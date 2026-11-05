import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import qs.Ui as Ui
import "Model.js" as Model

// The Omarchy Focus panel: five pages under one bar pill. This file owns the
// frame (tabs, scrolling, keys, strings); each page reads everything from it
// through `ctx`. All data comes from the host BarWidget.
//
// The base type is qualified on purpose: an unqualified `Panel` could
// resolve to a sibling file of the same name in this plugin directory.
Ui.Panel {
  id: root
  moduleName: "omarchy-focus"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  readonly property var barIdentity: hostWidget || root

  readonly property var host: hostWidget
  readonly property var model: host ? host.state : null
  readonly property var stats: host ? host.stats : null
  readonly property double nowMs: host ? host.nowMs : Date.now()
  readonly property string mode: Model.mode(model)
  readonly property string guardState: Model.guardState(model, nowMs)
  readonly property bool hasSession: mode === "work" || mode === "break" || mode === "paused"
  readonly property color fg: root.bar ? root.bar.foreground : Commons.Color.foreground
  readonly property color dim: Qt.rgba(fg.r, fg.g, fg.b, 0.62)
  readonly property color track: Qt.rgba(fg.r, fg.g, fg.b, 0.12)
  readonly property color accent: Commons.Color.accent
  readonly property color urgent: Commons.Color.urgent
  readonly property string fontFamily: root.bar ? root.bar.fontFamily : Style.font.family
  readonly property int goal: stats && stats.goal_minutes > 0 ? stats.goal_minutes : 150

  readonly property var tabs: [
    { name: "focus", icon: "󰔛" },
    { name: "tasks", icon: "󰄲" },
    { name: "sites", icon: "󰈈" },
    { name: "stats", icon: "󰄪" },
    { name: "settings", icon: "󰒓" }
  ]
  property int tab: 0

  // The text field with keyboard focus, if any: keys go to it, not the panel.
  property var activeField: null

  function noteField(field, focused) {
    if (focused) activeField = field
    else if (activeField === field) activeField = null
  }

  function releaseField() {
    if (panel.loadedContent) panel.loadedContent.forceActiveFocus()
  }

  // ---- Strings. A `language` on the widget entry beats the shell's language,
  // for a panel in Turkish on a desktop in English.

  Commons.Translations { id: strings; directory: Qt.resolvedUrl("i18n") }

  readonly property string languageOverride: {
    var value = host && host.settings ? String(host.settings.language || "") : ""
    return /^[A-Za-z]{2,3}(-[A-Za-z]{2,4})?$/.test(value) ? value : ""
  }

  FileView {
    id: overrideFile
    path: root.languageOverride ? strings.directoryPath + "/" + root.languageOverride + ".json" : ""
    blockLoading: true
    printErrors: false
  }

  readonly property var overrideStrings: {
    if (!root.languageOverride) return ({})
    try {
      return JSON.parse(overrideFile.text() || "{}")
    } catch (e) {
      return ({})
    }
  }

  readonly property var locale: Qt.locale(languageOverride ? languageOverride.replace("-", "_") : Commons.I18n.formatLocale)

  function t(key) {
    var value = overrideStrings[key]
    if (typeof value === "string" && value.length > 0) return value
    return strings.t(key)
  }

  function tn(key, count) {
    var value = overrideStrings[key]
    if (value && typeof value === "object") return String(count === 1 && value.one ? value.one : value.other).arg(count)
    return strings.tn(key, count).arg(count)
  }

  function dur(minutes) {
    return Model.minutesLabel(minutes, { h: t("unit.h"), m: t("unit.m") })
  }

  function dayLabel(ms) {
    return locale.toString(new Date(ms), "d MMM")
  }

  function dueLabel(task) {
    var kind = Model.dueKind(task, nowMs)
    if (kind === "today") return t("due.today")
    if (kind === "tomorrow") return t("due.tomorrow")
    if (kind === "overdue") return t("due.overdue").arg(dayLabel(task.due_at_ms))
    return kind ? dayLabel(task.due_at_ms) : ""
  }

  // Tags, due date and time spent, for the second line of a task row.
  function taskMeta(task) {
    var parts = []
    var due = dueLabel(task)
    if (due) parts.push(due)
    if (task.estimate) parts.push(dur(task.focus_minutes) + " / " + dur(task.estimate))
    else if (task.focus_minutes) parts.push(dur(task.focus_minutes))
    var tags = task.tags || []
    for (var i = 0; i < tags.length; i++) parts.push("#" + tags[i])
    return parts.join("  ·  ")
  }

  // ---- Opening and moving around

  function openFromHotkey() {
    root.controller.show()
    if (host) host.refresh()
  }

  function open() { openFromHotkey() }
  function close() { root.controller.hide() }
  function toggle() { root.opened ? root.close() : root.openFromHotkey() }

  function openTab(name) {
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].name === name) tab = i
    }
    openFromHotkey()
  }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      return root.bar.switchPanelFrom(root.barIdentity, direction)
    return false
  }

  function editTask(task) {
    tab = 1
    panel.ensureContent().tasksPage.edit(task)
  }

  function focusAddTask() {
    tab = 1
    panel.ensureContent().tasksPage.focusAdd()
  }

  function handleClose() {
    var content = panel.loadedContent
    if (content && tab === 1 && content.tasksPage.editing) content.tasksPage.closeEditor()
    else root.close()
  }

  function handleKey(text) {
    if (text >= "1" && text <= "5") tab = parseInt(text, 10) - 1
    else if (text === "a") focusAddTask()
    else if (text === "+" || text === "=") host.adjust(1)
    else if (text === "-") host.adjust(-1)
    else if (text === "p") host.primaryAction()
    else if (text === "g") host.toggleGuard()
    else if (text === "s" && hasSession) host.act(["stop"])
    else if (text === "s") host.startPomodoro(0)
    else if (text === "b" && mode === "break-ready") host.act(["break", "start"])
    else if (text === "n" && mode === "break-ready") host.act(["break", "skip"])
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: panel.loadedContent
    contentWidth: panel.fittedContentWidth(Style.space(500))
    contentHeight: panel.fittedContentHeight(panel.loadedContentHeight, Style.space(700))

    content: PanelKeyCatcher {
      id: keys
      property alias tasksPage: tasksPage
      anchors.fill: parent
      blocked: !!root.activeField
      implicitHeight: scroller.y + pageHost.implicitHeight

      onCloseRequested: root.handleClose()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onReturnRequested: if (root.tab === 0 && root.host) root.host.primaryAction()
      onTextKey: function(text) { if (root.host) root.handleKey(text) }
      onMoveRequested: function(dx, dy) {
        if (dx !== 0) root.tab = (root.tab + dx + root.tabs.length) % root.tabs.length
        if (dy !== 0) scroller.contentY = Math.max(0, Math.min(scroller.contentHeight - scroller.height, scroller.contentY + dy * Style.space(60)))
      }

      Row {
        id: tabRow
        width: parent.width
        spacing: Style.space(4)

        Repeater {
          model: root.tabs

          Ui.Button {
            required property var modelData
            required property int index
            width: (tabRow.width - tabRow.spacing * (root.tabs.length - 1)) / root.tabs.length
            iconText: modelData.icon
            text: root.t("tab." + modelData.name)
            selected: root.tab === index
            foreground: root.fg
            accent: root.accent
            fontFamily: root.fontFamily
            fontSize: Style.font.bodySmall
            iconSize: Style.font.body
            horizontalPadding: Style.space(4)
            onClicked: {
              root.tab = index
              scroller.contentY = 0
            }
          }
        }
      }

      // What just went wrong, in place of a notification while the panel is up.
      Rectangle {
        id: banner
        anchors.top: tabRow.bottom
        anchors.topMargin: visible ? Style.space(8) : 0
        width: parent.width
        visible: !!root.host && (root.host.actionError !== "" || root.host.error !== "")
        height: visible ? bannerText.implicitHeight + Style.space(12) : 0
        radius: Style.cornerRadius
        color: Qt.rgba(root.urgent.r, root.urgent.g, root.urgent.b, 0.18)

        FocusText {
          id: bannerText
          ctx: root
          anchors.left: parent.left
          anchors.right: parent.right
          anchors.verticalCenter: parent.verticalCenter
          anchors.margins: Style.space(10)
          text: root.host ? (root.host.actionError || root.host.error) : ""
          wrapMode: Text.WordWrap
          maximumLineCount: 3
          font.pixelSize: Style.font.bodySmall
        }
        MouseArea {
          anchors.fill: parent
          onClicked: if (root.host) root.host.actionError = ""
        }
      }

      Flickable {
        id: scroller
        anchors.top: banner.bottom
        anchors.topMargin: Style.space(14)
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.bottom: parent.bottom
        contentWidth: width
        contentHeight: pageHost.implicitHeight
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        interactive: contentHeight > height

        Item {
          id: pageHost
          // A sliver of room on the right: the flickable's clip would otherwise eat
          // the border of a button that ends on the edge at a fractional position.
          width: scroller.width - (scroller.interactive ? Style.space(10) : Style.space(2))
          implicitHeight: {
            switch (root.tab) {
            case 0: return timerPage.implicitHeight
            case 1: return tasksPage.implicitHeight
            case 2: return sitesPage.implicitHeight
            case 3: return statsPage.implicitHeight
            default: return settingsPage.implicitHeight
            }
          }

          TimerPage { id: timerPage; ctx: root; width: parent.width; visible: root.tab === 0 }
          TasksPage { id: tasksPage; ctx: root; width: parent.width; visible: root.tab === 1 }
          SitesPage { id: sitesPage; ctx: root; width: parent.width; visible: root.tab === 2 }
          StatsPage { id: statsPage; ctx: root; width: parent.width; visible: root.tab === 3 }
          SettingsPage { id: settingsPage; ctx: root; width: parent.width; visible: root.tab === 4 }
        }
      }

      // Where you are in a page too tall for the screen.
      Rectangle {
        visible: scroller.interactive
        anchors.right: scroller.right
        y: scroller.y + scroller.visibleArea.yPosition * scroller.height
        width: Style.space(3)
        height: Math.max(Style.space(24), scroller.visibleArea.heightRatio * scroller.height)
        radius: width / 2
        color: root.track
      }
    }
  }
}
