"""Paper integration regressions; actual isolated execution lives in the mandatory job."""

from pathlib import Path

import pytest

from proofmap.integrity import artifact_digest
from proofmap.paper import ci, diff


def manuscript(tmp_path: Path, body: str | None = None) -> Path:
    source = tmp_path / "new-paper.tex"
    source.write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}\label{identity}"
        + (body or r"For every $x\in\mathbb{Z}$, \[(x+1)^2=x^2+2x+1.\]")
        + r"\end{theorem}\end{document}",
        encoding="utf-8",
    )
    return source


def test_source_formalization_without_infrastructure_still_indexes(tmp_path):
    source = manuscript(tmp_path)
    bundle, code = ci(source, tmp_path / "out", tmp_path / "store", require_formal=True)
    assert code == 3
    coverage = bundle["assessment"]["outcomes"]["coverage"]
    assert coverage["authored_assertions"] == 1
    assert coverage["supported_formal_obligations"] == 1
    assert coverage["kernel_verified"] == coverage["accepted_claims"] == 0
    assert bundle["formalizations"][0]["status"] == "SUPPORTED"
    assert bundle["assessment"]["outcomes"]["formal_compilation"] == "UNAVAILABLE"
    assert bundle["assertions"][0]["status"] == "AUTHOR_ASSERTED"


def test_same_revision_resume_reuses_parse_without_trusting_acceptance(tmp_path, monkeypatch):
    source = manuscript(tmp_path)
    first, _ = ci(source, tmp_path / "first", tmp_path / "store")

    def should_not_parse(*args, **kwargs):
        raise AssertionError("identical parsing should be cached")

    monkeypatch.setattr("proofmap.paper.parse", should_not_parse)
    second, _ = ci(source, tmp_path / "second", tmp_path / "store", resume=True)
    assert first["assertions"] == second["assertions"]
    assert second["run_manifest"]["cache_provenance"]["reused_stages"]
    assert not second["assessment"]["outcomes"]["coverage"]["accepted_claims"]


def test_parser_timeout_is_not_a_reusable_success(tmp_path, monkeypatch):
    from proofmap.paper_sources import parse as original

    calls = []

    def first_timeout(*args, **kwargs):
        calls.append(True)
        result = original(*args, **kwargs)
        if len(calls) == 1:
            result["parser"]["execution"] = "TIMEOUT"
            result["status"] = "PARTIAL"
        return result

    monkeypatch.setattr("proofmap.paper.parse", first_timeout)
    source = manuscript(tmp_path)
    _, first = ci(source, tmp_path / "timeout", tmp_path / "store")
    assert first == 3
    second, code = ci(source, tmp_path / "resumed", tmp_path / "store", resume=True)
    assert code == 0 and len(calls) == 2
    assert not second["run_manifest"]["cache_provenance"]["reused_stages"]


def test_assumption_revision_invalidates_unchanged_displayed_equation(tmp_path):
    source = manuscript(tmp_path)
    old, _ = ci(source, tmp_path / "old", tmp_path / "store")
    source.write_text(
        source.read_text().replace(r"\begin{theorem}", "Assume x is positive.\\begin{theorem}")
    )
    new, _ = ci(source, tmp_path / "new", tmp_path / "store")
    result = diff(old, new)
    assert set(result["invalidated_assertions"]) >= {a["id"] for a in old["assertions"]}
    assert result["invalidation_reasons"]


def test_sarif_utf8_crlf_locations_and_pdf_no_fake_lines():
    from proofmap.paper_reports import physical_location

    raw = "α first\r\nβ theorem\r\n".encode()
    start = len("α first\r\nβ ".encode())
    loc = {
        "artifact": "paper.tex",
        "artifact_sha256": artifact_digest(raw),
        "format": "tex",
        "start": start,
        "end": start + 7,
    }
    result = physical_location(loc, {"paper.tex": raw})
    assert result["region"] == {"startLine": 2, "startColumn": 3, "endLine": 2, "endColumn": 10}
    with pytest.raises(ValueError):
        physical_location({**loc, "start": 1}, {"paper.tex": raw})
    pdf = physical_location({"format": "pdf", "artifact": "paper.pdf", "page": 2}, {})
    assert "region" not in pdf
    assert pdf["properties"]["pdfPage"] == 2


def test_required_partial_stage_needs_explicit_external_permission():
    from proofmap.paper_checkers import make_result, required_failures

    stages = [make_result("model-extraction", "PARTIAL")]
    assert required_failures(stages, ["model-extraction"]) == ["model-extraction"]
    assert not required_failures(stages, ["model-extraction"], allow_partial={"model-extraction"})


def test_approved_author_candidate_changes_exact_binding(tmp_path):
    source = manuscript(tmp_path)
    first, _ = ci(source, tmp_path / "one", tmp_path / "store")
    ident = first["assertions"][0]["id"]
    changed, _ = ci(
        source, tmp_path / "two", tmp_path / "store", candidate_overrides={ident: b"by rfl"}
    )
    assert (
        first["formalizations"][0]["binding"]["id"] != changed["formalizations"][0]["binding"]["id"]
    )
    with pytest.raises(ValueError, match="SUPPORTED_SOURCE"):
        ci(
            source,
            tmp_path / "bad",
            tmp_path / "store",
            candidate_overrides={"wrong-id": b"by rfl"},
        )
    with pytest.raises(ValueError, match="CANDIDATE"):
        ci(
            source,
            tmp_path / "unsafe",
            tmp_path / "store",
            candidate_overrides={ident: b"by sorry"},
        )


def test_candidate_graph_and_atomic_model_chunk_reuse(tmp_path, monkeypatch):
    import json

    from proofmap.extractor import extract as original
    from proofmap.extractor import make_request
    from proofmap.integrity import canonical_bytes, digest

    source = tmp_path / "two.tex"
    source.write_text(
        r"\begin{theorem}\label{first}First.\end{theorem}\begin{theorem}\label{second}Second.\end{theorem}"
    )
    config = {
        "provider": "ollama",
        "endpoint": "http://localhost:11434",
        "model": "test-offline",
        "timeout_seconds": 3,
        "max_output_tokens": 128,
    }
    requests = []

    def protocol(document, config, *, replay=None, **kwargs):
        if replay is not None:
            return original(document, config, replay=replay)
        requests.append(document)
        claims = [e["id"] for e in document["elements"] if e["kind"] == "ASSERTION"]
        raw = json.dumps(
            {
                "done": True,
                "model": "test-offline",
                "message": {
                    "content": json.dumps(
                        {
                            "classifications": [{"element": claims[0], "kind": "ASSERTION"}],
                            "dependencies": [{"conclusion": claims[1], "premises": [claims[0]]}],
                        }
                    )
                },
            }
        )
        return original(
            document,
            config,
            replay={
                "request_sha256": artifact_digest(canonical_bytes(make_request(document, config))),
                "config_digest": digest("extractor-config.v1", config),
                "raw_response": raw,
                "response_sha256": artifact_digest(raw.encode()),
            },
        )

    monkeypatch.setattr("proofmap.paper.extract", protocol)
    first, code = ci(
        source,
        tmp_path / "one",
        tmp_path / "store",
        extractor="configured",
        config={"extractor": config},
    )
    assert code == 0
    assert first["argument_map"]["relations"][0]["kind"] == "MODEL_INFERRED_DEPENDENCY"
    assert not first["assessment"]["closure"]["closed"]
    second, code = ci(
        source,
        tmp_path / "two",
        tmp_path / "store",
        extractor="configured",
        config={"extractor": config},
        resume=True,
    )
    assert code == 0 and len(requests) == 1
    assert first["semantic_overlay"] == second["semantic_overlay"]
    assert len(second["run_manifest"]["cache_provenance"]["reused_stages"]) == 2


def test_simulated_worker_full_review_cli_and_revocation(tmp_path, monkeypatch):
    """Contract-only simulation; this test does not claim actual Lean isolation."""
    import base64
    from copy import deepcopy

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    from proofmap.cli import main
    from proofmap.evidence_records import VerifierProfile
    from proofmap.execution import CHECKER_DIGEST
    from proofmap.integrity import canonical_bytes, load_json, write_json
    from proofmap.paper_evidence import (
        apply_fidelity,
        reassess,
        report_assessment,
        sign_fidelity_draft,
    )
    from proofmap.paper_store import PaperStore
    from proofmap.runner import RunResult

    source = manuscript(tmp_path)
    indexed, _ = ci(source, tmp_path / "index", tmp_path / "store")
    subject = indexed["assertions"][0]["id"]
    profile = VerifierProfile.create(
        image="sha256:" + "a" * 64,
        platform="linux/amd64",
        lean_sha256="b" * 64,
        library_digest="c" * 64,
        checker_digest=CHECKER_DIGEST,
        acquisition_digest="d" * 64,
    )
    private = Ed25519PrivateKey.generate()
    key = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    trust = {
        "schema_version": "2.0",
        "keys": [
            {
                "id": "test-only",
                "public_key": base64.b64encode(
                    private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                ).decode(),
                "roles": [
                    "verification-execution",
                    "source-fidelity-review",
                    "formal-fidelity-review",
                ],
                "subjects": [subject],
                "profiles": [profile.digest],
                "revoked": False,
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
            }
        ],
    }
    now = "2026-09-27T00:00:00Z"

    def simulated(image, root, argv, limits):
        assert b"grind" in (root / "Candidate.lean").read_bytes()
        assert not any(path.suffix == ".key" for path in root.iterdir())
        actual = {
            name: getattr(profile, name)
            for name in (
                "lean_sha256",
                "library_digest",
                "checker_digest",
                "platform",
                "executable",
                "search_path",
            )
        }
        actual["version"] = "Lean (version 4.30.0, TEST SIMULATION)"
        check = {
            "returncode": 0,
            "stdout": "'proofmap_target' depends on axioms: [propext, Classical.choice, Quot.sound]",
            "stderr": "",
        }
        report = {
            "outcome": "CHECKED",
            "actual": actual,
            "results": {"Candidate": check, "Recheck": check},
        }
        return RunResult("PASS", 0, canonical_bytes(report).decode(), "", 0, image, limits)

    monkeypatch.setattr("proofmap.execution.run", simulated)
    bundle, code = ci(
        source,
        tmp_path / "verified",
        tmp_path / "store",
        execution_profile=profile.to_dict(),
        controller_id="test-only",
        controller_key=key,
        trust_store=trust,
        evaluation_time=now,
        require_formal=True,
    )
    assert code == 0
    assert bundle["assessment"]["outcomes"]["coverage"]["kernel_verified"] == 1
    assert bundle["acceptance_records"][0]["assessment"] == "REVIEW_REQUIRED"
    profile_path, trust_path = tmp_path / "profile.json", tmp_path / "trust.json"
    write_json(profile_path, profile.to_dict())
    write_json(trust_path, trust)
    key_path = tmp_path / "reviewer.key"
    key_path.write_bytes(key)
    store = PaperStore(tmp_path / "store")
    try:
        before = reassess(bundle, store, profile.to_dict(), trust, now)
        assert before["counts"]["accepted"] == 0
        for dimension in ("source-fidelity", "formal-fidelity"):
            draft_path = tmp_path / (dimension + ".json")
            signed_path = tmp_path / (dimension + ".dsse.json")
            assert (
                main(
                    [
                        "paper",
                        "review-export",
                        str(tmp_path / "verified"),
                        "--author",
                        "test-only",
                        "--dimension",
                        dimension,
                        "--assertion",
                        subject,
                        "--execution-profile",
                        str(profile_path),
                        "--out",
                        str(draft_path),
                    ]
                )
                == 0
            )
            draft = load_json(draft_path)
            with pytest.raises(ValueError, match="EXPLICIT"):
                sign_fidelity_draft(draft, key)
            draft["decision"] = "APPROVE"
            write_json(draft_path, draft)
            assert (
                main(
                    [
                        "paper",
                        "review-sign",
                        str(draft_path),
                        "--key",
                        str(key_path),
                        "--out",
                        str(signed_path),
                    ]
                )
                == 0
            )
            assert (
                main(
                    [
                        "paper",
                        "review-apply",
                        str(tmp_path / "verified"),
                        str(signed_path),
                        "--store",
                        str(tmp_path / "store"),
                        "--execution-profile",
                        str(profile_path),
                        "--trust-store",
                        str(trust_path),
                        "--evaluation-time",
                        now,
                        "--report-out",
                        str(tmp_path / "current-report"),
                    ]
                )
                == 0
            )
        final = reassess(bundle, store, profile.to_dict(), trust, now)
        assert final["counts"] == {
            "ingested": 1,
            "formalized": 1,
            "verified": 1,
            "reviewed": 1,
            "accepted": 1,
        }
        assert len(store.list_audit(bundle["run_manifest"]["run_id"], "ReviewDecision")) == 2
        assert "ACCEPTED_UNDER_POLICY" in (tmp_path / "current-report" / "report.html").read_text()
        from html import unescape

        assert "ACCEPTED_UNDER_POLICY" in unescape(
            (tmp_path / "current-report" / "report.md").read_text()
        )
        reviewed_report = load_json(tmp_path / "current-report" / "current-assessment.json")
        assert len(reviewed_report["review_decisions"]) == 2
        assert all(r["reviewer_id"] == "test-only" for r in reviewed_report["review_decisions"])
        revoked = deepcopy(trust)
        revoked["keys"][0]["revoked"] = True
        revoked_assessment = reassess(bundle, store, profile.to_dict(), revoked, now)
        assert revoked_assessment["counts"]["accepted"] == 0
        report_assessment(bundle, revoked_assessment, store, tmp_path / "revoked-report")
        revoked_outcomes = load_json(tmp_path / "revoked-report" / "current-assessment.json")[
            "outcomes"
        ]
        assert revoked_outcomes["coverage"]["kernel_verified_fraction"] == 0.0
        assert revoked_outcomes["kernel_verification"] != "PASS"
        assert revoked_outcomes["formal_compilation"] == "PASS"
        assert bundle["assessment"]["outcomes"]["kernel_verification"] == "PASS"
        source.write_text(source.read_text().replace("mathbb{Z}", "mathbb{R}"))
        changed, _ = ci(source, tmp_path / "changed", tmp_path / "store")
        with pytest.raises(ValueError, match="STALE"):
            apply_fidelity(changed, load_json(signed_path), store, profile.to_dict(), trust, now)
    finally:
        store.close()
