import QtQuick
import Quickshell
import Quickshell.Io
import "TaskView.js" as TaskView

Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string helperPath: (Quickshell.env("HOME") || "") + "/.local/bin/todoist-helper"
  property var _snapshot: null
  property var _freshness: null
  readonly property var snapshot: _snapshot
  readonly property var freshness: _freshness
  readonly property bool hasSnapshot: snapshot !== null
  readonly property int activeCount: hasSnapshot && Array.isArray(snapshot.active) ? snapshot.active.length : -1
  readonly property bool stale: freshness && freshness.kind === "stale"
  // Bar badge input, recomputed after every helper run so it tracks midnight.
  property var _barSummary: null
  readonly property int dueCount: _barSummary ? _barSummary.count : -1
  readonly property int overdueCount: _barSummary ? _barSummary.overdue : 0
  // "unknown" until the first refresh, then "ok", "offline" or "error".
  property string syncState: "unknown"
  readonly property bool offline: syncState === "offline"
  readonly property bool syncProblem: syncState === "offline" || syncState === "error"
  readonly property bool refreshing: currentJob && currentJob.kind === "refresh"
  readonly property bool busy: worker.running || currentJob !== null || jobQueue.length > 0

  property var lastError: null
  property var lastWarning: null
  property var _pendingByTask: ({})
  property int pendingRevision: 0
  readonly property var pendingByTask: {
    var revision = pendingRevision
    return _pendingByTask
  }
  property var undo: null

  property var jobQueue: []
  property var currentJob: null
  property bool refreshQueued: false
  property int requestSerial: 0
  property string _stdout: ""
  property string _stderr: ""

  signal operationSucceeded(string requestId, string type, string taskId, string createdTaskId)
  signal operationFailed(string requestId, string type, string taskId, string code, string message)

  function refreshIntervalSec() {
    var configured = 60
    if (!shell || !shell.shellConfig || !shell.shellConfig.bar || !shell.shellConfig.bar.layout) return configured
    var layout = shell.shellConfig.bar.layout
    for (var section in layout) {
      var entries = layout[section]
      if (!Array.isArray(entries)) continue
      for (var i = 0; i < entries.length; i++) {
        if (entries[i] && entries[i].id === "kuba.tasks" && entries[i].refreshIntervalSec !== undefined)
          configured = Number(entries[i].refreshIntervalSec)
      }
    }
    if (!isFinite(configured)) configured = 60
    return Math.max(30, Math.min(3600, configured))
  }

  function nextRequestId() {
    requestSerial += 1
    return "shell-" + Date.now() + "-" + requestSerial
  }

  function cloneMap(source) {
    var result = {}
    for (var key in source) result[key] = source[key]
    return result
  }

  function setPending(key, value) {
    var next = cloneMap(_pendingByTask)
    if (value === null || value === undefined) delete next[key]
    else next[key] = value
    _pendingByTask = next
    pendingRevision += 1
  }

  function pendingFor(taskId) {
    var revision = pendingRevision
    return _pendingByTask[String(taskId || "")] || null
  }

  function taskById(taskId) {
    if (!hasSnapshot) return null
    var id = String(taskId || "")
    var collections = [snapshot.active || [], snapshot.completed || []]
    for (var group = 0; group < collections.length; group++)
      for (var i = 0; i < collections[group].length; i++)
        if (String(collections[group][i].id) === id) return collections[group][i]
    return null
  }

  function refresh(reason) {
    if (worker.running || currentJob !== null || jobQueue.length > 0) {
      refreshQueued = true
      return
    }
    startJob({ kind: "refresh", reason: String(reason || "manual") })
  }

  function enqueueAction(operation, taskId, fields) {
    var key = operation === "quickAdd" ? "__quickAdd__" : String(taskId || "")
    if (pendingFor(key)) return ""
    if (stale && (freshness.reason === "OFFLINE" || freshness.reason === "AUTH_REQUIRED")) {
      lastError = {
        code: freshness.reason,
        message: "Najpierw odśwież połączenie z Todoist.",
        retryable: true
      }
      return ""
    }

    var requestId = nextRequestId()
    var request = { version: 1, requestId: requestId, operation: operation }
    if (taskId) request.taskId = String(taskId)
    if (fields) for (var field in fields) request[field] = fields[field]
    var previousTask = taskId ? taskById(taskId) : null
    setPending(key, "queued")
    jobQueue = jobQueue.concat([{
      kind: "action",
      key: key,
      operation: operation,
      taskId: String(taskId || ""),
      requestId: requestId,
      request: request,
      previousTask: previousTask
    }])
    pump()
    return requestId
  }

  function quickAdd(content, due) {
    return enqueueAction("quickAdd", "", {
      content: String(content || ""),
      due: String(due || "")
    })
  }
  function completeTask(taskId) { return enqueueAction("complete", taskId, null) }
  function reopenTask(taskId) { return enqueueAction("reopen", taskId, null) }
  function setDue(taskId, due) { return enqueueAction("setDue", taskId, { due: String(due || "") }) }
  function clearDue(taskId) { return enqueueAction("clearDue", taskId, null) }
  function setPriority(taskId, priority) { return enqueueAction("setPriority", taskId, { priority: String(priority || "") }) }
  function browseTask(taskId) { return enqueueAction("browse", taskId, null) }
  function completeSeries(taskId) { return enqueueAction("completeSeries", taskId, null) }

  function undoLastCompletion() {
    if (!undo || Date.now() >= undo.expiresAtMs) {
      undo = null
      return ""
    }
    var taskId = undo.taskId
    undo = null
    return reopenTask(taskId)
  }

  function pump() {
    if (worker.running || currentJob !== null) return
    if (jobQueue.length > 0) {
      var nextQueue = jobQueue.slice()
      var job = nextQueue.shift()
      jobQueue = nextQueue
      startJob(job)
      return
    }
    if (refreshQueued) {
      refreshQueued = false
      startJob({ kind: "refresh", reason: "coalesced" })
    }
  }

  function startJob(job) {
    currentJob = job
    _stdout = ""
    _stderr = ""
    lastError = null
    if (job.kind === "action") {
      setPending(job.key, "running")
      worker.command = [helperPath, "request", JSON.stringify(job.request)]
    } else {
      worker.command = [helperPath, "snapshot"]
    }
    worker.running = true
  }

  function publicError(code, message, retryable) {
    return {
      code: String(code || "INTERNAL"),
      message: String(message || "Nieznany błąd integracji Todoist."),
      retryable: retryable === true
    }
  }

  function syncStateFor(code) {
    return String(code || "") === "OFFLINE" ? "offline" : "error"
  }

  function applyResult(exitCode, stdout, stderr) {
    var job = currentJob
    var payload = null
    try {
      payload = JSON.parse(String(stdout || ""))
    } catch (error) {
      payload = null
    }

    if (!payload || payload.contractVersion !== 1 || typeof payload.ok !== "boolean") {
      lastError = publicError("INTERNAL_PROTOCOL", stderr || "Helper Todoist zwrócił niepoprawną odpowiedź.", true)
      if (job && job.kind === "action")
        operationFailed(job.requestId, job.operation, job.taskId, lastError.code, lastError.message)
      else syncState = "error"
      settleJob(job)
      return
    }

    if (payload.ok) {
      if (payload.snapshot) _snapshot = payload.snapshot
      if (payload.freshness) {
        _freshness = payload.freshness
        syncState = payload.freshness.kind === "stale" ? syncStateFor(payload.freshness.reason) : "ok"
      }
      lastWarning = payload.warning || null
      lastError = null
      if (job && job.kind === "action") {
        var operation = payload.operation || ({})
        var createdId = String(operation.createdTaskId || "")
        if (job.operation === "complete" && job.previousTask && job.previousTask.recurring !== true) {
          undo = {
            taskId: job.taskId,
            title: String(job.previousTask.title || ""),
            expiresAtMs: Date.now() + 8000
          }
          undoTimer.restart()
        }
        operationSucceeded(job.requestId, job.operation, job.taskId, createdId)
        if (payload.snapshot) refreshQueued = false
      }
    } else {
      var errorValue = payload.error || ({})
      lastError = publicError(errorValue.code, errorValue.message, errorValue.retryable)
      if (job && job.kind === "action")
        operationFailed(job.requestId, job.operation, job.taskId, lastError.code, lastError.message)
      else syncState = syncStateFor(lastError.code)
    }
    settleJob(job)
  }

  function settleJob(job) {
    _barSummary = TaskView.barSummary(_snapshot, Date.now())
    if (job && job.kind === "action") setPending(job.key, null)
    currentJob = null
    pump()
  }

  Timer {
    id: refreshTimer
    interval: root.refreshIntervalSec() * 1000
    repeat: true
    running: true
    triggeredOnStart: true
    onTriggered: root.refresh("timer")
  }

  Timer {
    id: undoTimer
    interval: 8000
    repeat: false
    onTriggered: root.undo = null
  }

  Process {
    id: worker
    running: false
    command: []
    stdout: StdioCollector {
      id: stdoutCollector
      waitForEnd: true
      onStreamFinished: root._stdout = text
    }
    stderr: StdioCollector {
      id: stderrCollector
      waitForEnd: true
      onStreamFinished: root._stderr = text
    }
    onExited: function(exitCode) {
      root.applyResult(
        exitCode,
        String(stdoutCollector.text || root._stdout || ""),
        String(stderrCollector.text || root._stderr || "")
      )
    }
  }
}
