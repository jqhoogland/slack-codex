import pytest
import slack_codex as app
import linear_sync as sync


class Linear:
    def __init__(self, state):
        self.state = state

    def states(self, issues):
        return {issue: self.state for issue in issues}


class Slack:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def call(self, method, **params):
        self.calls.append((method, params))
        if self.fail:
            raise app.Error("failure")


@pytest.fixture
def setup(tmp_path):
    db = sync.database(tmp_path)
    with db:
        db.execute(
            "INSERT INTO linear_links(issue,team,user,channel,ts) VALUES(?,?,?,?,?)",
            ("HIRE-1", "T", "U", "C", "1.000001"),
        )
    yield db, {"team_id": "T", "user_id": "U"}, tmp_path
    db.close()


@pytest.mark.parametrize("state", ["unstarted", "started", "canceled"])
def test_incomplete_issue_does_not_react(setup, state):
    db, c, _ = setup
    slack = Slack()
    sync.sync(db, c, Linear(state), slack)
    assert slack.calls == []


def test_completed_issue_reacts_once_across_restart(setup):
    db, c, home = setup
    slack = Slack()
    sync.sync(db, c, Linear("completed"), slack)
    restarted = sync.database(home)
    sync.sync(restarted, c, Linear("completed"), slack)
    restarted.close()
    assert slack.calls == [
        (
            "reactions.add",
            {"channel": "C", "timestamp": "1.000001", "name": "white_check_mark"},
        ),
        (
            "reactions.remove",
            {"channel": "C", "timestamp": "1.000001", "name": "inbox_tray"},
        ),
    ]


def test_dry_run_does_not_consume_notification(setup):
    db, c, _ = setup
    assert sync.sync(db, c, Linear("completed"), None, dry_run=True)[0]["would_react"]
    assert db.execute("SELECT notified FROM linear_links").fetchone()[0] == 0


def test_failures_are_bounded_and_retry_is_delayed(setup):
    db, c, _ = setup
    slack = Slack(fail=True)
    for now in (0, 1, 300, 301, 900, 10000):
        sync.sync(db, c, Linear("completed"), slack, now=now)
    assert len(slack.calls) == 3
    assert tuple(
        db.execute("SELECT notified,attempts,error FROM linear_links").fetchone()
    ) == (0, 3, "Slack completion reaction failed.")


def test_other_workspace_does_not_react(setup):
    db, c, _ = setup
    c["team_id"] = "OTHER"
    slack = Slack()
    assert sync.sync(db, c, Linear("completed"), slack) == []
    assert slack.calls == []
