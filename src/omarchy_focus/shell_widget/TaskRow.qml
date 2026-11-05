import QtQuick
import qs.Commons
import "Model.js" as Model

// One task. Circle: done or reopen. Hover: start, edit, delete.
Rectangle {
  id: row
  required property var ctx
  required property var task
  // On the focus page a click starts the task instead of opening the editor.
  property bool startsOnClick: false

  readonly property bool isOpen: Model.isOpen(task)
  readonly property bool isCurrent: !!ctx.model && ctx.model.pomodoro.task_id === task.id
  readonly property string meta: ctx.taskMeta(task)
  readonly property bool hot: hover.hovered
  property bool confirmingDelete: false

  width: parent ? parent.width : 0
  height: textColumn.implicitHeight + Style.space(12)
  radius: Style.cornerRadius
  color: hot ? Style.hoverFillFor(ctx.fg, ctx.accent) : "transparent"

  function start() {
    if (ctx.hasSession) ctx.host.act(["assign", "--task-id", String(task.id)])
    else ctx.host.startPomodoro(task.id)
  }

  HoverHandler { id: hover }

  MouseArea {
    anchors.fill: parent
    cursorShape: Qt.PointingHandCursor
    onClicked: {
      if (row.startsOnClick && row.isOpen) row.start()
      else row.ctx.editTask(row.task)
    }
  }

  // Done / reopen.
  Rectangle {
    id: check
    anchors.left: parent.left
    anchors.leftMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(16)
    height: width
    radius: width / 2
    color: row.task.status === "done" ? row.ctx.accent : "transparent"
    border.width: Math.max(1, Style.space(1))
    border.color: checkArea.containsMouse ? row.ctx.accent : Model.priorityColor(row.task.priority, row.ctx.accent, row.ctx.fg, row.ctx.dim)

    FocusText {
      ctx: row.ctx
      anchors.centerIn: parent
      visible: row.task.status === "done" || checkArea.containsMouse
      text: "󰄬"
      color: row.task.status === "done" ? row.ctx.fg : row.ctx.accent
      font.pixelSize: Style.font.caption
    }
    MouseArea {
      id: checkArea
      anchors.fill: parent
      anchors.margins: -Style.space(4)
      hoverEnabled: true
      cursorShape: Qt.PointingHandCursor
      onClicked: {
        if (row.task.status === "done") row.ctx.host.act(["tasks", "edit", String(row.task.id), "--status=pending"])
        else row.ctx.host.act(["tasks", "done", String(row.task.id)])
      }
    }
  }

  Column {
    id: textColumn
    anchors.left: check.right
    anchors.leftMargin: Style.space(10)
    anchors.right: row.hot ? actions.left : parent.right
    anchors.rightMargin: Style.space(8)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(1)

    FocusText {
      ctx: row.ctx
      width: parent.width
      text: row.task.title
      color: row.isCurrent || row.task.status === "in_progress" ? row.ctx.accent : (row.isOpen ? row.ctx.fg : row.ctx.dim)
      font.strikeout: row.task.status === "done"
    }
    FocusText {
      ctx: row.ctx
      width: parent.width
      visible: row.meta !== ""
      muted: Model.dueKind(row.task, row.ctx.nowMs) !== "overdue"
      color: muted ? row.ctx.dim : row.ctx.urgent
      text: row.meta
      font.pixelSize: Style.font.caption
    }
  }

  Row {
    id: actions
    anchors.right: parent.right
    anchors.rightMargin: Style.space(6)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(2)
    visible: row.hot

    Chip {
      ctx: row.ctx
      visible: row.isOpen && !row.isCurrent
      bordered: false
      horizontalPadding: Style.space(6)
      iconText: row.ctx.hasSession ? "󰜴" : "󰐊"
      tooltipText: row.ctx.hasSession ? row.ctx.t("task.assign") : row.ctx.t("task.start")
      onClicked: row.start()
    }
    Chip {
      ctx: row.ctx
      bordered: false
      horizontalPadding: Style.space(6)
      iconText: "󰏫"
      tooltipText: row.ctx.t("task.edit")
      onClicked: row.ctx.editTask(row.task)
    }
    Chip {
      ctx: row.ctx
      bordered: false
      horizontalPadding: Style.space(6)
      iconText: "󰩺"
      text: row.confirmingDelete ? row.ctx.t("task.confirmDelete") : ""
      foreground: row.confirmingDelete ? row.ctx.urgent : row.ctx.fg
      tooltipText: row.ctx.t("task.delete")
      onClicked: {
        if (row.confirmingDelete) {
          row.ctx.host.act(["tasks", "delete", String(row.task.id)])
        } else {
          row.confirmingDelete = true
          deleteReset.restart()
        }
      }
    }
  }

  Timer {
    id: deleteReset
    interval: 3000
    onTriggered: row.confirmingDelete = false
  }
}
