"""Fail-closed bounded alpha readiness from current execution reports, never labels.

Reports are evidence from the trusted software workflow, not signed mathematical
authority. This checker never executes selectors or commands from the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

# Allow direct script use as well as module imports by pytest.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proofmap.integrity import load_json, relative_path, rooted_path, write_json

ROOT = Path(__file__).resolve().parents[1]
BASELINE_SHA256 = "1d8f46267600b65eaee74755d1bc86845da60cb29d1a48e1486b3064d11fe30e"
FROZEN_ALPHA_MANIFEST_SHA256 = "7ff8e38f9fa0aad8a2eb396406dd8042817cef19add80c2475cd13985ca9dfc0"
NORMATIVE_FIELDS = (
    "id",
    "original_section",
    "source",
    "area",
    "normative_behavior",
    "supported_domain",
)
MAX_REPORT_BYTES = 64_000_000
ARTIFACT_PRODUCERS = {
    "partitioned-regression-outcomes": ("windows-regression", "partitioned-regression"),
    "installed-regression-outcomes": ("python-tests", "installed-regression"),
    "alpha-isolated-scenarios": ("paper-e2e-isolated", "linux-alpha-isolated"),
    "alpha-offline-scenarios": ("package-build", "installed-alpha-offline"),
    "isolated-paper-outcomes": ("paper-e2e-isolated", "linux-isolated"),
    "benchmark": ("paper-ci-fixtures", "benchmark"),
    "wheel": ("package-build", "installed-wheel"),
    "dependency-audit": ("dependency-audit", "dependency-audit"),
}


def successor_package_compatible(package_version: str, target_version: str) -> bool:
    """One reviewed successor preserves exact frozen alpha capability obligations.

    This permits a package version transition only. All existing current-source,
    producer, selector, artifact and execution gates still run unmodified.
    """
    if package_version != "0.9.0b1" or target_version != "0.8.0a1":
        return False
    try:
        profile = load_json(ROOT / "acceptance/paper_ci_beta_compatibility.json")
        return (
            set(profile)
            == {
                "schema_version",
                "profile_id",
                "baseline_version",
                "successor_version",
                "alpha_manifest",
                "alpha_manifest_sha256",
                "mandatory_inventory",
                "mandatory_inventory_sha256",
                "requirements_preserved",
                "capability_scope",
            }
            and profile["schema_version"] == "1.0"
            and profile["profile_id"] == "paper-ci-alpha-preserved-for-campaign-beta"
            and profile["baseline_version"] == target_version
            and profile["successor_version"] == package_version
            and profile["alpha_manifest"] == "acceptance/paper_ci_alpha.json"
            and profile["mandatory_inventory"] == "acceptance/mandatory_requirements.json"
            and profile["mandatory_inventory_sha256"] == BASELINE_SHA256
            and profile["alpha_manifest_sha256"] == FROZEN_ALPHA_MANIFEST_SHA256
            and profile["requirements_preserved"] == 81
            and hashlib.sha256((ROOT / profile["alpha_manifest"]).read_bytes()).hexdigest()
            == profile["alpha_manifest_sha256"]
            and hashlib.sha256((ROOT / profile["mandatory_inventory"]).read_bytes()).hexdigest()
            == profile["mandatory_inventory_sha256"]
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def schema_errors(name: str, value: Any) -> list[str]:
    schema = load_json(ROOT / "schema" / (name + ".schema.json"))
    return [
        "SCHEMA: " + "/".join(map(str, issue.absolute_path)) + ": " + issue.message
        for issue in Draft202012Validator(schema).iter_errors(value)
    ]


def check_contract(manifest: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    errors = schema_errors("alpha_acceptance", manifest)
    if errors:
        return errors
    for field, expected in (
        ("requirements", [r["id"] for r in baseline["requirements"]]),
        ("fixture_categories", baseline["fixture_category_ids"]),
        ("scenarios", baseline["scenario_ids"]),
    ):
        ids = [row["id"] for row in manifest[field]]
        if len(ids) != len(set(ids)) or set(ids) != set(expected):
            errors.append("MANDATORY_SET_CHANGED: " + field)
    before = {r["id"]: r for r in baseline["requirements"]}
    for row in manifest["requirements"]:
        if row["id"] in before and any(row[k] != before[row["id"]][k] for k in NORMATIVE_FIELDS):
            errors.append("INHERITED_SCOPE_CHANGED: " + row["id"])
    for field in ("fixture_categories", "scenarios"):
        normative = {r["id"]: r["description"] for r in baseline[field]}
        for row in manifest[field]:
            if row["id"] in normative and row["description"] != normative[row["id"]]:
                errors.append("INHERITED_SCOPE_CHANGED: " + row["id"])
    return errors


def _dependency_audit(value: Any, expected: dict[str, Any]) -> None:
    """Require audited third-party packages; retain the explicit unpublished-self exception."""
    import re

    if (
        not isinstance(value, dict)
        or set(value) != {"dependencies", "fixes"}
        or value["fixes"] != []
        or not isinstance(value["dependencies"], list)
        or not 1 <= len(value["dependencies"]) <= 10000
    ):
        raise ValueError("DEPENDENCY_AUDIT_SHAPE")
    project = "proof-map-boundary-analysis"
    seen: set[str] = set()
    audited_third_party = 0
    for row in value["dependencies"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("name"), str)
            or not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", row["name"])
        ):
            raise ValueError("DEPENDENCY_AUDIT_PACKAGE")
        name = re.sub(r"[-_.]+", "-", row["name"]).lower()
        if name in seen:
            raise ValueError("DEPENDENCY_AUDIT_DUPLICATE")
        seen.add(name)
        if "skip_reason" in row:
            # The package under development need not be published to PyPI to
            # qualify software. Its exact-version skip remains visible in the
            # retained audit.json; no third-party skip or other reason qualifies.
            permitted = (
                "Dependency not found on PyPI and could not be audited: "
                + project
                + " ("
                + expected["package_version"]
                + ")"
            )
            if (
                set(row) != {"name", "skip_reason"}
                or row["name"] != project
                or row["skip_reason"] != permitted
            ):
                raise ValueError("DEPENDENCY_AUDIT_SKIPPED_PACKAGE")
            continue
        if (
            set(row) != {"name", "version", "vulns"}
            or not isinstance(row["version"], str)
            or not row["version"]
            or any(character.isspace() for character in row["version"])
            or not isinstance(row["vulns"], list)
        ):
            raise ValueError("DEPENDENCY_AUDIT_PACKAGE_SHAPE")
        if row["vulns"]:
            raise ValueError("DEPENDENCY_AUDIT_VULNERABILITIES")
        if name == project:
            if row["version"] != expected["package_version"]:
                raise ValueError("DEPENDENCY_AUDIT_PROJECT_VERSION")
        else:
            audited_third_party += 1
    if not audited_third_party:
        raise ValueError("DEPENDENCY_AUDIT_EMPTY_COVERAGE")


def _artifact(name: str, path: Path, expected: dict[str, Any]) -> None:
    """Check the existing producer's substantive outputs as well as their hashes."""
    if name == "wheel":
        from email.parser import BytesParser

        with zipfile.ZipFile(path) as archive:
            metadata = [n for n in archive.namelist() if n.endswith(".dist-info/METADATA")]
            if len(metadata) != 1:
                raise ValueError("WHEEL_METADATA")
            if archive.getinfo(metadata[0]).file_size > 1_000_000:
                raise ValueError("WHEEL_METADATA_SIZE")
            package = BytesParser().parsebytes(archive.read(metadata[0]))
            if (
                package["Name"] != "proof-map-boundary-analysis"
                or package["Version"] != expected["package_version"]
            ):
                raise ValueError("WHEEL_VERSION")
        return
    value = load_json(path)
    if name == "partitioned-regression-outcomes":
        from scripts.windows_pytest_partitions import validate_outcomes as validate_partitions

        validate_partitions(value, path.parent, expected, ROOT)
        return
    if name == "installed-regression-outcomes":
        from scripts.test_installed_wheel import validate_outcomes as validate_installed_regression

        validate_installed_regression(value, expected_identity=expected)
        return
    if name == "alpha-isolated-scenarios":
        from scripts.check_alpha_scenarios import validate_isolated

        _artifact("isolated-paper-outcomes", path, expected)
        validate_isolated(value)
        return
    if name == "alpha-offline-scenarios":
        from proofmap.integrity import require_digest
        from scripts.paper_alpha_offline import validate_outcomes

        validate_outcomes(value, require_installed=True)
        require_digest(value["material"]["wheel_sha256"])
        if value["material"]["package_version"] != expected["package_version"]:
            raise ValueError("INSTALLED_OFFLINE_VERSION")
        return
    if name == "dependency-audit":
        _dependency_audit(value, expected)
        return
    if name == "benchmark":
        from proofmap.benchmark_validation import validate_benchmark

        validate_benchmark(value, ROOT / "tests/fixtures/papers")
    elif name == "isolated-paper-outcomes":
        from proofmap.attempts import FormalObligation
        from proofmap.evidence_adapter import resolve_execution
        from proofmap.evidence_records import ExecutionEvent, FormalizationBinding, VerifierProfile
        from proofmap.trust import authenticated_record

        if value["status"] != "PASS" or value["authentication"] != "EPHEMERAL_TEST_AUTHORITY_ONLY":
            raise ValueError("ISOLATED_STATUS")
        if value["validator_sha"] != expected["tested_commit"]:
            raise ValueError("ISOLATED_REVISION")
        profile = VerifierProfile.from_dict(value["profile"])
        event = ExecutionEvent.from_dict(value["execution"]["event"]).to_dict()
        replay = ExecutionEvent.from_dict(value["replay"]).to_dict()
        binding = FormalizationBinding.from_dict(value["binding"])
        obligation = FormalObligation.from_dict(value["obligation"])
        for record, envelope in (
            (event, value["execution"]["envelope"]),
            (replay, value["replay_envelope"]),
        ):
            resolved = resolve_execution(
                envelope,
                value["trust_store"],
                binding,
                obligation,
                profile,
                evaluation_time=value["evaluation_time"],
            )
            if not resolved["accepted"] or authenticated_record(envelope) != record:
                raise ValueError("ISOLATED_AUTHENTICATION_OR_MATERIAL: " + resolved["reason"])
        if any(
            e["outcome"] != "VERIFIED"
            or not e["environment"]["complete"]
            or e["environment"]["profile_digest"] != profile.digest
            for e in (event, replay)
        ):
            raise ValueError("ISOLATED_EXECUTION")
        same_material = (
            "binding_digest",
            "revision_id",
            "assertion_id",
            "obligation_digest",
            "profile_digest",
            "candidate_digest",
            "wrapper_digest",
            "snapshot_digest",
            "controller_digest",
            "controller_id",
        )
        if (
            event["parent_event"] is not None
            or replay["parent_event"] != event["id"]
            or any(replay[key] != event[key] for key in same_material)
        ):
            raise ValueError("ISOLATED_REPLAY")
        dimensions = ("ingested", "formalized", "verified", "reviewed", "accepted")
        for phase, vector in (
            ("before_review", (1, 1, 1, 0, 0)),
            ("after_review", (1, 1, 1, 1, 1)),
            ("after_revision", (1, 0, 0, 0, 0)),
        ):
            if (
                not all(type(value[phase][key]) is int for key in dimensions)
                or tuple(value[phase][key] for key in dimensions) != vector
            ):
                raise ValueError("ISOLATED_OUTCOME_VECTOR: " + phase)
        required = {"wrong-role", "revoked", "tampered", "stale-review", "replay-binding"}
        if not required <= value["rejections"].keys() or not all(
            value["rejections"][k] for k in required
        ):
            raise ValueError("ISOLATED_REJECTIONS")
        if value["invalidated"] < 1 or not value["resume_reused"]:
            raise ValueError("ISOLATED_REVISION_RECOVERY")
    else:
        raise ValueError("UNKNOWN_ARTIFACT_KIND: " + name)


def validate_report(
    report: dict[str, Any], expected: dict[str, Any], directory: Path | None
) -> list[str]:
    errors = schema_errors("alpha_evidence", report)
    if errors:
        return errors
    if report["identity"] != expected:
        errors.append("IDENTITY_MISMATCH: checkout/tree/source/manifest/run/attempt/package/head")
    if report["profile"].startswith("python-") and (
        report["kind"] != "pytest" or report["job"] != "python-tests"
    ):
        errors.append("PROFILE_REQUIRES_PYTEST: " + report["profile"])
    if (
        report["profile"] in {"linux-unit", "windows-unit", "linux-sandbox", "chromium"}
        and report["kind"] != "pytest"
    ):
        errors.append("PROFILE_REQUIRES_PYTEST: " + report["profile"])
    ids = [row["nodeid"] for row in report["tests"]]
    if len(ids) != len(set(ids)):
        errors.append("DUPLICATE_TEST_ID")
    if report["kind"] == "pytest" and not ids:
        errors.append("ZERO_COLLECTED_REPORT")
    if report["kind"] == "command" and ids:
        errors.append("COMMAND_CANNOT_SUPPLY_TESTS")
    if report["status"] == "PASS" and report["exit_code"] != 0:
        errors.append("FAILED_EXECUTION_MARKED_PASS")
    names = [a["name"] for a in report["artifacts"]]
    for name, producer in ARTIFACT_PRODUCERS.items():
        if (report["job"], report["profile"]) == producer and (
            report["kind"] != "command" or name not in names
        ):
            errors.append("PROFILE_REQUIRES_ARTIFACT: " + name)
    if len(names) != len(set(names)):
        errors.append("DUPLICATE_ARTIFACT")
    for artifact in report["artifacts"]:
        try:
            if report["kind"] != "command" or ARTIFACT_PRODUCERS.get(artifact["name"]) != (
                report["job"],
                report["profile"],
            ):
                raise ValueError("WRONG_ARTIFACT_EXECUTION_PROFILE")
            if directory is None:
                raise ValueError("MISSING_ARTIFACT_DIRECTORY")
            relative_path(artifact["path"])
            path = rooted_path(directory, artifact["path"])
            if path.stat().st_size > MAX_REPORT_BYTES:
                raise ValueError("ARTIFACT_SIZE_LIMIT")
            if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
                raise ValueError("ARTIFACT_DIGEST_MISMATCH")
            _artifact(artifact["name"], path, expected)
        except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
            errors.append("INVALID_ARTIFACT: " + artifact["name"] + ": " + str(exc))
    return errors


def _row_result(row: dict[str, Any], reports: list[dict[str, Any]]) -> dict[str, Any]:
    reasons: list[str] = []
    failed = False
    used: set[str] = set()
    if row.get("implementation_status") == "needs_work" or row.get("gap"):
        reasons.append("IMPLEMENTATION_GAP: " + (row.get("gap") or "needs_work"))
        failed = True
    jobs, profiles = row.get("required_jobs", []), row.get("required_profiles", [])
    eligible = [
        r
        for r in reports
        if (not jobs or r["job"] in jobs) and (not profiles or r["profile"] in profiles)
    ]
    for job in jobs:
        if not any(r["job"] == job for r in eligible):
            reasons.append("MISSING_JOB: " + job)
    for profile in profiles:
        if not any(r["profile"] == profile for r in eligible):
            reasons.append("MISSING_PROFILE: " + profile)
    for report in eligible:
        if report["status"] != "PASS" or report["exit_code"] != 0:
            reasons.append("EXECUTION_FAILED: " + report["job"] + "/" + report["profile"])
            failed = True
    test_profiles = set(
        row.get("test_profiles", [r["profile"] for r in eligible if r["kind"] == "pytest"])
    )
    if "test_profiles" in row and not test_profiles <= set(profiles):
        reasons.append("TEST_PROFILE_OUTSIDE_REQUIRED_PROFILES")
        failed = True
    for polarity in ("positive_tests", "negative_tests"):
        if not row[polarity]:
            reasons.append("MISSING_SELECTORS: " + polarity)
        for selector in row[polarity]:
            for profile in sorted(test_profiles) or ["missing"]:
                matches = [
                    (r, test)
                    for r in eligible
                    if r["kind"] == "pytest" and r["profile"] == profile
                    for test in r["tests"]
                    if test["nodeid"] == selector or test["nodeid"].startswith(selector + "[")
                ]
                if not matches:
                    reasons.append("ZERO_COLLECTED_SELECTOR: " + profile + ":" + selector)
                for report, test in matches:
                    used.add(report["job"] + "/" + report["profile"] + ":" + test["nodeid"])
                    if test["outcome"] != "passed":
                        reasons.append(
                            "MANDATORY_TEST_NONPASS: " + test["nodeid"] + ":" + test["outcome"]
                        )
                        failed = True
    for name in row.get("expected_artifacts", []):
        artifact_matches = [
            r
            for r in eligible
            if r["kind"] == "command" and any(a["name"] == name for a in r["artifacts"])
        ]
        if not artifact_matches:
            reasons.append("MISSING_ARTIFACT: " + name)
        used.update(r["job"] + "/" + r["profile"] + ":" + name for r in artifact_matches)
    return {
        "id": row["id"],
        "status": "FAIL" if failed else "UNEXECUTED" if reasons else "PASS",
        "reasons": reasons,
        "evidence": sorted(used),
    }


def evaluate(
    manifest: dict[str, Any],
    baseline: dict[str, Any],
    reports: list[dict[str, Any]],
    expected: dict[str, Any],
    artifact_roots: list[Path] | None = None,
) -> dict[str, Any]:
    errors = check_contract(manifest, baseline)
    valid = []
    installed_wheels: set[str] = set()
    installed_pytest: list[dict[str, Any]] = []
    partitioned_pytest: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, report in enumerate(reports):
        problems = validate_report(
            report, expected, artifact_roots[index] if artifact_roots else None
        )
        if not problems:
            key = (report["job"], report["profile"], report["kind"])
            if key in seen:
                problems.append("DUPLICATE_REPORT: " + "/".join(key))
            seen.add(key)
        if problems:
            errors.extend("report " + str(index) + ": " + issue for issue in problems)
        else:
            valid.append(report)
            if artifact_roots:
                for artifact in report["artifacts"]:
                    if artifact["name"] == "alpha-offline-scenarios":
                        material = load_json(rooted_path(artifact_roots[index], artifact["path"]))
                        installed_wheels.add(material["material"]["wheel_sha256"])
                    if artifact["name"] == "installed-regression-outcomes":
                        material = load_json(rooted_path(artifact_roots[index], artifact["path"]))
                        installed_pytest.append(material["pytest_evidence"])
                    if artifact["name"] == "partitioned-regression-outcomes":
                        material = load_json(rooted_path(artifact_roots[index], artifact["path"]))
                        partitioned_pytest.append(material["pytest_evidence"])
    built_wheels = {
        artifact["sha256"]
        for report in valid
        for artifact in report["artifacts"]
        if artifact["name"] == "wheel"
    }
    if not installed_wheels <= built_wheels:
        errors.append("INSTALLED_SCENARIO_WHEEL_MISMATCH")
    if any(report not in valid for report in installed_pytest):
        errors.append("INSTALLED_PYTEST_REPORT_MISSING_OR_DIFFERENT")
    windows_reports = [
        report
        for report in valid
        if report["kind"] == "pytest" and report["profile"] == "python-windows-3.12"
    ]
    if windows_reports != partitioned_pytest:
        errors.append("WINDOWS_PARTITION_REPORT_MISSING_OR_DIFFERENT")
    rows: list[dict[str, Any]] = []
    if not check_contract(manifest, baseline):
        for field in ("requirements", "fixture_categories", "scenarios"):
            rows.extend({"category": field, **_row_result(row, valid)} for row in manifest[field])
    counts = {
        state: sum(r["status"] == state for r in rows) for state in ("PASS", "FAIL", "UNEXECUTED")
    }
    ready = bool(rows) and not errors and counts["PASS"] == len(rows)
    if expected["package_version"] != manifest.get(
        "target_version"
    ) and not successor_package_compatible(
        expected["package_version"], manifest.get("target_version", "")
    ):
        errors.append("RELEASE_VERSION_PENDING: " + expected["package_version"])
        ready = False
    return {
        "schema_version": "1.0",
        "ready": ready,
        "status": "READY" if ready else "NOT_READY",
        "identity": expected,
        "counts": counts,
        "requirements": rows,
        "errors": errors,
        "scientific_boundary": "Software conformance only. Extracted claims, formal execution, fidelity review, policy acceptance and scholarly acceptance remain distinct.",
    }


def main() -> int:
    from scripts.alpha_evidence import identity

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=ROOT / "acceptance/paper_ci_alpha.json")
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path)
    args = parser.parse_args()
    result: dict[str, Any]
    try:
        baseline_path = ROOT / "acceptance/mandatory_requirements.json"
        if hashlib.sha256(baseline_path.read_bytes()).hexdigest() != BASELINE_SHA256:
            raise ValueError(
                "MANDATORY_BASELINE_CHANGED: scope changes require explicit review and original authority"
            )
        paths = sorted(args.evidence_dir.rglob("*evidence.json"))
        if len(paths) > 256 or sum(p.stat().st_size for p in paths) > MAX_REPORT_BYTES:
            raise ValueError("EVIDENCE_RESOURCE_LIMIT")
        for path in paths:
            rooted_path(args.evidence_dir, path.relative_to(args.evidence_dir).as_posix())
        result = evaluate(
            load_json(args.manifest),
            load_json(baseline_path),
            [load_json(p) for p in paths],
            identity(ROOT, args.manifest),
            [p.parent for p in paths],
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {
            "schema_version": "1.0",
            "ready": False,
            "status": "NOT_READY",
            "counts": {"PASS": 0, "FAIL": 0, "UNEXECUTED": 0},
            "requirements": [],
            "errors": ["INVALID_INPUT: " + str(exc)],
        }
    write_json(args.out, result)
    lines = ["# Paper CI alpha readiness", "", result["status"], "", str(result["counts"]), ""]
    lines.extend("- " + issue.replace("\n", " ") for issue in result["errors"])
    for row in result["requirements"]:
        lines.append("- " + row["id"] + ": " + row["status"] + "; " + "; ".join(row["reasons"]))
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(result["status"], result["counts"])
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
