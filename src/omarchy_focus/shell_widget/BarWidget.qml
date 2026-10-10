import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model

// Omarchy Focus bar pill.
//
// Data flow: `omarchy-focus status --json` runs only when something changes.
// The CLI touches $XDG_RUNTIME_DIR/omarchy-focus.changed after every state
// change and this widget watches that file, so start/stop/task edits from
// the TUI, CLI or keybindings show up instantly. Between refreshes the
// countdown is computed locally from `ends_at_ms`, so no process runs per
// second. A slow heartbeat catches day rollover and session expiry.
BarWidget {
  id: root
  moduleName: "omarchy-focus"

  readonly property string home: Quickshell.env("HOME")
  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") || ("/tmp/" + Quickshell.env("UID"))
  readonly property string cli: String(setting("command", "omarchy-focus"))
  readonly property int refreshSec: Math.max(10, parseInt(setting("refreshIntervalSec", 30), 10) || 30)
  readonly property int guardMinutes: Math.max(5, parseInt(setting("guardMinutes", 50), 10) || 50)
  readonly property bool showIdleCount: setting("showIdleCount", true) !== false

  property var state: null
  property string error: ""
  property double nowMs: Date.now()
  property bool refreshQueued: false
  readonly property double loadStamp: Date.now()

  readonly property string mode: Model.mode(state)
  readonly property bool ticking: mode === "work" || mode === "break" || (mode === "guard" && !!(state && state.focus.ends_at_ms))
  readonly property real progress: Model.progress(state, nowMs)
  readonly property int remaining: Model.remaining(state, nowMs)
  readonly property bool hasSession: mode === "work" || mode === "break" || mode === "paused"

  // A login shell resolves the CLI through PATH, so pacman (/usr/bin), pip
  // and install.sh (~/.local/bin) installs all work.
  function argv(args) {
    return ["bash", "-lc", 'exec "$@"', "bash", root.cli].concat(args)
  }

  function refresh() {
    if (stateProc.running) {
      refreshQueued = true
      return
    }
    stateProc.running = true
  }

  // Runs a CLI subcommand, then refreshes. Commands that need root (the site
  // guard) get a polkit dialog from the CLI because there is no terminal.
  function act(args) {
    actionProc.command = root.argv(args)
    actionProc.running = true
  }

  function openApp() {
    Quickshell.execDetached(["bash", "-lc", "omarchy-launch-or-focus-tui omarchy-focus tui || xdg-terminal-exec -e omarchy-focus tui"])
  }

  function startPomodoro(taskId) {
    act(taskId ? ["start", "--task-id", String(taskId)] : ["start"])
  }

  function primaryAction() {
    if (mode === "work" || mode === "break") act(["pause"])
    else if (mode === "paused") act(["resume"])
    else if (mode === "break-ready") act(["break", "start"])
    else startPomodoro(0)
  }

  function toggleGuard() {
    if (state && state.focus && state.focus.active) act(["focus", "off"])
    else act(["focus", "on", "--minutes", String(guardMinutes)])
  }

  // Shape contract for shell summon/hide/toggle routing (see the weather
  // widget): the bar talks to this root, which forwards to the panel.
  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  readonly property real openPanelIndicatorWidth: button.implicitWidth * 0.55

  function open() { if (panelLoader.item) panelLoader.item.openFromHotkey() }
  function close() { if (panelLoader.item) panelLoader.item.close() }
  function toggle() { if (panelLoader.item) panelLoader.item.toggle() }
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    target.bar = root.bar
    target.settings = root.settings
    target.anchorItem = button
    target.hostWidget = root
  }

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  onBarChanged: injectPanel()
  // Settings arrive after creation (and can point at another CLI), so
  // refresh whenever they change rather than only on startup.
  onSettingsChanged: {
    injectPanel()
    Qt.callLater(refresh)
  }
  onCliChanged: Qt.callLater(refresh)
  Component.onCompleted: Qt.callLater(refresh)

  Process {
    id: stateProc
    command: root.argv(["status", "--json"])
    stdout: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var raw = String(text || "").trim()
        if (!raw) return
        try {
          root.state = JSON.parse(raw)
          root.error = ""
          root.nowMs = Date.now()
        } catch (e) {
          root.error = "Unreadable status from " + root.cli
        }
      }
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var message = String(text || "").trim()
        if (message) root.error = message.split("\n").pop()
      }
    }
    onExited: function(exitCode) {
      if (exitCode !== 0 && !root.error) root.error = "omarchy-focus exited with " + exitCode
      // The stamp file exists once the CLI has run; start watching it.
      if (!stamp.loaded) stamp.reload()
    }
    // Drain the queue on any stop, including a command that failed to start
    // (which never reports an exit).
    onRunningChanged: {
      if (running || !root.refreshQueued) return
      root.refreshQueued = false
      Qt.callLater(root.refresh)
    }
  }

  Process {
    id: actionProc
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var message = String(text || "").trim()
        if (message) Quickshell.execDetached(["notify-send", "-a", "Omarchy Focus", "Omarchy Focus", message.split("\n").pop()])
      }
    }
    onExited: root.refresh()
  }

  FileView {
    id: stamp
    property bool loaded: false
    path: root.runtimeDir + "/omarchy-focus.changed"
    watchChanges: true
    printErrors: false
    onLoaded: loaded = true
    onFileChanged: {
      reload()
      debounce.restart()
    }
  }

  // Coalesce bursts (a start touches the stamp more than once).
  Timer {
    id: debounce
    interval: 120
    onTriggered: root.refresh()
  }

  // Local countdown. Only runs while something is counting down.
  Timer {
    interval: 1000
    repeat: true
    running: root.ticking
    onTriggered: {
      root.nowMs = Date.now()
      // At zero the CLI must record the session and queue the break.
      if (root.hasSession && root.remaining <= 0) root.refresh()
      else if (root.mode === "guard" && Model.focusRemaining(root.state, root.nowMs) <= 0) root.refresh()
    }
  }

  Timer {
    interval: root.refreshSec * 1000
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  Loader {
    id: panelLoader
    active: true
    // The query defeats the engine's per-URL component cache, so a plugin
    // hot-reload (or an upgrade) picks up the new popup without a restart.
    source: Qt.resolvedUrl("FocusPanel.qml") + "?v=" + root.loadStamp
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  WidgetButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.vertical ? Model.icon(root.state) : Model.pillText(root.state, root.nowMs, root.showIdleCount)
    centerFigures: false
    active: root.mode === "break-ready"
    tooltipText: root.error !== "" ? root.error : ""

    onPressed: function(b) {
      if (b === Qt.RightButton) root.primaryAction()
      else if (b === Qt.MiddleButton) root.toggleGuard()
      else root.toggle()
    }
  }

  // Session progress as a hairline under the pill.
  Rectangle {
    visible: root.hasSession && !root.vertical
    anchors.left: button.left
    anchors.bottom: button.bottom
    anchors.leftMargin: Style.space(6)
    anchors.bottomMargin: Style.space(2)
    height: Math.max(1, Style.space(2))
    radius: height / 2
    width: Math.max(0, (button.width - Style.space(12)) * root.progress)
    color: root.mode === "work" ? Commons.Color.accent : root.bar ? root.bar.barForeground : Commons.Color.foreground
    opacity: root.mode === "paused" ? 0.45 : 0.9

    Behavior on width {
      enabled: !Style.reduceMotion
      NumberAnimation { duration: 400; easing.type: Easing.OutCubic }
    }
  }

  ShellIpc {
    target: "omarchy-focus"

    function open(): void { root.open() }
    function close(): void { root.close() }
    function show(): void { root.open() }
    function hide(): void { root.close() }
    function toggle(): void { root.toggle() }
    function refresh(): void { root.refresh() }
  }
}
