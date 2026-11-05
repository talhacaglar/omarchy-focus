import QtQuick
import qs.Commons
import "Model.js" as Model

// How it's been going: today against the goal, the last days and weeks, when
// you focus best, and on what.
Column {
  id: page
  required property var ctx

  readonly property var stats: ctx.stats
  readonly property var heatmap: ctx.host ? ctx.host.heatmap : []
  readonly property var week: heatmap.slice(-7)
  readonly property int weekMax: Math.max(Model.weekMax(week), 1)
  readonly property int weekTotal: week.reduce(function(sum, day) { return sum + day.minutes }, 0)
  readonly property var hours: stats && stats.hours ? stats.hours : []
  readonly property int hoursMax: Math.max.apply(null, hours.concat([1]))
  readonly property int topTaskMax: stats && stats.top_tasks && stats.top_tasks.length ? Math.max(stats.top_tasks[0].minutes, 1) : 1
  // The day under the pointer, spelled out below the chart it belongs to.
  property var hoveredDay: null

  spacing: Style.space(14)

  function parseDay(iso) {
    return new Date(iso + "T12:00:00")
  }

  function dayCaption(day) {
    return ctx.locale.toString(parseDay(day.date), "d MMMM ddd") + "  ·  " + ctx.dur(day.minutes)
  }

  // ---- Today.
  Column {
    width: parent.width
    spacing: Style.space(8)

    Item {
      width: parent.width
      height: todayLabel.implicitHeight
      SectionLabel { id: todayLabel; ctx: page.ctx; text: page.ctx.t("stats.today") }
      FocusText {
        ctx: page.ctx
        anchors.right: parent.right
        text: page.stats ? page.ctx.dur(page.stats.today_focus_minutes) + " / " + page.ctx.dur(page.ctx.goal) : ""
        font.pixelSize: Style.font.bodySmall
      }
    }
    Rectangle {
      width: parent.width
      height: Style.space(6)
      radius: height / 2
      color: page.ctx.track
      Rectangle {
        height: parent.height
        radius: parent.radius
        color: page.ctx.accent
        width: page.stats ? parent.width * Math.min(1, page.stats.today_focus_minutes / page.ctx.goal) : 0
      }
    }
    Row {
      spacing: Style.space(26)
      Tile { statValue: page.stats ? String(page.stats.today_pomodoros) : "0"; statLabel: page.ctx.t("stats.pomodoros") }
      Tile { statValue: page.stats ? String(page.stats.today_tasks_done) : "0"; statLabel: page.ctx.t("stats.tasksDone") }
      Tile { statValue: page.stats ? page.ctx.tn("stats.days", page.stats.streak_days) : ""; statLabel: page.ctx.t("stats.streak") }
    }
  }

  Rectangle { width: parent.width; height: Style.spacing.hairline; color: page.ctx.track }

  // ---- This week.
  Column {
    width: parent.width
    spacing: Style.space(8)

    SectionLabel { ctx: page.ctx; text: page.ctx.t("stats.thisWeek") }

    Row {
      spacing: Style.space(26)
      Tile { statValue: page.stats ? page.ctx.dur(page.stats.week_focus_minutes) : ""; statLabel: page.ctx.t("stats.focusTime") }
      Tile { statValue: page.stats ? String(page.stats.week_tasks_done) : "0"; statLabel: page.ctx.t("stats.tasksDone") }
      Tile {
        statValue: page.stats && page.stats.completion_rate !== null ? Math.round(page.stats.completion_rate * 100) + "%" : "—"
        statLabel: page.ctx.t("stats.finished")
      }
      Tile { statValue: page.stats ? String(page.stats.week_sessions_cut) : "0"; statLabel: page.ctx.t("stats.cut") }
      Tile { statValue: page.stats ? String(page.stats.week_guard_sessions) : "0"; statLabel: page.ctx.t("stats.guards") }
    }
  }

  Rectangle { width: parent.width; height: Style.spacing.hairline; color: page.ctx.track }

  // ---- Seven days and twelve weeks, side by side.
  Row {
    width: parent.width
    spacing: Style.space(26)

    Column {
      spacing: Style.space(6)

      SectionLabel { ctx: page.ctx; text: page.ctx.t("stats.sevenDays").arg(page.ctx.dur(page.weekTotal)) }

      Row {
        spacing: Style.space(8)
        height: Style.space(72)

        Repeater {
          model: page.week

          Column {
            id: bar
            required property var modelData
            required property int index
            spacing: Style.space(4)
            anchors.bottom: parent.bottom

            Rectangle {
              anchors.horizontalCenter: parent.horizontalCenter
              width: Style.space(16)
              radius: Style.space(3)
              height: Math.max(Style.space(3), Style.space(52) * bar.modelData.minutes / page.weekMax)
              color: bar.modelData.minutes > 0 ? page.ctx.accent : page.ctx.track
              opacity: bar.index === 6 ? 1 : 0.75
            }
            FocusText {
              ctx: page.ctx
              anchors.horizontalCenter: parent.horizontalCenter
              muted: bar.index !== 6
              text: page.ctx.locale.toString(page.parseDay(bar.modelData.date), "ddd").substring(0, 2)
              font.pixelSize: Style.font.caption
            }
            HoverHandler {
              onHoveredChanged: page.hoveredDay = hovered ? bar.modelData : (page.hoveredDay === bar.modelData ? null : page.hoveredDay)
            }
          }
        }
      }
    }

    Column {
      spacing: Style.space(6)

      SectionLabel { ctx: page.ctx; text: page.ctx.t("stats.twelveWeeks") }

      Row {
        spacing: Style.space(3)

        Repeater {
          model: Model.heatColumns(page.heatmap, page.ctx.goal)

          Column {
            required property var modelData
            spacing: Style.space(3)

            Repeater {
              model: parent.modelData

              Rectangle {
                id: cell
                required property var modelData
                width: Style.space(9)
                height: width
                radius: Style.space(2)
                color: modelData && modelData.level > 0 ? page.ctx.accent : page.ctx.fg
                opacity: modelData ? [0.1, 0.3, 0.5, 0.75, 1][modelData.level] : 0
                HoverHandler {
                  enabled: !!cell.modelData
                  onHoveredChanged: page.hoveredDay = hovered ? cell.modelData : (page.hoveredDay === cell.modelData ? null : page.hoveredDay)
                }
              }
            }
          }
        }
      }
    }
  }

  FocusText {
    ctx: page.ctx
    width: parent.width
    muted: true
    font.pixelSize: Style.font.caption
    text: page.hoveredDay ? page.dayCaption(page.hoveredDay) : page.ctx.t("stats.hoverHint")
  }

  Rectangle { width: parent.width; height: Style.spacing.hairline; color: page.ctx.track }

  // ---- Focus by hour of day.
  Column {
    width: parent.width
    spacing: Style.space(6)

    Item {
      width: parent.width
      height: hoursLabel.implicitHeight
      SectionLabel { id: hoursLabel; ctx: page.ctx; text: page.ctx.t("stats.byHour") }
      FocusText {
        ctx: page.ctx
        anchors.right: parent.right
        visible: !!page.stats && page.stats.peak_start !== null
        font.pixelSize: Style.font.caption
        color: page.ctx.accent
        text: {
          if (!page.stats || page.stats.peak_start === null) return ""
          var start = page.stats.peak_start
          return page.ctx.t("stats.peak").arg(Model.pad2(start) + ":00").arg(Model.pad2((start + 2) % 24) + ":00")
        }
      }
    }

    Row {
      id: hourBars
      width: parent.width
      height: Style.space(36)
      spacing: Style.space(2)

      Repeater {
        model: page.hours

        Rectangle {
          required property int modelData
          anchors.bottom: parent.bottom
          width: (hourBars.width - hourBars.spacing * 23) / 24
          height: Math.max(Style.space(2), hourBars.height * modelData / page.hoursMax)
          radius: Style.space(1)
          color: modelData > 0 ? page.ctx.accent : page.ctx.track
        }
      }
    }

    Item {
      width: parent.width
      height: axisProbe.implicitHeight
      FocusText { id: axisProbe; ctx: page.ctx; x: 0; muted: true; text: "00"; font.pixelSize: Style.font.caption }
      FocusText { ctx: page.ctx; x: parent.width * 0.25; muted: true; text: "06"; font.pixelSize: Style.font.caption }
      FocusText { ctx: page.ctx; x: parent.width * 0.5; muted: true; text: "12"; font.pixelSize: Style.font.caption }
      FocusText { ctx: page.ctx; x: parent.width * 0.75; muted: true; text: "18"; font.pixelSize: Style.font.caption }
    }
  }

  // ---- Where the time went.
  Column {
    width: parent.width
    spacing: Style.space(6)
    visible: !!page.stats && !!page.stats.top_tasks && page.stats.top_tasks.length > 0

    Rectangle { width: parent.width; height: Style.spacing.hairline; color: page.ctx.track }

    SectionLabel { ctx: page.ctx; topPadding: Style.space(8); text: page.ctx.t("stats.topTasks") }

    Repeater {
      model: page.stats && page.stats.top_tasks ? page.stats.top_tasks : []

      Item {
        required property var modelData
        width: parent.width
        height: Style.space(24)

        Rectangle {
          anchors.left: parent.left
          anchors.verticalCenter: parent.verticalCenter
          height: parent.height
          radius: Style.cornerRadius
          width: parent.width * parent.modelData.minutes / page.topTaskMax
          color: page.ctx.track
        }
        FocusText {
          ctx: page.ctx
          anchors.left: parent.left
          anchors.leftMargin: Style.space(8)
          anchors.right: taskMinutes.left
          anchors.rightMargin: Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          text: parent.modelData.title === "Unassigned" ? page.ctx.t("timer.noTask") : parent.modelData.title
          font.pixelSize: Style.font.bodySmall
        }
        FocusText {
          id: taskMinutes
          ctx: page.ctx
          anchors.right: parent.right
          anchors.rightMargin: Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          text: page.ctx.dur(parent.modelData.minutes)
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }

  // ---- What stayed blocked.
  Column {
    width: parent.width
    spacing: Style.space(4)
    visible: !!page.stats && !!page.stats.blocked_sites && page.stats.blocked_sites.length > 0

    Rectangle { width: parent.width; height: Style.spacing.hairline; color: page.ctx.track }

    SectionLabel { ctx: page.ctx; topPadding: Style.space(8); text: page.ctx.t("stats.blockedSites") }

    Repeater {
      model: page.stats && page.stats.blocked_sites ? page.stats.blocked_sites : []

      Item {
        required property var modelData
        width: parent.width
        height: Style.space(20)

        FocusText {
          ctx: page.ctx
          anchors.left: parent.left
          anchors.right: siteCount.left
          anchors.rightMargin: Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          text: parent.modelData.domain
          font.pixelSize: Style.font.bodySmall
        }
        FocusText {
          id: siteCount
          ctx: page.ctx
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          muted: true
          text: page.ctx.tn("stats.sessions", parent.modelData.sessions)
          font.pixelSize: Style.font.bodySmall
        }
      }
    }
  }

  component Tile: Column {
    property string statValue: ""
    property string statLabel: ""
    spacing: Style.space(2)
    FocusText {
      ctx: page.ctx
      text: parent.statValue
      font.pixelSize: Style.font.title
    }
    SectionLabel {
      ctx: page.ctx
      text: parent.statLabel
    }
  }
}
