"""Authenticated, pinned-TLS LAN task sync. No cloud account or external service.

An exchange is a single SQLite transaction. Revisions detect concurrent edits;
durable receipts make retries safe when a response is lost. Deleted identities
remain as tombstones so an offline phone cannot resurrect a removed task.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .database import Database
from .utils import to_iso, utc_now

MAX_BODY = 1024 * 1024
ID_PATTERN = re.compile(r"[a-zA-Z0-9-]{16,64}\Z")
FIELDS = {"title", "description", "priority", "status"}


def _validate_operation(op: Any) -> dict:
    if not isinstance(op, dict) or set(op) != {"id", "uid", "base", "kind", "fields"}:
        raise ValueError("Invalid operation")
    if any(not isinstance(op[key], str) or not ID_PATTERN.fullmatch(op[key]) for key in ("id", "uid")):
        raise ValueError("Invalid operation identity")
    if type(op["base"]) is not int or op["base"] < 0 or op["kind"] not in ("upsert", "delete"):
        raise ValueError("Invalid operation revision or kind")
    fields = op["fields"]
    if not isinstance(fields, dict) or not set(fields) <= FIELDS:
        raise ValueError("Invalid task fields")
    if op["kind"] == "delete" and fields:
        raise ValueError("Delete cannot contain fields")
    for key, value in fields.items():
        if not isinstance(value, str):
            raise ValueError("Task fields must be strings")
        if key == "title" and (not value.strip() or len(value) > 500):
            raise ValueError("Title must contain 1–500 characters")
        if key == "description" and len(value) > 20000:
            raise ValueError("Description too long")
        if key == "priority" and value not in ("low", "medium", "high"):
            raise ValueError("Invalid priority")
        if key == "status" and value not in ("pending", "in_progress", "done", "archived"):
            raise ValueError("Invalid status")
    return op


def _snapshot(conn: sqlite3.Connection) -> list[dict]:
    return [dict(row) for row in conn.execute("""
        SELECT s.uid, s.version, s.deleted, t.title, t.description, t.priority,
               t.status, t.tags_json, t.estimated_minutes, t.due_at, t.updated_at
        FROM sync_tasks s LEFT JOIN tasks t ON t.id = s.task_id ORDER BY s.uid
    """)]


def exchange(db: Database, payload: Any) -> dict:
    if not isinstance(payload, dict) or payload.get("protocol") != 1:
        raise ValueError("Unsupported sync protocol")
    operations = payload.get("operations")
    if not isinstance(operations, list) or len(operations) > 500:
        raise ValueError("At most 500 operations per exchange")
    operations = [_validate_operation(op) for op in operations]
    if len({op["uid"] for op in operations}) != len(operations):
        raise ValueError("Only one operation per task per exchange")
    accepted, conflicts = [], []
    with db.connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        identity = conn.execute("SELECT id FROM sync_identity").fetchone()[0]
        if payload.get("dataset") != identity:
            raise ValueError("Different desktop database; pair again")
        for op in operations:
            canonical = json.dumps(op, sort_keys=True, separators=(",", ":"))
            receipt = conn.execute("SELECT payload FROM sync_receipts WHERE operation_id = ?", (op["id"],)).fetchone()
            if receipt:
                if receipt[0] != canonical:
                    raise ValueError("Operation ID reused with different content")
                accepted.append(op["id"])
                continue
            record = conn.execute("SELECT * FROM sync_tasks WHERE uid = ?", (op["uid"],)).fetchone()
            if (record and (record["version"] != op["base"] or record["deleted"])) or (not record and op["base"] != 0):
                conflicts.append(op["uid"])
                continue
            now = to_iso(utc_now())
            if op["kind"] == "delete":
                if record:
                    conn.execute("DELETE FROM tasks WHERE id = ?", (record["task_id"],))
                else:
                    conn.execute("INSERT INTO sync_tasks(uid, version, deleted) VALUES (?, 1, 1)", (op["uid"],))
            else:
                fields = dict(op["fields"])
                if not record and "title" not in fields:
                    raise ValueError("New tasks need a title")
                if "title" in fields:
                    fields["title"] = fields["title"].strip()
                if not record:
                    cursor = conn.execute("""INSERT INTO tasks(title, description, priority, status,
                        tags_json, created_at, updated_at) VALUES (?, ?, ?, ?, '[]', ?, ?)""",
                        (fields["title"], fields.get("description", ""), fields.get("priority", "medium"),
                         fields.get("status", "pending"), now, now))
                    task_id = cursor.lastrowid
                    conn.execute("UPDATE sync_tasks SET uid = ? WHERE task_id = ?", (op["uid"], task_id))
                else:
                    task_id = record["task_id"]
                fields["updated_at"] = now
                if "status" in fields:
                    fields["completed_at"] = now if fields["status"] == "done" else None
                    fields["archived_at"] = now if fields["status"] == "archived" else None
                # Field names are restricted above; values are always parameters.
                assignments = ", ".join(f"{key} = ?" for key in fields)
                conn.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", (*fields.values(), task_id))
            conn.execute("INSERT INTO sync_receipts VALUES (?, ?)", (op["id"], canonical))
            accepted.append(op["id"])
        return {"protocol": 1, "dataset": identity, "accepted": accepted,
                "conflicts": conflicts, "tasks": _snapshot(conn)}


def prepare_pairing(db: Database, directory: Path, host: str, port: int) -> Path:
    """Generate credentials locally, never embed them in the APK or repository."""
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    key, cert, token_path = (directory / name for name in ("key.pem", "cert.pem", "token"))
    if not key.exists() or not cert.exists():
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:3072", "-nodes",
                        "-keyout", str(key), "-out", str(cert), "-days", "3650",
                        "-subj", "/CN=Clar Focus personal sync"], check=True, capture_output=True)
        key.chmod(0o600)
    if not token_path.exists():
        token_path.write_text(secrets.token_urlsafe(32))
        token_path.chmod(0o600)
    der = ssl.PEM_cert_to_DER_cert(cert.read_text())
    identity_row = db.fetchone("SELECT id FROM sync_identity")
    if identity_row is None:
        raise ValueError("Initialize the database before pairing")
    identity = identity_row[0]
    pairing = {"protocol": 1, "url": f"https://{host}:{port}",
               "fingerprint": hashlib.sha256(der).hexdigest(),
               "token": token_path.read_text().strip(), "dataset": identity}
    path = directory / "clar-focus-pairing.json"
    path.write_text(json.dumps(pairing, indent=2) + "\n")
    path.chmod(0o600)
    return path


def make_server(db: Database, directory: Path, host: str, port: int) -> HTTPServer:
    token = (directory / "token").read_text().strip()
    if len(token) < 32:
        raise ValueError("Invalid pairing token")

    class Handler(BaseHTTPRequestHandler):
        def setup(self) -> None:
            self.request.settimeout(10)
            super().setup()

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Never log credentials, task contents or client-controlled URLs.

        def respond(self, status: int, payload: dict) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            auth = self.headers.get("Authorization", "")
            if not hmac.compare_digest(auth.encode(), ("Bearer " + token).encode()):
                self.respond(401, {"error": "Pairing required"})
                return
            if self.path != "/v1/exchange":
                self.respond(404, {"error": "Not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or not 0 < length <= MAX_BODY:
                    raise ValueError("Invalid request size")
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError("Incomplete request")
                result = exchange(db, json.loads(body))
            except (ValueError, UnicodeError) as exc:
                self.respond(400, {"error": str(exc)})
                return
            except sqlite3.Error:
                self.respond(503, {"error": "Database busy; retry later"})
                return
            self.respond(200, result)

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(directory / "cert.pem", directory / "key.pem")

    class TLSServer(HTTPServer):
        def get_request(self):
            sock, address = super().get_request()
            sock.settimeout(10)
            try:
                return context.wrap_socket(sock, server_side=True), address
            except Exception:
                sock.close()
                raise

    return TLSServer((host, port), Handler)
