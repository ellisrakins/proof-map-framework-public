"""Verifier-gated proof-attempt receipts for AI and human proof search.

The existing Lean exporter is an obligation *scaffold*: it deliberately emits
axioms so that the shape of a proof map can be inspected.  This module serves a
different purpose.  It checks a candidate proof term against an immutable Lean
statement, records exactly what was checked, and never mutates the proof map.

The verifier is a reproducibility and proof-integrity boundary, not a security
sandbox.  Candidate files must come from a trusted local workflow.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .integrity import atomic_write, finite_number, load_json
from .lean_check import LeanCheckResult, check_lean_file, resolve_lean_executable
from .model import ProofMap

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_LEAN_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_']*(?:\.[A-Za-z_][A-Za-z0-9_']*)*$")
_LEAN_IMPORT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_LEAN_TOOLCHAIN_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+:v([0-9]+(?:\.[0-9]+){2,3})$")
_AXIOM_LIST_RE = re.compile(
    r"([^\s]+)\s+depends on axioms:\s*\[(.*?)\]",
    re.DOTALL,
)
_NO_AXIOMS_RE = re.compile(r"([^\s]+)\s+does not depend on any axioms")
_FORBIDDEN_CANDIDATE_WORDS = {
    "admit",
    "axiom",
    "class",
    "def",
    "elab",
    "inductive",
    "initialize",
    "instance",
    "lemma",
    "macro",
    "namespace",
    "noncomputable",
    "opaque",
    "run_tac",
    "section",
    "set_option",
    "sorry",
    "structure",
    "syntax",
    "theorem",
    "universe",
    "unsafe",
    "variable",
}


def utc_now() -> str:
    """Return a stable UTC timestamp suitable for JSON receipts."""

    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def normalize_statement(statement: str) -> str:
    """Normalize inconsequential surrounding whitespace before hashing."""

    return "\n".join(line.rstrip() for line in statement.replace("\r\n", "\n").split("\n")).strip()


def sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value: Mapping[str, Any] | list[Any]) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return sha256_text(payload)


def _require_sha256(value: str, field_name: str, *, allow_empty: bool = False) -> None:
    if allow_empty and not value:
        return
    if not _SHA256_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 hex digest")


def _unique(items: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(items))


def _string_tuple(value: Any, field_name: str, *, unique: bool = False) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{field_name} must be an array of strings")
    return _unique(value) if unique else tuple(value)


def _freeze_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON metadata cannot contain NaN or Infinity")
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f"Unsupported JSON metadata value: {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _load_json(path_or_text: str | Path) -> Mapping[str, Any]:
    value = load_json(path_or_text)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


class AttemptOutcome(str, Enum):
    """Result of checking one exact candidate artifact."""

    VERIFIED = "VERIFIED"
    POLICY_REJECTED = "POLICY_REJECTED"
    COMPILER_REJECTED = "COMPILER_REJECTED"
    UNTRUSTED_AXIOMS = "UNTRUSTED_AXIOMS"
    TIMEOUT = "TIMEOUT"
    VERIFIER_UNAVAILABLE = "VERIFIER_UNAVAILABLE"
    VERIFIER_ERROR = "VERIFIER_ERROR"


@dataclass(frozen=True)
class FormalObligation:
    """An immutable Lean statement bound to one proof-map target node."""

    id: str
    target_node_id: str
    statement: str
    toolchain: str
    declaration_name: str = ""
    imports: tuple[str, ...] | list[str] = field(default_factory=tuple)
    allowed_axioms: tuple[str, ...] | list[str] = field(default_factory=tuple)
    statement_sha256: str = ""
    notes: str = ""
    metadata: Mapping[str, Any] = field(default_factory=dict)
    formal_system: str = "lean4"

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Obligation id cannot be empty")
        if not self.target_node_id:
            raise ValueError("Obligation target_node_id cannot be empty")
        if not normalize_statement(self.statement):
            raise ValueError(f"Obligation {self.id} must contain a Lean statement")
        if self.formal_system.lower() != "lean4":
            raise ValueError("Verified Lean Attempt v1 only supports formal_system='lean4'")
        object.__setattr__(self, "formal_system", "lean4")
        if not _LEAN_TOOLCHAIN_RE.fullmatch(self.toolchain):
            raise ValueError(
                "Lean toolchain must be a pinned release such as 'leanprover/lean4:v4.30.0'"
            )

        if not self.declaration_name:
            object.__setattr__(self, "declaration_name", _lean_name(self.id))
        if not _LEAN_NAME_RE.fullmatch(self.declaration_name):
            raise ValueError(f"Invalid Lean declaration name: {self.declaration_name}")

        object.__setattr__(self, "imports", _string_tuple(self.imports, "imports", unique=True))
        object.__setattr__(
            self,
            "allowed_axioms",
            _string_tuple(self.allowed_axioms, "allowed_axioms", unique=True),
        )
        for module in self.imports:
            if not _LEAN_IMPORT_RE.fullmatch(module):
                raise ValueError(f"Invalid Lean import name: {module}")
        for axiom in self.allowed_axioms:
            if not _LEAN_NAME_RE.fullmatch(axiom):
                raise ValueError(f"Invalid allowed axiom name: {axiom}")
            if axiom == "sorryAx" or axiom.endswith(".sorryAx"):
                raise ValueError("sorryAx can never be an allowed axiom")

        expected_hash = sha256_text(normalize_statement(self.statement))
        _require_sha256(self.statement_sha256, "statement_sha256", allow_empty=True)
        if self.statement_sha256 and self.statement_sha256 != expected_hash:
            raise ValueError(
                f"Statement hash mismatch for obligation {self.id}: "
                f"expected {expected_hash}, got {self.statement_sha256}"
            )
        object.__setattr__(self, "statement_sha256", expected_hash)
        if not isinstance(self.metadata, Mapping):
            raise ValueError("Obligation metadata must be a JSON object")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_node_id": self.target_node_id,
            "statement": self.statement,
            "toolchain": self.toolchain,
            "declaration_name": self.declaration_name,
            "imports": list(self.imports),
            "allowed_axioms": list(self.allowed_axioms),
            "statement_sha256": self.statement_sha256,
            "notes": self.notes,
            "metadata": _thaw_json(self.metadata),
            "formal_system": self.formal_system,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "FormalObligation":
        required = {
            "id",
            "target_node_id",
            "statement",
            "toolchain",
            "statement_sha256",
            "formal_system",
        }
        missing = sorted(required.difference(data))
        if missing:
            raise ValueError(f"Formal obligation is missing required fields: {', '.join(missing)}")
        return cls(**dict(data))

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(
            self.to_dict(),
            indent=indent,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        if path is not None:
            Path(path).write_text(text + "\n", encoding="utf-8")
        return text

    @classmethod
    def from_json(cls, path_or_text: str | Path) -> "FormalObligation":
        return cls.from_dict(_load_json(path_or_text))


@dataclass(frozen=True)
class ProofAttempt:
    """A candidate proof artifact plus generator and resource provenance."""

    id: str
    obligation_id: str
    artifact_path: str
    producer: str
    provider: str = ""
    model: str = ""
    model_version: str = ""
    run_id: str = ""
    prompt_sha256: str = ""
    artifact_sha256: str = ""
    parent_attempt_ids: tuple[str, ...] | list[str] = field(default_factory=tuple)
    strategy: str = ""
    created_at: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    generation_seconds: float = 0.0
    estimated_cost_usd: float = 0.0
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Attempt id cannot be empty")
        finite_number(self.generation_seconds, "generation_seconds", minimum=0)
        finite_number(self.estimated_cost_usd, "estimated_cost_usd", minimum=0)
        if not self.obligation_id:
            raise ValueError("Attempt obligation_id cannot be empty")
        if not self.artifact_path:
            raise ValueError("Attempt artifact_path cannot be empty")
        if not self.producer:
            raise ValueError("Attempt producer cannot be empty")
        _require_sha256(self.prompt_sha256, "prompt_sha256", allow_empty=True)
        _require_sha256(self.artifact_sha256, "artifact_sha256", allow_empty=True)
        if (
            isinstance(self.input_tokens, bool)
            or isinstance(self.output_tokens, bool)
            or not isinstance(self.input_tokens, int)
            or not isinstance(self.output_tokens, int)
            or self.input_tokens < 0
            or self.output_tokens < 0
        ):
            raise ValueError("Attempt token counts must be nonnegative")
        if (
            not math.isfinite(self.generation_seconds)
            or not math.isfinite(self.estimated_cost_usd)
            or self.generation_seconds < 0
            or self.estimated_cost_usd < 0
        ):
            raise ValueError("Attempt duration and cost must be nonnegative")
        object.__setattr__(
            self,
            "parent_attempt_ids",
            _string_tuple(self.parent_attempt_ids, "parent_attempt_ids", unique=True),
        )
        if self.id in self.parent_attempt_ids:
            raise ValueError(f"Attempt {self.id} cannot be its own parent")
        if not self.created_at:
            object.__setattr__(self, "created_at", utc_now())
        if not isinstance(self.metadata, Mapping):
            raise ValueError("Attempt metadata must be a JSON object")
        object.__setattr__(self, "metadata", _freeze_json(self.metadata))

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "obligation_id": self.obligation_id,
            "artifact_path": self.artifact_path,
            "producer": self.producer,
            "provider": self.provider,
            "model": self.model,
            "model_version": self.model_version,
            "run_id": self.run_id,
            "prompt_sha256": self.prompt_sha256,
            "artifact_sha256": self.artifact_sha256,
            "parent_attempt_ids": list(self.parent_attempt_ids),
            "strategy": self.strategy,
            "created_at": self.created_at,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "generation_seconds": self.generation_seconds,
            "estimated_cost_usd": self.estimated_cost_usd,
            "metadata": _thaw_json(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProofAttempt":
        return cls(**dict(data))


@dataclass(frozen=True)
class VerificationRecord:
    outcome: AttemptOutcome | str
    checked_at: str
    verifier: str
    verifier_version: str
    verification_scope: str
    duration_seconds: float
    command: tuple[str, ...] | list[str]
    returncode: int | None
    stdout: str
    stderr: str
    axioms: tuple[str, ...] | list[str]
    allowed_axioms: tuple[str, ...] | list[str]
    policy_issues: tuple[str, ...] | list[str]
    wrapper_sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "outcome", AttemptOutcome(self.outcome))
        finite_number(self.duration_seconds, "duration_seconds", minimum=0)
        if self.returncode is not None and type(self.returncode) is not int:
            raise ValueError("returncode must be an integer or null, never bool")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("Verification duration_seconds must be finite and nonnegative")
        object.__setattr__(self, "command", _string_tuple(self.command, "command"))
        object.__setattr__(self, "axioms", _string_tuple(self.axioms, "axioms"))
        object.__setattr__(
            self,
            "allowed_axioms",
            _string_tuple(self.allowed_axioms, "allowed_axioms"),
        )
        object.__setattr__(
            self,
            "policy_issues",
            _string_tuple(self.policy_issues, "policy_issues"),
        )
        _require_sha256(self.wrapper_sha256, "wrapper_sha256", allow_empty=True)
        if self.outcome == AttemptOutcome.VERIFIED:
            if self.returncode != 0 or not self.wrapper_sha256:
                raise ValueError("A VERIFIED record requires returncode=0 and a wrapper hash")
            if self.verification_scope != "lean-kernel/exact-obligation-statement":
                raise ValueError("VERIFIED requires the exact obligation verification scope")
            if not self.verifier or not self.verifier_version:
                raise ValueError("VERIFIED requires verifier identity and version")
            if set(self.axioms) - set(self.allowed_axioms) or any(
                name == "sorryAx" or name.endswith(".sorryAx") for name in self.axioms
            ):
                raise ValueError("VERIFIED cannot depend on unauthorized axioms or sorryAx")
            if any(
                not issue.startswith("Could not remove temporary verification wrapper:")
                for issue in self.policy_issues
            ):
                raise ValueError("VERIFIED cannot contain fatal policy issues")

    @property
    def verified(self) -> bool:
        return self.outcome == AttemptOutcome.VERIFIED

    def to_dict(self) -> dict[str, Any]:
        self.__post_init__()
        return {
            "outcome": self.outcome.value,
            "verified": self.verified,
            "checked_at": self.checked_at,
            "verifier": self.verifier,
            "verifier_version": self.verifier_version,
            "verification_scope": self.verification_scope,
            "duration_seconds": self.duration_seconds,
            "command": list(self.command),
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "axioms": list(self.axioms),
            "allowed_axioms": list(self.allowed_axioms),
            "policy_issues": list(self.policy_issues),
            "wrapper_sha256": self.wrapper_sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VerificationRecord":
        payload = dict(data)
        if "verified" not in payload:
            raise ValueError("Verification record is missing required field: verified")
        declared_verified = payload.pop("verified")
        record = cls(**payload)
        if type(declared_verified) is not bool or declared_verified is not record.verified:
            raise ValueError(
                f"Verification outcome {record.outcome.value} contradicts verified={declared_verified}"
            )
        return record


@dataclass(frozen=True)
class AttemptReceipt:
    """Hash-bound, machine-readable result for one proof attempt."""

    proof_map_path: str
    proof_map_sha256: str
    proof_map_source_sha256: str
    target_node_id: str
    target_snapshot_sha256: str
    obligation_sha256: str
    artifact_sha256: str
    obligation: FormalObligation
    attempt: ProofAttempt
    verification: VerificationRecord
    receipt_sha256: str = ""
    schema_version: str = "1.0"
    semantic_caveat: str = (
        "Kernel verification establishes the encoded Lean statement only; it does not establish "
        "equivalence to the intended natural-language problem, novelty, or significance."
    )

    def __post_init__(self) -> None:
        self._validate_integrity(set_receipt_hash=True)

    def _integrity_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "proof_map_path": self.proof_map_path,
            "proof_map_sha256": self.proof_map_sha256,
            "proof_map_source_sha256": self.proof_map_source_sha256,
            "target_node_id": self.target_node_id,
            "target_snapshot_sha256": self.target_snapshot_sha256,
            "obligation_sha256": self.obligation_sha256,
            "artifact_sha256": self.artifact_sha256,
            "obligation": self.obligation.to_dict(),
            "attempt": self.attempt.to_dict(),
            "verification": self.verification.to_dict(),
            "semantic_caveat": self.semantic_caveat,
        }

    def _validate_integrity(self, *, set_receipt_hash: bool = False) -> None:
        self.verification.__post_init__()
        if self.verification.verified:
            if set(self.verification.allowed_axioms) != set(self.obligation.allowed_axioms):
                raise ValueError("Receipt axiom policy does not match obligation")
            if _toolchain_version_issue(
                self.obligation.toolchain, self.verification.verifier_version
            ):
                raise ValueError("Receipt toolchain mismatch")
        if self.schema_version != "1.0":
            raise ValueError(f"Unsupported attempt receipt schema_version: {self.schema_version}")
        for name in (
            "proof_map_sha256",
            "target_snapshot_sha256",
            "obligation_sha256",
            "artifact_sha256",
        ):
            _require_sha256(getattr(self, name), name)
        _require_sha256(
            self.proof_map_source_sha256,
            "proof_map_source_sha256",
            allow_empty=True,
        )
        if self.target_node_id != self.obligation.target_node_id:
            raise ValueError("Receipt target_node_id does not match the formal obligation")
        if self.attempt.obligation_id != self.obligation.id:
            raise ValueError("Receipt attempt does not reference the embedded formal obligation")
        if self.artifact_sha256 != self.attempt.artifact_sha256:
            raise ValueError("Receipt artifact hash does not match the embedded proof attempt")
        expected_obligation_hash = canonical_sha256(self.obligation.to_dict())
        if self.obligation_sha256 != expected_obligation_hash:
            raise ValueError("Receipt obligation hash does not match the embedded obligation")
        if tuple(self.verification.allowed_axioms) != tuple(self.obligation.allowed_axioms):
            raise ValueError("Verification allowed_axioms do not match the formal obligation")

        expected_receipt_hash = canonical_sha256(self._integrity_payload())
        if self.receipt_sha256:
            _require_sha256(self.receipt_sha256, "receipt_sha256")
            if self.receipt_sha256 != expected_receipt_hash:
                raise ValueError("Receipt content hash does not match its embedded records")
        elif set_receipt_hash:
            object.__setattr__(self, "receipt_sha256", expected_receipt_hash)
        else:
            raise ValueError("receipt_sha256 is required")

    @property
    def verified(self) -> bool:
        return self.verification.verified

    def to_dict(self) -> dict[str, Any]:
        self._validate_integrity()
        out = self._integrity_payload()
        out["receipt_sha256"] = self.receipt_sha256
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "AttemptReceipt":
        payload = dict(data)
        if not payload.get("receipt_sha256"):
            raise ValueError("receipt_sha256 is required when loading an attempt receipt")
        payload["obligation"] = FormalObligation.from_dict(payload["obligation"])
        payload["attempt"] = ProofAttempt.from_dict(payload["attempt"])
        payload["verification"] = VerificationRecord.from_dict(payload["verification"])
        return cls(**payload)

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(
            self.to_dict(),
            indent=indent,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
        )
        if path is not None:
            output = Path(path)
            output.parent.mkdir(parents=True, exist_ok=True)
            atomic_write(output, text + "\n")
        return text

    @classmethod
    def from_json(cls, path_or_text: str | Path) -> "AttemptReceipt":
        return cls.from_dict(_load_json(path_or_text))


def _lean_name(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_']+", "_", value).strip("_") or "proofmap_attempt"
    if name[0].isdigit():
        name = f"n_{name}"
    return f"proofmap_{name}"


def _strip_lean_comments_and_strings(source: str) -> str:
    """Blank comments and strings so policy checks avoid obvious false positives."""

    chars = list(source)
    i = 0
    block_depth = 0
    in_string = False
    while i < len(chars):
        if block_depth:
            if i + 1 < len(chars) and chars[i] == "/" and chars[i + 1] == "-":
                chars[i] = chars[i + 1] = " "
                block_depth += 1
                i += 2
                continue
            if i + 1 < len(chars) and chars[i] == "-" and chars[i + 1] == "/":
                chars[i] = chars[i + 1] = " "
                block_depth -= 1
                i += 2
                continue
            if chars[i] != "\n":
                chars[i] = " "
            i += 1
            continue

        if in_string:
            if chars[i] == "\\" and i + 1 < len(chars):
                chars[i] = chars[i + 1] = " "
                i += 2
                continue
            if chars[i] == '"':
                chars[i] = " "
                in_string = False
            elif chars[i] != "\n":
                chars[i] = " "
            i += 1
            continue

        if i + 1 < len(chars) and chars[i] == "-" and chars[i + 1] == "-":
            chars[i] = chars[i + 1] = " "
            i += 2
            while i < len(chars) and chars[i] != "\n":
                chars[i] = " "
                i += 1
            continue
        if i + 1 < len(chars) and chars[i] == "/" and chars[i + 1] == "-":
            chars[i] = chars[i + 1] = " "
            block_depth = 1
            i += 2
            continue
        if chars[i] == '"':
            chars[i] = " "
            in_string = True
        i += 1
    return "".join(chars)


def validate_candidate_source(source: str) -> list[str]:
    """Apply the v1 proof-body policy before invoking Lean."""

    stripped = _strip_lean_comments_and_strings(source)
    issues: list[str] = []
    if not re.match(r"^\s*by(?:\s|$)", stripped):
        issues.append("Candidate must be a Lean proof term beginning with 'by'.")
    if "#" in stripped:
        issues.append("Lean command syntax ('#') is forbidden in a candidate proof term.")
    for word in sorted(_FORBIDDEN_CANDIDATE_WORDS):
        if re.search(rf"(?<![A-Za-z0-9_']){re.escape(word)}(?![A-Za-z0-9_'])", stripped):
            issues.append(f"Forbidden Lean construct in candidate: {word}")
    return issues


def render_verification_wrapper(obligation: FormalObligation, candidate_source: str) -> str:
    """Build the exact theorem that Lean will kernel-check."""

    lines = ["/- Generated by proofmap Verified Lean Attempt v1. -/"]
    lines.extend(f"import {module}" for module in obligation.imports)
    if obligation.imports:
        lines.append("")
    lines.append("set_option autoImplicit false")
    lines.append(
        f"theorem {obligation.declaration_name} : ({normalize_statement(obligation.statement)}) :="
    )
    lines.extend(
        f"  {line}" if line else "" for line in candidate_source.replace("\r\n", "\n").split("\n")
    )
    lines.append("")
    lines.append(f"#print axioms {obligation.declaration_name}")
    lines.append("")
    return "\n".join(lines)


def parse_lean_axioms(output: str, declaration_name: str | None = None) -> list[str] | None:
    """Parse Lean 4's ``#print axioms`` response.

    ``None`` means that the compiler succeeded but the expected audit response
    was not found, which is treated as a verifier error rather than a pass.
    """

    events: list[tuple[int, str, set[str]]] = []
    for match in _AXIOM_LIST_RE.finditer(output):
        events.append(
            (
                match.start(),
                match.group(1).strip("'"),
                {item.strip() for item in match.group(2).split(",") if item.strip()},
            )
        )
    for match in _NO_AXIOMS_RE.finditer(output):
        events.append((match.start(), match.group(1).strip("'"), set()))
    if not events:
        return None
    events.sort(key=lambda item: item[0])
    selected_name = declaration_name or events[0][1]
    selected = [axioms for _offset, name, axioms in events if name == selected_name]
    if not selected:
        return None
    # Union every same-declaration report. This is deliberately fail-closed if
    # a tactic emits a forged log line before the generated #print audit.
    return sorted(set().union(*selected))


def _toolchain_version_issue(toolchain: str, verifier_version: str) -> str:
    match = _LEAN_TOOLCHAIN_RE.fullmatch(toolchain)
    if not match:  # FormalObligation rejects this; keep the verifier fail-closed.
        return f"Unrecognized pinned Lean toolchain: {toolchain}."
    expected = match.group(1)
    if re.search(rf"\bversion\s+{re.escape(expected)}\b", verifier_version, re.IGNORECASE):
        return ""
    return f"Lean toolchain mismatch: obligation requires {toolchain}, verifier reported {verifier_version or 'unknown version'}."


def _lean_version(lean: str, project_root: Path) -> tuple[str, str]:
    try:
        completed = subprocess.run(
            [lean, "--version"],
            cwd=str(project_root),
            text=True,
            capture_output=True,
            timeout=15.0,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc)
    combined = "\n".join(part for part in (completed.stdout, completed.stderr) if part).strip()
    if completed.returncode != 0:
        return "", combined or f"Lean --version exited with status {completed.returncode}."
    if not combined:
        return "", "Lean --version returned no version information."
    lines = combined.splitlines()
    version_line = next(
        (line for line in lines if re.search(r"\bLean\b.*\bversion\b", line, re.IGNORECASE)),
        lines[0],
    )
    return version_line, ""


def _receipt(
    *,
    map_path: Path | None,
    proof_map_sha256: str,
    proof_map_source_sha256: str,
    target_snapshot_sha256: str,
    obligation: FormalObligation,
    attempt: ProofAttempt,
    artifact_sha256: str,
    verification: VerificationRecord,
) -> AttemptReceipt:
    return AttemptReceipt(
        proof_map_path=str(map_path.resolve()) if map_path is not None else "",
        proof_map_sha256=proof_map_sha256,
        proof_map_source_sha256=proof_map_source_sha256,
        target_node_id=obligation.target_node_id,
        target_snapshot_sha256=target_snapshot_sha256,
        obligation_sha256=canonical_sha256(obligation.to_dict()),
        artifact_sha256=artifact_sha256,
        obligation=obligation,
        attempt=attempt,
        verification=verification,
    )


def check_proof_attempt(
    proof_map: ProofMap,
    obligation: FormalObligation,
    attempt: ProofAttempt,
    *,
    map_path: str | Path | None = None,
    project_root: str | Path = ".",
    lean_executable: str | None = None,
    timeout: float = 60.0,
) -> AttemptReceipt:
    """Check one proof term and return a durable verification receipt.

    The source ``proof_map`` is never modified.  A successful result proves
    only the exact Lean statement stored in ``obligation``.
    """

    # Reconstruct immutable, validated snapshots so callers cannot mutate an
    # obligation or attempt while the external verifier is running.
    obligation = FormalObligation.from_dict(obligation.to_dict())
    attempt = ProofAttempt.from_dict(attempt.to_dict())
    if obligation.target_node_id not in proof_map.nodes:
        raise ValueError(f"Unknown proof-map target node: {obligation.target_node_id}")
    if attempt.obligation_id != obligation.id:
        raise ValueError(
            f"Attempt {attempt.id} references obligation {attempt.obligation_id}, "
            f"not {obligation.id}"
        )
    if timeout <= 0:
        raise ValueError("Verification timeout must be positive")

    map_snapshot = proof_map.to_dict()
    proof_map_hash = canonical_sha256(map_snapshot)
    target_snapshot_hash = canonical_sha256(proof_map.nodes[obligation.target_node_id].to_dict())
    resolved_map_path = Path(map_path).resolve() if map_path is not None else None
    proof_map_source_hash = ""
    if resolved_map_path is not None:
        if not resolved_map_path.is_file():
            raise FileNotFoundError(f"Proof-map source file not found: {resolved_map_path}")
        source_bytes = resolved_map_path.read_bytes()
        proof_map_source_hash = sha256_bytes(source_bytes)
        source_data = json.loads(source_bytes.decode("utf-8"))
        source_map = ProofMap.from_dict(source_data)
        if canonical_sha256(source_map.to_dict()) != proof_map_hash:
            raise ValueError("proof_map object does not match the supplied map_path snapshot")

    root = Path(project_root).resolve()
    if not root.is_dir():
        raise ValueError(f"Project root is not a directory: {root}")
    artifact = Path(attempt.artifact_path).expanduser()
    if not artifact.is_absolute():
        artifact = root / artifact
    artifact = artifact.resolve()
    if not artifact.is_file():
        raise FileNotFoundError(f"Proof-attempt artifact not found: {artifact}")

    artifact_bytes = artifact.read_bytes()
    artifact_hash = sha256_bytes(artifact_bytes)
    candidate_source = artifact_bytes.decode("utf-8")
    if attempt.artifact_sha256 and attempt.artifact_sha256 != artifact_hash:
        raise ValueError(
            f"Artifact hash mismatch for attempt {attempt.id}: "
            f"expected {attempt.artifact_sha256}, got {artifact_hash}"
        )
    bound_attempt = replace(attempt, artifact_path=str(artifact), artifact_sha256=artifact_hash)
    policy_issues = validate_candidate_source(candidate_source)

    def finish(verification: VerificationRecord) -> AttemptReceipt:
        return _receipt(
            map_path=resolved_map_path,
            proof_map_sha256=proof_map_hash,
            proof_map_source_sha256=proof_map_source_hash,
            target_snapshot_sha256=target_snapshot_hash,
            obligation=obligation,
            attempt=bound_attempt,
            artifact_sha256=artifact_hash,
            verification=verification,
        )

    if policy_issues:
        verification = VerificationRecord(
            outcome=AttemptOutcome.POLICY_REJECTED,
            checked_at=utc_now(),
            verifier="proofmap-static-policy-v1",
            verifier_version="1",
            verification_scope="lean-proof-term/static-policy",
            duration_seconds=0.0,
            command=[],
            returncode=None,
            stdout="",
            stderr="",
            axioms=[],
            allowed_axioms=list(obligation.allowed_axioms),
            policy_issues=policy_issues,
            wrapper_sha256="",
        )
        return finish(verification)

    wrapper_source = render_verification_wrapper(obligation, candidate_source)
    wrapper_hash = sha256_text(wrapper_source)
    lean = resolve_lean_executable(lean_executable)
    if lean is None:
        verification = VerificationRecord(
            outcome=AttemptOutcome.VERIFIER_UNAVAILABLE,
            checked_at=utc_now(),
            verifier="lean4",
            verifier_version="",
            verification_scope="lean-kernel/exact-obligation-statement",
            duration_seconds=0.0,
            command=[],
            returncode=None,
            stdout="",
            stderr="Lean executable not found. Install elan/Lean or set PROOFMAP_LEAN.",
            axioms=[],
            allowed_axioms=list(obligation.allowed_axioms),
            policy_issues=[],
            wrapper_sha256=wrapper_hash,
        )
        return finish(verification)

    version, version_error = _lean_version(lean, root)
    if version_error:
        verification = VerificationRecord(
            outcome=AttemptOutcome.VERIFIER_UNAVAILABLE,
            checked_at=utc_now(),
            verifier=lean,
            verifier_version="",
            verification_scope="lean-kernel/exact-obligation-statement",
            duration_seconds=0.0,
            command=[lean, "--version"],
            returncode=None,
            stdout="",
            stderr=version_error,
            axioms=[],
            allowed_axioms=obligation.allowed_axioms,
            policy_issues=["Lean toolchain preflight failed; the candidate was not compiled."],
            wrapper_sha256=wrapper_hash,
        )
        return finish(verification)

    toolchain_issue = _toolchain_version_issue(obligation.toolchain, version)
    if toolchain_issue:
        verification = VerificationRecord(
            outcome=AttemptOutcome.VERIFIER_ERROR,
            checked_at=utc_now(),
            verifier=lean,
            verifier_version=version,
            verification_scope="lean-kernel/exact-obligation-statement",
            duration_seconds=0.0,
            command=[lean, "--version"],
            returncode=None,
            stdout="",
            stderr="",
            axioms=[],
            allowed_axioms=obligation.allowed_axioms,
            policy_issues=[toolchain_issue],
            wrapper_sha256=wrapper_hash,
        )
        return finish(verification)

    wrapper_path: Path | None = None
    result: LeanCheckResult | None = None
    cleanup_issue = ""
    started = time.perf_counter()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            suffix=".lean",
            prefix=".proofmap_attempt_",
            dir=root,
            delete=False,
        ) as handle:
            handle.write(wrapper_source)
            wrapper_path = Path(handle.name)
        result = check_lean_file(wrapper_path, lean_executable=lean, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        duration = time.perf_counter() - started
        verification = VerificationRecord(
            outcome=AttemptOutcome.VERIFIER_ERROR,
            checked_at=utc_now(),
            verifier=lean,
            verifier_version=version,
            verification_scope="lean-kernel/exact-obligation-statement",
            duration_seconds=duration,
            command=[],
            returncode=None,
            stdout="",
            stderr=str(exc),
            axioms=[],
            allowed_axioms=list(obligation.allowed_axioms),
            policy_issues=[],
            wrapper_sha256=wrapper_hash,
        )
    finally:
        if wrapper_path is not None:
            try:
                wrapper_path.unlink(missing_ok=True)
            except OSError as exc:
                cleanup_issue = f"Could not remove temporary verification wrapper: {exc}"

    if result is not None:
        duration = time.perf_counter() - started
        combined_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
        axioms = (
            parse_lean_axioms(combined_output, obligation.declaration_name) if result.ok else []
        )
        issues: list[str] = [cleanup_issue] if cleanup_issue else []
        if result.returncode == -1 and "timed out" in result.stderr.lower():
            outcome = AttemptOutcome.TIMEOUT
        elif not result.ok:
            outcome = AttemptOutcome.COMPILER_REJECTED
        elif axioms is None:
            outcome = AttemptOutcome.VERIFIER_ERROR
            axioms = []
            issues.append("Lean succeeded but proofmap could not parse the #print axioms audit.")
        else:
            untrusted = sorted(set(axioms).difference(obligation.allowed_axioms))
            if any(name == "sorryAx" or name.endswith(".sorryAx") for name in axioms):
                untrusted = sorted(set(untrusted).union({"sorryAx"}))
            if untrusted:
                outcome = AttemptOutcome.UNTRUSTED_AXIOMS
                issues.append(f"Proof depends on unauthorized axioms: {', '.join(untrusted)}")
            else:
                outcome = AttemptOutcome.VERIFIED
        verification = VerificationRecord(
            outcome=outcome,
            checked_at=utc_now(),
            verifier=lean,
            verifier_version=version,
            verification_scope="lean-kernel/exact-obligation-statement",
            duration_seconds=duration,
            command=result.command,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            axioms=list(axioms),
            allowed_axioms=list(obligation.allowed_axioms),
            policy_issues=issues,
            wrapper_sha256=wrapper_hash,
        )
    elif cleanup_issue:
        verification = replace(
            verification,
            policy_issues=tuple(verification.policy_issues) + (cleanup_issue,),
        )

    return finish(verification)
