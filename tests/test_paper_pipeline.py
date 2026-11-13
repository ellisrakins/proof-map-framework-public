from pathlib import Path

import pytest

from proofmap.cli import main
from proofmap.exact_check import equality
from proofmap.paper import ci, diff, review_apply, review_export
from proofmap.paper_store import PaperStore

FIXTURE = Path("tests/fixtures/papers/train/basic.tex")


def test_end_to_end_offline_auto_index_and_review(tmp_path):
    bundle, code = ci(FIXTURE, tmp_path / "out", tmp_path / "store")
    assert code == 0
    assert not bundle["assessment"]["closure"]["closed"]
    assert bundle["assessment"]["outcomes"]["kernel_verification"] == "NOT_RUN"
    assert {p.name for p in (tmp_path / "out").iterdir()} >= {
        "report.html",
        "report.md",
        "results.sarif",
        "argument_map.json",
        "run_manifest.json",
    }
    store = PaperStore(tmp_path / "store")
    try:
        records = store.list()
        assert len(records) == 1
        assert (
            store.inspect(records[0]["run"])["bundle"]["input_manifest"]["revision"]
            == bundle["input_manifest"]["revision"]
        )
        review = review_export(bundle, "Test reviewer")
        review["decisions"][0]["source_fidelity"] = "ACCEPTED"
        assert review_apply(bundle, review, store)
        assert review_apply(bundle, review, store)
        assert store.db.execute("SELECT count(*) FROM reviews").fetchone()[0] == 1
        count = store.db.execute("SELECT count(*) FROM entities").fetchone()[0]
        store.rebuild()
        assert store.db.execute("SELECT count(*) FROM entities").fetchone()[0] == count
        review["decisions"][0]["formal_fidelity"] = "ACCEPTED"
        with pytest.raises(ValueError):
            review_apply(bundle, review, store)
    finally:
        store.close()


def test_revision_definition_change_invalidates_dependents(tmp_path):
    source = tmp_path / "paper.tex"
    source.write_bytes(FIXTURE.read_bytes())
    a, _ = ci(source, tmp_path / "a", tmp_path / "store")
    source.write_text(source.read_text().replace("d(x)=2x", "d(x)=3x"))
    b, _ = ci(source, tmp_path / "b", tmp_path / "store")
    result = diff(a, b)
    assert result["reviews"] == "STALE"
    assert len(result["invalidated_assertions"]) >= 2
    review = review_export(a, "reviewer")
    store = PaperStore(tmp_path / "store")
    try:
        with pytest.raises(ValueError):
            review_apply(b, review, store)
    finally:
        store.close()


def test_exact_manifest_is_separate_from_fidelity_and_missing_formal_fails(tmp_path):
    config = {
        "exact_checks": [{"label": "eq:one", "left": "1+1", "right": "3"}],
        "required_stages": ["formal"],
    }
    b, code = ci(FIXTURE, tmp_path / "out", tmp_path / "store", config=config)
    assert code == 3
    finding = next(f for f in b["findings"] if f["code"] == "CANDIDATE_EXACT_CONTRADICTION")
    assert not finding["blocking_eligible"]


@pytest.mark.parametrize(
    "bad", ["__import__('os')", "x[0]", "True", "x**1000", "1/0", "[1]", "1e100", "x.__class__"]
)
def test_exact_language_rejects_unsafe_or_unbounded(bad):
    with pytest.raises((ValueError, SyntaxError)):
        equality(bad, "0")


def test_exact_polynomial_and_cli(tmp_path):
    assert equality("(x-1)**2", "x*x-2*x+1")
    assert not equality("x*x", "x")
    assert (
        main(
            [
                "paper",
                "ci",
                str(FIXTURE),
                "--out",
                str(tmp_path / "out"),
                "--store",
                str(tmp_path / "store"),
            ]
        )
        == 0
    )
    assert main(["paper", "list", "--store", str(tmp_path / "store")]) == 0
    assert (
        main(["closure", "examples/minimal_conops.json", "--target", "boundary.drag_residual"]) == 1
    )


def test_empty_assertion_coverage_is_unknown(tmp_path):
    source = tmp_path / "prose.tex"
    source.write_text("This is only prose, not an extracted theorem.")
    b, _ = ci(source, tmp_path / "out", tmp_path / "store")
    assert b["assessment"]["outcomes"]["coverage"]["kernel_verified_fraction"] is None
