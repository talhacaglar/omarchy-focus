import QtQuick
import qs.Commons

// A label on the left, its control on the right.
Item {
  id: row
  required property var ctx
  property string label: ""
  property string description: ""
  // Makes the whole row one click target, for a control that's only a display.
  property bool clickable: false
  default property alias control: slot.children
  signal clicked()

  width: parent ? parent.width : 0
  implicitHeight: Math.max(labels.implicitHeight, slot.childrenRect.height, Style.space(30))

  MouseArea {
    anchors.fill: parent
    enabled: row.clickable
    cursorShape: row.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
    onClicked: row.clicked()
  }

  Column {
    id: labels
    anchors.left: parent.left
    anchors.right: slot.left
    anchors.rightMargin: Style.space(12)
    anchors.verticalCenter: parent.verticalCenter
    spacing: Style.space(1)

    FocusText {
      ctx: row.ctx
      width: parent.width
      text: row.label
    }
    FocusText {
      ctx: row.ctx
      width: parent.width
      visible: row.description !== ""
      muted: true
      text: row.description
      wrapMode: Text.WordWrap
      maximumLineCount: 2
      font.pixelSize: Style.font.caption
    }
  }

  Item {
    id: slot
    anchors.right: parent.right
    anchors.verticalCenter: parent.verticalCenter
    width: childrenRect.width
    height: childrenRect.height
  }
}
