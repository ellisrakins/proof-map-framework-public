"""Synthetic installed-contract metadata tests; these do not prove installed execution."""

import zipfile
from copy import deepcopy

import pytest
from test_alpha_acceptance import IDENTITY, contract, evidence
from test_alpha_offline_driver import source_outcomes as source_outcomes

from proofmap.integrity import artifact_digest, write_json
from scripts.check_alpha_acceptance import evaluate
from scripts.paper_alpha_offline import validate_outcomes


def scenario_reports(source_outcomes, folder, *, wheel_version=None):
    # Deliberately tiny contract fixture, never an executable ProofMap package.
    wheel = folder / "contract-only.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(
            "proof_map_boundary_analysis.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: proof-map-boundary-analysis\nVersion: "
            + (wheel_version or IDENTITY["package_version"])
            + "\n",
        )
        archive.writestr("proofmap/__init__.py", "# Synthetic artifact-binding fixture only.\n")
    outcome = deepcopy(source_outcomes)
    outcome["profile"] = "installed-wheel"
    outcome["material"].update(
        installed=True,
        verified_files=1,
        package_version=IDENTITY["package_version"],
        wheel_sha256=artifact_digest(wheel.read_bytes()),
        package_path="/synthetic-contract/site-packages/proofmap",
    )
    scenario = folder / "scenario-contract.json"
    write_json(scenario, outcome)

    def report(profile, name, path):
        return {
            "schema_version": "1.0",
            "identity": deepcopy(IDENTITY),
            "job": "package-build",
            "profile": profile,
            "kind": "command",
            "status": "PASS",
            "exit_code": 0,
            "tests": [],
            "artifacts": [
                {"name": name, "path": path.name, "sha256": artifact_digest(path.read_bytes())}
            ],
        }

    return (
        outcome,
        scenario,
        [
            evidence(),
            report("installed-wheel", "wheel", wheel),
            report("installed-alpha-offline", "alpha-offline-scenarios", scenario),
        ],
    )


def scenario_contract():
    manifest, baseline = contract()
    row = manifest["requirements"][0]
    row["required_jobs"].append("package-build")
    row["required_profiles"] += ["installed-wheel", "installed-alpha-offline"]
    row["test_profiles"] = ["python-linux-3.12"]
    row["expected_artifacts"] = ["wheel", "alpha-offline-scenarios"]
    return manifest, baseline


def test_synthetic_matching_wheel_digest_satisfies_artifact_binding(source_outcomes, tmp_path):
    _, _, reports = scenario_reports(source_outcomes, tmp_path)
    manifest, baseline = scenario_contract()
    result = evaluate(manifest, baseline, reports, IDENTITY, [tmp_path] * len(reports))
    assert result["ready"] is True
    assert not result["errors"]


@pytest.mark.parametrize(
    "mutation", ["different-wheel", "missing-wheel", "wrong-version", "source-only"]
)
def test_installed_scenarios_require_the_current_built_wheel(source_outcomes, tmp_path, mutation):
    outcome, path, reports = scenario_reports(
        source_outcomes, tmp_path, wheel_version="0.0.0" if mutation == "wrong-version" else None
    )
    if mutation == "different-wheel":
        outcome["material"]["wheel_sha256"] = "f" * 64
    elif mutation == "missing-wheel":
        reports.pop(1)
    elif mutation == "source-only":
        outcome = deepcopy(source_outcomes)
    write_json(path, outcome)
    reports[-1]["artifacts"][0]["sha256"] = artifact_digest(path.read_bytes())
    manifest, baseline = scenario_contract()
    result = evaluate(manifest, baseline, reports, IDENTITY, [tmp_path] * len(reports))
    assert not result["ready"]
    if mutation == "source-only":
        assert any(
            "Actual installed-wheel evidence required" in reason for reason in result["errors"]
        )
    else:
        assert "INSTALLED_SCENARIO_WHEEL_MISMATCH" in result["errors"]


@pytest.mark.parametrize(
    "mutation",
    [
        "empty-commands",
        "failed-command",
        "missing-query",
        "boolean-exit",
        "empty-candidates",
        "duplicate-candidates",
        "malformed-candidate",
        "zero-digital-pages",
        "zero-scanned-pages",
    ],
)
def test_offline_diagnostics_cannot_contradict_measured_outcomes(source_outcomes, mutation):
    value = deepcopy(source_outcomes)
    provider = value["scenarios"]["D"]["provider"]
    if mutation == "empty-commands":
        value["commands"] = []
    elif mutation == "failed-command":
        value["commands"][0]["returncode"] = 1
    elif mutation == "missing-query":
        value["commands"] = [row for row in value["commands"] if row["command"] != "query"]
    elif mutation == "boolean-exit":
        value["commands"][0]["returncode"] = False
    elif mutation == "empty-candidates":
        provider["candidate_ids"] = provider["replayed_candidate_ids"] = []
    elif mutation == "duplicate-candidates":
        provider["candidate_ids"] = provider["replayed_candidate_ids"] = [
            provider["candidate_ids"][0]
        ] * provider["candidate_count"]
    elif mutation == "malformed-candidate":
        provider["candidate_ids"][0] = "not-a-digest"
        provider["replayed_candidate_ids"] = provider["candidate_ids"].copy()
    else:
        name = "born_digital.pdf" if mutation == "zero-digital-pages" else "scan.pdf"
        value["scenarios"]["D"]["pdf"][name]["pages"] = 0
    with pytest.raises(ValueError):
        validate_outcomes(value, require_installed=False)
