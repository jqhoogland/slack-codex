"""Codex app-server client. Uses the installed CLI protocol over stdin."""

import json
import queue
import re
import subprocess
import threading
import time

import slack_codex as app


class Rpc:
    def __init__(self, codex, log=None):
        self.events = queue.Queue()
        self.next_id = 0
        self.log = log
        self.proc = subprocess.Popen(
            [codex, "app-server"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=app.clean_env(),
        )
        threading.Thread(target=self._read, daemon=True).start()
        self.call(
            "initialize",
            {
                "clientInfo": {"name": "slack_codex", "version": "0.2"},
                "capabilities": {"experimentalApi": True},
            },
        )
        self.send({"method": "initialized"})

    def _read(self):
        try:
            for line in self.proc.stdout:
                self.events.put(json.loads(line))
        finally:
            self.events.put(None)

    def send(self, value):
        self.proc.stdin.write(json.dumps(value) + "\n")
        self.proc.stdin.flush()

    def receive(self, timeout=60):
        try:
            item = self.events.get(timeout=timeout)
        except queue.Empty:
            raise app.Error("Codex response timed out.") from None
        if item is None:
            raise app.Error("Codex app-server stopped.")
        if self.log:
            self.log.write(json.dumps(item) + "\n")
            self.log.flush()
        return item

    def call(self, method, params, timeout=120):
        self.next_id += 1
        request_id = self.next_id
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            item = self.receive(max(0.01, deadline - time.monotonic()))
            if item.get("id") == request_id and "method" not in item:
                if "error" in item:
                    raise app.Error("Codex request failed: " + item["error"]["message"])
                return item["result"]
            if "id" in item and "method" in item:
                raise app.Error("Codex needs user input. Continue the chat in the app.")

    def close(self):
        self.proc.terminate()
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def start_params(workflow, ephemeral=False):
    tools = [
        {
            "type": "function",
            "name": "schedule_chat_archive",
            "description": "Register this chat for deterministic archival 24 hours after confirmed task completion with no further activity. Uses no model wakeups.",
            "inputSchema": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        }
    ]
    if workflow.get("action") == "linear_intake":
        tools.append(
            {
                "type": "function",
                "name": "register_linear_issue",
                "description": "Register a verified Linear issue UUID against the original selected Slack message for completion checks. No Slack write.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"issue_id": {"type": "string"}},
                    "required": ["issue_id"],
                    "additionalProperties": False,
                },
            }
        )
    return {
        "dynamicTools": tools,
        "projectId": workflow["app_server_project_id"],
        "cwd": workflow["project"],
        "runtimeWorkspaceRoots": [workflow["project"]],
        "sandbox": workflow["sandbox"],
        "approvalPolicy": "on-request",
        "approvalsReviewer": "user",
        "ephemeral": ephemeral,
        "config": {
            "features.apps": True,
            "sandbox_workspace_write.network_access": False,
            "mcp_servers.airtable.enabled": False,
            "mcp_servers.playwright.enabled": False,
            "mcp_servers.granola.enabled": False,
            "mcp_servers.node_repl.enabled": False,
            "mcp_servers.computer-use.enabled": False,
        },
    }


def run(c, workflow, prompt, output, on_started, stop):
    """Create one durable chat and one turn. Never retry a submitted turn."""
    with (output / "events.jsonl").open("w") as log, Rpc(c["codex"], log) as rpc:
        result = rpc.call("thread/start", start_params(workflow))
        thread = result["thread"]
        thread_id = thread["id"]
        on_started(thread_id)
        if thread.get("projectId") != workflow["app_server_project_id"]:
            raise app.Error("Codex did not use the selected project.")
        if result.get("approvalPolicy") != "on-request":
            raise app.Error("Codex did not retain user approvals.")
        expected = {"read-only": "readOnly", "workspace-write": "workspaceWrite"}
        if result.get("sandbox", {}).get("type") != expected[workflow["sandbox"]]:
            raise app.Error("Codex did not apply the selected sandbox.")
        rpc.call(
            "thread/name/set",
            {"threadId": thread_id, "name": workflow.get("title", "Slack task")},
        )
        turn = rpc.call(
            "turn/start",
            {
                "threadId": thread_id,
                "input": [{"type": "text", "text": prompt}],
                "outputSchema": json.loads(
                    (app.ROOT / "result-schema.json").read_text()
                ),
            },
        )["turn"]
        deadline = time.monotonic() + c["timeout_seconds"]
        answer = ""
        archive_requested = False
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                event = rpc.receive(min(1, max(0.01, deadline - time.monotonic())))
            except app.Error as e:
                if "timed out" in str(e):
                    continue
                raise
            params = event.get("params", {})
            if params.get("threadId") not in (None, thread_id):
                continue
            if event.get("method") == "item/tool/call":
                try:
                    if params.get("threadId") != thread_id:
                        raise app.Error("Tool call belongs to another chat.")
                    if params["tool"] == "schedule_chat_archive":
                        archive_requested = True
                        message = "Archive registration will take effect only after this turn reports task completion."
                    elif (
                        params["tool"] == "register_linear_issue"
                        and workflow.get("action") == "linear_intake"
                    ):
                        import linear_sync

                        issue = params["arguments"]["issue_id"]
                        if not re.fullmatch(
                            r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}",
                            issue,
                        ):
                            raise app.Error("Use the verified issue UUID.")
                        context = json.loads((output / "context.json").read_text())
                        with linear_sync.database(output.parent.parent) as db:
                            db.execute(
                                "INSERT OR IGNORE INTO linear_links(issue,team,user,channel,ts) VALUES(?,?,?,?,?)",
                                (
                                    issue,
                                    c["team_id"],
                                    c["user_id"],
                                    context["channel"],
                                    context["selected_ts"],
                                ),
                            )
                        db.close()
                        message = (
                            "Completion link saved for the original selected message."
                        )
                    else:
                        raise app.Error("Unknown local workflow tool.")
                    reply = {
                        "success": True,
                        "contentItems": [{"type": "inputText", "text": message}],
                    }
                except Exception as exc:  # noqa: BLE001, redact boundary errors
                    reply = {
                        "success": False,
                        "contentItems": [
                            {
                                "type": "inputText",
                                "text": str(exc)
                                if isinstance(exc, app.Error)
                                else "Local registration failed.",
                            }
                        ],
                    }
                rpc.send({"id": event["id"], "result": reply})
                continue
            if "id" in event and "method" in event:
                # Preserve approvals. Leave this task for the user in its chat.
                rpc.send(
                    {
                        "id": 999999,
                        "method": "turn/interrupt",
                        "params": {"threadId": thread_id, "turnId": turn["id"]},
                    }
                )
                return (
                    "blocked",
                    "Codex needs user input. Continue this chat in the app.",
                )
            if event.get("method") == "item/completed":
                item = params.get("item", {})
                if item.get("type") == "agentMessage":
                    answer = item.get("text", "")
                    (output / "answer.md").write_text(answer)
            if event.get("method") == "turn/completed":
                if params["turn"].get("status") != "completed":
                    return "failed", "Codex turn failed. Inspect the saved output."
                try:
                    value = json.loads(answer)
                    status = value["status"]
                    if status not in ("completed", "blocked", "failed"):
                        raise ValueError
                except (ValueError, KeyError):
                    return "failed", "Codex did not return a valid task result."
                if status == "completed" and archive_requested:
                    import chat_archive

                    db = chat_archive.database(output.parent.parent)
                    try:
                        due = chat_archive.register(db, rpc, thread_id)
                        app.save(
                            output / "archive.json",
                            {"thread_id": thread_id, "due": due},
                        )
                    finally:
                        db.close()
                return (
                    ("succeeded", None)
                    if status == "completed"
                    else (status, value.get("summary"))
                )
        rpc.send(
            {
                "id": 999999,
                "method": "turn/interrupt",
                "params": {"threadId": thread_id, "turnId": turn["id"]},
            }
        )
        return (
            "interrupted",
            "Stopped or timed out. Continue the saved chat in the app.",
        )
