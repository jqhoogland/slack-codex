"""Keep connector work out of the isolated CLI runner."""

from pathlib import Path

import pytest
import slack_codex as app


def test_desktop_workflow_cannot_launch_cli():
    with pytest.raises(app.Error, match="desktop chat"):
        app.command({}, {"execution": "desktop"}, Path("/unused"))


def test_desktop_workflow_stops_before_queue_or_credentials():
    with pytest.raises(app.Error, match="routing"):
        app.run_one(
            None, {"workflows": {"inbox_tray": {"execution": "desktop"}}}, None, None
        )


def test_intake_completion_leaves_task_open(tmp_path):
    import json

    db = app.database(tmp_path)
    with db:
        db.execute(
            "INSERT INTO jobs(team,user,channel,ts,emoji,workflow,status,discovered) VALUES(?,?,?,?,?,?,?,?)",
            (
                "T",
                "U",
                "C",
                "1",
                "inbox_tray",
                json.dumps({"action": "linear_intake"}),
                "done",
                0,
            ),
        )
        app.queue_reaction(db, 1, "done")
    calls = []

    class Slack:
        def call(self, method, **params):
            calls.append((method, params["name"]))

    app.sync_reactions(
        db, {"status_reactions": True, "team_id": "T", "user_id": "U"}, Slack()
    )
    assert calls == [("reactions.remove", "codex_working")]
    assert db.execute("SELECT count(*) FROM reaction_updates").fetchone()[0] == 0
    db.close()
