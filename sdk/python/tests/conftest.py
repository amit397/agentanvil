"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_anvil.deterministic import Clock, SystemClock
from agent_anvil.events import EventWriter
from agent_anvil.tools.base import ToolContext


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def events(tmp_path: Path) -> EventWriter:
    return EventWriter(tmp_path / "events.jsonl", task_id="t-test")


@pytest.fixture
def clock() -> Clock:
    return SystemClock()


@pytest.fixture
def tool_ctx(workspace: Path, events: EventWriter, clock: Clock) -> ToolContext:
    return ToolContext(workspace=workspace, timeout_seconds=10, events=events, clock=clock)
