#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "payload" / "todoist" / ".local" / "bin" / "omarchy-todoist"


FAKE_TD = r'''#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

args = sys.argv[1:]
log = os.environ.get("FAKE_TD_LOG")
if log:
    with Path(log).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(args, ensure_ascii=False) + "\n")

if args == ["--version"]:
    print("3.3.1")
    raise SystemExit(0)
if args == ["auth", "status", "--json"]:
    print(json.dumps({"authenticated": True, "user": {"id": "u1"}}))
    raise SystemExit(0)
if os.environ.get("FAKE_TD_FAIL") == "1":
    print(json.dumps({"error": {"code": "API_ERROR", "message": "network unavailable"}}), file=sys.stderr)
    raise SystemExit(1)

if args[:2] == ["task", "list"]:
    print(json.dumps({"results": [
        {
            "id": "parent", "content": "Projekt domu", "description": "",
            "projectId": "p1", "sectionId": "s1", "parentId": None,
            "labels": ["dom"], "priority": 4, "childOrder": 1,
            "due": {"date": "2026-08-23", "isRecurring": False, "string": "23 sie"},
            "webUrl": "https://app.todoist.com/app/task/parent"
        },
        {
            "id": "child", "content": "Kupić farbę", "description": "Biała",
            "projectId": "p1", "sectionId": "s1", "parentId": "parent",
            "labels": ["zakupy"], "priority": 2, "childOrder": 2,
            "due": None, "webUrl": "https://app.todoist.com/app/task/child"
        }
    ]}))
elif args[:2] == ["project", "list"]:
    print(json.dumps({"results": [{"id": "p1", "name": "Dom"}]}))
elif args[:2] == ["section", "list"]:
    print(json.dumps({"results": [{"id": "s1", "projectId": "p1", "name": "Remont"}]}))
elif args[:2] == ["completed", "list"]:
    print(json.dumps({"results": [
        {
            "id": "done", "content": "Zwykłe ukończone", "description": "",
            "projectId": "p1", "sectionId": None, "parentId": None,
            "labels": [], "priority": 1, "childOrder": 0, "due": None,
            "completedAt": "2026-08-24T08:00:00Z",
            "webUrl": "https://app.todoist.com/app/task/done"
        },
        {
            "id": "cycle", "content": "Cykliczne ukończone", "description": "",
            "projectId": "p1", "sectionId": None, "parentId": None,
            "labels": [], "priority": 3, "childOrder": 0,
            "due": {"date": "2026-08-25", "isRecurring": True, "string": "codziennie"},
            "completedAt": "2026-08-23T08:00:00Z",
            "webUrl": "https://app.todoist.com/app/task/cycle"
        }
    ]}))
elif args[:2] == ["task", "add"]:
    print(json.dumps({"id": "created", "content": args[2]}))
elif args[:2] == ["task", "view"]:
    recurring = args[2] in {"id:cycle", "id:series"}
    print(json.dumps({
        "id": args[2][3:], "content": "Viewed", "priority": 1,
        "due": ({"date": "2026-08-25", "isRecurring": True, "string": "codziennie"} if recurring else None)
    }))
elif args[:2] in (["task", "complete"], ["task", "uncomplete"], ["task", "update"], ["task", "browse"]):
    if "--json" in args:
        print(json.dumps({"id": args[2][3:], "content": "Updated"}))
    else:
        print("ok")
else:
    print(json.dumps({"error": {"message": "unexpected argv: " + repr(args)}}), file=sys.stderr)
    raise SystemExit(1)
'''


class TodoistHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.temp = Path(self.temporary.name)
        self.fake_td = self.temp / "td"
        self.fake_td.write_text(FAKE_TD, encoding="utf-8")
        self.fake_td.chmod(0o755)
        self.log = self.temp / "td-argv.jsonl"
        self.env = {
            **os.environ,
            "OMARCHY_TODOIST_TD_BIN": str(self.fake_td),
            "OMARCHY_TODOIST_STATE_DIR": str(self.temp / "state"),
            "OMARCHY_TODOIST_NOW": "2026-08-24T12:00:00+02:00",
            "FAKE_TD_LOG": str(self.log),
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_helper(self, *args: str, env: dict[str, str] | None = None) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            ["python3", str(HELPER), *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env or self.env,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            self.fail(f"helper did not return one JSON document: {result.stdout!r}, stderr={result.stderr!r}, {error}")
        return result, payload

    def logged_argv(self) -> list[list[str]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]

    def test_snapshot_normalizes_domain_and_writes_private_cache(self) -> None:
        result, payload = self.run_helper("snapshot")

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        self.assertEqual("fresh", payload["freshness"]["kind"])
        snapshot = payload["snapshot"]
        self.assertEqual("2026-08-24", snapshot["today"])
        self.assertEqual(2, len(snapshot["active"]))
        self.assertEqual("p1", snapshot["active"][0]["priority"])
        self.assertEqual("Dom", snapshot["active"][1]["project"]["name"])
        self.assertEqual("Remont", snapshot["active"][1]["section"]["name"])
        self.assertEqual("Projekt domu", snapshot["active"][1]["parent"]["title"])
        self.assertTrue(snapshot["completed"][0]["reopenable"])
        self.assertFalse(snapshot["completed"][1]["reopenable"])
        self.assertIn(
            ["section", "list", "--project", "id:p1", "--all", "--json", "--full"],
            self.logged_argv(),
        )

        cache = self.temp / "state" / "snapshot-v1.json"
        self.assertTrue(cache.exists())
        self.assertEqual(0o600, stat.S_IMODE(cache.stat().st_mode))
        cached = json.loads(cache.read_text(encoding="utf-8"))
        self.assertEqual(1, cached["cacheVersion"])

    def test_failed_refresh_returns_last_snapshot_as_stale(self) -> None:
        self.run_helper("snapshot")
        failed_env = {**self.env, "FAKE_TD_FAIL": "1"}

        result, payload = self.run_helper("snapshot", env=failed_env)

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        self.assertEqual("stale", payload["freshness"]["kind"])
        self.assertEqual("OFFLINE", payload["freshness"]["reason"])
        self.assertEqual(2, len(payload["snapshot"]["active"]))

    def test_quick_add_creates_task_with_due_in_one_argv(self) -> None:
        content = "Kupić $(touch /tmp/nope); jutro p1 #Dom\nbez powłoki"
        request = json.dumps(
            {
                "version": 1,
                "requestId": "r1",
                "operation": "quickAdd",
                "content": content,
                "due": "2026-08-30",
            },
            ensure_ascii=False,
        )

        result, payload = self.run_helper("request", request)

        self.assertEqual(0, result.returncode)
        self.assertEqual("created", payload["operation"]["createdTaskId"])
        self.assertIn(
            ["task", "add", content, "--due", "2026-08-30", "--json"],
            self.logged_argv(),
        )

    def test_quick_add_without_due_omits_due_flag(self) -> None:
        request = json.dumps(
            {
                "version": 1,
                "requestId": "r1",
                "operation": "quickAdd",
                "content": "Bez terminu",
                "due": "",
            },
            ensure_ascii=False,
        )

        result, payload = self.run_helper("request", request)

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        self.assertIn(["task", "add", "Bez terminu", "--json"], self.logged_argv())

    def test_complete_series_validates_recurrence_and_uses_forever(self) -> None:
        request = json.dumps(
            {"version": 1, "requestId": "r2", "operation": "completeSeries", "taskId": "series"}
        )

        result, payload = self.run_helper("request", request)

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        self.assertIn(["task", "view", "id:series", "--json", "--full"], self.logged_argv())
        self.assertIn(["task", "complete", "id:series", "--forever"], self.logged_argv())

    def test_reopen_rejects_recurring_occurrence(self) -> None:
        request = json.dumps(
            {"version": 1, "requestId": "r3", "operation": "reopen", "taskId": "cycle"}
        )

        result, payload = self.run_helper("request", request)

        self.assertEqual(2, result.returncode)
        self.assertFalse(payload["ok"])
        self.assertEqual("UNSUPPORTED_RECURRING_REOPEN", payload["error"]["code"])
        self.assertNotIn(["task", "uncomplete", "id:cycle"], self.logged_argv())

    def test_invalid_task_id_never_reaches_td(self) -> None:
        request = json.dumps(
            {"version": 1, "requestId": "r4", "operation": "complete", "taskId": "bad id"}
        )

        result, payload = self.run_helper("request", request)

        self.assertEqual(2, result.returncode)
        self.assertEqual("INVALID_REQUEST", payload["error"]["code"])
        self.assertEqual([], self.logged_argv())

    def test_browse_does_not_downgrade_snapshot_freshness(self) -> None:
        request = json.dumps(
            {"version": 1, "requestId": "r5", "operation": "browse", "taskId": "child"}
        )

        result, payload = self.run_helper("request", request)

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        self.assertIsNone(payload["snapshot"])
        self.assertIsNone(payload["freshness"])
        self.assertIn(["task", "browse", "id:child"], self.logged_argv())

    def test_doctor_checks_cli_auth_and_state(self) -> None:
        result, payload = self.run_helper("doctor")

        self.assertEqual(0, result.returncode)
        self.assertTrue(payload["ok"])
        self.assertEqual({"td", "auth", "state"}, {check["name"] for check in payload["checks"]})


if __name__ == "__main__":
    unittest.main()
