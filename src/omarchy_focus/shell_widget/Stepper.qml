import QtQuick
import qs.Commons
import "Model.js" as Model

// − value +. Shows the new value at once; `value` catches up after the CLI ran.
// With `editable`, the value is a box you can click and type any number into:
// Enter keeps it, Esc drops it.
Row {
  id: stepper
  required property var ctx
  property int value: 0
  property int from: 0
  property int to: 100
  property int step: 1
  // Below this, − and + move by one, so short lengths aren't 5 minutes apart.
  property int fineBelow: 0
  property bool editable: false
  property string text: ""
  signal changed(int value)

  property int shown: value
  property bool editing: false
  readonly property string display: text !== "" ? text : String(shown)

  onValueChanged: {
    shown = value
    // Something else picked a value (a preset) while this was being typed in:
    // that pick wins.
    cancelEdit()
  }
  onDisplayChanged: if (!editing) input.text = display
  Component.onCompleted: input.text = display

  spacing: Style.space(4)

  function set(next) {
    next = Model.clampInt(next, from, to)
    if (next === shown) return
    shown = next
    changed(next)
  }

  function nudge(direction) {
    set(Model.stepValue(shown, direction, step, fineBelow))
  }

  function beginEdit() {
    editing = true
    input.text = String(shown)
    Qt.callLater(input.selectAll)
  }

  // Also called by a page before it acts on the value, in case the typing
  // wasn't confirmed with Enter.
  function commitEdit() {
    if (!editing) return
    editing = false
    var typed = parseInt(input.text, 10)
    input.text = display
    if (input.activeFocus) ctx.releaseField()
    if (!isNaN(typed)) set(typed)
  }

  function cancelEdit() {
    if (!editing) return
    editing = false
    input.text = display
    if (input.activeFocus) ctx.releaseField()
  }

  Chip {
    ctx: stepper.ctx
    iconText: "󰍴"
    enabled: stepper.shown > stepper.from
    anchors.verticalCenter: parent.verticalCenter
    onClicked: stepper.nudge(-1)
  }
  FocusText {
    ctx: stepper.ctx
    visible: !stepper.editable
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(78)
    horizontalAlignment: Text.AlignHCenter
    text: stepper.display
    font.features: { "tnum": 1 }
  }
  Field {
    id: input
    ctx: stepper.ctx
    visible: stepper.editable
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(78)
    horizontalPadding: Style.space(4)
    verticalPadding: Style.space(3)
    horizontalAlignment: TextInput.AlignHCenter
    font.pixelSize: Style.font.bodySmall
    font.features: { "tnum": 1 }
    inputMethodHints: Qt.ImhDigitsOnly
    onAccepted: stepper.commitEdit()
    onCancelled: stepper.cancelEdit()
  }
  // Field already watches its focus for the panel; this adds to that.
  Connections {
    target: input
    function onActiveFocusChanged() {
      if (input.activeFocus) stepper.beginEdit()
      else stepper.commitEdit()
    }
  }
  Chip {
    ctx: stepper.ctx
    iconText: "󰐕"
    enabled: stepper.shown < stepper.to
    anchors.verticalCenter: parent.verticalCenter
    onClicked: stepper.nudge(1)
  }
}
