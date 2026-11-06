"""Local Slack Socket Mode listener with one agent slot per workflow."""

import argparse
import json
import logging
import os
import signal
import threading
import time

from keyring.backends.macOS import Keyring
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse

import codex_rpc
import slack_codex as app

LOG = logging.getLogger("slack-codex.events")


def database(home):
    db = app.database(home)
    db.executescript("""
    CREATE TABLE IF NOT EXISTS slack_events(
      event_id TEXT PRIMARY KEY, received REAL NOT NULL, event_ts TEXT,
      channel TEXT, ts TEXT, emoji TEXT, job INTEGER);
    """)
    return db


def accept(db, c, payload, now=None):
    """Commit a matching event before acknowledging it. No network or model calls."""
    event = payload.get("event", {})
    item = event.get("item", {})
    if (
        payload.get("team_id") != c["team_id"]
        or payload.get("api_app_id") != c["slack_app_id"]
        or event.get("type") != "reaction_added"
        or event.get("user") != c["user_id"]
        or event.get("reaction") not in c["workflows"]
        or item.get("type") != "message"
        or not item.get("channel")
        or not item.get("ts")
        or not payload.get("event_id")
    ):
        return None
    now = time.time() if now is None else now
    emoji = event["reaction"]
    with db:
        db.execute("BEGIN IMMEDIATE")
        seen = db.execute(
            "INSERT OR IGNORE INTO slack_events VALUES(?,?,?,?,?,?,NULL)",
            (
                payload["event_id"],
                now,
                event.get("event_ts"),
                item["channel"],
                item["ts"],
                emoji,
            ),
        )
        if not seen.rowcount:
            return None
        row = db.execute(
            """INSERT OR IGNORE INTO jobs
            (team,user,channel,ts,emoji,workflow,status,discovered)
            VALUES(?,?,?,?,?,?,'queued',?)""",
            (
                c["team_id"],
                c["user_id"],
                item["channel"],
                item["ts"],
                emoji,
                json.dumps(c["workflows"][emoji]),
                now,
            ),
        )
        job = db.execute(
            "SELECT id FROM jobs WHERE team=? AND user=? AND channel=? AND ts=? AND emoji=?",
            (c["team_id"], c["user_id"], item["channel"], item["ts"], emoji),
        ).fetchone()[0]
        db.execute(
            "UPDATE slack_events SET job=? WHERE event_id=?", (job, payload["event_id"])
        )
        if row.rowcount and c.get("status_reactions"):
            app.queue_reaction(db, job, "working")
        return job if row.rowcount else None


def recover(db):
    # A known chat or an uncertain turn must not launch again after a restart.
    with db:
        db.execute("UPDATE jobs SET status='queued' WHERE status='fetching'")
        db.execute(
            "UPDATE jobs SET status='interrupted',error='Service stopped during a run. Inspect the saved chat before rerun.' WHERE status='running'"
        )
        db.execute(
            "UPDATE runs SET status='interrupted',finished=? WHERE status='running'",
            (time.time(),),
        )
        for row in db.execute(
            "SELECT id FROM jobs WHERE status IN ('blocked','failed','interrupted')"
        ):
            app.queue_reaction(db, row["id"], "stopped")


def run_one(home, c, db, slack, emoji, stop, runner=codex_rpc.run, job_id=None):
    with db:
        db.execute("BEGIN IMMEDIATE")
        job = db.execute(
            "SELECT * FROM jobs WHERE team=? AND user=? AND emoji=? AND status='queued' AND next_try<=? AND (? IS NULL OR id=?) ORDER BY id LIMIT 1",
            (c["team_id"], c["user_id"], emoji, time.time(), job_id, job_id),
        ).fetchone()
        if not job:
            return False
        db.execute(
            "UPDATE jobs SET status='fetching',attempts=attempts+1 WHERE id=?",
            (job["id"],),
        )
    workflow = json.loads(job["workflow"])
    try:
        if workflow != c["workflows"][emoji]:
            raise app.Error("Workflow changed. Use rerun to use the new instructions.")
        context = slack.thread(c, job["channel"], job["ts"], emoji, verify=False)
    except app.Error as e:
        attempt = job["attempts"] + 1
        with db:
            db.execute(
                "UPDATE jobs SET status=?,error=?,next_try=? WHERE id=?",
                (
                    "queued" if attempt < 3 else "failed",
                    str(e),
                    time.time() + 60 * attempt,
                    job["id"],
                ),
            )
        return True
    with db:
        run_id = db.execute(
            "INSERT INTO runs(job,started,status) VALUES(?,?,'running')",
            (job["id"], time.time()),
        ).lastrowid
        db.execute(
            "UPDATE jobs SET status='running',error=NULL WHERE id=?", (job["id"],)
        )
    output = home / "runs" / str(run_id)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    app.save(output / "context.json", context)
    prompt = app.prompt(workflow, context)
    (output / "prompt.txt").write_text(prompt)
    with db:
        db.execute("UPDATE runs SET output=? WHERE id=?", (str(output), run_id))

    def started(thread_id):
        with db:
            db.execute("UPDATE runs SET thread_id=? WHERE id=?", (thread_id, run_id))
        LOG.info("job=%s chat=%s started", job["id"], thread_id)

    try:
        titled_workflow = {**workflow, "title": app.chat_title(workflow, context)}
        status, error = runner(c, titled_workflow, prompt, output, started, stop)
    except Exception as e:  # noqa: BLE001, isolate worker failures
        status, error = (
            "failed",
            str(e) if isinstance(e, app.Error) else type(e).__name__,
        )
    with db:
        db.execute(
            "UPDATE runs SET status=?,finished=?,error=? WHERE id=?",
            (status, time.time(), error, run_id),
        )
        db.execute(
            "UPDATE jobs SET status=?,error=? WHERE id=?", (status, error, job["id"])
        )
        if c.get("status_reactions"):
            app.queue_reaction(
                db, job["id"], "done" if status == "succeeded" else "stopped"
            )
    LOG.info("job=%s status=%s", job["id"], status)
    return True


def serve(home, c, receive_only=False):
    if not receive_only and not app.approved(home, c):
        raise app.Error("Run a successful dry run for the current configuration first.")
    stop = threading.Event()
    wake = threading.Event()
    reconnect = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: (stop.set(), wake.set(), reconnect.set()))
    secret = Keyring().get_password(app.SERVICE, "slack-app")
    if not secret:
        raise app.Error("The Slack app token is missing from Keychain.")
    db = database(home)
    slack = app.Slack(app.token())
    slack.identity(c)
    # One initial scan establishes new-emoji baselines and catches up existing ones.
    identity = c["team_id"] + ":" + c["user_id"] + ":"
    if any(
        not db.execute(
            "SELECT 1 FROM meta WHERE key=?", ("baseline:" + identity + e,)
        ).fetchone()
        for e in c["workflows"]
    ):
        app.discover(db, c, slack.matches(c))
    else:
        reconnect.set()
    recover(db)
    db.close()
    LOG.info("Startup scan complete. Waiting for Slack events.")
    # SDK errors can include connection URLs. Keep its logger out of saved logs.
    sdk_log = logging.getLogger("slack-codex.socket-sdk")
    sdk_log.disabled = True
    client = SocketModeClient(app_token=secret, logger=sdk_log, concurrency=1)
    hello_count = 0

    def incoming(_client, message, _raw):
        nonlocal hello_count
        if message.get("type") == "hello":
            hello_count += 1
            LOG.info("Socket Mode connected")
            app.save(
                home / "socket-status.json",
                {"connected_at": time.time(), "pid": os.getpid()},
            )
            if hello_count > 1:
                reconnect.set()

    client.message_listeners.append(incoming)

    def request(_client, request):
        try:
            if request.type == "events_api":
                with database(home) as event_db:
                    job = accept(event_db, c, request.payload)
                event_db.close()
                if job:
                    LOG.info("Slack event queued job=%s", job)
                    wake.set()
            _client.send_socket_mode_response(
                SocketModeResponse(envelope_id=request.envelope_id)
            )
        except Exception as e:  # noqa: BLE001, isolate worker failures
            LOG.error("Event was not acknowledged: %s", type(e).__name__)

    client.socket_mode_request_listeners.append(request)
    threads = []

    def worker(emoji):
        local_db = database(home)
        local_slack = app.Slack(app.token())
        try:
            while not stop.is_set():
                if not run_one(home, c, local_db, local_slack, emoji, stop):
                    wake.wait(1)
                    wake.clear()
        finally:
            local_db.close()

    def reactions():
        local_db = database(home)
        local_slack = app.Slack(app.token())
        try:
            while not stop.is_set():
                app.sync_reactions(local_db, c, local_slack)
                stop.wait(1)
        finally:
            local_db.close()

    def maintenance():
        import chat_archive

        last_archive_check = 0
        local_db = database(home)
        local_slack = app.Slack(app.token())
        try:
            while not stop.is_set():
                if reconnect.is_set():
                    reconnect.clear()
                    try:
                        app.discover(local_db, c, local_slack.matches(c))
                        LOG.info("Reconnect scan complete")
                        wake.set()
                    except app.Error as e:
                        LOG.error("Reconnect scan failed: %s", e)
                        if not stop.wait(30):
                            reconnect.set()
                if time.monotonic() - last_archive_check >= 300:
                    last_archive_check = time.monotonic()
                    archive_db = chat_archive.database(home)
                    try:
                        if archive_db.execute(
                            "SELECT 1 FROM chat_archives WHERE status='pending' AND due<=?",
                            (time.time(),),
                        ).fetchone():
                            with codex_rpc.Rpc(c["codex"]) as rpc:
                                chat_archive.check(archive_db, rpc)
                    except app.Error as e:
                        LOG.error("Archive check failed: %s", e)
                    finally:
                        archive_db.close()
                stop.wait(1)
        finally:
            local_db.close()

    if not receive_only:
        for emoji in c["workflows"]:
            threads.append(threading.Thread(target=worker, args=(emoji,), daemon=True))
        threads.append(threading.Thread(target=maintenance, daemon=True))
        threads.append(threading.Thread(target=reactions, daemon=True))
        for thread in threads:
            thread.start()
    try:
        client.connect()
        while not stop.wait(5):
            if any(not thread.is_alive() for thread in threads):
                raise app.Error(
                    "A worker stopped. Restart the service and inspect failed jobs."
                )
    finally:
        stop.set()
        client.close()
        for thread in threads:
            thread.join(timeout=8)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["serve", "receive-only", "run-job"])
    parser.add_argument("--job", type=int)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    c = app.config(app.HOME)
    with app.lock(app.HOME):
        if args.action == "run-job":
            db = database(app.HOME)
            job = db.execute(
                "SELECT emoji FROM jobs WHERE id=?", (args.job,)
            ).fetchone()
            if not job:
                raise app.Error("Job not found.")
            run_one(
                app.HOME,
                c,
                db,
                app.Slack(app.token()),
                job["emoji"],
                threading.Event(),
                job_id=args.job,
            )
            db.close()
        else:
            serve(app.HOME, c, receive_only=args.action == "receive-only")


if __name__ == "__main__":
    main()
