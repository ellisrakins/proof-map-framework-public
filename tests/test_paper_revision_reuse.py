"""Measured dependency-local reuse; isolated Lean qualification lives in CI."""

from copy import deepcopy
from pathlib import Path

import pytest

from proofmap.integrity import canonical_bytes
from proofmap.paper import ci, diff
from proofmap.paper_store import PaperStore


def manuscript(
    path: Path, *, offset: int = 1, prefix: str = "", proof: str = "", suffix: str = ""
) -> Path:
    path.write_text(
        prefix
        + r"\documentclass{article}\begin{document}"
        + r"{\newcommand{\offset}{"
        + str(offset)
        + r"}"
        + r"\begin{theorem}\label{a}For every $x\in\mathbb{Z}$, "
        + r"\[(x+\offset)^2=x^2+2*\offset*x+\offset^2.\]\end{theorem}"
        + proof
        + "}"
        + r"{\begin{theorem}\label{b}For every $x\in\mathbb{Z}$, "
        + r"\[(x+3)^2=x^2+6x+9.\]\end{theorem}}"
        + suffix
        + r"\end{document}",
        encoding="utf-8",
    )
    return path


def decisions(bundle):
    return {row["label"]: row for row in bundle["revision_plan"]["rows"]}


def run_pair(tmp_path, monkeypatch, edit, **second_options):
    import proofmap.formalize as formalize

    calls = []
    original = formalize.formalize_assertion

    def measured(ir, element):
        calls.append(element["labels"])
        return original(ir, element)

    monkeypatch.setattr(formalize, "formalize_assertion", measured)
    source = manuscript(tmp_path / "paper.tex")
    first, _ = ci(source, tmp_path / "first", tmp_path / "store", paper_id="revision-test")
    assert calls == [["a"], ["b"]]
    assert all(row["status"] == "SUPPORTED" for row in first["formalizations"])
    calls.clear()
    edit(source)
    second, _ = ci(
        source, tmp_path / "second", tmp_path / "store", paper_id="revision-test", **second_options
    )
    return first, second, calls


def test_definition_change_executes_only_affected_branch(tmp_path, monkeypatch):
    first, second, calls = run_pair(tmp_path, monkeypatch, lambda path: manuscript(path, offset=2))
    assert calls == [["a"]]
    plan = decisions(second)
    assert plan["a"]["pure_execution"] == "EXECUTED"
    assert "DEFINITION_OR_MACRO_CHANGED" in plan["a"]["reasons"]
    assert plan["b"]["pure_execution"] == "REUSED"
    assert plan["b"]["cache_validation"] == "BOUNDED_EXACT_CERTIFICATE_RECOMPUTED"
    assert plan["a"]["cache_validation"] == "NOT_A_SUPPORTED_CACHE_HIT"
    assert plan["b"]["parent_stage"] == decisions(first)["b"]["pure_stage"]
    before, after = first["formalizations"][1], second["formalizations"][1]
    assert before["binding"]["id"] != after["binding"]["id"]
    assert before["source_locators"] != after["source_locators"]
    assert before["obligation"]["statement"] == after["obligation"]["statement"]
    assert before["exact_check"] == after["exact_check"]
    assert diff(first, second)["invalidated_assertions"] == [first["assertions"][0]["id"]]
    store = PaperStore(tmp_path / "store")
    store.rebuild()
    assert store.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 2
    assert canonical_bytes(
        store.inspect(first["run_manifest"]["run_id"])["bundle"]
    ) == canonical_bytes(first)
    assert canonical_bytes(
        store.inspect(second["run_manifest"]["run_id"])["bundle"]
    ) == canonical_bytes(second)
    store.close()


def test_source_only_move_reanchors_without_formalization_producer_execution(tmp_path, monkeypatch):
    first, second, calls = run_pair(
        tmp_path, monkeypatch, lambda path: manuscript(path, prefix="% source relocation\n")
    )
    assert calls == []
    assert all(row["pure_execution"] == "REUSED" for row in decisions(second).values())
    assert all(
        row["cache_validation"] == "BOUNDED_EXACT_CERTIFICATE_RECOMPUTED"
        for row in decisions(second).values()
    )
    assert all(row["changes"] == ["SOURCE_REANCHORED"] for row in decisions(second).values())
    assert second["execution_events"] == first["execution_events"] == []
    assert second["acceptance_records"] == []
    assert not diff(first, second)["invalidated_assertions"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ("hypothesis", "STATEMENT_OR_HYPOTHESIS_CHANGED"),
        ("proof", "PROOF_CHANGED"),
        ("citation", "UNRESOLVED_CITATION_OR_DEPENDENCY"),
    ],
)
def test_changed_local_material_preserves_independent_branch(tmp_path, monkeypatch, change, reason):
    def edit(path):
        if change == "hypothesis":
            path.write_text(
                path.read_text().replace(
                    r"\label{a}For every $x\in\mathbb{Z}$,",
                    r"\label{a}For every $x\in\mathbb{Z}$, if $x=0$, then",
                )
            )
        else:
            manuscript(
                path,
                proof=r"\begin{proof}"
                + (r"See \ref{missing}." if change == "citation" else "Direct calculation.")
                + r"\end{proof}",
            )

    _, second, calls = run_pair(tmp_path, monkeypatch, edit)
    assert calls == [["a"]]
    assert reason in decisions(second)["a"]["reasons"]
    assert decisions(second)["b"]["pure_execution"] == "REUSED"


def test_unresolved_surrounding_context_is_conservative(tmp_path, monkeypatch):
    _, second, calls = run_pair(
        tmp_path,
        monkeypatch,
        lambda path: manuscript(path, suffix="Assume all standing conditions above."),
    )
    assert calls == [["a"], ["b"]]
    assert all(not row["reuse_eligible"] for row in decisions(second).values())


def test_configuration_change_invalidates_pure_execution(tmp_path, monkeypatch):
    _, second, calls = run_pair(
        tmp_path, monkeypatch, lambda path: None, config={"required_stages": ["source-structure"]}
    )
    assert calls == [["a"], ["b"]]
    assert "CONFIG_CHANGED" in second["revision_plan"]["configuration_changes"]


@pytest.mark.parametrize("change", ["prompt", "model"])
def test_analysis_contract_change_executes_checks_again(tmp_path, monkeypatch, change):
    def edit(path):
        if change == "prompt":
            from proofmap.extractor import PROMPT

            monkeypatch.setattr("proofmap.extractor.PROMPT", PROMPT + " Test prompt revision.")

    options = {}
    if change == "model":
        options["config"] = {
            "extractor": {
                "provider": "ollama",
                "endpoint": "http://localhost:11434",
                "model": "different-offline-model",
                "timeout_seconds": 3,
                "max_output_tokens": 128,
            }
        }
    _, second, calls = run_pair(tmp_path, monkeypatch, edit, **options)
    assert calls == [["a"], ["b"]]
    assert second["revision_plan"]["configuration_changes"]


def test_unknown_policy_cannot_reuse_or_publish(tmp_path, monkeypatch):
    import proofmap.formalize as formalize
    from proofmap.paper import POLICY

    source = manuscript(tmp_path / "paper.tex")
    first, _ = ci(source, tmp_path / "first", tmp_path / "store")
    calls = []
    original = formalize.formalize_assertion

    def measured(ir, element):
        calls.append(element["labels"])
        return original(ir, element)

    monkeypatch.setattr(formalize, "formalize_assertion", measured)
    monkeypatch.setattr("proofmap.paper.POLICY", {**POLICY, "version": 2})
    with pytest.raises(ValueError, match="PAPER_RECORD_SCHEMA"):
        ci(source, tmp_path / "changed-policy", tmp_path / "store")
    assert calls == [["a"], ["b"]]
    store = PaperStore(tmp_path / "store")
    assert store.db.execute("SELECT count(*) FROM runs").fetchone()[0] == 1
    assert canonical_bytes(
        store.inspect(first["run_manifest"]["run_id"])["bundle"]
    ) == canonical_bytes(first)
    store.close()


@pytest.mark.parametrize("change", ["prompt", "model"])
def test_model_or_prompt_change_reexecutes_recorded_stage_and_preserves_history(
    tmp_path, monkeypatch, change
):
    """Offline provider protocol simulation; no live model requests or proof authority."""
    import json

    import proofmap.extractor as extractor
    import proofmap.formalize as formalize
    from proofmap.integrity import artifact_digest, digest

    requests, producers = [], []
    original_extract, original_formalize = extractor.extract, formalize.formalize_assertion

    def protocol(document, config, *, replay=None, **kwargs):
        if replay is not None:
            return original_extract(document, config, replay=replay, **kwargs)
        requests.append(extractor.make_request(document, config))
        raw = json.dumps(
            {
                "done": True,
                "model": config["model"],
                "message": {"content": json.dumps({"classifications": [], "dependencies": []})},
            }
        )
        return original_extract(
            document,
            config,
            replay={
                "request_sha256": artifact_digest(canonical_bytes(requests[-1])),
                "config_digest": digest("extractor-config.v1", config),
                "raw_response": raw,
                "response_sha256": artifact_digest(raw.encode()),
            },
            **kwargs,
        )

    def measured(ir, element):
        producers.append(element["labels"])
        return original_formalize(ir, element)

    monkeypatch.setattr("proofmap.paper.extract", protocol)
    monkeypatch.setattr(formalize, "formalize_assertion", measured)
    source = manuscript(tmp_path / "paper.tex")
    config = {
        "extractor": {
            "provider": "ollama",
            "endpoint": "http://localhost:11434",
            "model": "offline-protocol",
            "timeout_seconds": 3,
            "max_output_tokens": 128,
        }
    }
    options = {"extractor": "configured", "config": config}
    first, code = ci(source, tmp_path / "first", tmp_path / "store", **options)
    assert code == 0 and len(requests) == 1
    immutable = canonical_bytes(first)
    producers.clear()
    if change == "prompt":
        monkeypatch.setattr(
            extractor, "PROMPT", extractor.PROMPT + " Recorded prompt revision test."
        )
    else:
        options["config"] = {
            "extractor": {**config["extractor"], "model": "second-offline-protocol"}
        }
    second, code = ci(source, tmp_path / "second", tmp_path / "store", **options)
    assert code == 0 and len(requests) == 2 and producers == [["a"], ["b"]]
    if change == "prompt":
        assert requests[0]["messages"][0]["content"] != requests[1]["messages"][0]["content"]
        assert "EXTRACTOR_CONTRACT_CHANGED" in second["revision_plan"]["configuration_changes"]
        assert (
            second["extraction_events"][0]["prompt_digest"]
            != first["extraction_events"][0]["prompt_digest"]
        )
    else:
        assert requests[0]["model"] != requests[1]["model"]
        assert "CONFIG_CHANGED" in second["revision_plan"]["configuration_changes"]
        assert (
            second["extraction_events"][0]["config_digest"]
            != first["extraction_events"][0]["config_digest"]
        )
    store = PaperStore(tmp_path / "store")
    assert canonical_bytes(store.inspect(first["run_manifest"]["run_id"])["bundle"]) == immutable
    store.rebuild()
    assert canonical_bytes(store.inspect(first["run_manifest"]["run_id"])["bundle"]) == immutable
    store.close()


@pytest.mark.parametrize("change", ["proof_macro", "nested_citation"])
def test_proof_descendant_dependencies_invalidate_only_owner(tmp_path, monkeypatch, change):
    import proofmap.formalize as formalize

    root = tmp_path / "source"
    root.mkdir()
    path = root / "paper.tex"
    calls = []
    original = formalize.formalize_assertion

    def measured(ir, element):
        calls.append(element["labels"])
        return original(ir, element)

    monkeypatch.setattr(formalize, "formalize_assertion", measured)
    if change == "proof_macro":
        manuscript(
            path,
            prefix=r"\newcommand{\proofconstant}{1}",
            proof=r"\begin{proof}$\proofconstant$\end{proof}",
        )
    else:
        manuscript(
            path,
            proof=r"\begin{proof}$\text{\cite{key}}$\end{proof}",
            suffix=r"\bibliography{refs}",
        )
        (root / "refs.bib").write_text("@article{key,title={Old}}")
    first, _ = ci(root, tmp_path / "first", tmp_path / "store", entrypoint="paper.tex")
    calls.clear()
    if change == "proof_macro":
        path.write_text(path.read_text().replace(r"\proofconstant}{1}", r"\proofconstant}{2}"))
    else:
        (root / "refs.bib").write_text("@article{key,title={New}}")
    second, _ = ci(root, tmp_path / "second", tmp_path / "store", entrypoint="paper.tex")
    assert calls == [["a"]]
    assert decisions(first)["a"]["fingerprint"] != decisions(second)["a"]["fingerprint"]
    assert decisions(second)["b"]["pure_execution"] == "REUSED"


def test_rehashed_reuse_forgery_rejected_by_store(tmp_path, monkeypatch):
    from proofmap.integrity import digest

    first, second, _ = run_pair(tmp_path, monkeypatch, lambda path: manuscript(path, offset=2))
    forged = deepcopy(second)
    row = decisions(forged)["a"]
    row["reasons"] = []
    row["reuse_eligible"] = True
    row["previous_fingerprint"] = row["fingerprint"]
    forged["run_manifest"]["run_id"] = "forged-reuse"
    forged["run_manifest"]["bundle_digests"]["revision_plan"] = digest(
        "paper-bundle-component.v1", forged["revision_plan"]
    )
    store = PaperStore(tmp_path / "store")
    artifacts = {"paper.tex": (tmp_path / "paper.tex").read_bytes()}
    with pytest.raises(ValueError, match="REVISION_LINEAGE_MISMATCH"):
        store.ingest("revision-test", forged, artifacts)
    assert canonical_bytes(
        store.inspect(first["run_manifest"]["run_id"])["bundle"]
    ) == canonical_bytes(first)
    store.close()


@pytest.mark.parametrize("field", ["revision", "source_ids", "finding_source"])
def test_rehashed_checker_wrong_source_is_rejected(tmp_path, field):
    from proofmap.integrity import digest
    from proofmap.paper_checkers import make_result
    from proofmap.paper_store import validate_bundle

    source = manuscript(tmp_path / "paper.tex")
    bundle, _ = ci(source, tmp_path / "run", tmp_path / "store")
    changed = deepcopy(bundle)
    checker = changed["assessment"]["checkers"][0]
    if field == "finding_source":
        checker["findings"] = make_result(
            "example",
            "PASS",
            [{"code": "TEST_DIAGNOSTIC", "source": "a" * 64, "detail": "Unsupported source."}],
        )["findings"]
    else:
        checker[field] = "a" * 64 if field == "revision" else ["a" * 64]
    changed["run_manifest"]["bundle_digests"]["assessment"] = digest(
        "paper-bundle-component.v1", changed["assessment"]
    )
    with pytest.raises(ValueError, match="CHECKER_.*SOURCE_BINDING"):
        validate_bundle(changed)


def test_simulated_historical_execution_new_reviews_and_revocation(tmp_path, monkeypatch):
    """Test contract-only signed worker simulation, not actual Lean execution."""
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    from proofmap.evidence_records import VerifierProfile
    from proofmap.execution import CHECKER_DIGEST
    from proofmap.integrity import canonical_bytes
    from proofmap.paper_evidence import (
        apply_fidelity,
        fidelity_draft,
        reassess,
        sign_fidelity_draft,
    )
    from proofmap.paper_sources import acquire, parse
    from proofmap.runner import RunResult

    source = manuscript(tmp_path / "paper.tex")
    subjects = []
    for offset in (1, 2):
        manuscript(source, offset=offset)
        manifest, files = acquire(source)
        ir = parse(manifest, files)
        subjects.extend(row["id"] for row in ir["elements"] if row["kind"] == "ASSERTION")
    manuscript(source)
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
                "subjects": subjects,
                "profiles": [profile.digest],
                "revoked": False,
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
            }
        ],
    }
    calls = []

    def simulated(image, root, argv, limits):
        calls.append((root / "Candidate.lean").read_bytes())
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
        return RunResult(
            "PASS",
            0,
            canonical_bytes(
                {
                    "outcome": "CHECKED",
                    "actual": actual,
                    "results": {"Candidate": check, "Recheck": check},
                }
            ).decode(),
            "",
            0,
            image,
            limits,
        )

    monkeypatch.setattr("proofmap.execution.run", simulated)
    now = "2026-10-02T00:00:00Z"
    options = {
        "paper_id": "historical",
        "execution_profile": profile.to_dict(),
        "controller_key": key,
        "controller_id": "test-only",
        "trust_store": trust,
        "evaluation_time": now,
        "require_formal": True,
    }
    first, code = ci(source, tmp_path / "first", tmp_path / "store", **options)
    assert code == 0 and len(calls) == 2
    store = PaperStore(tmp_path / "store")
    old_reviews = []
    for dimension in ("source-fidelity", "formal-fidelity"):
        draft = fidelity_draft(
            first, first["assertions"][1]["id"], profile.to_dict(), dimension, "test-only"
        )
        draft["decision"] = "APPROVE"
        envelope = sign_fidelity_draft(draft, key)
        old_reviews.append(envelope)
        current = apply_fidelity(first, envelope, store, profile.to_dict(), trust, now)
    assert current["counts"]["accepted"] == 1
    immutable = canonical_bytes(first)
    manuscript(source, offset=2)
    calls.clear()
    second, code = ci(source, tmp_path / "second", tmp_path / "store", **options)
    assert code == 0 and len(calls) == 1
    assert len(second["execution_events"]) == 1
    assert decisions(second)["b"]["formal_execution"] == "HISTORICAL_REUSE"
    current_b = second["formalizations"][1]
    history = current_b["historical_execution"]
    assert history["execution"] == first["execution_events"][1]
    assert "execution_event" not in current_b
    assert current_b["binding"]["id"] != first["formalizations"][1]["binding"]["id"]
    assert all(record["assessment"] == "REVIEW_REQUIRED" for record in second["acceptance_records"])
    for envelope in old_reviews:
        with pytest.raises(ValueError, match="STALE_REVIEW_BINDING"):
            apply_fidelity(second, envelope, store, profile.to_dict(), trust, now)
    for dimension in ("source-fidelity", "formal-fidelity"):
        draft = fidelity_draft(
            second, second["assertions"][1]["id"], profile.to_dict(), dimension, "test-only"
        )
        draft["decision"] = "APPROVE"
        current = apply_fidelity(
            second, sign_fidelity_draft(draft, key), store, profile.to_dict(), trust, now
        )
    assert current["counts"]["verified"] == 2 and current["counts"]["accepted"] == 1
    revoked = deepcopy(trust)
    revoked["keys"][0]["revoked"] = True
    assert reassess(second, store, profile.to_dict(), revoked, now)["counts"]["accepted"] == 0
    calls.clear()
    third, code = ci(
        source, tmp_path / "revoked", tmp_path / "store", **{**options, "trust_store": revoked}
    )
    assert code != 0 and not calls
    assert third["assessment"]["outcomes"]["coverage"]["kernel_verified"] == 0
    assert all(row["formal_execution"] == "HISTORICAL_REUSE" for row in decisions(third).values())
    assert canonical_bytes(store.inspect(first["run_manifest"]["run_id"])["bundle"]) == immutable
    store.rebuild()
    assert canonical_bytes(
        store.inspect(second["run_manifest"]["run_id"])["bundle"]
    ) == canonical_bytes(second)
    store.close()
