import QtQuick
import qs.Commons
import "Model.js" as Model

// The clock: start a session with the length you want, change it while it
// runs, take the break it earned.
Column {
  id: page
  required property var ctx

  readonly property var model: ctx.model
  readonly property string mode: ctx.mode
  readonly property var settings: model ? model.settings : null
  readonly property bool guardOn: ctx.guardState !== "off"
  readonly property bool isIdle: mode === "idle" || mode === "guard"

  // Unset until touched, so they follow the settings until then.
  property int plannedMinutes: 0
  property int plannedBreak: 0
  property var guardChoice: null

  readonly property int startMinutes: plannedMinutes > 0 ? plannedMinutes : (settings ? settings.work_minutes : 50)
  readonly property int breakMinutes: plannedBreak > 0 ? plannedBreak : (model && model.pending_break ? model.pending_break.minutes : 0)
  readonly property bool withGuard: guardChoice === null ? !!(settings && settings.focus_on_pomodoro_start) : guardChoice

  spacing: Style.space(14)

  function start(taskId) {
    ctx.host.act(Model.startArgs(taskId, startMinutes, guardOn ? null : withGuard))
    plannedMinutes = 0
    guardChoice = null
  }

  function ringCenterText() {
    if (!model) return "—"
    if (ctx.hasSession) return Model.clock(Model.remaining(model, ctx.nowMs))
    if (mode === "break-ready") return ctx.dur(breakMinutes)
    if (ctx.guardState === "timed") return Model.clock(Model.focusRemaining(model, ctx.nowMs))
    return ctx.dur(ctx.stats ? ctx.stats.today_focus_minutes : 0)
  }

  function ringProgress() {
    if (ctx.hasSession) return Model.progress(model, ctx.nowMs)
    return ctx.stats ? Math.min(1, ctx.stats.today_focus_minutes / ctx.goal) : 0
  }

  function subtitle() {
    if (!model) return ctx.t("timer.loading")
    if (mode === "work" || mode === "paused") return model.pomodoro.task_title || ctx.t("timer.noTask")
    if (mode === "break") return ctx.t("timer.stepAway")
    if (mode === "break-ready") return ctx.t("timer.breakPrompt")
    var next = model.next_tasks && model.next_tasks.length ? model.next_tasks[0].title : ""
    return next ? ctx.t("timer.next").arg(next) : ctx.t("timer.queueClear")
  }

  // ---- Ring with the countdown, phase and current task.
  Item {
    width: parent.width
    height: Style.space(124)

    Ring {
      id: ring
      width: Style.space(124)
      height: width
      thickness: Style.space(7)
      progress: page.ringProgress()
      trackColor: page.ctx.track
      fillColor: page.mode === "break" || page.mode === "break-ready" ? page.ctx.fg : page.ctx.accent
      opacity: page.mode === "paused" ? 0.55 : 1

      Column {
        anchors.centerIn: parent
        spacing: Style.space(2)

        // Sized to the ring: "1 sa 40 dk" is far wider than "49:58".
        FocusText {
          ctx: page.ctx
          width: ring.width - ring.thickness * 2 - Style.space(14)
          height: Style.font.display * 1.3
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          fontSizeMode: Text.HorizontalFit
          minimumPixelSize: Style.font.body
          text: page.ringCenterText()
          font.pixelSize: Style.font.display
          font.bold: true
          font.features: { "tnum": 1 }
        }
        SectionLabel {
          ctx: page.ctx
          width: ring.width - ring.thickness * 2 - Style.space(14)
          horizontalAlignment: Text.AlignHCenter
          fontSizeMode: Text.HorizontalFit
          minimumPixelSize: Style.font.caption - 2
          text: page.mode === "idle" ? page.ctx.t("timer.ofGoal").arg(page.ctx.dur(page.ctx.goal)) : page.ctx.t(Model.phaseKey(page.model))
        }
      }
    }

    Column {
      anchors.left: ring.right
      anchors.leftMargin: Style.space(20)
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(8)

      // The ring already says the phase, except when idle, where it shows the goal.
      SectionLabel {
        ctx: page.ctx
        width: parent.width
        visible: page.mode === "idle"
        text: page.ctx.t(Model.phaseKey(page.model))
      }
      FocusText {
        ctx: page.ctx
        width: parent.width
        text: page.subtitle()
        font.pixelSize: Style.font.title
        wrapMode: Text.WordWrap
        maximumLineCount: 2
      }
      FocusText {
        ctx: page.ctx
        width: parent.width
        visible: !!page.model
        muted: !page.guardOn
        color: page.guardOn ? page.ctx.accent : page.ctx.dim
        font.pixelSize: Style.font.bodySmall
        text: page.guardOn
          ? "󰈈  " + page.ctx.tn("guard.onSites", page.model.focus.sites.length)
          : "󰈉  " + page.ctx.t("guard.off")
        MouseArea {
          anchors.fill: parent
          cursorShape: Qt.PointingHandCursor
          onClicked: page.ctx.tab = 2
        }
      }
    }
  }

  // ---- A session underway: change the time, pause, stop.
  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: page.ctx.hasSession

    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Style.space(6)

      Repeater {
        model: [-5, -1, 1, 5]

        Chip {
          required property int modelData
          ctx: page.ctx
          text: (modelData > 0 ? "+" : "−") + Math.abs(modelData) + page.ctx.t("unit.m")
          tooltipText: modelData > 0 ? page.ctx.t("timer.extend") : page.ctx.t("timer.shorten")
          enabled: modelData > 0 || Model.remaining(page.model, page.ctx.nowMs) > 60
          onClicked: page.ctx.host.adjust(modelData)
        }
      }
    }

    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Style.space(6)

      Chip {
        ctx: page.ctx
        visible: page.mode === "work" || page.mode === "break"
        iconText: "󰏤"
        text: page.ctx.t("timer.pause")
        onClicked: page.ctx.host.act(["pause"])
      }
      Chip {
        ctx: page.ctx
        visible: page.mode === "paused"
        iconText: "󰐊"
        text: page.ctx.t("timer.resume")
        onClicked: page.ctx.host.act(["resume"])
      }
      Chip {
        ctx: page.ctx
        iconText: "󰓛"
        text: page.ctx.t("timer.stop")
        onClicked: page.ctx.host.act(["stop"])
      }
      Chip {
        ctx: page.ctx
        visible: !!page.model && !!page.model.pomodoro.task_id && page.mode !== "break"
        iconText: "󰄬"
        text: page.ctx.t("timer.taskDone")
        onClicked: page.ctx.host.act(["tasks", "done", String(page.model.pomodoro.task_id)])
      }
    }
  }

  // ---- Nothing running: pick a length, then start.
  Column {
    width: parent.width
    spacing: Style.space(10)
    visible: page.isIdle && !!page.model

    Row {
      anchors.horizontalCenter: parent.horizontalCenter
      spacing: Style.space(6)

      Repeater {
        model: [15, 25, 50, 90]

        Chip {
          required property int modelData
          ctx: page.ctx
          text: modelData + page.ctx.t("unit.m")
          selected: page.startMinutes === modelData
          onClicked: page.plannedMinutes = modelData
        }
      }
      Stepper {
        ctx: page.ctx
        value: page.startMinutes
        from: 5
        to: 240
        step: 5
        text: page.ctx.dur(shown)
        onChanged: function(value) { page.plannedMinutes = value }
      }
    }

    ToggleRow {
      ctx: page.ctx
      visible: !page.guardOn
      label: page.ctx.t("timer.withGuard")
      description: page.ctx.t("timer.withGuardHint")
      checked: page.withGuard
      onToggled: page.guardChoice = !page.withGuard
    }

    Chip {
      ctx: page.ctx
      anchors.horizontalCenter: parent.horizontalCenter
      iconText: "󰐊"
      text: page.ctx.t("timer.start").arg(page.ctx.dur(page.startMinutes))
      selected: true
      fontSize: Style.font.body
      horizontalPadding: Style.space(18)
      verticalPadding: Style.space(7)
      onClicked: page.start(0)
    }
  }

  // ---- A session just ended: take the break, or don't.
  Row {
    anchors.horizontalCenter: parent.horizontalCenter
    spacing: Style.space(6)
    visible: page.mode === "break-ready"

    Stepper {
      ctx: page.ctx
      value: page.breakMinutes
      from: 1
      to: 120
      step: 1
      text: page.ctx.dur(shown)
      anchors.verticalCenter: parent.verticalCenter
      onChanged: function(value) { page.plannedBreak = value }
    }
    Chip {
      ctx: page.ctx
      iconText: "󰅶"
      text: page.ctx.t("timer.takeBreak")
      selected: true
      onClicked: {
        page.ctx.host.act(["break", "start", "--minutes", String(page.breakMinutes)])
        page.plannedBreak = 0
      }
    }
    Chip {
      ctx: page.ctx
      iconText: "󰒭"
      text: page.ctx.t("timer.skipBreak")
      onClicked: {
        page.ctx.host.act(["break", "skip"])
        page.plannedBreak = 0
      }
    }
  }

  Rectangle {
    width: parent.width
    height: Style.spacing.hairline
    color: page.ctx.track
  }

  // ---- Up next.
  Column {
    width: parent.width
    spacing: Style.space(2)
    visible: !!page.model && page.model.next_tasks.length > 0

    SectionLabel {
      ctx: page.ctx
      x: Style.space(8)
      bottomPadding: Style.space(4)
      text: page.ctx.t("timer.upNext").arg(page.model ? page.model.pending_tasks : 0)
    }

    Repeater {
      model: {
        var open = (page.ctx.host ? page.ctx.host.tasks : []).filter(Model.isOpen)
        return open.slice(0, 3)
      }

      TaskRow {
        required property var modelData
        ctx: page.ctx
        task: modelData
        startsOnClick: true
      }
    }
  }

  // ---- Today against the goal.
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: !!page.ctx.stats

    Item {
      width: parent.width
      height: todayLabel.implicitHeight
      SectionLabel {
        id: todayLabel
        ctx: page.ctx
        x: Style.space(8)
        text: page.ctx.t("stats.today")
      }
      FocusText {
        ctx: page.ctx
        anchors.right: parent.right
        anchors.rightMargin: Style.space(8)
        text: page.ctx.stats ? page.ctx.dur(page.ctx.stats.today_focus_minutes) + " / " + page.ctx.dur(page.ctx.goal) : ""
        font.pixelSize: Style.font.bodySmall
      }
    }
    Rectangle {
      x: Style.space(8)
      width: parent.width - Style.space(16)
      height: Style.space(6)
      radius: height / 2
      color: page.ctx.track
      Rectangle {
        height: parent.height
        radius: parent.radius
        color: page.ctx.accent
        width: page.ctx.stats ? parent.width * Math.min(1, page.ctx.stats.today_focus_minutes / page.ctx.goal) : 0
      }
    }
  }
}
