"""Week 2 acceptance: the SDK's parsed config matches what B's operator projects.

The operator marshals an AgentTaskSpec Go struct via sigs.k8s.io/yaml into the
task.yaml that's mounted into the pod. We round-trip the same shape on the
Python side: load, dump back to camelCase YAML, compare with the original.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from agent_anvil.config import (
    AgentTaskSpec,
    CheckpointPolicySpec,
    ModelSpec,
    ReplaySpec,
    ResourceSpec,
    ToolSpec,
    WorkspaceSpec,
    load_task,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_minimal() -> None:
    spec = load_task(FIXTURES / "task_minimal.yaml")
    assert spec.prompt == "Say hello and stop."
    assert spec.system_prompt == "Be brief."
    assert spec.model is not None
    assert spec.model.provider == "anthropic"
    assert spec.model.name == "claude-haiku-4-5"
    assert len(spec.tools) == 1
    assert spec.tools[0].name == "bash"
    assert spec.tools[0].timeout_seconds == 30


def test_load_full_with_aliases() -> None:
    spec = load_task(FIXTURES / "task_full.yaml")
    assert spec.system_prompt.startswith("You are a careful")
    assert spec.model is not None
    assert spec.model.api_key_secret_ref is not None
    assert spec.model.api_key_secret_ref.name == "agent-credentials"
    assert spec.model.params["maxTokens"] == "8192"
    assert spec.workspace is not None
    assert spec.workspace.base_image.startswith("ghcr.io")
    assert spec.workspace.init_command == ["pip", "install", "-r", "requirements.txt"]
    assert spec.timeout_seconds == 1800
    assert spec.max_steps == 100
    assert spec.resources is not None
    assert spec.resources.memory == "4Gi"
    assert spec.checkpoint_policy is not None
    assert spec.checkpoint_policy.mode == "Manual"
    assert spec.replay is not None
    assert spec.replay.checkpoint_id == "task-abc-123"


def test_load_full_crd_form() -> None:
    """Loading from a full CRD document (apiVersion/kind/metadata/spec) works."""
    spec = load_task(FIXTURES / "task_crd.yaml")
    assert spec.prompt == "hello"
    assert spec.tools[0].name == "bash"


def test_round_trip_preserves_camelcase() -> None:
    """The shape on disk uses Go-style camelCase; round-tripping must preserve it.

    This is the Week 2 CRD-freeze acceptance gate: the operator's projected
    YAML and the SDK's emitted YAML must match.
    """
    original = (FIXTURES / "task_full.yaml").read_text()
    spec = AgentTaskSpec.model_validate(yaml.safe_load(original))
    # Dump with aliases (camelCase) and exclude None defaults to avoid noisy
    # diff. The shape that goes back out should be a superset / subset of the
    # original — every key the original has must be present in the round-trip.
    emitted = spec.model_dump(by_alias=True, exclude_none=True)
    parsed_original = yaml.safe_load(original)

    def keys_recursive(obj: object, prefix: str = "") -> set[str]:
        keys: set[str] = set()
        if isinstance(obj, dict):
            for k, v in obj.items():
                p = f"{prefix}.{k}" if prefix else k
                keys.add(p)
                keys |= keys_recursive(v, p)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                keys |= keys_recursive(item, f"{prefix}[{i}]")
        return keys

    orig_keys = keys_recursive(parsed_original)
    emitted_keys = keys_recursive(emitted)
    missing = orig_keys - emitted_keys
    assert not missing, f"Round-trip lost keys: {missing}"


def test_snake_case_input_also_works() -> None:
    """Pydantic accepts either the alias (camelCase) or the field name."""
    raw = {
        "prompt": "x",
        "system_prompt": "y",
        "model": {"provider": "anthropic", "name": "claude-haiku-4-5"},
        "tools": [{"name": "bash", "timeout_seconds": 5}],
    }
    spec = AgentTaskSpec.model_validate(raw)
    assert spec.system_prompt == "y"
    assert spec.tools[0].timeout_seconds == 5


def test_missing_model_is_allowed_for_skeleton() -> None:
    """Phase 0 skeleton tasks (no model) load — useful for hello-world testing."""
    spec = AgentTaskSpec.model_validate({"prompt": "hi"})
    assert spec.model is None


def test_invalid_checkpoint_mode_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentTaskSpec.model_validate(
            {
                "prompt": "x",
                "checkpointPolicy": {"mode": "Nonsense"},
            }
        )


def test_helper_construction() -> None:
    """Round-trip via direct constructors. Sanity check on the model definitions."""
    spec = AgentTaskSpec(
        prompt="hi",
        model=ModelSpec(provider="anthropic", name="claude-haiku-4-5"),
        tools=[ToolSpec(name="bash")],
        workspace=WorkspaceSpec(base_image="x"),
        resources=ResourceSpec(cpu="1", memory="2Gi"),
        checkpoint_policy=CheckpointPolicySpec(mode="EveryStep"),
        replay=ReplaySpec(checkpoint_id="c-1", from_step=3),
    )
    dumped = spec.model_dump(by_alias=True)
    assert dumped["workspace"]["baseImage"] == "x"
    assert dumped["checkpointPolicy"]["mode"] == "EveryStep"
    assert dumped["replay"]["fromStep"] == 3
