"""Validate actual pip-audit artifact shape without requiring project publication."""

from copy import deepcopy

import pytest

from proofmap.integrity import artifact_digest, write_json
from scripts.check_alpha_acceptance import validate_report

IDENTITY = {
    "tested_commit": "a" * 40,
    "git_tree": "b" * 40,
    "source_fingerprint": "c" * 64,
    "pr_head": None,
    "run_id": "dependency-audit-contract-test",
    "run_attempt": "1",
    "package_version": "0.6.0",
    "manifest_sha256": "d" * 64,
}
PROJECT = "proof-map-boundary-analysis"


def clean_audit():
    return {
        "dependencies": [
            {"name": "jsonschema", "version": "4.26.0", "vulns": []},
            {"name": "cryptography", "version": "50.0.1", "vulns": []},
            {
                "name": PROJECT,
                "skip_reason": (
                    "Dependency not found on PyPI and could not be audited: " + PROJECT + " (0.6.0)"
                ),
            },
        ],
        "fixes": [],
    }


def observed_report(tmp_path, audit):
    path = tmp_path / "audit.json"
    write_json(path, audit)
    return {
        "schema_version": "1.0",
        "identity": deepcopy(IDENTITY),
        "job": "dependency-audit",
        "profile": "dependency-audit",
        "kind": "command",
        "status": "PASS",
        "exit_code": 0,
        "tests": [],
        "artifacts": [
            {
                "name": "dependency-audit",
                "path": "audit.json",
                "sha256": artifact_digest(path.read_bytes()),
            }
        ],
    }


@pytest.mark.parametrize("self_package", ["unpublished", "audited", "absent"])
def test_clean_dependency_artifact_keeps_unpublished_self_explicit(tmp_path, self_package):
    audit = clean_audit()
    if self_package == "audited":
        audit["dependencies"][-1] = {"name": PROJECT, "version": "0.6.0", "vulns": []}
    elif self_package == "absent":
        audit["dependencies"].pop()
    report = observed_report(tmp_path, audit)
    assert not validate_report(report, IDENTITY, tmp_path)
    if self_package == "unpublished":
        assert audit["dependencies"][-1]["skip_reason"].endswith(PROJECT + " (0.6.0)")


@pytest.mark.parametrize(
    "mutation",
    [
        "empty",
        "only_self",
        "missing_dependencies",
        "dependencies_not_array",
        "wrong_top_type",
        "unknown_top_field",
        "fixes_not_array",
        "fixes_applied",
        "invalid_row",
        "invalid_name",
        "duplicate",
        "normalized_duplicate",
        "missing_version",
        "version_boolean",
        "version_blank",
        "missing_vulns",
        "vulns_not_array",
        "vulnerable",
        "unknown_package_field",
        "third_party_skipped",
        "self_other_skip",
        "self_wrong_version",
        "self_skip_extra_fields",
        "audited_self_wrong_version",
    ],
)
def test_invalid_incomplete_or_vulnerable_dependency_artifacts_fail(tmp_path, mutation):
    audit = clean_audit()
    rows = audit["dependencies"]
    if mutation == "empty":
        rows.clear()
    elif mutation == "only_self":
        rows[:] = rows[-1:]
    elif mutation == "missing_dependencies":
        audit.pop("dependencies")
    elif mutation == "dependencies_not_array":
        audit["dependencies"] = {}
    elif mutation == "wrong_top_type":
        audit = []
    elif mutation == "unknown_top_field":
        audit["ignored_vulnerabilities"] = True
    elif mutation == "fixes_not_array":
        audit["fixes"] = None
    elif mutation == "fixes_applied":
        audit["fixes"] = [{"name": "jsonschema", "new_version": "future"}]
    elif mutation == "invalid_row":
        rows[0] = "jsonschema"
    elif mutation == "invalid_name":
        rows[0]["name"] = ""
    elif mutation == "duplicate":
        rows.append(deepcopy(rows[0]))
    elif mutation == "normalized_duplicate":
        rows.append({"name": "Proof_Map.Boundary_Analysis", "version": "0.6.0", "vulns": []})
    elif mutation == "missing_version":
        rows[0].pop("version")
    elif mutation == "version_boolean":
        rows[0]["version"] = True
    elif mutation == "version_blank":
        rows[0]["version"] = " "
    elif mutation == "missing_vulns":
        rows[0].pop("vulns")
    elif mutation == "vulns_not_array":
        rows[0]["vulns"] = None
    elif mutation == "vulnerable":
        rows[0]["vulns"] = [{"id": "SYNTHETIC-ADVISORY", "fix_versions": []}]
    elif mutation == "unknown_package_field":
        rows[0]["ignored"] = True
    elif mutation == "third_party_skipped":
        rows[0] = {"name": "jsonschema", "skip_reason": "Could not audit"}
    elif mutation == "self_other_skip":
        rows[-1]["skip_reason"] = "Network failure"
    elif mutation == "self_wrong_version":
        rows[-1]["skip_reason"] = rows[-1]["skip_reason"].replace("0.6.0", "0.5.0")
    elif mutation == "self_skip_extra_fields":
        rows[-1]["vulns"] = []
    else:
        rows[-1] = {"name": PROJECT, "version": "0.5.0", "vulns": []}
    report = observed_report(tmp_path, audit)
    assert any(
        "DEPENDENCY_AUDIT_" in error for error in validate_report(report, IDENTITY, tmp_path)
    )


@pytest.mark.parametrize("field", ["job", "profile"])
def test_dependency_artifact_requires_its_actual_producer(tmp_path, field):
    report = observed_report(tmp_path, clean_audit())
    report[field] = "package-build"
    assert any(
        "WRONG_ARTIFACT_EXECUTION_PROFILE" in error
        for error in validate_report(report, IDENTITY, tmp_path)
    )
