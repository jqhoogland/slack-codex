"""Archive explicitly completed chats after 24 hours without new activity."""

import argparse
import json
import logging
import os
import time

import slack_codex as app

LOG = logging.getLogger("slack-codex.archive")
DELAY = 24 * 60 * 60


def database(home):
    db = app.database(home)
    db.execute("""CREATE TABLE IF NOT EXISTS chat_archives(
        thread_id TEXT PRIMARY KEY, completed REAL NOT NULL,
        activity INTEGER NOT NULL, due REAL NOT NULL, status TEXT NOT NULL,
        error TEXT)""")
    return db


def register(db, rpc, thread_id, now=None):
    now = time.time() if now is None else now
    thread = rpc.call("thread/read", {"threadId": thread_id, "includeTurns": False})[
        "thread"
    ]
    if thread.get("status", {}).get("type") not in ("idle", "notLoaded"):
        raise app.Error(
            "Chat is still active. Register completion after its turn ends."
        )
    activity = thread["updatedAt"]
    with db:
        db.execute(
            """INSERT INTO chat_archives VALUES(?,?,?,?,?,NULL)
            ON CONFLICT(thread_id) DO UPDATE SET completed=excluded.completed,
            activity=excluded.activity,due=excluded.due,status='pending',error=NULL""",
            (thread_id, now, activity, max(now, activity) + DELAY, "pending"),
        )
    return max(now, activity) + DELAY


def check(db, rpc, now=None):
    now = time.time() if now is None else now
    for row in db.execute(
        "SELECT * FROM chat_archives WHERE status='pending' AND due<=?", (now,)
    ).fetchall():
        try:
            thread = rpc.call(
                "thread/read", {"threadId": row["thread_id"], "includeTurns": False}
            )["thread"]
            status = thread.get("status", {}).get("type")
            if thread["updatedAt"] != row["activity"]:
                # New work invalidates the completion declaration. The skill must
                # register completion again when that work is actually finished.
                with db:
                    db.execute(
                        "UPDATE chat_archives SET status='activity_changed',error=NULL WHERE thread_id=?",
                        (row["thread_id"],),
                    )
                continue
            if status not in ("idle", "notLoaded"):
                continue
            # Check again just before the write to reduce the activity race.
            latest = rpc.call(
                "thread/read", {"threadId": row["thread_id"], "includeTurns": False}
            )["thread"]
            if latest["updatedAt"] != row["activity"] or latest.get("status", {}).get(
                "type"
            ) not in ("idle", "notLoaded"):
                continue
            rpc.call("thread/archive", {"threadId": row["thread_id"]})
            with db:
                db.execute(
                    "UPDATE chat_archives SET status='archived',error=NULL WHERE thread_id=?",
                    (row["thread_id"],),
                )
            LOG.info("Archived completed chat %s", row["thread_id"])
        except app.Error as e:
            with db:
                db.execute(
                    "UPDATE chat_archives SET error=? WHERE thread_id=?",
                    (str(e), row["thread_id"]),
                )


def main():
    from codex_rpc import Rpc

    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=["complete", "cancel", "check", "status"])
    p.add_argument("thread_id", nargs="?")
    args = p.parse_args()
    db = database(app.HOME)
    if args.action == "status":
        print(
            json.dumps(
                [dict(r) for r in db.execute("SELECT * FROM chat_archives")], indent=2
            )
        )
    elif args.action == "cancel":
        with db:
            db.execute(
                "UPDATE chat_archives SET status='cancelled' WHERE thread_id=?",
                (args.thread_id,),
            )
    else:
        with Rpc(app.config(app.HOME)["codex"]) as rpc:
            if args.action == "complete":
                print("Archive due at UTC epoch", register(db, rpc, args.thread_id))
            else:
                check(db, rpc)
    db.close()


if __name__ == "__main__":
    main()
