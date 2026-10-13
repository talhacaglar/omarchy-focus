"""Desktop notifications.

Bodies often carry task titles, so they are sent straight to the session
bus. Arguments of a ``notify-send`` process are readable by every local user
through /proc, so the fallback passes only the fixed summary line.
"""

from __future__ import annotations

import shutil
import subprocess

from .paths import APP_NAME

_URGENCY = {"low": 0, "normal": 1, "critical": 2}


def _send_dbus(title: str, body: str, urgency: str) -> bool:
    """Call org.freedesktop.Notifications.Notify; False if that is not possible."""
    try:
        from jeepney import DBusAddress, new_method_call
        from jeepney.io.blocking import open_dbus_connection

        service = DBusAddress(
            "/org/freedesktop/Notifications",
            bus_name="org.freedesktop.Notifications",
            interface="org.freedesktop.Notifications",
        )
        message = new_method_call(
            service,
            "Notify",
            "susssasa{sv}i",
            (APP_NAME, 0, "", title, body, [], {"urgency": ("y", _URGENCY.get(urgency, 1))}, -1),
        )
        with open_dbus_connection(bus="SESSION") as connection:
            connection.send_and_get_reply(message, timeout=2)
    except Exception:
        return False
    return True


def notify(title: str, body: str = "", *, urgency: str = "normal", enabled: bool = True) -> None:
    if not enabled or _send_dbus(title, body, urgency):
        return
    if shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", "-a", APP_NAME, "-u", urgency, title],
            check=False,
            capture_output=True,
        )
