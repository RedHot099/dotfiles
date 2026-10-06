.pragma library

var TAB_IDS = ["all", "overdue", "today", "upcoming", "noDate", "completed"]
var BAR_HORIZON_DAYS = 21

function pad2(value) {
  return String(value).padStart(2, "0")
}

function localDate(nowMs) {
  var current = new Date(nowMs)
  return current.getFullYear() + "-" + pad2(current.getMonth() + 1) + "-" + pad2(current.getDate())
}

function shiftedLocalDate(nowMs, offsetDays) {
  var date = new Date(nowMs)
  date.setHours(12, 0, 0, 0)
  date.setDate(date.getDate() + offsetDays)
  return localDate(date.getTime())
}

// Bar badge: active tasks due today..today+horizon, plus everything overdue.
// No-date and further-out tasks are left out of the count on purpose.
function barSummary(snapshot, nowMs, horizonDays) {
  var active = snapshot && Array.isArray(snapshot.active) ? snapshot.active : []
  var days = horizonDays === undefined ? BAR_HORIZON_DAYS : horizonDays
  var today = localDate(nowMs)
  var horizon = shiftedLocalDate(nowMs, days)
  var overdue = 0
  var dueSoon = 0
  active.forEach(function(task) {
    if (!task || !task.due || !task.due.date) return
    var due = String(task.due.date).slice(0, 10)
    if (due < today) overdue += 1
    else if (due <= horizon) dueSoon += 1
  })
  return { overdue: overdue, dueSoon: dueSoon, count: overdue + dueSoon }
}

function bucketFor(task, today) {
  if (!task || !task.due || !task.due.date) return "noDate"
  var due = String(task.due.date).slice(0, 10)
  if (due < today) return "overdue"
  if (due === today) return "today"
  return "upcoming"
}

function priorityRank(task) {
  return { p1: 1, p2: 2, p3: 3, p4: 4 }[String(task && task.priority || "p4")] || 4
}

function compareActive(left, right) {
  var priority = priorityRank(left) - priorityRank(right)
  if (priority !== 0) return priority
  var leftDue = left && left.due && left.due.date ? String(left.due.date) : "9999-12-31"
  var rightDue = right && right.due && right.due.date ? String(right.due.date) : "9999-12-31"
  if (leftDue < rightDue) return -1
  if (leftDue > rightDue) return 1
  return Number(left && left.order || 0) - Number(right && right.order || 0)
}

function searchableText(task) {
  var values = [task && task.title, task && task.description]
  if (task && task.project) values.push(task.project.name)
  if (task && task.parent) values.push(task.parent.title)
  if (task && task.labels) values = values.concat(task.labels)
  return values.filter(function(value) { return value !== null && value !== undefined })
    .join(" ").toLocaleLowerCase()
}

function matches(task, query) {
  var normalized = String(query || "").trim().toLocaleLowerCase()
  return normalized === "" || searchableText(task).indexOf(normalized) !== -1
}

function sectionTitle(id) {
  return {
    overdue: "Zaległe",
    today: "Dzisiaj",
    upcoming: "Nadchodzące",
    noDate: "Bez terminu"
  }[id] || id
}

function buildView(snapshot, tabId, query, nowMs) {
  var active = snapshot && Array.isArray(snapshot.active) ? snapshot.active : []
  var completed = snapshot && Array.isArray(snapshot.completed) ? snapshot.completed : []
  var today = localDate(nowMs)
  var rows = []

  if (tabId === "completed") {
    completed.filter(function(task) { return matches(task, query) })
      .sort(function(left, right) {
        return String(right.completedAt || "").localeCompare(String(left.completedAt || ""))
      })
      .forEach(function(task) { rows.push({ kind: "task", key: "task:" + task.id, task: task }) })
  } else {
    var buckets = { overdue: [], today: [], upcoming: [], noDate: [] }
    active.filter(function(task) { return matches(task, query) }).forEach(function(task) {
      buckets[bucketFor(task, today)].push(task)
    })
    Object.keys(buckets).forEach(function(id) { buckets[id].sort(compareActive) })

    if (tabId === "all") {
      ;["overdue", "today", "upcoming", "noDate"].forEach(function(id) {
        if (buckets[id].length === 0) return
        rows.push({ kind: "header", key: "header:" + id, title: sectionTitle(id), count: buckets[id].length })
        buckets[id].forEach(function(task) { rows.push({ kind: "task", key: "task:" + task.id, task: task }) })
      })
    } else {
      var selected = buckets[tabId] || []
      selected.forEach(function(task) { rows.push({ kind: "task", key: "task:" + task.id, task: task }) })
    }
  }

  var selectableTaskIds = []
  var rowIndexByTaskId = {}
  rows.forEach(function(row, index) {
    if (row.kind !== "task") return
    selectableTaskIds.push(row.task.id)
    rowIndexByTaskId[row.task.id] = index
  })
  return { rows: rows, selectableTaskIds: selectableTaskIds, rowIndexByTaskId: rowIndexByTaskId }
}

function reconcileSelection(previousTaskId, previousIndex, view) {
  var ids = view && Array.isArray(view.selectableTaskIds) ? view.selectableTaskIds : []
  if (ids.length === 0) return ""
  if (previousTaskId && view.rowIndexByTaskId[previousTaskId] !== undefined) return previousTaskId
  var index = Math.max(0, Math.min(ids.length - 1, Number(previousIndex) || 0))
  return ids[index]
}
