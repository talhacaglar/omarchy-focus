#!/usr/bin/env bash
# Fallback bar helper for Omarchy Shell's generic "command" widget and for
# Waybar. Omarchy installs normally use the native widget in omarchy-plugin/
# instead, which needs no polling.

set -euo pipefail

case "${1:-status}" in
  status)
    exec omarchy-focus bar
    ;;
  open)
    if omarchy-focus raise >/dev/null 2>&1; then
      exit 0
    fi
    exec omarchy-launch-or-focus-tui omarchy-focus tui
    ;;
  toggle-pomodoro)
    exec omarchy-focus toggle
    ;;
  toggle-focus)
    # The CLI asks for root through polkit when there is no terminal.
    if omarchy-focus focus status | grep -q "Focus ON"; then
      exec omarchy-focus focus off
    fi
    exec omarchy-focus focus on --minutes 50
    ;;
  *)
    echo "Usage: $0 {status|open|toggle-pomodoro|toggle-focus}" >&2
    exit 1
    ;;
esac
