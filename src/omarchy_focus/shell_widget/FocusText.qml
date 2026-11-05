import QtQuick
import qs.Commons

// Everything the panel writes goes through this: plain text only, because
// task titles and domains must never be read as markup.
Text {
  required property var ctx
  property bool muted: false

  textFormat: Text.PlainText
  color: muted ? ctx.dim : ctx.fg
  font.family: ctx.fontFamily
  font.pixelSize: Style.font.body
  elide: Text.ElideRight
}
