"""Focus mode service."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any

from ..database import Database
from ..exceptions import FocusModeError
from ..focus_hosts_helper import (
    DEFAULT_HOSTS_PATH,
    SYSTEM_HELPER_PATH,
    HostsStatus,
    inspect_hosts_file,
    is_valid_domain,
)
from ..models import FocusStateSnapshot
from ..notifications import notify
from ..settings import SettingsService
from ..utils import json_dumps, parse_dt, poke_status_bar, remaining_seconds, to_iso, utc_now


class FocusService:
    STATE_KEY = "focus.current"

    def __init__(self, db: Database, settings: SettingsService) -> None:
        self.db = db
        self.settings = settings

    def _normalize_domain(self, value: str) -> str:
        domain = value.strip().lower()
        domain = re.sub(r"^https?://", "", domain)
        domain = domain.split("/", 1)[0]
        if not domain:
            raise FocusModeError("Domain cannot be empty")
        if not is_valid_domain(domain):
            raise FocusModeError(f"Not a valid domain: {value.strip()}")
        return domain

    def list_sites(self, *, enabled_only: bool = False) -> list[tuple[str, bool, str]]:
        sql = "SELECT domain, enabled, source FROM blocked_sites"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY source DESC, domain ASC"
        rows = self.db.fetchall(sql)
        return [(row["domain"], bool(row["enabled"]), row["source"]) for row in rows]

    def add_site(self, domain: str, *, enabled: bool = True, source: str = "user") -> None:
        value = self._normalize_domain(domain)
        self.db.execute(
            """
            INSERT INTO blocked_sites (domain, enabled, created_at, source)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(domain) DO UPDATE SET
                enabled = excluded.enabled,
                source = excluded.source
            """,
            (value, 1 if enabled else 0, to_iso(utc_now()), source),
        )
        self._reapply_active_sites()
        notify("Blocked site list updated", value, enabled=self.settings.get("notifications_enabled"))
        poke_status_bar()

    def update_site(
        self,
        domain: str,
        *,
        new_domain: str | None = None,
        enabled: bool | None = None,
    ) -> str:
        current_domain = self._normalize_domain(domain)
        row = self.db.fetchone(
            "SELECT domain, enabled, source FROM blocked_sites WHERE domain = ?",
            (current_domain,),
        )
        if not row:
            raise FocusModeError("Blocked site not found")

        next_domain = self._normalize_domain(new_domain) if new_domain is not None else current_domain
        next_enabled = row["enabled"] if enabled is None else (1 if enabled else 0)

        if next_domain != current_domain:
            exists = self.db.fetchone(
                "SELECT domain FROM blocked_sites WHERE domain = ?",
                (next_domain,),
            )
            if exists:
                raise FocusModeError("Target domain already exists")

        self.db.execute(
            """
            UPDATE blocked_sites
            SET domain = ?, enabled = ?
            WHERE domain = ?
            """,
            (next_domain, next_enabled, current_domain),
        )
        self._reapply_active_sites()
        notify(
            "Blocked site updated",
            f"{current_domain} -> {next_domain}",
            enabled=self.settings.get("notifications_enabled"),
        )
        poke_status_bar()
        return next_domain

    def remove_site(self, domain: str) -> None:
        value = self._normalize_domain(domain)
        self.db.execute("DELETE FROM blocked_sites WHERE domain = ?", (value,))
        self._reapply_active_sites()
        notify("Blocked site removed", value, enabled=self.settings.get("notifications_enabled"))
        poke_status_bar()

    def toggle_site(self, domain: str, enabled: bool) -> None:
        value = self._normalize_domain(domain)
        self.db.execute("UPDATE blocked_sites SET enabled = ? WHERE domain = ?", (1 if enabled else 0, value))
        self._reapply_active_sites()
        notify(
            "Blocked site toggled",
            f"{value}: {'enabled' if enabled else 'disabled'}",
            enabled=self.settings.get("notifications_enabled"),
        )
        poke_status_bar()

    def recover(self) -> FocusStateSnapshot:
        system = inspect_hosts_file(DEFAULT_HOSTS_PATH)
        raw = self._load_state()
        if raw and not system.readable:
            snapshot = self._snapshot_from_raw(raw)
            if snapshot.active:
                snapshot.system_consistent = False
                self._persist_snapshot(snapshot)
            return snapshot

        if raw and not system.active:
            self._close_active_session("System blocks were removed externally")
            poke_status_bar()
            return FocusStateSnapshot(active=False)

        if not raw and system.active:
            snapshot = FocusStateSnapshot(
                active=True,
                session_id=system.session_id or uuid.uuid4().hex[:12],
                strict_mode=system.strict,
                blocked_sites=system.sites,
                started_at=parse_dt(system.started_at),
                ends_at=None,
                recovered=True,
                system_consistent=True,
                auto_release=False,
            )
            self._persist_snapshot(snapshot)
            with self.db.connection() as conn:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO focus_sessions (
                        session_id, strict_mode, started_at, ends_at, active,
                        blocked_sites_json, auto_release, recovered, notes
                    ) VALUES (?, ?, ?, ?, 1, ?, 0, 1, ?)
                    """,
                    (
                        snapshot.session_id,
                        1 if snapshot.strict_mode else 0,
                        to_iso(snapshot.started_at or utc_now()),
                        None,
                        json.dumps(list(snapshot.blocked_sites)),
                        "Recovered from existing hosts markers",
                    ),
                )
            return snapshot

        snapshot = self.status(check_expiry=False)
        if snapshot.active:
            before = asdict(snapshot)
            snapshot.system_consistent = system.readable and system.active
            snapshot.blocked_sites = system.sites if system.sites else snapshot.blocked_sites
            # recover() runs on every bar refresh; only write when it matters.
            if asdict(snapshot) != before:
                self._persist_snapshot(snapshot)
        return snapshot

    def _helper_script(self) -> list[str]:
        # A root-owned copy installed by `install.sh --system-helper` is
        # preferred: sudoers can then allow it without a password, safely.
        if os.access(SYSTEM_HELPER_PATH, os.X_OK):
            return [str(SYSTEM_HELPER_PATH)]
        for name in ("omarchy-focus-hosts-helper", "clar-focus-hosts-helper"):
            helper = shutil.which(name)
            if helper:
                return [helper]
        helper_path = Path(__file__).resolve().parents[1] / "focus_hosts_helper.py"
        return [sys.executable, str(helper_path)]

    def _privilege_prefix(self, helper: list[str], *, interactive: bool) -> list[str]:
        """Pick how to become root for the hosts helper.

        Order: cached/passwordless sudo, a sudo prompt on a terminal, then a
        polkit dialog (Omarchy Shell ships an agent) when launched from the
        bar or a keybinding without a terminal.
        """
        if os.geteuid() == 0:
            return []
        probe = subprocess.run(["sudo", "-n", *helper, "status", "--json"], check=False, capture_output=True)
        if probe.returncode == 0 or not interactive:
            return ["sudo", "-n"]
        if sys.stdin.isatty():
            if subprocess.run(["sudo", "-v"], check=False).returncode != 0:
                raise FocusModeError("sudo authentication failed")
            return ["sudo", "-n"]
        if shutil.which("pkexec"):
            return ["pkexec"]
        raise FocusModeError("Root access needed: run from a terminal or install polkit (pkexec)")

    def _run_helper(
        self,
        *args: str,
        interactive: bool = True,
    ) -> HostsStatus:
        command = self._helper_script()
        if args and args[0] in {"clear", "status"} and "--json" not in args:
            args = (*args, "--json")
        command = [*self._privilege_prefix(command, interactive=interactive), *command]
        command.extend(args)
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if command[0] == "pkexec" and result.returncode in {126, 127}:
            # pkexec's codes for a dismissed dialog or a failed authentication.
            raise FocusModeError("Authentication cancelled; sites were not changed")
        if result.returncode != 0:
            stderr = (result.stderr or result.stdout).strip()
            raise FocusModeError(stderr or "Failed to update hosts file")
        payload = json.loads(result.stdout.strip() or "{}")
        return HostsStatus(
            active=bool(payload.get("active")),
            session_id=payload.get("session_id"),
            strict=bool(payload.get("strict")),
            started_at=payload.get("started_at"),
            owner=payload.get("owner"),
            sites=tuple(payload.get("sites", [])),
        )

    def _load_state(self) -> dict[str, Any] | None:
        row = self.db.get_state(self.STATE_KEY)
        return json.loads(row["value_json"]) if row else None

    def snapshot(self) -> FocusStateSnapshot:
        return self._snapshot_from_raw(self._load_state())

    def _snapshot_from_raw(self, raw: dict[str, Any] | None) -> FocusStateSnapshot:
        if not raw:
            return FocusStateSnapshot(active=False)
        return FocusStateSnapshot(
            active=bool(raw.get("active", False)),
            session_id=str(raw.get("session_id")) if raw.get("session_id") else None,
            strict_mode=bool(raw.get("strict_mode", False)),
            blocked_sites=tuple(raw.get("blocked_sites", [])),
            started_at=parse_dt(raw.get("started_at")),
            ends_at=parse_dt(raw.get("ends_at")),
            recovered=bool(raw.get("recovered", False)),
            system_consistent=bool(raw.get("system_consistent", True)),
            auto_release=bool(raw.get("auto_release", True)),
        )

    def _persist_snapshot(self, snapshot: FocusStateSnapshot) -> None:
        self.db.upsert_state(self.STATE_KEY, json_dumps(asdict(snapshot)))

    def _update_active_session_record(self, snapshot: FocusStateSnapshot) -> None:
        if not snapshot.session_id:
            return
        self.db.execute(
            """
            UPDATE focus_sessions
            SET blocked_sites_json = ?, ends_at = ?, strict_mode = ?, auto_release = ?
            WHERE session_id = ? AND active = 1
            """,
            (
                json.dumps(list(snapshot.blocked_sites)),
                to_iso(snapshot.ends_at),
                1 if snapshot.strict_mode else 0,
                1 if snapshot.auto_release else 0,
                snapshot.session_id,
            ),
        )

    def _reapply_active_sites(self, *, interactive: bool = True) -> None:
        snapshot = self.status(check_expiry=False)
        if not snapshot.active:
            return

        enabled_sites = [domain for domain, _, _ in self.list_sites(enabled_only=True)]
        if enabled_sites:
            session_id = snapshot.session_id or uuid.uuid4().hex[:12]
            status = self._run_helper(
                "apply",
                "--session-id",
                session_id,
                "--started-at",
                to_iso(snapshot.started_at) or "",
                *(("--strict",) if snapshot.strict_mode else ()),
                *enabled_sites,
                interactive=interactive,
            )
            snapshot.session_id = session_id
            snapshot.blocked_sites = status.sites or tuple(enabled_sites)
            snapshot.system_consistent = True
        else:
            self._run_helper("clear", interactive=interactive)
            snapshot.blocked_sites = ()
            snapshot.system_consistent = True

        self._persist_snapshot(snapshot)
        self._update_active_session_record(snapshot)
        poke_status_bar()

    def _close_active_session(self, note: str = "") -> None:
        raw = self._load_state()
        if not raw or not raw.get("session_id"):
            self.db.delete_state(self.STATE_KEY)
            return
        with self.db.connection() as conn:
            conn.execute(
                """
                UPDATE focus_sessions
                SET active = 0,
                    ended_actual_at = ?,
                    notes = TRIM(notes || '\n' || ?)
                WHERE session_id = ?
                """,
                (to_iso(utc_now()), note, raw["session_id"]),
            )
        self.db.delete_state(self.STATE_KEY)

    def status(self, *, check_expiry: bool = True) -> FocusStateSnapshot:
        snapshot = self._snapshot_from_raw(self._load_state())
        if snapshot.active and check_expiry and snapshot.ends_at and remaining_seconds(snapshot.ends_at) <= 0:
            if snapshot.auto_release:
                try:
                    return self.stop(force=True, interactive=False, reason="Session expired")
                except FocusModeError:
                    snapshot.system_consistent = inspect_hosts_file(DEFAULT_HOSTS_PATH).active
                    return snapshot
            snapshot.active = False
        return snapshot

    def start(
        self,
        *,
        minutes: int | None = None,
        strict_mode: bool | None = None,
        sites: list[str] | None = None,
        auto_release: bool | None = None,
    ) -> FocusStateSnapshot:
        current = self.recover()
        if current.active:
            raise FocusModeError("Focus mode is already active")

        strict_mode = self.settings.get("strict_mode_default") if strict_mode is None else strict_mode
        auto_release = self.settings.get("focus_auto_release") if auto_release is None else auto_release
        if strict_mode and not minutes:
            raise FocusModeError("Strict mode requires a timed session")
        site_list = sites or [domain for domain, _, _ in self.list_sites(enabled_only=True)]
        if not site_list:
            raise FocusModeError("No blocked sites configured")

        started_at = utc_now()
        ends_at = started_at + timedelta(minutes=minutes) if minutes else None
        session_id = uuid.uuid4().hex[:12]
        status = self._run_helper(
            "apply",
            "--session-id",
            session_id,
            "--started-at",
            to_iso(started_at) or "",
            *(("--strict",) if strict_mode else ()),
            *site_list,
            interactive=True,
        )
        snapshot = FocusStateSnapshot(
            active=True,
            session_id=session_id,
            strict_mode=strict_mode,
            blocked_sites=status.sites or tuple(site_list),
            started_at=started_at,
            ends_at=ends_at,
            recovered=False,
            system_consistent=True,
            auto_release=bool(auto_release),
        )
        with self.db.connection() as conn:
            conn.execute(
                """
                INSERT INTO focus_sessions (
                    session_id, strict_mode, started_at, ends_at,
                    active, blocked_sites_json, auto_release, recovered, notes
                ) VALUES (?, ?, ?, ?, 1, ?, ?, 0, '')
                """,
                (
                    session_id,
                    1 if strict_mode else 0,
                    to_iso(started_at),
                    to_iso(ends_at),
                    json.dumps(list(snapshot.blocked_sites)),
                    1 if auto_release else 0,
                ),
            )
        self._persist_snapshot(snapshot)
        notify(
            "Focus mode active",
            f"{len(snapshot.blocked_sites)} site(s) blocked",
            enabled=self.settings.get("notifications_enabled"),
        )
        poke_status_bar()
        return snapshot

    def stop(
        self,
        *,
        force: bool = False,
        interactive: bool = True,
        reason: str = "Focus mode disabled",
    ) -> FocusStateSnapshot:
        snapshot = self.recover()
        if not snapshot.active:
            try:
                self._run_helper("clear", interactive=interactive)
                poke_status_bar()
            except FocusModeError:
                pass
            return FocusStateSnapshot(active=False)
        if (
            snapshot.strict_mode
            and not force
            and snapshot.ends_at
            and remaining_seconds(snapshot.ends_at) > 0
        ):
            raise FocusModeError("Strict mode is active; session cannot be removed yet")
        self._run_helper("clear", interactive=interactive)
        self._close_active_session(reason)
        notify("Focus mode off", reason, enabled=self.settings.get("notifications_enabled"))
        poke_status_bar()
        return FocusStateSnapshot(active=False)

    def toggle(self) -> FocusStateSnapshot:
        snapshot = self.status()
        return self.stop() if snapshot.active else self.start()
