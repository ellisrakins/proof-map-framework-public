"""Boundary tests; simulated worker output is never evidence of real Lean execution."""

import base64
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from proofmap.attempts import FormalObligation
from proofmap.evidence_records import FormalizationBinding, VerifierProfile, validate_record
from proofmap.execution import execute, render_wrapper
from proofmap.trust import sign_record, verify_record


def obligation():
    return FormalObligation(
        "poly",
        "claim",
        "∀ (x : Int), x + 0 = x",
        "leanprover/lean4:v4.30.0",
        imports=("Std",),
        allowed_axioms=("Classical.choice", "Quot.sound", "propext"),
    )


def binding():
    return FormalizationBinding.create(
        revision_id="a" * 64,
        assertion_id="claim",
        assertion_digest="b" * 64,
        source_locators=[{"file": "paper.tex", "start": 0, "end": 10}],
        context_digest="c" * 64,
        definition_digest="d" * 64,
        obligation=obligation(),
        method="integer-polynomial-v1",
    )


def profile():
    from proofmap.execution import CHECKER_DIGEST

    return VerifierProfile.create(
        image="sha256:" + "a" * 64,
        platform="linux/amd64",
        lean_sha256="b" * 64,
        library_digest="c" * 64,
        checker_digest=CHECKER_DIGEST,
        acquisition_digest="d" * 64,
    )


def authority(role, subject, profile_digest):
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = base64.b64encode(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    store = {
        "schema_version": "2.0",
        "keys": [
            {
                "id": "controller",
                "public_key": public,
                "roles": [role],
                "subjects": [subject],
                "profiles": [profile_digest],
                "revoked": False,
                "not_before": "2026-01-01T00:00:00Z",
                "not_after": "2027-01-01T00:00:00Z",
            }
        ],
    }
    return private, store


def test_fresh_no_runtime_returns_unavailable_without_host_fallback(monkeypatch):
    monkeypatch.setattr("proofmap.runner.shutil.which", lambda _: None)
    value = execute(binding(), obligation(), b"by grind", profile())
    assert value["event"]["outcome"] == "UNAVAILABLE"
    assert value["event"]["environment"]["complete"] is False
    assert value["envelope"] is None
    validate_record(value["event"])


@pytest.mark.parametrize(
    "candidate",
    [
        b"by sorry",
        b'by\n  run_tac IO.println "PASS"',
        b"by grind\n#print axioms evil",
        b"by\n exact False.elim (by sorry)",
    ],
)
def test_candidate_is_parsed_approved_program_not_blacklist(candidate):
    with pytest.raises(ValueError, match="CANDIDATE"):
        render_wrapper(obligation(), candidate)


def test_wrong_obligation_binding_rejected_before_execution():
    with pytest.raises(ValueError, match="BINDING"):
        execute(
            binding(),
            replace(obligation(), statement="∀ (x : Int), x + 1 = x", statement_sha256=""),
            b"by grind",
            profile(),
        )


def test_records_schema_reject_unknown_semantics_bool_integer_and_identity():
    record = profile().to_dict()
    record["limits"]["seconds"] = True
    with pytest.raises(ValueError):
        VerifierProfile.from_dict(record)
    record = binding().to_dict()
    record["future_semantics"] = "ignored"
    with pytest.raises(ValueError):
        FormalizationBinding.from_dict(record)
    record = binding().to_dict()
    record["obligation_digest"] = "malformed"
    with pytest.raises(ValueError):
        FormalizationBinding.from_dict(record)


def test_execution_role_revocation_scope_and_validity(monkeypatch):
    monkeypatch.setattr("proofmap.runner.shutil.which", lambda _: None)
    event = execute(binding(), obligation(), b"by grind", profile(), controller_id="controller")[
        "event"
    ]
    key, store = authority("verification-execution", binding().assertion_id, profile().digest)
    envelope = sign_record(event, key, "controller")
    auth = verify_record(
        envelope,
        store,
        role="verification-execution",
        subject="claim",
        profile_digest=profile().digest,
        evaluation_time="2026-09-27T00:00:00Z",
    )
    assert auth.authenticated
    for field, value in [
        ("revoked", True),
        ("roles", ["receipt-content"]),
        ("subjects", ["other"]),
        ("profiles", ["f" * 64]),
        ("not_after", "2026-01-02T00:00:00Z"),
    ]:
        modified = __import__("copy").deepcopy(store)
        modified["keys"][0][field] = value
        with pytest.raises(ValueError):
            verify_record(
                envelope,
                modified,
                role="verification-execution",
                subject="claim",
                profile_digest=profile().digest,
                evaluation_time="2026-09-27T00:00:00Z",
            )
    changed = dict(envelope, payload=base64.b64encode(b"{}").decode())
    with pytest.raises(ValueError):
        verify_record(
            changed,
            store,
            role="verification-execution",
            subject="claim",
            profile_digest=profile().digest,
            evaluation_time="2026-09-27T00:00:00Z",
        )


def simulated_execution(monkeypatch, *, report_change=None):
    """Only exercises contracts, never claims that the Lean/image exists locally."""
    import json

    from proofmap.runner import RunResult

    selected = profile()
    private, store = authority("verification-execution", "claim", selected.digest)
    actual = {
        key: getattr(selected, key)
        for key in (
            "lean_sha256",
            "library_digest",
            "checker_digest",
            "platform",
            "executable",
            "search_path",
        )
    }
    actual["version"] = "Lean (version 4.30.0, simulated-contract-test)"
    report = {
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
    if report_change:
        report_change(report)
    monkeypatch.setattr(
        "proofmap.execution.run",
        lambda image, source, argv, limits: RunResult(
            "PASS", 0, json.dumps(report), "", 0.1, image, limits
        ),
    )
    result = execute(
        binding(),
        obligation(),
        b"by grind",
        selected,
        controller_id="controller",
        private_key=private,
    )
    return result, private, store


def test_formal_encoding_precedes_authenticated_fidelity_and_revocation(monkeypatch):
    from proofmap.evidence_adapter import assess_binding, resolve_execution
    from proofmap.evidence_records import ReviewDecision

    result, private, store = simulated_execution(monkeypatch)
    assert result["event"]["outcome"] == "VERIFIED"
    resolved = resolve_execution(
        result["envelope"],
        store,
        binding(),
        obligation(),
        profile(),
        evaluation_time="2026-09-27T00:00:00Z",
    )
    assert resolved["formal_verified"], resolved
    before = assess_binding(
        binding(),
        obligation(),
        profile(),
        result["envelope"],
        [],
        store,
        evaluation_time="2026-09-27T00:00:00Z",
    )
    assert before.assessment == "REVIEW_REQUIRED"
    store["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]
    reviews = [
        sign_record(
            ReviewDecision.create(
                binding=binding(),
                profile=profile(),
                dimension=dimension,
                decision="APPROVE",
                reviewer_id="controller",
            ).to_dict(),
            private,
            "controller",
        )
        for dimension in ("source-fidelity", "formal-fidelity")
    ]
    assessed = assess_binding(
        binding(),
        obligation(),
        profile(),
        result["envelope"],
        reviews,
        store,
        evaluation_time="2026-09-27T00:00:00Z",
    )
    assert assessed.assessment == "ACCEPTED_UNDER_POLICY"
    store["keys"][0]["revoked"] = True
    assert (
        assess_binding(
            binding(),
            obligation(),
            profile(),
            result["envelope"],
            reviews,
            store,
            evaluation_time="2026-09-27T00:00:00Z",
        ).assessment
        == "UNVERIFIED"
    )


@pytest.mark.parametrize(
    "field",
    [
        "binding_digest",
        "revision_id",
        "obligation_digest",
        "candidate_digest",
        "wrapper_digest",
        "snapshot_digest",
        "controller_digest",
    ],
)
def test_signed_wrong_bindings_are_rejected(monkeypatch, field):
    from proofmap.evidence_adapter import resolve_execution
    from proofmap.evidence_records import ExecutionEvent

    result, private, store = simulated_execution(monkeypatch)
    fields = {
        k: v for k, v in result["event"].items() if k not in {"id", "record_type", "schema_version"}
    }
    fields[field] = "e" * 64
    changed = ExecutionEvent.build(**fields)
    resolved = resolve_execution(
        sign_record(changed.to_dict(), private, "controller"),
        store,
        binding(),
        obligation(),
        profile(),
        evaluation_time="2026-09-27T00:00:00Z",
    )
    assert not resolved["formal_verified"]
    assert not resolved["trusted_evidence"]


@pytest.mark.parametrize(
    "mutation",
    [
        "forged-audit",
        "wrong-declaration",
        "material",
        "compiler-fail",
        "recheck-fail",
        "no-recheck",
        "untrusted-axiom",
    ],
)
def test_worker_stdout_alone_cannot_grant_verification(monkeypatch, mutation):
    def change(report):
        if mutation == "material":
            report["actual"]["lean_sha256"] = "e" * 64
        elif mutation == "compiler-fail":
            report["results"]["Candidate"]["returncode"] = 1
        elif mutation == "recheck-fail":
            report["results"]["Recheck"]["returncode"] = 1
        elif mutation == "no-recheck":
            del report["results"]["Recheck"]
        else:
            report["results"]["Recheck"]["stdout"] = {
                "forged-audit": "PASS",
                "wrong-declaration": "'other' does not depend on any axioms",
                "untrusted-axiom": "'proofmap_target' depends on axioms: [sorryAx]",
            }[mutation]

    result, _, _ = simulated_execution(monkeypatch, report_change=change)
    assert result["event"]["outcome"] != "VERIFIED"


def test_replay_uses_fresh_executor_and_rejects_changed_candidate(monkeypatch):
    from proofmap.execution import replay_execution

    result, _, _ = simulated_execution(monkeypatch)
    replayed = replay_execution(result["event"], binding(), obligation(), b"by grind", profile())
    assert replayed["event"]["parent_event"] == result["event"]["id"]
    assert replayed["event"]["outcome"] == "VERIFIED"
    with pytest.raises(ValueError, match="REPLAY_BINDING"):
        replay_execution(result["event"], binding(), obligation(), b"by rfl", profile())


@pytest.mark.parametrize(
    "statement",
    [
        "True",
        "∀ (x : Nat), x = x",
        '∀ (x : Int), x = x\nrun_tac IO.println "PASS"',
        "∀ (x : Int), x = y",
        "∀ (x x : Int), x = x",
        "∀ (x : Int), x",
        "∀ (x : Int), x = 99999999999999999",
    ],
)
def test_arbitrary_statements_do_not_enter_approved_grammar(statement):
    with pytest.raises(ValueError, match="UNSUPPORTED_PROFILE"):
        render_wrapper(replace(obligation(), statement=statement, statement_sha256=""), b"by grind")


def test_changed_revision_and_review_supersession(monkeypatch):
    from proofmap.evidence_adapter import assess_binding
    from proofmap.evidence_records import ReviewDecision

    result, private, store = simulated_execution(monkeypatch)
    store["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]
    source = ReviewDecision.create(
        binding=binding(),
        profile=profile(),
        dimension="source-fidelity",
        decision="APPROVE",
        reviewer_id="controller",
    )
    reject = ReviewDecision.create(
        binding=binding(),
        profile=profile(),
        dimension="source-fidelity",
        decision="REJECT",
        reviewer_id="controller",
        supersedes=source.digest,
    )
    reviews = [sign_record(r.to_dict(), private, "controller") for r in (source, reject)]
    assert (
        assess_binding(
            binding(),
            obligation(),
            profile(),
            result["envelope"],
            reviews,
            store,
            evaluation_time="2026-09-27T00:00:00Z",
        ).assessment
        == "REJECTED"
    )
    fields = {
        k: v
        for k, v in binding().to_dict().items()
        if k not in {"id", "record_type", "schema_version"}
    }
    fields["revision_id"] = "e" * 64
    new_binding = FormalizationBinding.build(**fields)
    assessment = assess_binding(
        new_binding,
        obligation(),
        profile(),
        result["envelope"],
        reviews,
        store,
        evaluation_time="2026-09-27T00:00:00Z",
    )
    assert assessment.assessment == "UNVERIFIED"
    assert assessment.source_fidelity == "NOT_REVIEWED"
