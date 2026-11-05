import QtQuick
import qs.Commons
import "Model.js" as Model

// Every field of a task. Its values are loaded once, not bound to the state,
// so a refresh while you type never touches them.
Column {
  id: editor
  required property var ctx
  signal done()

  property var task: null
  property string priority: "medium"
  property int estimate: 0
  property bool confirmingDelete: false

  spacing: Style.space(10)

  function load(source, seedTitle) {
    task = source
    titleField.text = source ? source.title : seedTitle
    descriptionField.text = source ? source.description : ""
    tagsField.text = source ? (source.tags || []).join(", ") : ""
    dueField.text = source && source.due ? source.due.replace(" 00:00", "") : ""
    priority = source ? source.priority : "medium"
    estimate = source && source.estimate ? source.estimate : 0
    confirmingDelete = false
    Qt.callLater(function() { titleField.forceActiveFocus() })
  }

  function save() {
    var title = titleField.text.trim()
    if (title === "") {
      titleField.forceActiveFocus()
      return
    }
    var draft = {
      title: title,
      description: descriptionField.text.trim(),
      priority: priority,
      tags: tagsField.text.trim(),
      estimate: estimate,
      due: dueField.text.trim()
    }
    ctx.host.act(task ? Model.taskEditArgs(task.id, draft) : Model.taskAddArgs(draft))
    done()
  }

  SectionLabel {
    ctx: editor.ctx
    text: editor.task ? editor.ctx.t("editor.editTitle") : editor.ctx.t("editor.newTitle")
  }

  Field {
    id: titleField
    ctx: editor.ctx
    width: parent.width
    placeholderText: editor.ctx.t("editor.title")
    onAccepted: editor.save()
  }
  Field {
    id: descriptionField
    ctx: editor.ctx
    width: parent.width
    placeholderText: editor.ctx.t("editor.description")
    onAccepted: editor.save()
  }

  SettingRow {
    ctx: editor.ctx
    label: editor.ctx.t("editor.priority")

    Row {
      spacing: Style.space(4)
      Repeater {
        model: ["low", "medium", "high"]
        Chip {
          required property string modelData
          ctx: editor.ctx
          text: editor.ctx.t("priority." + modelData)
          selected: editor.priority === modelData
          onClicked: editor.priority = modelData
        }
      }
    }
  }

  SettingRow {
    ctx: editor.ctx
    label: editor.ctx.t("editor.estimate")

    Stepper {
      ctx: editor.ctx
      value: editor.estimate
      from: 0
      to: 600
      step: 5
      text: shown === 0 ? editor.ctx.t("editor.none") : editor.ctx.dur(shown)
      onChanged: function(value) { editor.estimate = value }
    }
  }

  Field {
    id: tagsField
    ctx: editor.ctx
    width: parent.width
    placeholderText: editor.ctx.t("editor.tags")
    onAccepted: editor.save()
  }

  Row {
    width: parent.width
    spacing: Style.space(4)

    Field {
      id: dueField
      ctx: editor.ctx
      width: parent.width - dueChips.width - parent.spacing
      placeholderText: editor.ctx.t("editor.due")
      onAccepted: editor.save()
    }
    Row {
      id: dueChips
      anchors.verticalCenter: parent.verticalCenter
      spacing: Style.space(2)

      Repeater {
        model: [
          { key: "due.today", days: 0 },
          { key: "due.tomorrow", days: 1 },
          { key: "editor.inWeek", days: 7 }
        ]
        Chip {
          required property var modelData
          ctx: editor.ctx
          bordered: false
          horizontalPadding: Style.space(6)
          text: editor.ctx.t(modelData.key)
          onClicked: dueField.text = Model.dueInDays(modelData.days, Date.now())
        }
      }
      Chip {
        ctx: editor.ctx
        bordered: false
        horizontalPadding: Style.space(6)
        iconText: "󰅖"
        tooltipText: editor.ctx.t("editor.clearDue")
        onClicked: dueField.text = ""
      }
    }
  }

  Item {
    width: parent.width
    height: mainButtons.height

    Row {
      id: mainButtons
      spacing: Style.space(6)

      Chip {
        ctx: editor.ctx
        iconText: "󰄬"
        text: editor.ctx.t("editor.save")
        selected: true
        onClicked: editor.save()
      }
      Chip {
        ctx: editor.ctx
        text: editor.ctx.t("editor.cancel")
        onClicked: editor.done()
      }
    }
    Row {
      anchors.right: parent.right
      spacing: Style.space(6)
      visible: !!editor.task

      Chip {
        ctx: editor.ctx
        bordered: false
        iconText: editor.task && editor.task.status === "archived" ? "󰑓" : "󰆧"
        text: editor.task && editor.task.status === "archived" ? editor.ctx.t("editor.unarchive") : editor.ctx.t("editor.archive")
        onClicked: {
          var next = editor.task.status === "archived" ? "pending" : "archived"
          editor.ctx.host.act(["tasks", "edit", String(editor.task.id), "--status=" + next])
          editor.done()
        }
      }
      Chip {
        ctx: editor.ctx
        bordered: false
        iconText: "󰩺"
        foreground: editor.confirmingDelete ? editor.ctx.urgent : editor.ctx.fg
        text: editor.confirmingDelete ? editor.ctx.t("task.confirmDelete") : editor.ctx.t("task.delete")
        onClicked: {
          if (!editor.confirmingDelete) {
            editor.confirmingDelete = true
            return
          }
          editor.ctx.host.act(["tasks", "delete", String(editor.task.id)])
          editor.done()
        }
      }
    }
  }
}
