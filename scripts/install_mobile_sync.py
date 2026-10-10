#!/usr/bin/env python3
"""Install the opt-in personal LAN sync user service with an explicit LAN IP."""
from __future__ import annotations

import argparse
import ipaddress
import os
import subprocess
import sys
from pathlib import Path

from omarchy_focus.database import Database
from omarchy_focus.mobile_sync import prepare_pairing
from omarchy_focus.paths import CONFIG_DIR


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="This computer's LAN IPv4 address")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    address = ipaddress.IPv4Address(args.host)
    if not address.is_private or address.is_unspecified or address.is_multicast:
        parser.error("Use a specific private LAN IPv4 address")
    if not 1024 <= args.port <= 65535:
        parser.error("Port must be between 1024 and 65535")
    db = Database()
    db.initialize()
    pairing = prepare_pairing(db, CONFIG_DIR / "mobile-sync", str(address), args.port)
    config_root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    service = config_root / "systemd/user/clar-focus-mobile.service"
    service.parent.mkdir(parents=True, exist_ok=True)
    # systemd uses percent specifiers, not shell expansion. Quote the executable.
    executable = sys.executable.replace("%", "%%").replace('"', '\\"')
    content = f'''[Unit]
Description=Clar Focus personal Android LAN sync
After=network.target

[Service]
Type=simple
ExecStart="{executable}" -m omarchy_focus.cli mobile serve --host {address} --port {args.port}
Restart=on-failure
RestartSec=10
UMask=0077
NoNewPrivileges=true

[Install]
WantedBy=default.target
'''
    if service.exists() and service.read_text() != content:
        backup = service.with_suffix(".service.bak")
        if backup.exists():
            parser.error(f"Preserve or remove the existing service backup first: {backup}")
        backup.write_text(service.read_text())
    service.write_text(content)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "--user", "enable", "clar-focus-mobile.service"], check=True)
    subprocess.run(["systemctl", "--user", "restart", "clar-focus-mobile.service"], check=True)
    print(f"Service: {service}")
    print(f"Private pairing file: {pairing}")
    print(f"Listener: https://{address}:{args.port}")


if __name__ == "__main__":
    main()
