"""Terminal charts shared by the CLI and the TUI.

Each chart is built once as rows of ``(glyph, level)`` cells and then
rendered either as ANSI (CLI), Rich markup (TUI) or plain text (pipes).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

# Empty → goal reached. Warm gold ramp matching the TUI's midnight-gold theme.
HEAT_COLORS = ("#2b313d", "#5c4a1f", "#8a6d24", "#b8984e", "#f6e4b2")
HEAT_ANSI = (238, 94, 136, 178, 223)
HEAT_PLAIN = "·░▒▓█"
BLOCKS = "▁▂▃▄▅▆▇█"
WEEKDAY_LABELS = ("Mon", "", "Wed", "", "Fri", "", "Sun")

Cell = tuple[str, int]


def heat_level(minutes: int, goal: int) -> int:
    """0 for no focus, then quarters of the daily goal, 4 once it is met."""
    if minutes <= 0:
        return 0
    goal = max(goal, 1)
    if minutes >= goal:
        return 4
    return min(3, 1 + int(3 * minutes / goal))


def heatmap_rows(days: Sequence[tuple[str, int]], goal: int) -> tuple[list[str], list[list[Cell | None]]]:
    """Lay daily totals out GitHub-style: one column per week, Monday on top.

    Returns month labels (one per column, blank unless a month starts) and
    seven rows of cells. Days before the first entry are ``None``.
    """
    if not days:
        return [], [[] for _ in range(7)]
    first = date.fromisoformat(days[0][0])
    lead = first.weekday()
    padded: list[tuple[str, int] | None] = [None] * lead + list(days)
    columns = (len(padded) + 6) // 7
    rows: list[list[Cell | None]] = [[] for _ in range(7)]
    months: list[str] = []
    last_month = None
    for col in range(columns):
        label = ""
        for row in range(7):
            index = col * 7 + row
            item = padded[index] if index < len(padded) else None
            if item is None:
                rows[row].append(None)
                continue
            day = date.fromisoformat(item[0])
            if day.month != last_month and (day.day <= 7 or last_month is None):
                label = day.strftime("%b")
                last_month = day.month
            rows[row].append(("■", heat_level(item[1], goal)))
        months.append(label)
    return months, rows


def _month_line(months: list[str], cell_width: int) -> str:
    line = ""
    for col, label in enumerate(months):
        target = col * cell_width
        if label and len(line) <= target:
            line = line.ljust(target) + label
    return line


def render_heatmap(days: Sequence[tuple[str, int]], goal: int, *, style: str = "plain") -> str:
    """Render a heatmap. ``style`` is ``plain``, ``ansi`` or ``rich``."""
    months, rows = heatmap_rows(days, goal)
    gutter = 4
    lines = [" " * gutter + _month_line(months, 2)]
    for row_index, row in enumerate(rows):
        parts = [f"{WEEKDAY_LABELS[row_index]:<{gutter}}"]
        for cell in row:
            if cell is None:
                parts.append("  ")
                continue
            _, level = cell
            if style == "ansi":
                parts.append(f"\x1b[38;5;{HEAT_ANSI[level]}m■\x1b[0m ")
            elif style == "rich":
                parts.append(f"[{HEAT_COLORS[level]}]■[/] ")
            else:
                parts.append(HEAT_PLAIN[level] + " ")
        lines.append("".join(parts).rstrip())
    legend_cells = []
    for level in range(5):
        if style == "ansi":
            legend_cells.append(f"\x1b[38;5;{HEAT_ANSI[level]}m■\x1b[0m")
        elif style == "rich":
            legend_cells.append(f"[{HEAT_COLORS[level]}]■[/]")
        else:
            legend_cells.append(HEAT_PLAIN[level])
    lines.append(" " * gutter + "less " + " ".join(legend_cells) + f"  more  ·  brightest = {goal}m goal")
    return "\n".join(lines)


def render_hours(hours: Sequence[int], *, style: str = "plain") -> str:
    """24 vertical bars for focus by hour of day, with a time axis."""
    top = max(hours) if hours else 0
    if top <= 0:
        bars = BLOCKS[0] * 24
    else:
        bars = "".join(BLOCKS[min(7, round(value / top * 7))] if value else " " for value in hours)
    if style == "rich":
        bars = f"[{HEAT_COLORS[3]}]{bars}[/]"
    axis = "0     6     12    18   23"
    return f"{bars}\n{axis}"


def week_columns(values: Sequence[int]) -> str:
    """Rich-markup bars two cells wide, spaced to sit above two-letter day labels."""
    top = max(values) if values else 0
    cells = []
    for value in values:
        block = BLOCKS[min(7, round(value / top * 7))] if top > 0 and value > 0 else BLOCKS[0]
        color = HEAT_COLORS[3] if value > 0 else HEAT_COLORS[0]
        cells.append(f"[{color}]{block * 2}[/]")
    return "  ".join(cells)


def peak_window(hours: Sequence[int], width: int = 2) -> tuple[int, int] | None:
    """The busiest ``width``-hour window as ``(start_hour, minutes)``."""
    if not hours or max(hours) <= 0:
        return None
    best = max(range(24), key=lambda start: sum(hours[(start + i) % 24] for i in range(width)))
    return best, sum(hours[(best + i) % 24] for i in range(width))


def color_bar(value: int, maximum: int, width: int = 14) -> str:
    """Rich-markup horizontal bar: gold fill on a dim track."""
    maximum = max(maximum, 1)
    filled = min(width, round(width * value / maximum))
    if value > 0:
        filled = max(filled, 1)
    return f"[{HEAT_COLORS[3]}]{'━' * filled}[/][{HEAT_COLORS[0]}]{'━' * (width - filled)}[/]"


def goal_bar(minutes: int, goal: int, width: int = 20) -> str:
    goal = max(goal, 1)
    filled = min(width, round(width * minutes / goal))
    return "━" * filled + "─" * (width - filled)
