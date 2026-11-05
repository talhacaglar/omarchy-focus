import QtQuick
import qs.Commons
import qs.Ui as Ui
import "Model.js" as Model

// The task list: add in one line, filter, search; everything else on a row.
Column {
  id: page
  required property var ctx

  readonly property var tasks: ctx.host ? ctx.host.tasks : []
  readonly property double today: Model.dayStartMs(ctx.nowMs)
  readonly property var counts: Model.filterCounts(tasks, today)
  property string filter: "open"
  property string sort: "priority"
  property string addPriority: "medium"
  property bool editing: false
  readonly property var shown: Model.visibleTasks(tasks, filter, searchField.text, sort, today)

  spacing: Style.space(10)

  function edit(task) {
    editor.load(task, "")
    editing = true
  }

  function closeEditor() {
    editing = false
    ctx.releaseField()
  }

  function focusAdd() {
    closeEditor()
    Qt.callLater(function() { addField.forceActiveFocus() })
  }

  function addTask() {
    var title = addField.text.trim()
    if (title === "") return
    ctx.host.act(Model.taskAddArgs({ title: title, priority: addPriority }))
    addField.text = ""
  }

  TaskEditor {
    id: editor
    ctx: page.ctx
    width: parent.width
    visible: page.editing
    onDone: page.closeEditor()
  }

  // ---- Add a task.
  Row {
    width: parent.width
    spacing: Style.space(6)
    visible: !page.editing

    Field {
      id: addField
      ctx: page.ctx
      width: parent.width - priorityChip.width - detailChip.width - addChip.width - parent.spacing * 3
      placeholderText: page.ctx.t("tasks.addPlaceholder")
      onAccepted: page.addTask()
      onCancelled: text = ""
    }
    Chip {
      id: priorityChip
      ctx: page.ctx
      anchors.verticalCenter: parent.verticalCenter
      iconText: "󰈿"
      foreground: page.addPriority === "low" ? page.ctx.dim : page.addPriority === "high" ? page.ctx.accent : page.ctx.fg
      tooltipText: page.ctx.t("priority." + page.addPriority)
      onClicked: page.addPriority = page.addPriority === "medium" ? "high" : page.addPriority === "high" ? "low" : "medium"
    }
    Chip {
      id: detailChip
      ctx: page.ctx
      anchors.verticalCenter: parent.verticalCenter
      iconText: "󰏫"
      tooltipText: page.ctx.t("tasks.addDetails")
      onClicked: {
        editor.load(null, addField.text.trim())
        addField.text = ""
        page.editing = true
      }
    }
    Chip {
      id: addChip
      ctx: page.ctx
      anchors.verticalCenter: parent.verticalCenter
      iconText: "󰐕"
      tooltipText: page.ctx.t("tasks.add")
      enabled: addField.text.trim() !== ""
      onClicked: page.addTask()
    }
  }

  // ---- Which tasks, in what order.
  Item {
    width: parent.width
    height: filterRow.height
    visible: !page.editing

    Row {
      id: filterRow
      spacing: Style.space(4)

      Repeater {
        model: [
          { key: "open", count: page.counts.open },
          { key: "today", count: page.counts.today },
          { key: "done", count: page.counts.done },
          { key: "archived", count: page.counts.archived }
        ]

        Chip {
          required property var modelData
          ctx: page.ctx
          bordered: false
          horizontalPadding: Style.space(8)
          selected: page.filter === modelData.key
          text: page.ctx.t("tasks.filter." + modelData.key) + (modelData.count > 0 ? " " + modelData.count : "")
          onClicked: page.filter = modelData.key
        }
      }
    }
    Chip {
      ctx: page.ctx
      anchors.right: parent.right
      anchors.verticalCenter: parent.verticalCenter
      bordered: false
      horizontalPadding: Style.space(6)
      iconText: "󰒺"
      text: page.ctx.t("tasks.sort." + page.sort)
      onClicked: page.sort = Model.nextSort(page.sort)
    }
  }

  Field {
    id: searchField
    ctx: page.ctx
    width: parent.width
    visible: !page.editing && page.tasks.length > 0
    placeholderText: page.ctx.t("tasks.search")
    onCancelled: text = ""
  }

  // ---- The list.
  Column {
    width: parent.width
    spacing: Style.space(1)
    visible: !page.editing

    Repeater {
      model: page.shown

      TaskRow {
        required property var modelData
        ctx: page.ctx
        task: modelData
      }
    }

    FocusText {
      ctx: page.ctx
      width: parent.width
      visible: page.shown.length === 0
      topPadding: Style.space(16)
      bottomPadding: Style.space(16)
      muted: true
      horizontalAlignment: Text.AlignHCenter
      text: searchField.text.trim() !== "" ? page.ctx.t("tasks.noMatch") : page.ctx.t("tasks.empty." + page.filter)
    }
  }
}
