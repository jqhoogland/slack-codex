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
