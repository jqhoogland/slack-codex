import http.client
from unittest.mock import MagicMock, patch

import pytest

import slack_codex as app


@pytest.mark.parametrize("recovers", [True, False])
def test_incomplete_slack_response_retries_without_exposing_payload(recovers):
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {}
    response.read.side_effect = http.client.IncompleteRead(b"private message", 100)
    success = MagicMock()
    success.__enter__.return_value = success
    success.headers = {}
    success.read.return_value = b'{"ok": true, "items": []}'
    replies = [response, response, success if recovers else response]
    with patch("urllib.request.urlopen", side_effect=replies), patch("time.sleep"):
        client = app.Slack("test-token")
        if recovers:
            assert client.call("reactions.list") == {"ok": True, "items": []}
        else:
            with pytest.raises(app.Error, match="^Slack request failed or response was invalid.$"):
                client.call("reactions.list")
        assert client.calls == 3
