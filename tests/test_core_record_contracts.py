"""Bounded semantic contracts; source claims and schema validity are not proofs."""

from copy import deepcopy
from dataclasses import replace

import pytest
from test_execution import binding, obligation, profile, simulated_execution
from test_kernel import certified, graph

from proofmap.evidence_adapter import assess_binding, assessment_records, resolve_reused_execution
from proofmap.evidence_records import (
    AcceptanceRecord,
    AssessmentRecord,
    EnvironmentManifest,
    ExecutionEvent,
    FormalizationBinding,
    ReviewDecision,
    VerifierProfile,
    record_issues,
)
from proofmap.integrity import canonical_bytes, digest
from proofmap.kernel import RELATIONS, Context, Inference, KernelMap, TypedRelation, closure
from proofmap.schema import schema, validate
from proofmap.trust import sign_record

TIME = "2026-10-02T00:00:00Z"


def test_relation_contracts_have_distinct_views_directions_and_no_proof_authority():
    assert RELATIONS["CITES"].direction == "citing claim -> cited claim"
    assert "dependency" not in RELATIONS["CITES"].views
    assert "dependency" not in RELATIONS["CONTRADICTS"].views
    assert "flow" in RELATIONS["FLOWS_TO"].views
    assert RELATIONS["CONTRADICTS"].symmetric
    for kind in RELATIONS:
        value = replace(graph(), relations=(TypedRelation("A", "B", kind),))
        value.validate()
        assert closure(value, foundations=(("c", "A"),)).closed == ("A",)


def test_relation_cycles_endpoints_context_and_symmetry_are_enforced():
    for kind in ("DEFINES", "LIMITS_TO"):
        value = replace(
            graph(), relations=(TypedRelation("A", "B", kind), TypedRelation("B", "A", kind))
        )
        with pytest.raises(ValueError, match="RELATION_CYCLE"):
            value.validate()
    citation_cycle = replace(
        graph(), relations=(TypedRelation("A", "B", "CITES"), TypedRelation("B", "A", "CITES"))
    )
    citation_cycle.validate()
    assert not closure(citation_cycle).closed
    mirrored = replace(
        graph(),
        relations=(TypedRelation("A", "B", "CONTRADICTS"), TypedRelation("B", "A", "CONTRADICTS")),
    )
    with pytest.raises(ValueError, match="DUPLICATE_RELATION"):
        mirrored.validate()
    crossed = replace(
        graph(),
        contexts=graph().contexts + (Context("other", "r"),),
        claims=(replace(graph().claims[0], context="other"),) + graph().claims[1:],
        relations=(TypedRelation("A", "B", "PROVES"),),
    )
    with pytest.raises(ValueError, match="RELATION_CROSS_CONTEXT"):
        crossed.validate()
    replace(crossed, relations=(TypedRelation("A", "B", "BRIDGES"),)).validate()


@pytest.mark.parametrize(
    "mutation", ["warnings", "claim", "missing", "duplicate", "dangling", "context", "relation"]
)
def test_kernel_loader_rejects_malformed_contracts(mutation):
    value = graph().to_dict()
    if mutation == "warnings":
        value["warnings"] = "string-is-not-an-array"
    elif mutation == "claim":
        value["claims"][0]["revision"] = True
    elif mutation == "missing":
        value["claims"][0].pop("label")
    elif mutation == "duplicate":
        value["inferences"] = [Inference("i", "B", ("A", "A"), "c").__dict__]
    elif mutation == "dangling":
        value["inferences"] = [Inference("i", "B", ("A",), "c", evidence=("missing",)).__dict__]
    elif mutation == "context":
        value["contexts"][0]["description"] = 2
    else:
        value["relations"] = [{"kind": "FUTURE", "source": "A", "target": "B"}]
    with pytest.raises(ValueError):
        KernelMap.from_dict(value)


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("missing", "MISSING_EVIDENCE"),
        ("stale", "STALE_EVIDENCE_BINDING"),
        ("untrusted", "UNTRUSTED_EVIDENCE"),
        ("failed", "INVALID_EVIDENCE_OUTCOME"),
    ],
)
def test_evidence_failure_reasons_are_distinct(mutation, code):
    value, trusted = certified(graph(), Inference("i", "B", ("A",), "c"))
    if mutation == "missing":
        value = replace(value, inferences=(replace(value.inferences[0], evidence=()),), evidence=())
    elif mutation == "stale":
        value = replace(
            value,
            claims=tuple(
                replace(c, statement="changed") if c.id == "B" else c for c in value.claims
            ),
        )
    elif mutation == "untrusted":
        trusted = "0" * 64
    else:
        value = replace(value, evidence=(replace(value.evidence[0], outcome="FAIL"),))
        trusted = value.evidence[0].digest
    result = closure(value, foundations=(("c", "A"),), trusted_evidence=(trusted,))
    assert result.closed == ("A",)
    assert code in result.evidence_issues["i"]


def assessment_fields():
    return dict(
        subject="claim",
        subject_kind="claim",
        subject_digest="a" * 64,
        context_digest="b" * 64,
        dimension="source_fidelity",
        status="NOT_ASSESSED",
        policy_digest="c" * 64,
        method="human-review-v1",
        evidence_digests=[],
        actor_id="reviewer",
        authentication="NOT_CHECKED",
        authentication_digests=[],
        authority_digest=None,
        evaluation_time=TIME,
        reasons=["No review supplied"],
    )


def test_dimension_assessment_is_versioned_immutable_and_not_acceptance():
    record = AssessmentRecord.build(**assessment_fields())
    assert not validate("assessment-record", record.to_dict())
    assert not record_issues(record.to_dict())
    copy = record.to_dict()
    copy["status"] = "PASS"
    assert record.status == "NOT_ASSESSED"
    with pytest.raises(ValueError, match="IDENTITY"):
        AssessmentRecord.from_dict(copy)
    assert not closure(graph()).closed


@pytest.mark.parametrize(
    "change", ["dimension", "time", "future", "authority", "duplicate", "false_number"]
)
def test_assessment_provenance_rejects_malformed_fields(change):
    fields = assessment_fields()
    if change == "dimension":
        fields["dimension"] = "overall_truth"
    elif change == "time":
        fields["evaluation_time"] = "2026-10-02T00:00:00"
    elif change == "future":
        fields["schema_version"] = "2.0"
    elif change == "authority":
        fields["authentication"] = "VERIFIED"
    elif change == "duplicate":
        fields["authentication_digests"] = ["a" * 64, "a" * 64]
    else:
        fields["subject"] = True
    with pytest.raises(ValueError):
        AssessmentRecord.build(**fields)


def test_all_execution_schema_resources_are_public_and_nested_material_agrees():
    for name in (
        "formalization-binding",
        "verifier-profile",
        "environment-manifest",
        "execution-event",
        "review-decision",
        "acceptance-record",
        "assessment-record",
    ):
        assert schema(name)["type"] == "object"
    assert schema("execution-event")["properties"]["environment"] == schema("environment-manifest")
    assert not validate("formalization-binding", binding().to_dict())


@pytest.mark.parametrize("change", ["missing", "unknown", "digest", "platform"])
def test_complete_environment_requires_exact_typed_material(monkeypatch, change):
    result, _, _ = simulated_execution(monkeypatch)
    fields = result["event"]["environment"].copy()
    fields.pop("id")
    fields.pop("record_type")
    fields.pop("schema_version")
    if change == "missing":
        fields["actual"].pop("library_digest")
    elif change == "unknown":
        fields["actual"]["unmeasured_import"] = "Other"
    elif change == "digest":
        fields["actual"]["library_digest"] = "fake"
    else:
        fields["actual"]["platform"] = "windows/amd64"
    with pytest.raises(ValueError):
        EnvironmentManifest.build(**fields)


def test_record_boundaries_reject_empty_limits_reversed_and_unsafe_locators():
    selected = profile().to_dict()
    selected["limits"] = {}
    with pytest.raises(ValueError):
        VerifierProfile.from_dict(selected)
    for loc in (
        {"file": "../escape.tex", "start": 0, "end": 1},
        {"file": "paper.tex", "start": 5, "end": 1},
    ):
        fields = binding().to_dict()
        fields.pop("id")
        fields.pop("record_type")
        fields.pop("schema_version")
        fields["source_locators"] = [loc]
        with pytest.raises(ValueError):
            FormalizationBinding.build(**fields)


def historical_fixture(monkeypatch):
    execution, private, trust = simulated_execution(monkeypatch)
    current_obligation = replace(obligation(), id="revised-obligation", target_node_id="new-claim")
    current_binding = FormalizationBinding.create(
        revision_id="e" * 64,
        assertion_id="new-claim",
        assertion_digest="f" * 64,
        source_locators=[{"file": "revised.tex", "start": 0, "end": 10}],
        context_digest="1" * 64,
        definition_digest="2" * 64,
        obligation=current_obligation,
        method="integer-polynomial-v1",
    )
    history = {
        "parent_run_id": "old-run",
        "parent_revision": binding().revision_id,
        "binding": binding().to_dict(),
        "obligation": obligation().to_dict(),
        "execution": execution,
    }
    return history, current_binding, current_obligation, private, trust


def test_historical_reuse_preserves_event_and_requires_current_fidelity(monkeypatch):
    history, current, target, private, trust = historical_fixture(monkeypatch)
    previous_bytes = canonical_bytes(history)
    resolved = resolve_reused_execution(
        history, trust, current, target, profile(), evaluation_time=TIME
    )
    assert resolved["formal_verified"], resolved
    assert canonical_bytes(history) == previous_bytes
    assert resolved["execution_digest"] == history["execution"]["event"]["id"]
    assert (
        assess_binding(
            current,
            target,
            profile(),
            None,
            [],
            trust,
            evaluation_time=TIME,
            historical_execution=history,
        ).assessment
        == "REVIEW_REQUIRED"
    )
    trust["keys"][0]["roles"] += ["source-fidelity-review", "formal-fidelity-review"]
    trust["keys"][0]["subjects"].append(current.assertion_id)

    def reviews(subject):
        return [
            sign_record(
                ReviewDecision.create(
                    binding=subject,
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

    assert (
        assess_binding(
            current,
            target,
            profile(),
            None,
            reviews(binding()),
            trust,
            evaluation_time=TIME,
            historical_execution=history,
        ).assessment
        == "REVIEW_REQUIRED"
    )
    assert (
        assess_binding(
            current,
            target,
            profile(),
            None,
            reviews(current),
            trust,
            evaluation_time=TIME,
            historical_execution=history,
        ).assessment
        == "ACCEPTED_UNDER_POLICY"
    )
    trust["keys"][0]["revoked"] = True
    assert not resolve_reused_execution(
        history, trust, current, target, profile(), evaluation_time=TIME
    )["formal_verified"]


def test_emitted_assessment_dimensions_preserve_formal_and_paper_boundary(monkeypatch):
    execution, _, trust = simulated_execution(monkeypatch)
    accepted = assess_binding(
        binding(), obligation(), profile(), execution["envelope"], [], trust, evaluation_time=TIME
    )
    records = assessment_records(accepted, binding())
    assert len(records) == 9
    dimensions = {row["dimension"]: row for row in records}
    assert dimensions["deductive"]["status"] == "PASS"
    assert dimensions["deductive"]["subject_kind"] == "formal_encoding"
    for dimension, row in dimensions.items():
        AssessmentRecord.from_dict(row)
        assert row["authentication"] == "NOT_CHECKED"
        if dimension != "deductive":
            assert row["status"] == "NOT_ASSESSED"
            assert row["evidence_digests"] == []


@pytest.mark.parametrize(
    "mutation", ["statement", "candidate", "event", "revision", "signature", "missing", "import"]
)
def test_historical_reuse_fails_closed_for_changed_material(monkeypatch, mutation):
    history, current, target, _, trust = historical_fixture(monkeypatch)
    history = deepcopy(history)
    if mutation == "statement":
        target = replace(
            target, statement=target.statement.replace("+ 0", "+ 1"), statement_sha256=""
        )
    elif mutation == "candidate":
        fields = current.to_dict()
        fields.pop("id")
        fields.pop("record_type")
        fields.pop("schema_version")
        fields["candidate_digest"] = "8" * 64
        current = FormalizationBinding.build(**fields)
    elif mutation == "event":
        history["execution"]["event"]["duration_seconds"] = 987
    elif mutation == "revision":
        history["parent_revision"] = "0" * 64
    elif mutation == "signature":
        history["execution"]["envelope"]["signatures"][0]["sig"] = "AAAA"
    elif mutation == "missing":
        history.pop("binding")
    else:
        target = replace(target, imports=("Std", "Unsafe"))
    resolved = resolve_reused_execution(
        history, trust, current, target, profile(), evaluation_time=TIME
    )
    assert not resolved["formal_verified"] and not resolved["trusted_evidence"]


def test_execution_record_schema_cannot_invent_missing_outputs(monkeypatch):
    result, _, _ = simulated_execution(monkeypatch)
    record = result["event"].copy()
    record["outputs"] = {}
    record["output_digests"] = {}
    record["id"] = digest("execution-event.v1", {k: v for k, v in record.items() if k != "id"})
    with pytest.raises(ValueError):
        ExecutionEvent.from_dict(record)


@pytest.mark.parametrize(
    "changed",
    [
        {"execution_digest": None},
        {"formal_status": "UNVERIFIED"},
        {"assessment": "ACCEPTED_UNDER_POLICY"},
        {"assessment": "REJECTED"},
        {"source_fidelity": "REJECT"},
        {"evaluation_time": "2026-10-02T00:00:00"},
    ],
)
def test_rehashed_acceptance_cannot_violate_policy_state(monkeypatch, changed):
    result, _, trust = simulated_execution(monkeypatch)
    valid = assess_binding(
        binding(), obligation(), profile(), result["envelope"], [], trust, evaluation_time=TIME
    )
    value = {**valid.to_dict(), **changed}
    value["id"] = digest("acceptance-record.v1", {k: v for k, v in value.items() if k != "id"})
    with pytest.raises(ValueError):
        AcceptanceRecord.from_dict(value)


@pytest.mark.parametrize("mutation", [None, "event", "subject", "dimension", "omitted-dimension"])
def test_cached_acceptance_and_dimension_projections_require_actual_event(monkeypatch, mutation):
    from proofmap.paper_records import _validate_initial_acceptances

    result, _, trust = simulated_execution(monkeypatch)
    accepted = assess_binding(
        binding(), obligation(), profile(), result["envelope"], [], trust, evaluation_time=TIME
    )
    bundle = {
        "formalizations": [
            {"binding": binding().to_dict(), "execution_event": result["event"]["id"]}
        ],
        "execution_events": [result],
        "acceptance_records": [accepted.to_dict()],
        "assessment_records": assessment_records(accepted, binding()),
    }
    if mutation is None:
        _validate_initial_acceptances(bundle)
        return
    if mutation in {"event", "subject"}:
        value = bundle["acceptance_records"][0]
        value["execution_digest" if mutation == "event" else "assertion_id"] = "0" * 64
        value["id"] = digest("acceptance-record.v1", {k: v for k, v in value.items() if k != "id"})
    elif mutation == "dimension":
        bundle["assessment_records"][0]["status"] = "FAIL"
    else:
        bundle["assessment_records"].pop()
    with pytest.raises(ValueError, match="ACCEPTANCE_|ASSESSMENT_DIMENSION_PROJECTION"):
        _validate_initial_acceptances(bundle)
