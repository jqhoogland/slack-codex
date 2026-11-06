import subprocess
from types import SimpleNamespace

import codex_rpc


def test_only_explicit_accept_grants_permission(monkeypatch):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="accept\n")

    monkeypatch.setattr(codex_rpc.subprocess, "run", run)
    command = 'echo "$(do-not-execute)"'
    assert codex_rpc.command_approval({"command": command}) == "accept"
    assert calls[0][0][:2] == ["/usr/bin/osascript", "-"]
    assert command in calls[0][0][2]
    assert command not in calls[0][1]["input"]
    assert "shell" not in calls[0][1]


def test_dialog_failure_never_approves(monkeypatch):
    monkeypatch.setattr(
        codex_rpc.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1, stdout="accept"),
    )
    assert codex_rpc.command_approval({"command": "test"}) == "decline"


def test_dialog_timeout_never_approves(monkeypatch):
    def run(*a, **k):
        raise subprocess.TimeoutExpired("osascript", 310)

    monkeypatch.setattr(codex_rpc.subprocess, "run", run)
    assert codex_rpc.command_approval({"command": "test"}) == "cancel"


def test_unsupported_or_incomplete_request_cannot_approve():
    assert codex_rpc.command_approval({}) == "cancel"
    assert (
        codex_rpc.command_approval(
            {"command": "test", "availableDecisions": ["acceptForSession", "cancel"]}
        )
        == "cancel"
    )
    assert codex_rpc.command_approval({"command": "x" * 6001}) == "cancel"


def test_close_releases_owned_chat_before_exit():
    calls = []
    rpc = object.__new__(codex_rpc.Rpc)
    rpc.owned_threads = {"CHAT"}
    rpc.call = lambda method, params, **kwargs: calls.append(method)
    rpc.proc = SimpleNamespace(
        terminate=lambda: calls.append("terminate"), wait=lambda **k: None
    )
    rpc.close()
    assert calls == ["thread/unsubscribe", "terminate"]
