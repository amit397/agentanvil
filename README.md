# Agent-Anvil

> Self-hostable, Kubernetes-native platform for running coding agents safely at scale, with **deterministic replay** and a built-in eval harness.

## Status

Pre-alpha. Targeting 6 months to v1.0 with public dataset release and SWE-bench Lite results.

## Problem

Current agent execution platforms (e2b, Modal, Daytona) provide secure sandboxing but lack the observability and reproducibility needed to systematically debug agent behavior. When a coding agent fails on a task at step 47, today's tools tell you *that* it failed — they don't let you replay the execution to understand why, or fork the trace to test "what if the prompt had been different at step 17."

This matters because:

- **Production teams** running agents at scale can't debug failures effectively. Logs aren't enough; you need to re-execute.
- **Research teams** running agent evals can't reproduce results across model versions. LLM non-determinism, network flakiness, and time-dependent state break reproducibility silently.
- **Frontier labs** training agents (RLHF/RLAIF for tool use) need deterministic rollouts for offline analysis. Bespoke internal tooling exists but isn't open.

Agent-Anvil fills this gap by treating agent executions as replayable artifacts, not ephemeral logs.

## Goals

1. Run coding agents in secure, isolated sandboxes (gVisor) on Kubernetes.
2. Capture every non-determinism (LLM responses, tool outputs, network calls, time, randomness) such that any execution can be replayed deterministically.
3. Support **forking**: replay up to step N, modify a parameter (prompt, model, tool), run forward and compare outcomes.
4. Provide an eval harness that runs SWE-bench Lite with cost/latency/regression tracking.
5. Generate a public dataset of replayable agent failures with taxonomy labels.
6. Be runnable end-to-end on `kind` (laptop) in under 5 minutes via `make demo`.

## Non-goals

- **Personal-assistant agent framework.** This is not OpenClaw. There is no messaging integration, no skills marketplace.
- **Multi-modal agents** (vision, voice). Text-only for v1.
- **Production-grade multi-tenancy** with billing, quotas, complex RBAC. Single-tenant or trusted-tenant only.
- **Computer-use agents** that drive a GUI. Code-execution agents only.
- **Custom LLM training infrastructure.** Eval and debugging only. The architecture supports rollouts as a foundation for future training work, but training is out of scope.
- **A second, custom agent loop framework.** Use existing frameworks (the SDK is thin glue).
- **Process-level checkpoint/restore (CRIU).** Only quiescent checkpoints are supported. Long-running subprocesses inside the sandbox are not snapshotted.

## High-level architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                      User / CI / Eval harness                    │
│                              │                                   │
│                       anvil CLI / API                            │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                  Control plane (K8s)                     │    │
│  │  ┌────────────┐    ┌──────────────┐    ┌─────────────┐  │    │
│  │  │ AgentTask  │───▶│  Operator    │───▶│   Pod       │  │    │
│  │  │   CRD      │    │  (Go)        │    │  scheduler  │  │    │
│  │  └────────────┘    └──────────────┘    └─────────────┘  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                              │                                   │
│                              ▼                                   │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │              Sandbox pod (gVisor RuntimeClass)           │    │
│  │  ┌─────────────────────┐    ┌────────────────────────┐  │    │
│  │  │  Agent loop (Py)    │───▶│  Recording proxy (Go)  │  │    │
│  │  │  - MCP tools        │    │  - TLS intercept       │  │    │
│  │  │  - Event stream     │    │  - Cache by req hash   │  │    │
│  │  │  - Workspace (CoW)  │    │  - LLM-aware caching   │  │    │
│  │  └─────────────────────┘    └────────────────────────┘  │    │
│  │           │                              │              │    │
│  │           ▼                              ▼              │    │
│  │  Workspace PVC (OverlayFS)       Trace store (S3)       │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │         Replay engine + Eval harness (offline)          │    │
│  │  - anvil replay <task-id>                               │    │
│  │  - anvil fork   <task-id> --at-step N --override ...    │    │
│  │  - anvil eval   --benchmark swe-bench-lite              │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

## Components

### 1. Control plane: K8s operator (Go)

Implements the `AgentTask` CRD and reconciles it into running sandbox pods. Built with [kubebuilder](https://book.kubebuilder.io/). Lifecycle: `Pending → Provisioning → Running → Checkpointing → (Completed | Failed | Evicted)`.

Deliberately minimal: ~500–800 LoC. No webhooks, no leader election, no multi-version CRD in v1. The operator's job is *only* to translate `AgentTask` resources into pods with the right RuntimeClass, NetworkPolicy, volumes, and proxy sidecar.

### 2. Sandbox pod

Each `AgentTask` becomes one pod with:

- **gVisor RuntimeClass** for kernel isolation
- **NetworkPolicy** blocking all egress except to the proxy sidecar
- **Workspace volume** (OverlayFS) — base image is read-only, writes go to an upper layer that can be snapshotted
- **Resource limits** (CPU, memory, ephemeral storage)
- **Timeout** enforced by the operator
- **Two containers**: `agent` (Python loop) + `proxy` (Go recording proxy)

### 3. Recording proxy (Go)

The keystone component for determinism. Sits between the agent and the outside world. All HTTP/HTTPS egress from the agent container is forced through the proxy via NetworkPolicy + iptables.

- **TLS interception** via a per-task CA cert installed in the agent container's trust store
- **Two modes**: `record` (forward + cache) and `replay` (serve from cache, refuse real network)
- **Cache key**: hash of `(method, normalized URL, canonicalized body, ordering index)` — see ADR-008
- **LLM-aware caching**: requests to known LLM API endpoints are cached by `(model, messages, params)` for cost attribution and determinism
- **Write semantics**: cached writes (POST/PUT to GitHub etc.) are replayed as the recorded response, but a fork operation surfaces them for explicit user approval

### 4. Agent loop SDK (Python)

Thin wrapper around an MCP-compatible tool-use loop. Not a new framework — designed to be replaced with a different framework if the user wants.

- Tools exposed via [MCP](https://modelcontextprotocol.io/) (Anthropic's emerging standard)
- Stock tools: `bash`, `file_read`, `file_write`, `file_edit`, `web_search` (mocked initially)
- Every LLM call, tool call, and filesystem mutation emitted to a structured event stream
- Event stream is the source of truth for replay

### 5. Replay engine

Reconstructs a past execution by:

1. Restoring the workspace OverlayFS upper layer to the snapshot at the desired step
2. Pointing the proxy at the cached responses for that trace
3. Re-executing the agent loop, which now hits cached LLM responses and tool outputs

**Fork semantics**: replay up to step N. At step N, the user provides an override (different prompt, different model, different tool result). From step N onwards, the proxy operates in `record` mode for the divergent branch — real LLM calls happen, real network egress is allowed (where caching can't help), and a new trace is recorded.

### 6. Eval harness

- SWE-bench Lite runner (300 tasks)
- Submits each task as an `AgentTask`, collects results
- Cost/latency/token telemetry per task, aggregated
- Regression detection: diff two runs to find newly failing or newly passing tasks
- Outputs leaderboard JSON + replay manifests for every failure

### 7. CLI: `anvil`

```
anvil submit task.yaml                      # submit an AgentTask
anvil list                                   # list running and recent tasks
anvil logs <task-id>                         # stream events
anvil replay <task-id>                       # deterministic re-execution
anvil fork <task-id> --at-step N --prompt "..." --model "..."
anvil eval --benchmark swe-bench-lite [--baseline <run-id>]
anvil dataset publish --tag <name>           # build HF dataset from traces
```

## Tech stack

| Layer | Choice | Rationale |
|---|---|---|
| Operator language | Go | Idiomatic for K8s operators; signals systems competence |
| Agent SDK language | Python | LLM ecosystem is Python-first; matches eval tooling |
| Operator framework | kubebuilder | Scaffolds 80% of operator boilerplate; canonical |
| Sandbox runtime | gVisor | Strong isolation, runs on managed K8s (GKE), simpler than Firecracker for this scope |
| Workspace CoW | OverlayFS | Already in K8s/Linux stack, no exotic node setup |
| Recording proxy | Custom Go (built on `net/http` + `crypto/tls`) | Need fine control over request hashing and cache semantics; mitmproxy considered but Go matches operator stack |
| Tool protocol | MCP | Industry-standard; compatibility with Claude/Anthropic stack signals ecosystem awareness |
| Trace storage | S3-compatible (MinIO local, real S3 prod) | Object store is right shape for traces; works locally and in cloud |
| Metadata DB | SQLite (local) → Postgres (prod) | Keep local dev cheap; production path defined |
| Local cluster | kind | Standard, works on macOS/Linux, supports custom RuntimeClass with gVisor |
| Prod cluster | GKE | gVisor first-class support, low cost for demo scale |
| Eval benchmark | SWE-bench Lite | 300 tasks, manageable cost, industry-recognized |
| Self-hosted model | vLLM serving Qwen2.5-Coder-7B (optional) | Cost-routing experiments only; not load-bearing |
| Observability | OpenTelemetry → Tempo + Prometheus | Standard, easy to demo |

## Architectural decisions (ADRs)

### ADR-001: gVisor over Firecracker for sandboxing

**Decision:** Use gVisor as the sandbox runtime.

**Alternatives considered:** Firecracker (e2b's choice), Kata Containers, plain Docker.

**Rationale:** gVisor runs natively as a K8s RuntimeClass on GKE without per-node configuration. Firecracker would require microVM management infrastructure (firecracker-containerd) that adds 2–3 weeks of yak-shaving. The security trade-off is real (gVisor's syscall interception is weaker than full virtualization), but acceptable for a demo platform running trusted-source agents.

**Consequences:** Some Python packages with unusual syscall patterns may break under gVisor. Document known incompatibilities. Production deployments wanting stronger isolation can swap RuntimeClass.

### ADR-002: OverlayFS over ZFS for workspace CoW

**Decision:** Use OverlayFS for workspace copy-on-write.

**Alternatives considered:** ZFS snapshots, btrfs subvolumes, full filesystem clones.

**Rationale:** OverlayFS is in the K8s stack already. ZFS requires per-node configuration that breaks managed-K8s portability. btrfs is operationally annoying. OverlayFS is "good enough" for snapshot/restore at quiescent points.

**Consequences:** Process state is not snapshotted (only filesystem state). Long-running subprocesses inside the sandbox cannot be checkpointed. Document this constraint; CRIU is explicitly out of scope.

### ADR-003: Recording proxy is mandatory, not optional

**Decision:** All agent egress is forced through a recording proxy from day one.

**Rationale:** Without it, the "deterministic replay" claim is false. An agent that calls the GitHub API at step 10 will get different responses on replay (rate limits, API changes, commit hashes). Replay would diverge silently.

**Consequences:** ~3 weeks of dedicated proxy work in Phase 2. TLS interception requires CA cert management. Streaming responses (SSE for LLM APIs) require special handling.

### ADR-004: MCP for tool protocol

**Decision:** Tools are exposed via the Model Context Protocol.

**Rationale:** MCP is becoming the de-facto standard for agent tool exposure. Building on it makes Agent-Anvil a node in an emerging ecosystem rather than a silo. Stock tools become interchangeable with any MCP-compliant tool server.

**Consequences:** Locked into MCP's protocol semantics. If MCP evolves incompatibly, migration cost.

### ADR-005: Minimal operator with kubebuilder

**Decision:** ~500–800 LoC operator. No webhooks, no leader election, no multi-version CRD in v1.

**Rationale:** Operator boilerplate is high signal but low engineering content. The interesting work is in the proxy, replay engine, and eval harness. Cap operator scope.

**Consequences:** Single replica only in v1. Concurrent reconciliation can race. Acceptable for demo and small-scale eval; document the constraint.

### ADR-006: SQLite for v1, Postgres path defined for prod

**Decision:** Default metadata store is SQLite. Operator supports a Postgres connection string for prod deployments.

**Rationale:** SQLite makes `make demo` work without an external database. Postgres is the production target but adds friction for local dev.

**Consequences:** Schema migrations need to support both. Use a migration framework (`golang-migrate`).

### ADR-007: Quiescent-only checkpoints

**Decision:** Workspace snapshots are taken only between agent loop iterations, when no subprocesses are running.

**Rationale:** Snapshotting a running subprocess requires CRIU, which is fragile and platform-dependent. Quiescent checkpoints are sufficient for the agent-loop pattern (one tool call at a time).

**Consequences:** Cannot resume mid-tool-call. If the bash tool was running `pip install` and the pod was evicted, the install is lost. Document; resume semantics restart the interrupted tool call.

### ADR-008: Cache-key strategy differs by request type

**Decision:** Three cache-key strategies in the recording proxy.

- **LLM API calls**: hash of `(provider, model, normalized messages, params)`. Excludes auth headers, request IDs, timestamps.
- **General reads** (GET requests): hash of `(method, URL, canonicalized body, selected headers, ordering index)`. Ordering index disambiguates "Nth call to this endpoint."
- **Writes** (POST/PUT/DELETE to non-LLM endpoints): cached but flagged. On replay, returned from cache. On fork past the write, surfaced to user with "actually execute or skip?" prompt.

**Rationale:** Cache keys must capture semantic identity, not byte-level identity. Auth tokens rotate; timestamps differ; but the request is logically the same.

**Consequences:** Cache-key normalization logic is the most error-prone part of the proxy. Invest in tests.

## Output artifacts

Order of importance for hiring signal:

1. **Public GitHub repo** with clean commit history, ADRs, contributor guide. Public from week 1.
2. **Failure-mode taxonomy writeup** (blog post + arXiv preprint optional). "What I learned running 300 SWE-bench tasks through my own agent platform."
3. **HuggingFace dataset** of replayable agent failures with taxonomy labels. The differentiating artifact.
4. **Live demo on GKE** with `curl` example in README.
5. **`make demo`** path runnable on `kind` in under 5 minutes.
6. **Conference submission** (KubeCon, MLSys workshop). Stretch.

## Glossary

- **Trace** — full record of an agent execution: events, LLM calls, tool calls, filesystem mutations, network requests/responses.
- **Replay** — deterministic re-execution of a trace from cached non-determinism.
- **Fork** — replay up to step N, then diverge with modified parameters; record the new branch.
- **Sandbox** — single pod running one `AgentTask`, isolated by gVisor + NetworkPolicy.
- **Recording proxy** — TLS-intercepting HTTP proxy that captures and replays all agent egress.
- **Quiescent checkpoint** — workspace snapshot taken between agent loop iterations.
- **Step** — one iteration of the agent loop (one LLM call + zero or more tool calls).
- **AgentTask** — Kubernetes custom resource representing one agent execution.

## Out-of-scope but worth noting

If v1 succeeds, follow-up work could include: multi-agent orchestration (subagents, planner/executor splits), RL-style rollouts at scale (training data generation), computer-use agents (with E2B Desktop-style virtual desktops), production-grade multi-tenancy with billing. None of these are committed.

## How to test (v1)

- Run on one terminal:
  - ```make manifests```
  - ```make install```
  - ```make run```
- Run on another terminal:
  - ```kubectl apply -f config/samples/agenttasks_v1_agenttask.yaml```
