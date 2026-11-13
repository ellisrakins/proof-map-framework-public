"""Real reconstruction reuse must leave source and current authority checks fresh."""

import shutil
import subprocess
import venv
from copy import deepcopy
from pathlib import Path

import pytest

from proofmap import paper_sources
from proofmap.campaign.models import qualified_ref
from proofmap.campaign.portable import audit_campaign, export_campaign, import_campaign
from proofmap.campaign.reports import campaign_report_model, write_campaign_report
from proofmap.campaign.service import add_goal, ingest, initialize
from proofmap.campaign.store import CampaignStore
from proofmap.integrity import artifact_digest

CORPUS = Path(__file__).parent / "fixtures/campaign/realism"
PDF = CORPUS / "euclid/book-i-proposition-i.pdf"


def reconstruction_counter(monkeypatch):
    original = paper_sources.parse
    calls = []

    def observed(manifest, files, parser="auto", **kwargs):
        if any(name.endswith(".pdf") for name in files):
            calls.append((parser, tuple(artifact_digest(raw) for raw in files.values())))
        return original(manifest, files, parser, **kwargs)

    monkeypatch.setattr(paper_sources, "parse", observed)
    return calls, observed


@paper_sources.source_validation_operation
def source_campaign(tmp_path):
    store = CampaignStore(tmp_path / "store")
    campaign_id = initialize(store, "Scoped validation", "Keep exact source and authority fresh")[
        "campaign_id"
    ]
    source = tmp_path / "source"
    source.mkdir()
    (source / "euclid.pdf").write_bytes(PDF.read_bytes())
    (source / "claim.tex").write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}\label{identity}"
        r"For every $x\in\mathbb{Z}$, \[(x+1)^2=x^2+2x+1.\]"
        r"\end{theorem}\begin{proof}Direct calculation.\end{proof}\end{document}"
    )
    ingest(store, campaign_id, source)
    selected = store.current_snapshot(campaign_id)["selections"]
    tex = next(row for row in selected if row["paper_id"].endswith(".tex"))
    pdf = next(row for row in selected if row["paper_id"].endswith(".pdf"))
    goal = add_goal(store, campaign_id, run_id=tex["run_id"], label="identity")
    return store, campaign_id, goal["target"], pdf["run_id"]


@pytest.fixture(scope="module")
def validated_source_campaign(tmp_path_factory):
    with paper_sources.source_validation_scope():
        store, campaign_id, ref, pdf_run = source_campaign(
            tmp_path_factory.mktemp("source-validation-base")
        )
        try:
            stored = store.inspect(pdf_run)
            element = stored["bundle"]["document_ir"]["elements"][0]
            sources = {name: store.get(sha) for name, sha in stored["artifacts"].items()}
            root = store.root
        finally:
            store.close()
    # All snapshots are immutable material from real public intake, with the DB closed.
    before = {
        path.relative_to(root): artifact_digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    yield root, campaign_id, ref, pdf_run, element, sources
    assert {
        path.relative_to(root): artifact_digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    } == before


def campaign_copy(tmp_path, baseline):
    root, campaign_id, ref, pdf_run, _, _ = baseline
    copied = tmp_path / "store"
    shutil.copytree(root, copied)
    return CampaignStore(copied), campaign_id, deepcopy(ref), pdf_run


def test_report_restore_reuses_real_pdf_and_still_rereads_corrupt_cas(
    tmp_path, monkeypatch, validated_source_campaign
):
    store, campaign_id, ref, pdf_run = campaign_copy(tmp_path, validated_source_campaign)
    restored = CampaignStore(tmp_path / "restored")
    calls, _ = reconstruction_counter(monkeypatch)
    try:
        with paper_sources.source_validation_scope():
            store.current_snapshot(campaign_id)
            assert qualified_ref(store, ref["run_id"], ref["assertion_id"]) == ref
            stored = store.inspect(pdf_run)
            write_campaign_report(store, campaign_id, tmp_path / "report")
            archive = tmp_path / "dossier.zip"
            export_campaign(store, campaign_id, archive, include_source=True)
            import_campaign(archive, restored)
            assert audit_campaign(restored, campaign_id)["integrity"] == "PASS"
            assert len(calls) == 1
            sha = next(iter(stored["artifacts"].values()))
            object_path = store.root / "objects" / sha[:2] / sha[2:]
            original = object_path.read_bytes()
            try:
                object_path.write_bytes(original + b"changed while reconstruction is cached")
                with pytest.raises(ValueError, match="CORRUPT_CAS_OBJECT"):
                    store.current_snapshot(campaign_id)
                assert len(calls) == 1
            finally:
                object_path.write_bytes(original)
        assert campaign_report_model(store, campaign_id)["coverage"]["accepted"] == 0
        assert len(calls) == 2  # A separate operation independently reconstructs the source.
    finally:
        restored.close()
        store.close()


def test_scoped_reconstruction_rechecks_locators_exact_bytes_and_exception_boundary(
    monkeypatch, validated_source_campaign
):
    _, _, _, _, element, files = validated_source_campaign
    locator, text = element["locator"], element["text"]
    calls, _ = reconstruction_counter(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        with paper_sources.source_validation_scope() as session:
            paper_sources.validate_locator(locator, files, text)
            # A caller cannot alter cached reconstruction by mutating a returned list.
            session.pdf_pages(files[locator["artifact"]])[0] = "poisoned copy"
            paper_sources.validate_locator(locator, files, text)
            assert len(calls) == 1
            with pytest.raises(ValueError, match="SOURCE_EXCERPT_MISMATCH"):
                paper_sources.validate_locator(locator, files, text + "wrong characters")
            wrong_range = {**locator, "text_end": locator["text_end"] + 1}
            with pytest.raises(
                ValueError, match="PDF_RECONSTRUCTION_RANGE|SOURCE_EXCERPT_MISMATCH"
            ):
                paper_sources.validate_locator(wrong_range, files, text)
            changed = {name: raw + b"\n% exact bytes changed" for name, raw in files.items()}
            with pytest.raises(ValueError, match="STALE_SOURCE_LOCATOR"):
                paper_sources.validate_locator(locator, changed, text)
            changed_locator = {
                **locator,
                "artifact_sha256": artifact_digest(changed[locator["artifact"]]),
            }
            paper_sources.validate_locator(changed_locator, changed, text)
            assert len(calls) == 2
            raise KeyboardInterrupt
    with paper_sources.source_validation_scope():
        paper_sources.validate_locator(locator, files, text)
    assert len(calls) == 3


@pytest.mark.parametrize("limit", ["count", "bytes"])
def test_reconstruction_budget_evicts_or_declines_retention(
    monkeypatch, limit, validated_source_campaign
):
    """Capacity bookkeeping uses a labelled double; real parser integration is above."""
    _, _, _, _, element, files = validated_source_campaign
    locator, text = element["locator"], element["text"]
    calls = []

    def reconstructed(manifest, sources, parser):
        assert parser == "pypdf" and sources["source.pdf"].startswith(b"%PDF")
        calls.append(manifest.revision)
        return {"parser": {"execution": "COMPLETED"}, "elements": [{"text": text}]}

    monkeypatch.setattr(paper_sources, "parse", reconstructed)
    monkeypatch.setattr(
        paper_sources,
        "MAX_VALIDATION_PDFS" if limit == "count" else "MAX_VALIDATION_TEXT_BYTES",
        1,
    )
    with paper_sources.source_validation_scope():
        paper_sources.validate_locator(locator, files, text)
        changed = {name: raw + b"\n% second reconstruction" for name, raw in files.items()}
        changed_locator = {
            **locator,
            "artifact_sha256": artifact_digest(changed[locator["artifact"]]),
        }
        paper_sources.validate_locator(changed_locator, changed, text)
        paper_sources.validate_locator(locator, files, text)
    assert len(calls) == 3


def test_scoped_pdf_reuse_never_caches_current_profile_time_or_review_authority(
    tmp_path, monkeypatch, validated_source_campaign
):
    import test_execution as fixture

    from proofmap.attempts import FormalObligation
    from proofmap.evidence_records import FormalizationBinding, ReviewDecision, VerifierProfile
    from proofmap.execution import execute
    from proofmap.trust import sign_record

    store, campaign_id, ref, _ = campaign_copy(tmp_path, validated_source_campaign)
    try:
        fixture.simulated_execution(monkeypatch)  # Explicit unit trust contract, not Lean evidence.
        formal = store.inspect(ref["run_id"])["bundle"]["formalizations"][0]
        binding = FormalizationBinding.from_dict(formal["binding"])
        profile = fixture.profile()
        private, trust = fixture.authority(
            "verification-execution", binding.assertion_id, profile.digest
        )
        trust["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]
        execution = execute(
            binding,
            FormalObligation.from_dict(formal["obligation"]),
            formal["candidate"].encode(),
            profile,
            controller_id="controller",
            private_key=private,
        )
        store.add_audit(
            ref["run_id"], {"record": execution["event"], "envelope": execution["envelope"]}
        )
        for dimension in ("source-fidelity", "formal-fidelity"):
            decision = ReviewDecision.create(
                binding=binding,
                profile=profile,
                dimension=dimension,
                decision="APPROVE",
                reviewer_id="controller",
            ).to_dict()
            store.add_audit(
                ref["run_id"],
                {"record": decision, "envelope": sign_record(decision, private, "controller")},
            )
        inputs = {
            "execution_profile": profile.to_dict(),
            "trust_store": trust,
            "evaluation_time": "2026-10-02T00:00:00Z",
        }
        calls, _ = reconstruction_counter(monkeypatch)
        revoked = deepcopy(trust)
        revoked["keys"][0]["revoked"] = True
        changed_fields = {
            key: value
            for key, value in profile.to_dict().items()
            if key not in {"id", "record_type", "schema_version"}
        }
        changed_fields["image"] = "sha256:" + "e" * 64
        changed_profile = VerifierProfile.build(**changed_fields).to_dict()
        before = store.db.total_changes
        with paper_sources.source_validation_scope():
            assert campaign_report_model(store, campaign_id, **inputs)["coverage"]["accepted"] == 1
            for change in (
                {"trust_store": revoked},
                {"evaluation_time": "2027-10-02T00:00:00Z"},
                {"execution_profile": changed_profile},
            ):
                denied = campaign_report_model(store, campaign_id, **{**inputs, **change})
                assert denied["coverage"]["accepted"] == denied["coverage"]["verified"] == 0
            assert campaign_report_model(store, campaign_id)["coverage"]["accepted"] == 0
            assert len(calls) == 1
        assert campaign_report_model(store, campaign_id, **inputs)["coverage"]["accepted"] == 1
        assert len(calls) == 2 and store.db.total_changes == before
    finally:
        store.close()


def test_realism_reuses_reconstruction_with_actual_initial_intake_and_resume(tmp_path, monkeypatch):
    from proofmap import paper
    from proofmap.campaign.pilot import evaluate_realism

    calls, observed = reconstruction_counter(monkeypatch)
    monkeypatch.setattr(paper, "parse", observed)
    result = evaluate_realism(CORPUS, tmp_path)
    assert (
        result["source_anchor_validity"]["valid"] == result["source_anchor_validity"]["total"] == 49
    )
    assert sum(row["discovered_claims"] for row in result["documents"]) == 4
    assert all(row["reused_pure_stages"] > 0 for row in result["documents"])
    assert len(calls) == 2  # Initial parser worker plus independent locator reconstruction worker.


def test_missing_optional_pdf_adapter_preserves_isolated_parser_error(tmp_path):
    """An isolated copy of the imported product must reach the real missing adapter."""
    import proofmap

    environment = tmp_path / "bare-python"
    venv.EnvBuilder(with_pip=False).create(environment)
    interpreter = environment / (
        "Scripts/python.exe" if (environment / "Scripts").exists() else "bin/python"
    )
    discovered = subprocess.run(
        [str(interpreter), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    purelib = Path(discovered.stdout.strip()).resolve()
    assert purelib.is_relative_to(environment.resolve())
    assert not list(purelib.iterdir())  # No parent third-party packages enter this child.
    package_root = Path(proofmap.__file__).resolve().parent
    copied_package = purelib / "proofmap"

    def package_hashes(root):
        return {
            path.relative_to(root).as_posix(): artifact_digest(path.read_bytes())
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        }

    original_hashes = package_hashes(package_root)
    assert original_hashes and "paper_sources.py" in original_hashes
    shutil.copytree(
        package_root,
        copied_package,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
    )
    assert package_hashes(copied_package) == original_hashes
    assert [path.name for path in purelib.iterdir()] == ["proofmap"]
    code = (
        "import sys; assert sys.flags.isolated == 1; "
        "import importlib.util; "
        "assert importlib.util.find_spec('pypdf') is None; "
        "assert importlib.util.find_spec('pylatexenc') is None; "
        "from pathlib import Path; import proofmap; "
        "assert Path(proofmap.__file__).resolve().parent == Path("
        + repr(str(copied_package.resolve()))
        + "); "
        "from proofmap.paper_sources import LocatorValidationSession; "
        "session = LocatorValidationSession(); "
        "raw = Path(" + repr(str(PDF.resolve())) + ").read_bytes(); "
        "\nfor attempt in range(2):\n"
        " try: session.pdf_pages(raw)\n"
        " except ValueError as error: print(type(error).__name__, str(error))\n"
        " else: raise AssertionError('Missing optional parser accepted source')\n"
    )
    completed = subprocess.run(
        [str(interpreter), "-I", "-c", code], capture_output=True, text=True, timeout=45
    )
    assert completed.returncode == 0, completed.stderr
    assert package_hashes(package_root) == package_hashes(copied_package) == original_hashes
    assert completed.stdout.splitlines() == [
        "ValueError No module named 'pypdf'",
        "ValueError No module named 'pypdf'",
    ]


def test_leaf_scope_shares_real_pdf_reconstruction_and_rechecks_exact_source(
    monkeypatch, validated_source_campaign
):
    _, _, _, _, element, files = validated_source_campaign
    locator, text = element["locator"], element["text"]
    calls, _ = reconstruction_counter(monkeypatch)

    @paper_sources.source_validation_leaf_operation
    def validate_twice():
        session = paper_sources._validation_session.get()
        assert session is not None and session.structural_reuse_enabled is False
        paper_sources.validate_locator(locator, files, text)
        session.pdf_pages(files[locator["artifact"]])[0] = "poisoned caller copy"
        paper_sources.validate_locator(locator, files, text)
        with pytest.raises(ValueError, match="SOURCE_EXCERPT_MISMATCH"):
            paper_sources.validate_locator(locator, files, text + "wrong characters")
        changed = {name: raw + b"\n% changed actual PDF bytes" for name, raw in files.items()}
        with pytest.raises(ValueError, match="STALE_SOURCE_LOCATOR"):
            paper_sources.validate_locator(locator, changed, text)
        assert not session._bundle_validations and not session._contract_certifications
        return session

    assert paper_sources._validation_session.get() is None
    first = validate_twice()
    assert len(calls) == 1  # The real parser/subprocess is called once inside one leaf scope.
    assert paper_sources._validation_session.get() is None
    second = validate_twice()
    assert second is not first and len(calls) == 2  # Separate public operations reconstruct anew.
    assert paper_sources._validation_session.get() is None
