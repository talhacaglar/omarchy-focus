import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model

// Omarchy Focus bar pill, and the only way in: the panel it opens does
// everything (timer, tasks, sites, stats, settings).
//
// Data flow: `omarchy-focus status --json` runs only when something changes.
// The CLI touches $XDG_RUNTIME_DIR/omarchy-focus.changed after every state
// change and this widget watches that file, so changes from the panel, CLI or
// keybindings show up instantly. Between refreshes the countdown is computed
// locally from `ends_at_ms`, so no process runs per second. A slow heartbeat
// catches day rollover and session expiry.
BarWidget {
  id: root
  moduleName: "omarchy-focus"

  readonly property string home: Quickshell.env("HOME")
  readonly property string runtimeDir: Quickshell.env("XDG_RUNTIME_DIR") || ("/tmp/" + Quickshell.env("UID"))
  readonly property string cli: String(setting("command", "omarchy-focus"))
  readonly property int refreshSec: Math.max(10, parseInt(setting("refreshIntervalSec", 30), 10) || 30)
  readonly property bool showIdleCount: setting("showIdleCount", true) !== false

  property var state: null
  // Split out of `state` and only replaced when they really change, so a
  // refresh doesn't rebuild the lists the user is hovering or scrolling.
  property var tasks: []
  property var sites: []
  property var heatmap: []
  property var stats: null
  property var signatures: ({})

  property string error: ""
  property string actionError: ""
  property double nowMs: Date.now()
  property bool refreshQueued: false

  // Actions run one at a time, in order, so quick clicks on a stepper or a
  // password dialog holding up the queue never lose a click.
  property var actionQueue: []
  property string actionPayload: ""

  property real wheelAccumulator: 0
  property int wheelMinutes: 0

  readonly property string mode: Model.mode(state)
  readonly property string guardState: Model.guardState(state, nowMs)
  readonly property bool hasSession: mode === "work" || mode === "break" || mode === "paused"
  readonly property bool ticking: mode === "work" || mode === "break" || guardState === "timed"
  readonly property real progress: Model.progress(state, nowMs)
  readonly property int remaining: Model.remaining(state, nowMs)

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

  function keep(name, value) {
    var signature = JSON.stringify(value)
    if (signatures[name] === signature) return
    signatures[name] = signature
    root[name] = value
  }

  function applyState(parsed) {
    if (!parsed.schema || parsed.schema < 2) {
      root.error = "This widget needs a newer omarchy-focus CLI (0.3 or later)"
      return
    }
    root.state = parsed
    root.error = ""
    root.nowMs = Date.now()
    keep("tasks", parsed.tasks || [])
    keep("sites", parsed.sites || [])
    keep("heatmap", parsed.heatmap || [])
    keep("stats", parsed.stats || null)
  }

  // Runs a CLI command, then refreshes. Arguments travel over stdin: task
  // titles and domains on a command line are readable by every local user
  // through /proc. Commands that need root (the site guard) get a polkit
  // dialog from the CLI because there is no terminal.
  function act(args) {
    actionQueue.push(args)
    drainActions()
  }

  function drainActions() {
    if (actionProc.running || actionQueue.length === 0) return
    actionPayload = JSON.stringify(actionQueue.shift()) + "\n"
    actionProc.stdinEnabled = true
    actionProc.running = true
  }

  function reportActionError(message) {
    if (root.opened) {
      root.actionError = message
      actionErrorClear.restart()
    } else {
      Quickshell.execDetached(["notify-send", "-a", "Omarchy Focus", "Omarchy Focus", message])
    }
  }

  function startPomodoro(taskId) {
    act(Model.startArgs(taskId, 0, null))
  }

  function primaryAction() {
    if (mode === "work" || mode === "break") act(["pause"])
    else if (mode === "paused") act(["resume"])
    else if (mode === "break-ready") act(["break", "start"])
    else startPomodoro(0)
  }

  function guardOn(minutes, strict) {
    act(Model.guardArgs(minutes, strict))
  }

  function toggleGuard() {
    if (state && state.focus && state.focus.active) act(["focus", "off"])
    else if (state) guardOn(state.settings.guard_minutes, state.settings.strict_mode_default)
  }

  // Adds to whatever is counting down: the session, else the guard.
  function adjust(minutes) {
    if (hasSession) act(["adjust", String(minutes)])
    else if (guardState === "timed") act(["focus", "adjust", String(minutes)])
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
          root.applyState(JSON.parse(raw))
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
    command: root.argv(["--args-from-stdin"])
    stdinEnabled: true
    onStarted: {
      write(root.actionPayload)
      stdinEnabled = false
    }
    stderr: StdioCollector {
      waitForEnd: true
      onStreamFinished: {
        var message = String(text || "").trim()
        if (message) root.reportActionError(message.split("\n").pop())
      }
    }
    onRunningChanged: {
      if (running) return
      if (root.actionQueue.length > 0) Qt.callLater(root.drainActions)
      else Qt.callLater(root.refresh)
    }
  }

  Timer {
    id: actionErrorClear
    interval: 8000
    onTriggered: root.actionError = ""
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
      // At zero the CLI must record the session and queue the break. A guard
      // that reaches zero gets one refresh too: `ticking` goes false with it,
      // so one that can't be released without root isn't polled every second.
      if (root.hasSession && root.remaining <= 0) root.refresh()
      else if (root.guardState === "expired") root.refresh()
    }
  }

  Timer {
    interval: root.refreshSec * 1000
    repeat: true
    running: true
    onTriggered: root.refresh()
  }

  // Scrolling on the pill adds or takes minutes; a burst becomes one change.
  Timer {
    id: wheelCommit
    interval: 180
    onTriggered: {
      var minutes = root.wheelMinutes
      root.wheelMinutes = 0
      if (minutes !== 0) root.adjust(minutes)
    }
  }

  Loader {
    id: panelLoader
    active: true
    // The shell loads plugins from a qs:// URL, where QML can't see sibling
    // files as types. Under file:// the panel finds its pages. The shell clears
    // its component cache when a plugin reloads, so edits are still picked up.
    source: String(Qt.resolvedUrl("FocusPanel.qml")).replace(/^qs:\/\//, "file://")
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

    onWheelMoved: function(delta) {
      if (!root.hasSession && root.guardState !== "timed") return
      var wheel = Util.wheelSteps(root.wheelAccumulator, delta)
      root.wheelAccumulator = wheel.remainder
      if (wheel.steps === 0) return
      root.wheelMinutes += wheel.steps
      wheelCommit.restart()
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
      NumberAnimation { duration: Style.duration(400); easing.type: Easing.OutCubic }
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
    function tab(name: string): void { if (panelLoader.item) panelLoader.item.openTab(name) }
    // Whether the panel loaded, for checking an install without opening it.
    function health(): string { return panelLoader.status === Loader.Ready ? "ready" : "panel failed to load" }
  }
}
