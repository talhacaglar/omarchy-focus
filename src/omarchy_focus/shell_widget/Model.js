// Pure helpers for the Omarchy Focus widget. No QML types in here so the
// logic can be unit-tested with plain node (see tests/test_plugin_model.mjs).

.pragma library

function pad(value) {
  return value < 10 ? "0" + value : String(value)
}

function clock(totalSeconds) {
  var seconds = Math.max(0, Math.floor(totalSeconds || 0))
  var hours = Math.floor(seconds / 3600)
  var minutes = Math.floor((seconds % 3600) / 60)
  var rest = seconds % 60
  if (hours > 0) return hours + ":" + pad(minutes) + ":" + pad(rest)
  return pad(minutes) + ":" + pad(rest)
}

function minutesLabel(minutes) {
  var value = Math.max(0, Math.round(minutes || 0))
  if (value === 0) return "0m"
  var hours = Math.floor(value / 60)
  var rest = value % 60
  if (hours === 0) return rest + "m"
  return rest === 0 ? hours + "h" : hours + "h " + rest + "m"
}

// Seconds left, counted locally from the server's end timestamp so the bar
// ticks every second without re-running the CLI.
function remaining(state, nowMs) {
  if (!state || !state.pomodoro) return 0
  var p = state.pomodoro
  if (p.phase === "running" && p.ends_at_ms) return Math.max(0, Math.ceil((p.ends_at_ms - nowMs) / 1000))
  return Math.max(0, p.remaining_seconds || 0)
}

function focusRemaining(state, nowMs) {
  if (!state || !state.focus || !state.focus.active || !state.focus.ends_at_ms) return 0
  return Math.max(0, Math.ceil((state.focus.ends_at_ms - nowMs) / 1000))
}

// 0..1 share of the current session already done.
function progress(state, nowMs) {
  if (!state || !state.pomodoro) return 0
  var total = state.pomodoro.total_seconds || 0
  if (total <= 0) return 0
  return Math.min(1, Math.max(0, 1 - remaining(state, nowMs) / total))
}

// One of: idle, work, break, paused, break-ready, guard.
function mode(state) {
  if (!state || !state.pomodoro) return "idle"
  var p = state.pomodoro
  if (p.phase === "running") return p.type === "work" ? "work" : "break"
  if (p.phase === "paused") return "paused"
  if (state.pending_break) return "break-ready"
  if (state.focus && state.focus.active) return "guard"
  return "idle"
}

var ICONS = {
  idle: "󰔛",
  work: "󰄉",
  "break": "󰅶",
  paused: "󰏤",
  "break-ready": "󰅶",
  guard: "󰈈"
}

function icon(state) {
  return ICONS[mode(state)]
}

function pillText(state, nowMs, showIdleCount) {
  var m = mode(state)
  var glyph = ICONS[m]
  if (m === "work" || m === "break" || m === "paused") return glyph + " " + clock(remaining(state, nowMs))
  if (m === "break-ready") return glyph + " " + (state.pending_break.minutes || 0) + "m?"
  if (m === "guard") {
    var left = focusRemaining(state, nowMs)
    return left > 0 ? glyph + " " + clock(left) : glyph
  }
  if (showIdleCount && state && state.pending_tasks > 0) return glyph + " " + state.pending_tasks
  return glyph
}

function phaseLabel(state) {
  var m = mode(state)
  if (m === "work") return "FOCUS"
  if (m === "break") return state.pomodoro.type === "long_break" ? "LONG BREAK" : "BREAK"
  if (m === "paused") return "PAUSED"
  if (m === "break-ready") return "BREAK READY"
  if (m === "guard") return "GUARD ON"
  return "READY"
}

// Same thresholds as the CLI/TUI heatmap: quarters of the daily goal.
function heatLevel(minutes, goal) {
  if (!minutes || minutes <= 0) return 0
  var g = Math.max(goal || 0, 1)
  if (minutes >= g) return 4
  return Math.min(3, 1 + Math.floor(3 * minutes / g))
}

// Arrange [{date, minutes}] into week columns, Monday first, padding the
// first column so weekdays line up. Returns an array of columns, each an
// array of 7 cells ({date, minutes, level} or null).
function heatColumns(days, goal) {
  if (!days || days.length === 0) return []
  var first = new Date(days[0].date + "T12:00:00")
  var lead = (first.getDay() + 6) % 7
  var cells = []
  for (var i = 0; i < lead; i++) cells.push(null)
  for (var j = 0; j < days.length; j++) {
    cells.push({ date: days[j].date, minutes: days[j].minutes, level: heatLevel(days[j].minutes, goal) })
  }
  var columns = []
  for (var k = 0; k < cells.length; k += 7) {
    var column = cells.slice(k, k + 7)
    while (column.length < 7) column.push(null)
    columns.push(column)
  }
  return columns
}

function weekMax(week) {
  var top = 0
  for (var i = 0; week && i < week.length; i++) top = Math.max(top, week[i].minutes || 0)
  return top
}

function priorityColor(priority, high, medium, low) {
  if (priority === "high") return high
  if (priority === "medium") return medium
  return low
}
