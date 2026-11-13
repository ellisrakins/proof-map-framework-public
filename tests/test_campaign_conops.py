"""Source-bound campaign diagnostics must preserve operational boundaries."""

import base64
import json
import shutil
import subprocess
import sys
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from proofmap.campaign.conops import (
    installed_material,
    run_research_conops,
    validate_isolated_outcomes,
    validate_outcomes,
)
from proofmap.campaign.pilot import evaluate_realism, validate_corpus
from proofmap.integrity import artifact_digest, load_json, write_json
from scripts.check_campaign_acceptance import validate_realism

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "tests/fixtures/campaign/realism"


@pytest.fixture(scope="module")
def outcomes(tmp_path_factory):
    return run_research_conops(tmp_path_factory.mktemp("campaign-conops"))


@pytest.fixture(scope="module")
def simulated_isolated_outcomes(tmp_path_factory):
    """Exercise orchestration, not Lean qualification, using labelled worker doubles.

    Source intake, signatures, reviews, archive restore and the independent
    SQLite controller subprocesses are real. Only isolation preflight and the
    container worker boundary are simulated. The uninstalled result cannot be
    supplied as a qualifying installed command artifact.
    """
    from test_execution import profile

    from proofmap.runner import RunResult

    selected = profile()
    observed = {"valid": 0, "invalid": 0, "cancel": 0, "output": 0}

    def worker(image, source, argv, limits, **kwargs):
        if (source / "request.json").is_file():
            material = load_json(source / "request.json")["profile"]
            assert material == selected.to_dict()
            invalid = " + 1" in (source / "Candidate.lean").read_text()
            observed["invalid" if invalid else "valid"] += 1
            actual = {
                key: material[key]
                for key in (
                    "lean_sha256",
                    "library_digest",
                    "checker_digest",
                    "platform",
                    "executable",
                    "search_path",
                )
            }
            actual["version"] = "Lean (version 4.30.0, SIMULATED_UNIT_CONTRACT_ONLY)"
            report = {
                "outcome": "CHECKED",
                "actual": actual,
                "results": {
                    name: {
                        "returncode": 1 if invalid else 0,
                        "stdout": "SIMULATED_UNIT_CONTRACT_ONLY"
                        if invalid
                        else "'proofmap_target' depends on axioms: [propext]",
                        "stderr": "",
                    }
                    for name in ("Candidate", "Recheck")
                },
            }
            return RunResult("PASS", 0, json.dumps(report), "", 0.01, image, limits)
        if "time.sleep(30)" in argv[-1]:
            assert callable(kwargs["cancelled"])
            observed["cancel"] += 1
            return RunResult("CANCELLED", 1, "", "SIMULATED_UNIT_CONTRACT_ONLY", 1.1, image, limits)
        assert "200000" in argv[-1] and limits.output_bytes == 1024
        observed["output"] += 1
        return RunResult(
            "ERROR", 1, "x" * 1024, "SIMULATED_UNIT_CONTRACT_ONLY", 0.01, image, limits
        )

    original_popen = subprocess.Popen

    def source_controller_process(command, *args, **kwargs):
        # Preserve -I and real independent processes, while explicitly selecting
        # this unit test's source package rather than requiring an installed wheel.
        command = list(command)
        if "-c" in command:
            index = command.index("-c") + 1
            if "proofmap.campaign" in command[index]:
                command[index] = (
                    "import sys; sys.path.insert(0, " + repr(str(ROOT)) + "); " + command[index]
                )
        return original_popen(command, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("proofmap.execution.run", worker)
        patch.setattr("proofmap.runner.run", worker)
        patch.setattr("proofmap.paper_evidence.preflight", lambda _: {"execution": "READY"})
        patch.setattr(subprocess, "Popen", source_controller_process)
        value = run_research_conops(
            tmp_path_factory.mktemp("simulated-campaign-contract"),
            profile="isolated",
            execution_profile=selected.to_dict(),
        )
    assert observed == {"valid": 2, "invalid": 1, "cancel": 1, "output": 1}
    assert value["material"]["installed"] is False
    return value


def test_offline_conops_records_source_bound_work(outcomes):
    validate_outcomes(outcomes)
    assert outcomes["validation"] == "PASS"
    assert len(outcomes["goals"]) == 5
    assert outcomes["checks"]["OP-02"]["status"] == "UNEXECUTED"
    assert outcomes["checks"]["OP-07"]["status"] == "UNEXECUTED"
    assert outcomes["formal"] == "UNAVAILABLE"
    assert outcomes["accepted_under_policy"] == 0


def test_uninstalled_diagnostics_never_qualify(outcomes):
    with pytest.raises(ValueError, match="Installed material missing"):
        validate_outcomes(outcomes, require_installed=True)


def test_isolated_artifact_requires_authenticated_actual_events(outcomes):
    altered = deepcopy(outcomes)
    altered["profile"] = "isolated"
    for row in altered["checks"].values():
        row["status"] = "PASS"
    with pytest.raises(ValueError, match="Actual isolated diagnostics missing"):
        validate_outcomes(altered)


def test_recorded_replay_cannot_claim_live_quality(outcomes):
    recorded = outcomes["recorded_extraction"]
    assert recorded["live_model"] is False
    assert recorded["model_quality"] == "NOT_MEASURED"
    assert recorded["altered_replay_exit"] != 0
    assert all(event["replayed"] for event in recorded["events"])
    altered = deepcopy(outcomes)
    altered["recorded_extraction"]["live_model"] = True
    with pytest.raises(ValueError, match="Replay provenance"):
        validate_outcomes(altered)


def test_rights_backed_realism_uses_three_authors_and_unknown_quality(campaign_offline_realism):
    corpus = Path(__file__).parent / "fixtures/campaign/realism"
    manifest = validate_corpus(corpus)
    assert len({r["author"] for r in manifest["samples"]}) == 3
    _, result = campaign_offline_realism
    validate_realism(result)
    assert result["source_anchor_validity"]["valid"] == result["source_anchor_validity"]["total"]
    assert result["live_model_quality"] == "NOT_MEASURED"
    assert result["external_user_pilot"] == "NOT_PERFORMED"
    assert all(row["reused_pure_stages"] > 0 for row in result["documents"])
    changed = deepcopy(result)
    changed["macro"]["discovered_claims"] += 1
    with pytest.raises(ValueError, match="MACRO_DENOMINATOR"):
        validate_realism(changed)


def test_live_pilot_requires_explicit_disclosure_before_endpoint_call(tmp_path):
    with pytest.raises(ValueError, match="DISCLOSURE_NOT_AUTHORIZED"):
        evaluate_realism(
            Path(__file__).parent / "fixtures/campaign/realism",
            tmp_path,
            live_config={"endpoint": "http://127.0.0.1:1"},
        )


def test_retained_realism_source_bytes_are_independently_manifested():
    manifest = load_json(Path(__file__).parent / "fixtures/campaign/realism/provenance.json")
    assert all(
        r["rights_url"].startswith("https://www.gutenberg.org/ebooks/") for r in manifest["samples"]
    )
    assert {r["format"] for r in manifest["samples"]} >= {"born-digital-pdf", "multi-file-tex"}


def test_optional_pilot_budget_is_shared_and_unknown_usage_is_reserved(tmp_path):
    """A bounded local protocol double observes disclosure; it is no live benchmark."""
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    requests = []

    class Provider(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            response = json.dumps(
                {
                    "done": True,
                    "model": "LOCAL_PROTOCOL_TEST_DOUBLE",
                    "message": {"content": json.dumps({"classifications": [], "dependencies": []})},
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(response)))
            self.end_headers()
            self.wfile.write(response)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    config = {
        "provider": "ollama",
        "endpoint": f"http://127.0.0.1:{server.server_port}",
        "model": "LOCAL_PROTOCOL_TEST_DOUBLE",
        "timeout_seconds": 1,
        "max_output_tokens": 512,
        "max_requests": 1,
        "max_input_bytes": 1_000_000,
        "max_total_output_tokens": 512,
        "max_total_seconds": 3,
    }
    try:
        result = evaluate_realism(
            Path(__file__).parent / "fixtures/campaign/realism",
            tmp_path,
            live_config=config,
            disclosure_authorized=True,
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert len(requests) == 1
    assert len(result["live_model_budget"]["reservations"]) == 1
    assert all(amount == 0 for amount in result["live_model_budget"]["remaining"].values())
    assert [r["model_dispatch"] for r in result["documents"]][1:] == [
        "NOT_RUN_BUDGET_EXHAUSTED"
    ] * 2
    assert result["live_model_quality"] == "NOT_MEASURED"
    assert result["live_model_budget"]["absent_usage_is_not_zero"] is True


def test_simulated_orchestration_retains_source_review_and_restore_boundaries(
    simulated_isolated_outcomes,
):
    value = simulated_isolated_outcomes
    validate_outcomes(value, required_profile="isolated")
    raw = value["isolated"]
    assert raw["before_review"]["counts"]["verified"] == 2
    assert raw["before_review"]["counts"]["accepted"] == 0
    assert raw["after_review"]["counts"]["accepted"] == 1
    assert raw["after_revision"]["counts"]["verified"] == 1
    assert raw["after_revision"]["counts"]["accepted"] == 0
    assert raw["restored_without_authority"]["counts"]["verified"] == 0
    assert raw["restored_with_authority"]["counts"]["accepted"] == 1
    assert raw["queue"]["race_winners"] == 1
    assert raw["queue"]["controller_crash_exit"] == 17
    with pytest.raises(ValueError, match="Installed material missing"):
        validate_outcomes(value, require_installed=True)


@pytest.mark.parametrize(
    "attack",
    [
        "source_bytes",
        "duplicate_execution",
        "detached_payload",
        "revoked_controller",
        "expired_authority",
        "wrong_review_role",
        "altered_signed_rejection",
        "approval_labelled_as_rejection",
        "rejection_for_another_goal",
    ],
)
def test_raw_isolated_contract_rechecks_original_material_and_external_authority(
    simulated_isolated_outcomes,
    attack,
):
    raw = deepcopy(simulated_isolated_outcomes["isolated"])
    if attack == "source_bytes":
        source = next(iter(raw["source_bundles"].values()))
        name = next(iter(source["artifacts"]))
        source["artifacts"][name] = base64.b64encode(b"different manuscript").decode()
    elif attack == "duplicate_execution":
        raw["events"].append(deepcopy(raw["events"][0]))
    elif attack == "detached_payload":
        raw["events"][0]["envelope"]["payload"] = base64.b64encode(b"{}").decode()
    elif attack == "revoked_controller":
        raw["trust_store"]["keys"][0]["revoked"] = True
    elif attack == "expired_authority":
        raw["evaluation_time"] = "2028-01-01T00:00:00Z"
    elif attack == "wrong_review_role":
        raw["trust_store"]["keys"][1]["roles"] = ["formal-fidelity-review"]
    elif attack == "approval_labelled_as_rejection":
        raw["signed_rejection"] = deepcopy(raw["review_decisions"][0])
    elif attack == "rejection_for_another_goal":
        raw["goals"][0]["target"] = deepcopy(raw["goals"][1]["target"])
    else:
        raw["signed_rejection"]["payload"] = base64.b64encode(b"{}").decode()
    with pytest.raises(ValueError):
        validate_isolated_outcomes(raw)


@pytest.mark.parametrize(
    "attack,reason",
    [
        ("restored_dispatch", "fresh-authority/dispatch"),
        ("archive_supplied_authority", "fresh-authority/dispatch"),
        ("revision_acceptance", "Assessment count"),
        ("late_worker_publication", "Queue recovery"),
        ("uncancelled_worker", "cancellation/output"),
    ],
)
def test_isolated_contract_rejects_unsafe_delivery_observations(
    simulated_isolated_outcomes,
    attack,
    reason,
):
    raw = deepcopy(simulated_isolated_outcomes["isolated"])
    if attack == "restored_dispatch":
        raw["authenticated_restore_task_states"].append("RUNNING")
    elif attack == "archive_supplied_authority":
        raw["authenticated_restore"]["authority_imported"] = True
    elif attack == "revision_acceptance":
        raw["after_revision"]["counts"]["accepted"] = 1
    elif attack == "late_worker_publication":
        raw["queue"]["late_result_fenced"] = False
    else:
        raw["queue"]["cancelled_container"]["execution_status"] = "PASS"
    with pytest.raises(ValueError, match=reason):
        validate_isolated_outcomes(raw)


@pytest.mark.parametrize(
    "attack,reason",
    [
        ("too_few_authors", "COMPOSITION"),
        ("missing_format", "COMPOSITION"),
        ("duplicate_document", "PROVENANCE"),
        ("no_rights", "PROVENANCE"),
        ("undeclared_transform", "PROVENANCE"),
        ("missing_retained_file", "ARTIFACT_SET"),
        ("changed_retained_bytes", "ARTIFACT_CHANGED"),
        ("unmanifested_file", "ARTIFACT_SET"),
        ("too_small", "INVENTORY"),
    ],
)
def test_pilot_rejects_unsupported_provenance_before_intake(tmp_path, attack, reason):
    corpus = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus)
    manifest = load_json(corpus / "provenance.json")
    if attack == "too_few_authors":
        for sample in manifest["samples"]:
            sample["author"] = "one author"
    elif attack == "missing_format":
        for sample in manifest["samples"]:
            sample["format"] = "single-file-tex"
    elif attack == "duplicate_document":
        manifest["samples"][1]["id"] = manifest["samples"][0]["id"]
    elif attack == "no_rights":
        manifest["samples"][0]["rights"] = ""
    elif attack == "undeclared_transform":
        manifest["samples"][0]["transformation"] = ""
    elif attack == "missing_retained_file":
        manifest["samples"][1]["retained_artifacts"].pop()
    elif attack == "changed_retained_bytes":
        path = corpus / manifest["samples"][0]["retained_artifacts"][0]["path"]
        path.write_bytes(path.read_bytes() + b" altered")
    elif attack == "unmanifested_file":
        directory = next(
            corpus / r["path"] for r in manifest["samples"] if (corpus / r["path"]).is_dir()
        )
        (directory / "unmanifested.tex").write_text("additional source")
    else:
        manifest["samples"] = manifest["samples"][:2]
    write_json(corpus / "provenance.json", manifest)
    with pytest.raises(ValueError, match=reason):
        evaluate_realism(corpus, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_pilot_rejects_source_paths_outside_provenance_root(tmp_path):
    corpus = tmp_path / "corpus"
    shutil.copytree(CORPUS, corpus)
    (tmp_path / "outside.tex").write_text("source outside approved corpus")
    manifest = load_json(corpus / "provenance.json")
    manifest["samples"][0]["path"] = "../outside.tex"
    write_json(corpus / "provenance.json", manifest)
    with pytest.raises(ValueError):
        validate_corpus(corpus)


def test_live_pilot_requires_all_explicit_budgets_before_disclosure(tmp_path, monkeypatch):
    requests = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: requests.append(args))
    config = {
        "provider": "ollama",
        "endpoint": "http://127.0.0.1:1",
        "model": "TEST_ONLY",
        "timeout_seconds": 1,
        "max_output_tokens": 128,
    }
    with pytest.raises(ValueError, match="EXPLICIT_BUDGET_REQUIRED"):
        evaluate_realism(CORPUS, tmp_path / "out", live_config=config, disclosure_authorized=True)
    assert requests == [] and not (tmp_path / "out").exists()


def test_installed_material_checks_all_package_bytes_and_denies_wheel_traversal(
    tmp_path,
    monkeypatch,
):
    """Synthetic installation verifies the byte-check contract, not installed qualification."""
    import proofmap

    prefix = tmp_path / "unit-venv"
    package = prefix / "lib/site-packages/proofmap"
    package.mkdir(parents=True)
    (package / "__init__.py").write_bytes(b"unit package\n")
    monkeypatch.setattr(proofmap, "__file__", str(package / "__init__.py"))
    monkeypatch.setattr(sys, "prefix", str(prefix))
    wheel = tmp_path / "unit.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("proofmap/__init__.py", b"unit package\n")
    material = installed_material(wheel)
    assert material["verified_files"] == 1
    assert material["wheel_sha256"] == artifact_digest(wheel.read_bytes())
    (package / "__init__.py").write_bytes(b"changed installed bytes\n")
    with pytest.raises(ValueError, match="Installed material changed"):
        installed_material(wheel)
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("proofmap/../outside.py", b"outside")
    with pytest.raises(ValueError, match="Wheel traversal"):
        installed_material(wheel)
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("unrelated.txt", b"no package material")
    with pytest.raises(ValueError, match="Empty installed package"):
        installed_material(wheel)


def test_installed_material_rejects_checkout_and_mismatched_candidate_version(
    outcomes,
    tmp_path,
    monkeypatch,
):
    import proofmap

    with monkeypatch.context() as patch:
        patch.setattr(proofmap, "__file__", str(tmp_path / "checkout/proofmap/__init__.py"))
        with pytest.raises(ValueError, match="outside checkout"):
            installed_material(tmp_path / "unused.whl")
    value = deepcopy(outcomes)
    value["material"].update(installed=True, verified_files=1, wheel_sha256="a" * 64)
    value["candidate_identity"] = {"package_version": "wrong-version"}
    with pytest.raises(ValueError, match="version differs"):
        validate_outcomes(value, require_installed=True)


def test_conops_rejects_unsupported_profiles_and_wrong_producer(outcomes, tmp_path):
    with pytest.raises(ValueError, match="RESEARCH_CONOPS_PROFILE"):
        run_research_conops(tmp_path, profile="host-lean")
    with pytest.raises(ValueError, match="Wrong producer profile"):
        validate_outcomes(outcomes, required_profile="isolated")


def test_conops_report_rejects_current_cas_corruption_and_resets_scope(tmp_path, monkeypatch):
    """A warm structural token cannot hide source corruption during one command."""
    from proofmap import paper_sources
    from proofmap.campaign import conops, reports

    real_report = reports.write_campaign_report
    observed = {}

    def corrupt_then_report(store, campaign_id, report_out, **inputs):
        session = paper_sources.locator_validation_session()
        # The enclosing CONOPS command must own the scope before the report starts.
        assert paper_sources.locator_validation_session() is session
        selected = store.current_snapshot(campaign_id)["selections"][0]
        stored = store.inspect(selected["run_id"])
        source_sha = next(iter(stored["artifacts"].values()))
        source = store.root / "objects" / source_sha[:2] / source_sha[2:]
        original = source.read_bytes()
        assert artifact_digest(original) == source_sha
        observed.update(session=session, real_report_called=False)
        try:
            source.write_bytes(original + b"\n% corrupted after validated source read\n")
            assert artifact_digest(source.read_bytes()) != source_sha
            observed["real_report_called"] = True
            try:
                return real_report(store, campaign_id, report_out, **inputs)
            except ValueError as exc:
                observed["real_report_error"] = str(exc)
                raise
        finally:
            source.write_bytes(original)

    monkeypatch.setattr(reports, "write_campaign_report", corrupt_then_report)
    # This fault targets source/report freshness. The separate replay/protocol
    # regressions retain their real assertions; avoid another unrelated pilot here.
    monkeypatch.setattr(
        conops,
        "_recorded_extraction",
        lambda *args: {"test_double": "UNRELATED_REPLAY_PILOT_NOT_EXERCISED"},
    )
    out = tmp_path / "offline-fault"
    with pytest.raises(ValueError, match="CORRUPT_CAS_OBJECT"):
        conops.run_research_conops(out, fixtures=ROOT / "tests/fixtures/campaign/operational")
    assert observed["real_report_called"] is True
    assert observed["real_report_error"] == "CORRUPT_CAS_OBJECT"
    assert not (out / "report/campaign-report.json").exists()
    assert not (out / "campaign-outcomes.json").exists()
    fresh = paper_sources.locator_validation_session()
    assert fresh is not observed["session"]
    # No active context remains after the command's exception.
    assert paper_sources.locator_validation_session() is not fresh
