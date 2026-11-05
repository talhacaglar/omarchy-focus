import QtQuick
import qs.Commons
import qs.Ui as Ui
import "Model.js" as Model

// The site guard and what it blocks. Turning it on and changing an active
// block need root, so those clicks can bring up the password dialog; the list
// on its own and the timer don't.
Column {
  id: page
  required property var ctx

  readonly property var model: ctx.model
  readonly property var settings: model ? model.settings : null
  readonly property var guardInfo: model ? model.focus : null
  readonly property string guard: ctx.guardState
  readonly property var sites: ctx.host ? ctx.host.sites : []
  readonly property bool strictLocked: !!guardInfo && guardInfo.strict && guard === "timed"

  // 0 is "until I turn it off". Unset until touched, so it follows the settings.
  property int guardMinutes: -1
  property var strictChoice: null
  property string renaming: ""

  readonly property int startMinutes: guardMinutes >= 0 ? guardMinutes : (settings ? settings.guard_minutes : 50)
  readonly property bool strict: startMinutes > 0 && (strictChoice === null ? !!(settings && settings.strict_mode_default) : strictChoice)

  spacing: Style.space(12)

  function commitSite() {
    var domain = siteField.text.trim()
    if (domain === "") return
    if (renaming !== "") ctx.host.act(["focus", "edit-site", "--new-domain=" + domain, "--", renaming])
    else ctx.host.act(["focus", "add-site", "--", domain])
    cancelEdit()
  }

  function cancelEdit() {
    siteField.text = ""
    renaming = ""
  }

  function startRename(domain) {
    renaming = domain
    siteField.text = domain
    siteField.selectAll()
    siteField.forceActiveFocus()
  }

  // ---- Off: how long, how strict, go.
  Column {
    width: parent.width
    spacing: Style.space(10)
    visible: page.guard === "off"

    SectionLabel { ctx: page.ctx; text: page.ctx.t("guard.title") }

    Row {
      spacing: Style.space(6)

      Repeater {
        model: [25, 50, 90]

        Chip {
          required property int modelData
          ctx: page.ctx
          text: modelData + page.ctx.t("unit.m")
          selected: page.startMinutes === modelData
          onClicked: page.guardMinutes = modelData
        }
      }
      Chip {
        ctx: page.ctx
        iconText: "󰖉"
        text: page.ctx.t("guard.untilOff")
        selected: page.startMinutes === 0
        onClicked: page.guardMinutes = 0
      }
    }

    ToggleRow {
      ctx: page.ctx
      enabled: page.startMinutes > 0
      label: page.ctx.t("guard.strict")
      description: page.ctx.t("guard.strictHint")
      checked: page.strict
      onToggled: page.strictChoice = !page.strict
    }

    Chip {
      ctx: page.ctx
      anchors.horizontalCenter: parent.horizontalCenter
      iconText: "󰈈"
      text: page.startMinutes > 0 ? page.ctx.t("guard.startFor").arg(page.ctx.dur(page.startMinutes)) : page.ctx.t("guard.start")
      selected: true
      fontSize: Style.font.body
      horizontalPadding: Style.space(18)
      verticalPadding: Style.space(7)
      enabled: page.sites.some(function(site) { return site.enabled })
      onClicked: page.ctx.host.guardOn(page.startMinutes, page.strict)
    }
  }

  // ---- On: what's left, more or less of it, turn it off.
  Column {
    width: parent.width
    spacing: Style.space(8)
    visible: page.guard !== "off"

    SectionLabel {
      ctx: page.ctx
      text: page.ctx.t("guard.title")
    }

    Item {
      width: parent.width
      height: guardActions.height

      Column {
        anchors.left: parent.left
        anchors.right: guardActions.left
        anchors.rightMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(1)

        FocusText {
          ctx: page.ctx
          width: parent.width
          color: page.ctx.accent
          font.pixelSize: Style.font.title
          font.features: { "tnum": 1 }
          text: {
            if (page.guard === "timed") return Model.clock(Model.focusRemaining(page.model, page.ctx.nowMs))
            if (page.guard === "expired") return page.ctx.t("guard.expired")
            return page.ctx.t("guard.untilOff")
          }
        }
        FocusText {
          ctx: page.ctx
          width: parent.width
          muted: true
          font.pixelSize: Style.font.caption
          text: page.guardInfo ? page.ctx.tn("guard.onSites", page.guardInfo.sites.length) + (page.guardInfo.strict ? "  ·  " + page.ctx.t("guard.strict") : "") : ""
        }
      }

      Row {
        id: guardActions
        anchors.right: parent.right
        spacing: Style.space(4)

        Chip {
          ctx: page.ctx
          visible: page.guard === "timed" && !page.strictLocked
          text: "−5" + page.ctx.t("unit.m")
          anchors.verticalCenter: parent.verticalCenter
          enabled: Model.focusRemaining(page.model, page.ctx.nowMs) > 60
          onClicked: page.ctx.host.act(["focus", "adjust", "-5"])
        }
        Chip {
          ctx: page.ctx
          visible: page.guard === "timed"
          text: "+5" + page.ctx.t("unit.m")
          anchors.verticalCenter: parent.verticalCenter
          onClicked: page.ctx.host.act(["focus", "adjust", "5"])
        }
        Chip {
          ctx: page.ctx
          iconText: "󰈉"
          text: page.guard === "expired" ? page.ctx.t("guard.release") : page.ctx.t("guard.turnOff")
          enabled: !page.strictLocked
          anchors.verticalCenter: parent.verticalCenter
          onClicked: page.ctx.host.act(["focus", "off"])
        }
      }
    }

    FocusText {
      ctx: page.ctx
      width: parent.width
      visible: page.strictLocked || (!!page.guardInfo && !page.guardInfo.consistent)
      color: page.ctx.urgent
      font.pixelSize: Style.font.caption
      wrapMode: Text.WordWrap
      text: page.strictLocked ? page.ctx.t("guard.strictLocked") : page.ctx.t("guard.inconsistent")
    }
  }

  FocusText {
    ctx: page.ctx
    width: parent.width
    visible: !!page.model && !page.model.passwordless_guard
    muted: true
    font.pixelSize: Style.font.caption
    wrapMode: Text.WordWrap
    text: page.ctx.t("guard.needsPassword")
  }

  Rectangle {
    width: parent.width
    height: Style.spacing.hairline
    color: page.ctx.track
  }

  // ---- The list.
  SectionLabel {
    ctx: page.ctx
    text: page.renaming !== "" ? page.ctx.t("sites.renaming").arg(page.renaming) : page.ctx.t("sites.title")
  }

  Row {
    width: parent.width
    spacing: Style.space(6)

    Field {
      id: siteField
      ctx: page.ctx
      width: parent.width - commitChip.width - parent.spacing
      placeholderText: page.ctx.t("sites.addPlaceholder")
      maximumLength: 253
      onAccepted: page.commitSite()
      onCancelled: page.cancelEdit()
    }
    Chip {
      id: commitChip
      ctx: page.ctx
      anchors.verticalCenter: parent.verticalCenter
      iconText: page.renaming !== "" ? "󰄬" : "󰐕"
      tooltipText: page.renaming !== "" ? page.ctx.t("sites.rename") : page.ctx.t("sites.add")
      enabled: siteField.text.trim() !== ""
      onClicked: page.commitSite()
    }
  }

  Column {
    width: parent.width
    spacing: Style.space(1)

    Repeater {
      model: page.sites

      Rectangle {
        id: siteRow
        required property var modelData
        readonly property bool blocking: !!page.guardInfo && page.guardInfo.sites.indexOf(modelData.domain) !== -1
        width: parent.width
        height: Style.space(32)
        radius: Style.cornerRadius
        color: siteHover.hovered ? Style.hoverFillFor(page.ctx.fg, page.ctx.accent) : "transparent"

        HoverHandler { id: siteHover }

        Ui.ToggleSwitch {
          id: siteSwitch
          anchors.left: parent.left
          anchors.leftMargin: Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          checked: siteRow.modelData.enabled
          trackHeight: Style.space(14)
          cursorRing: false
          foreground: page.ctx.fg
          accent: page.ctx.accent
          onToggled: {
            var verb = siteRow.modelData.enabled ? "disable-site" : "enable-site"
            page.ctx.host.act(["focus", verb, "--", siteRow.modelData.domain])
          }
        }
        FocusText {
          ctx: page.ctx
          anchors.left: siteSwitch.right
          anchors.leftMargin: Style.space(10)
          anchors.right: siteHover.hovered ? siteActions.left : parent.right
          anchors.rightMargin: Style.space(8)
          anchors.verticalCenter: parent.verticalCenter
          text: siteRow.modelData.domain
          color: siteRow.blocking ? page.ctx.accent : (siteRow.modelData.enabled ? page.ctx.fg : page.ctx.dim)
        }
        Row {
          id: siteActions
          anchors.right: parent.right
          anchors.rightMargin: Style.space(6)
          anchors.verticalCenter: parent.verticalCenter
          spacing: Style.space(2)
          visible: siteHover.hovered

          Chip {
            ctx: page.ctx
            bordered: false
            horizontalPadding: Style.space(6)
            iconText: "󰏫"
            tooltipText: page.ctx.t("sites.rename")
            onClicked: page.startRename(siteRow.modelData.domain)
          }
          Chip {
            ctx: page.ctx
            bordered: false
            horizontalPadding: Style.space(6)
            iconText: "󰩺"
            tooltipText: page.ctx.t("sites.remove")
            onClicked: page.ctx.host.act(["focus", "remove-site", "--", siteRow.modelData.domain])
          }
        }
      }
    }

    FocusText {
      ctx: page.ctx
      width: parent.width
      visible: page.sites.length === 0
      topPadding: Style.space(12)
      bottomPadding: Style.space(12)
      muted: true
      horizontalAlignment: Text.AlignHCenter
      text: page.ctx.t("sites.empty")
    }
  }
}
