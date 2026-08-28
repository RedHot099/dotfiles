import QtQuick
import QtTest
import "../../omarchy/payload/todoist/.config/omarchy/plugins/kuba.tasks/TaskView.js" as TaskView

TestCase {
  name: "TaskView"

  property var snapshot: ({
    active: [
      { id: "late", title: "Zaległe", priority: "p2", order: 2, due: { date: "2026-08-23" }, project: { name: "Dom" }, labels: [] },
      { id: "today-low", title: "Dzisiaj P4", priority: "p4", order: 2, due: { date: "2026-08-24" }, project: { name: "Praca" }, labels: [] },
      { id: "today-high", title: "Dzisiaj P1", priority: "p1", order: 4, due: { date: "2026-08-24" }, project: { name: "Praca" }, labels: ["ważne"] },
      { id: "future", title: "Przyszłe", priority: "p3", order: 1, due: { date: "2027-01-01" }, project: { name: "Dom" }, labels: [] },
      { id: "free", title: "Bez terminu", priority: "p3", order: 1, due: null, project: { name: "Inbox" }, labels: [] }
    ],
    completed: [
      { id: "old", title: "Stare", completedAt: "2026-08-20T10:00:00Z", project: { name: "Dom" }, labels: [] },
      { id: "new", title: "Nowe", completedAt: "2026-08-24T10:00:00Z", project: { name: "Dom" }, labels: [] }
    ]
  })

  function test_all_groups_and_sorts() {
    var view = TaskView.buildView(snapshot, "all", "", new Date(2026, 7, 24, 12).getTime())
    compare(view.rows.filter(function(row) { return row.kind === "header" }).map(function(row) { return row.title }),
      ["Zaległe", "Dzisiaj", "Nadchodzące", "Bez terminu"])
    var today = view.rows.filter(function(row) { return row.kind === "task" && row.task.due && row.task.due.date === "2026-08-24" })
    compare(today[0].task.id, "today-high")
    compare(today[1].task.id, "today-low")
  }

  function test_tabs_and_search() {
    var today = TaskView.buildView(snapshot, "today", "ważne", new Date(2026, 7, 24, 12).getTime())
    compare(today.selectableTaskIds, ["today-high"])
    var project = TaskView.buildView(snapshot, "all", "inbox", new Date(2026, 7, 24, 12).getTime())
    compare(project.selectableTaskIds, ["free"])
  }

  function test_completed_is_newest_first() {
    var view = TaskView.buildView(snapshot, "completed", "", new Date(2026, 7, 24, 12).getTime())
    compare(view.selectableTaskIds, ["new", "old"])
  }

  function test_cached_task_rebuckets_after_midnight() {
    var before = TaskView.buildView(snapshot, "today", "", new Date(2026, 7, 24, 23, 59).getTime())
    verify(before.selectableTaskIds.indexOf("today-high") >= 0)
    var after = TaskView.buildView(snapshot, "overdue", "", new Date(2026, 7, 25, 0, 1).getTime())
    verify(after.selectableTaskIds.indexOf("today-high") >= 0)
  }

  function test_selection_is_stable_or_nearest() {
    var view = TaskView.buildView(snapshot, "today", "", new Date(2026, 7, 24, 12).getTime())
    compare(TaskView.reconcileSelection("today-low", 0, view), "today-low")
    compare(TaskView.reconcileSelection("missing", 1, view), "today-low")
  }
}
