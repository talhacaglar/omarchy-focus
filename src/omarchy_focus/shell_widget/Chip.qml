import QtQuick
import qs.Commons
import qs.Ui as Ui

// The panel's small button: a preset, a filter, a row action.
Ui.Button {
  required property var ctx

  bordered: true
  foreground: ctx.fg
  accent: ctx.accent
  fontFamily: ctx.fontFamily
  fontSize: Style.font.bodySmall
  iconSize: Style.font.body
  horizontalPadding: Style.space(10)
  verticalPadding: Style.space(4)
  opacity: enabled ? 1 : 0.4
}
