# Agent-Anvil — Track A (Amit)

> Your track owns the **differentiating components**: the agent loop SDK, the recording proxy, the replay engine, fork semantics, workspace snapshots, SWE-bench task adaptation, and the failure-analysis writeup. This is the work that makes Agent-Anvil a portfolio piece rather than another e2b clone.
>
> Track B (your partner) owns the **platform infrastructure**: operator, CRD, pod template, gVisor setup, trace storage backend, observability, eviction handling, eval harness orchestration, GKE deploy, demo polish.
>
> Read **SPEC.md** for the project spec and **INTERFACES.md** for the contracts between tracks. This document tells you what to build *on your side*; INTERFACES.md tells you what crosses the boundary.

## How to use this document

Each phase has: **Goal**, **Build**, **Tools/libraries**, **Why**, **How**, **Acceptance**, **Risks**.

Your time budget: ~10–15 hours/week. Phases overlap with B's; sync points are in INTERFACES.md §7. **Hit the syncs.**

If you can't finish a phase on time, see "What to drop if behind schedule" at the end of this document. Drop in the listed order, no exceptions.

---

## Phase 0 (Week 1) — Co-foundation

You and your partner do this together. Don't divide it.

### Build

- Public GitHub repo, Apache 2.0 license
- README, CONTRIBUTING, CODE_OF_CONDUCT
- Go module + Python `uv` setup
- Repo skeleton matching SPEC.md §"High-level architecture"
- CI: GitHub Actions (build, test, lint)
- `make` targets: `demo`, `build`, `test`, `lint`
- First ADR: `docs/adrs/001-gvisor-over-firecracker.md`
- SPEC.md, INTERFACES.md, PLAN-A.md, PLAN-B.md committed
- Issues opened for Phase 1, milestoned

### Why

Public commit history starting in Week 1 is itself a hiring signal. The "Amit was committing to this for 6 months" timeline matters.

### Acceptance

Per INTERFACES.md §7 "Week 1 — Foundation sync."

---

## Phase 1A (Weeks 2–8) — Agent loop SDK

### Goal

A Python SDK that runs an agent loop, calls LLM APIs, executes MCP-compatible tools, and emits a structured event stream. **Runs locally without K8s.** Integrates with B's operator at Week 5.

### Build

```
sdk/python/
├── pyproject.toml
├── src/agent_anvil/
│   ├── __init__.py
│   ├── loop.py                    # main agent loop
│   ├── config.py                  # parses /etc/agent-anvil/task.yaml
│   ├── events.py                  # event schema + writer (per INTERFACES.md §2)
│   ├── client/
│   │   ├── __init__.py
│   │   ├── base.py                # provider-agnostic interface
│   │   ├── anthropic.py           # Anthropic provider
│   │   └── openai.py              # OpenAI provider (lower priority)
│   ├── mcp/
│   │   ├── __init__.py
│   │   └── server.py              # MCP server hosting stock tools
│   ├── tools/
│   │   ├── bash.py
│   │   ├── file_read.py
│   │   ├── file_write.py
│   │   ├── file_edit.py
│   │   └── web_search.py          # mock for now
│   ├── trace.py                   # trace bundle reader (Python parallel of Go pkg/trace)
│   └── deterministic.py           # injectable clock + RNG for replay
└── tests/
    ├── test_loop.py
    ├── test_tools.py
    ├── test_events.py
    └── test_trace_roundtrip.py    # cross-language with Go pkg/trace
```

### Tools/libraries

- `anthropic` (official Python SDK)
- `openai` (lower priority)
- `mcp` (Anthropic's MCP Python library)
- `pydantic` for config and event types
- `pytest`, `pytest-asyncio`
- `ruff`, `mypy --strict`
- `httpx` (with explicit proxy config; the SDK respects `HTTPS_PROXY` env)

### Why

The SDK is the runtime that does the actual agent work. Everything else (operator, proxy, eval) is plumbing around it. **Build it standalone first** — running locally as `python -m agent_anvil.loop --task task.yaml` — then integrate with K8s. Don't couple SDK development to operator development.

### How

**Week 2 (parallel with B's CRD work):**

1. Define event schema in `events.py` per INTERFACES.md §2. Use Pydantic models for type safety. Write a JSONL writer that flushes after every event.
2. Define config schema in `config.py` matching INTERFACES.md §1 AgentTaskSpec. **Sync with B at end of week** — your parsed config and their projected config must round-trip.
3. Skeleton `loop.py` that reads config, prints "hello world", emits `agent_start` and `agent_done` events. No LLM yet.

**Week 3:**

4. Implement `client/anthropic.py`. Single method: `complete(messages, tools, params) -> Response`. Handles streaming SSE, tool-use API. Emits `llm_call_start` / `llm_call_end` events with token counts and cost.
5. Implement `tools/bash.py` first (it's the simplest). Run command in workspace, capture stdout/stderr, enforce timeout. Emit `tool_call_start` / `tool_call_end` and `file_mutation` events.
6. Wire bash + Anthropic into `loop.py`. Run trivial task locally: "echo hello to a file". Verify trace.

**Week 4:**

7. Implement remaining tools (`file_read`, `file_write`, `file_edit`). `file_edit` is the trickiest — diff-based or line-range based; pick line-range for v1, document.
8. **Event schema freeze sync** with B (INTERFACES.md §7 Week 4). Run round-trip golden test: sample events.jsonl loadable by both Python and Go.
9. Implement `deterministic.py`: a `Clock` class and `RNG` class that read from trace on replay. Inject via context.

**Week 5:**

10. **Integration with B's operator** (INTERFACES.md §7 Week 5). End-to-end: `anvil submit hello-world.yaml` runs SDK in pod, returns trace.
11. Bug fixing.

**Weeks 6–7:**

12. MCP server wrapping. Tools become MCP tools, served via stdio to the SDK. Use the official `mcp` Python library.
13. Tighten error handling: timeouts, OOM in tools, malformed LLM responses.
14. Test coverage push to ≥70%.

**Week 8:**

15. **Phase 1 demo sync** (INTERFACES.md §7 Week 8). Real bug-fix task running end-to-end.

### Acceptance

- [ ] `python -m agent_anvil.loop --task examples/trivial.yaml` runs to completion locally
- [ ] Events emitted match INTERFACES.md §2 schema; pydantic validates them
- [ ] Cross-language trace round-trip test green
- [ ] All four file tools work; bash respects timeout
- [ ] Anthropic client handles streaming + tool use correctly
- [ ] `Clock.now()` and `RNG.random()` are intercepted; replay produces same values
- [ ] Test coverage ≥ 70% on `agent_anvil` package
- [ ] Integration test with B's operator green at Weeks 5 and 8

### Risks

- **Tool-use API differences between providers.** Anthropic's tool-use API is different from OpenAI's. Don't write a leaky abstraction — pick Anthropic for v1, document the gap. OpenAI is post-v1.
- **MCP library churn.** MCP is young; the Python library may have breaking changes. Pin a version, document it, upgrade deliberately.
- **`file_edit` semantics.** Most coding agents fail because of bad edit tools (off-by-one errors, no-op edits). Get this right with extensive tests. Steal from Aider's edit-format research if helpful.
- **Async vs sync.** Anthropic's SDK has both. Pick one (sync is simpler for an agent loop) and stick with it. Don't mix.

---

## Phase 2A (Weeks 9–12) — Recording proxy, replay engine, fork

### Goal

Every agent execution is captured deterministically. `anvil replay <task-id>` reproduces the original. `anvil fork <task-id> --at-step N` diverges at N.

### Build

```
cmd/proxy/
└── main.go

pkg/proxy/
├── server.go                      # HTTP/HTTPS server, mode handling
├── intercept.go                   # TLS interception, CA management
├── cache.go                       # cache backend (sqlite local, S3 prod)
├── keys.go                        # request canonicalization + hashing  ⚠️ HARDEST CODE
├── llm.go                         # LLM-aware caching
├── streaming.go                   # SSE handling
├── control.go                     # /v1/step, /v1/mode, /v1/fork sidecar API
└── events.go                      # proxy-events.jsonl writer

cmd/anvil/
├── replay.go                      # anvil replay
├── fork.go                        # anvil fork
└── snapshot.go                    # anvil snapshot (manual)

pkg/replay/
├── engine.go                      # orchestrates replay
├── verify.go                      # post-replay event diff
└── fork.go                        # fork semantics
```

### Tools/libraries

- Go stdlib `net/http`, `crypto/tls`, `crypto/x509`
- `golang.org/x/net/http2` for SSE
- `gjson` / `sjson` for JSON canonicalization
- `github.com/google/go-cmp` for diff
- `mattn/go-sqlite3` for local cache
- `aws-sdk-go-v2/service/s3` for prod
- mitmproxy as a reference *to read*, not a dependency

### Why

This is **the** differentiator. Without it, the project is "another e2b clone." With it, you have a research-relevant capability that production teams genuinely lack.

### How

**Week 9: Proxy skeleton + cache key normalization.**

1. Standalone proxy server: `cmd/proxy/main.go`. Accepts `--mode={record,replay}`, `--cache-dir=...`, `--task-id=...`. Listens on `:8080` (data) and `:8081` (control).
2. TLS interception via on-the-fly cert generation. Generate per-task CA cert at proxy startup; SDK trusts it via `SSL_CERT_FILE`.
3. **Cache key normalization** (`keys.go`). The most error-prone code in the project. Approach:
   - Build a fixture corpus by capturing real Anthropic + OpenAI requests from Phase 1
   - Write golden tests: pairs of semantically-equivalent requests should hash identically; semantically-different should not
   - Normalization rules: strip `authorization`, strip `x-request-id` and similar, canonicalize JSON (sorted keys, no whitespace), strip timestamps from request bodies (configurable JSON paths), add ordering index for repeated identical requests
   - **Test relentlessly.** This is where bugs hide.

**Week 10: LLM caching and streaming.**

4. `llm.go` — detect requests to known LLM endpoints (`api.anthropic.com`, `api.openai.com`). Parse request body to extract `(model, messages, params)`. Hash by canonical form.
5. `streaming.go` — SSE handling. Record full reconstructed response on the way through; on replay, replay events with original timing (or compressed; configurable).
6. Sidecar control API (`control.go`) per INTERFACES.md §5.

**Week 11: Replay engine.**

7. `pkg/replay/engine.go`. Given a task ID:
   - Load trace from S3
   - Spawn a new pod identical to original (B's operator support needed; coordinate)
   - Inject proxy with `--mode=replay --cache-dir=<from-trace>`
   - Restore workspace if snapshots present (Phase 3); else start empty
   - Run the agent
   - Diff replayed events against original; surface divergences
8. `cmd/anvil/replay.go` — CLI wrapper.

**Week 12: Fork.**

9. Fork semantics: replay up to step N from cache. At step N, sidecar API switches proxy to `record` mode for the divergent branch. Apply the override (modified prompt, model, or tool result).
10. `cmd/anvil/fork.go` — CLI wrapper. Override syntax: `--override prompt="..." --override model="claude-haiku-4-5" --override step17.tool_result.bash="fake output"`.
11. **Replay milestone sync** (INTERFACES.md §7 Week 12).

### Acceptance

- [ ] `anvil replay <task-id>` event stream identical to original (modulo timestamps)
- [ ] Replay works for tasks involving Anthropic API + arbitrary HTTPS GETs
- [ ] `anvil fork <task-id> --at-step 3 --override prompt="..."` produces divergent trace
- [ ] Cache hit rate on replay = 100% for cached non-determinism
- [ ] Streaming LLM (SSE) replays correctly
- [ ] Cache-key normalization tests cover ≥20 corner cases
- [ ] Documented threat model: what determinism we provide, what we don't

### Risks

- **Cache-key normalization is bottomless.** Hard scope: support Anthropic + OpenAI + generic HTTPS GET. Document others as future work.
- **TLS interception edge cases.** HTTP/2, certificate pinning, SNI weirdness. Use mitmproxy as a reference for how they handle these.
- **Time-dependent agent behavior.** Already handled via `Clock` injection in Phase 1A. Verify it works in the proxy context too.
- **Subprocess time/randomness.** If a tool spawns a subprocess that reads system time, replay diverges. Document; non-deterministic subprocesses are out of scope for v1.

---

## Phase 3A (Weeks 13–15) — Workspace snapshots and replay-from-step

### Goal

Workspace state is snapshotted at quiescent points. Replay can start from any snapshot, not just step 0. Fork is now cheap (no need to re-execute steps 0..N-1).

### Build

```
sdk/python/src/agent_anvil/
└── snapshot.py                    # snapshot/restore from inside agent pod

pkg/replay/
└── from_step.go                   # restore + replay from arbitrary step
```

### Tools/libraries

- `tarfile` (Python stdlib) for snapshot creation
- OverlayFS (kernel feature; B sets up the mount in Phase 3B)
- `aws-sdk-go-v2/service/s3` for snapshot upload

### Why

Two reasons:

1. **Eval harness needs it.** SWE-bench Lite tasks can take 10+ minutes each at 300 tasks. Without checkpointing, a node failure kills your eval run.
2. **Fork requires it.** Without snapshot-based replay, fork at step N requires re-executing 0..N-1 with real tokens. Slow and expensive.

### How

**Week 13:**

1. Coordinate with B on OverlayFS pod setup (B owns the init container; you consume the mount).
2. Implement `snapshot.py`: tar the OverlayFS upper layer, upload to S3, emit `checkpoint_start` / `checkpoint_end` events with snapshot ID.
3. Trigger snapshot from agent loop based on `checkpointPolicy` (manual | every-step | interval).

**Week 14:**

4. Implement restore: download snapshot, extract into upper layer (B's init container needs to support this).
5. Update replay engine: `--from-step N` restores the snapshot at step N before starting.
6. Update fork: `--at-step N` uses snapshot-restore instead of re-executing.

**Week 15:**

7. Testing. Long-running task with checkpoints, killed pod, resume. Verify byte-equivalence of restored workspace.
8. **Long-running tasks sync** (INTERFACES.md §7 Week 16; you have a week buffer).

### Acceptance

- [ ] Long task (>10 min) checkpointed and resumed successfully
- [ ] `anvil replay --from-step 17` restores workspace and replays from step 17
- [ ] Snapshot/restore byte-correctness verified (file hashes match)
- [ ] Snapshot storage cost <100MB per checkpoint for typical SWE-bench task

### Risks

- **OverlayFS in unprivileged containers.** Some K8s distros disallow mount syscalls. Coordinate with B; document constraints.
- **Snapshot frequency vs. I/O cost.** Snapshotting every step on I/O-heavy tasks is expensive. Profile early.

---

## Phase 4A (Weeks 17–19) — SWE-bench task adaptation + SDK telemetry

### Goal

The SDK can run SWE-bench tasks. Cost/latency/token data flows into traces. Optional: self-hosted small-model router demonstrates cost optimization.

### Build

```
eval/swebench/
├── adapter.py                     # SWE-bench task → AgentTask spec
├── verifier.py                    # post-task test runner
└── prompts/                        # task-specific prompt templates

sdk/python/src/agent_anvil/
└── telemetry.py                   # cost calculation, token tracking

deploy/vllm/                       # optional Phase 4 stretch
└── deployment.yaml                # vLLM serving Qwen2.5-Coder-7B
```

(B owns the harness orchestration that runs all 300 tasks; you own the task → AgentTask conversion and the SDK-side instrumentation.)

### Tools/libraries

- SWE-bench dataset (HuggingFace)
- `datasets` Python library
- vLLM (optional)

### Why

The SDK needs to know what makes a SWE-bench task different from a generic agent task: how the workspace is constructed (clone repo at base commit), what the success criterion is (test command), how the task description maps to a prompt.

### How

**Week 17:**

1. SWE-bench task adapter: load task from HF dataset, construct AgentTask spec with appropriate base image (their docker image with the repo cloned), prompt template, tool config.
2. Verifier: runs the success-test inside the pod after the agent finishes, returns pass/fail.

**Week 18:**

3. Cost calculation in `telemetry.py`. Maintain a price table per `(provider, model, input/output)`. Update `llm_call_end.cost_usd` correctly. Sync with B who's aggregating.
4. Run 10 SWE-bench tasks end-to-end, debug the long tail of weirdness.

**Week 19:**

5. (Optional, only if on schedule) Self-hosted vLLM. Deploy Qwen2.5-Coder-7B. Wire a "router" mode in the SDK: classify subtask, route to local or frontier. Compare cost and accuracy.

### Acceptance

- [ ] 10 random SWE-bench Lite tasks run successfully through the adapter
- [ ] Cost data accurate within 5% of provider-reported cost (verify against billing dashboard)
- [ ] Verifier correctly distinguishes pass/fail
- [ ] Optional: router demonstrates ≥20% cost reduction with ≤5% pass-rate loss

### Risks

- **SWE-bench environments are messy.** Each task has its own dependencies, weird Python versions, flaky tests. Be patient.
- **Cost calculation drift.** Provider prices change. Make the price table easy to update.

---

## Phase 5A (Weeks 21–24) — Failure analysis and writeup

### Goal

The artifacts that turn this from a project into a portfolio piece.

### Build

- `docs/failure-taxonomy.md` — your taxonomy with definitions
- `eval/analysis/` — Jupyter notebooks for trace analysis
- HuggingFace dataset published under your account
- Blog post (~3000 words)
- Demo video (≤5 min)
- Conference abstract (KubeCon CFP, MLSys workshop, or similar)

### Tools/libraries

- `datasets` (HuggingFace)
- Jupyter
- A blog platform (your choice)
- `asciinema` or `terminalizer` for terminal demos

### Why

This phase is what differentiates "portfolio project" from "GitHub repo." Most engineers stop at "the code works." The few who write up insights get DMs from recruiters. **This is the highest-leverage work you do in 6 months.**

### How

**Week 21: Failure analysis.**

1. Load all failure traces from the SWE-bench run (B has the leaderboard JSON).
2. For each, inspect: what was the prompt, what did the agent do, where did it go wrong.
3. Use `anvil replay` and `anvil fork` to test hypotheses ("would this have passed with a longer context?").
4. Assign taxonomy labels. **Start from existing literature** — cite SWE-bench analyses, METR's autonomy evals, Anthropic's agent eval writeups. Refine based on what you observe. The narrative is "I extended the standard taxonomy with N new categories I observed."

Concrete starting taxonomy:
- Specification — agent misunderstood the task
- Localization — agent edited the wrong file/function
- Reasoning — agent's plan was wrong
- Tool-use — wrong tool, wrong args, hallucinated tool
- Context-management — relevant info fell out of context window
- Verification — agent thought it was done but tests failed
- Recovery — agent failed once and couldn't recover

**Write the blog post outline now**, before all analysis is done. It keeps you focused on what the headline finding will be.

**Week 22: Dataset packaging + writeup draft.**

5. HF dataset: one row per failed task. Columns: task_id, original_prompt, trace_url, taxonomy_label, agent_model, failure_step, replay_manifest_url. Include load+replay example notebook.
6. Blog post draft. Sections: problem → architecture → replay design (technical depth) → eval results (numbers) → taxonomy (headline) → reflections.

**Week 23: Demo polish, writeup revision.**

7. Demo video: submit → replay → fork → eval, ≤5 minutes, cleanly produced.
8. Revise blog post. Get a critical reader (not your partner; they're too close).

**Week 24: Publish, submit, share.**

9. Publish blog post. Cross-post: HN (carefully titled), LinkedIn, X.
10. Publish HF dataset.
11. Submit conference abstract.

### Acceptance

- [ ] HF dataset published with ≥50 labeled failure traces
- [ ] Blog post ≥3000 words with diagrams and code examples
- [ ] Demo video published
- [ ] Conference abstract submitted (regardless of acceptance)

### Risks

- **Underweighting the writeup.** This is the most common failure mode. Mitigation: outline week 21, draft week 22. Schedule it.
- **Dataset isn't useful.** If labels are noisy, dataset has no research value. Mitigation: focus on a coherent failure mode (e.g., "context-management failures in long-horizon tasks") and go deep rather than broad.
- **Promoting it wrong.** A good post on HN with a bad title dies. Spend an hour on the title. "How I built X" is bad; "What 300 SWE-bench failures taught me about coding agents" is better.

---

## What to drop if behind schedule (in this order)

1. Self-hosted vLLM router (Phase 4A, optional)
2. Fork semantics (keep replay; drop fork) — but only as a last resort, since fork is part of the differentiator
3. OpenAI provider in SDK (Anthropic-only is fine)
4. Conference abstract submission (the dataset and blog post are enough)

**Do not drop:**
- Recording proxy and replay (the differentiator)
- Workspace snapshots (eval needs them)
- SWE-bench task adapter
- Failure analysis writeup and HF dataset

If you can't finish all the must-keeps, raise it in a sync, redistribute with B, or extend timeline. Don't ship without them.

## What to do if ahead of schedule

In order of marginal portfolio value:

1. arXiv preprint of the failure taxonomy (turn the blog post into a paper)
2. Multi-agent: spawn-subagent tool with shared trace
3. A second benchmark (LiveCodeBench, MLE-bench)
4. Computer-use sandbox (E2B Desktop-style)

## Resume bullets to write *toward*

- *Designed and built the recording proxy and replay engine for Agent-Anvil, a Kubernetes-native agent execution platform. TLS-intercepting Go proxy with semantic cache-key normalization enables deterministic re-execution of agent traces across model and prompt changes; supports forking to compare counterfactual executions.*
- *Authored a public failure-mode taxonomy of N coding-agent failures observed across 300 SWE-bench Lite tasks; published as a HuggingFace dataset of replayable traces.*
- *Implemented OverlayFS-based copy-on-write workspace snapshotting for sandbox pods, supporting checkpoint/resume across pod evictions and step-level forking of agent executions.*

If a sub-task isn't contributing to one of these bullets, justify why before doing it.
