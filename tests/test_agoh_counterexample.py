import hashlib
import json
import subprocess
import sys
from pathlib import Path

import jsonschema

from proofmap import ProofMap
from proofmap.attempts import AttemptOutcome, AttemptReceipt, FormalObligation
from proofmap.sources import SourceRegistry

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "research" / "agoh_2026"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_exact_counterexample_certificate_reproduces() -> None:
    completed = subprocess.run(
        [sys.executable, str(CASE / "verify_counterexample.py")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    assert json.loads(completed.stdout) == _json(CASE / "certificate.json")


def test_research_artifacts_validate_and_bind_the_factorization() -> None:
    map_path = CASE / "agoh_counterexample_map.json"
    sources_path = CASE / "agoh_counterexample_sources.json"
    obligation_path = CASE / "agoh_factorization_obligation.json"

    jsonschema.validate(_json(map_path), _json(ROOT / "schema" / "proofmap.schema.json"))
    jsonschema.validate(_json(sources_path), _json(ROOT / "schema" / "source.schema.json"))
    jsonschema.validate(
        _json(obligation_path),
        _json(ROOT / "schema" / "formal_obligation.schema.json"),
    )

    proof_map = ProofMap.from_json(map_path)
    sources = SourceRegistry.from_json(sources_path)
    obligation = FormalObligation.from_json(obligation_path)

    assert obligation.target_node_id == "theorem.n2_factorization"
    assert obligation.target_node_id in proof_map.nodes
    assert obligation.statement_sha256 == (
        "6955e33027111b65ec195df1ab05f9a6eb31a77ebe4d2290f6c91c0d220778b7"
    )
    assert "agoh_2026_a9" in sources.sources
    assert proof_map.nodes["conclusion.only_if_false"].status.value == "DERIVED"


def test_checked_receipt_is_current_and_uses_only_permitted_standard_axioms() -> None:
    map_path = CASE / "agoh_counterexample_map.json"
    candidate_path = CASE / "agoh_factorization_candidate.lean"
    receipt_path = CASE / "agoh_factorization_receipt.json"

    data = _json(receipt_path)
    jsonschema.validate(data, _json(ROOT / "schema" / "proof_attempt.schema.json"))
    receipt = AttemptReceipt.from_json(receipt_path)

    assert receipt.verified
    assert receipt.verification.outcome == AttemptOutcome.VERIFIED
    assert set(receipt.verification.axioms) == {
        "Classical.choice",
        "Quot.sound",
        "propext",
    }
    assert receipt.verification.axioms == receipt.verification.allowed_axioms
    assert "sorryAx" not in receipt.verification.axioms
    assert receipt.target_node_id == "theorem.n2_factorization"
    assert receipt.proof_map_source_sha256 == hashlib.sha256(map_path.read_bytes()).hexdigest()
    assert receipt.artifact_sha256 == hashlib.sha256(candidate_path.read_bytes()).hexdigest()
