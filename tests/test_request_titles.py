import json

import pytest

import slack_codex as app


@pytest.fixture
def forwarded_request():
    return {
        "selected_message": {
            "ts": "2.000001",
            "text": "<@U123> can you tackle this?",
            "attachments": [
                {
                    "files": [
                        {
                            "subject": "Would love RSS feed(s)^^",
                            "plain_text": "Please add separate feeds for news/research/events.",
                        }
                    ]
                }
            ],
        },
        "thread_ts": "2.000001",
        "messages": [],
    }


def test_forwarded_request_drives_title_and_readable_prompt(forwarded_request):
    workflow = {"title": "Slack query", "instructions": "Handle it.", "skill": "/skill"}
    prompt = app.prompt(workflow, forwarded_request)
    excerpt = json.loads(prompt.splitlines()[1])
    assert excerpt.startswith("Would love RSS feed(s)^^\n\nPlease add separate feeds")
    assert (
        app.chat_title(workflow, forwarded_request)
        == "Slack query: Would love RSS feed(s)^^"
    )
    context = json.loads(prompt.split("SLACK_CONTEXT_JSON\n", 1)[1])
    assert context == forwarded_request


def test_reply_keeps_original_parent_request():
    context = {
        "selected_message": {"ts": "2.000001", "text": "Please handle this."},
        "thread_ts": "1.000001",
        "messages": [{"ts": "1.000001", "text": "Add a news RSS feed."}],
    }
    assert "Add a news RSS feed." in app.request_excerpt(context)


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        (
            {"text": "<@U123> Fix search &amp; filters"},
            "Slack task: Fix search & filters",
        ),
        ({"text": ""}, "Slack task"),
        ({"text": "x" * 200}, "Slack task: " + "x" * 108),
    ],
)
def test_titles_are_readable_and_bounded(message, expected):
    assert app.chat_title({}, {"selected_message": message}) == expected
