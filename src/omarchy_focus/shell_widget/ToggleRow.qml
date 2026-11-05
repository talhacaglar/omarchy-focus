import QtQuick
import qs.Commons
import qs.Ui as Ui

// A setting that's on or off; the whole row is the click target.
SettingRow {
  id: row
  property bool checked: false
  signal toggled()

  clickable: true
  opacity: enabled ? 1 : 0.4
  onClicked: row.toggled()

  Ui.ToggleSwitch {
    checked: row.checked
    interactive: false
    foreground: row.ctx.fg
    accent: row.ctx.accent
  }
}
