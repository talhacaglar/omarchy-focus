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

// `units` lets a translation say "1 sa 30 dk": { h: " sa", m: " dk" }.
function minutesLabel(minutes, units) {
  var h = units ? units.h : "h"
  var m = units ? units.m : "m"
  var value = Math.max(0, Math.round(minutes || 0))
  if (value === 0) return "0" + m
  var hours = Math.floor(value / 60)
  var rest = value % 60
  if (hours === 0) return rest + m
  return rest === 0 ? hours + h : hours + h + " " + rest + m
}

// Seconds left, counted locally from the server's end timestamp so the bar
// ticks every second without re-running the CLI.
function remaining(state, nowMs) {
  if (!state || !state.pomodoro) return 0
  var p = state.pomodoro
  if (p.phase === "running" && p.ends_at_ms) return Math.max(0, Math.ceil((p.ends_at_ms - nowMs) / 1000))
  return Math.max(0, p.remaining_seconds || 0)
}

// A work session with no timer: no end, it counts up until it is stopped.
function isOpenEnded(state) {
  if (!state || !state.pomodoro) return false
  var p = state.pomodoro
  return !!p.open_ended && (p.phase === "running" || p.phase === "paused")
}

// Seconds spent in the session, pauses left out. Counted locally while it runs.
function elapsed(state, nowMs) {
  if (!state || !state.pomodoro) return 0
  var p = state.pomodoro
  if (p.phase === "running" && p.started_at_ms) {
    return Math.max(0, Math.floor((nowMs - p.started_at_ms) / 1000) - (p.paused_seconds || 0))
  }
  return Math.max(0, p.elapsed_seconds || 0)
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

// The site guard on its own: off, manual (no timer), timed, or expired, which
// is a timed guard still waiting for root to take the block down.
function guardState(state, nowMs) {
  if (!state || !state.focus || !state.focus.active) return "off"
  if (!state.focus.ends_at_ms) return "manual"
  return state.focus.ends_at_ms > nowMs ? "timed" : "expired"
}

// The end (ms) of a guard that ran out and is still up, else 0. The 1 s timer
// asks the CLI to take it down once per end: one only root can take down stays
// expired, and asking every second re-ran a failing sudo each time.
function expiredGuardEnd(state, nowMs) {
  return guardState(state, nowMs) === "expired" ? state.focus.ends_at_ms : 0
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
  if (isOpenEnded(state)) return glyph + " " + clock(elapsed(state, nowMs))
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
  if (m === "work") return isOpenEnded(state) ? "NO TIMER" : "FOCUS"
  if (m === "break") return state.pomodoro.type === "long_break" ? "LONG BREAK" : "BREAK"
  if (m === "paused") return "PAUSED"
  if (m === "break-ready") return "BREAK READY"
  if (m === "guard") return "GUARD ON"
  return "READY"
}

// Catalog key for the phase label, so the panel can translate it.
function phaseKey(state) {
  var m = mode(state)
  if (m === "work") return isOpenEnded(state) ? "phase.openEnded" : "phase.focus"
  if (m === "break") return state.pomodoro.type === "long_break" ? "phase.longBreak" : "phase.break"
  if (m === "paused") return "phase.paused"
  if (m === "break-ready") return "phase.breakReady"
  if (m === "guard") return "phase.guard"
  return "phase.ready"
}

// Same thresholds as the CLI heatmap: quarters of the daily goal.
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

function clampInt(value, low, high) {
  return Math.max(low, Math.min(high, Math.round(value)))
}

// Where a stepper's − (direction -1) or + (1) goes from `value`: the next
// multiple of `step`, so a typed 7 goes to 5 or 10, and steps of one below
// `fineBelow`, so 5 minutes can still go down to 4.
function stepValue(value, direction, step, fineBelow) {
  var fine = direction > 0 ? value < fineBelow : value <= fineBelow
  var size = fine ? 1 : Math.max(1, step)
  if (direction > 0) return Math.floor(value / size) * size + size
  return Math.ceil(value / size) * size - size
}

// ---- Tasks

function isOpen(task) {
  return task.status === "pending" || task.status === "in_progress"
}

function pad2(value) {
  return value < 10 ? "0" + value : String(value)
}

function dayKey(ms) {
  var d = new Date(ms)
  return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate())
}

// overdue, today, tomorrow, later, or "" without a due date. Done tasks are
// never overdue.
function dueKind(task, nowMs) {
  if (!task.due_at_ms) return ""
  var due = dayKey(task.due_at_ms)
  var today = dayKey(nowMs)
  if (due < today) return isOpen(task) ? "overdue" : "later"
  if (due === today) return "today"
  if (due === dueInDays(1, nowMs)) return "tomorrow"
  return "later"
}

function inFilter(task, filter, nowMs) {
  if (filter === "done") return task.status === "done"
  if (filter === "archived") return task.status === "archived"
  if (!isOpen(task)) return false
  if (filter !== "today") return true
  var kind = dueKind(task, nowMs)
  return task.status === "in_progress" || kind === "overdue" || kind === "today"
}

function filterCounts(tasks, nowMs) {
  var counts = { open: 0, today: 0, done: 0, archived: 0 }
  for (var i = 0; tasks && i < tasks.length; i++) {
    if (inFilter(tasks[i], "open", nowMs)) counts.open++
    if (inFilter(tasks[i], "today", nowMs)) counts.today++
    if (tasks[i].status === "done") counts.done++
    if (tasks[i].status === "archived") counts.archived++
  }
  return counts
}

var SORTS = ["priority", "due", "title", "newest"]

function nextSort(sort) {
  return SORTS[(SORTS.indexOf(sort) + 1) % SORTS.length]
}

function matchesQuery(task, query) {
  if (!query) return true
  var needle = query.toLowerCase()
  var haystack = [task.title, task.description || ""].concat(task.tags || []).join(" ").toLowerCase()
  return haystack.indexOf(needle) !== -1
}

// The CLI already sends open tasks in priority order, so "priority" keeps it.
function visibleTasks(tasks, filter, query, sort, nowMs) {
  var trimmed = String(query || "").trim()
  var shown = (tasks || []).filter(function(task) {
    return inFilter(task, filter, nowMs) && matchesQuery(task, trimmed)
  })
  if (sort === "due") {
    shown.sort(function(a, b) {
      return (a.due_at_ms || Number.MAX_VALUE) - (b.due_at_ms || Number.MAX_VALUE)
    })
  } else if (sort === "title") {
    shown.sort(function(a, b) { return a.title.localeCompare(b.title) })
  } else if (sort === "newest") {
    shown.sort(function(a, b) { return b.id - a.id })
  }
  return shown
}

// A date the due chips can hand straight to `tasks edit --due`. Counted in
// calendar days, so a clock change on the way doesn't land on the wrong one.
function dueInDays(days, nowMs) {
  var d = new Date(nowMs)
  d.setDate(d.getDate() + days)
  return dayKey(d.getTime())
}

// Midnight of the day `nowMs` falls on. List filters depend on this rather than
// the clock, so a running countdown doesn't rebuild them every second.
function dayStartMs(nowMs) {
  var d = new Date(nowMs)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

// ---- CLI arguments. Values use --key=value (or follow --) so a title that
// starts with a dash can't be read as an option.

// `minutes` 0 is a session with no timer; leave it out (null) for the saved length.
function startArgs(taskId, minutes, guard) {
  var args = ["start"]
  if (taskId) args.push("--task-id", String(taskId))
  if (minutes > 0) args.push("--minutes", String(minutes))
  else if (minutes === 0) args.push("--open-ended")
  if (guard === true) args.push("--focus")
  else if (guard === false) args.push("--no-focus")
  return args
}

function guardArgs(minutes, strict) {
  var args = ["focus", "on"]
  if (minutes > 0) args.push("--minutes", String(minutes))
  args.push(strict && minutes > 0 ? "--strict" : "--no-strict")
  return args
}

function taskAddArgs(draft) {
  var args = ["add-task", "--priority", draft.priority || "medium"]
  if (draft.description) args.push("--description=" + draft.description)
  if (draft.tags) args.push("--tags=" + draft.tags)
  if (draft.estimate > 0) args.push("--estimate=" + draft.estimate)
  if (draft.due) args.push("--due=" + draft.due)
  args.push("--", draft.title)
  return args
}

function taskEditArgs(id, draft) {
  return [
    "tasks", "edit", String(id),
    "--title=" + draft.title,
    "--description=" + (draft.description || ""),
    "--priority=" + (draft.priority || "medium"),
    "--tags=" + (draft.tags || ""),
    draft.estimate > 0 ? "--estimate=" + draft.estimate : "--clear-estimate",
    draft.due ? "--due=" + draft.due : "--clear-due"
  ]
}

function settingArgs(key, value) {
  return ["settings", "set", key, String(value)]
}
