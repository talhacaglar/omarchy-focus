# Changelog

## 0.2.2 — 2026-10-10

### Fixed
- The TUI could raise `NoMatches` when a refresh timer fired before the screen was composed or while it was closing (rare, seen as a flaky test).

## 0.2.1 — 2026-10-10

### Fixed
- The bar widget looked for the CLI only in `~/.local/bin`, so it failed on AUR (`/usr/bin`) installs. It now resolves `omarchy-focus` through a login shell's PATH.

## 0.2.0 — 2026-10-09

Renamed from **Clar Focus** to **Omarchy Focus**. Data migrates automatically and the `clar-focus` command remains as an alias.

### Added
- Native Omarchy Shell bar widget with a popup: progress ring, pause/resume/stop, break controls, site guard, click-to-start task queue, daily goal, 7-day bars and a 12-week heatmap. Follows the Omarchy theme. IPC: `omarchy-shell omarchy-focus toggle`.
- `omarchy-focus widget install|remove`, so AUR and pip installs can set up the bar.
- `omarchy-focus stats` report with a GitHub-style heatmap, peak focus hours and session completion rate. The same charts are in the TUI Statistics view.
- `daily_goal_minutes` setting, shown in the bar tooltip, TUI, widget and heatmap levels.
- `omarchy-focus break start|skip`, `--version`.
- Polkit (`pkexec`) prompt for the site guard when launched without a terminal, and `install.sh --system-helper` for a root-owned helper with a passwordless sudoers rule.
- `install.sh --editable`, `--no-bar`, `--uninstall`.

### Changed
- The bar updates via an inotify change stamp instead of a 2-second poll: about 25× fewer process spawns while idle, with no database writes on refresh.
- The TUI no longer pops up when a session ends (opt in with `open_app_on_complete`).
- "Up next" and the Now view only list open tasks, with in-progress tasks first.
- Waybar output carries specific classes (`pomodoro`, `break`, `paused`, `focus`) so the shipped CSS applies.

### Fixed
- Long breaks were never scheduled; `pomodoro_long_break_every` is now honoured.
- Paused time was counted as focus time.
- Deleting a default blocked site re-added it on the next start.
- Foreign keys were only enforced during setup, so deleting a task didn't detach its sessions.
- Completed sessions recorded the time they were noticed instead of their planned end.
- The guard showed "0 sites" while off.

### Security
- The root hosts helper validates every domain, session id and timestamp, and refuses `--hosts-file` under sudo or pkexec. Before, a crafted site name could inject arbitrary lines into `/etc/hosts`.

## 0.1.0

First release as Clar Focus: Textual TUI, SQLite tasks, pomodoro timer, `/etc/hosts` site blocking and an Omarchy bar command widget.
