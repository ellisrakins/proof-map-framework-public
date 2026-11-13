"""Consume exact-candidate campaign evidence without rerunning producers."""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proofmap.integrity import artifact_digest, canonical_bytes, load_json, rooted_path, write_json
from scripts.check_alpha_acceptance import _row_result, schema_errors, validate_report

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "acceptance/research_campaign_conops_v1.json"
REQUIRED = tuple(f"OP-{i:02d}" for i in range(1, 11))
REQUIREMENTS_SHA256 = "c3cb9527dda4016d45ad19496bc650c06a95010a7e8f3f65bd3a6147168fc912"
ALPHA_SHA256 = "7ff8e38f9fa0aad8a2eb396406dd8042817cef19add80c2475cd13985ca9dfc0"
PRODUCERS = {
    "campaign-offline-outcomes": ("package-build", "installed-campaign-offline"),
    "campaign-isolated-outcomes": ("paper-e2e-isolated", "installed-campaign-isolated"),
    "campaign-realism-outcomes": ("paper-ci-fixtures", "campaign-realism"),
}


def check_contract(value: dict[str, Any]) -> list[str]:
    errors = []
    if set(value) != {
        "schema_version",
        "contract_id",
        "target_version",
        "evidence_identity_manifest",
        "preserved_alpha_manifest_sha256",
        "requirements",
        "optional_states",
    }:
        return ["CAMPAIGN_CONTRACT_FIELDS"]
    if value["schema_version"] != "1.0" or value["contract_id"] != "research-campaign-conops-v1":
        errors.append("CAMPAIGN_CONTRACT_IDENTITY")
    ids = [r["id"] for r in value["requirements"]]
    if len(ids) != len(set(ids)) or set(ids) != set(REQUIRED):
        errors.append("CAMPAIGN_MANDATORY_INVENTORY_CHANGED")
    if value["evidence_identity_manifest"] != "acceptance/paper_ci_alpha.json":
        errors.append("CAMPAIGN_IDENTITY_MANIFEST_CHANGED")
    if (
        value["target_version"] != "0.9.0b1"
        or value["preserved_alpha_manifest_sha256"] != ALPHA_SHA256
    ):
        errors.append("CAMPAIGN_RELEASE_OR_PRESERVED_ALPHA_CHANGED")
    if artifact_digest(canonical_bytes(value["requirements"])) != REQUIREMENTS_SHA256:
        errors.append("CAMPAIGN_MANDATORY_BINDINGS_CHANGED")
    if value["optional_states"] != {
        "live_model_quality": "NOT_MEASURED",
        "external_user_pilot": "NOT_PERFORMED",
        "production_authority": "NOT_CONFIGURED",
        "publication": "NOT_REQUESTED",
    }:
        errors.append("CAMPAIGN_OPTIONAL_STATE_INFLATED")
    for row in value["requirements"]:
        if (
            set(row)
            != {
                "id",
                "description",
                "positive_tests",
                "negative_tests",
                "required_profiles",
                "test_profiles",
                "required_jobs",
                "expected_artifacts",
                "implementation_status",
                "gap",
            }
            or not row["positive_tests"]
            or not row["negative_tests"]
            or not row["required_jobs"]
            or not row["required_profiles"]
            or not row["expected_artifacts"]
            or not set(row["test_profiles"]) <= set(row["required_profiles"])
        ):
            errors.append("CAMPAIGN_ROW_CONTRACT: " + row.get("id", "unknown"))
    return errors


def validate_realism(value: dict[str, Any]) -> None:
    rows = value.get("documents", [])
    if len(rows) < 3 or len(rows) != value.get("documents_total"):
        raise ValueError("REALISM_DOCUMENT_INVENTORY")
    if len({r["author"] for r in rows}) < 3 or not {"born-digital-pdf", "multi-file-tex"} <= {
        r["format"] for r in rows
    }:
        raise ValueError("REALISM_COMPOSITION")
    for row in rows:
        if (
            row["exit_code"] != 0
            or row["resume_exit_code"] != 0
            or row["anchors_total"] <= 0
            or row["anchors_valid"] != row["anchors_total"]
            or row["anchor_failures"]
            or row["parser_failures"]
            or row["verified_claims"] != 0
            or row["fidelity"] is not None
            or row["novelty"] is not None
            or row["false_hard_blocks"] is not None
        ):
            raise ValueError("REALISM_MEASURED_BOUNDARY")
    for name, average in value["macro"].items():
        if abs(average - sum(r[name] for r in rows) / len(rows)) > 1e-9:
            raise ValueError("REALISM_MACRO_DENOMINATOR")
    anchors = value["source_anchor_validity"]
    if anchors["valid"] != sum(r["anchors_valid"] for r in rows) or anchors["total"] != sum(
        r["anchors_total"] for r in rows
    ):
        raise ValueError("REALISM_ANCHOR_DENOMINATOR")


def validate_campaign_report(
    report: dict[str, Any], expected: dict[str, Any], directory: Path | None
) -> list[str]:
    errors = schema_errors("alpha_evidence", report)
    if errors:
        return errors
    custom = report["profile"] in {profile for _, profile in PRODUCERS.values()}
    if not custom:
        return validate_report(report, expected, directory)
    # Preserve the alpha envelope's identity/outcome/test rules. Custom artifacts
    # are handled below rather than broadening the old alpha artifact allowlist.
    errors.extend(validate_report({**report, "artifacts": []}, expected, directory))
    names = [a["name"] for a in report["artifacts"]]
    expected_names = {
        name
        for name, producer in PRODUCERS.items()
        if producer == (report["job"], report["profile"])
    }
    if set(names) != expected_names or len(names) != len(set(names)) or report["kind"] != "command":
        errors.append("CAMPAIGN_ARTIFACT_PRODUCER_OR_INVENTORY")
    for artifact in report["artifacts"]:
        try:
            if directory is None or PRODUCERS.get(artifact["name"]) != (
                report["job"],
                report["profile"],
            ):
                raise ValueError("CAMPAIGN_ARTIFACT_PRODUCER")
            path = rooted_path(directory, artifact["path"])
            if (
                path.stat().st_size > 64_000_000
                or hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]
            ):
                raise ValueError("CAMPAIGN_ARTIFACT_BYTES")
            value = load_json(path)
            if artifact["name"] == "campaign-realism-outcomes":
                validate_realism(value)
            else:
                from proofmap.campaign.conops import validate_outcomes

                validate_outcomes(
                    value,
                    require_installed=True,
                    required_profile=report["profile"].removeprefix("installed-campaign-"),
                )
                if value["candidate_identity"] != expected:
                    raise ValueError("CAMPAIGN_CANDIDATE_IDENTITY")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            errors.append("INVALID_CAMPAIGN_ARTIFACT: " + str(exc))
    return errors


def evaluate(
    contract: dict[str, Any],
    reports: list[dict[str, Any]],
    expected: dict[str, Any],
    alpha: dict[str, Any],
    artifact_roots: list[Path] | None = None,
) -> dict[str, Any]:
    errors = check_contract(contract)
    valid = []
    seen = set()
    for index, report in enumerate(reports):
        issues = validate_campaign_report(
            report, expected, artifact_roots[index] if artifact_roots else None
        )
        key = (report.get("job"), report.get("profile"), report.get("kind"))
        if key in seen:
            issues.append("DUPLICATE_CAMPAIGN_REPORT")
        seen.add(key)
        if issues:
            errors.extend(issues)
        else:
            valid.append(report)
            if artifact_roots:
                for artifact in report["artifacts"]:
                    if artifact["name"] == "installed-regression-outcomes":
                        material = load_json(rooted_path(artifact_roots[index], artifact["path"]))
                        valid.append(material["pytest_evidence"])
    frozen = load_json(ROOT / "acceptance/paper_ci_alpha.json")
    expected_alpha = {
        (category, row["id"])
        for category in ("requirements", "fixture_categories", "scenarios")
        for row in frozen[category]
    }
    alpha_rows = alpha.get("requirements", [])
    alpha_pass = (
        alpha.get("ready") is True
        and alpha.get("status") == "READY"
        and alpha.get("identity") == expected
        and alpha.get("counts") == {"PASS": 81, "FAIL": 0, "UNEXECUTED": 0}
        and not alpha.get("errors")
        and alpha.get("schema_version") == "1.0"
        and len(alpha_rows) == len(expected_alpha) == 81
        and {(row.get("category"), row.get("id")) for row in alpha_rows} == expected_alpha
        and all(
            row.get("status") == "PASS" and row.get("reasons") == [] and row.get("evidence")
            for row in alpha_rows
        )
    )
    # An observed regression differs from missing or stale qualification. The
    # complete frozen inventory and reconciled row counts must belong to this
    # candidate before any failed execution can be attributed to it. This status
    # is descriptive only; alpha_pass remains the unchanged readiness gate.
    alpha_failed = (
        alpha.get("identity") == expected
        and alpha.get("schema_version") == "1.0"
        and alpha.get("ready") is False
        and alpha.get("status") == "NOT_READY"
        and len(alpha_rows) == len(expected_alpha) == 81
        and {(row.get("category"), row.get("id")) for row in alpha_rows} == expected_alpha
        and all(row.get("status") in {"PASS", "FAIL", "UNEXECUTED"} for row in alpha_rows)
        and alpha.get("counts")
        == {
            state: sum(row.get("status") == state for row in alpha_rows)
            for state in ("PASS", "FAIL", "UNEXECUTED")
        }
        and any(
            row.get("status") == "FAIL"
            and any(
                isinstance(reason, str)
                and reason.startswith(("EXECUTION_FAILED: ", "MANDATORY_TEST_NONPASS: "))
                for reason in row.get("reasons", [])
            )
            for row in alpha_rows
        )
    )
    if not alpha_pass:
        errors.append("PRESERVED_ALPHA_NOT_QUALIFIED_FOR_CANDIDATE")
    rows = (
        [_row_result(row, valid) for row in contract["requirements"]]
        if not check_contract(contract)
        else []
    )
    counts = {
        state: sum(r["status"] == state for r in rows) for state in ("PASS", "FAIL", "UNEXECUTED")
    }
    ready = len(rows) == len(REQUIRED) and counts["PASS"] == len(rows) and not errors
    if expected["package_version"] != contract["target_version"]:
        errors.append("BETA_RELEASE_VERSION_PENDING: " + expected["package_version"])
        ready = False
    return {
        "schema_version": "1.0",
        "contract_id": "research-campaign-conops-v1",
        "ready": ready,
        "status": "READY" if ready else "NOT_READY",
        "identity": expected,
        "counts": counts,
        "requirements": rows,
        "errors": errors,
        "software_alpha_regression": "PASS"
        if alpha_pass
        else "FAIL"
        if alpha_failed
        else "UNEXECUTED",
        "research_campaign_implementation": "COMPLETE"
        if rows
        and not any(
            r["gap"] or r["implementation_status"] == "needs_work" for r in contract["requirements"]
        )
        else "INCOMPLETE",
        "research_campaign_validation": "PASS"
        if ready
        else "FAIL"
        if errors or counts["FAIL"]
        else "UNEXECUTED",
        **contract["optional_states"],
    }


def main(argv: list[str] | None = None) -> int:
    from scripts.alpha_evidence import identity

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--alpha", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        contract = load_json(CONTRACT)
        alpha_manifest = ROOT / contract["evidence_identity_manifest"]
        if (
            hashlib.sha256(alpha_manifest.read_bytes()).hexdigest()
            != contract["preserved_alpha_manifest_sha256"]
        ):
            raise ValueError("PRESERVED_ALPHA_CONTRACT_CHANGED")
        paths = sorted(args.evidence_dir.rglob("*evidence.json"))
        if len(paths) > 256 or sum(p.stat().st_size for p in paths) > 64_000_000:
            raise ValueError("CAMPAIGN_EVIDENCE_LIMIT")
        result = evaluate(
            contract,
            [load_json(p) for p in paths],
            identity(ROOT, alpha_manifest),
            load_json(args.alpha),
            [p.parent for p in paths],
        )
        result["contract_sha256"] = hashlib.sha256(CONTRACT.read_bytes()).hexdigest()
    except (OSError, ValueError, TypeError, KeyError) as exc:
        result = {
            "schema_version": "1.0",
            "ready": False,
            "status": "NOT_READY",
            "errors": ["INVALID_INPUT: " + str(exc)],
            "counts": {"PASS": 0, "FAIL": 0, "UNEXECUTED": 0},
        }
    write_json(args.out, result)
    print(result["status"], result["counts"])
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
