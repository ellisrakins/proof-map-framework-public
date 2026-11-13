"""Versioned, offline-validated records at the paper/execution trust boundary.

Record identity excludes only its own identity, never subject or material bindings.
The contained JSON is held as immutable bytes; callers receive defensive copies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib.resources import files
from typing import TYPE_CHECKING, Any, ClassVar, Mapping, TypeVar, cast

from .attempts import FormalObligation
from .integrity import (
    ValidationIssue,
    artifact_digest,
    canonical_bytes,
    digest,
    relative_path,
    strict_loads,
)

if TYPE_CHECKING:
    from jsonschema.protocols import Validator

VERSION = "1.0"
R = TypeVar("R", bound="Record")
KINDS = {
    "FormalizationBinding": "formalization-binding",
    "VerifierProfile": "verifier-profile",
    "EnvironmentManifest": "environment-manifest",
    "ExecutionEvent": "execution-event",
    "ReviewDecision": "review-decision",
    "AcceptanceRecord": "acceptance-record",
    "AssessmentRecord": "assessment-record",
}
_RECORD_SCHEMAS = frozenset(KINDS.values())


@lru_cache(maxsize=len(_RECORD_SCHEMAS))
def _record_validator(kind: str) -> Validator:
    """Reuse private packaged schemas, never input records or validation results."""
    from jsonschema import Draft202012Validator

    if kind not in _RECORD_SCHEMAS:
        raise ValueError("RECORD_TYPE_UNSUPPORTED")
    schema = strict_loads(files("proofmap.resources").joinpath(kind + ".schema.json").read_bytes())
    return Draft202012Validator(schema)


def validate_record(value: Mapping[str, Any]) -> None:
    """Validate schema, identity and invariants, without fetching remote schemas."""
    canonical_bytes(value)

    if (
        not isinstance(value, dict)
        or not isinstance(value.get("record_type"), str)
        or value.get("record_type") not in KINDS
    ):
        if isinstance(value, dict) and value.get("record_type") == "StageResult":
            from .paper_stages import StageResult

            StageResult.from_dict(value)
            return
        raise ValueError("RECORD_TYPE_UNSUPPORTED")
    kind = KINDS[value["record_type"]]
    errors = sorted(_record_validator(kind).iter_errors(value), key=lambda e: str(e.path))
    if errors:
        raise ValueError("RECORD_SCHEMA: " + errors[0].message[:256])
    body = {k: v for k, v in value.items() if k != "id"}
    if value["id"] != digest(kind + ".v1", body):
        raise ValueError("RECORD_IDENTITY_MISMATCH")
    if kind == "formalization-binding":
        for loc in value["source_locators"]:
            relative_path(loc.get("artifact", loc.get("file")))
            if "file" in loc or loc["format"] == "tex":
                if (
                    type(loc["start"]) is not int
                    or type(loc["end"]) is not int
                    or loc["end"] < loc["start"]
                ):
                    raise ValueError("BINDING_SOURCE_INTERVAL")
                if "artifact" in loc and (
                    loc["page"] is not None or loc["offsets"] != "utf8-bytes-half-open"
                ):
                    raise ValueError("BINDING_TEX_COORDINATES")
            elif (
                loc["start"] is not None
                or loc["end"] is not None
                or loc["page"] is None
                or loc["offsets"] != "reconstructed-text-no-source-offsets"
                or (loc.get("text_start") is None) != (loc.get("text_end") is None)
                or (loc.get("text_start") is not None and loc["text_end"] < loc["text_start"])
            ):
                raise ValueError("BINDING_PDF_COORDINATES")
    if kind in {"assessment-record", "acceptance-record"}:
        try:
            instant = datetime.fromisoformat(value["evaluation_time"].replace("Z", "+00:00"))
            if instant.utcoffset() is None:
                raise ValueError("missing timezone")
        except ValueError as exc:
            raise ValueError("ASSESSMENT_TIME: expected timezone-aware ISO timestamp") from exc
    if kind == "acceptance-record":
        formal = value["formal_status"] == "VERIFIED"
        approved = value["source_fidelity"] == value["formal_fidelity"] == "APPROVE"
        rejected = "REJECT" in (value["source_fidelity"], value["formal_fidelity"])
        if formal != (value["execution_digest"] is not None):
            raise ValueError("ACCEPTANCE_EXECUTION_BINDING")
        if value["assessment"] == "ACCEPTED_UNDER_POLICY" and (
            not formal or not approved or len(value["review_digests"]) < 2 or value["reasons"]
        ):
            raise ValueError("ACCEPTANCE_POLICY_INVARIANTS")
        if (
            (value["assessment"] == "REVIEW_REQUIRED" and not formal)
            or (value["assessment"] == "UNVERIFIED" and formal)
            or (value["assessment"] == "REJECTED" and not rejected)
            or (rejected and value["assessment"] != "REJECTED")
        ):
            raise ValueError("ACCEPTANCE_STATE_INVARIANTS")
        if (approved or rejected) and not value["review_digests"]:
            raise ValueError("ACCEPTANCE_REVIEW_BINDING")
    if kind == "assessment-record":
        if value["status"] == "NOT_ASSESSED" and value["evidence_digests"]:
            raise ValueError("ASSESSMENT_NOT_ASSESSED_EVIDENCE")
        if value["authentication"] == "VERIFIED" and (
            value["authority_digest"] is None or not value["authentication_digests"]
        ):
            raise ValueError("ASSESSMENT_AUTHENTICATION_PROVENANCE")
    if kind == "environment-manifest" and value["complete"]:
        required = {
            "lean_sha256",
            "library_digest",
            "checker_digest",
            "version",
            "platform",
            "executable",
            "search_path",
            "image",
        }
        if (
            set(value["actual"]) != required
            or not value["reason"]
            or "version 4.30.0," not in value["actual"]["version"]
        ):
            raise ValueError("ENVIRONMENT_COMPLETE_MATERIAL")
    if kind == "execution-event":
        EnvironmentManifest.from_dict(value["environment"])
        if value["environment"]["profile_digest"] != value["profile_digest"]:
            raise ValueError("EXECUTION_MIXED_PROFILE")
        for name, raw in value["outputs"].items():
            if value["output_digests"].get(name) != digest("execution-output.v1", raw):
                raise ValueError("EXECUTION_OUTPUT_MISMATCH")
        if set(value["outputs"]) != set(value["output_digests"]):
            raise ValueError("EXECUTION_OUTPUT_MISMATCH")
        if value["outcome"] == "VERIFIED" and (
            not value["environment"]["complete"]
            or value["checker_outcome"] != "PASS"
            or value["compiler_outcome"] != "PASS"
            or any(x not in ("Classical.choice", "Quot.sound", "propext") for x in value["axioms"])
        ):
            raise ValueError("EXECUTION_VERIFIED_INVARIANTS")


@dataclass(frozen=True)
class Record:
    _bytes: bytes
    KIND: ClassVar[str] = ""

    @classmethod
    def from_dict(cls: type[R], value: Mapping[str, Any]) -> R:
        copied = strict_loads(canonical_bytes(dict(value)))
        if copied.get("record_type") != cls.KIND:
            raise ValueError("RECORD_TYPE_MISMATCH")
        validate_record(copied)
        return cls(canonical_bytes(copied))

    @classmethod
    def build(cls: type[R], **fields: Any) -> R:
        value = {"record_type": cls.KIND, "schema_version": VERSION, **fields}
        value["id"] = digest(KINDS[cls.KIND] + ".v1", value)
        return cls.from_dict(value)

    def to_dict(self) -> dict[str, Any]:
        return cast(dict[str, Any], strict_loads(self._bytes))

    def __getattr__(self, name: str) -> Any:
        try:
            return self.to_dict()[name]
        except KeyError as exc:
            raise AttributeError(name) from exc

    @property
    def digest(self) -> str:
        return str(self.to_dict()["id"])


class FormalizationBinding(Record):
    KIND = "FormalizationBinding"

    @classmethod
    def create(
        cls,
        *,
        revision_id: str,
        assertion_id: str,
        assertion_digest: str,
        source_locators: list[dict[str, Any]],
        context_digest: str,
        definition_digest: str,
        obligation: FormalObligation,
        method: str,
        candidate: bytes = b"by grind",
    ) -> FormalizationBinding:
        if assertion_id != obligation.target_node_id:
            raise ValueError("FORMAL_OBLIGATION_ASSERTION_MISMATCH")
        return cls.build(
            revision_id=revision_id,
            assertion_id=assertion_id,
            assertion_digest=assertion_digest,
            source_locators=source_locators,
            context_digest=context_digest,
            definition_digest=definition_digest,
            obligation_digest=obligation_identity(obligation),
            candidate_digest=artifact_digest(candidate),
            method=method,
        )


def obligation_identity(obligation: FormalObligation) -> str:
    return digest("formal-obligation.v1", obligation.to_dict())


class VerifierProfile(Record):
    KIND = "VerifierProfile"

    @classmethod
    def create(
        cls,
        *,
        image: str,
        platform: str,
        lean_sha256: str,
        library_digest: str,
        checker_digest: str,
        acquisition_digest: str,
        limits: dict[str, int] | None = None,
    ) -> VerifierProfile:
        return cls.build(
            name="lean-std-int-polynomial-v1",
            toolchain="leanprover/lean4:v4.30.0",
            imports=["Std"],
            axioms=["Classical.choice", "Quot.sound", "propext"],
            executable="/opt/lean/bin/lean",
            search_path="/opt/lean/lib/lean",
            image=image,
            platform=platform,
            lean_sha256=lean_sha256,
            library_digest=library_digest,
            checker_digest=checker_digest,
            acquisition_digest=acquisition_digest,
            limits=limits
            if limits is not None
            else {
                "seconds": 120,
                "memory_mb": 2048,
                "cpus": 1,
                "pids": 64,
                "output_bytes": 1000000,
                "temp_mb": 128,
            },
        )


class EnvironmentManifest(Record):
    KIND = "EnvironmentManifest"


class ExecutionEvent(Record):
    KIND = "ExecutionEvent"


class ReviewDecision(Record):
    KIND = "ReviewDecision"

    @classmethod
    def create(
        cls,
        *,
        binding: FormalizationBinding,
        profile: VerifierProfile,
        dimension: str,
        decision: str,
        reviewer_id: str,
        method: str = "human-review-v1",
        supersedes: str | None = None,
    ) -> ReviewDecision:
        return cls.build(
            binding_digest=binding.digest,
            revision_id=binding.revision_id,
            assertion_id=binding.assertion_id,
            obligation_digest=binding.obligation_digest,
            profile_digest=profile.digest,
            dimension=dimension,
            decision=decision,
            reviewer_id=reviewer_id,
            method=method,
            supersedes=supersedes,
        )


class AcceptanceRecord(Record):
    KIND = "AcceptanceRecord"


class AssessmentRecord(Record):
    """A dimension-specific assessment with provenance, not a trust capability.

    ``authentication`` reports a caller's verification result. Schema validity,
    record hashes, or a caller-authored VERIFIED field never grant closure or
    authenticate an actor; the external execution/review adapter does that.
    """

    KIND = "AssessmentRecord"


def record_issues(value: Mapping[str, Any]) -> list[ValidationIssue]:
    """Stable structured issues while preserving existing ValueError callers."""
    try:
        validate_record(value)
    except (ValueError, TypeError, KeyError) as exc:
        return [ValidationIssue(str(exc).split(":", 1)[0], "/record", str(exc))]
    return []


def record_type(value: Mapping[str, Any]) -> type[Record]:
    name = value.get("record_type", "")
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z]+", name) or name not in KINDS:
        raise ValueError("RECORD_TYPE_UNSUPPORTED")
    return cast(type[Record], globals()[name])
