"""Planning contracts. Simulated signed worker fixtures are not real proof evidence."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

from proofmap.evidence_records import FormalizationBinding, ReviewDecision
from proofmap.integrity import canonical_bytes, digest
from proofmap.kernel import Claim, Context, Inference, KernelMap, TypedRelation, closure
from proofmap.paper_actions import (
    plan_evidence_actions,
    plan_paper_actions,
    rank_evidence_actions,
    request_action,
    simulate_evidence_actions,
    simulate_paper_actions,
    validate_action_record,
)
from proofmap.trust import sign_record


def graph():
    return KernelMap(
        claims=tuple(Claim(n, n, "c", "r1") for n in "ABC"),
        contexts=(Context("c", "definitions-v1"),),
        inferences=(Inference("i", "C", ("A", "B"), "c"),),
    )


def paper():
    import test_execution as fixture

    assertion = {"id": "claim", "revision": "a" * 64, "scope": "global", "statement": "x + 0 = x"}
    binding = FormalizationBinding.create(
        revision_id=assertion["revision"],
        assertion_id="claim",
        assertion_digest=digest("assertion.v1", assertion),
        source_locators=[{"file": "paper.tex", "start": 0, "end": 10}],
        context_digest="c" * 64,
        definition_digest="d" * 64,
        obligation=fixture.obligation(),
        method="integer-polynomial-v1",
    )
    return {
        "input_manifest": {"revision": assertion["revision"]},
        "assertions": [assertion],
        "formalizations": [
            {
                "assertion_id": "claim",
                "status": "SUPPORTED",
                "binding": binding.to_dict(),
                "obligation": fixture.obligation().to_dict(),
            }
        ],
        "execution_events": [],
        "acceptance_records": [],
    }


def simulated_signed_paper(monkeypatch):
    import test_execution as fixture

    bundle = paper()
    binding = FormalizationBinding.from_dict(bundle["formalizations"][0]["binding"])
    monkeypatch.setattr(fixture, "binding", lambda: binding)
    result, private, trust = fixture.simulated_execution(monkeypatch)
    bundle["execution_events"] = [result]
    bundle["formalizations"][0]["execution_event"] = result["event"]["id"]
    authority = {
        "profile": fixture.profile().to_dict(),
        "trust_store": trust,
        "evaluation_time": "2026-10-02T00:00:00Z",
    }
    return bundle, binding, private, authority


def ids(plan, kind=None):
    return [a["id"] for a in plan["actions"] if kind is None or a["kind"] == kind]


def test_missing_premise_and_certificate_have_distinct_exact_actions():
    g = graph()
    plan = plan_evidence_actions(g, foundations=(("c", "A"),))
    premise = next(a for a in plan["actions"] if a["kind"] == "PROVE_PREMISE")
    verify = next(a for a in plan["actions"] if a["kind"] == "VERIFY_INFERENCE")
    assert premise["subject"]["id"] == "B"
    assert verify["subject"] == {
        "kind": "inference",
        "id": "i",
        "digest": g.inference_digest(g.inferences[0]),
    }
    assert premise["required_artifact"] != verify["required_artifact"]
    assert premise["expected_gain"] is None and premise["estimated_cost"] is None
    assert plan["actual"]["closed"] == ["A"]


def test_counterfactual_and_witnesses_do_not_mutate_actual_claims_or_evidence():
    g = graph()
    before = canonical_bytes(g.to_dict())
    plan = plan_evidence_actions(g, foundations=(("c", "A"),))
    partial = simulate_evidence_actions(g, ids(plan, "VERIFY_INFERENCE"), foundations=(("c", "A"),))
    assert partial["delta"] == []
    result = simulate_evidence_actions(g, ids(plan), foundations=(("c", "A"),))
    assert result["actual"]["closed"] == ["A"]
    assert result["hypothetical"]["closed"] == ["A", "B", "C"]
    assert set(result["hypothetical"]["witnesses"]["C"]["actions"]) == set(ids(plan))
    assert result["hypothetical"]["witnesses"]["C"]["inferences"] == ["i"]
    assert result["execution"] == "NOT_RUN" and result["authority"] == "PLANNING_ONLY"
    assert canonical_bytes(g.to_dict()) == before
    assert closure(g, foundations=(("c", "A"),)).closed == ("A",)


def test_visual_relations_cannot_improve_actual_or_hypothetical_closure():
    g = graph()
    decorated = replace(
        g, relations=(TypedRelation("A", "C", "CITES"), TypedRelation("B", "C", "CONTRADICTS"))
    )
    options = {"foundations": (("c", "A"),)}
    first, second = plan_evidence_actions(g, **options), plan_evidence_actions(decorated, **options)
    assert first["actions"] == second["actions"]
    assert first["actual"]["closed"] == second["actual"]["closed"]
    assert (
        simulate_evidence_actions(g, ids(first), **options)["delta"]
        == simulate_evidence_actions(decorated, ids(second), **options)["delta"]
    )


def test_cyclic_inferences_do_not_seed_counterfactual_closure():
    g = replace(
        graph(), inferences=(Inference("i", "B", ("A",), "c"), Inference("j", "A", ("B",), "c"))
    )
    plan = plan_evidence_actions(g)
    result = simulate_evidence_actions(g, ids(plan, "VERIFY_INFERENCE"))
    assert result["hypothetical"]["closed"] == []


def test_context_discharge_is_an_action_but_no_guessed_simulated_proof():
    g = graph()
    g = replace(g, claims=(replace(g.claims[0], scope="local"), *g.claims[1:]))
    plan = plan_evidence_actions(g)
    assert any(a["kind"] == "RESOLVE_CONTEXT" and a["effect"] == "NONE" for a in plan["actions"])
    assert "C" not in simulate_evidence_actions(g, ids(plan))["hypothetical"]["closed"]


@pytest.mark.parametrize(
    "mode,policy",
    [("COMPUTATIONAL", "computational-reproducible-v1"), ("EMPIRICAL", "empirical-support-v1")],
)
def test_reproduction_plans_preserve_unknown_empirical_gain(mode, policy):
    g = replace(graph(), inferences=(Inference("i", "C", (), "c", mode=mode),))
    plan = plan_evidence_actions(g, policy=policy)
    action = next(a for a in plan["actions"] if a["kind"] == "COMPUTATIONAL_REPRODUCTION")
    assert action["mode"] == mode and action["expected_gain"] is None
    assert rank_evidence_actions(plan)[0]["expected_gain"] is None


def test_cached_authority_labels_cannot_satisfy_reviews_or_verification():
    bundle = paper()
    bundle["acceptance_records"] = [
        {"assessment": "ACCEPTED_UNDER_POLICY", "formal_status": "VERIFIED"}
    ]
    plan = plan_paper_actions(bundle)
    assert plan["actual"]["authority_evaluated"] is False
    assert plan["actual"]["accepted"] == [] and plan["actual"]["unknown"] == ["claim"]
    assert {a["kind"] for a in plan["actions"]} == {
        "VERIFY_FORMAL_SUBJECT",
        "SOURCE_FIDELITY_REVIEW",
        "FORMAL_FIDELITY_REVIEW",
    }


def test_paper_review_prerequisites_and_declared_counterfactual_delta():
    bundle = paper()
    original = canonical_bytes(bundle)
    plan = plan_paper_actions(bundle)
    review_ids = ids(plan, "SOURCE_FIDELITY_REVIEW") + ids(plan, "FORMAL_FIDELITY_REVIEW")
    result = simulate_paper_actions(bundle, review_ids)
    assert result["delta"] == [] and set(result["blocked_actions"]) == set(review_ids)
    full = simulate_paper_actions(bundle, ids(plan))
    assert full["delta"] == ["claim"]
    assert full["actual"]["accepted"] == []
    assert set(full["hypothetical"]["witnesses"]["claim"]["actions"]) == set(ids(plan))
    assert canonical_bytes(bundle) == original and bundle["execution_events"] == []


def test_current_verified_subject_needs_review_not_another_premise_proof(monkeypatch):
    bundle, binding, private, authority = simulated_signed_paper(monkeypatch)
    plan = plan_paper_actions(bundle, **authority)
    assert plan["actual"]["verified"] == ["claim"] and plan["actual"]["accepted"] == []
    assert {a["kind"] for a in plan["actions"]} == {
        "SOURCE_FIDELITY_REVIEW",
        "FORMAL_FIDELITY_REVIEW",
    }
    assert all(a["prerequisites"] == [] for a in plan["actions"])
    assert simulate_paper_actions(bundle, ids(plan), **authority)["delta"] == ["claim"]
    assert (
        plan_evidence_actions(graph())["actions"][0]["required_artifact"]
        != plan["actions"][0]["required_artifact"]
    )


def test_current_authenticated_reviews_remove_actions_revocation_restores_them(monkeypatch):
    import test_execution as fixture

    bundle, binding, private, authority = simulated_signed_paper(monkeypatch)
    authority["trust_store"]["keys"][0]["roles"] += [
        "source-fidelity-review",
        "formal-fidelity-review",
    ]
    reviews = [
        sign_record(
            ReviewDecision.create(
                binding=binding,
                profile=fixture.profile(),
                dimension=dimension,
                decision="APPROVE",
                reviewer_id="controller",
            ).to_dict(),
            private,
            "controller",
        )
        for dimension in ("source-fidelity", "formal-fidelity")
    ]
    accepted = plan_paper_actions(bundle, reviews=reviews, **authority)
    assert accepted["actual"]["accepted"] == ["claim"] and accepted["actions"] == []
    authority["trust_store"]["keys"][0]["revoked"] = True
    revoked = plan_paper_actions(bundle, reviews=reviews, **authority)
    assert revoked["actual"]["accepted"] == [] and revoked["actual"]["verified"] == []
    assert any(a["kind"] == "AUTHENTICATE_EVIDENCE" for a in revoked["actions"])
    assert revoked["id"] != accepted["id"]


def test_unsupported_source_plan_never_predicts_acceptance():
    bundle = paper()
    bundle["formalizations"] = [
        {"assertion_id": "claim", "status": "UNSUPPORTED", "reason": "unknown quantifier"}
    ]
    plan = plan_paper_actions(bundle)
    assert plan["actions"][0]["kind"] == "RESOLVE_CONTEXT"
    assert simulate_paper_actions(bundle, ids(plan))["delta"] == []


def test_requests_are_auditable_but_never_run_or_sign(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Planning attempted execution or signing")

    monkeypatch.setattr("proofmap.execution.execute", forbidden)
    monkeypatch.setattr("proofmap.trust.sign_record", forbidden)
    plan = plan_paper_actions(paper())
    request = request_action(
        plan, ids(plan)[0], actor="researcher", requested_at="2026-10-02T00:00:00Z"
    )
    assert request["status"] == "REQUESTED" and request["event_ids"] == []
    assert request["execution"] == "NOT_RUN" and request["attribution_authenticated"] is False
    validate_action_record(request)
    assert simulate_paper_actions(paper(), ids(plan))["execution"] == "NOT_RUN"


@pytest.mark.parametrize("mutation", ["revision", "statement", "duplicate", "obligation"])
def test_cross_revision_and_substituted_subjects_rejected(mutation):
    bundle = paper()
    if mutation == "revision":
        bundle["input_manifest"]["revision"] = "f" * 64
    elif mutation == "statement":
        bundle["assertions"][0]["statement"] = "different"
    elif mutation == "duplicate":
        bundle["formalizations"] *= 2
    else:
        bundle["formalizations"][0]["obligation"]["statement"] = "False"
    with pytest.raises(ValueError):
        plan_paper_actions(bundle)


@pytest.mark.parametrize("selection", [["f" * 64], "duplicate"])
def test_unknown_or_duplicate_actions_rejected(selection):
    plan = plan_evidence_actions(graph())
    if selection == "duplicate":
        selection = [ids(plan)[0]] * 2
    with pytest.raises(ValueError, match="ACTION_"):
        simulate_evidence_actions(graph(), selection)


def test_changed_binding_rejects_old_action_ids():
    bundle = paper()
    plan = plan_paper_actions(bundle)
    changed = deepcopy(bundle)
    changed["formalizations"] = [{"assertion_id": "claim", "status": "UNSUPPORTED"}]
    with pytest.raises(ValueError, match="STALE"):
        simulate_paper_actions(changed, ids(plan))


@pytest.mark.parametrize("cost", [True, -1, float("nan"), float("inf"), "cheap"])
def test_invalid_costs_are_not_scientific_values(cost):
    plan = plan_evidence_actions(graph())
    with pytest.raises(ValueError, match="COST"):
        rank_evidence_actions(plan, costs={ids(plan)[0]: cost})


def test_named_ranking_keeps_unknowns_null_and_records_supplied_cost_basis():
    plan = plan_evidence_actions(graph())
    ranked = rank_evidence_actions(plan)
    assert all(
        r["expected_gain"] is None and r["estimated_cost"] is None and r["score"] is None
        for r in ranked
    )
    ranked = rank_evidence_actions(plan, costs={ids(plan)[0]: 2.5})
    supplied = next(r for r in ranked if r["action"]["id"] == ids(plan)[0])
    assert (
        supplied["estimated_cost"] == 2.5
        and supplied["cost_basis"] == "caller-estimated effort units"
    )
    assert supplied["heuristic"] == {"name": "conditional-closure-planning", "version": "1"}


@pytest.mark.parametrize(
    "field,value", [("schema_version", "9.0"), ("authority", "TRUSTED"), ("extra", True)]
)
def test_rehashed_unknown_record_semantics_rejected(field, value):
    plan = plan_evidence_actions(graph())
    plan[field] = value
    plan["id"] = digest("action-planning.v1", {k: v for k, v in plan.items() if k != "id"})
    with pytest.raises(ValueError, match="SCHEMA"):
        validate_action_record(plan)


def test_incomplete_authority_is_not_silently_ignored():
    with pytest.raises(ValueError, match="AUTHORITY_INPUTS"):
        plan_paper_actions(paper(), trust_store={})


@pytest.mark.parametrize(
    "actor,when", [("", "2026-10-02T00:00:00Z"), ("reader", "now"), ("reader", "2026-10-02")]
)
def test_request_requires_explicit_attribution_and_timezone(actor, when):
    plan = plan_evidence_actions(graph())
    with pytest.raises(ValueError, match="REQUEST"):
        request_action(plan, ids(plan)[0], actor=actor, requested_at=when)


def test_valid_inference_evidence_only_requires_missing_premise():
    from test_kernel import certified

    g = replace(graph(), inferences=())
    g, trusted = certified(g, Inference("i", "C", ("A", "B"), "c"))
    plan = plan_evidence_actions(g, foundations=(("c", "A"),), trusted_evidence=(trusted,))
    assert [a["kind"] for a in plan["actions"]] == ["PROVE_PREMISE"]
    result = simulate_evidence_actions(
        g, ids(plan), foundations=(("c", "A"),), trusted_evidence=(trusted,)
    )
    assert result["delta"] == ["B", "C"] and result["actual"]["closed"] == ["A"]


@pytest.mark.parametrize(
    "change,expected",
    [
        ("stale", "REFRESH_EVIDENCE"),
        ("untrusted", "AUTHENTICATE_EVIDENCE"),
        ("invalid", "VERIFY_INFERENCE"),
    ],
)
def test_specific_evidence_failures_produce_matching_repairs(change, expected):
    from test_kernel import certified

    g, trusted = certified(replace(graph(), inferences=()), Inference("i", "C", ("A", "B"), "c"))
    if change == "stale":
        g = replace(g, contexts=(Context("c", "definitions-v2"),))
    elif change == "invalid":
        g = replace(g, evidence=(replace(g.evidence[0], outcome="FAIL"),))
        trusted = g.evidence[0].digest
    plan = plan_evidence_actions(g, trusted_evidence=() if change == "untrusted" else (trusted,))
    assert any(a["kind"] == expected for a in plan["actions"])


def test_alternative_derivation_has_its_own_witness():
    g = replace(
        graph(), inferences=(Inference("i", "C", ("A",), "c"), Inference("j", "C", ("B",), "c"))
    )
    plan = plan_evidence_actions(g, foundations=(("c", "A"),))
    selected = [a["id"] for a in plan["actions"] if a["subject"]["id"] == "i"]
    result = simulate_evidence_actions(g, selected, foundations=(("c", "A"),))
    assert result["delta"] == ["C"] and result["hypothetical"]["witnesses"]["C"]["inferences"] == [
        "i"
    ]
    assert "B" not in result["hypothetical"]["closed"]


def test_legacy_adapter_preserves_status_uncertainty_and_metrics():
    from proofmap.examples import build_minimal_conops_map
    from proofmap.optimizer import rank_closure_candidates, simulate_closure

    pm = build_minimal_conops_map()
    original = canonical_bytes(pm.to_dict())
    ranked = rank_closure_candidates(pm, limit=2)
    assert ranked and ranked[0].action_ids
    before, after, scenario = simulate_closure(pm, ranked[0].node_id, proposed_uncertainty=0.0)
    assert before.to_dict() == after.to_dict()
    assert scenario.nodes[ranked[0].node_id].to_dict() == pm.nodes[ranked[0].node_id].to_dict()
    assert canonical_bytes(pm.to_dict()) == original
    assert scenario.metadata["scenario_overlay"]["counterfactual"]["authority"] == "PLANNING_ONLY"


@pytest.mark.parametrize("limit", [True, -1, 1.5])
def test_legacy_adapter_rejects_invalid_limit(limit):
    from proofmap.examples import build_minimal_conops_map
    from proofmap.optimizer import rank_closure_candidates

    with pytest.raises(ValueError, match="LIMIT"):
        rank_closure_candidates(build_minimal_conops_map(), limit=limit)


def test_counterfactual_rehashed_false_delta_is_rejected():
    plan = plan_evidence_actions(graph())
    scenario = simulate_evidence_actions(graph(), ids(plan))
    scenario["delta"] = []
    scenario["id"] = digest("action-planning.v1", {k: v for k, v in scenario.items() if k != "id"})
    with pytest.raises(ValueError, match="COUNTERFACTUAL_BINDING"):
        validate_action_record(scenario)


def test_rehashed_dangling_prerequisite_is_rejected():
    plan = plan_evidence_actions(graph())
    action = plan["actions"][0]
    action["prerequisites"] = ["f" * 64]
    action["id"] = digest("evidence-action.v1", {k: v for k, v in action.items() if k != "id"})
    plan["id"] = digest("action-planning.v1", {k: v for k, v in plan.items() if k != "id"})
    with pytest.raises(ValueError, match="DANGLING"):
        validate_action_record(plan)


def test_rehashed_counterfactual_authority_is_rejected():
    plan = plan_paper_actions(paper())
    plan["actual"]["accepted"] = ["claim"]
    plan["actual"]["verified"] = ["claim"]
    plan["id"] = digest("action-planning.v1", {k: v for k, v in plan.items() if k != "id"})
    with pytest.raises(ValueError, match="AUTHORITY_NOT_EVALUATED"):
        validate_action_record(plan)


def test_historical_execution_reuse_still_requires_current_reviews(monkeypatch):
    import test_execution as fixture

    bundle, previous, _, authority = simulated_signed_paper(monkeypatch)
    history = {
        "parent_run_id": "original-run",
        "parent_revision": previous.revision_id,
        "binding": previous.to_dict(),
        "obligation": fixture.obligation().to_dict(),
        "execution": bundle["execution_events"][0],
    }
    historical_bytes = canonical_bytes(history)
    assertion = {
        "id": "new-claim",
        "revision": "e" * 64,
        "scope": "global",
        "statement": "x + 0 = x",
    }
    obligation = replace(fixture.obligation(), id="new-obligation", target_node_id="new-claim")
    current = FormalizationBinding.create(
        revision_id=assertion["revision"],
        assertion_id=assertion["id"],
        assertion_digest=digest("assertion.v1", assertion),
        source_locators=[{"file": "moved.tex", "start": 0, "end": 10}],
        context_digest="1" * 64,
        definition_digest="2" * 64,
        obligation=obligation,
        method="integer-polynomial-v1",
    )
    bundle.update(
        input_manifest={"revision": assertion["revision"]},
        assertions=[assertion],
        execution_events=[],
        formalizations=[
            {
                "assertion_id": assertion["id"],
                "status": "SUPPORTED",
                "binding": current.to_dict(),
                "obligation": obligation.to_dict(),
                "historical_execution": history,
            }
        ],
    )
    plan = plan_paper_actions(bundle, **authority)
    assert plan["actual"]["verified"] == ["new-claim"] and plan["actual"]["accepted"] == []
    assert {a["kind"] for a in plan["actions"]} == {
        "SOURCE_FIDELITY_REVIEW",
        "FORMAL_FIDELITY_REVIEW",
    }
    assert simulate_paper_actions(bundle, ids(plan), **authority)["delta"] == ["new-claim"]
    assert canonical_bytes(history) == historical_bytes and bundle["execution_events"] == []
    authority["trust_store"]["keys"][0]["revoked"] = True
    revoked = plan_paper_actions(bundle, **authority)
    assert revoked["actual"]["verified"] == []
    assert ids(revoked, "AUTHENTICATE_EVIDENCE")


def test_automatic_source_has_exact_binding_plan_without_running_verification(tmp_path):
    from proofmap.paper import ci

    source = tmp_path / "paper.tex"
    source.write_text(
        r"\documentclass{article}\begin{document}\begin{theorem}"
        r"For every $x\in\mathbb{Z}$, \[(x+2)^2=x^2+4x+4.\]"
        r"\end{theorem}\end{document}",
        encoding="utf-8",
    )
    bundle, code = ci(source, tmp_path / "out", tmp_path / "store")
    assert code == 0 and bundle["execution_events"] == []
    plan = plan_paper_actions(bundle)
    row = bundle["formalizations"][0]
    assert row["status"] == "SUPPORTED"
    assert all(a["subject"]["digest"] == row["binding"]["id"] for a in plan["actions"])
    assert all(a["subject"]["id"] == row["assertion_id"] for a in plan["actions"])
    assert plan["actual"]["accepted"] == []
    assert Path(tmp_path / "out" / "report.html").is_file()
