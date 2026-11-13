"""Portable isolated re-execution. Historical absolute paths are never read."""

from __future__ import annotations

import tempfile
import uuid
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .attempts import (
    AttemptReceipt,
    canonical_sha256,
    parse_lean_axioms,
    render_verification_wrapper,
)
from .integrity import artifact_digest, atomic_write, digest, rooted_path
from .model import ProofMap
from .runner import Limits, run


def replay_bound_execution(
    event: dict[str, Any],
    binding: dict[str, Any],
    obligation: dict[str, Any],
    candidate: bytes,
    profile: dict[str, Any],
    **authority: Any,
) -> dict[str, Any]:
    """Versioned execution replay uses exactly the same executor as fresh papers.

    The historical receipt reader below remains a content-only compatibility
    operation. It cannot issue execution-role evidence for this strict profile.
    """
    from .attempts import FormalObligation
    from .evidence_records import FormalizationBinding, VerifierProfile
    from .execution import replay_execution

    return replay_execution(
        event,
        FormalizationBinding.from_dict(binding),
        FormalObligation.from_dict(obligation),
        candidate,
        VerifierProfile.from_dict(profile),
        **authority,
    )


def replay(
    receipt: AttemptReceipt,
    artifact_root: Path,
    manifest: dict[str, Any],
    image: str,
    *,
    executable: str = "/usr/local/bin/lean",
) -> dict[str, Any]:
    if (
        set(manifest) != {"schema_version", "candidate", "map", "files"}
        or manifest["schema_version"] != "1.0"
    ):
        raise ValueError("REPLAY_MANIFEST_FIELDS")
    if not executable.startswith("/") or ".." in executable.split("/"):
        raise ValueError("REPLAY_EXECUTABLE_PATH")
    if not isinstance(manifest["files"], dict) or len(manifest["files"]) > 256:
        raise ValueError("REPLAY_INPUT_LIMIT")
    artifacts = {}
    total = 0
    for name, expected_hash in manifest["files"].items():
        source = rooted_path(artifact_root, name)
        if source.stat().st_size > 8_000_000:
            raise ValueError("REPLAY_INPUT_LIMIT")
        raw = source.read_bytes()
        total += len(raw)
        if total > 32_000_000 or artifact_digest(raw) != expected_hash:
            raise ValueError("REPLAY_STALE_OR_OVERSIZE_INPUT")
        artifacts[name] = raw
    if manifest["candidate"] not in artifacts or manifest["map"] not in artifacts:
        raise ValueError("REPLAY_REQUIRED_INPUT_MISSING")
    candidate = artifacts[manifest["candidate"]]
    if artifact_digest(candidate) != receipt.artifact_sha256:
        raise ValueError("REPLAY_CANDIDATE_MISMATCH")
    pm = ProofMap.from_json(artifacts[manifest["map"]].decode("utf-8"))
    if canonical_sha256(pm.to_dict()) != receipt.proof_map_sha256:
        raise ValueError("REPLAY_MAP_MISMATCH")
    wrapper = render_verification_wrapper(receipt.obligation, candidate.decode("utf-8"))
    if artifact_digest(wrapper.encode()) != receipt.verification.wrapper_sha256:
        raise ValueError("REPLAY_WRAPPER_MISMATCH")
    wrapper_name = "proofmap_replay_" + uuid.uuid4().hex + ".lean"
    # Generated snapshot contains only the explicitly bound portable manifest.
    with tempfile.TemporaryDirectory(prefix="proofmap-replay-") as folder:
        source_root = Path(folder)
        source_root.chmod(0o755)
        for name, raw in artifacts.items():
            target = rooted_path(source_root, name)
            atomic_write(target, raw)
            target.chmod(0o644)
        atomic_write(source_root / wrapper_name, wrapper)
        (source_root / wrapper_name).chmod(0o644)
        limits = Limits(seconds=120, memory_mb=2048)
        version = run(image, source_root, (executable, "--version"), limits)
        binary = run(image, source_root, ("/usr/bin/sha256sum", executable), limits)
        expected_version = receipt.obligation.toolchain.rsplit(":v", 1)[1]
        if version.execution_status != "PASS" or binary.execution_status != "PASS":
            result = version if version.execution_status != "PASS" else binary
        elif (
            f"version {expected_version}," not in version.stdout
            and f"version {expected_version})" not in version.stdout
        ):
            raise ValueError("REPLAY_TOOLCHAIN_MISMATCH")
        else:
            result = run(image, source_root, (executable, "/src/" + wrapper_name), limits)
    axioms = (
        parse_lean_axioms(result.stdout + "\n" + result.stderr, receipt.obligation.declaration_name)
        if result.execution_status == "PASS"
        else None
    )
    valid = (
        axioms is not None
        and not set(axioms) - set(receipt.obligation.allowed_axioms)
        and not any(a == "sorryAx" or a.endswith(".sorryAx") for a in axioms)
    )
    event = {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "parent_receipt": receipt.receipt_sha256,
        "outcome": "VERIFIED"
        if valid
        else result.execution_status
        if result.execution_status != "PASS"
        else "VERIFIER_ERROR",
        "execution": asdict(result),
        "axioms": axioms,
        "manifest": manifest,
        "manifest_digest": digest("replay-manifest.v1", manifest),
        "wrapper_sha256": receipt.verification.wrapper_sha256,
        "subject_digest": receipt.obligation_sha256,
        "actual_lean_version": version.stdout,
        "resolved_executable": executable,
        "executable_hash_output": binary.stdout,
        "environment_completeness": "IMAGE_AND_SNAPSHOT",
        "image_digest": image,
        "authentication": "LOCAL_UNSIGNED_EVENT",
        "fidelity": "NOT_ESTABLISHED",
        "semantic_invariants_match": bool(
            valid and tuple(axioms or ()) == receipt.verification.axioms
        ),
    }
    event["event_digest"] = digest("replay-event.v1", event)
    return event
