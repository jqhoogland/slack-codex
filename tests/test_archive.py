import chat_archive as archive


class Rpc:
    def __init__(self):
        self.thread = {"updatedAt": 100, "status": {"type": "notLoaded"}}
        self.archived = []

    def call(self, method, params):
        if method == "thread/read":
            return {"thread": self.thread.copy()}
        assert method == "thread/archive"
        self.archived.append(params["threadId"])
        return {}


def test_archive_after_24_hours_once(tmp_path):
    db = archive.database(tmp_path)
    rpc = Rpc()
    due = archive.register(db, rpc, "CHAT", now=200)
    archive.check(db, rpc, now=due - 1)
    assert not rpc.archived
    archive.check(db, rpc, now=due)
    archive.check(db, rpc, now=due + 1)
    assert rpc.archived == ["CHAT"]


def test_activity_requires_new_completion(tmp_path):
    db = archive.database(tmp_path)
    rpc = Rpc()
    due = archive.register(db, rpc, "CHAT", now=200)
    rpc.thread["updatedAt"] = 300
    archive.check(db, rpc, now=due)
    assert not rpc.archived
    assert (
        db.execute("SELECT status FROM chat_archives").fetchone()[0]
        == "activity_changed"
    )
    due = archive.register(db, rpc, "CHAT", now=due)
    archive.check(db, rpc, now=due)
    assert rpc.archived == ["CHAT"]


def test_active_chat_is_never_archived(tmp_path):
    db = archive.database(tmp_path)
    rpc = Rpc()
    due = archive.register(db, rpc, "CHAT", now=200)
    rpc.thread["status"] = {"type": "active"}
    archive.check(db, rpc, now=due)
    assert not rpc.archived
