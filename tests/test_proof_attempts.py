import json
from dataclasses import FrozenInstanceError
from pathlib import Path

import jsonschema
import pytest

import proofmap.attempts as attempts_module
from proofmap.attempts import (
    AttemptOutcome,
    AttemptReceipt,
    FormalObligation,
    ProofAttempt,
    check_proof_attempt,
    parse_lean_axioms,
    validate_candidate_source,
)
from proofmap.cli import build_parser
from proofmap.examples import build_minimal_conops_map
from proofmap.lean_check import LeanCheckResult, resolve_lean_executable

TARGET = "boundary.drag_residual"


def _obligation(**overrides) -> FormalObligation:
    values = {
        "id": "obligation.reflexivity",
        "target_node_id": TARGET,
        "statement": "∀ n : Nat, n = n",
        "toolchain": "leanprover/lean4:v4.30.0",
        "declaration_name": "proofmap_reflexivity",
    }
    values.update(overrides)
    return FormalObligation(**values)


def _attempt(path: Path, **overrides) -> ProofAttempt:
    values = {
        "id": "attempt.reflexivity.1",
        "obligation_id": "obligation.reflexivity",
        "artifact_path": str(path),
        "producer": "test-worker",
        "provider": "local",
        "model": "test-model",
        "run_id": "run-1",
        "input_tokens": 12,
        "output_tokens": 8,
    }
    values.update(overrides)
    return ProofAttempt(**values)


def _mock_lean(
    monkeypatch: pytest.MonkeyPatch, *, returncode: int = 0, output: str | None = None
) -> None:
    monkeypatch.setattr(attempts_module, "resolve_lean_executable", lambda _: "lean-test")
    monkeypatch.setattr(
        attempts_module,
        "_lean_version",
        lambda _lean, _root: ("Lean (version 4.30.0, test build)", ""),
    )

    def fake_check(path, *, lean_executable=None, timeout=60.0):
        stdout = output
        if stdout is None:
            stdout = "'proofmap_reflexivity' does not depend on any axioms"
        return LeanCheckResult(
            path=Path(path),
            command=[str(lean_executable), str(path)],
            returncode=returncode,
            stdout=stdout,
            stderr="compiler error" if returncode else "",
        )

    monkeypatch.setattr(attempts_module, "check_lean_file", fake_check)


def test_formal_obligation_hash_is_immutable(tmp_path: Path):
    obligation = _obligation()
    assert len(obligation.statement_sha256) == 64

    path = tmp_path / "obligation.json"
    obligation.to_json(path)
    loaded = FormalObligation.from_json(path)
    assert loaded == obligation

    with pytest.raises(ValueError, match="Statement hash mismatch"):
        _obligation(statement_sha256="0" * 64)
    with pytest.raises(ValueError, match="pinned release"):
        _obligation(toolchain="latest")
    with pytest.raises(FrozenInstanceError):
        obligation.statement = "False"  # type: ignore[misc]


def test_candidate_policy_rejects_placeholders_but_ignores_comments():
    issues = validate_candidate_source("by\n  sorry")
    assert "Forbidden Lean construct in candidate: sorry" in issues
    assert (
        validate_candidate_source("by\n  -- mentioning sorry in a comment is harmless\n  rfl") == []
    )
    assert validate_candidate_source("rfl") == [
        "Candidate must be a Lean proof term beginning with 'by'."
    ]
    assert (
        "Lean command syntax ('#') is forbidden"
        in validate_candidate_source('by\n  rfl\n#eval IO.println "fake audit"')[0]
    )


def test_verified_attempt_records_provenance_and_does_not_mutate_map(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _mock_lean(monkeypatch)
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    proof_map = build_minimal_conops_map()
    before = proof_map.to_json()

    receipt = check_proof_attempt(
        proof_map,
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )

    assert receipt.verified
    assert receipt.verification.outcome == AttemptOutcome.VERIFIED
    assert receipt.verification.verifier_version == "Lean (version 4.30.0, test build)"
    assert receipt.attempt.model == "test-model"
    assert receipt.attempt.artifact_sha256 == receipt.artifact_sha256
    assert receipt.target_snapshot_sha256
    assert len(receipt.receipt_sha256) == 64
    assert proof_map.to_json() == before

    receipt_path = tmp_path / "receipt.json"
    receipt.to_json(receipt_path)
    assert AttemptReceipt.from_json(receipt_path).to_dict() == receipt.to_dict()


def test_static_rejection_happens_before_lean_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  admit\n", encoding="utf-8")

    def should_not_resolve(_):
        raise AssertionError("Lean must not run for a policy-rejected artifact")

    monkeypatch.setattr(attempts_module, "resolve_lean_executable", should_not_resolve)
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )
    assert receipt.verification.outcome == AttemptOutcome.POLICY_REJECTED
    assert not receipt.verified


def test_untrusted_axiom_blocks_verification(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _mock_lean(
        monkeypatch,
        output="'proofmap_reflexivity' depends on axioms: [Classical.choice]",
    )
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )
    assert receipt.verification.outcome == AttemptOutcome.UNTRUSTED_AXIOMS, (
        receipt.verification.stdout + receipt.verification.stderr
    )
    assert receipt.verification.axioms == ("Classical.choice",)
    assert "unauthorized axioms" in receipt.verification.policy_issues[0]


def test_forged_same_name_audit_cannot_hide_real_axioms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _mock_lean(
        monkeypatch,
        output=(
            "'proofmap_reflexivity' depends on axioms: []\n"
            "'proofmap_reflexivity' depends on axioms: [Classical.choice]"
        ),
    )
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )
    assert receipt.verification.outcome == AttemptOutcome.UNTRUSTED_AXIOMS
    assert receipt.verification.axioms == ("Classical.choice",)


def test_explicitly_allowed_axiom_can_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _mock_lean(
        monkeypatch,
        output="'proofmap_reflexivity' depends on axioms: [Classical.choice]",
    )
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(allowed_axioms=["Classical.choice"]),
        _attempt(candidate),
        project_root=tmp_path,
    )
    assert receipt.verification.outcome == AttemptOutcome.VERIFIED


def test_compiler_failure_and_artifact_hash_mismatch_are_distinct(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _mock_lean(monkeypatch, returncode=1, output="")
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  exact missing_name\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )
    assert receipt.verification.outcome == AttemptOutcome.COMPILER_REJECTED
    assert receipt.verification.stderr == "compiler error"

    with pytest.raises(ValueError, match="Artifact hash mismatch"):
        check_proof_attempt(
            build_minimal_conops_map(),
            _obligation(),
            _attempt(candidate, artifact_sha256="0" * 64),
            project_root=tmp_path,
        )


def test_timeout_writes_a_distinct_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _mock_lean(monkeypatch)

    def timed_out(path, *, lean_executable=None, timeout=60.0):
        return LeanCheckResult(
            path=Path(path),
            command=[str(lean_executable), str(path)],
            returncode=-1,
            stdout="partial verifier output",
            stderr=f"Lean check timed out after {timeout:g}s.",
        )

    monkeypatch.setattr(attempts_module, "check_lean_file", timed_out)
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
        timeout=0.01,
    )
    assert receipt.verification.outcome == AttemptOutcome.TIMEOUT
    assert receipt.verification.stdout == "partial verifier output"


def test_unknown_target_is_rejected_before_verification(tmp_path: Path):
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  trivial\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown proof-map target node"):
        check_proof_attempt(
            build_minimal_conops_map(),
            _obligation(target_node_id="missing.target"),
            _attempt(candidate),
            project_root=tmp_path,
        )


def test_axiom_parser_is_fail_closed():
    assert parse_lean_axioms("foo does not depend on any axioms") == []
    assert parse_lean_axioms("foo depends on axioms: [propext, Quot.sound]") == [
        "Quot.sound",
        "propext",
    ]
    assert parse_lean_axioms("unexpected successful output") is None
    spoofed = "target depends on axioms: []\ntarget depends on axioms: [sorryAx]"
    assert parse_lean_axioms(spoofed, "target") == ["sorryAx"]
    assert parse_lean_axioms(spoofed, "missing") is None


def test_receipt_rejects_tampering_and_contradictory_verdict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _mock_lean(monkeypatch)
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )
    payload = json.loads(receipt.to_json())
    payload["attempt"]["model"] = "tampered-model"
    with pytest.raises(ValueError, match="Receipt content hash"):
        AttemptReceipt.from_dict(payload)

    payload = json.loads(receipt.to_json())
    payload["verification"]["verified"] = False
    with pytest.raises(ValueError, match="contradicts"):
        AttemptReceipt.from_dict(payload)

    payload = json.loads(receipt.to_json())
    payload["artifact_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="artifact hash"):
        AttemptReceipt.from_dict(payload)


def test_emitted_records_validate_against_json_schemas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    obligation = _obligation()
    formal_schema = json.loads(
        Path("schema/formal_obligation.schema.json").read_text(encoding="utf-8")
    )
    receipt_schema = json.loads(
        Path("schema/proof_attempt.schema.json").read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator.check_schema(formal_schema)
    jsonschema.Draft202012Validator.check_schema(receipt_schema)
    jsonschema.validate(obligation.to_dict(), formal_schema)

    _mock_lean(monkeypatch)
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        obligation,
        _attempt(candidate),
        project_root=tmp_path,
    )
    payload = receipt.to_dict()
    jsonschema.validate(payload, receipt_schema)
    payload["verification"]["verified"] = False
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, receipt_schema)


def test_verifier_preflight_failure_is_not_labeled_as_candidate_rejection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    monkeypatch.setattr(attempts_module, "resolve_lean_executable", lambda _: "elan-shim")
    monkeypatch.setattr(
        attempts_module,
        "_lean_version",
        lambda _lean, _root: ("", "error: toolchain download failed"),
    )

    def should_not_compile(*_args, **_kwargs):
        raise AssertionError("Candidate compilation must not run after failed preflight")

    monkeypatch.setattr(attempts_module, "check_lean_file", should_not_compile)
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )
    assert receipt.verification.outcome == AttemptOutcome.VERIFIER_UNAVAILABLE
    assert "download failed" in receipt.verification.stderr


def test_locked_temporary_wrapper_is_reported_without_losing_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    _mock_lean(monkeypatch)
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    original_unlink = Path.unlink

    def locked_unlink(path: Path, *args, **kwargs):
        if path.name.startswith(".proofmap_attempt_"):
            raise PermissionError("simulated Windows file lock")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", locked_unlink)
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )
    assert receipt.verified
    assert (
        "Could not remove temporary verification wrapper" in receipt.verification.policy_issues[0]
    )

    leftovers = list(tmp_path.glob(".proofmap_attempt_*.lean"))
    monkeypatch.undo()
    for leftover in leftovers:
        leftover.unlink()


def test_map_path_must_match_in_memory_snapshot(tmp_path: Path):
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    map_path = tmp_path / "map.json"
    other = build_minimal_conops_map()
    other.title = "Different snapshot"
    other.to_json(map_path)
    with pytest.raises(ValueError, match="does not match"):
        check_proof_attempt(
            build_minimal_conops_map(),
            _obligation(),
            _attempt(candidate),
            map_path=map_path,
            project_root=tmp_path,
        )


@pytest.mark.parametrize("protected", ["map", "obligation", "candidate"])
def test_cli_refuses_to_overwrite_any_input(tmp_path: Path, protected: str):
    map_path = tmp_path / "map.json"
    obligation_path = tmp_path / "obligation.json"
    candidate_path = tmp_path / "candidate.lean"
    build_minimal_conops_map().to_json(map_path)
    _obligation().to_json(obligation_path)
    candidate_path.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    paths = {"map": map_path, "obligation": obligation_path, "candidate": candidate_path}
    before = paths[protected].read_bytes()
    args = build_parser().parse_args(
        [
            "attempt-check",
            str(map_path),
            str(obligation_path),
            str(candidate_path),
            "--producer",
            "test",
            "--out",
            str(paths[protected]),
            "--project-root",
            str(tmp_path),
        ]
    )
    assert args.func(args) == 2
    assert paths[protected].read_bytes() == before


def test_declared_toolchain_must_match_actual_verifier(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    _mock_lean(monkeypatch)
    monkeypatch.setattr(
        attempts_module,
        "_lean_version",
        lambda _lean, _root: ("Lean (version 4.29.0, stale build)", ""),
    )
    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate),
        project_root=tmp_path,
    )
    assert receipt.verification.outcome == AttemptOutcome.VERIFIER_ERROR
    assert "toolchain mismatch" in receipt.verification.policy_issues[0].lower()


def test_real_lean_kernel_verifies_exact_statement_when_installed(tmp_path: Path):
    lean = resolve_lean_executable()
    if lean is None:
        pytest.skip("Lean executable is not installed")

    candidate = tmp_path / "candidate.lean"
    candidate.write_text("by\n  intro n\n  rfl\n", encoding="utf-8")
    receipt = check_proof_attempt(
        build_minimal_conops_map(),
        _obligation(),
        _attempt(candidate, producer="pytest-real-lean"),
        project_root=Path.cwd(),
        lean_executable=lean,
        timeout=120.0,
    )
    assert receipt.verified, receipt.verification.stderr or receipt.verification.stdout
    assert receipt.verification.axioms == ()
