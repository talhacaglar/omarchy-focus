# Changelog

## 0.2.4 — 2026-10-13

### Security
- Upgrading from Clar Focus left the old `clar-focus` database, its WAL files and directories readable by other local users after their data was copied to the new private location. Every start now locks the legacy copy down (`0700` directories, `0600` database files), including installs migrated by 0.2.0–0.2.3. The copy is kept so a downgrade still finds its data.
- The migrated config directory took the legacy directory's `0755` mode from `shutil.copytree`; it and its files are now private as well.
- Notifications passed task titles to `notify-send` as process arguments, which every local user can read from `/proc`. They are now sent directly over the session D-Bus (new dependency: `jeepney`). Without D-Bus the `notify-send` fallback shows only the fixed summary line, never the body.
- Without `XDG_RUNTIME_DIR` (cron, `su`, ssh without pam_systemd) the runtime files fell back to `/tmp/<uid>`, which another user could create first and fill with symlinks, so opening the TUI could truncate a file of the victim's choosing. The fallback is now `/run/user/<uid>` only when it is ours and private, else `~/.cache/omarchy-focus/run`.
- The database directory is created `0700` even when the database is opened before the app directories are set up.

## 0.2.3 — 2026-10-10

### Security
- Task data was world-readable on systems with the common umask `022`: the data directory was created `0755` and `focus.db` `0644`, so other local users could read task titles and descriptions. Data, config, state and cache directories are now `0700`, the database and its WAL files `0600`, and existing installs are tightened on the next run. The runtime stamp, lock and window files also live in `0700` directories. Reported during the Omarchy plugin marketplace review.

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
