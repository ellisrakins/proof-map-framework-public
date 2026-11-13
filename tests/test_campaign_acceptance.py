"""The fixed operational contract consumes current evidence fail closed."""

from copy import deepcopy
from pathlib import Path

import pytest

from proofmap.integrity import artifact_digest, load_json, write_json
from scripts import check_alpha_acceptance as alpha_checker
from scripts import check_campaign_acceptance as checker
from scripts.ci_required import REQUIRED, accepted

ROOT = Path(__file__).resolve().parents[1]
IDENTITY = {
    "tested_commit": "a" * 40,
    "git_tree": "b" * 40,
    "source_fingerprint": "c" * 64,
    "pr_head": None,
    "run_id": "123",
    "run_attempt": "1",
    "package_version": "0.9.0b1",
    "manifest_sha256": "d" * 64,
}


def contract():
    return load_json(ROOT / "acceptance/research_campaign_conops_v1.json")


def test_fixed_op_inventory_cannot_delete_duplicate_or_add():
    original = contract()
    assert checker.check_contract(original) == []
    for rows in (
        original["requirements"][:-1],
        original["requirements"] + [original["requirements"][0]],
        original["requirements"] + [{**original["requirements"][0], "id": "OP-11"}],
    ):
        altered = {**original, "requirements": rows}
        assert "CAMPAIGN_MANDATORY_INVENTORY_CHANGED" in checker.check_contract(altered)


def test_missing_campaign_execution_and_current_alpha_never_qualify():
    result = checker.evaluate(contract(), [], IDENTITY, {})
    assert not result["ready"]
    assert result["counts"]["UNEXECUTED"] == 10
    assert "PRESERVED_ALPHA_NOT_QUALIFIED_FOR_CANDIDATE" in result["errors"]
    assert result["live_model_quality"] == "NOT_MEASURED"


def test_campaign_selector_and_optional_quality_bindings_cannot_be_weakened():
    value = contract()
    value["requirements"][0]["negative_tests"] = ["tests/fabricated.py::test_pass"]
    assert "CAMPAIGN_MANDATORY_BINDINGS_CHANGED" in checker.check_contract(value)
    value = contract()
    value["optional_states"]["live_model_quality"] = "PASS"
    assert "CAMPAIGN_OPTIONAL_STATE_INFLATED" in checker.check_contract(value)


def test_summary_counts_do_not_substitute_for_all_frozen_alpha_rows():
    invented = {
        "schema_version": "1.0",
        "ready": True,
        "status": "READY",
        "identity": IDENTITY,
        "counts": {"PASS": 81, "FAIL": 0, "UNEXECUTED": 0},
        "errors": [],
        "requirements": [],
    }
    result = checker.evaluate(contract(), [], IDENTITY, invented)
    assert result["software_alpha_regression"] == "UNEXECUTED"
    assert "PRESERVED_ALPHA_NOT_QUALIFIED_FOR_CANDIDATE" in result["errors"]


@pytest.mark.parametrize(
    ("case", "expected_state"),
    [
        ("complete_pass", "PASS"),
        ("observed_failure", "FAIL"),
        ("unexecuted_row", "UNEXECUTED"),
        ("stale_failure", "UNEXECUTED"),
        ("incomplete_failure", "UNEXECUTED"),
        ("unreconciled_failure", "UNEXECUTED"),
        ("unobserved_gap", "UNEXECUTED"),
    ],
)
def test_alpha_regression_state_distinguishes_observed_failure_from_missing_execution(
    case, expected_state
):
    frozen = load_json(ROOT / "acceptance/paper_ci_alpha.json")
    # Synthetic consumer input, never qualification evidence. Use the preserved
    # alpha row evaluator so a failure has its real reason/evidence shape.
    alpha = {
        "schema_version": "1.0",
        "ready": True,
        "status": "READY",
        "identity": deepcopy(IDENTITY),
        "counts": {"PASS": 81, "FAIL": 0, "UNEXECUTED": 0},
        "errors": [],
        "requirements": [
            {
                "category": category,
                "id": row["id"],
                "status": "PASS",
                "reasons": [],
                "evidence": ["SYNTHETIC_CONSUMER_UNIT_CONTRACT_ONLY"],
            }
            for category in ("requirements", "fixture_categories", "scenarios")
            for row in frozen[category]
        ],
    }
    if case != "complete_pass":
        first = frozen["requirements"][0]
        selectors = first["positive_tests"] + first["negative_tests"]
        observed = {
            "job": "python-tests",
            "profile": "python-linux-3.12",
            "kind": "pytest",
            "status": "FAIL",
            "exit_code": 1,
            "tests": [
                {"nodeid": selector, "outcome": "failed" if index == 0 else "passed"}
                for index, selector in enumerate(selectors)
            ],
            "artifacts": [],
        }
        failure = alpha_checker._row_result(first, [observed])
        assert failure["status"] == "FAIL" and failure["evidence"]
        alpha["requirements"][0] = {"category": "requirements", **failure}
        alpha.update(
            ready=False, status="NOT_READY", counts={"PASS": 80, "FAIL": 1, "UNEXECUTED": 0}
        )
        if case == "unexecuted_row":
            alpha["requirements"][0].update(
                status="UNEXECUTED", reasons=["MISSING_PROFILE: python-linux-3.12"], evidence=[]
            )
            alpha["counts"] = {"PASS": 80, "FAIL": 0, "UNEXECUTED": 1}
        elif case == "stale_failure":
            alpha["identity"]["run_attempt"] = "previous-attempt"
        elif case == "incomplete_failure":
            alpha["requirements"].pop()
            alpha["counts"]["PASS"] -= 1
        elif case == "unreconciled_failure":
            alpha["counts"]["FAIL"] = 2
        elif case == "unobserved_gap":
            alpha["requirements"][0].update(reasons=["IMPLEMENTATION_GAP: missing adapter"])
    result = checker.evaluate(contract(), [], IDENTITY, alpha)
    assert result["software_alpha_regression"] == expected_state
    assert result["ready"] is False  # Missing operational producers still block readiness.
    assert result["counts"] == {"PASS": 0, "FAIL": 0, "UNEXECUTED": 10}
    assert ("PRESERVED_ALPHA_NOT_QUALIFIED_FOR_CANDIDATE" in result["errors"]) == (
        expected_state != "PASS"
    )


@pytest.mark.parametrize("state", ["failure", "skipped", "cancelled"])
def test_conops_readiness_is_mandatory(state):
    assert "conops-readiness" in REQUIRED
    results = {name: {"result": "success"} for name in REQUIRED}
    results["conops-readiness"]["result"] = state
    assert not accepted(results)


def test_beta_compatibility_requires_exact_frozen_alpha_and_inventory(tmp_path, monkeypatch):
    assert alpha_checker.successor_package_compatible("0.9.0b1", "0.8.0a1")
    assert not alpha_checker.successor_package_compatible("0.9.0b2", "0.8.0a1")
    destination = tmp_path / "acceptance"
    destination.mkdir()
    for name in (
        "paper_ci_beta_compatibility.json",
        "paper_ci_alpha.json",
        "mandatory_requirements.json",
    ):
        (destination / name).write_bytes((ROOT / "acceptance" / name).read_bytes())
    monkeypatch.setattr(alpha_checker, "ROOT", tmp_path)
    assert alpha_checker.successor_package_compatible("0.9.0b1", "0.8.0a1")
    value = load_json(destination / "paper_ci_beta_compatibility.json")
    value["requirements_preserved"] = 80
    write_json(destination / "paper_ci_beta_compatibility.json", value)
    assert not alpha_checker.successor_package_compatible("0.9.0b1", "0.8.0a1")
    # Updating both a changed manifest and its local profile hash still cannot
    # relabel a different alpha capability contract as the frozen baseline.
    import hashlib

    value["requirements_preserved"] = 81
    changed = destination / "paper_ci_alpha.json"
    changed.write_bytes(changed.read_bytes() + b"\n")
    value["alpha_manifest_sha256"] = hashlib.sha256(changed.read_bytes()).hexdigest()
    write_json(destination / "paper_ci_beta_compatibility.json", value)
    assert not alpha_checker.successor_package_compatible("0.9.0b1", "0.8.0a1")


def test_stale_identity_and_wrong_artifact_producer_fail_before_loading(tmp_path):
    report = {
        "schema_version": "1.0",
        "identity": deepcopy(IDENTITY),
        "job": "package-build",
        "profile": "installed-campaign-offline",
        "kind": "command",
        "status": "PASS",
        "exit_code": 0,
        "tests": [],
        "artifacts": [
            {"name": "campaign-isolated-outcomes", "path": "outcomes.json", "sha256": "e" * 64}
        ],
    }
    report["identity"]["source_fingerprint"] = "f" * 64
    errors = checker.validate_campaign_report(report, IDENTITY, tmp_path)
    assert any("IDENTITY" in error for error in errors)
    assert "CAMPAIGN_ARTIFACT_PRODUCER_OR_INVENTORY" in errors


def test_workflow_consumer_waits_for_alpha_and_never_reexecutes_producers():
    import re

    text = (ROOT / ".github/workflows/ci.yml").read_text()
    match = re.search(r"^  conops-readiness:\n(.*?)(?=^  [\w-]+:|\Z)", text, re.M | re.S)
    assert match is not None
    job = match[1]
    assert "if: always()" in job and "needs: [alpha-readiness]" in job
    assert "check_campaign_acceptance.py" in job
    assert "python -m pytest" not in job and "campaign_installed_scenarios.py" not in job


@pytest.fixture
def realism_artifact(campaign_offline_realism):
    directory, value = campaign_offline_realism
    path = directory / "realism-outcomes.json"
    report = {
        "schema_version": "1.0",
        "identity": deepcopy(IDENTITY),
        "job": "paper-ci-fixtures",
        "profile": "campaign-realism",
        "kind": "command",
        "status": "PASS",
        "exit_code": 0,
        "tests": [],
        "artifacts": [
            {
                "name": "campaign-realism-outcomes",
                "path": path.name,
                "sha256": artifact_digest(path.read_bytes()),
            }
        ],
    }
    return directory, value, report


def test_consumer_reads_rights_backed_artifact_and_rechecks_exact_bytes(realism_artifact, tmp_path):
    directory, value, report = realism_artifact
    assert checker.validate_campaign_report(report, IDENTITY, directory) == []
    path = tmp_path / "realism-outcomes.json"
    write_json(path, value)
    path.write_bytes(path.read_bytes() + b" ")
    errors = checker.validate_campaign_report(report, IDENTITY, tmp_path)
    assert any("CAMPAIGN_ARTIFACT_BYTES" in error for error in errors)
    altered = deepcopy(report)
    altered["artifacts"][0]["path"] = "../realism-outcomes.json"
    assert checker.validate_campaign_report(altered, IDENTITY, directory)
    assert checker.validate_campaign_report(report, IDENTITY, None)


@pytest.mark.parametrize(
    "attack",
    [
        "invented_verified",
        "quality_label",
        "invalid_anchor",
        "collapsed_authors",
        "false_inventory",
        "wrong_totals",
    ],
)
def test_realism_consumer_rejects_inflated_measurements(realism_artifact, attack, tmp_path):
    _, original, report = realism_artifact
    value = deepcopy(original)
    if attack == "invented_verified":
        value["documents"][0]["verified_claims"] = 1
    elif attack == "quality_label":
        value["documents"][0]["novelty"] = 1.0
    elif attack == "invalid_anchor":
        value["documents"][0]["anchors_valid"] -= 1
    elif attack == "collapsed_authors":
        for row in value["documents"]:
            row["author"] = "single author"
    elif attack == "false_inventory":
        value["documents_total"] += 1
    else:
        value["source_anchor_validity"]["total"] += 1
    path = tmp_path / "realism-outcomes.json"
    write_json(path, value)
    altered = deepcopy(report)
    altered["artifacts"][0]["sha256"] = artifact_digest(path.read_bytes())
    errors = checker.validate_campaign_report(altered, IDENTITY, tmp_path)
    assert any("INVALID_CAMPAIGN_ARTIFACT" in error for error in errors)


def test_consumer_requires_unique_reports_and_all_profiles_after_complete_alpha(realism_artifact):
    directory, _, report = realism_artifact
    frozen = load_json(ROOT / "acceptance/paper_ci_alpha.json")
    # Deliberately synthetic envelope tests the consumer conjunction only;
    # no output from this test is qualification evidence for the candidate.
    alpha = {
        "schema_version": "1.0",
        "ready": True,
        "status": "READY",
        "identity": IDENTITY,
        "counts": {"PASS": 81, "FAIL": 0, "UNEXECUTED": 0},
        "errors": [],
        "requirements": [
            {
                "category": category,
                "id": row["id"],
                "status": "PASS",
                "reasons": [],
                "evidence": ["SYNTHETIC_CONSUMER_UNIT_CONTRACT_ONLY"],
            }
            for category in ("requirements", "fixture_categories", "scenarios")
            for row in frozen[category]
        ],
    }
    result = checker.evaluate(contract(), [report], IDENTITY, alpha, [directory])
    assert result["software_alpha_regression"] == "PASS"
    assert result["ready"] is False and result["counts"]["UNEXECUTED"] == 10
    duplicate = checker.evaluate(
        contract(), [report, report], IDENTITY, alpha, [directory, directory]
    )
    assert "DUPLICATE_CAMPAIGN_REPORT" in duplicate["errors"]
    wrong_version = {**IDENTITY, "package_version": "0.9.0b2"}
    result = checker.evaluate(contract(), [], wrong_version, {**alpha, "identity": wrong_version})
    assert any(error.startswith("BETA_RELEASE_VERSION_PENDING") for error in result["errors"])


def test_acceptance_cli_records_missing_inputs_without_executing_producers(
    tmp_path,
    capsys,
    monkeypatch,
):
    monkeypatch.setattr("scripts.alpha_evidence.identity", lambda *args: deepcopy(IDENTITY))
    destination = tmp_path / "acceptance.json"
    code = checker.main(
        [
            "--evidence-dir",
            str(tmp_path),
            "--alpha",
            str(tmp_path / "missing.json"),
            "--out",
            str(destination),
        ]
    )
    value = load_json(destination)
    assert code == 1 and value["status"] == "NOT_READY"
    assert value["ready"] is False
    assert any(error.startswith("INVALID_INPUT") for error in value["errors"])
    assert "NOT_READY" in capsys.readouterr().out
