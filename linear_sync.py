"""Check linked Linear issues and add a Slack completion reaction without a model."""

import argparse
import getpass
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

import slack_codex as app


def database(home):
    db = app.database(home)
    db.execute("""CREATE TABLE IF NOT EXISTS linear_links(
        issue TEXT NOT NULL, team TEXT NOT NULL, user TEXT NOT NULL,
        channel TEXT NOT NULL, ts TEXT NOT NULL,
        notified INTEGER NOT NULL DEFAULT 0, attempts INTEGER NOT NULL DEFAULT 0,
        next_try REAL NOT NULL DEFAULT 0, error TEXT, state TEXT,
        PRIMARY KEY(issue,team,user,channel,ts))""")
    return db


def credential():
    from keyring.backends.macOS import Keyring

    value = Keyring().get_password(app.SERVICE, "linear-read")
    if not value:
        raise app.Error("Run linear_sync.py credential in a local terminal first.")
    return value


class Linear:
    def __init__(self, secret):
        self.secret = secret
        self.retry_at = 0

    def query(self, query, variables):
        if time.monotonic() < self.retry_at:
            raise app.Error("Linear rate limit wait is still active.")
        request = urllib.request.Request(
            "https://api.linear.app/graphql",
            data=json.dumps({"query": query, "variables": variables}).encode(),
            headers={"Authorization": self.secret, "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                body = json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                try:
                    delay = max(300, float(exc.headers.get("Retry-After", "300")))
                except ValueError:
                    delay = 300
                self.retry_at = time.monotonic() + delay
                raise app.Error(
                    "Linear rate limit reached; retry on a later poll."
                ) from None
            raise app.Error("Linear request failed (HTTP %s)." % exc.code) from None
        except (OSError, ValueError):
            raise app.Error("Linear request failed or returned invalid data.") from None
        if body.get("errors") or not isinstance(body.get("data"), dict):
            raise app.Error("Linear query failed. Check account access.")
        return body["data"]

    def states(self, issues):
        # Bound query complexity and use variables for all external IDs.
        result = {}
        for offset in range(0, len(issues), 25):
            batch = issues[offset : offset + 25]
            declarations = ",".join(f"$i{i}:String!" for i in range(len(batch)))
            fields = " ".join(
                f"x{i}:issue(id:$i{i}){{id state{{type}}}}" for i in range(len(batch))
            )
            data = self.query(
                f"query({declarations}){{{fields}}}",
                {f"i{i}": v for i, v in enumerate(batch)},
            )
            for i, issue in enumerate(batch):
                node = data.get(f"x{i}")
                if not node or not node.get("state", {}).get("type"):
                    raise app.Error("A linked Linear issue is missing or inaccessible.")
                result[issue] = node["state"]["type"]
        return result


def sync(db, c, linear, slack, dry_run=False, now=None):
    now = time.time() if now is None else now
    rows = db.execute(
        """SELECT rowid,* FROM linear_links WHERE team=? AND user=?
        AND notified=0 AND attempts<3 AND next_try<=?""",
        (c["team_id"], c["user_id"], now),
    ).fetchall()
    if not rows:
        return []
    states = linear.states(sorted({r["issue"] for r in rows}))
    results = []
    for row in rows:
        state = states[row["issue"]]
        results.append(
            {
                "issue": row["issue"],
                "channel": row["channel"],
                "ts": row["ts"],
                "state": state,
                "would_react": state == "completed",
            }
        )
        if dry_run:
            continue
        with db:
            db.execute(
                "UPDATE linear_links SET state=? WHERE rowid=?", (state, row["rowid"])
            )
        if state != "completed":
            continue
        try:
            # Slack already_reacted is success. A crash after this call is safe to retry.
            slack.call(
                "reactions.add",
                channel=row["channel"],
                timestamp=row["ts"],
                name="white_check_mark",
            )
            slack.call(
                "reactions.remove",
                channel=row["channel"],
                timestamp=row["ts"],
                name="inbox_tray",
            )
        except app.Error:
            with db:
                db.execute(
                    """UPDATE linear_links SET attempts=attempts+1,next_try=?,error=?
                    WHERE rowid=?""",
                    (
                        now + 300 * 2 ** row["attempts"],
                        "Slack completion reaction failed.",
                        row["rowid"],
                    ),
                )
        else:
            with db:
                db.execute(
                    "UPDATE linear_links SET notified=1,error=NULL WHERE rowid=?",
                    (row["rowid"],),
                )
    return results


def main():
    os.umask(0o077)
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="action", required=True)
    for name in ("credential", "check", "sync", "serve", "status", "retry"):
        sub.add_parser(name)
    link = sub.add_parser("link")
    link.add_argument("issue")
    link.add_argument("slack_url")
    args = p.parse_args()
    try:
        c = app.config(app.HOME)
        db = database(app.HOME)
        if args.action == "credential":
            if not sys.stdin.isatty():
                raise app.Error(
                    "Use a local interactive terminal for hidden credential entry."
                )
            secret = getpass.getpass("Linear read-only API key (hidden): ").strip()
            Linear(secret).query("{viewer{id}}", {})
            from keyring.backends.macOS import Keyring

            Keyring().set_password(app.SERVICE, "linear-read", secret)
            print("Stored Linear key in macOS Keychain.")
        elif args.action == "link":
            if not re.fullmatch(
                r"(?:[A-Za-z][A-Za-z0-9]*-[0-9]+|[0-9a-fA-F-]{36})", args.issue
            ):
                raise app.Error("Use a Linear issue identifier or UUID.")
            match = re.fullmatch(
                r"https://resolutionalignment\.slack\.com/archives/([CDG][A-Z0-9]+)/p([0-9]{10})([0-9]{6})",
                args.slack_url,
            )
            if not match:
                raise app.Error(
                    "Use a Resolution Slack message permalink without query parameters."
                )
            channel, seconds, fraction = match.groups()
            with db:
                db.execute(
                    "INSERT OR IGNORE INTO linear_links(issue,team,user,channel,ts) VALUES(?,?,?,?,?)",
                    (
                        args.issue,
                        c["team_id"],
                        c["user_id"],
                        channel,
                        seconds + "." + fraction,
                    ),
                )
            print("Issue link saved. No Slack write was made.")
        elif args.action == "status":
            print(
                json.dumps(
                    [dict(r) for r in db.execute("SELECT * FROM linear_links")],
                    indent=2,
                )
            )
        elif args.action == "retry":
            with db:
                db.execute(
                    "UPDATE linear_links SET attempts=0,next_try=0,error=NULL WHERE notified=0"
                )
            print("Pending links can retry on the next sync.")
        else:
            if args.action != "check" and not c.get("linear_completion_enabled"):
                raise app.Error(
                    "Completion sync is not enabled. Finish the read-only check and Slack scope setup first."
                )
            lock_home = app.HOME / "linear-completion"
            lock_home.mkdir(exist_ok=True, mode=0o700)
            with app.lock(lock_home):
                linear = Linear(credential())
                slack = None
                if args.action != "check":
                    if "reactions:write" not in c["scopes"]:
                        raise app.Error("Slack reactions:write is required.")
                    slack = app.Slack(app.token())
                    slack.identity(c)
                while True:
                    try:
                        print(
                            json.dumps(
                                sync(
                                    db, c, linear, slack, dry_run=args.action == "check"
                                )
                            ),
                            flush=True,
                        )
                    except app.Error as exc:
                        if args.action != "serve":
                            raise
                        print(str(exc), file=sys.stderr, flush=True)
                    if args.action != "serve":
                        break
                    time.sleep(300)
    except app.Error as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except (OSError, ValueError, KeyError):
        print("Completion sync failed. Check local configuration.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
