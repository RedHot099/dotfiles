import json
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1] / "desktop/omarchy/payload/core-desktop/.config/omarchy/plugins/kuba.agents"
RPC = runpy.run_path(str(PLUGIN / "update-usage"))["rpc_request"]


class AgentUsageRpcTests(unittest.TestCase):
    def server(self, body):
        proc = subprocess.Popen(
            [sys.executable, "-c", "import os,sys,time; sys.stdin.readline(); " + body],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        self.addCleanup(proc.stdout.close)
        self.addCleanup(proc.stdin.close)
        self.addCleanup(proc.wait)
        self.addCleanup(proc.terminate)
        return proc

    def test_notification_and_response_in_one_write(self):
        proc = self.server(
            "os.write(1, b'{\"method\":\"account/updated\"}\\n' "
            "b'{\"id\":2,\"result\":{\"account\":{\"planType\":\"plus\"}}}\\n'); time.sleep(5)"
        )
        self.assertEqual(
            RPC(proc, 2, "account/read", timeout=1),
            {"id": 2, "result": {"account": {"planType": "plus"}}},
        )

    def test_fragmented_response_and_unrelated_lines(self):
        proc = self.server(
            "os.write(1, b'log line\\n{\"id\":0}\\n{\"id\":2,'); "
            "time.sleep(.05); os.write(1, b'\"result\":{\"rateLimits\":{}}}\\n'); time.sleep(5)"
        )
        self.assertEqual(RPC(proc, 2, "account/rateLimits/read", timeout=1),
                         {"id": 2, "result": {"rateLimits": {}}})

    def test_timeout_names_the_request(self):
        proc = self.server("time.sleep(5)")
        with self.assertRaisesRegex(TimeoutError, "timed out during account/read"):
            RPC(proc, 2, "account/read", timeout=.1)

    def test_closed_pipe_names_the_request(self):
        proc = self.server("pass")
        with self.assertRaisesRegex(EOFError, "closed stdout during account/read"):
            RPC(proc, 2, "account/read", timeout=1)


class AgentUsageUpdateTests(unittest.TestCase):
    def test_updates_codex_and_preserves_provider_selection(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binaries = root / "bin"
            binaries.mkdir()
            updater = binaries / "omarchy-agent-usage-update"
            updater.write_text('#!/usr/bin/python3\nimport json,sys\nprint(json.dumps(sys.argv[1:]))\n')
            updater.chmod(0o755)
            (binaries / "omarchy-agent-usage-codex").write_text(
                'import json,sys\n'
                'def fetch_codex_rpc(): pass\n'
                'def main(): print(json.dumps({"id":"codex","flags":sys.argv[1:]}))\n'
            )
            environment = dict(os.environ, OMARCHY_PATH=str(root), XDG_STATE_HOME=str(root / "state"))
            record = root / "state/omarchy/agents/usage/codex.json"
            result = subprocess.run(
                [str(PLUGIN / "update-usage"), "--limits-only", "codex"],
                env=environment, text=True, capture_output=True, check=True,
            )
            self.assertEqual(json.loads(result.stdout), ["--limits-only", "codex", "--except", "codex"])
            self.assertEqual(json.loads(record.read_text()), {"id": "codex", "flags": ["--limits-only"]})
            before = record.stat().st_mtime_ns
            for flags in (["--except", "codex"], ["claude"]):
                subprocess.run([str(PLUGIN / "update-usage"), *flags], env=environment,
                               capture_output=True, check=True)
                self.assertEqual(record.stat().st_mtime_ns, before)
            self.assertEqual([p.name for p in record.parent.iterdir()], ["codex.json"])
