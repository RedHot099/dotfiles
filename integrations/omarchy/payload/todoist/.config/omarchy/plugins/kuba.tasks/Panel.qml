import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Quickshell
import qs.Commons
import qs.Ui
import "TaskView.js" as TaskView

Panel {
  id: root
  moduleName: "kuba.tasks"
  ipcTarget: "kuba.tasks"
  manageIpc: true

  property var service: null
  readonly property var tasks: service || (bar && bar.shell ? bar.shell.serviceFor("kuba.tasks") : null)
  readonly property color foreground: bar ? bar.foreground : Color.foreground
  readonly property color urgent: bar ? bar.urgent : Color.urgent
  // Themes expose no "warning" role, so the offline/sync-problem badge colour is fixed.
  readonly property color warning: "#e5c07b"
  readonly property color dim: Qt.darker(foreground, 1.55)
  readonly property string fontFamily: bar ? bar.fontFamily : Style.font.family

  property var tabs: [
    { id: "all", title: "Wszystkie", icon: "󰝖" },
    { id: "overdue", title: "Zaległe", icon: "󰨱" },
    { id: "today", title: "Dzisiaj", icon: "󰃶" },
    { id: "upcoming", title: "Nadchodzące", icon: "󰙹" },
    { id: "noDate", title: "Bez terminu", icon: "󰱅" },
    { id: "completed", title: "Ukończone", icon: "󰗡" }
  ]
  property int tabIndex: 0
  property var selectedByTab: ({})
  property var selectedOrdinalByTab: ({})
  property var scrollByTab: ({})
  property string selectedTaskId: ""
  property string query: ""
  property string editorMode: ""
  property string editorTaskId: ""
  property string quickAddDraft: ""
  property string pendingQuickAddRequestId: ""
  property string message: ""
  property bool consumeNextActivation: false
  property bool interactionArmed: false
  property double activationArmedAtMs: 0
  property double nowMs: Date.now()

  readonly property string tabId: tabs[tabIndex].id
  readonly property var view: TaskView.buildView(tasks ? tasks.snapshot : null, tabId, query, nowMs)
  readonly property var selectedTask: tasks ? tasks.taskById(selectedTaskId) : null
  readonly property int dueCount: tasks ? tasks.dueCount : -1
  readonly property int overdueCount: tasks ? tasks.overdueCount : 0
  readonly property bool hasOverdue: overdueCount > 0
  readonly property bool syncProblem: tasks ? tasks.syncProblem : false
  readonly property bool textEditorOpen: editorMode === "quickAdd"
    || editorMode === "search"
    || editorMode === "customDue"
    || editorMode === "quickAddCustomDue"
  readonly property bool choiceEditorOpen: editorMode === "menu"
    || editorMode === "due"
    || editorMode === "quickAddDue"
    || editorMode === "priority"
    || editorMode === "confirmSeries"

  function cloneMap(value) {
    var copy = {}
    for (var key in value) copy[key] = value[key]
    return copy
  }

  function rememberSelection() {
    var selected = cloneMap(selectedByTab)
    selected[tabId] = selectedTaskId
    selectedByTab = selected
    var ordinal = view.selectableTaskIds.indexOf(selectedTaskId)
    var ordinals = cloneMap(selectedOrdinalByTab)
    ordinals[tabId] = Math.max(0, ordinal)
    selectedOrdinalByTab = ordinals
  }

  function rememberScroll() {
    if (!taskList) return
    var positions = cloneMap(scrollByTab)
    positions[tabId] = taskList.contentY
    scrollByTab = positions
  }

  function reconcileSelection() {
    var wanted = selectedTaskId || selectedByTab[tabId] || ""
    var ordinal = selectedOrdinalByTab[tabId] || 0
    selectedTaskId = TaskView.reconcileSelection(wanted, ordinal, view)
    ensureSelectedVisible()
  }

  function switchTab(delta) {
    interactionArmed = true
    rememberSelection()
    rememberScroll()
    tabIndex = ((tabIndex + delta) % tabs.length + tabs.length) % tabs.length
    selectedTaskId = selectedByTab[tabId] || ""
    reconcileSelection()
    taskList.contentY = Math.max(0, Number(scrollByTab[tabId] || 0))
  }

  function selectTab(index) {
    if (index === tabIndex) return
    switchTab(index - tabIndex)
  }

  function moveSelection(delta) {
    interactionArmed = true
    var ids = view.selectableTaskIds
    if (ids.length === 0) return
    var current = ids.indexOf(selectedTaskId)
    if (current < 0) current = 0
    current = Math.max(0, Math.min(ids.length - 1, current + delta))
    selectedTaskId = ids[current]
    rememberSelection()
    ensureSelectedVisible()
  }

  function ensureSelectedVisible() {
    var rowIndex = view.rowIndexByTaskId[selectedTaskId]
    if (rowIndex === undefined || !taskList) return
    taskList.positionViewAtIndex(rowIndex, ListView.Contain)
  }

  function selectTask(taskId, arm) {
    selectedTaskId = String(taskId || "")
    if (arm === true) interactionArmed = true
    rememberSelection()
  }

  function taskPending(taskId) {
    return tasks ? !!tasks.pendingFor(taskId) : false
  }

  function interactionReady() {
    return interactionArmed || Date.now() >= activationArmedAtMs
  }

  function toggleSelected() {
    if (!interactionReady()) return
    var task = selectedTask
    if (!task || taskPending(task.id)) return
    message = ""
    if (task.kind === "active") tasks.completeTask(task.id)
    else if (task.reopenable) tasks.reopenTask(task.id)
    else message = "Powtarzalnego wystąpienia nie można ponownie otworzyć."
  }

  function openSelected() {
    if (!interactionReady()) return
    var task = selectedTask
    if (!task || taskPending(task.id)) return
    tasks.browseTask(task.id)
  }

  function showEditor(mode, taskId) {
    editorMode = mode
    editorTaskId = String(taskId || selectedTaskId || "")
    message = ""
    entryField.text = ""
    if (textEditorOpen) entryField.forceActiveFocus()
    else if (choiceEditorOpen) choiceFocusTimer.restart()
  }

  function focusChoiceEditor() {
    var items = choiceItems()
    if (items.length > 0) items[0].forceActiveFocus()
  }

  function choiceItems() {
    var items = []
    if (editorMode === "menu") {
      items.push(menuDueButton, menuPriorityButton, menuBrowserButton)
      if (completeSeriesButton.visible) items.push(completeSeriesButton)
    } else if (editorMode === "due" || editorMode === "quickAddDue") {
      for (var dueIndex = 0; dueIndex < dueRepeater.count; dueIndex++)
        items.push(dueRepeater.itemAt(dueIndex))
      items.push(customDueButton)
    } else if (editorMode === "priority") {
      for (var priorityIndex = 0; priorityIndex < priorityRepeater.count; priorityIndex++)
        items.push(priorityRepeater.itemAt(priorityIndex))
    } else if (editorMode === "confirmSeries") {
      items.push(cancelSeriesButton, confirmSeriesButton)
    }
    return items
  }

  function moveChoiceFocus(delta) {
    var items = choiceItems()
    if (items.length === 0) return
    var current = -1
    for (var index = 0; index < items.length; index++)
      if (items[index].activeFocus) current = index
    if (current < 0) current = 0
    var next = ((current + delta) % items.length + items.length) % items.length
    items[next].forceActiveFocus()
  }

  function handleChoiceKey(event) {
    if (!choiceEditorOpen) return
    if (event.key === Qt.Key_Left || event.key === Qt.Key_Up
        || event.key === Qt.Key_H || event.key === Qt.Key_K
        || event.text === "h" || event.text === "k") {
      moveChoiceFocus(-1)
      event.accepted = true
    } else if (event.key === Qt.Key_Right || event.key === Qt.Key_Down
               || event.key === Qt.Key_L || event.key === Qt.Key_J
               || event.text === "l" || event.text === "j") {
      moveChoiceFocus(1)
      event.accepted = true
    }
  }

  function closeEditor() {
    choiceFocusTimer.stop()
    editorMode = ""
    editorTaskId = ""
    quickAddDraft = ""
    entryField.text = ""
    if (opened) keyCatcher.forceActiveFocus()
  }

  function submitEditor() {
    var text = entryField.text.trim()
    if (editorMode === "quickAdd") {
      if (text !== "") {
        quickAddDraft = text
        showEditor("quickAddDue", "")
      }
      return
    }
    if (editorMode === "search") {
      query = text
      closeEditor()
      reconcileSelection()
      return
    }
    if (editorMode === "customDue") {
      if (text !== "" && tasks && tasks.setDue(editorTaskId, text) !== "") closeEditor()
      return
    }
    if (editorMode === "quickAddCustomDue" && text !== "") {
      submitQuickAdd(text)
    }
  }

  function submitQuickAdd(due) {
    if (!tasks || quickAddDraft === "") return
    var requestId = tasks.quickAdd(quickAddDraft, due)
    if (requestId === "") return
    pendingQuickAddRequestId = requestId
    message = "Dodaję zadanie…"
    closeEditor()
  }

  function dateIso(offsetDays) {
    var date = new Date(nowMs)
    date.setHours(12, 0, 0, 0)
    date.setDate(date.getDate() + offsetDays)
    return date.getFullYear() + "-" + String(date.getMonth() + 1).padStart(2, "0")
      + "-" + String(date.getDate()).padStart(2, "0")
  }

  function applyDue(value) {
    if (editorMode === "quickAddDue") {
      submitQuickAdd(value)
      return
    }
    if (!tasks || editorTaskId === "") return
    if (value === "") tasks.clearDue(editorTaskId)
    else tasks.setDue(editorTaskId, value)
    closeEditor()
  }

  function applyPriority(value) {
    if (tasks && editorTaskId !== "") tasks.setPriority(editorTaskId, value)
    closeEditor()
  }

  function barTooltip() {
    if (dueCount < 0) return "Todoist · trwa wczytywanie"
    var parts = ["Todoist · " + dueCount + " do zrobienia w 3 tyg."]
    if (hasOverdue) parts.push("zaległe: " + overdueCount)
    if (tasks && tasks.offline) parts.push("brak połączenia")
    else if (syncProblem) parts.push("błąd synchronizacji")
    return parts.join(" · ")
  }

  function formatDue(task) {
    if (!task || !task.due || !task.due.date) return ""
    var value = String(task.due.date).slice(0, 10)
    var today = TaskView.localDate(nowMs)
    if (value < today) return "zaległe · " + value
    if (value === today) return "dzisiaj"
    if (value === dateIso(1)) return "jutro"
    return value
  }

  function metadata(task) {
    if (!task) return ""
    var values = []
    if (task.project && task.project.name) values.push(task.project.name)
    if (task.parent && task.parent.title) values.push("↳ " + task.parent.title)
    if (task.labels && task.labels.length) values.push(task.labels.map(function(label) { return "@" + label }).join(" "))
    return values.join(" · ")
  }

  function handleTextKey(text) {
    if (text === "a") showEditor("quickAdd", "")
    else if (text === "/") showEditor("search", "")
    else if (text === "r") { if (tasks) tasks.refresh("keyboard") }
    else if (text === "m") showEditor("menu", selectedTaskId)
    else if (text === "d") showEditor("due", selectedTaskId)
    else if (text === "p") showEditor("priority", selectedTaskId)
    else if (text === "o") openSelected()
  }

  function closeOrBack() {
    if (editorMode !== "") closeEditor()
    else if (query !== "") { query = ""; reconcileSelection() }
    else close()
  }

  implicitWidth: barButton.implicitWidth
  implicitHeight: barButton.implicitHeight

  onOpenedChanged: if (opened) {
    nowMs = Date.now()
    interactionArmed = false
    activationArmedAtMs = Date.now() + 1000
    message = ""
    if (tasks) tasks.refresh("panel-open")
    reconcileSelection()
  } else {
    pendingQuickAddRequestId = ""
    rememberSelection()
    rememberScroll()
    closeEditor()
  }

  Timer {
    interval: 30000
    repeat: true
    running: root.opened
    onTriggered: root.nowMs = Date.now()
  }

  Timer {
    id: choiceFocusTimer
    interval: 0
    onTriggered: root.focusChoiceEditor()
  }

  Connections {
    target: root.tasks
    function onOperationSucceeded(requestId, type, taskId, createdTaskId) {
      if (type === "quickAdd") {
        root.pendingQuickAddRequestId = ""
        root.message = "Zadanie dodane."
      } else if (type === "browse") root.message = "Otwarto w Todoist."
      else root.message = "Zmiana zapisana."
    }
    function onOperationFailed(requestId, type, taskId, code, errorMessage) {
      if (requestId === root.pendingQuickAddRequestId) root.pendingQuickAddRequestId = ""
      root.message = errorMessage
    }
  }

  WidgetButton {
    id: barButton
    anchors.fill: parent
    bar: root.bar
    text: "󰄬 " + (root.dueCount < 0 ? "…" : root.dueCount)
    // Red wins over yellow: overdue work matters more than a sync problem.
    active: root.hasOverdue || root.syncProblem
    activeColor: root.hasOverdue ? root.urgent : root.warning
    dimmed: root.tasks && root.tasks.refreshing
    tooltipText: root.barTooltip()
    onPressed: function(buttonCode) {
      if (buttonCode === Qt.RightButton && root.tasks) root.tasks.refresh("bar")
      else root.toggle()
    }
  }

  KeyboardPanel {
    id: panel
    anchorItem: barButton
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(380))
    contentHeight: panel.fittedContentHeight(contentColumn.implicitHeight,
                                             Math.max(Style.space(260), Math.floor(panel.screenH * 0.5)))

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      blocked: (entryField.visible && entryField.activeFocus) || root.choiceEditorOpen

      onMoveRequested: function(dx, dy) {
        if (dx !== 0) root.switchTab(dx)
        if (dy !== 0) root.moveSelection(dy)
      }
      onReturnRequested: {
        root.consumeNextActivation = true
        root.openSelected()
      }
      onActivateRequested: {
        if (root.consumeNextActivation) root.consumeNextActivation = false
        else root.toggleSelected()
      }
      onDeleteRequested: root.toggleSelected()
      onCloseRequested: root.closeOrBack()
      onTabRequested: function(direction) { root.switchPanel(direction) }
      onTextKey: function(text) { root.handleTextKey(text) }

      Column {
        id: contentColumn
        width: parent.width
        spacing: Style.space(10)

        RowLayout {
          width: parent.width
          spacing: Style.spacing.md

          Text {
            text: "󰄬 Todoist - " + root.tabs[root.tabIndex].title
            color: root.foreground
            font.family: root.fontFamily
            font.pixelSize: Style.font.title
            font.bold: true
          }

          Item { Layout.fillWidth: true }

          PanelActionButton {
            iconText: "󰑐"
            tooltipText: "Odśwież (r)"
            foreground: root.foreground
            fontFamily: root.fontFamily
            enabled: root.tasks && !root.tasks.refreshing
            onClicked: if (root.tasks) root.tasks.refresh("button")
          }

          PanelActionButton {
            id: quickAddButton
            iconText: "󰐕"
            tooltipText: "Dodaj zadanie (a)"
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.showEditor("quickAdd", "")
          }

          PanelActionButton {
            id: searchButton
            iconText: "󰍉"
            tooltipText: "Szukaj (/)"
            foreground: root.foreground
            fontFamily: root.fontFamily
            onClicked: root.showEditor("search", "")
          }
        }

        Row {
          id: tabRow
          width: parent.width
          spacing: Style.space(4)

          Repeater {
            model: root.tabs

            Button {
              required property var modelData
              required property int index
              width: (tabRow.width - tabRow.spacing * (root.tabs.length - 1)) / root.tabs.length
              text: modelData.icon
              tooltipText: modelData.title
              selected: index === root.tabIndex
              hasCursor: index === root.tabIndex
              foreground: root.foreground
              fontFamily: root.fontFamily
              fontSize: Style.font.icon
              horizontalPadding: Style.space(3)
              verticalPadding: Style.space(5)
              onClicked: root.selectTab(index)
            }
          }
        }

        BorderSurface {
          visible: root.tasks && root.tasks.stale
          width: parent.width
          implicitHeight: staleText.implicitHeight + Style.space(14)
          color: root.alpha(root.urgent, 0.10)
          borderSpec: Border.flat(root.alpha(root.urgent, 0.35), 1)
          radius: Style.cornerRadius

          Text {
            id: staleText
            anchors.fill: parent
            anchors.margins: Style.space(7)
            text: "Tryb offline · dane z " + (root.tasks && root.tasks.freshness ? root.tasks.freshness.fetchedAt : "cache")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.caption
            elide: Text.ElideRight
          }
        }

        BorderSurface {
          id: actionSheet
          visible: root.textEditorOpen
            || root.editorMode === "menu"
            || root.editorMode === "due"
            || root.editorMode === "quickAddDue"
            || root.editorMode === "priority"
            || root.editorMode === "confirmSeries"
          width: parent.width
          implicitHeight: sheetColumn.implicitHeight + Style.space(16)
          color: Style.selectedFillFor(root.foreground, Color.accent)
          borderSpec: Border.controlSpec("normal", root.foreground, Color.accent)
          radius: Style.cornerRadius
          Keys.onEscapePressed: root.closeEditor()

          Column {
            id: sheetColumn
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.margins: Style.space(8)
            spacing: Style.space(6)

            Text {
              width: parent.width
              text: root.editorMode === "quickAdd" ? "Nowe zadanie"
                : (root.editorMode === "search" ? "Wyszukiwanie"
                : (root.editorMode === "customDue" || root.editorMode === "quickAddCustomDue" ? "Własny termin"
                : (root.editorMode === "quickAddDue" ? "Termin nowego zadania"
                : (root.editorMode === "confirmSeries" ? "Zakończyć całą serię?" : "Akcje zadania"))))
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.bodySmall
              font.bold: true
            }

            RowLayout {
              visible: root.textEditorOpen
              width: parent.width
              spacing: Style.spacing.sm

              TextField {
                id: entryField
                Layout.fillWidth: true
                foreground: root.foreground
                placeholderText: root.editorMode === "quickAdd" ? "Nazwa zadania"
                  : (root.editorMode === "search" ? "Szukaj w zadaniach" : "Termin, np. 2026-08-30")
                onVisibleChanged: if (visible) {
                  text = ""
                  forceActiveFocus()
                }
                Keys.onPressed: function(event) {
                  if (event.key === Qt.Key_Escape) {
                    root.closeEditor()
                    event.accepted = true
                  } else if (event.key === Qt.Key_Return || event.key === Qt.Key_Enter) {
                    root.submitEditor()
                    event.accepted = true
                  }
                }
              }

              Button {
                text: root.editorMode === "quickAdd" ? "Dalej"
                  : (root.editorMode === "search" ? "Szukaj" : "Ustaw")
                foreground: root.foreground
                fontFamily: root.fontFamily
                enabled: root.editorMode === "search" || entryField.text.trim() !== ""
                onClicked: root.submitEditor()
              }
            }

            Row {
              visible: root.editorMode === "menu"
              width: parent.width
              spacing: Style.space(5)

              Button {
                id: menuDueButton
                width: (parent.width - parent.spacing * 2) / 3
                text: "Termin"
                iconText: "󰃭"
                foreground: root.foreground
                fontFamily: root.fontFamily
                focusable: true
                Keys.onPressed: function(event) { root.handleChoiceKey(event) }
                onClicked: root.showEditor("due", root.editorTaskId)
              }
              Button {
                id: menuPriorityButton
                width: (parent.width - parent.spacing * 2) / 3
                text: "Priorytet"
                iconText: "󰈿"
                foreground: root.foreground
                fontFamily: root.fontFamily
                focusable: true
                Keys.onPressed: function(event) { root.handleChoiceKey(event) }
                onClicked: root.showEditor("priority", root.editorTaskId)
              }
              Button {
                id: menuBrowserButton
                width: (parent.width - parent.spacing * 2) / 3
                text: "Przeglądarka"
                iconText: "󰖟"
                foreground: root.foreground
                fontFamily: root.fontFamily
                focusable: true
                Keys.onPressed: function(event) { root.handleChoiceKey(event) }
                onClicked: {
                  if (root.tasks) root.tasks.browseTask(root.editorTaskId)
                  root.closeEditor()
                }
              }
            }

            Button {
              id: completeSeriesButton
              visible: root.editorMode === "menu" && root.selectedTask && root.selectedTask.kind === "active" && root.selectedTask.recurring
              width: parent.width
              text: "Zakończ całą serię powtarzalną"
              iconText: "󰜺"
              foreground: root.urgent
              fontFamily: root.fontFamily
              bordered: true
              focusable: true
              Keys.onPressed: function(event) { root.handleChoiceKey(event) }
              onClicked: root.showEditor("confirmSeries", root.editorTaskId)
            }

            Row {
              visible: root.editorMode === "due" || root.editorMode === "quickAddDue"
              width: parent.width
              spacing: Style.space(4)

              Repeater {
                id: dueRepeater
                model: [
                  { title: "Dziś", value: root.dateIso(0) },
                  { title: "Jutro", value: root.dateIso(1) },
                  { title: "+7 dni", value: root.dateIso(7) },
                  { title: "Bez", value: "" }
                ]
                Button {
                  required property var modelData
                  width: (parent.width - parent.spacing * 3) / 4
                  text: modelData.title
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  focusable: true
                  Keys.onPressed: function(event) { root.handleChoiceKey(event) }
                  onClicked: root.applyDue(modelData.value)
                }
              }
            }

            Button {
              id: customDueButton
              visible: root.editorMode === "due" || root.editorMode === "quickAddDue"
              width: parent.width
              text: "Własny termin…"
              foreground: root.foreground
              fontFamily: root.fontFamily
              focusable: true
              Keys.onPressed: function(event) { root.handleChoiceKey(event) }
              onClicked: root.showEditor(
                root.editorMode === "quickAddDue" ? "quickAddCustomDue" : "customDue",
                root.editorTaskId
              )
            }

            Row {
              visible: root.editorMode === "priority"
              width: parent.width
              spacing: Style.space(4)

              Repeater {
                id: priorityRepeater
                model: ["p1", "p2", "p3", "p4"]
                Button {
                  required property string modelData
                  width: (parent.width - parent.spacing * 3) / 4
                  text: modelData.toUpperCase()
                  foreground: modelData === "p1" ? root.urgent : root.foreground
                  fontFamily: root.fontFamily
                  focusable: true
                  Keys.onPressed: function(event) { root.handleChoiceKey(event) }
                  onClicked: root.applyPriority(modelData)
                }
              }
            }

            Row {
              visible: root.editorMode === "confirmSeries"
              width: parent.width
              spacing: Style.space(6)

              Button {
                id: cancelSeriesButton
                width: (parent.width - parent.spacing) / 2
                text: "Anuluj"
                foreground: root.foreground
                fontFamily: root.fontFamily
                focusable: true
                Keys.onPressed: function(event) { root.handleChoiceKey(event) }
                onClicked: root.closeEditor()
              }
              Button {
                id: confirmSeriesButton
                width: (parent.width - parent.spacing) / 2
                text: "Zakończ serię"
                foreground: root.urgent
                fontFamily: root.fontFamily
                bordered: true
                focusable: true
                Keys.onPressed: function(event) { root.handleChoiceKey(event) }
                onClicked: {
                  if (root.tasks) root.tasks.completeSeries(root.editorTaskId)
                  root.closeEditor()
                }
              }
            }
          }
        }

        ListView {
          id: taskList
          width: parent.width
          height: Math.min(Math.max(Style.space(100), contentHeight), Style.space(320))
          model: root.view.rows
          spacing: Style.space(4)
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          reuseItems: true
          ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

          delegate: Item {
            id: delegateRoot
            required property var modelData
            width: taskList.width
            height: modelData.kind === "header" ? Style.space(28) : taskSurface.implicitHeight

            PanelSectionHeader {
              visible: delegateRoot.modelData.kind === "header"
              anchors.left: parent.left
              anchors.right: parent.right
              anchors.verticalCenter: parent.verticalCenter
              text: delegateRoot.modelData.kind === "header"
                ? delegateRoot.modelData.title.toUpperCase() + "  " + delegateRoot.modelData.count
                : ""
              foreground: root.foreground
              fontFamily: root.fontFamily
            }

            CursorSurface {
              id: taskSurface
              visible: delegateRoot.modelData.kind === "task"
              width: parent.width
              implicitHeight: taskLayout.implicitHeight + Style.space(14)
              hasCursor: visible && delegateRoot.modelData.task.id === root.selectedTaskId
              foreground: root.foreground

              MouseArea {
                id: rowMouse
                anchors.fill: parent
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                hoverEnabled: true
                onEntered: if (delegateRoot.modelData.kind === "task") root.selectTask(delegateRoot.modelData.task.id, false)
                onClicked: function(mouse) {
                  if (delegateRoot.modelData.kind !== "task") return
                  root.selectTask(delegateRoot.modelData.task.id, true)
                  if (mouse.button === Qt.RightButton) root.showEditor("menu", delegateRoot.modelData.task.id)
                }
                onDoubleClicked: if (delegateRoot.modelData.kind === "task") root.openSelected()
              }

              RowLayout {
                id: taskLayout
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: Style.space(7)
                spacing: Style.space(7)

                BusyIndicator {
                  visible: delegateRoot.modelData.kind === "task" && root.taskPending(delegateRoot.modelData.task.id)
                  running: visible
                  Layout.preferredWidth: Style.space(20)
                  Layout.preferredHeight: Style.space(20)
                }

                PanelActionButton {
                  visible: delegateRoot.modelData.kind === "task" && !root.taskPending(delegateRoot.modelData.task.id)
                  iconText: delegateRoot.modelData.kind === "task" && delegateRoot.modelData.task.kind === "completed" ? "󰡖" : "󰄱"
                  tooltipText: delegateRoot.modelData.kind === "task" && delegateRoot.modelData.task.kind === "completed" ? "Otwórz ponownie (spacja)" : "Ukończ (spacja)"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  enabled: delegateRoot.modelData.kind === "task"
                    && (delegateRoot.modelData.task.kind === "active" || delegateRoot.modelData.task.reopenable)
                  onClicked: {
                    root.selectTask(delegateRoot.modelData.task.id, true)
                    root.toggleSelected()
                  }
                }

                ColumnLayout {
                  Layout.fillWidth: true
                  spacing: Style.space(2)

                  Text {
                    Layout.fillWidth: true
                    text: delegateRoot.modelData.kind === "task" ? delegateRoot.modelData.task.title : ""
                    color: root.foreground
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.body
                    font.strikeout: delegateRoot.modelData.kind === "task" && delegateRoot.modelData.task.kind === "completed"
                    elide: Text.ElideRight
                  }

                  Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: delegateRoot.modelData.kind === "task" ? root.metadata(delegateRoot.modelData.task) : ""
                    color: root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    elide: Text.ElideRight
                  }
                }

                ColumnLayout {
                  visible: delegateRoot.modelData.kind === "task"
                  spacing: Style.space(1)

                  Text {
                    Layout.alignment: Qt.AlignRight
                    text: delegateRoot.modelData.kind === "task" ? root.formatDue(delegateRoot.modelData.task) : ""
                    visible: text !== ""
                    color: text.indexOf("zaległe") === 0 ? root.urgent : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                  }
                  Text {
                    Layout.alignment: Qt.AlignRight
                    text: delegateRoot.modelData.kind === "task" && delegateRoot.modelData.task.priority !== "p4"
                      ? delegateRoot.modelData.task.priority.toUpperCase() : ""
                    visible: text !== ""
                    color: text === "P1" ? root.urgent : root.dim
                    font.family: root.fontFamily
                    font.pixelSize: Style.font.caption
                    font.bold: true
                  }
                }

                PanelActionButton {
                  visible: delegateRoot.modelData.kind === "task"
                  iconText: "󰇙"
                  tooltipText: "Więcej (m)"
                  foreground: root.foreground
                  fontFamily: root.fontFamily
                  onClicked: {
                    root.selectTask(delegateRoot.modelData.task.id, true)
                    root.showEditor("menu", delegateRoot.modelData.task.id)
                  }
                }
              }

              PanelToolTip {
                visible: rowMouse.containsMouse && delegateRoot.modelData.kind === "task"
                  && String(delegateRoot.modelData.task.description || "") !== ""
                text: delegateRoot.modelData.kind === "task" ? delegateRoot.modelData.task.description : ""
                fontFamily: root.fontFamily
              }

            }
          }

          Text {
            anchors.centerIn: parent
            visible: taskList.count === 0
            width: parent.width - Style.space(24)
            text: root.tasks && root.tasks.refreshing ? "Pobieram zadania…"
              : (root.query !== "" ? "Brak wyników dla „" + root.query + "”." : "Brak zadań w tym filtrze.")
            color: root.dim
            font.family: root.fontFamily
            font.pixelSize: Style.font.body
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
          }
        }

        BorderSurface {
          visible: root.tasks && root.tasks.undo
          width: parent.width
          implicitHeight: undoRow.implicitHeight + Style.space(12)
          color: Style.selectedFillFor(root.foreground, Color.accent)
          radius: Style.cornerRadius

          RowLayout {
            id: undoRow
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.margins: Style.space(6)

            Text {
              Layout.fillWidth: true
              text: root.tasks && root.tasks.undo ? "Ukończono: " + root.tasks.undo.title : ""
              color: root.foreground
              font.family: root.fontFamily
              font.pixelSize: Style.font.caption
              elide: Text.ElideRight
            }
            Button {
              text: "Cofnij"
              foreground: root.foreground
              fontFamily: root.fontFamily
              onClicked: root.tasks.undoLastCompletion()
            }
          }
        }

        Text {
          visible: root.message !== "" || (root.tasks && root.tasks.lastError)
          width: parent.width
          text: root.tasks && root.tasks.lastError ? root.tasks.lastError.message : root.message
          color: root.tasks && root.tasks.lastError ? root.urgent : root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }

        Text {
          width: parent.width
          text: "←/→ filtry  ·  ↑/↓ zadania  ·  enter otwórz  ·  spacja ukończ  ·  a dodaj  ·  / szukaj"
          color: root.dim
          font.family: root.fontFamily
          font.pixelSize: Style.font.caption
          horizontalAlignment: Text.AlignHCenter
          elide: Text.ElideRight
        }
      }
    }
  }

  function alpha(color, opacity) {
    return Qt.rgba(color.r, color.g, color.b, opacity)
  }
}
