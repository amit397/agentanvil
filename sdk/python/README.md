# agent-anvil (Python SDK)

The agent loop runtime for Agent-Anvil. Reads an `AgentTaskSpec`, calls an LLM,
executes MCP-compatible tools in the workspace, and emits a structured JSONL
event stream that the replay engine can consume.

## Running locally

```bash
pip install -e ".[dev]"

# Run a task from the bundled examples (uses the mock LLM client):
AGENT_ANVIL_PROVIDER=mock python -m agent_anvil --task examples/trivial.yaml

# Inspect the trace:
cat /tmp/agent-anvil-trace/events.jsonl | jq -s '.[].type'
```

## Running inside a pod

The operator projects the `AgentTaskSpec` to `/etc/agent-anvil/task.yaml` and
sets `AGENT_ANVIL_*` env vars per INTERFACES.md §4. The SDK's container
entrypoint is `python -m agent_anvil` with no arguments — it picks up the
mounted task and writes to `/var/log/agent-anvil/events.jsonl`.

## Layout

```
src/agent_anvil/
├── __main__.py        # entrypoint
├── loop.py            # main agent loop
├── config.py          # AgentTaskSpec parsing (matches INTERFACES.md §1)
├── events.py          # event models + JSONL writer (INTERFACES.md §2)
├── deterministic.py   # injectable Clock + RNG for replay
├── trace.py           # offline trace loader
├── pricing.py         # token cost table
├── client/            # LLM provider implementations
│   ├── base.py
│   ├── anthropic.py
│   └── mock.py
└── tools/             # built-in tools (bash, file_*, web_search)
```

## Tests

```bash
pytest
```
