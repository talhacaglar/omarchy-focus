# Omarchy Focus: technical reference

## Layout

```text
src/omarchy_focus/
├── cli.py                 # argparse entry point (omarchy-focus, clar-focus)
├── bar.py                 # status --json payload for the widget, bar/waybar text
├── charts.py              # heatmap, hour histogram and bars for CLI + TUI
├── widget.py              # omarchy-focus widget install|remove
├── shell_widget/          # the Omarchy Shell plugin (QML), shipped in the wheel
│   ├── manifest.json
│   ├── BarWidget.qml      # pill, data loading, inotify watch, IPC
│   ├── FocusPanel.qml     # popup: ring, controls, tasks, goal, 7 days, heatmap
│   └── Model.js           # pure helpers, unit-tested with node
├── database.py            # SQLite + versioned migrations
├── focus_hosts_helper.py  # the only code that runs as root
├── paths.py               # XDG paths, migration from Clar Focus
├── services/              # tasks, pomodoro, focus guard, stats
└── tui/                   # Textual app
```

## How the bar widget stays cheap

1. Every state change (CLI, TUI, timer) calls `poke_status_bar()`, which writes `$XDG_RUNTIME_DIR/omarchy-focus.changed`.
2. The widget watches that file (`FileView` + inotify) and runs `omarchy-focus status --json` once, debounced.
3. The JSON carries `ends_at_ms`, so the countdown and progress ring tick locally in QML.
4. When a countdown reaches zero, the widget refreshes once so the CLI can record the session and queue the break. A 30 s heartbeat (configurable) covers day rollover.

Refreshing is read-only: the countdown is derived from `ends_at` instead of being saved on every tick, and the database skips its DDL when `PRAGMA user_version` is current.

| | 0.1 (command widget) | 0.2 (native widget) |
| --- | --- | --- |
| Process spawns while idle | 30 / min (`bash -l` → bash → Python) | 2 / min |
| Cost per spawn | ~140 ms | ~80 ms |
| SQLite writes per refresh | several | none |
| Latency after start/stop | up to 2 s | instant |

### Widget settings

Set these on the widget's entry in `~/.config/omarchy/shell.json`:

```json
{ "id": "omarchy-focus", "showIdleCount": true, "refreshIntervalSec": 30, "guardMinutes": 50,
  "command": "/home/you/.local/bin/omarchy-focus" }
```

IPC: `omarchy-shell omarchy-focus toggle|open|close|refresh`.

### `status --json`

Schema `1`. Keys: `pomodoro` (`phase`, `type`, `remaining_seconds`, `total_seconds`, `ends_at_ms`, `task_id`, `task_title`, `cycle`), `pending_break`, `focus` (`active`, `strict`, `sites`, `ends_at_ms`, `consistent`), `stats` (`today_*`, `goal_minutes`, `week_focus_minutes`, `streak_days`, `completion_rate`, `week[]`), `heatmap[]` (84 days), `next_tasks[]`, `settings`. Keys from 0.1 are kept.

## CLI

```bash
omarchy-focus                         # TUI (same as: omarchy-focus tui)
omarchy-focus status [--json]
omarchy-focus stats [--json | --md] [--weeks 17]

omarchy-focus add-task "Title" --priority high --tags "work docs" --estimate 50 --due "2026-10-20 15:00"
omarchy-focus tasks list [--today] [--completed] [--search text]
omarchy-focus tasks edit 3 --status in_progress
omarchy-focus tasks done 3 | delete 3

omarchy-focus start [--task-id 3] [--minutes 25] [--focus | --no-focus] [--strict]
omarchy-focus pause | resume | stop | toggle
omarchy-focus break [start | skip] [--minutes 15]

omarchy-focus focus on --minutes 50 [--strict] [--site x.com]
omarchy-focus focus off [--force] | status [--json] | recover
omarchy-focus focus add-site youtube.com | remove-site x.com | enable-site | disable-site

omarchy-focus settings show [--json]
omarchy-focus settings set daily_goal_minutes 180
omarchy-focus widget install | remove | path
```

### Settings

| Key | Default | Meaning |
| --- | --- | --- |
| `pomodoro_work_minutes` | 50 | Work session length |
| `pomodoro_short_break_minutes` | 10 | Short break |
| `pomodoro_long_break_minutes` | 25 | Long break |
| `pomodoro_long_break_every` | 4 | Long break after this many sessions in a row (a 2 h gap starts a new cycle) |
| `daily_goal_minutes` | 150 | Goal for the progress bar, ring and heatmap levels |
| `focus_on_pomodoro_start` | false | Start the site guard with every session |
| `strict_mode_default` | false | Guard can't be turned off before it ends |
| `focus_auto_release` | true | Unblock sites when a timed guard ends |
| `open_app_on_complete` | false | Raise the TUI when a session ends |
| `notifications_enabled` | true | Desktop notifications |

## TUI keys

`s` start/stop · `p` pause/resume · `m` site guard · `a` add · `e` edit · `x` done · `d` delete · `/` search · `f` filter · `b` blocked sites · `g` Now · `t` Tasks · `i` Statistics · `,` Settings · `F2` light/dark · `?` help · `q` quit

## Site guard

Blocked domains go into a marked block in `/etc/hosts`, pointed at `0.0.0.0` and `::1`:

```text
# >>> OMARCHY_FOCUS START
# OMARCHY_FOCUS_META {"owner": "...", "session_id": "...", "started_at": "...", "strict": true}
0.0.0.0 reddit.com www.reddit.com
::1 reddit.com www.reddit.com
# <<< OMARCHY_FOCUS END
```

- Only the marked block is ever rewritten, atomically, preserving the file's mode and owner. A truncated block (start marker without end) is left alone.
- If the app dies, the next run reconciles SQLite with the markers in either direction (`focus recover`).
- Strict mode needs a timed session; `focus off` is refused until it ends (`--force` overrides).

### Privileges

The app never edits `/etc/hosts` itself; it runs `omarchy-focus-hosts-helper` as root. In order, it tries cached or passwordless `sudo`, a `sudo` prompt when it has a terminal, then `pkexec`, which shows Omarchy Shell's polkit dialog when launched from the bar.

`./install.sh --system-helper` installs a root-owned copy at `/usr/local/libexec/omarchy-focus-hosts-helper` and a sudoers rule for it, so the guard starts and auto-releases without prompts. A root-owned copy matters: a sudoers rule pointing at a file in your home directory would let any process running as you become root.

The helper is standard-library only and refuses anything it would not write itself: domains must be valid RFC 1123 hostnames, session ids are `[A-Za-z0-9_-]`, and `--hosts-file` is rejected when running under sudo or pkexec.

## Data

| What | Where |
| --- | --- |
| Database | `~/.local/share/omarchy-focus/focus.db` |
| Change stamp | `$XDG_RUNTIME_DIR/omarchy-focus.changed` |
| Widget | `~/.config/omarchy/plugins/omarchy-focus/` |
| Virtualenv (install.sh) | `~/.local/share/omarchy-focus/venv` |

Coming from Clar Focus: on first run the database is copied (via SQLite's backup API, so WAL contents come along) from `~/.local/share/clar-focus/`, and config from `~/.config/clar-focus/`. The originals stay in place.

## Development

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/pytest                      # includes the QML model tests when node is installed

# Demo data and screenshots, isolated from your real database:
export XDG_DATA_HOME=/tmp/of-demo
python scripts/demo_data.py
python scripts/tui_screenshots.py screenshots/
omarchy-focus widget install          # then set "command" on the widget to a wrapper that exports XDG_DATA_HOME
```

Editing the QML in `~/.config/omarchy/plugins/omarchy-focus/` hot-reloads. The shell caches files it has already compiled, so after renaming a QML file or changing `Model.js`, run `omarchy restart shell`.
