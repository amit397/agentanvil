# Agent-Anvil SDK container.
#
# The operator launches this image as the `agent` container in the sandbox pod
# (internal/controller/pod_builder.go). It picks up the projected task.yaml at
# /etc/agent-anvil/task.yaml and writes events.jsonl to /var/log/agent-anvil/.

FROM python:3.12-slim AS builder

WORKDIR /build

# Install deps into a known prefix so the runtime stage can copy them with
# their dependencies intact.
COPY pyproject.toml ./
COPY README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim

# Tools used by the bash tool. Keep the layer thin — anything else can be
# baked into the per-task base image referenced by `workspace.baseImage`.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

# The operator mounts these as emptyDir / projected ConfigMap. Pre-creating
# them avoids permission surprises under non-root.
RUN mkdir -p /etc/agent-anvil /var/log/agent-anvil /workspace

# Don't run as root inside the sandbox.
RUN useradd --create-home --uid 65532 agent \
    && chown -R agent:agent /var/log/agent-anvil /workspace
USER 65532:65532
WORKDIR /workspace

ENV PYTHONUNBUFFERED=1 \
    AGENT_ANVIL_TRACE_DIR=/var/log/agent-anvil \
    AGENT_ANVIL_WORKSPACE=/workspace

ENTRYPOINT ["python", "-m", "agent_anvil"]
