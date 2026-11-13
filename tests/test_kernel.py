from dataclasses import replace

import pytest

from proofmap.examples import build_minimal_conops_map
from proofmap.kernel import (
    POLICIES,
    Claim,
    Context,
    EvidenceArtifact,
    Inference,
    KernelMap,
    TypedRelation,
    closure,
    migrate,
    semantic_digest,
)


def graph():
    return KernelMap(
        contexts=(Context("c", "definitions-v1"),),
        claims=tuple(Claim(n, n, "c", "r1") for n in "ABCD"),
    )


def certified(g, inference, policy="deductive-strict-v1"):
    p = POLICIES[policy]
    e = EvidenceArtifact(
        "e-" + inference.id,
        inference.id,
        g.inference_digest(inference),
        "c",
        "definitions-v1",
        p.digest,
        inference.mode,
        "PASS",
        "a" * 64,
    )
    inference = replace(inference, evidence=(e.id,))
    return replace(g, inferences=g.inferences + (inference,), evidence=g.evidence + (e,)), e.digest


def test_f01_conjunction_not_reachability():
    g, trusted = certified(graph(), Inference("i", "C", ("A", "B"), "c"))
    result = closure(g, foundations=(("c", "A"),), trusted_evidence=(trusted,))
    assert result.closed == ("A",)
    assert result.unresolved_premises["i"] == ("B",)
    assert closure(g, foundations=(("c", "A"), ("c", "B")), trusted_evidence=(trusted,)).closed == (
        "A",
        "B",
        "C",
    )


def test_support_does_not_credit_untrusted_extra_artifact():
    g, trusted = certified(graph(), Inference("i", "B", ("A",), "c"))
    bad = replace(g.evidence[0], id="untrusted", artifact_digest="b" * 64)
    g = replace(
        g,
        evidence=g.evidence + (bad,),
        inferences=(replace(g.inferences[0], evidence=(g.evidence[0].id, bad.id)),),
    )
    result = closure(g, foundations=(("c", "A"),), trusted_evidence=(trusted,))
    assert result.justifications["B"][0].evidence == (g.evidence[0].id,)


def test_cycles_labels_unsigned_and_stale_never_close():
    g, t = certified(graph(), Inference("i", "B", ("A",), "c"))
    g, u = certified(g, Inference("j", "A", ("B",), "c"))
    assert not closure(g, trusted_evidence=(t, u)).closed
    assert closure(g, foundations=(("c", "A"),)).closed == ("A",)
    changed = replace(
        g, claims=tuple(replace(c, statement="changed") if c.id == "B" else c for c in g.claims)
    )
    assert closure(changed, foundations=(("c", "A"),), trusted_evidence=(t, u)).closed == ("A",)


def test_or_alternatives_preserve_minimal_assumptions():
    g, t = certified(graph(), Inference("i", "C", ("A",), "c"), "conditional-research-v1")
    g, u = certified(g, Inference("j", "C", ("B",), "c"), "conditional-research-v1")
    result = closure(
        g,
        policy="conditional-research-v1",
        assumptions=(("c", "A"), ("c", "B")),
        trusted_evidence=(t, u),
    )
    assert result.conditional == ("A", "B", "C")
    assert [s.assumptions for s in result.justifications["C"]] == [("c:A",), ("c:B",)]
    result = closure(
        g,
        policy="conditional-research-v1",
        foundations=(("c", "A"),),
        assumptions=(("c", "B"),),
        trusted_evidence=(t, u),
    )
    assert "C" in result.closed and "C" not in result.conditional
    assert any(s.assumptions == () for s in result.justifications["C"])


def test_f04_order_invariant_hash_and_closure():
    g = graph()
    reverse = replace(g, claims=tuple(reversed(g.claims)))
    assert semantic_digest(g) == semantic_digest(reverse)
    assert closure(g).to_dict() == closure(reverse).to_dict()
    assert semantic_digest(
        replace(g, claims=(replace(g.claims[0], statement="other"),) + g.claims[1:])
    ) != semantic_digest(g)


def test_migration_is_idempotent_conservative_and_preserves_original():
    original = build_minimal_conops_map().to_dict()
    migrated = migrate(original)
    assert migrate(migrated.to_dict()).to_dict() == migrated.to_dict()
    assert migrated.legacy == original
    assert not closure(migrated).closed
    assert all(i.status == "REVIEW_REQUIRED" for i in migrated.inferences)
    assert migrated.warnings


def test_local_hypotheses_do_not_leak():
    g = graph()
    g = replace(g, claims=(replace(g.claims[0], scope="lemma"),) + g.claims[1:])
    with pytest.raises(ValueError):
        closure(g, assumptions=(("c", "A"),), policy="conditional-research-v1")


def test_status_is_not_proof_and_paper_policy_cannot_accept():
    g = graph()
    g = replace(g, claims=tuple(replace(c, status="PROVED") for c in g.claims))
    assert not closure(g).closed
    assert not closure(g, policy="paper-assertion-v1").closed


def test_kernel_additional_validation_boundaries():
    g = graph()
    bad = [
        replace(g, inferences=(Inference("A", "B", ("A",), "c"),)),
        replace(g, claims=(replace(g.claims[0], statement=3),) + g.claims[1:]),
        replace(g, claims=(replace(g.claims[0], hypotheses=["x"]),) + g.claims[1:]),
        replace(g, inferences=(Inference("i", "B", ("A",), "c", mode="UNKNOWN"),)),
        replace(g, inferences=(Inference("i", "B", ("A",) * 257, "c"),)),
        replace(
            g,
            contexts=g.contexts + (Context("d", "r"),),
            claims=(replace(g.claims[0], context="d"),) + g.claims[1:],
            inferences=(Inference("i", "B", ("A",), "c"),),
        ),
        replace(g, relations=(TypedRelation("A", "A", "PROVES"),)),
        replace(g, relations=(TypedRelation("A", "missing", "PROVES"),)),
    ]
    for invalid in bad:
        with pytest.raises(ValueError):
            invalid.validate()
    value = g.to_dict()
    value["claims"] = "not-array"
    with pytest.raises(ValueError):
        KernelMap.from_dict(value)
    value = g.to_dict()
    value["claims"][0]["unexpected"] = True
    with pytest.raises(ValueError):
        KernelMap.from_dict(value)


def test_blocked_scopes_and_contradictions_are_not_proof():
    g = graph()
    g = replace(
        g,
        claims=(replace(g.claims[0], scope="local"), replace(g.claims[1], status="BLOCKED"))
        + g.claims[2:],
        inferences=(Inference("i", "B", ("A",), "c", assumptions=("C",)),),
        relations=(TypedRelation("C", "D", "CONTRADICTS"),),
    )
    result = closure(g)
    assert not result.closed
    assert result.contradictions == (("C", "D"),)
    assert set(result.evidence_issues["i"]) >= {
        "CONCLUSION_BLOCKED",
        "UNVERIFIED_SCOPE_DISCHARGE",
        "UNACCEPTED_EXTRA_ASSUMPTION",
    }


def test_bound_exhaustion_is_explicit_not_complete(monkeypatch):
    policy = replace(POLICIES["conditional-research-v1"], max_alternatives=1)
    monkeypatch.setitem(POLICIES, policy.id, policy)
    g, t = certified(graph(), Inference("i", "C", ("A",), "c"), policy.id)
    g, u = certified(g, Inference("j", "C", ("B",), "c"), policy.id)
    result = closure(
        g, policy=policy.id, assumptions=(("c", "A"), ("c", "B")), trusted_evidence=(t, u)
    )
    assert result.truncated
    assert len(result.justifications["C"]) == 1
    monkeypatch.setitem(
        POLICIES, "deductive-strict-v1", replace(POLICIES["deductive-strict-v1"], max_updates=1)
    )
    g, t = certified(graph(), Inference("i", "B", ("A",), "c"))
    assert closure(g, foundations=(("c", "A"),), trusted_evidence=(t,)).truncated
