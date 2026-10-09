#!/usr/bin/env bash
# Omarchy Focus installer. Safe to re-run: it upgrades in place.
#
#   ./install.sh                 install or upgrade for this user
#   ./install.sh --editable      install from this checkout in development mode
#   ./install.sh --system-helper also install a root-owned hosts helper and a
#                                sudoers rule, so the site guard never prompts
#   ./install.sh --no-bar        leave the bar layout alone
#   ./install.sh --uninstall     remove commands, widget and helper (keeps data)

set -euo pipefail

PROJECT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="$HOME/.local/bin"
APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/omarchy-focus"
VENV_DIR="$APP_DIR/venv"
LEGACY_VENV_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/clar-focus/venv"
OMARCHY_DIR="$HOME/.config/omarchy"
SYSTEM_HELPER="/usr/local/libexec/omarchy-focus-hosts-helper"
SUDOERS_FILE="/etc/sudoers.d/omarchy-focus"

COMMANDS=(omarchy-focus omarchy-focus-hosts-helper clar-focus clar-focus-hosts-helper focus focus-indicator)
BAR_ALIASES=(omarchy-focus-bar omarchy-focus-waybar clar-focus-bar clar-focus-waybar)

editable=0 system_helper=0 bar=1 uninstall=0
for arg in "$@"; do
  case "$arg" in
    --editable) editable=1 ;;
    --system-helper) system_helper=1 ;;
    --no-bar) bar=0 ;;
    --uninstall) uninstall=1 ;;
    -h | --help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

say() { printf '\033[1;33m[omarchy-focus]\033[0m %s\n' "$*"; }
note() { printf '  → %s\n' "$*"; }

have_omarchy_shell() { [[ -d $OMARCHY_DIR ]] && command -v omarchy-shell >/dev/null 2>&1; }

if (( uninstall )); then
  say "Removing commands, widget and helper (your tasks and history stay in $APP_DIR)"
  if [[ -x $BIN_DIR/omarchy-focus ]]; then
    "$BIN_DIR/omarchy-focus" widget remove | while IFS= read -r line; do note "$line"; done
  fi
  for name in "${COMMANDS[@]}" "${BAR_ALIASES[@]}"; do rm -f -- "$BIN_DIR/$name"; done
  rm -rf -- "$VENV_DIR"
  if [[ -e $SYSTEM_HELPER || -e $SUDOERS_FILE ]]; then
    sudo rm -f -- "$SYSTEM_HELPER" "$SUDOERS_FILE"
  fi
  exit 0
fi

PYTHON="${PYTHON:-python3}"
if ! "$PYTHON" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
  echo "Python 3.12 or newer is required (found: $("$PYTHON" --version 2>&1))." >&2
  exit 1
fi

say "Installing into $VENV_DIR"
mkdir -p "$BIN_DIR" "$APP_DIR"
[[ -x $VENV_DIR/bin/python ]] || "$PYTHON" -m venv "$VENV_DIR"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
if (( editable )); then
  "$VENV_DIR/bin/pip" install --quiet -e "$PROJECT_DIR"
else
  "$VENV_DIR/bin/pip" install --quiet --force-reinstall --no-deps "$PROJECT_DIR"
  "$VENV_DIR/bin/pip" install --quiet "$PROJECT_DIR"
fi

for name in "${COMMANDS[@]}"; do
  ln -sfn "$VENV_DIR/bin/$name" "$BIN_DIR/$name"
done
install -m 755 "$PROJECT_DIR/examples/omarchy-shell/omarchy-focus-bar.sh" "$BIN_DIR/omarchy-focus-bar"
for name in "${BAR_ALIASES[@]:1}"; do
  ln -sfn "$BIN_DIR/omarchy-focus-bar" "$BIN_DIR/$name"
done
note "Commands: omarchy-focus (alias: clar-focus), omarchy-focus-bar"

# Earlier releases (named Clar Focus) kept their virtualenv next to the
# database. The database is migrated on first run; the old venv is dead weight.
if [[ -d $LEGACY_VENV_DIR ]]; then
  rm -rf -- "$LEGACY_VENV_DIR"
  note "Removed old Clar Focus virtualenv (data kept in ${LEGACY_VENV_DIR%/venv})"
fi

# First run migrates data from older releases and creates the database.
"$BIN_DIR/omarchy-focus" status >/dev/null

if (( bar )) && have_omarchy_shell; then
  "$BIN_DIR/omarchy-focus" widget install | while IFS= read -r line; do note "$line"; done
elif (( bar )); then
  note "Omarchy Shell not found. For Waybar see examples/waybar/."
fi

if (( system_helper )); then
  say "Installing root-owned hosts helper (asks for your password once)"
  tmp="$(mktemp)"
  { echo '#!/usr/bin/python3 -I'; tail -n +1 "$PROJECT_DIR/src/omarchy_focus/focus_hosts_helper.py"; } > "$tmp"
  sudo install -D -o root -g root -m 755 "$tmp" "$SYSTEM_HELPER"
  rm -f -- "$tmp"
  rule="$(id -un) ALL=(root) NOPASSWD: $SYSTEM_HELPER"
  tmp="$(mktemp)"
  printf '# Omarchy Focus: let %s toggle the site guard without a password.\n%s\n' "$(id -un)" "$rule" > "$tmp"
  if sudo visudo -cqf "$tmp"; then
    sudo install -o root -g root -m 440 "$tmp" "$SUDOERS_FILE"
    note "Site guard now starts and auto-releases without prompts"
  else
    echo "visudo rejected the generated rule; nothing installed." >&2
  fi
  rm -f -- "$tmp"
fi

echo
say "Done. Try:"
note "omarchy-focus            open the app"
note "omarchy-focus stats      heatmap and peak hours in your terminal"
if (( bar )) && have_omarchy_shell; then
  note "Bar: click = panel · right-click = start/pause · middle-click = site guard"
  note "Keybinding (~/.config/hypr/bindings.lua):"
  note "  o.bind(\"SUPER + ALT + F\", \"Focus panel\", \"omarchy-shell omarchy-focus toggle\")"
fi
(( system_helper )) || note "Optional: ./install.sh --system-helper for prompt-free site blocking"
