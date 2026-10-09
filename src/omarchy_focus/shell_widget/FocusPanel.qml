import QtQuick
import Quickshell
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import qs.Ui as Ui
import "Model.js" as Model

// Popup for the Omarchy Focus pill: timer ring and controls, the task
// queue (click a task to start on it), today's goal, the last seven days
// and a twelve-week heatmap. All data comes from the host BarWidget.
//
// The base type is qualified on purpose: an unqualified `Panel` could
// resolve to a sibling file of the same name in this plugin directory.
Ui.Panel {
  id: root
  moduleName: "omarchy-focus"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property var host: hostWidget
  readonly property var model: host ? host.state : null
  readonly property double nowMs: host ? host.nowMs : Date.now()
  readonly property string mode: Model.mode(model)
  readonly property color fg: root.bar ? root.bar.foreground : Commons.Color.foreground
  readonly property color dim: Qt.darker(fg, 1.5)
  readonly property color accent: Commons.Color.accent
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
  readonly property var stats: model ? model.stats : null
  readonly property int goal: stats && stats.goal_minutes > 0 ? stats.goal_minutes : 150

  function openFromHotkey() {
    root.controller.show()
    if (host) host.refresh()
  }

  function open() { openFromHotkey() }
  function close() { root.controller.hide() }
  function toggle() { root.opened ? root.close() : root.openFromHotkey() }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function ringCenterText() {
    if (!model) return "—"
    if (mode === "work" || mode === "break" || mode === "paused") return Model.clock(Model.remaining(model, nowMs))
    if (mode === "break-ready") return (model.pending_break.minutes || 0) + "m"
    if (mode === "guard" && model.focus.ends_at_ms) return Model.clock(Model.focusRemaining(model, nowMs))
    return Model.minutesLabel(stats ? stats.today_focus_minutes : 0)
  }

  function ringProgress() {
    if (mode === "work" || mode === "break" || mode === "paused") return Model.progress(model, nowMs)
    return stats ? Math.min(1, stats.today_focus_minutes / goal) : 0
  }

  function subtitle() {
    if (!model) return host && host.error ? host.error : "Loading…"
    if (mode === "work" || mode === "paused") return model.pomodoro.task_title || "Unassigned focus session"
    if (mode === "break") return "Step away from the screen"
    if (mode === "break-ready") return "Session done. Take the break?"
    var next = model.next_tasks && model.next_tasks.length ? model.next_tasks[0].title : ""
    return next ? "Next: " + next : "Queue clear. Add a task in the app."
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keys
    contentWidth: panel.fittedContentWidth(Style.space(440))
    contentHeight: panel.fittedContentHeight(content.implicitHeight)

    PanelKeyCatcher {
      id: keys
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onReturnRequested: if (host) host.primaryAction()
      onActivateRequested: if (host) host.primaryAction()
      onTextKey: function(text) {
        if (!host) return
        if (text === "s") mode === "idle" || mode === "guard" ? host.startPomodoro(0) : host.act(["stop"])
        else if (text === "p") host.primaryAction()
        else if (text === "b" && mode === "break-ready") host.act(["break", "start"])
        else if (text === "n" && mode === "break-ready") host.act(["break", "skip"])
        else if (text === "g") host.toggleGuard()
        else if (text === "o") { root.close(); host.openApp() }
      }

      Flickable {
        id: scroller
        anchors.fill: parent
        contentWidth: width
        contentHeight: content.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Column {
          id: content
          width: scroller.width
          spacing: Style.space(16)

          // ---- Hero: ring with the countdown, phase and current task.
          Item {
            width: parent.width
            height: Style.space(132)

            Ring {
              id: ring
              width: Style.space(132)
              height: width
              anchors.left: parent.left
              anchors.leftMargin: Style.space(8)
              thickness: Style.space(7)
              progress: root.ringProgress()
              trackColor: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.12)
              fillColor: root.mode === "break" || root.mode === "break-ready" ? root.fg : root.accent
              opacity: root.mode === "paused" ? 0.55 : 1

              Column {
                anchors.centerIn: parent
                spacing: Style.space(2)

                Text {
                  anchors.horizontalCenter: parent.horizontalCenter
                  textFormat: Text.PlainText
                  text: root.ringCenterText()
                  color: root.fg
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.display
                  font.bold: true
                  font.features: { "tnum": 1 }
                }
                Text {
                  anchors.horizontalCenter: parent.horizontalCenter
                  textFormat: Text.PlainText
                  text: root.mode === "idle" ? "OF " + Model.minutesLabel(root.goal).toUpperCase() : Model.phaseLabel(root.model)
                  color: root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.caption
                  font.letterSpacing: 1
                }
              }
            }

            Column {
              anchors.left: ring.right
              anchors.leftMargin: Style.space(20)
              anchors.right: parent.right
              anchors.rightMargin: Style.space(8)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(10)

              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: Model.phaseLabel(root.model)
                color: root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.caption
                font.letterSpacing: 1
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                text: root.subtitle()
                color: root.fg
                font.family: root.fontFamily
                font.pixelSize: Style.font.title
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
              }
              Text {
                width: parent.width
                textFormat: Text.PlainText
                visible: !!root.model
                text: {
                  if (!root.model) return ""
                  var f = root.model.focus
                  if (f && f.active) return "󰈈  Guard on · " + f.sites.length + " sites" + (f.strict ? " · strict" : "")
                  return "󰈉  Guard off · press g"
                }
                color: root.model && root.model.focus.active ? root.accent : root.dim
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
                elide: Text.ElideRight
              }
            }
          }

          // ---- Controls follow the session state.
          Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Style.space(8)

            Button {
              visible: root.mode === "idle" || root.mode === "guard"
              iconText: "󰐊"
              text: "Focus " + (root.model ? root.model.settings.work_minutes : 50) + "m"
              bordered: true
              fontFamily: root.fontFamily
              onClicked: root.host.startPomodoro(0)
            }
            Button {
              visible: root.mode === "work" || root.mode === "break"
              iconText: "󰏤"
              text: "Pause"
              bordered: true
              fontFamily: root.fontFamily
              onClicked: root.host.act(["pause"])
            }
            Button {
              visible: root.mode === "paused"
              iconText: "󰐊"
              text: "Resume"
              bordered: true
              fontFamily: root.fontFamily
              onClicked: root.host.act(["resume"])
            }
            Button {
              visible: root.mode === "work" || root.mode === "break" || root.mode === "paused"
              iconText: "󰓛"
              text: "Stop"
              bordered: true
              fontFamily: root.fontFamily
              onClicked: root.host.act(["stop"])
            }
            Button {
              visible: root.mode === "break-ready"
              iconText: "󰅶"
              text: "Break " + (root.model && root.model.pending_break ? root.model.pending_break.minutes : 0) + "m"
              bordered: true
              fontFamily: root.fontFamily
              onClicked: root.host.act(["break", "start"])
            }
            Button {
              visible: root.mode === "break-ready"
              iconText: "󰒭"
              text: "Skip"
              bordered: true
              fontFamily: root.fontFamily
              onClicked: root.host.act(["break", "skip"])
            }
            Button {
              iconText: root.model && root.model.focus.active ? "󰈉" : "󰈈"
              text: root.model && root.model.focus.active ? "Unblock" : "Guard"
              tooltipText: "Block distracting sites via /etc/hosts"
              bordered: true
              fontFamily: root.fontFamily
              onClicked: root.host.toggleGuard()
            }
            Button {
              iconText: "󰆍"
              tooltipText: "Open the full app"
              bordered: true
              fontFamily: root.fontFamily
              onClicked: { root.close(); root.host.openApp() }
            }
          }

          Divider {}

          // ---- Up next: click to start a pomodoro on that task.
          Column {
            width: parent.width
            spacing: Style.space(4)
            visible: !!root.model && root.model.next_tasks.length > 0

            SectionLabel { text: "UP NEXT · " + (root.model ? root.model.pending_tasks : 0) + " OPEN" }

            Repeater {
              model: root.model ? root.model.next_tasks : []

              Rectangle {
                required property var modelData
                width: parent.width
                height: Style.space(30)
                radius: Style.cornerRadius
                color: taskArea.containsMouse ? Style.hoverFillFor(root.fg, root.accent) : "transparent"

                Row {
                  anchors.left: parent.left
                  anchors.leftMargin: Style.space(10)
                  anchors.right: startHint.left
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(10)

                  Rectangle {
                    width: Style.space(6)
                    height: width
                    radius: width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: Model.priorityColor(modelData.priority, root.accent, root.fg, root.dim)
                    opacity: modelData.priority === "low" ? 0.6 : 1
                  }
                  Text {
                    width: parent.width - Style.space(16)
                    textFormat: Text.PlainText
                    text: modelData.title
                    color: modelData.status === "in_progress" ? root.accent : root.fg
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    elide: Text.ElideRight
                  }
                }
                Text {
                  id: startHint
                  anchors.right: parent.right
                  anchors.rightMargin: Style.space(10)
                  anchors.verticalCenter: parent.verticalCenter
                  textFormat: Text.PlainText
                  text: taskArea.containsMouse ? "󰐊 start" : (modelData.estimate ? Model.minutesLabel(modelData.estimate) : "")
                  color: taskArea.containsMouse ? root.accent : root.dim
                  font.family: root.fontFamily
                  font.pixelSize: Style.font.bodySmall
                }
                MouseArea {
                  id: taskArea
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.host.startPomodoro(modelData.id)
                }
              }
            }
          }

          // ---- Today against the daily goal.
          Column {
            width: parent.width
            spacing: Style.space(8)
            visible: !!root.stats

            Item {
              width: parent.width
              height: todayLabel.implicitHeight
              SectionLabel { id: todayLabel; text: "TODAY" }
              Text {
                anchors.right: parent.right
                anchors.rightMargin: Style.space(8)
                textFormat: Text.PlainText
                text: root.stats ? Model.minutesLabel(root.stats.today_focus_minutes) + " / " + Model.minutesLabel(root.goal) : ""
                color: root.fg
                font.family: root.fontFamily
                font.pixelSize: Style.font.bodySmall
              }
            }
            Rectangle {
              x: Style.space(8)
              width: parent.width - Style.space(16)
              height: Style.space(6)
              radius: height / 2
              color: Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.12)
              Rectangle {
                height: parent.height
                radius: parent.radius
                color: root.accent
                width: root.stats ? parent.width * Math.min(1, root.stats.today_focus_minutes / root.goal) : 0
                Behavior on width {
                  enabled: !Style.reduceMotion
                  NumberAnimation { duration: 500; easing.type: Easing.OutCubic }
                }
              }
            }
            Row {
              x: Style.space(8)
              spacing: Style.space(28)
              Stat { statValue: root.stats ? String(root.stats.today_pomodoros) : "0"; statLabel: "POMODOROS" }
              Stat { statValue: root.stats ? String(root.stats.today_tasks_done) : "0"; statLabel: "TASKS DONE" }
              Stat { statValue: root.stats ? root.stats.streak_days + "d" : "0d"; statLabel: "STREAK" }
              Stat {
                statValue: root.stats && root.stats.completion_rate !== null ? Math.round(root.stats.completion_rate * 100) + "%" : "—"
                statLabel: "FINISHED"
              }
            }
          }

          Divider { visible: !!root.stats }

          // ---- Last seven days and a twelve-week heatmap, side by side.
          Row {
            width: parent.width
            spacing: Style.space(20)
            visible: !!root.stats

            Column {
              id: weekColumn
              spacing: Style.space(6)

              SectionLabel { text: "7 DAYS · " + (root.stats ? Model.minutesLabel(root.stats.week_focus_minutes) : "") }

              Row {
                x: Style.space(8)
                spacing: Style.space(8)
                height: Style.space(64)

                Repeater {
                  model: root.stats ? root.stats.week : []

                  Column {
                    required property var modelData
                    required property int index
                    spacing: Style.space(4)
                    anchors.bottom: parent.bottom

                    Rectangle {
                      anchors.horizontalCenter: parent.horizontalCenter
                      width: Style.space(14)
                      radius: Style.space(3)
                      height: Math.max(Style.space(3), Style.space(44) * modelData.minutes / Math.max(Model.weekMax(root.stats.week), 1))
                      color: modelData.minutes > 0 ? root.accent : Qt.rgba(root.fg.r, root.fg.g, root.fg.b, 0.15)
                      opacity: index === 6 ? 1 : 0.75
                    }
                    Text {
                      anchors.horizontalCenter: parent.horizontalCenter
                      textFormat: Text.PlainText
                      text: modelData.label.substring(0, 2)
                      color: index === 6 ? root.fg : root.dim
                      font.family: root.fontFamily
                      font.pixelSize: Style.font.caption
                    }
                  }
                }
              }
            }

            Column {
              spacing: Style.space(6)

              SectionLabel { text: "12 WEEKS" }

              Row {
                x: Style.space(8)
                spacing: Style.space(3)

                Repeater {
                  model: Model.heatColumns(root.model ? root.model.heatmap : [], root.goal)

                  Column {
                    required property var modelData
                    spacing: Style.space(3)

                    Repeater {
                      model: modelData

                      Rectangle {
                        required property var modelData
                        width: Style.space(7)
                        height: width
                        radius: Style.space(2)
                        visible: modelData !== null
                        color: modelData && modelData.level > 0 ? root.accent : root.fg
                        opacity: modelData ? [0.1, 0.3, 0.5, 0.75, 1][modelData.level] : 0
                      }
                    }
                  }
                }
              }
            }
          }

          Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            textFormat: Text.PlainText
            text: "↵ start/pause · s stop · g guard · o open app"
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
          }
        }
      }
    }
  }

  component Divider: Rectangle {
    width: parent ? parent.width : 0
    height: Style.spacing.hairline
    color: root.fg
    opacity: 0.12
  }

  component SectionLabel: Text {
    x: Style.space(8)
    textFormat: Text.PlainText
    color: root.dim
    font.family: root.fontFamily
    font.pixelSize: Style.font.caption
    font.letterSpacing: 1
  }

  component Stat: Column {
    property string statValue: ""
    property string statLabel: ""
    spacing: Style.space(2)
    Text {
      textFormat: Text.PlainText
      text: parent.statValue
      color: root.fg
      font.family: root.fontFamily
      font.pixelSize: Style.font.title
    }
    Text {
      textFormat: Text.PlainText
      text: parent.statLabel
      color: root.dim
      font.family: root.fontFamily
      font.pixelSize: Style.font.caption
      font.letterSpacing: 1
    }
  }

  // Circular progress ring, 0..1 clockwise from 12 o'clock.
  component Ring: Canvas {
    property real progress: 0
    property real thickness: 6
    property color trackColor: "#33ffffff"
    property color fillColor: "white"

    onProgressChanged: requestPaint()
    onTrackColorChanged: requestPaint()
    onFillColorChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
      var ctx = getContext("2d")
      ctx.reset()
      var radius = Math.min(width, height) / 2 - thickness / 2
      var cx = width / 2
      var cy = height / 2
      ctx.lineWidth = thickness
      ctx.lineCap = "round"

      ctx.strokeStyle = trackColor
      ctx.beginPath()
      ctx.arc(cx, cy, radius, 0, Math.PI * 2)
      ctx.stroke()

      var value = Math.max(0, Math.min(1, progress))
      if (value <= 0) return
      ctx.strokeStyle = fillColor
      ctx.beginPath()
      ctx.arc(cx, cy, radius, -Math.PI / 2, -Math.PI / 2 + value * Math.PI * 2)
      ctx.stroke()
    }
  }
}
