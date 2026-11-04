import threading

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


def test_project_and_sandbox_are_explicit(tmp_path):
    w = config(tmp_path)["workflows"]["robot_face"]
    params = codex_rpc.start_params(w)
    assert params["projectId"] == "P"
    assert params["sandbox"] == "read-only"
    assert params["approvalPolicy"] == "on-request"
    assert params["approvalsReviewer"] == "user"
    assert params["ephemeral"] is False
