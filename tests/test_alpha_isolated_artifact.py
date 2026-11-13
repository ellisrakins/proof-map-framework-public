"""Synthetic artifact validation tests; the mocked worker is NOT Lean evidence."""

from copy import deepcopy

import pytest

from proofmap.attempts import FormalObligation
from proofmap.evidence_records import EnvironmentManifest, ExecutionEvent, FormalizationBinding
from proofmap.execution import execute
from proofmap.integrity import artifact_digest, digest, write_json
from scripts.check_alpha_acceptance import validate_report

IDENTITY = {
    "tested_commit": "a" * 40,
    "git_tree": "b" * 40,
    "source_fingerprint": "c" * 64,
    "pr_head": None,
    "run_id": "synthetic-validator-tests",
    "run_attempt": "1",
    "package_version": "0.8.0a1",
    "manifest_sha256": "d" * 64,
}


@pytest.fixture
def synthetic_outcomes(monkeypatch):
    """Exercise contract validation, never claim a real toolchain was executed."""
    import base64
    import json

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    from proofmap.evidence_records import VerifierProfile
    from proofmap.execution import CHECKER_DIGEST
    from proofmap.runner import RunResult

    profile = VerifierProfile.create(
        image="sha256:" + "a" * 64,
        platform="linux/amd64",
        lean_sha256="b" * 64,
        library_digest="c" * 64,
        checker_digest=CHECKER_DIGEST,
        acquisition_digest="d" * 64,
    )
    obligation = FormalObligation(
        "poly",
        "claim",
        "∀ (x : Int), x + 0 = x",
        "leanprover/lean4:v4.30.0",
        imports=("Std",),
        allowed_axioms=("Classical.choice", "Quot.sound", "propext"),
    )
    binding = FormalizationBinding.create(
        revision_id="a" * 64,
        assertion_id="claim",
        assertion_digest="b" * 64,
        source_locators=[{"file": "synthetic.tex", "start": 0, "end": 10}],
        context_digest="c" * 64,
        definition_digest="d" * 64,
        obligation=obligation,
        method="integer-polynomial-v1",
    )
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    trust = {
        "schema_version": "2.0",
        "keys": [
            {
                "id": "synthetic-controller",
                "public_key": base64.b64encode(
                    key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
                ).decode("ascii"),
                "roles": ["verification-execution"],
                "subjects": ["claim"],
                "profiles": [profile.digest],
                "revoked": False,
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
            }
        ],
    }
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
    actual["version"] = "Lean (version 4.30.0, SYNTHETIC CONTRACT TEST)"
    worker = {
        "outcome": "CHECKED",
        "actual": actual,
        "results": {
            name: {
                "returncode": 0,
                "stdout": "'proofmap_target' depends on axioms: [propext]",
                "stderr": "",
            }
            for name in ("Candidate", "Recheck")
        },
    }
    monkeypatch.setattr(
        "proofmap.execution.run",
        lambda image, source, argv, limits: RunResult(
            "PASS",
            0,
            json.dumps(worker),
            "",
            0.1,
            image,
            limits,
        ),
    )
    options = {"controller_id": "synthetic-controller", "private_key": private}
    original = execute(binding, obligation, b"by grind", profile, **options)
    replay = execute(
        binding, obligation, b"by grind", profile, parent_event=original["event"]["id"], **options
    )
    dimensions = ("ingested", "formalized", "verified", "reviewed", "accepted")
    value = {
        "status": "PASS",
        "authentication": "EPHEMERAL_TEST_AUTHORITY_ONLY",
        "installed_package": "/synthetic-env/site-packages/proofmap/__init__.py",
        "validator_sha": IDENTITY["tested_commit"],
        "manuscript_sha": "e" * 40,
        "profile": profile.to_dict(),
        "binding": binding.to_dict(),
        "obligation": obligation.to_dict(),
        "trust_store": trust,
        "evaluation_time": "2026-10-01T00:00:00Z",
        "before_review": dict(zip(dimensions, (1, 1, 1, 0, 0), strict=True)),
        "after_review": dict(zip(dimensions, (1, 1, 1, 1, 1), strict=True)),
        "after_revision": dict(zip(dimensions, (1, 0, 0, 0, 0), strict=True)),
        "invalidated": 1,
        "resume_reused": ["ingest"],
        "rejections": {
            name: "REJECTED"
            for name in (
                "wrong-role",
                "revoked",
                "tampered",
                "stale-review",
                "replay-binding",
            )
        },
        "data_only": {
            "status": "PASS",
            "paper_count": 1,
            "validator_sha": IDENTITY["tested_commit"],
            "manuscript_sha": "e" * 40,
        },
        "environment": original["event"]["environment"],
        "execution": original,
        "replay": replay["event"],
        "replay_envelope": replay["envelope"],
    }
    return value, private


def validate_artifact(tmp_path, value):
    path = tmp_path / "outcomes.json"
    write_json(path, value)
    report = {
        "schema_version": "1.0",
        "identity": deepcopy(IDENTITY),
        "job": "paper-e2e-isolated",
        "profile": "linux-isolated",
        "kind": "command",
        "status": "PASS",
        "exit_code": 0,
        "tests": [],
        "artifacts": [
            {
                "name": "isolated-paper-outcomes",
                "path": "outcomes.json",
                "sha256": artifact_digest(path.read_bytes()),
            }
        ],
    }
    return validate_report(report, IDENTITY, tmp_path)


def rebuilt(record, kind):
    # Model hostile serialized bytes. Legitimate constructors now reject these
    # records before signing, so using them here would miss the load boundary.
    from proofmap.evidence_records import KINDS

    body = {k: v for k, v in record.items() if k != "id"}
    return {**body, "id": digest(KINDS[kind.KIND] + ".v1", body)}


def resnapshot(value, private, phase):
    """Keep record IDs/signatures valid so malformed semantics remain the failure."""
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from proofmap.integrity import canonical_bytes
    from proofmap.trust import pae

    key = "event" if phase == "execution" else None
    event = value[phase][key] if key else value[phase]
    event["environment"] = rebuilt(event["environment"], EnvironmentManifest)
    event["output_digests"] = {
        k: digest("execution-output.v1", v) for k, v in event["outputs"].items()
    }
    event = rebuilt(event, ExecutionEvent)
    payload_type = value["execution"]["envelope"]["payloadType"]
    payload = canonical_bytes(event)
    signature = Ed25519PrivateKey.from_private_bytes(private).sign(pae(payload_type, payload))
    envelope = {
        "payloadType": payload_type,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [
            {"keyid": "synthetic-controller", "sig": base64.b64encode(signature).decode("ascii")}
        ],
    }
    if phase == "execution":
        value["execution"] = {"event": event, "envelope": envelope}
        value["environment"] = event["environment"]
        value["replay"]["parent_event"] = event["id"]
        resnapshot(value, private, "replay")
    else:
        value["replay"], value["replay_envelope"] = event, envelope


def test_synthetic_well_bound_isolated_artifact_contract(tmp_path, synthetic_outcomes):
    value, _ = synthetic_outcomes
    assert not validate_artifact(tmp_path, value)


@pytest.mark.parametrize(
    "field",
    [
        "binding_digest",
        "revision_id",
        "assertion_id",
        "obligation_digest",
        "candidate_digest",
        "wrapper_digest",
        "snapshot_digest",
        "controller_digest",
        "controller_id",
    ],
)
def test_synthetic_replay_cannot_change_subject_or_material(tmp_path, synthetic_outcomes, field):
    value, private = synthetic_outcomes
    value["replay"][field] = "other" if field in {"assertion_id", "controller_id"} else "e" * 64
    resnapshot(value, private, "replay")
    assert validate_artifact(tmp_path, value)


@pytest.mark.parametrize("phase", ["execution", "replay"])
@pytest.mark.parametrize(
    "field",
    [
        "lean_sha256",
        "library_digest",
        "checker_digest",
        "platform",
        "executable",
        "search_path",
        "image",
        "version",
        "empty",
    ],
)
def test_synthetic_complete_label_cannot_hide_wrong_material(
    tmp_path,
    synthetic_outcomes,
    phase,
    field,
):
    value, private = synthetic_outcomes
    event = value["execution"]["event"] if phase == "execution" else value["replay"]
    if field == "empty":
        event["environment"]["actual"] = {}
    else:
        event["environment"]["actual"][field] = "wrong"
    resnapshot(value, private, phase)
    assert validate_artifact(tmp_path, value)


@pytest.mark.parametrize("phase", ["execution", "replay"])
@pytest.mark.parametrize("mutation", ["absent", "different_payload", "missing_signatures"])
def test_synthetic_execution_requires_matching_envelope(
    tmp_path,
    synthetic_outcomes,
    phase,
    mutation,
):
    value, _ = synthetic_outcomes
    envelope = value["execution"]["envelope"] if phase == "execution" else value["replay_envelope"]
    if mutation == "absent":
        envelope = None
    elif mutation == "different_payload":
        envelope = (
            value["replay_envelope"] if phase == "execution" else value["execution"]["envelope"]
        )
    else:
        envelope["signatures"] = []
    if phase == "execution":
        value["execution"]["envelope"] = envelope
    else:
        value["replay_envelope"] = envelope
    assert validate_artifact(tmp_path, value)


@pytest.mark.parametrize("mutation", ["revoked", "wrong_role", "expired", "bad_signature"])
def test_synthetic_ephemeral_authority_is_still_checked(tmp_path, synthetic_outcomes, mutation):
    value, _ = synthetic_outcomes
    if mutation == "revoked":
        value["trust_store"]["keys"][0]["revoked"] = True
    elif mutation == "wrong_role":
        value["trust_store"]["keys"][0]["roles"] = ["receipt-content"]
    elif mutation == "expired":
        value["evaluation_time"] = "2027-02-01T00:00:00Z"
    else:
        value["execution"]["envelope"]["signatures"][0]["sig"] = "AAAA"
    assert validate_artifact(tmp_path, value)


@pytest.mark.parametrize("phase", ["execution", "replay"])
def test_synthetic_candidate_bytes_must_match_material(tmp_path, synthetic_outcomes, phase):
    value, private = synthetic_outcomes
    event = value["execution"]["event"] if phase == "execution" else value["replay"]
    event["outputs"]["candidate_source"] = "by rfl"
    resnapshot(value, private, phase)
    assert validate_artifact(tmp_path, value)
