"""Offline review navigation and immutable, non-authoritative interpretation edits."""

import json
import os
from copy import deepcopy
from importlib.metadata import version
from pathlib import Path

import pytest

from proofmap.cli import main
from proofmap.integrity import canonical_bytes, digest, load_json, write_json
from proofmap.paper import ci, load_bundle
from proofmap.paper_overrides import apply_override, override_export, validate_override_bundle
from proofmap.paper_reports import query_store, report_model, write_reports
from proofmap.paper_store import PaperStore

FIXTURE = Path(__file__).parent / "fixtures" / "papers" / "review_override" / "main.tex"


@pytest.fixture
def reviewed(tmp_path):
    bundle, _ = ci(FIXTURE, tmp_path / "original", tmp_path / "store", paper_id="review-example")
    store = PaperStore(tmp_path / "store")
    try:
        yield bundle, store
    finally:
        store.close()


def draft_for(bundle):
    draft = override_export(bundle, "Local test editor")
    by_id = {row["id"]: row for row in draft["targets"]}
    elements = bundle["document_ir"]["elements"]
    first = next(row["id"] for row in elements if "claim:custom" in row["labels"])
    second = next(row["id"] for row in elements if "claim:second" in row["labels"])
    proof = next(row["id"] for row in elements if row["kind"] == "PROOF")
    for target, kind, value in (
        (first, "role", "LEMMA"),
        (proof, "proof_for", second),
        (second, "dependencies", [first]),
    ):
        binding = by_id[target]
        draft["changes"].append(
            {
                "target": target,
                "kind": kind,
                "scope": binding["scope"],
                "source_digest": binding["source_digest"],
                "value": value,
                "note": "Original fixture editor's explicit interpretation.",
            }
        )
    return draft, first, second, proof


def test_override_recomputes_map_preserves_raw_source_and_history(reviewed, tmp_path):
    bundle, store = reviewed
    before = canonical_bytes(bundle)
    draft, first, second, proof = draft_for(bundle)
    derived = apply_override(bundle, draft, store, tmp_path / "derived")
    assert canonical_bytes(bundle) == before
    assert derived["document_ir"] == bundle["document_ir"]
    assert derived["extraction_events"] == bundle["extraction_events"]
    assert next(a for a in bundle["assertions"] if a["id"] == first)["role"] == "UNRESOLVED"
    assert next(a for a in derived["assertions"] if a["id"] == first)["role"] == "LEMMA"
    assert next(a for a in derived["assertions"] if a["id"] == second)["proof_ids"] == [proof]
    assert any(
        row["conclusion"] == second and row["premises"] == [first]
        for row in derived["argument_map"]["inferences"]
    )
    assert derived["run_manifest"]["analysis_digest"] != bundle["run_manifest"]["analysis_digest"]
    assert derived["run_manifest"]["parent_run_id"] == bundle["run_manifest"]["run_id"]
    assert derived["execution_events"] == derived["acceptance_records"] == []
    assert derived["assessment"]["outcomes"]["coverage"]["accepted_claims"] == 0
    assert canonical_bytes(store.inspect(bundle["run_manifest"]["run_id"])["bundle"]) == before
    assert load_bundle(tmp_path / "derived") == derived
    second_draft = override_export(derived, "Second editor")
    target = next(t for t in second_draft["targets"] if t["id"] == first)
    second_draft["changes"] = [
        {
            "kind": "role",
            "target": first,
            "scope": target["scope"],
            "source_digest": target["source_digest"],
            "value": "PROPOSITION",
            "note": "Revised interpretation.",
        }
    ]
    latest = apply_override(derived, second_draft, store)
    assert len(latest["interpretation_overrides"]) == 2
    assert latest["interpretation_overrides"][0] == derived["interpretation_overrides"][0]
    store.rebuild()
    assert store.inspect(latest["run_manifest"]["run_id"])["bundle"] == latest


@pytest.mark.parametrize(
    "mutation",
    [
        lambda d: d.update(revision="0" * 64),
        lambda d: d.update(run_id="wrong-run"),
        lambda d: d.update(analysis_digest="0" * 64),
        lambda d: d.update(attribution_authenticated=True),
        lambda d: d.update(author=""),
        lambda d: d.update(created_at="2026-10-02T00:00:00"),
        lambda d: d["changes"][0].update(scope="other-scope"),
        lambda d: d["changes"][0].update(source_digest="0" * 64),
        lambda d: d["changes"][0].update(value="ACCEPTED"),
        lambda d: d["changes"][0].update(kind="statement"),
        lambda d: d["changes"][0].update(note=""),
        lambda d: d["changes"].append(deepcopy(d["changes"][0])),
        lambda d: d["changes"][2].update(value=[d["changes"][2]["target"]]),
    ],
)
def test_stale_forged_or_authority_creating_override_is_rejected(reviewed, mutation):
    bundle, store = reviewed
    draft, *_ = draft_for(bundle)
    mutation(draft)
    with pytest.raises(ValueError):
        apply_override(bundle, draft, store)
    assert len(store.list()) == 1


def test_override_rejects_rehashed_derived_tampering_and_existing_output(reviewed, tmp_path):
    bundle, store = reviewed
    draft, *_ = draft_for(bundle)
    with pytest.raises(ValueError, match="OUTPUT_MUST_BE_NEW"):
        apply_override(bundle, draft, store, tmp_path / "original")
    derived = apply_override(bundle, draft, store)
    for component in ("interpreted_ir", "assertions", "execution_events"):
        forged = deepcopy(derived)
        if component == "interpreted_ir":
            forged[component]["elements"][0]["text"] += " forged"
        elif component == "assertions":
            forged[component][0]["status"] = "ACCEPTED"
        else:
            forged[component] = [{"event": {"id": "forged"}}]
        forged["run_manifest"]["bundle_digests"] = {
            name: digest("paper-bundle-component.v1", value)
            for name, value in forged.items()
            if name != "run_manifest"
        }
        with pytest.raises(ValueError):
            validate_override_bundle(forged)


def test_reports_and_query_share_claims_versions_and_safe_source(reviewed, tmp_path):
    bundle, store = reviewed
    draft, first, *_ = draft_for(bundle)
    derived = apply_override(bundle, draft, store)
    indexed = store.inspect(derived["run_manifest"]["run_id"])
    artifacts = {name: store.get(sha) for name, sha in indexed["artifacts"].items()}
    model = write_reports(derived, tmp_path / "reports", artifacts)
    assert model == load_json(tmp_path / "reports" / "report.json")
    sarif = load_json(tmp_path / "reports" / "results.sarif")
    assert model["tool"]["version"] == version("proof-map-boundary-analysis")
    assert sarif["runs"][0]["tool"]["driver"] == model["tool"]
    assert sarif["runs"][0]["properties"]["outcomes"] == model["outcomes"]
    rows = query_store(store, paper="review-example", role="LEMMA", state="AUTHOR_ASSERTED")
    assert [r["assertion"] for r in rows] == [first]
    assert rows[0]["assessment_scope"] == "HISTORICAL_RUN_SNAPSHOT"
    assert query_store(store, revision="0" * 64) == []
    assert query_store(store, state="ACCEPTED_UNDER_POLICY") == []
    assert query_store(store, finding="NO_SUCH_FINDING") == []
    assert all(claim["next_steps"] for claim in model["claims"])


def test_cli_exports_applies_queries_inspects_and_reports(reviewed, tmp_path, capsys):
    bundle, store = reviewed
    store_path = str(tmp_path / "store")
    original = str(tmp_path / "original")
    template = tmp_path / "override.json"
    assert (
        main(
            [
                "paper",
                "override-export",
                original,
                "--author",
                "Fixture editor",
                "--out",
                str(template),
            ]
        )
        == 0
    )
    draft, first, *_ = draft_for(bundle)
    write_json(template, draft)
    assert (
        main(
            [
                "paper",
                "override-apply",
                original,
                str(template),
                "--out",
                str(tmp_path / "derived"),
                "--store",
                store_path,
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        main(
            [
                "paper",
                "query",
                "--store",
                store_path,
                "--paper",
                "review-example",
                "--role",
                "LEMMA",
            ]
        )
        == 0
    )
    query = json.loads(capsys.readouterr().out)
    assert query[0]["assertion"] == first
    assert (
        main(
            [
                "paper",
                "inspect",
                query[0]["run"],
                "--store",
                store_path,
                "--assertion",
                "claim:custom",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["role"] == "LEMMA"
    assert (
        main(
            [
                "paper",
                "report",
                str(tmp_path / "derived"),
                "--store",
                store_path,
                "--out",
                str(tmp_path / "report"),
            ]
        )
        == 0
    )
    assert (tmp_path / "report" / "report.html").is_file()


@pytest.mark.skipif(
    os.environ.get("PROOFMAP_BROWSER_TEST") != "1",
    reason="Select real browser suite with PROOFMAP_BROWSER_TEST=1",
)
def test_browser_navigates_source_context_formal_evidence_reviews_without_scripts(tmp_path):
    from playwright.sync_api import sync_playwright

    source = tmp_path / "unsafe.tex"
    payload = (
        '<script>window.PWNED=1</script><img src=x onerror="window.PWNED=2"> javascript:alert(1)'
    )
    source.write_text(
        r"\begin{theorem}\label{claim:unsafe}" + payload + r"\end{theorem}", encoding="utf-8"
    )
    bundle, _ = ci(source, tmp_path / "out", tmp_path / "store")
    model = report_model(bundle)
    assert model["claims"][0]["source"]["text"].find(payload) >= 0
    markdown = (tmp_path / "out" / "report.md").read_text(encoding="utf-8")
    assert "<script>" not in markdown
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto((tmp_path / "out" / "report.html").as_uri())
        page.locator("details summary").first.focus()
        page.keyboard.press("Enter")
        assert payload in page.locator("body").inner_text()
        for text in ("Source", "Context", "Formal", "Evidence", "Reviews"):
            link = page.get_by_role("navigation", name="Claim details").get_by_role(
                "link", name=text, exact=True
            )
            link.focus()
            page.keyboard.press("Enter")
            assert page.locator(":target h3").inner_text() == text
        assert page.evaluate("window.PWNED") is None
        assert page.locator("script, img, svg").count() == 0
        assert page.locator('a[href^="javascript:"]').count() == 0
        browser.close()
