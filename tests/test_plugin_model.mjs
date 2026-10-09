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

console.log("plugin model ok")
