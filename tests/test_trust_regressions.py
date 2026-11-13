"""Regression cases written against the audited baseline before fixes."""

import json
from pathlib import Path

import pytest

from proofmap.attempts import AttemptReceipt, VerificationRecord
from proofmap.examples import build_minimal_conops_map
from proofmap.model import ProofMap
from proofmap.surface_visualize import render_surface_explorer_html


def record_payload():
    return dict(
        outcome="VERIFIED",
        verified=True,
        checked_at="2026-09-23T00:00:00Z",
        verifier="lean",
        verifier_version="Lean (version 4.30.0)",
        verification_scope="lean-kernel/exact-obligation-statement",
        duration_seconds=0,
        command=["lean"],
        returncode=0,
        stdout="",
        stderr="",
        axioms=[],
        allowed_axioms=[],
        policy_issues=[],
        wrapper_sha256="a" * 64,
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(verified=None),
        dict(returncode=False),
        dict(axioms=["sorryAx"]),
        dict(axioms=["Other.sorryAx"]),
        dict(axioms=["evil"]),
        dict(policy_issues=["fatal integrity failure"]),
        dict(verification_scope="scaffold"),
    ],
)
def test_f05_verdict_reload_rejects_semantic_forgery(change):
    data = record_payload()
    data.update(change)
    with pytest.raises(ValueError):
        VerificationRecord.from_dict(data)


@pytest.mark.parametrize("number", [True, float("nan"), float("inf")])
def test_f03_map_rejects_invalid_numbers(number):
    data = build_minimal_conops_map().to_dict()
    data["nodes"][0]["proof_cost"] = number
    with pytest.raises(ValueError):
        ProofMap.from_dict(data)


def test_f03_duplicate_json_keys_rejected():
    with pytest.raises(ValueError):
        ProofMap.from_json('{"title":"one","title":"two","nodes":[],"edges":[]}')


def test_f03_long_json_is_not_a_path():
    data = build_minimal_conops_map().to_dict()
    data["description"] = "x" * 10000
    assert ProofMap.from_json(json.dumps(data)).description == data["description"]


def test_f05_empty_stored_receipt_hash_rejected():
    data = json.loads(
        Path("research/agoh_2026/agoh_factorization_receipt.json").read_text(encoding="utf-8")
    )
    data["receipt_sha256"] = ""
    with pytest.raises(ValueError):
        AttemptReceipt.from_dict(data)


def test_f07_inert_script_data(tmp_path):
    pm = build_minimal_conops_map()
    pm.nodes[next(iter(pm.nodes))].label = "</script><script>window.PWNED=1</script>"
    path = tmp_path / "report.html"
    render_surface_explorer_html(pm, path)
    html = path.read_text(encoding="utf-8")
    assert "</script><script>window.PWNED=1" not in html
    assert "innerHTML" not in html
