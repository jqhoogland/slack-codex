import threading

import pytest

import codex_rpc
import event_worker as worker
import slack_codex as app


def config(tmp_path):
    skill = tmp_path / "SKILL.md"
    skill.write_text("Handle the request.")
    workflow = {
        "project": str(tmp_path),
        "skill": str(skill),
        "sandbox": "read-only",
        "instructions": "Handle the request.",
        "app_server_project_id": "P",
    }
    return {
        "team_id": "T",
        "user_id": "U",
        "slack_app_id": "A",
        "status_reactions": False,
        "workflows": {"robot_face": workflow, "inbox_tray": workflow.copy()},
    }


def event(emoji="robot_face", eid="E", ts="1.000001"):
    return {
        "team_id": "T",
        "api_app_id": "A",
        "event_id": eid,
        "event": {
            "type": "reaction_added",
            "user": "U",
            "item_user": "OTHER",
            "reaction": emoji,
            "event_ts": "2000.0",
            "item": {"type": "message", "channel": "C", "ts": ts},
        },
    }


def test_attribution_and_scope(tmp_path):
    c = config(tmp_path)
    db = worker.database(tmp_path)
    for path, value in [
        (("team_id",), "OTHER"),
        (("api_app_id",), "OTHER"),
        (("event", "user"), "OTHER"),
        (("event", "reaction"), "smile"),
        (("event", "item", "type"), "file"),
    ]:
        payload = event()
        dest = payload
        for key in path[:-1]:
            dest = dest[key]
        dest[path[-1]] = value
        assert worker.accept(db, c, payload) is None
    assert worker.accept(db, c, event()) == 1


def test_old_message_new_event_and_restart_dedup(tmp_path):
    c = config(tmp_path)
    db = worker.database(tmp_path)
    assert worker.accept(db, c, event()) == 1
    assert worker.accept(db, c, event()) is None
    db.close()
    db = worker.database(tmp_path)
    assert worker.accept(db, c, event(eid="REMOVED_AND_ADDED")) is None
    assert worker.accept(db, c, event("inbox_tray", "E2")) == 2
    assert db.execute("SELECT count(*) FROM jobs").fetchone()[0] == 2


def test_baseline_event_does_not_launch(tmp_path):
    c = config(tmp_path)
    db = worker.database(tmp_path)
    app.discover(db, c, {("C", "1.000001", "robot_face"): {}})
    assert worker.accept(db, c, event()) is None
    assert db.execute("SELECT status FROM jobs").fetchone()[0] == "baseline"


def test_restart_retains_chat_and_holds_uncertain_work(tmp_path):
    c = config(tmp_path)
    db = worker.database(tmp_path)
    worker.accept(db, c, event())
    with db:
        db.execute("UPDATE jobs SET status='running'")
        db.execute(
            "INSERT INTO runs(job,started,status,thread_id) VALUES(1,0,'running','CHAT')"
        )
    worker.recover(db)
    assert db.execute("SELECT status FROM jobs").fetchone()[0] == "interrupted"
    assert db.execute("SELECT thread_id FROM runs").fetchone()[0] == "CHAT"
    assert worker.accept(db, c, event(eid="E2")) is None


def test_both_workflows_run_in_parallel(tmp_path):
    c = config(tmp_path)
    db = worker.database(tmp_path)
    worker.accept(db, c, event())
    worker.accept(db, c, event("inbox_tray", "E2"))
    barrier = threading.Barrier(2)
    errors = []

    class Slack:
        def thread(self, *args, **kwargs):
            return {"thread_ts": "PARENT", "selected_ts": "REPLY", "messages": []}

    def runner(c, w, prompt, output, started, stop):
        started("CHAT-" + output.name)
        assert "PARENT" in prompt and "REPLY" in prompt
        barrier.wait(timeout=3)
        return "succeeded", None

    def run(emoji):
        local = worker.database(tmp_path)
        try:
            assert worker.run_one(
                tmp_path, c, local, Slack(), emoji, threading.Event(), runner
            )
        except Exception as e:  # noqa: BLE001, isolate worker failures
            errors.append(e)
        finally:
            local.close()

    threads = [threading.Thread(target=run, args=(emoji,)) for emoji in c["workflows"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)
    assert not errors
    assert [r[0] for r in db.execute("SELECT status FROM jobs")] == [
        "succeeded",
        "succeeded",
    ]
    assert (
        len(list(db.execute("SELECT thread_id FROM runs WHERE thread_id IS NOT NULL")))
        == 2
    )


def test_fetch_failures_are_bounded(tmp_path):
    c = config(tmp_path)
    db = worker.database(tmp_path)
    worker.accept(db, c, event())

    class Slack:
        def thread(self, *args, **kwargs):
            raise app.Error("offline")

    for _ in range(3):
        worker.run_one(tmp_path, c, db, Slack(), "robot_face", threading.Event())
        with db:
            db.execute("UPDATE jobs SET next_try=0")
    assert tuple(db.execute("SELECT status,attempts FROM jobs").fetchone()) == (
        "failed",
        3,
    )


def test_runner_receives_request_title_without_changing_configuration(tmp_path):
    c = config(tmp_path)
    db = worker.database(tmp_path)
    worker.accept(db, c, event())
    titles = []

    class Slack:
        def thread(self, *args, **kwargs):
            return {"selected_message": {"text": "Add news RSS feeds"}, "messages": []}

    def runner(c, workflow, *args):
        titles.append(workflow["title"])
        return "succeeded", None

    worker.run_one(tmp_path, c, db, Slack(), "robot_face", threading.Event(), runner)
    assert titles == ["Slack task: Add news RSS feeds"]
    assert "title" not in c["workflows"]["robot_face"]
    db.close()


@pytest.mark.parametrize(
    ("sandbox", "approval"),
    [("read-only", "on-request"), ("danger-full-access", "never")],
)
def test_project_and_sandbox_are_explicit(tmp_path, sandbox, approval):
    w = config(tmp_path)["workflows"]["robot_face"]
    w["sandbox"] = sandbox
    params = codex_rpc.start_params(w)
    assert params["projectId"] == "P"
    assert params["sandbox"] == sandbox
    assert params["approvalPolicy"] == approval
    assert params["approvalsReviewer"] == "user"
    assert params["ephemeral"] is False


def test_blocked_job_removes_spinner_without_checkmark(tmp_path):
    c = config(tmp_path)
    c["status_reactions"] = True
    db = worker.database(tmp_path)
    worker.accept(db, c, event())
    calls = []

    class Slack:
        def thread(self, *args, **kwargs):
            return {"messages": []}

        def call(self, method, **params):
            calls.append((method, params["name"]))

    def runner(*args):
        return "blocked", "Permission needed"

    worker.run_one(tmp_path, c, db, Slack(), "robot_face", threading.Event(), runner)
    app.sync_reactions(db, c, Slack())
    assert calls == [("reactions.remove", "codex_working")]
    assert db.execute("SELECT status FROM jobs").fetchone()[0] == "blocked"


def test_recovery_clears_old_spinner(tmp_path):
    c = config(tmp_path)
    c["status_reactions"] = True
    db = worker.database(tmp_path)
    worker.accept(db, c, event())
    with db:
        db.execute("UPDATE jobs SET status='running'")
    worker.recover(db)
    assert db.execute("SELECT desired FROM reaction_updates").fetchone()[0] == "stopped"


def test_service_environment_finds_user_tools_without_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("SLACK_TOKEN", "secret-for-test")
    env = app.clean_env()
    assert str(app.Path.home() / ".local/bin") in env["PATH"].split(":")
    assert "SLACK_TOKEN" not in env


def test_custom_emoji_runs_configured_workflow_without_reply_authority(tmp_path):
    c = config(tmp_path)
    c["workflows"]["bookmark"] = {
        **c["workflows"]["robot_face"],
        "action": "custom",
        "instructions": "Extract references, check duplicates, then save a local reading list. Do not post to Slack.",
        "app_server_project_id": "READING",
    }
    db = worker.database(tmp_path)
    assert worker.accept(db, c, event("bookmark", "CUSTOM")) == 1
    received = []

    class Slack:
        def thread(self, *args, **kwargs):
            return {"selected_message": {"text": "A paper to save"}, "messages": []}

    def runner(c, workflow, prompt, output, started, stop):
        received.append((workflow, prompt))
        started("READING-CHAT")
        return "succeeded", None

    assert worker.run_one(
        tmp_path, c, db, Slack(), "bookmark", threading.Event(), runner
    )
    workflow, prompt = received[0]
    assert workflow["app_server_project_id"] == "READING"
    assert "Extract references, check duplicates" in prompt
    assert "Do not post to Slack." in prompt
    assert "Carry out its clear implied actions and reply" not in prompt
    assert "create or find the relevant Linear issue" not in prompt
    assert worker.accept(db, c, event("bookmark", "READDED")) is None
    assert db.execute("SELECT status FROM jobs").fetchone()[0] == "succeeded"
    db.close()


def test_new_emoji_gets_its_own_baseline(tmp_path):
    c = config(tmp_path)
    db = worker.database(tmp_path)
    app.discover(db, c, {})
    c["workflows"]["bookmark"] = {**c["workflows"]["robot_face"], "action": "custom"}
    app.discover(db, c, {("C", "1.000001", "bookmark"): {}})
    assert worker.accept(db, c, event("bookmark", "OLD")) is None
    assert worker.accept(db, c, event("bookmark", "NEW", "2.000001")) is not None
    assert [r[0] for r in db.execute("SELECT status FROM jobs ORDER BY id")] == [
        "baseline",
        "queued",
    ]
    db.close()
