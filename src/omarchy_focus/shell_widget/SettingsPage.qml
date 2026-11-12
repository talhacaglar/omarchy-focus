import QtQuick
import qs.Commons
import "Model.js" as Model

// Lengths, the daily goal and the guard's defaults. Each change saves at once.
Column {
  id: page
  required property var ctx

  readonly property var values: ctx.model ? ctx.model.settings : null

  spacing: Style.space(8)

  function set(key, value) {
    ctx.host.act(Model.settingArgs(key, value))
  }

  SectionLabel { ctx: page.ctx; text: page.ctx.t("settings.lengths") }

  SettingRow {
    ctx: page.ctx
    label: page.ctx.t("settings.work")
    Stepper {
      ctx: page.ctx
      // Also what the Focus page last picked; 0 is a session with no timer.
      value: page.values ? page.values.work_minutes : 50
      editable: true
      from: 0; to: 720; step: 5; fineBelow: 5
      text: shown === 0 ? page.ctx.t("timer.openEnded") : page.ctx.dur(shown)
      onChanged: function(value) { page.set("pomodoro_work_minutes", value) }
    }
  }
  SettingRow {
    ctx: page.ctx
    label: page.ctx.t("settings.shortBreak")
    Stepper {
      ctx: page.ctx
      value: page.values ? page.values.short_break_minutes : 10
      from: 1; to: 60; step: 1
      text: page.ctx.dur(shown)
      onChanged: function(value) { page.set("pomodoro_short_break_minutes", value) }
    }
  }
  SettingRow {
    ctx: page.ctx
    label: page.ctx.t("settings.longBreak")
    Stepper {
      ctx: page.ctx
      value: page.values ? page.values.long_break_minutes : 25
      from: 1; to: 120; step: 5
      text: page.ctx.dur(shown)
      onChanged: function(value) { page.set("pomodoro_long_break_minutes", value) }
    }
  }
  SettingRow {
    ctx: page.ctx
    label: page.ctx.t("settings.longBreakEvery")
    description: page.ctx.t("settings.longBreakEveryHint")
    Stepper {
      ctx: page.ctx
      value: page.values ? page.values.long_break_every : 4
      from: 0; to: 12; step: 1
      text: shown === 0 ? page.ctx.t("settings.off") : String(shown)
      onChanged: function(value) { page.set("pomodoro_long_break_every", value) }
    }
  }
  SettingRow {
    ctx: page.ctx
    label: page.ctx.t("settings.goal")
    Stepper {
      ctx: page.ctx
      value: page.values ? page.values.daily_goal_minutes : 150
      from: 15; to: 720; step: 15
      text: page.ctx.dur(shown)
      onChanged: function(value) { page.set("daily_goal_minutes", value) }
    }
  }

  Rectangle { width: parent.width; height: Style.spacing.hairline; color: page.ctx.track }

  SectionLabel { ctx: page.ctx; topPadding: Style.space(6); text: page.ctx.t("settings.guard") }

  SettingRow {
    ctx: page.ctx
    label: page.ctx.t("settings.guardLength")
    Stepper {
      ctx: page.ctx
      value: page.values ? page.values.guard_minutes : 50
      from: 5; to: 240; step: 5
      text: page.ctx.dur(shown)
      onChanged: function(value) { page.set("guard_minutes", value) }
    }
  }
  ToggleRow {
    ctx: page.ctx
    label: page.ctx.t("settings.guardWithSession")
    checked: !!page.values && page.values.focus_on_pomodoro_start
    onToggled: page.set("focus_on_pomodoro_start", !checked)
  }
  ToggleRow {
    ctx: page.ctx
    label: page.ctx.t("settings.strictDefault")
    description: page.ctx.t("guard.strictHint")
    checked: !!page.values && page.values.strict_mode_default
    onToggled: page.set("strict_mode_default", !checked)
  }
  ToggleRow {
    ctx: page.ctx
    label: page.ctx.t("settings.autoRelease")
    checked: !!page.values && page.values.focus_auto_release
    onToggled: page.set("focus_auto_release", !checked)
  }

  Rectangle { width: parent.width; height: Style.spacing.hairline; color: page.ctx.track }

  ToggleRow {
    ctx: page.ctx
    label: page.ctx.t("settings.notifications")
    checked: !!page.values && page.values.notifications_enabled
    onToggled: page.set("notifications_enabled", !checked)
  }

  FocusText {
    ctx: page.ctx
    width: parent.width
    topPadding: Style.space(6)
    muted: true
    horizontalAlignment: Text.AlignHCenter
    font.pixelSize: Style.font.caption
    text: page.ctx.model ? "Omarchy Focus " + page.ctx.model.version + "  ·  " + page.ctx.t("settings.keys") : ""
  }
}
