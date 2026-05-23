"""Container entrypoint and local CLI for the SDK.

Invocation modes:

    # Inside the operator-managed pod (no flags — picks up env + mounted file):
    python -m agent_anvil

    # Local development:
    python -m agent_anvil --task examples/trivial.yaml --provider mock --trace-dir /tmp/trace

Env vars (per INTERFACES.md §4):
    AGENT_ANVIL_TASK_ID
    AGENT_ANVIL_TRACE_DIR        (default: /var/log/agent-anvil)
    AGENT_ANVIL_WORKSPACE        (default: /workspace)
    AGENT_ANVIL_API_KEY_FILE     (optional; if absent, ANTHROPIC_API_KEY env is used)
    AGENT_ANVIL_PROVIDER         (optional override: anthropic | mock)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .client import LLMClient
from .config import load_task
from .deterministic import SystemClock
from .events import EventWriter
from .loop import LoopRuntime, run

DEFAULT_TASK_PATH = "/etc/agent-anvil/task.yaml"
DEFAULT_TRACE_DIR = "/var/log/agent-anvil"
DEFAULT_WORKSPACE = "/workspace"


def _make_client(provider: str, model: str, api_key: str | None) -> LLMClient:
    if provider == "mock":
        from .client.mock import EchoClient

        return EchoClient()
    if provider == "anthropic":
        from .client.anthropic import AnthropicClient

        return AnthropicClient(model=model, api_key=api_key)
    raise ValueError(f"Unknown provider: {provider}")


def _read_api_key(api_key_file: str | None) -> str | None:
    if api_key_file and Path(api_key_file).is_file():
        return Path(api_key_file).read_text(encoding="utf-8").strip()
    return os.environ.get("ANTHROPIC_API_KEY")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=os.environ.get("AGENT_ANVIL_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(prog="agent-anvil", description="Run an AgentTask.")
    parser.add_argument(
        "--task",
        default=os.environ.get("AGENT_ANVIL_TASK_FILE", DEFAULT_TASK_PATH),
        help="Path to task.yaml (default: %(default)s)",
    )
    parser.add_argument(
        "--trace-dir",
        default=os.environ.get("AGENT_ANVIL_TRACE_DIR", DEFAULT_TRACE_DIR),
        help="Directory for events.jsonl (default: %(default)s)",
    )
    parser.add_argument(
        "--workspace",
        default=os.environ.get("AGENT_ANVIL_WORKSPACE", DEFAULT_WORKSPACE),
        help="Agent workspace path (default: %(default)s)",
    )
    parser.add_argument(
        "--task-id",
        default=os.environ.get("AGENT_ANVIL_TASK_ID", "local-task"),
        help="Task identifier (default: %(default)s)",
    )
    parser.add_argument(
        "--provider",
        default=os.environ.get("AGENT_ANVIL_PROVIDER"),
        help="Override the LLM provider (anthropic | mock).",
    )
    parser.add_argument(
        "--echo-events",
        action="store_true",
        default=os.environ.get("AGENT_ANVIL_ECHO_EVENTS", "").lower() in ("1", "true", "yes"),
        help="Also write each event to stdout (so kubectl logs shows the trace).",
    )
    args = parser.parse_args(argv)

    task_path = Path(args.task)
    if not task_path.is_file():
        print(f"task.yaml not found: {task_path}", file=sys.stderr)
        return 1

    spec = load_task(task_path)
    provider = args.provider or (spec.model.provider if spec.model else "mock")
    model = spec.model.name if spec.model else "scripted"

    api_key_file = os.environ.get("AGENT_ANVIL_API_KEY_FILE")
    api_key = _read_api_key(api_key_file)

    workspace = Path(args.workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    trace_dir = Path(args.trace_dir)
    trace_dir.mkdir(parents=True, exist_ok=True)
    events_path = trace_dir / "events.jsonl"
    # Start with a fresh events file so the trace is one run, not accumulated
    # debris from prior aborted runs. Resume semantics will revisit this.
    if events_path.exists():
        events_path.unlink()

    clock = SystemClock()
    client = _make_client(provider, model, api_key)

    echo = sys.stdout if args.echo_events else None
    with EventWriter(events_path, args.task_id, clock=clock, echo=echo) as events:
        runtime = LoopRuntime(
            task_id=args.task_id,
            workspace=workspace,
            events=events,
            clock=clock,
            client=client,
        )
        done = run(spec, runtime)

    # Per INTERFACES.md §4 "Container exit conventions": exit 0 = task
    # completed. Success vs failure of the agent's *task* lives in the trace,
    # not the exit code. Exit 1 only if the SDK itself crashed (uncaught
    # exception above this point would propagate; we don't trap it).
    _ = done
    return 0


if __name__ == "__main__":
    sys.exit(main())
