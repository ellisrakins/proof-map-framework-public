"""Current external authority and exact record schema adversarial cases."""

import base64
import copy

import pytest
from test_execution import binding, obligation, profile, simulated_execution

from proofmap.evidence_records import ExecutionEvent, FormalizationBinding, ReviewDecision
from proofmap.trust import sign_record, verify_record

TIME = "2026-09-27T00:00:00Z"


@pytest.mark.parametrize(
    "mutation",
    [
        "type",
        "store",
        "keys",
        "fields",
        "id",
        "duplicate",
        "revoked",
        "scope",
        "period",
        "role",
        "public",
        "signature-count",
        "signature-fields",
        "time",
        "before",
        "profile-scope",
    ],
)
def test_external_authority_schema_strict(monkeypatch, mutation):
    result, _, store = simulated_execution(monkeypatch)
    envelope = result["envelope"]
    at = TIME
    if mutation == "type":
        envelope["payloadType"] = "application/vnd.proofmap.attempt-receipt.v1+json"
    elif mutation == "store":
        store["schema_version"] = "1.0"
    elif mutation == "keys":
        store["keys"] = {}
    elif mutation == "fields":
        store["keys"][0]["embedded_authority"] = True
    elif mutation == "id":
        store["keys"][0]["id"] = 7
    elif mutation == "duplicate":
        store["keys"] *= 2
    elif mutation == "revoked":
        store["keys"][0]["revoked"] = 0
    elif mutation == "scope":
        store["keys"][0]["subjects"] = "claim"
    elif mutation == "period":
        store["keys"][0]["not_before"] = store["keys"][0]["not_after"]
    elif mutation == "role":
        store["keys"][0]["roles"] = ["arbitrary-authority"]
    elif mutation == "public":
        store["keys"][0]["public_key"] = base64.b64encode(b"short").decode()
    elif mutation == "signature-count":
        envelope["signatures"] = []
    elif mutation == "signature-fields":
        envelope["signatures"][0]["key"] = "embedded"
    elif mutation == "time":
        at = "not-a-dateZ"
    elif mutation == "before":
        at = "2020-01-01T00:00:00Z"
    else:
        store["keys"][0]["profiles"] = ["malformed"]
    with pytest.raises(ValueError):
        verify_record(
            envelope,
            store,
            role="verification-execution",
            subject="claim",
            profile_digest=profile().digest,
            evaluation_time=at,
        )


def rebuild(record, **changes):
    values = {k: v for k, v in record.items() if k not in {"id", "record_type", "schema_version"}}
    return ExecutionEvent.build(**{**values, **changes}).to_dict()


def test_signed_wrong_subject_controller_and_profile(monkeypatch):
    result, private, store = simulated_execution(monkeypatch)
    for changes in (
        {"controller_id": "other"},
        {"assertion_id": "other"},
        {"profile_digest": "e" * 64},
    ):
        original = copy.deepcopy(result["event"])
        if "profile_digest" in changes:
            from proofmap.evidence_records import EnvironmentManifest

            fields = {
                k: v
                for k, v in original["environment"].items()
                if k not in {"id", "record_type", "schema_version"}
            }
            original["environment"] = EnvironmentManifest.build(**{**fields, **changes}).to_dict()
        envelope = sign_record(rebuild(original, **changes), private, "controller")
        with pytest.raises(ValueError):
            verify_record(
                envelope,
                store,
                role="verification-execution",
                subject="claim",
                profile_digest=profile().digest,
                evaluation_time=TIME,
            )


def test_wrong_review_identity_dimension_and_time_rejected(monkeypatch):
    _, private, store = simulated_execution(monkeypatch)
    store["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]
    for dimension, reviewer in [("formal-fidelity", "controller"), ("source-fidelity", "other")]:
        record = ReviewDecision.create(
            binding=binding(),
            profile=profile(),
            dimension=dimension,
            decision="APPROVE",
            reviewer_id=reviewer,
        )
        envelope = sign_record(record.to_dict(), private, "controller")
        with pytest.raises(ValueError):
            verify_record(
                envelope,
                store,
                role="source-fidelity-review",
                subject="claim",
                profile_digest=profile().digest,
                evaluation_time=TIME,
            )
    with pytest.raises(ValueError):
        verify_record(
            envelope,
            store,
            role="source-fidelity-review",
            subject="claim",
            profile_digest=profile().digest,
            evaluation_time="2026-09-27",
        )
    with pytest.raises(ValueError):
        verify_record(
            envelope,
            store,
            role="receipt-content",
            subject="claim",
            profile_digest=profile().digest,
            evaluation_time=TIME,
        )
    with pytest.raises(ValueError):
        sign_record(binding().to_dict(), private, "controller")


@pytest.mark.parametrize(
    "mutation", ["id", "outputs", "output-keys", "complete", "axioms", "mixed-profile"]
)
def test_execution_record_invariants(monkeypatch, mutation):
    result, _, _ = simulated_execution(monkeypatch)
    record = copy.deepcopy(result["event"])
    if mutation == "id":
        record["id"] = "e" * 64
    elif mutation == "outputs":
        record["outputs"]["worker_stdout"] = "forged"
    elif mutation == "output-keys":
        record["output_digests"]["extra"] = "e" * 64
    elif mutation == "complete":
        from proofmap.evidence_records import EnvironmentManifest

        fields = {
            k: v
            for k, v in record["environment"].items()
            if k not in {"id", "record_type", "schema_version"}
        }
        record["environment"] = EnvironmentManifest.build(**{**fields, "complete": False}).to_dict()
    elif mutation == "axioms":
        record["axioms"] = ["sorryAx"]
    else:
        record["profile_digest"] = "e" * 64
    if mutation != "id":
        from proofmap.integrity import digest

        record["id"] = digest("execution-event.v1", {k: v for k, v in record.items() if k != "id"})
    with pytest.raises(ValueError):
        ExecutionEvent.from_dict(record)


def test_record_readers_immutable_and_unknown_fields():
    from proofmap.evidence_records import record_type, validate_record

    row = binding()
    copy_row = row.to_dict()
    copy_row["source_locators"][0]["start"] = 999
    assert row.source_locators[0]["start"] == 0
    assert record_type(row.to_dict()) is FormalizationBinding
    with pytest.raises(AttributeError):
        _ = row.missing
    with pytest.raises(ValueError):
        ExecutionEvent.from_dict(row.to_dict())
    for unknown in ({"record_type": []}, {"record_type": "Unknown"}, {}):
        with pytest.raises(ValueError):
            validate_record(unknown)
        with pytest.raises(ValueError):
            record_type(unknown)


def test_review_missing_supersession_conflict_and_signature(monkeypatch):
    from proofmap.evidence_adapter import assess_binding

    result, private, store = simulated_execution(monkeypatch)
    store["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]
    for second in [
        dict(decision="APPROVE", supersedes="e" * 64),
        dict(decision="REJECT", supersedes=None),
    ]:
        reviews = [
            ReviewDecision.create(
                binding=binding(),
                profile=profile(),
                dimension="source-fidelity",
                decision="APPROVE",
                reviewer_id="controller",
            ),
            ReviewDecision.create(
                binding=binding(),
                profile=profile(),
                dimension="source-fidelity",
                reviewer_id="controller",
                **second,
            ),
        ]
        envelopes = [sign_record(r.to_dict(), private, "controller") for r in reviews]
        record = assess_binding(
            binding(),
            obligation(),
            profile(),
            result["envelope"],
            envelopes,
            store,
            evaluation_time=TIME,
        )
        assert record.assessment == "REVIEW_REQUIRED"
        assert record.reasons


@pytest.mark.parametrize(
    "mutation", ["actual", "report-actual", "output-code", "output-axiom", "audit-set"]
)
def test_signed_self_consistent_report_still_needs_exact_material_and_audit(monkeypatch, mutation):
    import json

    from proofmap.evidence_adapter import resolve_execution
    from proofmap.evidence_records import EnvironmentManifest
    from proofmap.integrity import digest

    result, private, store = simulated_execution(monkeypatch)
    record = result["event"]
    environment = {
        k: v
        for k, v in record["environment"].items()
        if k not in {"id", "record_type", "schema_version"}
    }
    report = json.loads(record["outputs"]["worker_stdout"])
    if mutation == "actual":
        environment["actual"]["library_digest"] = "e" * 64
    elif mutation == "report-actual":
        report["actual"]["library_digest"] = "e" * 64
    elif mutation == "output-code":
        report["results"]["Recheck"]["returncode"] = True
    elif mutation == "output-axiom":
        report["results"]["Recheck"]["stdout"] = "'proofmap_target' depends on axioms: [sorryAx]"
    else:
        record["axioms"] = []
    record["environment"] = EnvironmentManifest.build(**environment).to_dict()
    record["outputs"]["worker_stdout"] = json.dumps(report)
    record["output_digests"]["worker_stdout"] = digest(
        "execution-output.v1", record["outputs"]["worker_stdout"]
    )
    signed = sign_record(rebuild(record), private, "controller")
    resolved = resolve_execution(
        signed, store, binding(), obligation(), profile(), evaluation_time=TIME
    )
    assert not resolved["formal_verified"]


def test_modern_replay_cli_uses_bound_executor(monkeypatch, tmp_path):
    from proofmap.cli import main
    from proofmap.integrity import load_json, write_json

    result, _, _ = simulated_execution(monkeypatch)
    for name, value in [
        ("event", result["event"]),
        ("binding", binding().to_dict()),
        ("obligation", obligation().to_dict()),
        ("profile", profile().to_dict()),
    ]:
        write_json(tmp_path / (name + ".json"), value)
    (tmp_path / "candidate.lean").write_bytes(b"by grind")
    argv = [
        "receipt-replay",
        str(tmp_path / "event.json"),
        "--artifact-root",
        str(tmp_path),
        "--out",
        str(tmp_path / "replay.json"),
    ]
    assert main(argv) == 2
    argv += [
        "--binding",
        str(tmp_path / "binding.json"),
        "--obligation",
        str(tmp_path / "obligation.json"),
        "--candidate",
        str(tmp_path / "candidate.lean"),
        "--profile",
        str(tmp_path / "profile.json"),
    ]
    assert main(argv) == 0
    assert load_json(tmp_path / "replay.json")["event"]["parent_event"] == result["event"]["id"]


def test_reject_unsupported_size_encoding_checker_and_missing_authentication(monkeypatch):
    from dataclasses import replace

    from proofmap.evidence_adapter import formal_graph, resolve_execution
    from proofmap.evidence_records import VerifierProfile
    from proofmap.execution import execute, render_wrapper

    for candidate in (b"x" * 129, b"\xff"):
        with pytest.raises(ValueError, match="CANDIDATE"):
            render_wrapper(obligation(), candidate)
    for changed in (
        replace(obligation(), statement="x" * 16001, statement_sha256=""),
        replace(obligation(), imports=("Lean",)),
    ):
        with pytest.raises(ValueError, match="UNSUPPORTED_PROFILE"):
            render_wrapper(changed, b"by grind")
    wrong = profile().to_dict()
    fields = {k: v for k, v in wrong.items() if k not in {"id", "record_type", "schema_version"}}
    wrong_profile = VerifierProfile.build(**{**fields, "checker_digest": "e" * 64})
    with pytest.raises(ValueError, match="CHECKER"):
        execute(binding(), obligation(), b"by grind", wrong_profile)
    assert not resolve_execution(
        None, {}, binding(), obligation(), profile(), evaluation_time=TIME
    )["accepted"]
    with pytest.raises(ValueError, match="BINDING"):
        formal_graph(
            binding(), replace(obligation(), statement="∀ (x : Int), x = 1", statement_sha256="")
        )
