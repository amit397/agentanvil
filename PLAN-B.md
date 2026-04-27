# Agent-Anvil — Track B (Partner)

> Your track owns the **platform infrastructure**: the Kubernetes operator, AgentTask CRD, pod template, gVisor setup, trace storage backend, observability, eviction handling, eval harness orchestration, GKE deploy, and demo polish. This is the work that makes Agent-Anvil run as a credible platform.
>
> Track A (Amit) owns the **differentiating components**: agent loop SDK, recording proxy, replay engine, fork semantics, workspace snapshots, SWE-bench task adaptation, and the failure-analysis writeup.
>
> Read **SPEC.md** for the project spec and **INTERFACES.md** for the contracts between tracks. This document tells you what to build *on your side*; INTERFACES.md tells you what crosses the boundary.

## How to use this document

Each phase has: **Goal**, **Build**, **Tools/libraries**, **Why**, **How**, **Acceptance**, **Risks**.

Your time budget: ~10–15 hours/week. Phases overlap with A's; sync points are in INTERFACES.md §7. **Hit the syncs.**

If you can't finish a phase on time, see "What to drop if behind schedule" at the end of this document. Drop in the listed order, no exceptions.

---

## Phase 0 (Week 1) — Co-foundation

You and Amit do this together. Don't divide it.

### Build

Same list as PLAN-A.md Phase 0. Both committing equally.

### Acceptance

Per INTERFACES.md §7 "Week 1 — Foundation sync."

---

## Phase 1B (Weeks 2–8) — Operator + sandbox infrastructure

### Goal

A Kubernetes operator that translates `AgentTask` resources into running sandbox pods. gVisor RuntimeClass installed on `kind`. NetworkPolicy locks down egress except to a proxy sidecar (stub for now; A fills it in Phase 2). CLI scaffolding for submit/list/status/logs/delete.

### Build

```
api/v1alpha1/
├── agenttask_types.go             # CRD types per INTERFACES.md §1
├── zz_generated.deepcopy.go       # kubebuilder-generated
└── groupversion_info.go

internal/controller/
├── agenttask_controller.go        # main reconcile loop
├── pod_builder.go                 # constructs the sandbox Pod spec
├── network_policy.go              # NetworkPolicy generator
└── status.go                      # status updates

config/
├── crd/                            # generated CRD manifests
├── rbac/                           # operator service account + role
├── manager/                        # deployment manifest
└── samples/                        # example AgentTask YAMLs

cmd/operator/
└── main.go                         # operator entry point

cmd/anvil/
├── main.go                         # cobra root
├── submit.go
├── list.go
├── status.go
├── logs.go
├── delete.go
├── cluster_up.go
└── cluster_down.go

deploy/kind/
├── kind-config.yaml                # cluster config with gVisor
├── setup.sh                        # bootstrap script
└── runtime-class.yaml              # gVisor RuntimeClass

deploy/helm/agent-anvil/
├── Chart.yaml
├── values.yaml
├── templates/
│   ├── operator-deployment.yaml
│   ├── crd.yaml
│   ├── rbac.yaml
│   └── runtime-class.yaml
└── README.md
```

### Tools/libraries

- Go 1.22+
- `kubebuilder` v4 — scaffold the operator
- `controller-runtime` v0.19+
- `client-go` matching cluster version
- `cobra` for CLI
- `kind` v0.23+ for local cluster
- gVisor (`runsc`) — install per [official guide](https://gvisor.dev/docs/user_guide/install/)
- `helm` for packaging

### Why

The operator is the load-bearing skeleton. Until it can spin up a sandbox pod with the right RuntimeClass, NetworkPolicy, volumes, and sidecar — and reconcile its status correctly — nothing else can be tested. Cap operator complexity: this is plumbing, not the differentiator.

### How

**Week 2 — CRD freeze (sync with A).**

1. `kubebuilder init --domain agentanvil.dev --repo github.com/<user>/agent-anvil`
2. `kubebuilder create api --group agentanvil --version v1alpha1 --kind AgentTask`
3. Fill in `agenttask_types.go` per **INTERFACES.md §1**. This is the contract; sync with A. End-of-week round-trip test: A's SDK config parser produces the same struct as your projected config.

**Week 3 — Operator skeleton.**

4. `agenttask_controller.go`: minimal reconcile loop. Phases: `Pending → Provisioning → Running → Completed/Failed`. On `Pending`, create a "hello world" pod (no real agent). On pod completion, mark `Completed`. ~200 LoC.
5. `pod_builder.go`: build a pod spec from AgentTask. For now, the pod is a busybox container that prints task ID and exits 0. No volumes, no sidecars yet.
6. End-of-week milestone: `kubectl apply -f sample-agenttask.yaml` causes a pod to run; AgentTask transitions through phases. Verify with kind cluster.

**Week 4 — Pod template real.**

7. Expand `pod_builder.go`:
   - Two containers: `agent` (placeholder image, A will provide later) + `proxy` (placeholder; A's Phase 2)
   - Mount `/etc/agent-anvil/task.yaml` as projected ConfigMap (from AgentTask spec)
   - Mount `/var/log/agent-anvil/` as emptyDir for trace output
   - Mount workspace as emptyDir for now (OverlayFS in Phase 3)
   - Set env vars per **INTERFACES.md §4**
8. `network_policy.go`: deny-all egress except localhost (so agent can reach proxy sidecar).
9. **Event schema freeze sync** (INTERFACES.md §7 Week 4) — review A's event schema for any operator-side concerns.

**Week 5 — gVisor + integration.**

10. **gVisor on kind** — the time sink. Budget the full week. Steps:
    - Install `runsc` on the kind node image (custom node image)
    - Register `RuntimeClass` named `gvisor` pointing to runsc
    - Add `runtimeClassName: gvisor` to pod spec in `pod_builder.go`
    - Verify with `runsc --version` inside a pod
    - **Fallback plan:** if gVisor doesn't work in a week, document and switch to standard runtime for local dev. Don't death-march this.
11. **First end-to-end integration with A's SDK.** A provides their SDK as a container image; you wire it into the pod template. Acceptance: `anvil submit hello-world.yaml` runs A's SDK, returns trace. (INTERFACES.md §7 Week 5.)

**Week 6 — CLI scaffolding.**

12. Cobra-based CLI: `cmd/anvil/main.go` is the root. Subcommands per INTERFACES.md §6 (Track B's commands only): `submit`, `list`, `status`, `logs`, `delete`, `cluster up`, `cluster down`. Each in its own file.
13. `submit.go`: parse YAML, validate, `kubectl apply` equivalent via client-go.
14. `list.go`: list AgentTasks across namespaces with phase, age, model.
15. `logs.go`: stream events.jsonl from the pod (kubectl logs equivalent).

**Week 7 — Resilience.**

16. Operator handles pod deletion (e.g., user `kubectl delete pod`): mark task Failed, set reason.
17. Operator handles timeout: at `spec.timeoutSeconds`, kill pod, mark Failed.
18. Operator handles AgentTask deletion: clean up pod, optionally preserve trace (configurable).
19. Test coverage push to ≥70% on `internal/controller`.

**Week 8 — Phase 1 demo.**

20. **Phase 1 demo sync** (INTERFACES.md §7 Week 8). Real bug-fix task running end-to-end via `make demo` on a fresh laptop. Under 5 minutes.

### Acceptance

- [ ] AgentTask CRD installed; samples apply cleanly
- [ ] Operator reconciles AgentTask through full lifecycle
- [ ] Pod template includes both containers, correct mounts, correct env per INTERFACES.md §4
- [ ] gVisor RuntimeClass functional on kind (or documented fallback)
- [ ] NetworkPolicy verified: agent can't egress except to localhost proxy
- [ ] CLI commands work: submit/list/status/logs/delete/cluster up/down
- [ ] Operator under 800 LoC (excluding generated code)
- [ ] Test coverage ≥ 70% on operator
- [ ] `make demo` works on a fresh laptop in ≤5 minutes
- [ ] Helm chart installs cleanly: `helm install agent-anvil ./deploy/helm/agent-anvil`

### Risks

- **gVisor on kind is the biggest time sink.** Budget the full week. Have the fallback ready.
- **Operator scope creep.** No webhooks, no leader election, no multi-version CRD. Keep it under 800 LoC.
- **kubebuilder generation churn.** Don't edit generated files; if codegen drifts, regenerate.
- **Reconcile loop races.** Single replica only. Document.
- **Pod template churn.** A and you both edit `pod_builder.go` indirectly (A through interface changes). Lock the env/mounts contract early via INTERFACES.md §4.

---

## Phase 2B (Weeks 9–12) — Trace storage + observability

### Goal

A solid storage backend for traces (S3-compatible, MinIO local, real S3 prod). Observability of the platform itself: operator metrics, structured logs, distributed tracing.

### Build

```
pkg/trace/
├── trace.go                       # Trace struct, Load/Save
├── bundle.go                      # tar.gz packing/unpacking
├── manifest.go                    # manifest.json handling
├── store/
│   ├── store.go                   # interface
│   ├── s3.go                      # S3 / MinIO impl
│   └── local.go                   # filesystem impl (testing)
└── trace_test.go                  # cross-language test with A's Python impl

internal/controller/
├── telemetry.go                   # OpenTelemetry instrumentation
└── metrics.go                     # Prometheus metrics

deploy/observability/
├── otel-collector.yaml
├── tempo.yaml                     # distributed tracing
├── prometheus.yaml
└── grafana/
    ├── dashboards/
    └── datasources/
```

### Tools/libraries

- `aws-sdk-go-v2/service/s3`
- MinIO (deployed in cluster for local dev)
- OpenTelemetry Go SDK
- `prometheus/client_golang`
- Tempo + Prometheus + Grafana via Helm charts

### Why

Two reasons:

1. **`pkg/trace` is the shared contract for trace I/O.** Both you and A use it. You own the implementation; A consumes it. The Python parallel (in A's SDK) tests against the Go via cross-language round-trip.
2. **Platform observability is what makes the GKE demo credible.** A live Grafana dashboard during a demo says "this is real production-shaped infra," not "this is a hobby project."

### How

**Week 9 — pkg/trace.**

1. Implement `pkg/trace/store/store.go` interface. Three methods: `Put(taskID, data)`, `Get(taskID) -> data`, `List(prefix) -> taskIDs`.
2. S3 implementation. Local MinIO setup in `deploy/kind/setup.sh`.
3. Local filesystem implementation for testing.
4. Bundle format per INTERFACES.md §3. Tar.gz with manifest + events + caches + snapshots.
5. **Cross-language round-trip test** (INTERFACES.md §7 Week 4 was the deadline; sliding into Week 9 if needed). A's Python `agent_anvil.trace` and your `pkg/trace` produce equivalent in-memory structures from the same bundle.

**Week 10 — operator instrumentation.**

6. OpenTelemetry on the operator: spans for reconciliation, pod creation, status updates. Export to OTLP endpoint.
7. Prometheus metrics: tasks created/completed/failed (counter), reconcile latency (histogram), pods scheduled (counter).
8. Wire OpenTelemetry collector into `kind` cluster.

**Week 11 — observability stack.**

9. Tempo deployment for traces.
10. Prometheus deployment for metrics.
11. Grafana with two dashboards: "Operator health" and "Agent fleet overview."
12. `anvil cluster up` deploys the full observability stack (or `anvil cluster up --minimal` skips it).

**Week 12 — replay milestone support.**

13. Coordinate with A on replay: A needs `pkg/trace` to load traces from S3, get cache contents, and write a new fork trace back. Make sure your Go API is what A needs.
14. **Replay milestone sync** (INTERFACES.md §7 Week 12). A's replay/fork demos depend on your storage working correctly.

### Acceptance

- [ ] `pkg/trace` Go API stable and documented
- [ ] Cross-language round-trip test green
- [ ] Trace bundle creation/extraction works for >100MB bundles
- [ ] Operator emits OpenTelemetry traces; visible in Tempo
- [ ] Operator exposes Prometheus metrics
- [ ] Grafana dashboards working with sample data
- [ ] MinIO works locally; switching to real S3 is config-only
- [ ] A's replay demo works end-to-end

### Risks

- **Bundle size growth.** SWE-bench tasks can produce large traces. Stream rather than buffer.
- **MinIO config differences vs real S3.** Path-style vs virtual-host-style addressing. Test against both.
- **Observability deploy bloat.** Don't ship a 2GB observability stack on `make demo`. Make it opt-in for local dev.

---

## Phase 3B (Weeks 13–16) — Eviction handling, OverlayFS, resume

### Goal

Long-running tasks survive pod evictions. `anvil resume` works. OverlayFS workspace mounts are set up by the operator's init container so A's snapshots work.

### Build

```
internal/controller/
├── eviction.go                    # detect and handle pod evictions
└── workspace.go                   # OverlayFS init container generation

cmd/anvil/
└── resume.go

deploy/kind/
└── overlayfs-init.yaml            # init container template
```

### Tools/libraries

- OverlayFS (Linux kernel; nothing to install on most distros)
- `tar` via Go `archive/tar` (don't shell out)
- A privileged init container for the OverlayFS mount

### Why

A's snapshot work in Phase 3A depends on the workspace being an OverlayFS mount. You set up the mount; A snapshots the upper layer. Eviction handling is operator-side: detecting that a pod was evicted and triggering automatic resume.

### How

**Week 13 — OverlayFS init container.**

1. Pod template gets an `initContainer` that sets up OverlayFS:
   ```yaml
   initContainers:
   - name: setup-workspace
     image: busybox
     command: ["sh", "-c", "mkdir -p /work/upper /work/workdir && \
       mount -t overlay overlay -o lowerdir=/base,upperdir=/work/upper,workdir=/work/workdir /work/merged"]
     securityContext:
       privileged: true
     volumeMounts: [...]
   ```
2. `agent` container mounts `/work/merged` as `/workspace`. `proxy` doesn't need workspace.
3. Coordinate with A: A's snapshot path needs to access `/work/upper` from inside the agent container (or via a shared volume).

**Week 14 — eviction detection.**

4. Operator watches pod events. On `Reason=Evicted` or pod deletion not initiated by operator, transition AgentTask to `Evicted` phase, then to `Provisioning` (auto-resume).
5. On resume: find latest snapshot, set spec to restore that snapshot, set `replay.fromStep` per INTERFACES.md §1.

**Week 15 — resume CLI.**

6. `anvil resume <task-id>` — manually trigger resume from latest snapshot. Useful for debugging.
7. `anvil resume <task-id> --from-snapshot <snapshot-id>` — resume from a specific snapshot.
8. End-to-end test: long task, kill pod, observe automatic resume, verify success.

**Week 16 — long-running tasks demo.**

9. **Long-running tasks sync** (INTERFACES.md §7 Week 16). 10-minute task, mid-task pod kill, automatic resume, completes successfully.

### Acceptance

- [ ] OverlayFS workspace mounted correctly in agent container
- [ ] Privileged init container is the only privileged surface; documented
- [ ] Operator detects pod eviction and triggers resume
- [ ] `anvil resume` manual command works
- [ ] 10-minute task survives mid-task pod kill
- [ ] A's snapshot path can read/write `/work/upper`

### Risks

- **Privileged init container is a security concession.** Bound it (only the init container is privileged; main containers are not). Document. Consider a CSI driver for production hardening (out of scope for v1).
- **Eviction detection edge cases.** "Pod deleted by user vs evicted by scheduler" — distinguish via pod conditions. Test.
- **Resume race conditions.** What if a user submits a resume while the pod is mid-checkpoint? Operator coordinates via task phase.

---

## Phase 4B (Weeks 17–20) — SWE-bench harness orchestration + telemetry pipeline + regression detection

### Goal

Run all 300 SWE-bench Lite tasks. Aggregate cost/latency/token telemetry. Detect regressions against a baseline.

### Build

```
eval/
├── runner/
│   ├── runner.go                  # parallel SWE-bench task runner
│   ├── orchestrator.go            # batches, retries, rate-limits
│   └── result.go                  # task result schema
├── aggregate/
│   ├── stats.go                   # aggregate stats from traces
│   └── regression.go              # diff two runs
└── leaderboard/
    └── format.go                  # leaderboard JSON output

cmd/anvil/
└── eval.go                        # anvil eval --benchmark ...
```

### Tools/libraries

- A's SWE-bench adapter (Phase 4A) — you call it
- Go concurrency primitives for parallelism
- `golang.org/x/sync/errgroup` for orchestration
- Token/cost data from traces (A's telemetry)

### Why

The eval harness is what produces the numbers that go in the writeup. Numbers are what hiring managers screenshot. Without this, the project ships without quantitative results.

### How

**Week 17 — runner skeleton.**

1. `runner.go`: takes a list of SWE-bench tasks, submits each as an AgentTask, polls for completion. Concurrency control: configurable max parallel tasks.
2. Initial test: run 5 tasks, verify each produces a trace.

**Week 18 — orchestration robustness.**

3. Retry logic: transient failures (network, model API errors) retry up to 3x.
4. Rate limiting: respect provider rate limits (Anthropic's TPM/RPM).
5. Cost budgeting: total run cost cap; abort if exceeded.
6. Resume-on-failure: if the runner itself crashes, resume from where it left off (idempotency via task IDs).
7. Run 30 tasks end-to-end; debug edge cases.

**Week 19 — aggregate stats.**

8. `aggregate/stats.go`: load all traces from a run, compute pass rate, mean/median cost per task, mean/median latency, total tokens.
9. `leaderboard/format.go`: leaderboard JSON. One row per task with task_id, outcome, cost, latency, model, trace_url. Aggregate stats at top.
10. Run 100 tasks; verify aggregation correct.

**Week 20 — regression detection.**

11. `regression.go`: diff two runs. Output: tasks newly passing, newly failing, cost delta, latency delta. Surface trace IDs for newly-failing tasks.
12. **Full SWE-bench Lite run** (300 tasks). Total cost target ≤ $200 with Haiku, ≤ $500 with Sonnet.
13. **Eval results sync** (INTERFACES.md §7 Week 20). Hand off leaderboard JSON + failure trace list to A for Phase 5A analysis.

### Acceptance

- [ ] Full SWE-bench Lite run completes (300 tasks)
- [ ] Pass rate reported with confidence interval
- [ ] Per-task cost/latency captured and aggregated
- [ ] Regression detection works against a baseline run
- [ ] Failed task trace IDs are linkable from leaderboard JSON
- [ ] Total cost of full run ≤ $200 (Haiku) or ≤ $500 (Sonnet)
- [ ] Runner handles transient failures gracefully

### Risks

- **Cost overruns.** Run partial benchmarks first (10 → 50 → 300). Don't fire off the full run blind.
- **Rate limit pain.** Anthropic and OpenAI have different rate limits per tier. Tune concurrency accordingly.
- **Flaky SWE-bench tasks.** Some tasks have flaky tests. Document; don't fight them.
- **Long runs (>6 hours).** Monitor manually; have a kill switch.

---

## Phase 5B (Weeks 21–24) — Demo polish, GKE deploy, examples

### Goal

The demo and infrastructure that make the project production-credible. GKE deployment, polished examples, README that converts.

### Build

```
deploy/gke/
├── terraform/                     # GKE cluster provisioning
│   ├── main.tf
│   ├── variables.tf
│   └── outputs.tf
├── values-prod.yaml               # Helm values for GKE
└── README.md                      # GKE deploy guide

examples/
├── 01-hello-world/
├── 02-trivial-bug-fix/
├── 03-swebench-task/
├── 04-replay-and-fork/
└── 05-eval-comparison/

docs/
├── architecture.md                # diagrams, component overview
├── getting-started.md
├── deployment-guide.md
├── threat-model.md
└── api-reference.md               # CRD reference, CLI reference

# Polished READMEs, badges, screenshots, GIFs
```

### Tools/libraries

- Terraform (for GKE)
- mkdocs-material (optional, for docs site)
- `asciinema` or `terminalizer` for terminal GIFs
- Mermaid for diagrams

### Why

The repo is the artifact recruiters click on. If it looks like a hobby project, it gets dismissed. If it looks like a real platform, it gets a callback. Spend time on polish.

### How

**Week 21 — examples + docs.**

1. Five worked examples, each with its own README, walking through a real use case.
2. `docs/architecture.md` with mermaid diagrams (steal from SPEC.md).
3. `docs/getting-started.md` — 10-minute quickstart from zero.
4. `docs/deployment-guide.md` — kind, GKE, helm.

**Week 22 — GKE deploy.**

5. Terraform for a small GKE cluster (one e2-standard-4 node, gVisor enabled).
6. Helm values tuned for prod. Real S3 (GCS-compatible).
7. `make deploy-gke` workflow; document credentials.
8. Stand up a live demo. Document the URL.

**Week 23 — polish.**

9. README polish: hero image, badges (CI, license, version), 30-second elevator pitch, links to demo + blog post (when A publishes), screenshots, GIF of `make demo`.
10. Threat model doc — describe the security boundaries explicitly. This signals seriousness about security.
11. API reference auto-generation from CRD types and cobra commands.

**Week 24 — ship.**

12. **Final sync** (INTERFACES.md §7 Week 24).
13. Coordinate launch with A's blog post.
14. Post-launch: monitor issues, respond to questions, fix obvious bugs.

### Acceptance

- [ ] GKE deployment works; live demo accessible at a URL
- [ ] README is polished: clear pitch, badges, screenshots, links
- [ ] Five examples each have working README and runnable code
- [ ] Architecture, deployment, threat-model, API reference docs all written
- [ ] `make demo` still works on fresh laptop (regression test)

### Risks

- **GKE cost.** A small cluster is ~$3/day. Document that the demo URL has a budget; might come down on a schedule.
- **Underweight the README.** This is the artifact most recruiters see. Spend a full day on it.
- **Security claims you can't back up.** Don't claim "production-grade security" if the platform is a demo. Be precise about the threat model.

---

## What to drop if behind schedule (in this order)

1. Terraform for GKE (use a manually-created cluster and document the steps)
2. mkdocs site (markdown files in docs/ are enough)
3. Some examples (3 instead of 5 is fine)
4. Grafana dashboards (Prometheus alone is enough)
5. Helm chart polish (raw manifests are fine for v1)

**Do not drop:**
- Operator + CRD + pod template (Phase 1B; load-bearing for everything)
- gVisor or documented fallback (security claim depends on it)
- pkg/trace (A depends on it)
- Eviction handling (A's snapshots depend on it)
- SWE-bench harness (the numbers depend on it)
- Live GKE demo (the credibility depends on it)

If you can't finish all the must-keeps, raise it in a sync, redistribute with A, or extend timeline.

## What to do if ahead of schedule

1. Multi-region GKE with failover
2. CSI driver for OverlayFS (replace privileged init container)
3. Horizontal scaling: multi-replica operator with leader election
4. Webhook-based AgentTask validation
5. mkdocs-material docs site

## Resume bullets to write *toward*

- *Designed and built the Kubernetes operator and sandbox infrastructure for Agent-Anvil, an open-source agent execution platform. Implemented the AgentTask CRD, gVisor-isolated pod template with NetworkPolicy egress controls, and OverlayFS-based workspace mounts supporting checkpoint and resume across pod evictions.*
- *Built the SWE-bench Lite eval harness orchestrator with parallel task execution, retry logic, rate-limit-aware scheduling, and cost-budgeted termination; ran the full benchmark with end-to-end cost/latency telemetry under $200.*
- *Deployed Agent-Anvil to GKE with full observability (OpenTelemetry, Prometheus, Grafana) and infrastructure-as-code provisioning, supporting a public live demo.*

If a sub-task isn't contributing to one of these bullets, justify why before doing it.
