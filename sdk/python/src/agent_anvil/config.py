"""AgentTaskSpec parsing.

Mirrors `api/v1/agenttask_types.go` field-for-field. The operator's controller
marshals `AgentTask.Spec` via `sigs.k8s.io/yaml` (which honors Go JSON tags)
into a ConfigMap that's mounted at `/etc/agent-anvil/task.yaml`. The shapes
defined here must round-trip with that marshalled YAML.

Field names use snake_case in Python with camelCase aliases that match the Go
JSON tags. Pydantic accepts either form on input and emits camelCase on output
when called with `by_alias=True`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field


class APIKeySecretRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = ""
    key: str = ""


class ModelSpec(BaseModel):
    # `protected_namespaces=()` disables Pydantic's "field name conflicts with
    # `model_` namespace" guard. The Go CRD field is literally `model`, so we
    # have to live with it.
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())

    provider: str = ""
    name: str = ""
    api_key_secret_ref: APIKeySecretRef | None = Field(default=None, alias="apiKeySecretRef")
    params: dict[str, str] = Field(default_factory=dict)


class ToolSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str = ""
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds")


class WorkspaceSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    base_image: str = Field(default="", alias="baseImage")
    init_command: list[str] = Field(default_factory=list, alias="initCommand")


class ResourceSpec(BaseModel):
    # Go side uses k8s resource.Quantity which serializes to a string like
    # "2" or "4Gi". Keep them as strings — parsing is a downstream concern.
    model_config = ConfigDict(populate_by_name=True)
    cpu: str = ""
    memory: str = ""
    ephemeral_storage: str = Field(default="", alias="ephemeralStorage")


CheckpointMode = Literal["Manual", "EveryStep", "Interval"]


class CheckpointPolicySpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    mode: CheckpointMode = "Manual"
    interval_seconds: int | None = Field(default=None, alias="intervalSeconds")


class ReplaySpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    checkpoint_id: str = Field(default="", alias="checkpointId")
    from_step: int = Field(default=0, alias="fromStep")


class AgentTaskSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True, protected_namespaces=())

    prompt: str = ""
    system_prompt: str = Field(default="", alias="systemPrompt")
    model: ModelSpec | None = None
    tools: list[ToolSpec] = Field(default_factory=list)
    workspace: WorkspaceSpec | None = None
    timeout_seconds: int | None = Field(default=None, alias="timeoutSeconds")
    max_steps: int | None = Field(default=None, alias="maxSteps")
    resources: ResourceSpec | None = None
    checkpoint_policy: CheckpointPolicySpec | None = Field(default=None, alias="checkpointPolicy")
    replay: ReplaySpec | None = None


def load_task(path: Path | str) -> AgentTaskSpec:
    """Load `task.yaml` into an AgentTaskSpec.

    Accepts either:
    1. The projected form (just the spec content) that the operator writes to
       `/etc/agent-anvil/task.yaml`, e.g. `{"prompt": "...", "model": {...}}`.
    2. The full CRD form (`apiVersion`/`kind`/`metadata`/`spec`) that users
       might point the local CLI at via `python -m agent_anvil --task task.yaml`.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"task.yaml root must be a mapping, got {type(raw).__name__}")
    if "apiVersion" in raw and "spec" in raw:
        raw = raw["spec"]
    return AgentTaskSpec.model_validate(raw)
