import QtQuick

// Circular progress ring, 0..1 clockwise from 12 o'clock.
Canvas {
  property real progress: 0
  property real thickness: 6
  property color trackColor: "#33ffffff"
  property color fillColor: "white"

  onProgressChanged: requestPaint()
  onTrackColorChanged: requestPaint()
  onFillColorChanged: requestPaint()
  onWidthChanged: requestPaint()
  onHeightChanged: requestPaint()

  onPaint: {
    var ctx = getContext("2d")
    ctx.reset()
    var radius = Math.min(width, height) / 2 - thickness / 2
    var cx = width / 2
    var cy = height / 2
    ctx.lineWidth = thickness
    ctx.lineCap = "round"

    ctx.strokeStyle = trackColor
    ctx.beginPath()
    ctx.arc(cx, cy, radius, 0, Math.PI * 2)
    ctx.stroke()

    var value = Math.max(0, Math.min(1, progress))
    if (value <= 0) return
    ctx.strokeStyle = fillColor
    ctx.beginPath()
    ctx.arc(cx, cy, radius, -Math.PI / 2, -Math.PI / 2 + value * Math.PI * 2)
    ctx.stroke()
  }
}
