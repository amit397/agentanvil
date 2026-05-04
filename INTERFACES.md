# Agent-Anvil — Interface contracts between tracks

> The shared API surface between Track A (Amit) and Track B (Partner). Both tracks code against these contracts. Changes require sign-off from both engineers and a noted entry in this file's changelog.

## Why this document exists

Parallel work without agreed contracts produces integration disasters. The first day of Phase 1 starts with both engineers reviewing this document and committing to it. Anything you build that crosses the track boundary uses these interfaces; if your work needs an interface that's not here, propose it as a PR to this file *before* writing the implementation.

## Table of contents

1. AgentTask CRD spec
2. Trace event schema
3. Trace bundle format
4. Pod environment and config
5. Agent ↔ Proxy sidecar API
6. CLI command structure
7. Sync points and acceptance gates
8. Changelog

---

## 1. AgentTask CRD spec

Frozen by **end of Week 2**. Owned by Track B (defines the type), consumed by Track A (SDK reads it).

```yaml
apiVersion: agenttasks.agentanvil.com/v1
kind: AgentTask
metadata:
  name: example-task
spec:
  # Required: what the agent should do
  prompt: "Fix the bug in src/parser.py that causes infinite recursion on nested arrays"
  systemPrompt: |
    You are a careful coding agent. Read code before editing.

  # Required: model
  model:
    provider: anthropic              # anthropic | openai | local
    name: claude-sonnet-4-5
    apiKeySecretRef:
      name: agent-credentials
      key: anthropic-api-key
    params:                          # passed through to provider
      temperature: 0
      maxTokens: 8192

  # Required: tools available
  tools:
    - name: bash
      timeoutSeconds: 60
    - name: file_read
    - name: file_write
    - name: file_edit

  # Optional: workspace setup
  workspace:
    baseImage: ghcr.io/example/swebench-task:abc123  # read-only base
    initCommand: ["pip", "install", "-r", "requirements.txt"]

  # Optional: limits
  timeoutSeconds: 1800
  maxSteps: 100
  resources:
    cpu: "2"
    memory: "4Gi"
    ephemeralStorage: "10Gi"

  # Optional: checkpointing policy
  checkpointPolicy:
    mode: Manual                     # Manual | EveryStep | Interval
    intervalSeconds: 300

  # Optional: replay config (set by operator when this task is a replay)
  replay:
    checkpointId: "task-abc-123"
    fromStep: 0                      # 0 = full replay, >0 = restore + replay from step

status:
  phase: Pending                     # Pending|Provisioning|Running|Checkpointing|Completed|Failed|Evicted
  currentStep: 0
  startedAt: null
  finishedAt: null
  traceURL: ""                       # s3://bucket/traces/<task-id>/
  podName: ""
  reason: ""                         # human-readable termination reason
  conditions: []                     # standard k8s conditions
```

**Track B builds the type.** Use kubebuilder. Generate Go types with deepcopy + CRD manifests.

**Track A consumes the spec.** The SDK reads its task config from `/etc/agent-anvil/task.yaml` (mounted via downward API + ConfigMap). Track B is responsible for projecting the spec into that file.

### Versioning

CRD is `v1`. Breaking changes during the 6-month build are expected and don't require version bumps. Post-v1.0, version bumps require both engineers' sign-off.

---

## 2. Trace event schema

Frozen by **end of Week 4**. Owned by both tracks (designed jointly). The SDK emits these events; the replay engine consumes them; the eval harness aggregates them.

Events are emitted as a JSONL stream to `/var/log/agent-anvil/events.jsonl` inside the agent container. The recording proxy emits its own events to `/var/log/agent-anvil/proxy-events.jsonl`. Both files are bundled into the trace at task completion.

```jsonc
// Common envelope for all events
{
  "schema": "agent-anvil/v1",
  "task_id": "task-abc-123",
  "step": 5,                          // 0-indexed agent loop iteration
  "ts": "2026-01-15T10:30:00.123Z",  // ISO 8601 UTC
  "monotonic_ns": 4823901230,         // monotonic clock (for ordering)
  "type": "llm_call_start",           // see types below
  "data": { /* type-specific */ }
}
```

### Event types

```
agent_start            — task begins
agent_step_start       — new agent loop iteration
llm_call_start         — request to LLM API
llm_call_end           — response (incl. token counts, cost)
tool_call_start        — agent invokes a tool
tool_call_end          — tool returns
file_mutation          — workspace file changed (recorded by SDK shim around file ops)
network_request        — HTTP request through proxy (recorded by proxy, deduped against tool_call)
network_response       — HTTP response (recorded by proxy)
checkpoint_start       — workspace snapshot beginning
checkpoint_end         — workspace snapshot completed (with snapshot ID)
agent_step_end         — agent loop iteration done
agent_done             — task completed (success or failure)
agent_error            — uncaught exception
```

### Per-type data shapes

```jsonc
// llm_call_start.data
{
  "provider": "anthropic",
  "model": "claude-sonnet-4-5",
  "request_hash": "sha256:abc123...",  // canonicalized request hash
  "messages_count": 12,
  "params": { "temperature": 0, "max_tokens": 8192 }
}

// llm_call_end.data
{
  "request_hash": "sha256:abc123...",
  "response_hash": "sha256:def456...",
  "input_tokens": 4203,
  "output_tokens": 891,
  "stop_reason": "tool_use",
  "cost_usd": 0.0234,
  "latency_ms": 4231
}

// tool_call_start.data
{
  "tool_name": "bash",
  "args": { "command": "pytest tests/test_parser.py" },
  "tool_call_id": "toolu_abc123"
}

// tool_call_end.data
{
  "tool_call_id": "toolu_abc123",
  "result": "...",                    // truncated if > 64KB; full result in trace bundle
  "result_truncated": false,
  "exit_code": 0,
  "latency_ms": 2103,
  "result_blob_path": null            // set if result was offloaded to blob storage
}

// file_mutation.data
{
  "path": "src/parser.py",
  "operation": "edit",                // create | edit | delete
  "size_before": 4203,
  "size_after": 4189,
  "hash_after": "sha256:..."
}

// agent_done.data
{
  "outcome": "completed",             // completed | failed | timeout | max_steps | evicted
  "total_steps": 23,
  "total_cost_usd": 0.42,
  "total_input_tokens": 89234,
  "total_output_tokens": 12039,
  "wall_clock_seconds": 423
}
```

### Determinism and event ordering

Both `ts` and `monotonic_ns` are recorded. **`monotonic_ns` is the source of truth for ordering.** Wall-clock timestamps drift; monotonic does not. Replay events use the original monotonic timestamps so timing analysis remains comparable.

---

## 3. Trace bundle format

Frozen by **end of Week 4**. Owned jointly.

A trace is a tarball stored at `s3://bucket/traces/<task-id>/trace.tar.gz`:

```
trace.tar.gz
├── manifest.json              # version, task_id, timestamps, schema
├── spec.yaml                   # original AgentTask spec
├── events.jsonl                # SDK events (per §2)
├── proxy-events.jsonl          # proxy events (per §2)
├── llm-cache/
│   ├── <request_hash>.req.json
│   └── <request_hash>.res.json
├── network-cache/
│   ├── <request_hash>.req.json
│   └── <request_hash>.res.json
├── tool-blobs/
│   └── <blob_id>               # large tool results offloaded here
├── workspace-snapshots/
│   ├── step-0.tar.gz           # snapshot at start
│   ├── step-5.tar.gz
│   └── step-final.tar.gz
└── README.md                   # human-readable summary, auto-generated
```

### manifest.json

```json
{
  "schema_version": "v1",
  "task_id": "task-abc-123",
  "parent_task_id": null,
  "fork_at_step": null,
  "created_at": "2026-01-15T10:30:00Z",
  "completed_at": "2026-01-15T10:37:23Z",
  "outcome": "completed",
  "agent_anvil_version": "0.1.0",
  "schema_files": {
    "events": "events.jsonl",
    "proxy_events": "proxy-events.jsonl"
  },
  "stats": {
    "total_steps": 23,
    "total_cost_usd": 0.42,
    "snapshots": 5
  }
}
```

### Loading traces

A shared Go package `pkg/trace` provides `Load(path string) (*Trace, error)`. Both tracks import this; only one track owns the implementation. **Track B owns `pkg/trace`** and exposes a stable Go API.

A parallel Python package `agent_anvil.trace` (in the SDK) provides the same load functionality for offline analysis. **Track A owns the Python version.** The two implementations must produce equivalent in-memory representations; cross-language tests verify this.

---

## 4. Pod environment and config

Owned by Track B (operator sets these), consumed by Track A (SDK reads).

### Mounted files in agent container

```
/etc/agent-anvil/
├── task.yaml                   # AgentTask spec (projected from CRD)
├── ca-cert.pem                 # proxy's CA cert for TLS interception
└── proxy-config.json           # proxy mode, endpoint, fork config

/var/log/agent-anvil/           # writable; collected at task end
├── events.jsonl                # SDK writes here
└── proxy-events.jsonl          # proxy writes here

/workspace/                     # OverlayFS merged view
                                # writable, snapshotted at quiescent points
```

### Environment variables

```
AGENT_ANVIL_TASK_ID=task-abc-123
AGENT_ANVIL_PROXY_URL=http://localhost:8080
AGENT_ANVIL_TRACE_DIR=/var/log/agent-anvil
AGENT_ANVIL_WORKSPACE=/workspace
AGENT_ANVIL_API_KEY_FILE=/etc/agent-anvil/secrets/anthropic-api-key
AGENT_ANVIL_MODE=record         # record | replay
AGENT_ANVIL_REPLAY_FROM_STEP=0  # set on replay
HTTP_PROXY=http://localhost:8080
HTTPS_PROXY=http://localhost:8080
SSL_CERT_FILE=/etc/agent-anvil/ca-cert.pem
```

### Container exit conventions

- Exit 0 = task completed (success or failure of *the agent's task* — that's a different signal in the trace)
- Exit 1 = SDK crashed (uncaught exception)
- Exit 124 = SDK detected timeout
- Exit 137 = SIGKILL (operator pod kill)

The operator distinguishes these to set AgentTask `status.reason`.

---

## 5. Agent ↔ Proxy sidecar API

Owned by Track A (both sides). Documented here because both tracks need to know it exists.

The proxy exposes a small HTTP control API on `localhost:8081` (separate from the data plane on 8080). The SDK calls this to coordinate.

```
POST /v1/step
  body: { "step": 5 }
  effect: proxy advances internal "current step" counter; events written by proxy
          from this point onward are tagged with this step
  response: 200 OK

POST /v1/mode
  body: { "mode": "replay", "from_step": 0 }
  effect: switch proxy mode; only the SDK can call this
  response: 200 OK

POST /v1/fork
  body: { "at_step": 17, "fork_id": "fork-xyz" }
  effect: at step 17, proxy switches from replay to record
  response: 200 OK

GET /v1/stats
  response: { "cache_hits": ..., "cache_misses": ..., "egress_bytes": ... }
```

The control API is unauthenticated — it's localhost-only inside one pod. Don't expose it across pod boundaries.

---

## 6. CLI command structure

Owned by Track B (CLI scaffolding), but commands are added by both tracks. Commands map to subcommand files in `cmd/anvil/`.

```
anvil submit <task.yaml>            # Track B
anvil list                           # Track B
anvil status <task-id>               # Track B
anvil logs <task-id>                 # Track B
anvil delete <task-id>               # Track B

anvil replay <task-id>               # Track A
anvil fork <task-id> --at-step N --override key=value  # Track A
anvil resume <task-id>               # Track B
anvil snapshot <task-id>             # Track A (manual checkpoint trigger)

anvil eval --benchmark swe-bench-lite [--baseline <run-id>]  # Track B
anvil dataset publish --tag <name>   # Track A

anvil cluster up                     # Track B (kind cluster bootstrap)
anvil cluster down                   # Track B
```

To avoid merge conflicts, **each track creates its own subcommand files**. Don't edit each other's files unless coordinating on a PR.

Use cobra. Root command in `cmd/anvil/main.go` (Track B owns root). Each subcommand in `cmd/anvil/<command>.go`.

---

## 7. Sync points and acceptance gates

Both engineers attend each sync. If a sync gate is not met, do not proceed to the next phase — fix the gap first. Treat these as commit milestones for both repos.

### Week 1 — Foundation sync
**Both tracks sign off on:**
- SPEC.md
- INTERFACES.md (this document)
- Repo skeleton, CI green
- Open issues for Phase 1, milestoned

### Week 2 — CRD freeze
**Track B presents:** AgentTask CRD as Go types, kubebuilder-generated.
**Track A presents:** SDK skeleton that can read a `task.yaml` and dump it as a struct.
**Acceptance:** SDK's parsed config matches operator's projected config exactly (round-trip test).

### Week 4 — Event schema freeze
**Both:** events.jsonl schema, proxy-events.jsonl schema, trace bundle format.
**Acceptance:** golden test — sample trace can be loaded by both Go (`pkg/trace`) and Python (`agent_anvil.trace`) producing equivalent in-memory representations.

### Week 5 — First end-to-end integration
**Acceptance:** `anvil submit hello-world.yaml` runs an SDK that calls Claude with a trivial prompt, produces a trace, AgentTask transitions to Completed. No replay, no proxy caching yet.

### Week 8 — Phase 1 demo
**Acceptance:** `make demo` works on a fresh laptop. SWE-bench-style task: agent fixes a one-liner bug in a Python file, tests pass, full trace captured. gVisor + NetworkPolicy verified.

### Week 12 — Replay milestone
**Acceptance:** for a previously-run task, `anvil replay <task-id>` produces an event stream that matches the original (modulo timestamps). `anvil fork <task-id> --at-step 3 --override prompt="..."` produces a divergent trace.

### Week 16 — Long-running tasks
**Acceptance:** a 10-minute task can be checkpointed, the pod killed, and `anvil resume` continues from the checkpoint. Replay from arbitrary step works.

### Week 20 — Eval results
**Acceptance:** SWE-bench Lite full run completed, leaderboard JSON produced, regression detection works, total cost ≤ $200.

### Week 24 — Ship
**Acceptance:** HF dataset published with ≥50 labeled failures, blog post live, GKE demo accessible by URL, README updated with results.

---

## 8. Changelog

Every interface change goes here with date and reason.

```
2026-XX-XX  Initial version. AgentTask CRD, event schema, trace bundle, pod env, sidecar API,
            CLI structure, sync points.
```

(Add entries as you go. Keep them terse: date, what changed, why, who signed off.)
