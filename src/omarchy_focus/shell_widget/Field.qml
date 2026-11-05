import QtQuick
import qs.Commons
import qs.Ui as Ui

// Text input that tells the panel it has the keyboard, and gives it back on Esc.
Ui.TextField {
  id: field
  required property var ctx
  signal cancelled()

  foreground: ctx.fg
  accent: ctx.accent
  font.family: ctx.fontFamily
  font.pixelSize: Style.font.body
  selectByMouse: true
  maximumLength: 500

  onActiveFocusChanged: ctx.noteField(field, activeFocus)
  Keys.onEscapePressed: function(event) {
    field.cancelled()
    field.ctx.releaseField()
    event.accepted = true
  }
}
