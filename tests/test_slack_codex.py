import os
import sys
import tempfile
import threading
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import slack_codex as app


class FakeSlack(app.Slack):
    def __init__(self, responses):
        self.responses = iter(responses)
        self.requests = []

    def call(self, method, **args):
        self.requests.append((method, args))
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        return response


def message(ts="1.000001", reactions=None, **extra):
    return {
        "type": "message",
        "ts": ts,
        "text": "A query",
        "reactions": reactions or [],
        **extra,
    }


def reaction(name="robot_face", user="U1"):
    return {"name": name, "users": [user], "count": 50}


def item(m):
    return {"type": "message", "channel": "C1", "message": m}


class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.skill = self.home / "SKILL.md"
        self.skill.write_text("Answer the query.")
        self.workflow = {
            "project": str(self.home),
            "sandbox": "read-only",
            "skill": str(self.skill),
            "instructions": "Answer.",
        }
        self.c = {
            "user_id": "U1",
            "team_id": "T1",
            "workflows": {"robot_face": self.workflow},
            "codex": "/unused",
            "scopes": sorted(app.SCOPES),
            "timeout_seconds": 5,
        }
        self.db = app.database(self.home)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def state(self):
        return [
            (r["ts"], r["emoji"], r["status"])
            for r in self.db.execute("SELECT * FROM jobs ORDER BY id")
        ]

    def test_specific_emoji_attribution_and_duplicate_items(self):
        mine = item(message(reactions=[reaction(), reaction("eyes", "U2")]))
        other = item(
            message("2.000001", [reaction("robot_face", "U2"), reaction("eyes")])
        )
        s = FakeSlack([{"items": [mine, mine, other]}])
        self.assertEqual(list(s.matches(self.c)), [("C1", "1.000001", "robot_face")])
        self.assertEqual(s.requests[0][1]["user"], "U1")
        self.assertEqual(s.requests[0][1]["full"], "true")

    def test_cursor_pagination_empty_page_and_old_message(self):
        s = FakeSlack(
            [
                {"items": [], "response_metadata": {"next_cursor": "abc"}},
                {"items": [item(message("0.000001", [reaction()]))]},
            ]
        )
        self.assertEqual(len(s.matches(self.c)), 1)
        self.assertEqual(s.requests[1][1]["cursor"], "abc")

    def test_legacy_pagination(self):
        s = FakeSlack(
            [
                {"items": [], "paging": {"pages": 2}},
                {"items": [], "paging": {"pages": 2}},
            ]
        )
        self.assertEqual(s.matches(self.c), {})
        self.assertEqual(s.requests[1][1]["page"], 2)

    def test_repeated_cursor_and_incomplete_thread_fail(self):
        for responses in (
            [{"items": [], "response_metadata": {"next_cursor": "x"}}] * 2,
            [{"items": [], "has_more": True}],
        ):
            with self.assertRaises(app.Error):
                FakeSlack(responses).matches(self.c)

    def test_baseline_new_old_reaction_remove_readd_restart(self):
        first = {("C1", "100.000001", "robot_face"): {}}
        old = {("C1", "1.000001", "robot_face"): {}}
        app.discover(self.db, self.c, first)
        self.assertEqual(self.state()[0][2], "baseline")
        app.discover(self.db, self.c, old | first)
        app.discover(self.db, self.c, {})
        self.db.close()
        self.db = app.database(self.home)
        app.discover(self.db, self.c, old | first)
        self.assertEqual(
            self.state(),
            [
                ("100.000001", "robot_face", "baseline"),
                ("1.000001", "robot_face", "queued"),
            ],
        )

    def test_new_emoji_has_own_baseline(self):
        app.discover(self.db, self.c, {})
        self.c["workflows"]["eyes"] = self.workflow
        app.discover(
            self.db,
            self.c,
            {("C1", "1.000001", "eyes"): {}, ("C1", "1.000001", "robot_face"): {}},
        )
        self.assertEqual(
            self.state(),
            [("1.000001", "eyes", "baseline"), ("1.000001", "robot_face", "queued")],
        )

    def test_partial_scan_does_not_set_baseline(self):
        s = FakeSlack(
            [
                {"items": [], "response_metadata": {"next_cursor": "x"}},
                app.Error("offline"),
            ]
        )
        with self.assertRaises(app.Error):
            app.discover(self.db, self.c, s.matches(self.c))
        self.assertEqual(self.db.execute("SELECT count(*) FROM meta").fetchone()[0], 0)

    def test_reply_fetches_root_and_all_pages(self):
        selected = message("2.000001", [reaction()], thread_ts="1.000001")
        s = FakeSlack(
            [
                {"message": selected},
                {"messages": [message()], "response_metadata": {"next_cursor": "next"}},
                {"messages": [selected]},
            ]
        )
        context = s.thread(self.c, "C1", "2.000001", "robot_face")
        self.assertEqual(s.requests[1][1]["ts"], "1.000001")
        self.assertEqual(s.requests[2][1]["cursor"], "next")
        self.assertEqual(len(context["messages"]), 2)
        self.assertEqual(context["selected_ts"], "2.000001")

    def test_wrong_reactor_rejected_in_dry_run(self):
        with self.assertRaises(app.Error):
            FakeSlack([{"message": message(reactions=[reaction(user="U2")])}]).thread(
                self.c, "C1", "1.000001", "robot_face"
            )

    def test_crash_recovery_never_relaunches_running(self):
        app.discover(self.db, self.c, {})
        app.discover(self.db, self.c, {("C1", "1.000001", "robot_face"): {}})
        with self.db:
            self.db.execute("UPDATE jobs SET status='running'")
            self.db.execute(
                "INSERT INTO runs(job,started,status) VALUES(1,0,'running')"
            )
        app.recover(self.db)
        self.assertEqual(self.state()[0][2], "interrupted")
        self.assertEqual(
            self.db.execute("SELECT status FROM runs").fetchone()[0], "interrupted"
        )

    def test_lock_blocks_second_worker(self):
        with app.lock(self.home):
            with self.assertRaises(app.Error):
                with app.lock(self.home):
                    pass

    def prepare_job(self):
        app.discover(self.db, self.c, {})
        app.discover(self.db, self.c, {("C1", "1.000001", "robot_face"): {}})
        app.save(self.home / "approval.json", {"digest": app.digest(self.c)})

    def test_bounded_fetch_retries(self):
        self.prepare_job()
        s = FakeSlack([app.Error("offline")] * 3)
        for _ in range(3):
            app.run_one(self.home, self.c, s, self.db)
            with self.db:
                self.db.execute("UPDATE jobs SET next_try=0")
        self.assertEqual(self.state()[0][2], "failed")
        self.assertEqual(self.db.execute("SELECT attempts FROM jobs").fetchone()[0], 3)

    def test_no_launch_without_approval(self):
        with patch("subprocess.Popen") as p:
            with self.assertRaises(app.Error):
                app.run_one(self.home, self.c, FakeSlack([]), self.db)
            p.assert_not_called()

    def test_real_subprocess_stdin_environment_and_duplicate_prevention(self):
        self.prepare_job()
        fake = self.home / "fake.py"
        fake.write_text(
            'import os,sys,json\np=sys.stdin.read()\nassert "$(touch /tmp/should-not-exist)" in p\nassert "SLACK_TOKEN" not in os.environ\nprint(json.dumps({"type":"thread.started","thread_id":"test-thread"}))\n'
        )
        m = message(text_override="unused")
        m["text"] = "$(touch /tmp/should-not-exist)"
        s = FakeSlack([{"message": m}, {"messages": [m]}])
        with (
            patch.object(app, "command", return_value=[sys.executable, str(fake)]),
            patch.dict(os.environ, {"SLACK_TOKEN": "test-secret"}),
        ):
            self.assertTrue(app.run_one(self.home, self.c, s, self.db))
            self.assertFalse(app.run_one(self.home, self.c, s, self.db))
        self.assertEqual(self.state()[0][2], "succeeded")
        self.assertEqual(
            self.db.execute("SELECT thread_id FROM runs").fetchone()[0], "test-thread"
        )
        self.assertNotIn("test-secret", (self.home / "runs/1/prompt.txt").read_text())

    def test_timeout_kills_process_and_requires_manual_rerun(self):
        self.c["timeout_seconds"] = 0.1
        self.prepare_job()
        s = FakeSlack([{"message": message()}, {"messages": [message()]}])
        with patch.object(
            app,
            "command",
            return_value=[sys.executable, "-c", "import time; time.sleep(10)"],
        ):
            app.run_one(self.home, self.c, s, self.db)
        self.assertEqual(self.state()[0][2], "timed_out")

    def test_stop_interrupts_process(self):
        self.prepare_job()
        stop = threading.Event()
        stop.set()
        s = FakeSlack([{"message": message()}, {"messages": [message()]}])
        with patch.object(
            app,
            "command",
            return_value=[sys.executable, "-c", "import time; time.sleep(10)"],
        ):
            app.run_one(self.home, self.c, s, self.db, stop=stop)
        self.assertEqual(self.state()[0][2], "interrupted")

    def test_configuration_change_revokes_approval(self):
        self.prepare_job()
        self.skill.write_text("Changed instructions")
        self.assertFalse(app.approved(self.home, self.c))

    def test_rate_limit_retries_and_redacts_error(self):
        s = app.Slack("SECRET")
        e = urllib.error.HTTPError(
            "secret-url", 429, "secret-body", {"Retry-After": "5"}, None
        )
        with (
            patch("urllib.request.urlopen", side_effect=[e, e, e]),
            patch("time.sleep") as sleep,
        ):
            with self.assertRaisesRegex(app.Error, "HTTP 429") as result:
                s.call("reactions.list")
        self.assertNotIn("SECRET", str(result.exception))
        e.close()
        self.assertEqual(s.calls, 3)
        self.assertTrue(any(x.args[0] > 4 for x in sleep.call_args_list))

    def test_other_account_jobs_are_not_launched(self):
        self.prepare_job()
        with self.db:
            self.db.execute("UPDATE jobs SET team='T2'")
        with patch("subprocess.Popen") as child:
            self.assertFalse(app.run_one(self.home, self.c, FakeSlack([]), self.db))
            child.assert_not_called()

    def test_recovery_hold_blocks_other_jobs(self):
        self.prepare_job()
        with self.db:
            self.db.execute("UPDATE jobs SET status='running'")
        app.recover(self.db)
        app.discover(self.db, self.c, {("C1", "2.000001", "robot_face"): {}})
        with self.assertRaisesRegex(app.Error, "uncertain outcome"):
            app.run_one(self.home, self.c, FakeSlack([]), self.db)

    def test_identity_accepts_implicit_identify_and_rejects_write_scope(self):
        client = FakeSlack([{"user_id": "U1", "team_id": "T1"}] * 2)
        client.scopes = set(app.SCOPES) | {"identify"}
        self.assertEqual(client.identity(self.c)["user_id"], "U1")
        client.scopes.add("chat:write")
        with self.assertRaises(app.Error):
            client.identity(self.c)

    def test_no_write_api(self):
        with self.assertRaises(app.Error):
            app.Slack("unused").call("chat.postMessage")


if __name__ == "__main__":
    unittest.main()
