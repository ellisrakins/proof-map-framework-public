"""Policy-qualified AND/OR kernel. Authored statuses never confer acceptance.

Trust is supplied by the caller as content digests, never read from the graph.
The conservative scope rule refuses discharge rather than guessing a theorem.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field, fields
from itertools import islice, product
from typing import Any, Iterable, Mapping

from .integrity import ValidationIssue, canonical_bytes, digest, json_value, require_digest

SCHEMA = "urn:proofmap:kernel:1"
VERSION = "1.0"
DIMENSIONS = (
    "deductive",
    "computational",
    "empirical_support",
    "empirical_contradiction",
    "approximation",
    "source_fidelity",
    "formal_fidelity",
    "independent_review",
    "novelty",
)
STATES = {
    "AUTHOR_ASSERTED",
    "REVIEW_REQUIRED",
    "PROVED",
    "CORE",
    "GAP",
    "BLOCKED",
    "REJECTED",
    "ACTIVE",
}
MODES = {"DEDUCTIVE", "COMPUTATIONAL", "EMPIRICAL", "APPROXIMATION", "PAPER_ASSERTION"}


@dataclass(frozen=True)
class Claim:
    id: str
    statement: str
    context: str
    revision: str
    status: str = "AUTHOR_ASSERTED"
    scope: str = "global"
    hypotheses: tuple[str, ...] = ()
    quantifiers: tuple[str, ...] = ()
    label: str = ""


Proposition = Claim


@dataclass(frozen=True)
class Context:
    id: str
    definition_revision: str
    description: str = ""


@dataclass(frozen=True)
class Foundation:
    context: str
    claim: str


@dataclass(frozen=True)
class Inference:
    id: str
    conclusion: str
    premises: tuple[str, ...]
    context: str
    mode: str = "DEDUCTIVE"
    assumptions: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    status: str = "ACTIVE"
    scope: str = "global"


@dataclass(frozen=True)
class EvidenceArtifact:
    id: str
    subject: str
    subject_digest: str
    context: str
    definition_revision: str
    policy_digest: str
    mode: str
    outcome: str
    artifact_digest: str

    @property
    def digest(self) -> str:
        return digest("evidence.v1", asdict(self))


@dataclass(frozen=True)
class VerificationEvent:
    id: str
    evidence_digest: str
    execution_status: str
    runner_provenance_digest: str
    parent_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Assessment:
    """Independent dimensions; never collapse these into a truth/confidence scalar."""

    subject: str
    dimensions: Mapping[str, str] = field(
        default_factory=lambda: {d: "NOT_ASSESSED" for d in DIMENSIONS}
    )


@dataclass(frozen=True)
class Policy:
    id: str
    modes: tuple[str, ...]
    dimension: str
    allow_assumptions: bool = False
    max_alternatives: int = 64
    max_combinations: int = 4096
    max_updates: int = 200_000

    @property
    def digest(self) -> str:
        return digest("policy.v1", asdict(self))


POLICIES = {
    p.id: p
    for p in (
        Policy("deductive-strict-v1", ("DEDUCTIVE",), "deductive"),
        Policy("computational-reproducible-v1", ("COMPUTATIONAL",), "computational"),
        Policy("empirical-support-v1", ("EMPIRICAL",), "empirical_support"),
        Policy("conditional-research-v1", ("DEDUCTIVE",), "deductive", True),
        Policy("paper-assertion-v1", (), "source_fidelity"),
    )
}


@dataclass(frozen=True)
class RelationSpec:
    direction: str
    domain: str = "claim"
    range: str = "claim"
    self_allowed: bool = False
    cycles_allowed: bool = True
    closure_role: str = "none; only certified first-class inferences can close claims"
    views: tuple[str, ...] = ("visualization", "dependency")
    same_context: bool = False
    symmetric: bool = False


# This kernel's endpoint domain is deliberately claims. Source documents,
# execution events and reviewer identities have their own record types and may
# not masquerade as endpoints. These relations describe authored structure;
# only a certified Inference contributes to deductive closure.
RELATIONS = {
    "PROVES": RelationSpec("claimed proof source -> claimed conclusion", same_context=True),
    "DEPENDS_ON": RelationSpec("prerequisite source -> dependent target", same_context=True),
    "DEFINES": RelationSpec(
        "definition source -> defined claim", cycles_allowed=False, same_context=True
    ),
    "BRIDGES": RelationSpec(
        "source context claim -> target context claim", views=("visualization", "context")
    ),
    "INTERFACE": RelationSpec(
        "interacting source <-> target", views=("visualization", "interface"), symmetric=True
    ),
    "LIMITS_TO": RelationSpec(
        "general claim -> limiting claim",
        cycles_allowed=False,
        views=("visualization", "approximation"),
    ),
    "APPROXIMATES": RelationSpec(
        "approximation -> reference claim", views=("visualization", "approximation")
    ),
    "EMPIRICALLY_CONSTRAINS": RelationSpec(
        "observation claim -> constrained claim", views=("visualization", "empirical")
    ),
    "FLOWS_TO": RelationSpec("source state -> destination state", views=("visualization", "flow")),
    "TRANSFORMS_TO": RelationSpec(
        "input claim -> transformed claim", views=("visualization", "flow")
    ),
    "BLOCKS": RelationSpec(
        "blocking claim -> blocked claim", views=("visualization", "diagnostic")
    ),
    "CONTRADICTS": RelationSpec(
        "conflicting source <-> target", views=("visualization", "contradiction"), symmetric=True
    ),
    "CITES": RelationSpec("citing claim -> cited claim", views=("visualization", "citation")),
    "MODEL_INFERRED_DEPENDENCY": RelationSpec(
        "candidate prerequisite -> candidate dependent", views=("visualization", "candidate")
    ),
}


def _identifier(value: Any, code: str) -> None:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(code)


def _strings(value: Any, code: str, *, identifiers: bool = False) -> None:
    if not isinstance(value, tuple) or any(not isinstance(x, str) for x in value):
        raise ValueError(code)
    if identifiers and (len(value) != len(set(value)) or any(not x or len(x) > 512 for x in value)):
        raise ValueError(code)


@dataclass(frozen=True)
class TypedRelation:
    source: str
    target: str
    kind: str


@dataclass(frozen=True)
class KernelMap:
    claims: tuple[Claim, ...] = ()
    contexts: tuple[Context, ...] = ()
    inferences: tuple[Inference, ...] = ()
    evidence: tuple[EvidenceArtifact, ...] = ()
    relations: tuple[TypedRelation, ...] = ()
    warnings: tuple[str, ...] = ()
    legacy: Mapping[str, Any] | None = None

    def validate(self) -> None:
        for records, typ in (
            (self.claims, Claim),
            (self.contexts, Context),
            (self.inferences, Inference),
            (self.evidence, EvidenceArtifact),
            (self.relations, TypedRelation),
        ):
            if not isinstance(records, tuple) or any(not isinstance(row, typ) for row in records):
                raise ValueError("KERNEL_RECORD_TYPE")
        _strings(self.warnings, "KERNEL_WARNINGS_TYPE")
        if self.legacy is not None and not isinstance(self.legacy, Mapping):
            raise ValueError("KERNEL_LEGACY_TYPE")
        json_value(self.to_dict())
        if len(self.claims) > 100_000 or len(self.inferences) > 200_000:
            raise ValueError("RESOURCE_LIMIT: graph size")
        groups = (self.claims, self.contexts, self.inferences, self.evidence)
        for group in groups:
            ids = [x.id for x in group]
            if any(not isinstance(x, str) or not x or len(x) > 512 for x in ids) or len(ids) != len(
                set(ids)
            ):
                raise ValueError("DUPLICATE_OR_INVALID_ID")
        if {x.id for x in self.claims} & {x.id for x in self.inferences}:
            raise ValueError("AMBIGUOUS_SUBJECT_ID")
        contexts = {x.id: x for x in self.contexts}
        claims = {x.id: x for x in self.claims}
        inference_ids = {i.id for i in self.inferences}
        for context in self.contexts:
            if not isinstance(context.definition_revision, str) or not context.definition_revision:
                raise ValueError("CONTEXT_REVISION_REQUIRED")
            _identifier(context.definition_revision, "CONTEXT_REVISION_REQUIRED")
            if not isinstance(context.description, str):
                raise ValueError("CONTEXT_DESCRIPTION_TYPE")
        for c in self.claims:
            for value in (c.context, c.revision, c.scope, c.status):
                _identifier(value, "CLAIM_CONTEXT_OR_STATE")
            if c.context not in contexts or c.status not in STATES or not c.revision or not c.scope:
                raise ValueError(f"CLAIM_CONTEXT_OR_STATE: {c.id}")
            if not isinstance(c.statement, str) or not isinstance(c.label, str):
                raise ValueError("CLAIM_STATEMENT_TYPE")
            for key in (c.hypotheses, c.quantifiers):
                _strings(key, "CLAIM_SCOPE_TYPE")
        evidence_ids = {e.id for e in self.evidence}
        for i in self.inferences:
            for value in (i.context, i.conclusion, i.scope, i.mode, i.status):
                _identifier(value, "INFERENCE_CONTEXT_OR_STATE")
            for values in (i.premises, i.assumptions, i.evidence):
                _strings(values, "INFERENCE_REFERENCE_TYPE", identifiers=True)
            if any(eid not in evidence_ids for eid in i.evidence):
                raise ValueError("DANGLING_INFERENCE_EVIDENCE: " + i.id)
            if i.context not in contexts or i.status not in STATES or i.mode not in MODES:
                raise ValueError(f"INFERENCE_CONTEXT_OR_STATE: {i.id}")
            if i.conclusion not in claims or any(
                p not in claims for p in i.premises + i.assumptions
            ):
                raise ValueError(f"MISSING_ENDPOINT: {i.id}")
            if len(i.premises) > 256 or len(i.assumptions) > 256:
                raise ValueError("RESOURCE_LIMIT: inference fan-in")
            if any(
                claims[p].context != i.context for p in i.premises + i.assumptions + (i.conclusion,)
            ):
                raise ValueError(f"CROSS_CONTEXT: {i.id}; explicit bridge claim required")
        for e in self.evidence:
            for value in (e.subject, e.context, e.definition_revision, e.mode, e.outcome):
                _identifier(value, "EVIDENCE_TYPE_OR_CONTEXT")
            if e.subject not in claims and e.subject not in inference_ids:
                raise ValueError("DANGLING_EVIDENCE_SUBJECT: " + e.id)
            for h in (e.subject_digest, e.policy_digest, e.artifact_digest):
                require_digest(h)
            if (
                e.context not in contexts
                or e.mode not in MODES
                or e.outcome
                not in {"PASS", "FAIL", "PARTIAL", "NOT_RUN", "UNAVAILABLE", "ERROR", "TIMEOUT"}
            ):
                raise ValueError("EVIDENCE_TYPE_OR_CONTEXT")
        seen_relations: set[tuple[str, str, str]] = set()
        for r in self.relations:
            if any(not isinstance(value, str) for value in (r.source, r.target, r.kind)):
                raise ValueError("INVALID_RELATION")
            if r.kind not in RELATIONS or r.source not in claims or r.target not in claims:
                raise ValueError("INVALID_RELATION")
            if r.source == r.target and not RELATIONS[r.kind].self_allowed:
                raise ValueError("SELF_RELATION")
            spec = RELATIONS[r.kind]
            if spec.same_context and claims[r.source].context != claims[r.target].context:
                raise ValueError("RELATION_CROSS_CONTEXT: " + r.kind)
            endpoints = (
                tuple(sorted((r.source, r.target))) if spec.symmetric else (r.source, r.target)
            )
            key = (r.kind, endpoints[0], endpoints[1])
            if key in seen_relations:
                raise ValueError("DUPLICATE_RELATION")
            seen_relations.add(key)
        for kind, spec in RELATIONS.items():
            if spec.cycles_allowed:
                continue
            edges: dict[str, list[str]] = defaultdict(list)
            incoming: dict[str, int] = defaultdict(int)
            for relation in self.relations:
                if relation.kind == kind:
                    edges[relation.source].append(relation.target)
                    incoming.setdefault(relation.source, 0)
                    incoming[relation.target] += 1
            pending = deque(key for key, count in incoming.items() if not count)
            removed = 0
            while pending:
                removed += 1
                for target in edges[pending.popleft()]:
                    incoming[target] -= 1
                    if incoming[target] == 0:
                        pending.append(target)
            if removed != len(incoming):
                raise ValueError("RELATION_CYCLE: " + kind)

    def validation_issues(self) -> list[ValidationIssue]:
        """Machine-readable counterpart to the compatibility ValueError boundary."""
        try:
            self.validate()
        except (ValueError, TypeError) as exc:
            return [ValidationIssue(str(exc).split(":", 1)[0], "/kernel", str(exc))]
        return []

    def inference_digest(
        self,
        inference: Inference,
        *,
        claims: Mapping[str, Claim] | None = None,
        contexts: Mapping[str, Context] | None = None,
    ) -> str:
        claims = claims if claims is not None else {c.id: c for c in self.claims}
        contexts = contexts if contexts is not None else {c.id: c for c in self.contexts}
        i = asdict(inference)
        # Evidence points back to this digest: never include that backlink.
        i.pop("evidence")
        i["premises"] = sorted(set(inference.premises))
        i["assumptions"] = sorted(set(inference.assumptions))
        return digest(
            "inference-obligation.v1",
            {
                "inference": i,
                "context": asdict(contexts[inference.context]),
                "claims": [
                    asdict(claims[n])
                    for n in sorted(
                        set(inference.premises + inference.assumptions + (inference.conclusion,))
                    )
                ],
            },
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "$schema": SCHEMA,
            "schema_version": VERSION,
            "claims": [asdict(c) for c in self.claims],
            "contexts": [asdict(c) for c in self.contexts],
            "inferences": [asdict(i) for i in self.inferences],
            "evidence": [asdict(e) for e in self.evidence],
            "relations": [asdict(r) for r in self.relations],
            "warnings": list(self.warnings),
            "legacy": self.legacy,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> KernelMap:
        if not isinstance(value, Mapping):
            raise ValueError("KERNEL_OBJECT_REQUIRED")
        expected = {
            "$schema",
            "schema_version",
            "claims",
            "contexts",
            "inferences",
            "evidence",
            "relations",
            "warnings",
            "legacy",
        }
        if (
            set(value) != expected
            or value["$schema"] != SCHEMA
            or value["schema_version"] != VERSION
        ):
            raise ValueError("UNSUPPORTED_SCHEMA_OR_FIELDS")

        def records(key: str, typ: Any, tuples: tuple[str, ...] = ()) -> tuple[Any, ...]:
            items = value[key]
            if not isinstance(items, (list, tuple)):
                raise ValueError(f"TYPE {key}: expected array")
            result = []
            for item in items:
                if not isinstance(item, Mapping):
                    raise ValueError(f"TYPE {key}: expected record object")
                if set(item) != {f.name for f in fields(typ)}:
                    raise ValueError(f"INVALID_FIELDS {key}")
                row = dict(item)
                for name in tuples:
                    if name in row:
                        if not isinstance(row[name], (list, tuple)) or any(
                            not isinstance(x, str) for x in row[name]
                        ):
                            raise ValueError(f"TYPE {key}.{name}")
                        row[name] = tuple(row[name])
                try:
                    result.append(typ(**row))
                except TypeError as exc:
                    raise ValueError(f"INVALID_FIELDS {key}") from exc
            return tuple(result)

        if not isinstance(value["warnings"], (list, tuple)):
            raise ValueError("KERNEL_WARNINGS_TYPE")
        g = cls(
            records("claims", Claim, ("hypotheses", "quantifiers")),
            records("contexts", Context),
            records("inferences", Inference, ("premises", "assumptions", "evidence")),
            records("evidence", EvidenceArtifact),
            records("relations", TypedRelation),
            tuple(value["warnings"]),
            value["legacy"],
        )
        g.validate()
        return g


def canonical_graph(graph: KernelMap) -> dict[str, Any]:
    graph.validate()
    value = graph.to_dict()
    # Presentation/history are preserved by migration but not semantic identity.
    value.pop("legacy")
    value.pop("warnings")
    for key in ("claims", "contexts", "inferences", "evidence"):
        value[key].sort(key=lambda x: x["id"])
    for row in value["claims"]:
        row.pop("label")
    for row in value["inferences"]:
        for key in ("premises", "assumptions", "evidence"):
            row[key] = sorted(set(row[key]))
    value["relations"].sort(key=canonical_bytes)
    return value


def semantic_digest(graph: KernelMap) -> str:
    return digest("semantic-graph.v1", canonical_graph(graph))


@dataclass(frozen=True)
class Support:
    assumptions: tuple[str, ...] = ()
    foundations: tuple[str, ...] = ()
    inferences: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClosureResult:
    graph_digest: str
    policy: str
    policy_digest: str
    dimension: str
    contexts: tuple[str, ...]
    foundations: tuple[str, ...]
    closed: tuple[str, ...]
    open: tuple[str, ...]
    conditional: tuple[str, ...]
    contradictions: tuple[tuple[str, str], ...]
    justifications: Mapping[str, tuple[Support, ...]]
    unresolved_premises: Mapping[str, tuple[str, ...]]
    evidence_issues: Mapping[str, tuple[str, ...]]
    warnings: tuple[str, ...]
    truncated: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def closure(
    graph: KernelMap,
    *,
    policy: str = "deductive-strict-v1",
    foundations: Iterable[tuple[str, str]] = (),
    assumptions: Iterable[tuple[str, str]] = (),
    trusted_evidence: Iterable[str] = (),
) -> ClosureResult:
    """Least fixed point over ALL premises / ANY alternative.

    `trusted_evidence` is supplied by a trusted replay/review boundary, not graph
    flags. Passing attacker-controlled digests here is a caller trust error.
    """
    graph.validate()
    if policy not in POLICIES:
        raise ValueError("UNKNOWN_POLICY")
    p = POLICIES[policy]
    claims = {c.id: c for c in graph.claims}
    contexts = {c.id: c for c in graph.contexts}
    artifacts = {e.id: e for e in graph.evidence}
    trusted = set(trusted_evidence)
    seeds = sorted(set(foundations))
    assumed = sorted(set(assumptions))
    if assumed and not p.allow_assumptions:
        raise ValueError("POLICY_DISALLOWS_RESEARCH_ASSUMPTIONS")
    supports: dict[str, tuple[Support, ...]] = {c: () for c in claims}
    for is_assumed, entries in ((False, seeds), (True, assumed)):
        for context, claim in entries:
            c = claims.get(claim)
            if (
                not c
                or c.context != context
                or c.scope != "global"
                or c.status in {"GAP", "BLOCKED", "REJECTED"}
            ):
                raise ValueError("INVALID_FOUNDATION_OR_ASSUMPTION")
            token = context + ":" + claim
            s = Support(assumptions=(token,)) if is_assumed else Support(foundations=(token,))
            supports[claim] = tuple(
                sorted(set(supports[claim] + (s,)), key=lambda x: (x.assumptions, x.foundations))
            )

    eligible: dict[str, Inference] = {}
    eligible_evidence: dict[str, tuple[str, ...]] = {}
    issues: dict[str, tuple[str, ...]] = {}
    reverse: dict[str, list[str]] = defaultdict(list)
    for i in sorted(graph.inferences, key=lambda x: x.id):
        reasons: list[str] = []
        if i.status != "ACTIVE" or i.mode not in p.modes:
            reasons.append("INFERENCE_NOT_ACCEPTABLE_UNDER_POLICY")
        conclusion = claims[i.conclusion]
        if conclusion.status in {"GAP", "BLOCKED", "REJECTED"}:
            reasons.append("CONCLUSION_BLOCKED")
        if i.scope != conclusion.scope or any(claims[x].scope != i.scope for x in i.premises):
            reasons.append("UNVERIFIED_SCOPE_DISCHARGE")
        if i.assumptions and (
            not p.allow_assumptions or any((i.context, a) not in assumed for a in i.assumptions)
        ):
            reasons.append("UNACCEPTED_EXTRA_ASSUMPTION")
        valid_evidence: list[str] = []
        evidence_failures: set[str] = set()
        subject_digest = graph.inference_digest(i, claims=claims, contexts=contexts)
        for eid in i.evidence:
            e = artifacts.get(eid)
            if e is None:
                evidence_failures.add("MISSING_EVIDENCE")
                continue
            if (
                e.subject != i.id
                or e.subject_digest != subject_digest
                or e.context != i.context
                or e.definition_revision != contexts[i.context].definition_revision
                or e.policy_digest != p.digest
                or e.mode != i.mode
            ):
                evidence_failures.add("STALE_EVIDENCE_BINDING")
            if e.digest not in trusted:
                evidence_failures.add("UNTRUSTED_EVIDENCE")
            if e.outcome != "PASS":
                evidence_failures.add("INVALID_EVIDENCE_OUTCOME")
            if (
                e
                and e.digest in trusted
                and e.subject == i.id
                and e.subject_digest == subject_digest
                and e.context == i.context
                and e.definition_revision == contexts[i.context].definition_revision
                and e.policy_digest == p.digest
                and e.mode == i.mode
                and e.outcome == "PASS"
            ):
                valid_evidence.append(eid)
        if not valid_evidence:
            reasons.extend(sorted(evidence_failures or {"MISSING_EVIDENCE"}))
            reasons.append("MISSING_STALE_OR_UNTRUSTED_EVIDENCE")
        if reasons:
            issues[i.id] = tuple(reasons)
            continue
        eligible[i.id] = i
        eligible_evidence[i.id] = tuple(valid_evidence)
        for premise in set(i.premises):
            reverse[premise].append(i.id)

    pending = deque(sorted(eligible))
    queued = set(pending)
    truncated = False
    updates = 0
    while pending:
        iid = pending.popleft()
        queued.remove(iid)
        i = eligible[iid]
        choices = [supports[x] for x in sorted(set(i.premises))]
        if any(not choice for choice in choices):
            continue
        combinations = 1
        for choice in choices:
            combinations *= len(choice)
        if combinations > p.max_combinations:
            truncated = True
        candidates = list(supports[i.conclusion])
        for combination in islice(product(*choices), p.max_combinations):
            if any(iid in s.inferences for s in combination):
                continue

            def union(attr: str, entries: tuple[Support, ...] = combination) -> tuple[str, ...]:
                return tuple(sorted({x for s in entries for x in getattr(s, attr)}))

            candidates.append(
                Support(
                    tuple(
                        sorted(
                            set(union("assumptions")) | {i.context + ":" + a for a in i.assumptions}
                        )
                    ),
                    union("foundations"),
                    tuple(sorted(set(union("inferences")) | {iid})),
                    tuple(sorted(set(union("evidence")) | set(eligible_evidence[iid]))),
                )
            )
        # Antichain over assumptions and foundations; stable first witness for
        # identical support requirements. No union across OR alternatives.
        minimal: list[Support] = []
        for candidate in sorted(
            set(candidates),
            key=lambda s: (
                len(s.assumptions) + len(s.foundations),
                s.assumptions,
                s.foundations,
                s.inferences,
                s.evidence,
            ),
        ):
            if any(
                set(s.assumptions) <= set(candidate.assumptions)
                and set(s.foundations) <= set(candidate.foundations)
                for s in minimal
            ):
                continue
            minimal.append(candidate)
        if len(minimal) > p.max_alternatives:
            truncated = True
        result = tuple(
            sorted(minimal[: p.max_alternatives], key=lambda s: (s.assumptions, s.foundations))
        )
        if result != supports[i.conclusion]:
            supports[i.conclusion] = result
            updates += 1
            if updates >= p.max_updates:
                truncated = True
                break
            for dependent in reverse[i.conclusion]:
                if dependent not in queued:
                    pending.append(dependent)
                    queued.add(dependent)
    closed = tuple(sorted(c for c, ss in supports.items() if any(not s.assumptions for s in ss)))
    conditional = tuple(sorted(c for c, ss in supports.items() if ss and c not in closed))
    return ClosureResult(
        semantic_digest(graph),
        p.id,
        p.digest,
        p.dimension,
        tuple(sorted(contexts)),
        tuple(c + ":" + n for c, n in seeds),
        closed,
        tuple(sorted(set(claims) - set(closed) - set(conditional))),
        conditional,
        tuple(sorted((r.source, r.target) for r in graph.relations if r.kind == "CONTRADICTS")),
        {c: supports[c] for c in sorted(supports) if supports[c]},
        {
            i.id: tuple(sorted(x for x in i.premises if not supports[x]))
            for i in sorted(graph.inferences, key=lambda x: x.id)
        },
        issues,
        graph.warnings,
        truncated,
    )


def migrate(value: Mapping[str, Any]) -> KernelMap:
    if "$schema" in value or "schema_version" in value:
        return KernelMap.from_dict(value)
    from .model import EdgeKind, NodeKind, NodeStatus, ProofMap

    pm = ProofMap.from_dict(value)
    ctx = Context(
        "legacy",
        digest(
            "legacy-definitions.v1",
            sorted(
                (n.id, n.statement)
                for n in pm.nodes.values()
                if NodeKind(n.kind).value == "DEFINITION"
            ),
        ),
    )
    claims = tuple(
        Claim(
            n.id,
            n.statement or n.label,
            ctx.id,
            digest("legacy-claim.v1", n.to_dict()),
            NodeStatus(n.status).value
            if NodeStatus(n.status).value in STATES
            else "AUTHOR_ASSERTED",
            label=n.label,
        )
        for n in sorted(pm.nodes.values(), key=lambda n: n.id)
    )
    groups: dict[str, set[str]] = defaultdict(set)
    relations = []
    for edge in pm.edges:
        if EdgeKind(edge.kind).value in {"PROVES", "DEPENDS_ON", "DEFINES"}:
            groups[edge.target].add(edge.source)
        if edge.source != edge.target:
            relations.append(TypedRelation(edge.source, edge.target, EdgeKind(edge.kind).value))
    g = KernelMap(
        claims,
        (ctx,),
        tuple(
            Inference(
                "legacy-inference:" + target,
                target,
                tuple(sorted(premises)),
                ctx.id,
                status="REVIEW_REQUIRED",
            )
            for target, premises in sorted(groups.items())
        ),
        relations=tuple(relations),
        warnings=(
            "LEGACY_REVIEW_REQUIRED: proof-like incoming edges grouped conjunctively; no foundation or evidence accepted.",
            "Authored labels, geometry and reachability are not proof closure; original data retained in legacy.",
        ),
        legacy=dict(value),
    )
    g.validate()
    return g
