"""Readiness must fail closed on incomplete or stale execution evidence."""

from copy import deepcopy

import pytest

from proofmap.integrity import artifact_digest, load_json, write_json
from scripts.check_alpha_acceptance import check_contract, evaluate, validate_report

IDENTITY = {
    "tested_commit": "a" * 40,
    "git_tree": "b" * 40,
    "source_fingerprint": "c" * 64,
    "pr_head": None,
    "run_id": "123",
    "run_attempt": "1",
    "package_version": "0.8.0a1",
    "manifest_sha256": "d" * 64,
}


def contract():
    row = {
        "id": "R001",
        "original_section": "3",
        "source": "original.md",
        "area": "C01",
        "normative_behavior": "A bounded fixture contract",
        "supported_domain": "Test contract",
        "implementation": ["proofmap/paper.py"],
        "positive_tests": ["tests/test_example.py::test_positive"],
        "negative_tests": ["tests/test_example.py::test_negative"],
        "required_profiles": ["python-linux-3.12"],
        "required_jobs": ["python-tests"],
        "expected_artifacts": [],
        "implementation_status": "already_implemented",
        "gap": "",
    }
    fixture = {
        "id": "F01",
        "description": "Original fixture",
        "positive_tests": row["positive_tests"],
        "negative_tests": row["negative_tests"],
        "required_jobs": row["required_jobs"],
        "required_profiles": row["required_profiles"],
        "gap": "",
    }
    scenario = {
        k: deepcopy(v)
        for k, v in row.items()
        if k
        not in {
            "original_section",
            "source",
            "area",
            "normative_behavior",
            "supported_domain",
            "implementation",
        }
    }
    scenario.update(id="A", description="Integrated scenario")
    manifest = {
        "schema_version": "1.0",
        "contract_id": "paper-ci-alpha",
        "target_version": "0.8.0a1",
        "baseline_ref": "acceptance/mandatory_requirements.json",
        "requirements": [row],
        "fixture_categories": [fixture],
        "scenarios": [scenario],
        "exclusions": [],
    }
    baseline = {
        "schema_version": "1.0",
        "contract_id": "paper-ci-alpha",
        "requirements": [
            {
                k: row[k]
                for k in (
                    "id",
                    "original_section",
                    "source",
                    "area",
                    "normative_behavior",
                    "supported_domain",
                )
            }
        ],
        "fixture_category_ids": ["F01"],
        "scenario_ids": ["A"],
        "fixture_categories": [{"id": "F01", "description": "Original fixture"}],
        "scenarios": [{"id": "A", "description": "Integrated scenario"}],
    }
    return manifest, baseline


def evidence():
    return {
        "schema_version": "1.0",
        "identity": deepcopy(IDENTITY),
        "job": "python-tests",
        "profile": "python-linux-3.12",
        "kind": "pytest",
        "status": "PASS",
        "exit_code": 0,
        "tests": [
            {"nodeid": "tests/test_example.py::test_positive", "outcome": "passed"},
            {"nodeid": "tests/test_example.py::test_negative", "outcome": "passed"},
        ],
        "artifacts": [],
    }


def test_current_positive_and_negative_execution_satisfies_contract():
    manifest, baseline = contract()
    result = evaluate(manifest, baseline, [evidence()], IDENTITY)
    assert result["ready"] is True
    assert result["counts"] == {"PASS": 3, "FAIL": 0, "UNEXECUTED": 0}


def test_explicit_selector_profiles_preserve_all_mandatory_jobs():
    from scripts.check_alpha_acceptance import _row_result

    manifest, _ = contract()
    row = manifest["requirements"][0]
    row["required_profiles"] += ["linux-unit"]
    row["required_jobs"] += ["schema-migration"]
    row["test_profiles"] = ["python-linux-3.12"]
    secondary = deepcopy(evidence())
    secondary.update(job="schema-migration", profile="linux-unit")
    secondary["tests"] = [{"nodeid": "tests/test_schema.py::test_schema", "outcome": "passed"}]
    assert _row_result(row, [evidence(), secondary])["status"] == "PASS"
    assert _row_result(row, [evidence()])["status"] == "UNEXECUTED"
    secondary.update(status="FAIL", exit_code=1)
    assert _row_result(row, [evidence(), secondary])["status"] == "FAIL"


@pytest.mark.parametrize("profiles", [["absent"], ["linux-unit"]])
def test_explicit_selector_profile_cannot_waive_unexecuted_tests(profiles):
    from scripts.check_alpha_acceptance import _row_result

    manifest, _ = contract()
    row = manifest["requirements"][0]
    row["test_profiles"] = profiles
    result = _row_result(row, [evidence()])
    assert result["status"] == "FAIL"
    assert "TEST_PROFILE_OUTSIDE_REQUIRED_PROFILES" in result["reasons"]
    assert any(reason.startswith("ZERO_COLLECTED_SELECTOR") for reason in result["reasons"])


@pytest.mark.parametrize("field", ["requirements", "fixture_categories", "scenarios"])
def test_deleted_mandatory_contract_members_fail(field):
    manifest, baseline = contract()
    manifest[field] = []
    assert check_contract(manifest, baseline)
    assert not evaluate(manifest, baseline, [evidence()], IDENTITY)["ready"]


@pytest.mark.parametrize("field", ["normative_behavior", "original_section", "supported_domain"])
def test_inherited_scope_cannot_silently_change(field):
    manifest, baseline = contract()
    manifest["requirements"][0][field] = "weaker requirement"
    assert check_contract(manifest, baseline)


@pytest.mark.parametrize("outcome", ["failed", "skipped", "xfailed", "xpassed", "error"])
def test_mandatory_nonpass_is_never_success(outcome):
    manifest, baseline = contract()
    report = evidence()
    report["tests"][1]["outcome"] = outcome
    result = evaluate(manifest, baseline, [report], IDENTITY)
    assert not result["ready"]
    assert result["counts"]["FAIL"] == 3


@pytest.mark.parametrize("field", list(IDENTITY))
def test_stale_or_mixed_identity_fails(field):
    manifest, baseline = contract()
    report = evidence()
    report["identity"][field] = (
        "e" * 64
        if field.endswith("sha256") or field == "source_fingerprint"
        else "e" * 40
        if field in {"tested_commit", "git_tree", "pr_head"}
        else "other"
    )
    if field == "run_attempt":
        report["identity"][field] = "2"
    result = evaluate(manifest, baseline, [report], IDENTITY)
    assert not result["ready"]
    assert any("IDENTITY_MISMATCH" in issue for issue in result["errors"])


def test_zero_collected_selector_and_missing_negative_test_fail():
    manifest, baseline = contract()
    report = evidence()
    report["tests"].pop()
    result = evaluate(manifest, baseline, [report], IDENTITY)
    assert not result["ready"]
    assert result["counts"]["UNEXECUTED"] == 3
    manifest["requirements"][0]["negative_tests"] = []
    assert not evaluate(manifest, baseline, [evidence()], IDENTITY)["ready"]


def test_optional_skips_do_not_replace_required_profile_execution():
    manifest, baseline = contract()
    report = evidence()
    report["tests"].append(
        {"nodeid": "tests/test_optional.py::test_optional", "outcome": "skipped"}
    )
    assert evaluate(manifest, baseline, [report], IDENTITY)["ready"]
    report["profile"] = "python-windows-3.12"
    assert not evaluate(manifest, baseline, [report], IDENTITY)["ready"]


def test_every_required_pytest_profile_must_collect_each_selector():
    manifest, baseline = contract()
    manifest["requirements"][0]["required_profiles"].append("python-windows-3.12")
    windows = evidence()
    windows["profile"] = "python-windows-3.12"
    windows["tests"] = [{"nodeid": "tests/test_other.py::test_other", "outcome": "passed"}]
    result = evaluate(manifest, baseline, [evidence(), windows], IDENTITY)
    assert not result["ready"]
    assert any("python-windows-3.12" in reason for reason in result["requirements"][0]["reasons"])


@pytest.mark.parametrize("field", ["fixture_categories", "scenarios"])
def test_fixture_and_scenario_scope_cannot_silently_change(field):
    manifest, baseline = contract()
    manifest[field][0]["description"] = "weaker behavior"
    assert check_contract(manifest, baseline)


def test_duplicate_reports_and_duplicate_test_ids_fail():
    manifest, baseline = contract()
    assert not evaluate(manifest, baseline, [evidence(), evidence()], IDENTITY)["ready"]
    report = evidence()
    report["tests"].append(deepcopy(report["tests"][0]))
    assert not evaluate(manifest, baseline, [report], IDENTITY)["ready"]


def test_parametrized_selector_requires_every_collected_case():
    manifest, baseline = contract()
    report = evidence()
    report["tests"][0]["nodeid"] += "[first]"
    report["tests"].append(
        {"nodeid": "tests/test_example.py::test_positive[second]", "outcome": "passed"}
    )
    assert evaluate(manifest, baseline, [report], IDENTITY)["ready"]
    report["tests"][-1]["outcome"] = "skipped"
    assert not evaluate(manifest, baseline, [report], IDENTITY)["ready"]


def test_implementation_label_is_never_execution_evidence():
    manifest, baseline = contract()
    assert not evaluate(manifest, baseline, [], IDENTITY)["ready"]
    manifest["requirements"][0]["implementation_status"] = "needs_work"
    assert not evaluate(manifest, baseline, [evidence()], IDENTITY)["ready"]


@pytest.mark.parametrize("mutation", ["missing", "unknown", "zero", "failure"])
def test_malformed_or_failed_reports_fail(mutation):
    manifest, baseline = contract()
    report = evidence()
    if mutation == "missing":
        report.pop("identity")
    elif mutation == "unknown":
        report["trusted"] = True
    elif mutation == "zero":
        report["tests"] = []
    else:
        report["exit_code"] = 1
    assert not evaluate(manifest, baseline, [report], IDENTITY)["ready"]


def wheel_report(tmp_path):
    import zipfile

    path = tmp_path / "package.whl"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "proof_map_boundary_analysis-0.8.0a1.dist-info/METADATA",
            "Name: proof-map-boundary-analysis\nVersion: 0.8.0a1\n",
        )
    report = evidence()
    report.update(
        job="package-build",
        profile="installed-wheel",
        kind="command",
        tests=[],
        artifacts=[
            {"name": "wheel", "path": "package.whl", "sha256": artifact_digest(path.read_bytes())}
        ],
    )
    return report, path


def test_current_wheel_bytes_and_metadata_are_checked(tmp_path):
    report, path = wheel_report(tmp_path)
    assert not validate_report(report, IDENTITY, tmp_path)
    path.write_bytes(b"tampered")
    assert any("DIGEST" in x for x in validate_report(report, IDENTITY, tmp_path))


@pytest.mark.parametrize(
    "case", ["missing", "invalid_zip", "wrong_version", "outside", "wrong_profile"]
)
def test_missing_malformed_unbound_or_unsafe_artifacts_fail(tmp_path, case):
    report, path = wheel_report(tmp_path)
    expected = deepcopy(IDENTITY)
    if case == "missing":
        path.unlink()
    elif case == "invalid_zip":
        path.write_bytes(b"not a zip")
        report["artifacts"][0]["sha256"] = artifact_digest(path.read_bytes())
    elif case == "wrong_version":
        expected["package_version"] = report["identity"]["package_version"] = "0.6.0"
    elif case == "outside":
        report["artifacts"][0]["path"] = "../package.whl"
    else:
        report["profile"] = "python-linux-3.12"
    assert validate_report(report, expected, tmp_path)


def test_generic_docker_report_cannot_substitute_for_actual_isolated_driver(tmp_path):
    path = tmp_path / "outcomes.json"
    write_json(path, {"status": "PASS", "authentication": "EPHEMERAL_TEST_AUTHORITY_ONLY"})
    report = evidence()
    report.update(
        job="sandbox-security",
        profile="linux-sandbox",
        kind="command",
        tests=[],
        artifacts=[
            {
                "name": "isolated-paper-outcomes",
                "path": "outcomes.json",
                "sha256": artifact_digest(path.read_bytes()),
            }
        ],
    )
    assert any(
        "WRONG_ARTIFACT_EXECUTION_PROFILE" in issue
        for issue in validate_report(report, IDENTITY, tmp_path)
    )
    report.update(job="paper-e2e-isolated", profile="linux-isolated")
    assert validate_report(report, IDENTITY, tmp_path)


def test_missing_expected_execution_artifact_is_unexecuted():
    manifest, baseline = contract()
    manifest["requirements"][0]["expected_artifacts"] = ["isolated-paper-outcomes"]
    result = evaluate(manifest, baseline, [evidence()], IDENTITY)
    assert not result["ready"]
    assert "MISSING_ARTIFACT: isolated-paper-outcomes" in result["requirements"][0]["reasons"]


def test_contract_duplicate_ids_and_future_version_fail():
    manifest, baseline = contract()
    manifest["requirements"].append(deepcopy(manifest["requirements"][0]))
    assert check_contract(manifest, baseline)
    manifest, baseline = contract()
    manifest["schema_version"] = "99.0"
    assert check_contract(manifest, baseline)


def test_release_version_cannot_be_promoted_by_green_tests():
    manifest, baseline = contract()
    report = evidence()
    expected = deepcopy(IDENTITY)
    expected["package_version"] = report["identity"]["package_version"] = "0.6.0"
    result = evaluate(manifest, baseline, [report], expected)
    assert not result["ready"]
    assert "RELEASE_VERSION_PENDING: 0.6.0" in result["errors"]


def test_command_cannot_substitute_for_required_test_profile():
    manifest, baseline = contract()
    manifest["requirements"][0]["required_profiles"].append("python-windows-3.12")
    windows = evidence()
    windows.update(profile="python-windows-3.12", kind="command", tests=[])
    assert not evaluate(manifest, baseline, [evidence(), windows], IDENTITY)["ready"]


def test_real_execution_profile_cannot_omit_its_artifact():
    report = evidence()
    report.update(job="paper-e2e-isolated", profile="linux-isolated", kind="command", tests=[])
    assert "PROFILE_REQUIRES_ARTIFACT: isolated-paper-outcomes" in validate_report(
        report, IDENTITY, None
    )


def test_repository_contract_is_complete_and_matches_frozen_scope():
    from scripts.check_alpha_acceptance import BASELINE_SHA256, ROOT

    baseline = ROOT / "acceptance/mandatory_requirements.json"
    manifest = load_json(ROOT / "acceptance/paper_ci_alpha.json")
    assert artifact_digest(baseline.read_bytes()) == BASELINE_SHA256
    assert not check_contract(manifest, load_json(baseline))
    assert {r["id"] for r in manifest["requirements"]} == {
        *(f"R{i:03}" for i in range(1, 53)),
        *(f"C{i:02}" for i in range(1, 13)),
    }


def test_cli_writes_honest_missing_evidence_summary(tmp_path, monkeypatch):
    from scripts.check_alpha_acceptance import main

    output = tmp_path / "alpha-acceptance.json"
    summary = tmp_path / "alpha-acceptance.md"
    monkeypatch.setenv("ALPHA_RUN_ID", "unit-gate-command")
    # This unit checks absent-evidence presentation. Real Git/source identity is
    # exercised in test_alpha_evidence, including outside-checkout execution.
    monkeypatch.setattr(
        "scripts.alpha_evidence.identity", lambda root, manifest: deepcopy(IDENTITY)
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "check_alpha_acceptance",
            "--evidence-dir",
            str(tmp_path / "missing"),
            "--out",
            str(output),
            "--summary",
            str(summary),
        ],
    )
    assert main() == 1
    result = load_json(output)
    assert result["status"] == "NOT_READY"
    assert sum(result["counts"].values()) == 81
    assert result["counts"]["PASS"] == 0
    assert "NOT_READY" in summary.read_text()


def test_cli_rejects_changed_mandatory_baseline_before_reading_evidence(tmp_path, monkeypatch):
    from scripts import check_alpha_acceptance as checker

    output = tmp_path / "alpha-acceptance.json"
    monkeypatch.setattr(checker, "BASELINE_SHA256", "0" * 64)
    monkeypatch.setattr(
        "sys.argv",
        ["check_alpha_acceptance", "--evidence-dir", str(tmp_path), "--out", str(output)],
    )
    assert checker.main() == 1
    assert "MANDATORY_BASELINE_CHANGED" in load_json(output)["errors"][0]
