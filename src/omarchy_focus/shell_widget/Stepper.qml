import QtQuick
import qs.Commons

// − value +. Shows the new value at once; `value` catches up after the CLI ran.
Row {
  id: stepper
  required property var ctx
  property int value: 0
  property int from: 0
  property int to: 100
  property int step: 1
  property string text: ""
  signal changed(int value)

  property int shown: value
  onValueChanged: shown = value
  spacing: Style.space(4)

  function nudge(direction) {
    var next = Math.max(from, Math.min(to, shown + direction * step))
    if (next === shown) return
    shown = next
    changed(next)
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
    anchors.verticalCenter: parent.verticalCenter
    width: Style.space(78)
    horizontalAlignment: Text.AlignHCenter
    text: stepper.text !== "" ? stepper.text : String(stepper.shown)
    font.features: { "tnum": 1 }
  }
  Chip {
    ctx: stepper.ctx
    iconText: "󰐕"
    enabled: stepper.shown < stepper.to
    anchors.verticalCenter: parent.verticalCenter
    onClicked: stepper.nudge(1)
  }
}
