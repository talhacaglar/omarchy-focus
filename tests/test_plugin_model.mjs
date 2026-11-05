// Runs the Omarchy Shell widget's Model.js under node (strips the QML pragma).
import assert from "node:assert/strict"
import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import vm from "node:vm"

const source = readFileSync(fileURLToPath(new URL("../src/omarchy_focus/shell_widget/Model.js", import.meta.url)), "utf8")
  .replace(".pragma library", "")
// Top-level functions in a script context become properties of the sandbox.
const M = {}
vm.runInNewContext(source, M)

assert.equal(M.clock(0), "00:00")
assert.equal(M.clock(65), "01:05")
assert.equal(M.clock(3725), "1:02:05")
assert.equal(M.minutesLabel(0), "0m")
assert.equal(M.minutesLabel(90), "1h 30m")
assert.equal(M.minutesLabel(120), "2h")

const now = 1_000_000
const running = {
  pomodoro: { phase: "running", type: "work", ends_at_ms: now + 90_500, total_seconds: 300, remaining_seconds: 0 },
  focus: { active: false },
  pending_break: null,
  pending_tasks: 3,
}
assert.equal(M.mode(running), "work")
assert.equal(M.remaining(running, now), 91)
assert.ok(Math.abs(M.progress(running, now) - (1 - 91 / 300)) < 1e-9)
assert.equal(M.pillText(running, now, true), "󰄉 01:31")

const paused = { ...running, pomodoro: { ...running.pomodoro, phase: "paused", remaining_seconds: 42 } }
assert.equal(M.mode(paused), "paused")
assert.equal(M.remaining(paused, now), 42)

const idle = { pomodoro: { phase: "idle" }, focus: { active: false }, pending_break: null, pending_tasks: 3 }
assert.equal(M.pillText(idle, now, true), "󰔛 3")
assert.equal(M.pillText(idle, now, false), "󰔛")
assert.equal(M.pillText(null, now, true), "󰔛")

const ready = { ...idle, pending_break: { minutes: 10 } }
assert.equal(M.mode(ready), "break-ready")
assert.equal(M.pillText(ready, now, true), "󰅶 10m?")

const guard = { ...idle, focus: { active: true, ends_at_ms: now + 60_000 } }
assert.equal(M.mode(guard), "guard")
assert.equal(M.pillText(guard, now, true), "󰈈 01:00")

assert.deepEqual([0, 10, 50, 90, 120].map((m) => M.heatLevel(m, 120)), [0, 1, 2, 3, 4])
// 2026-10-07 is a Wednesday.
const columns = M.heatColumns([{ date: "2026-10-07", minutes: 30 }, { date: "2026-10-08", minutes: 0 }], 120)
assert.equal(columns.length, 1)
assert.equal(columns[0][0], null)
assert.equal(columns[0][2].level, 1)
assert.equal(columns[0][3].level, 0)
assert.equal(columns[0][6], null)

assert.equal(M.minutesLabel(90, { h: " sa", m: " dk" }), "1 sa 30 dk")
assert.equal(M.minutesLabel(0, { h: " sa", m: " dk" }), "0 dk")

// Guard states, on their own and at the moment a timed one runs out.
assert.equal(M.guardState(idle, now), "off")
assert.equal(M.guardState(guard, now), "timed")
assert.equal(M.guardState(guard, now + 60_000), "expired")
assert.equal(M.guardState({ ...idle, focus: { active: true, ends_at_ms: null } }, now), "manual")

assert.equal(M.phaseKey(running), "phase.focus")
assert.equal(M.phaseKey(ready), "phase.breakReady")
assert.equal(M.phaseKey(null), "phase.ready")

// Tasks: filters, due dates and sorting.
const noon = new Date(2026, 10, 5, 12).getTime()
const day = 86_400_000
const tasks = [
  { id: 1, title: "Write", status: "in_progress", priority: "high", tags: ["work"] },
  { id: 2, title: "ödev teslim", status: "pending", priority: "medium", due_at_ms: noon - day },
  { id: 3, title: "Call", status: "pending", priority: "low", due_at_ms: noon + day, description: "dentist" },
  { id: 4, title: "Old", status: "done", priority: "low", due_at_ms: noon - day },
  { id: 5, title: "Shelved", status: "archived", priority: "low" },
]
const ids = (list) => JSON.stringify(list.map((task) => task.id))
assert.equal(M.dueKind(tasks[1], noon), "overdue")
assert.equal(M.dueKind(tasks[2], noon), "tomorrow")
assert.equal(M.dueKind(tasks[3], noon), "later") // done is never overdue
assert.equal(M.dueKind(tasks[0], noon), "")
assert.equal(JSON.stringify(M.filterCounts(tasks, noon)), JSON.stringify({ open: 3, today: 2, done: 1, archived: 1 }))
assert.equal(ids(M.visibleTasks(tasks, "open", "", "priority", noon)), "[1,2,3]")
assert.equal(ids(M.visibleTasks(tasks, "today", "", "priority", noon)), "[1,2]")
assert.equal(ids(M.visibleTasks(tasks, "open", "DENTIST", "priority", noon)), "[3]")
assert.equal(ids(M.visibleTasks(tasks, "open", " #none ", "priority", noon)), "[]")
assert.equal(ids(M.visibleTasks(tasks, "open", "work", "priority", noon)), "[1]")
assert.equal(ids(M.visibleTasks(tasks, "open", "", "newest", noon)), "[3,2,1]")
assert.equal(ids(M.visibleTasks(tasks, "open", "", "due", noon)), "[2,3,1]")
assert.equal(M.nextSort("newest"), "priority")
assert.equal(M.dueInDays(1, new Date(2026, 11, 31, 23).getTime()), "2027-01-01")
assert.equal(M.dayStartMs(noon), new Date(2026, 10, 5).getTime())
// Filters stay put for the whole day, or a countdown would rebuild the list.
assert.equal(M.dayStartMs(noon + 3_600_000), M.dayStartMs(noon))

// Arguments for the CLI: values can't turn into options.
const list = (value) => JSON.stringify(Array.from(value))
assert.equal(list(M.startArgs(7, 25, true)), list(["start", "--task-id", "7", "--minutes", "25", "--focus"]))
assert.equal(list(M.startArgs(0, 0, null)), list(["start"]))
assert.equal(list(M.startArgs(0, 15, false)), list(["start", "--minutes", "15", "--no-focus"]))
assert.equal(list(M.guardArgs(50, true)), list(["focus", "on", "--minutes", "50", "--strict"]))
assert.equal(list(M.guardArgs(0, true)), list(["focus", "on", "--no-strict"])) // strict needs a timer
assert.equal(list(M.taskAddArgs({ title: "-rf", priority: "high" })), list(["add-task", "--priority", "high", "--", "-rf"]))
assert.deepEqual(
  Array.from(M.taskEditArgs(3, { title: "-x", description: "", priority: "low", tags: "a", estimate: 0, due: "" })),
  ["tasks", "edit", "3", "--title=-x", "--description=", "--priority=low", "--tags=a", "--clear-estimate", "--clear-due"],
)
assert.equal(list(M.taskEditArgs(3, { title: "t", estimate: 25, due: "2026-12-01" }).slice(-2)), list(["--estimate=25", "--due=2026-12-01"]))
assert.equal(list(M.settingArgs("guard_minutes", 30)), list(["settings", "set", "guard_minutes", "30"]))

console.log("plugin model ok")
