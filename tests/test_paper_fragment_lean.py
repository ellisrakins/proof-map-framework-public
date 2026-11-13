"""Explicitly opt-in host compiler compatibility; never paper execution evidence."""

import os
import subprocess
from pathlib import Path

import pytest

from proofmap.attempts import parse_lean_axioms
from proofmap.formalize import formalize_document
from proofmap.integrity import load_json
from proofmap.paper_sources import acquire, parse


def test_source_fragment_on_explicit_real_lean_430(tmp_path):
    lean = os.environ.get("PROOFMAP_LEAN")
    if not lean:
        pytest.skip(
            "Host compatibility needs explicit PROOFMAP_LEAN; isolated integration is separate"
        )
    version = subprocess.run([lean, "--version"], capture_output=True, text=True, timeout=15)
    assert version.returncode == 0 and "version 4.30.0," in version.stdout
    corpus = Path("tests/fixtures/papers")
    fixtures = load_json(corpus / "golden.json")["fixtures"]
    expected = {
        (fixture["path"], label)
        for fixture in fixtures
        for label, status in fixture["formalization_status"].items()
        if status == "SUPPORTED"
    }
    expected_rejections = {
        (fixture["path"], label)
        for fixture in fixtures
        for label, equal in fixture.get("exact_identities", {}).items()
        if equal is False
    }
    assert expected and expected_rejections
    checked = set()
    rejected = set()
    for fixture in fixtures:
        manifest, files = acquire(corpus / fixture["path"], fixture.get("entrypoint"))
        ir = parse(manifest, files)
        by_id = {element["id"]: element for element in ir["elements"]}
        for row in formalize_document(ir):
            if row["status"] != "SUPPORTED":
                continue
            source = tmp_path / f"candidate{len(checked)}.lean"
            labels = by_id[row["assertion_id"]]["labels"]
            assert len(labels) == 1
            subject = (fixture["path"], labels[0])
            assert subject not in checked
            source.write_text(
                "import Std\ntheorem ProofMapPolynomial : "
                + row["obligation"]["statement"]
                + " := "
                + row["candidate"]
                + "\n#print axioms ProofMapPolynomial\n",
                encoding="utf-8",
            )
            completed = subprocess.run(
                [lean, str(source)], capture_output=True, text=True, encoding="utf-8", timeout=60
            )
            assert (completed.returncode == 0) is row["exact_check"]["equal"]
            if completed.returncode == 0:
                axioms = parse_lean_axioms(completed.stdout, "ProofMapPolynomial")
                assert axioms is not None
                assert set(axioms) <= {"propext", "Classical.choice", "Quot.sound"}
            else:
                rejected.add(subject)
            checked.add(subject)
    assert checked == expected
    assert rejected == expected_rejections
