"""Versioned stage identities; cache content is analysis, never execution authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .integrity import canonical_bytes, digest, require_digest, strict_loads
from .schema import validate

PURE_STAGES = frozenset({"parsing", "extraction", "formalization"})


def validate_stage_output(stage: str, revision: str, output: dict[str, Any]) -> None:
    canonical_bytes(output)
    if not isinstance(output, dict):
        raise ValueError("STAGE_OUTPUT_SCHEMA")
    if stage == "parsing" and (validate("document-ir", output) or output["revision"] != revision):
        raise ValueError("STAGE_OUTPUT_SCHEMA")
    if stage == "extraction":
        from .extractor import extract

        if (
            set(output) != {"event", "chunk", "config"}
            or output["chunk"].get("revision") != revision
        ):
            raise ValueError("STAGE_OUTPUT_SCHEMA")
        replayed = extract(output["chunk"], output["config"], replay=output["event"])
        if replayed["result"] != output["event"].get("result"):
            raise ValueError("STAGE_EXTRACTION_REPLAY_MISMATCH")
    if stage == "formalization":
        from .attempts import FormalObligation
        from .formalize import validate_formalization

        if set(output) != {"row", "fingerprint", "parent_stage"}:
            raise ValueError("STAGE_FORMALIZATION_FIELDS")
        require_digest(output["fingerprint"])
        if output["parent_stage"] is not None:
            require_digest(output["parent_stage"])
        row = output["row"]
        validate_formalization(row)
        if (
            not isinstance(row, dict)
            or row.get("schema_version") != "1.0"
            or row.get("revision") != revision
            or row.get("status") not in {"SUPPORTED", "UNSUPPORTED"}
            or {
                "binding",
                "execution_event",
                "resolution",
                "historical_execution",
                "candidate_method",
            }
            & row.keys()
        ):
            raise ValueError("STAGE_FORMALIZATION_SCHEMA")
        require_digest(row["assertion_id"])
        require_digest(row["context_digest"])
        require_digest(row["definition_digest"])
        if row["status"] == "SUPPORTED":
            obligation = FormalObligation.from_dict(row["obligation"])
            if (
                obligation.target_node_id != row["assertion_id"]
                or not isinstance(row.get("candidate"), str)
                or row.get("fidelity") != "NOT_REVIEWED"
                or row.get("exact_check", {}).get("authority")
                != "LOCAL_ANALYSIS_NOT_FORMAL_EVIDENCE"
            ):
                raise ValueError("STAGE_FORMALIZATION_BINDING")


def stage_key(
    *,
    revision: str,
    analysis: str,
    stage: str,
    inputs: dict[str, str],
    implementation: str,
    parents: dict[str, str] | None = None,
    namespace: str = "local-controller",
) -> dict[str, Any]:
    require_digest(revision)
    require_digest(analysis)
    for name in (stage, implementation, namespace):
        if not isinstance(name, str) or not name or len(name) > 512:
            raise ValueError("INVALID_STAGE_KEY")
    for mapping in (inputs, parents or {}):
        if not isinstance(mapping, dict):
            raise ValueError("INVALID_STAGE_DEPENDENCIES")
        for key, value in mapping.items():
            if not isinstance(key, str) or not key:
                raise ValueError("INVALID_STAGE_DEPENDENCIES")
            require_digest(value)
    return {
        "revision": revision,
        "analysis": analysis,
        "stage": stage,
        "inputs": inputs,
        "implementation": implementation,
        "parents": parents or {},
        "namespace": namespace,
    }


@dataclass(frozen=True)
class StageResult:
    """Validated canonical record. Consumers obtain copies, not mutable internals."""

    _canonical: bytes

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> StageResult:
        raw = canonical_bytes(value)
        if validate("stage-result", value):
            raise ValueError("INVALID_STAGE_RESULT_SCHEMA")
        if value["id"] != digest("stage-result.v1", {k: v for k, v in value.items() if k != "id"}):
            raise ValueError("INVALID_STAGE_RESULT_ID")
        if value["cache_provenance"]["namespace"] != value["namespace"]:
            raise ValueError("INVALID_STAGE_CACHE_PROVENANCE")
        stage_key(
            **{
                name: value[name]
                for name in (
                    "revision",
                    "analysis",
                    "stage",
                    "inputs",
                    "implementation",
                    "parents",
                    "namespace",
                )
            }
        )
        for key, number in value["resource_use"].items():
            if number is not None and (type(number) not in (int, float) or number < 0):
                raise ValueError("INVALID_STAGE_RESOURCE_USE: " + key)
        return cls(raw)

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = strict_loads(self._canonical)
        return value

    def digest(self) -> str:
        return str(self.to_dict()["id"])
