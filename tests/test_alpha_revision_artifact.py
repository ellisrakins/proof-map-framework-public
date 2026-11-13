"""Contract simulations for scenario evidence; these never claim actual Lean execution."""

import base64
from copy import deepcopy

import pytest

from scripts.check_alpha_scenarios import validate_isolated
from scripts.paper_e2e_isolated import independent_revision_scenario


@pytest.fixture(scope="module")
def simulated_revision(tmp_path_factory):
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
    from proofmap.runner import RunResult

    profile = VerifierProfile.create(
        image="sha256:" + "a" * 64,
        platform="linux/amd64",
        lean_sha256="b" * 64,
        library_digest="c" * 64,
        checker_digest=CHECKER_DIGEST,
        acquisition_digest="d" * 64,
    )
    keys, authority = {}, {"schema_version": "2.0", "keys": []}
    for name, roles in (
        ("ci-ephemeral-controller", ["verification-execution"]),
        ("ci-ephemeral-reviewer", ["source-fidelity-review", "formal-fidelity-review"]),
    ):
        private = Ed25519PrivateKey.generate()
        keys[name] = private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
        authority["keys"].append(
            {
                "id": name,
                "public_key": base64.b64encode(
                    private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                ).decode(),
                "roles": roles,
                "subjects": [],
                "profiles": [profile.digest],
                "revoked": False,
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
            }
        )
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
        actual["version"] = "Lean (version 4.30.0, CONTRACT SIMULATION)"
        result = {
            "returncode": 0,
            "stderr": "",
            "stdout": "'proofmap_target' depends on axioms: [propext, Classical.choice, Quot.sound]",
        }
        return RunResult(
            "PASS",
            0,
            canonical_bytes(
                {
                    "outcome": "CHECKED",
                    "actual": actual,
                    "results": {"Candidate": result, "Recheck": result},
                }
            ).decode(),
            "",
            0,
            image,
            limits,
        )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("proofmap.execution.run", simulated)
        result = independent_revision_scenario(
            tmp_path_factory.mktemp("scenario-contract") / "work",
            profile.to_dict(),
            keys,
            authority,
            "2026-10-02T00:00:00Z",
        )
    assert len(calls) == 3
    return {"profile": profile.to_dict(), "alpha_revision": result}


def test_simulated_revision_contract_requires_actual_stage_lineage(simulated_revision):
    validate_isolated(simulated_revision)


@pytest.mark.parametrize(
    "change",
    [
        "event",
        "fresh_binding",
        "stale_review",
        "count",
        "lineage",
        "antecedent",
        "fallback",
        "revocation",
        "unreviewed_acceptance",
        "history_label",
        "unresolved_event",
        "source_revision",
        "prior_fingerprint",
        "fake_current_event",
        "source_bytes",
        "rehashed_source_manifest",
        "source_element_text",
        "hidden_cache_validation",
    ],
)
def test_revision_artifact_rejects_tampering(simulated_revision, change):
    value = deepcopy(simulated_revision)
    row = value["alpha_revision"]
    if change == "event":
        row["revised_execution_events"][0]["envelope"]["payload"] = base64.b64encode(b"{}").decode()
    elif change == "fresh_binding":
        row["reused_formalization"]["binding"] = row["reused_formalization"][
            "historical_execution"
        ]["binding"]
    elif change == "stale_review":
        row["current_reviews"] = row["initial_reviews"]
    elif change == "count":
        row["revised_execution_count"] = True
    elif change == "lineage":
        row["revision_plan"]["rows"][1]["previous_fingerprint"] = "0" * 64
    elif change == "antecedent":
        row["reused_formalization"]["obligation"]["statement"] = "True"
    elif change == "fallback":
        row["unresolved_plan"]["rows"][0]["reuse_eligible"] = True
    elif change == "revocation":
        row["after_revocation"]["verified"] = 2
    elif change == "unreviewed_acceptance":
        row["revised_before_review"]["accepted"] = 2
    elif change == "unresolved_event":
        row["unresolved_execution_count"] = 1
        row["unresolved_execution_events"] = [row["revised_execution_events"][0]]
    elif change == "source_revision":
        row["initial_ir"] = row["revised_ir"]
    elif change == "prior_fingerprint":
        row["revision_plan"]["rows"][0]["previous_fingerprint"] = "f" * 64
    elif change == "fake_current_event":
        row["reused_formalization"]["execution_event"] = row["initial_execution_events"][1][
            "event"
        ]["id"]
    elif change in {"source_bytes", "rehashed_source_manifest"}:
        from proofmap.integrity import artifact_digest, digest

        name = next(iter(row["initial_sources"]))
        raw = base64.b64decode(row["initial_sources"][name]).replace(b"offset}{1}", b"offset}{9}")
        row["initial_sources"][name] = base64.b64encode(raw).decode()
        if change == "rehashed_source_manifest":
            manifest = row["initial_input_manifest"]
            manifest["artifacts"][0]["sha256"] = artifact_digest(raw)
            manifest["revision"] = digest(
                "paper-manifest.v1",
                {"entrypoint": manifest["entrypoint"], "artifacts": manifest["artifacts"]},
            )
    elif change == "source_element_text":
        element = next(
            element
            for element in row["initial_ir"]["elements"]
            if element["kind"] == "MACRO_DEFINITION" and "offset" in element["text"]
        )
        element["text"] = element["text"].replace("{1}", "{9}")
    elif change == "hidden_cache_validation":
        next(
            decision for decision in row["revision_plan"]["rows"] if decision["label"] == "branch-b"
        )["cache_validation"] = "NOT_A_SUPPORTED_CACHE_HIT"
    else:
        row["historical_events_unchanged"] = False
    with pytest.raises((ValueError, KeyError, TypeError)):
        validate_isolated(value)
