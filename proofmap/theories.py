"""Extensible theory profiles, relations, map bindings, and scaffolds."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Mapping

from .model import Edge, EdgeKind, EdgeStatus, Layer, Node, NodeKind, NodeStatus, ProofMap


class TheoryKind(str, Enum):
    THEORY = "THEORY"
    FRAMEWORK = "FRAMEWORK"
    MODEL = "MODEL"
    EFFECTIVE_THEORY = "EFFECTIVE_THEORY"
    RESEARCH_PROGRAM = "RESEARCH_PROGRAM"
    INTERPRETATION = "INTERPRETATION"


class TheoryMaturity(str, Enum):
    ESTABLISHED = "ESTABLISHED"
    EFFECTIVE = "EFFECTIVE"
    ACTIVE_RESEARCH = "ACTIVE_RESEARCH"
    SPECULATIVE = "SPECULATIVE"
    HISTORICAL = "HISTORICAL"


class EvidenceStatus(str, Enum):
    PRECISION_TESTED = "PRECISION_TESTED"
    EMPIRICALLY_SUPPORTED = "EMPIRICALLY_SUPPORTED"
    INDIRECTLY_SUPPORTED = "INDIRECTLY_SUPPORTED"
    CONSTRAINED = "CONSTRAINED"
    UNCONFIRMED = "UNCONFIRMED"
    DISFAVORED = "DISFAVORED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TheoryRelationKind(str, Enum):
    EXTENDS = "EXTENDS"
    REDUCES_TO = "REDUCES_TO"
    EFFECTIVE_LIMIT_OF = "EFFECTIVE_LIMIT_OF"
    DUAL_TO = "DUAL_TO"
    COMPATIBLE_WITH = "COMPATIBLE_WITH"
    ALTERNATIVE_TO = "ALTERNATIVE_TO"
    CONFLICTS_WITH = "CONFLICTS_WITH"
    USES = "USES"
    UNIFIES = "UNIFIES"


@dataclass(frozen=True)
class ValidityRegime:
    id: str
    description: str
    dimensions: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("Validity-regime id cannot be empty")
        if not self.description:
            raise ValueError(f"Validity regime {self.id} requires a description")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ValidityRegime":
        return cls(**dict(data))


@dataclass
class TheoryProfile:
    id: str
    name: str
    kind: TheoryKind | str
    maturity: TheoryMaturity | str
    evidence_status: EvidenceStatus | str
    family: str
    summary: str
    domains: list[str]
    foundations: list[str]
    mathematical_frameworks: list[str]
    validity_regimes: list[ValidityRegime | Mapping[str, Any]]
    key_results: list[str] = field(default_factory=list)
    open_questions: list[str] = field(default_factory=list)
    discriminating_tests: list[str] = field(default_factory=list)
    source_ids: list[str] = field(default_factory=list)
    last_verified: str = ""
    aliases: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.kind = TheoryKind(self.kind)
        self.maturity = TheoryMaturity(self.maturity)
        self.evidence_status = EvidenceStatus(self.evidence_status)
        self.validity_regimes = [
            regime if isinstance(regime, ValidityRegime) else ValidityRegime.from_dict(regime)
            for regime in self.validity_regimes
        ]
        if not self.id:
            raise ValueError("Theory-profile id cannot be empty")
        if not self.name:
            raise ValueError(f"Theory profile {self.id} requires a name")
        if not self.family:
            raise ValueError(f"Theory profile {self.id} requires a family")
        if not self.domains:
            raise ValueError(f"Theory profile {self.id} requires at least one domain")

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["kind"] = self.kind.value
        out["maturity"] = self.maturity.value
        out["evidence_status"] = self.evidence_status.value
        out["validity_regimes"] = [regime.to_dict() for regime in self.validity_regimes]
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TheoryProfile":
        return cls(**dict(data))


@dataclass
class TheoryRelation:
    source: str
    target: str
    kind: TheoryRelationKind | str
    confidence: float = 1.0
    notes: str = ""
    source_ids: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.kind = TheoryRelationKind(self.kind)
        if not self.source or not self.target:
            raise ValueError("Theory-relation source and target cannot be empty")
        if self.source == self.target:
            raise ValueError(f"Self theory relation is not allowed: {self.source}")
        if not 0 <= self.confidence <= 1:
            raise ValueError("Theory-relation confidence must be in [0, 1]")

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["kind"] = self.kind.value
        return out

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TheoryRelation":
        return cls(**dict(data))


@dataclass
class TheoryCatalog:
    title: str
    version: str
    scope: str
    profiles: dict[str, TheoryProfile] = field(default_factory=dict)
    relations: list[TheoryRelation] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def add_profile(self, profile: TheoryProfile) -> None:
        if profile.id in self.profiles:
            raise ValueError(f"Duplicate theory-profile id: {profile.id}")
        self.profiles[profile.id] = profile

    def add_relation(self, relation: TheoryRelation) -> None:
        self.relations.append(relation)

    def select(
        self,
        *,
        ids: Iterable[str] | None = None,
        family: str | None = None,
        maturity: TheoryMaturity | str | None = None,
        domain: str | None = None,
        kind: TheoryKind | str | None = None,
    ) -> list[TheoryProfile]:
        selected_ids = set(ids) if ids is not None else None
        maturity_value = TheoryMaturity(maturity) if maturity is not None else None
        kind_value = TheoryKind(kind) if kind is not None else None
        selected = []
        for profile in self.profiles.values():
            if selected_ids is not None and profile.id not in selected_ids:
                continue
            if family is not None and profile.family != family:
                continue
            if maturity_value is not None and profile.maturity != maturity_value:
                continue
            if domain is not None and domain not in profile.domains:
                continue
            if kind_value is not None and profile.kind != kind_value:
                continue
            selected.append(profile)
        return sorted(selected, key=lambda item: (item.family, item.name, item.id))

    def referenced_source_ids(self) -> set[str]:
        source_ids: set[str] = set()
        for profile in self.profiles.values():
            source_ids.update(profile.source_ids)
        for relation in self.relations:
            source_ids.update(relation.source_ids)
        return source_ids

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "version": self.version,
            "scope": self.scope,
            "metadata": self.metadata,
            "profiles": [
                profile.to_dict()
                for profile in sorted(self.profiles.values(), key=lambda item: item.id)
            ],
            "relations": [
                relation.to_dict()
                for relation in sorted(
                    self.relations,
                    key=lambda item: (item.source, item.target, item.kind.value),
                )
            ],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "TheoryCatalog":
        catalog = cls(
            title=str(data.get("title", "Untitled theory catalog")),
            version=str(data.get("version", "0")),
            scope=str(data.get("scope", "")),
            metadata=dict(data.get("metadata", {})),
        )
        for profile_data in data.get("profiles", []):
            catalog.add_profile(TheoryProfile.from_dict(profile_data))
        for relation_data in data.get("relations", []):
            catalog.add_relation(TheoryRelation.from_dict(relation_data))
        return catalog

    def to_json(self, path: str | Path | None = None, *, indent: int = 2) -> str:
        text = json.dumps(self.to_dict(), indent=indent, sort_keys=True)
        if path is not None:
            Path(path).write_text(text + "\n", encoding="utf-8")
        return text

    @classmethod
    def from_json(cls, path_or_text: str | Path) -> "TheoryCatalog":
        from .integrity import load_json

        return cls.from_dict(load_json(path_or_text))


@dataclass(frozen=True)
class TheoryCatalogValidation:
    errors: list[str]
    warnings: list[str]
    profile_count: int
    relation_count: int
    family_count: int
    domain_count: int
    maturity_counts: dict[str, int]

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["ok"] = self.ok
        return out


@dataclass(frozen=True)
class TheoryBindingValidation:
    errors: list[str]
    warnings: list[str]
    node_counts: dict[str, int]
    edge_counts: dict[str, int]
    unbound_node_count: int
    unbound_edge_count: int

    @property
    def ok(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out["ok"] = self.ok
        return out


def _hierarchy_cycles(catalog: TheoryCatalog) -> list[list[str]]:
    hierarchy_kinds = {
        TheoryRelationKind.EXTENDS,
        TheoryRelationKind.REDUCES_TO,
        TheoryRelationKind.EFFECTIVE_LIMIT_OF,
    }
    outgoing: dict[str, list[str]] = {profile_id: [] for profile_id in catalog.profiles}
    for relation in catalog.relations:
        if relation.kind in hierarchy_kinds and relation.source in outgoing:
            outgoing[relation.source].append(relation.target)

    color = {profile_id: 0 for profile_id in catalog.profiles}
    stack: list[str] = []
    cycles: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()

    def visit(profile_id: str) -> None:
        color[profile_id] = 1
        stack.append(profile_id)
        for target in outgoing.get(profile_id, []):
            if target not in color:
                continue
            if color[target] == 0:
                visit(target)
            elif color[target] == 1 and target in stack:
                cycle = stack[stack.index(target) :] + [target]
                key = tuple(sorted(set(cycle)))
                if key not in seen:
                    seen.add(key)
                    cycles.append(cycle)
        stack.pop()
        color[profile_id] = 2

    for profile_id in sorted(catalog.profiles):
        if color[profile_id] == 0:
            visit(profile_id)
    return cycles


def validate_theory_catalog(
    catalog: TheoryCatalog,
    source_registry: Any | None = None,
    *,
    require_sources: bool = False,
) -> TheoryCatalogValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if not catalog.profiles:
        errors.append("Theory catalog has no profiles")

    available_sources = set(source_registry.sources) if source_registry is not None else None
    for profile in catalog.profiles.values():
        if not profile.foundations:
            warnings.append(f"Theory profile has no declared foundations: {profile.id}")
        if not profile.mathematical_frameworks:
            warnings.append(f"Theory profile has no mathematical frameworks: {profile.id}")
        if not profile.validity_regimes:
            warnings.append(f"Theory profile has no validity regimes: {profile.id}")
        if not profile.last_verified:
            warnings.append(f"Theory profile has no last_verified date: {profile.id}")
        if require_sources and not profile.source_ids:
            errors.append(f"Theory profile has no source_ids: {profile.id}")
        if available_sources is not None:
            missing = sorted(set(profile.source_ids) - available_sources)
            if missing:
                errors.append(f"Missing sources for theory {profile.id}: {', '.join(missing)}")

    relation_keys: set[tuple[str, str, TheoryRelationKind]] = set()
    symmetric_pairs: dict[frozenset[str], set[TheoryRelationKind]] = {}
    symmetric_kinds = {
        TheoryRelationKind.DUAL_TO,
        TheoryRelationKind.COMPATIBLE_WITH,
        TheoryRelationKind.ALTERNATIVE_TO,
        TheoryRelationKind.CONFLICTS_WITH,
    }
    for relation in catalog.relations:
        key = (relation.source, relation.target, relation.kind)
        if key in relation_keys:
            errors.append(
                f"Duplicate theory relation: {relation.source} {relation.kind.value} {relation.target}"
            )
        relation_keys.add(key)
        if relation.source not in catalog.profiles:
            errors.append(f"Unknown relation source: {relation.source}")
        if relation.target not in catalog.profiles:
            errors.append(f"Unknown relation target: {relation.target}")
        if require_sources and not relation.source_ids:
            warnings.append(
                f"Theory relation has no source_ids: "
                f"{relation.source} {relation.kind.value} {relation.target}"
            )
        if available_sources is not None:
            missing = sorted(set(relation.source_ids) - available_sources)
            if missing:
                errors.append(
                    f"Missing sources for relation {relation.source}->{relation.target}: "
                    f"{', '.join(missing)}"
                )
        if relation.kind in symmetric_kinds:
            pair = frozenset((relation.source, relation.target))
            symmetric_pairs.setdefault(pair, set()).add(relation.kind)

    for pair, kinds in symmetric_pairs.items():
        if (
            TheoryRelationKind.COMPATIBLE_WITH in kinds
            and TheoryRelationKind.CONFLICTS_WITH in kinds
        ):
            errors.append(
                f"Theory pair is both compatible and conflicting: {', '.join(sorted(pair))}"
            )

    for cycle in _hierarchy_cycles(catalog):
        errors.append(f"Theory hierarchy cycle: {' -> '.join(cycle)}")

    families = {profile.family for profile in catalog.profiles.values()}
    domains = {domain for profile in catalog.profiles.values() for domain in profile.domains}
    maturity_counts = {
        maturity.value: sum(profile.maturity == maturity for profile in catalog.profiles.values())
        for maturity in TheoryMaturity
    }
    return TheoryCatalogValidation(
        errors=errors,
        warnings=warnings,
        profile_count=len(catalog.profiles),
        relation_count=len(catalog.relations),
        family_count=len(families),
        domain_count=len(domains),
        maturity_counts=maturity_counts,
    )


def validate_theory_bindings(
    proof_map: ProofMap,
    catalog: TheoryCatalog,
    *,
    require_any: bool = False,
) -> TheoryBindingValidation:
    errors: list[str] = []
    warnings: list[str] = []
    node_counts = {profile_id: 0 for profile_id in catalog.profiles}
    edge_counts = {profile_id: 0 for profile_id in catalog.profiles}
    unbound_nodes = 0
    unbound_edges = 0

    for node in proof_map.nodes.values():
        if not node.theory_ids:
            unbound_nodes += 1
        for profile_id in node.theory_ids:
            if profile_id not in catalog.profiles:
                errors.append(f"Node {node.id} references unknown theory: {profile_id}")
            else:
                node_counts[profile_id] += 1

    for edge in proof_map.edges:
        if not edge.theory_ids:
            unbound_edges += 1
        for profile_id in edge.theory_ids:
            if profile_id not in catalog.profiles:
                errors.append(
                    f"Edge {edge.source}->{edge.target} references unknown theory: {profile_id}"
                )
            else:
                edge_counts[profile_id] += 1

    used = {profile_id for profile_id, count in node_counts.items() if count}
    declared = set(proof_map.metadata.get("theory_profile_ids", []))
    missing_declarations = sorted(used - declared)
    if missing_declarations:
        warnings.append(
            "Map metadata does not declare bound theory profiles: "
            + ", ".join(missing_declarations)
        )
    unknown_declarations = sorted(declared - set(catalog.profiles))
    if unknown_declarations:
        errors.append("Map metadata declares unknown theories: " + ", ".join(unknown_declarations))
    if require_any and not used:
        errors.append("Proof map has no theory bindings")

    return TheoryBindingValidation(
        errors=errors,
        warnings=warnings,
        node_counts={key: value for key, value in node_counts.items() if value},
        edge_counts={key: value for key, value in edge_counts.items() if value},
        unbound_node_count=unbound_nodes,
        unbound_edge_count=unbound_edges,
    )


def build_theory_scaffold(catalog: TheoryCatalog, theory_id: str) -> ProofMap:
    if theory_id not in catalog.profiles:
        raise KeyError(f"Unknown theory profile: {theory_id}")
    profile = catalog.profiles[theory_id]
    pm = ProofMap(
        title=f"{profile.name} proof-map scaffold",
        description=(
            "Generated theory scaffold. Foundation and framework nodes are declared commitments; "
            "open questions and tests remain explicit boundary debt."
        ),
        metadata={
            "theory_profile_ids": [profile.id],
            "theory_catalog_version": catalog.version,
            "generated_from_theory_profile": True,
        },
    )

    foundation_ids: list[str] = []
    foundations = profile.foundations or [profile.summary]
    for index, statement in enumerate(foundations, start=1):
        node_id = f"core.{profile.id}.foundation_{index}"
        foundation_ids.append(node_id)
        pm.add_node(
            Node(
                id=node_id,
                label=f"Foundation {index}",
                kind=NodeKind.AXIOM,
                status=NodeStatus.CORE,
                layer=Layer.CORE,
                domain=profile.domains[0],
                statement=statement,
                uncertainty=0.05 if profile.maturity == TheoryMaturity.ESTABLISHED else 0.35,
                source_ids=list(profile.source_ids),
                evidence_class="theory_profile",
                last_verified=profile.last_verified,
                validity_regime="; ".join(
                    regime.description for regime in profile.validity_regimes
                ),
                theory_ids=[profile.id],
                formal_systems=list(profile.mathematical_frameworks),
                regime_dimensions={
                    regime.id: dict(regime.dimensions) for regime in profile.validity_regimes
                },
            )
        )

    model_status = NodeStatus.ASSUMPTION
    if profile.evidence_status == EvidenceStatus.PRECISION_TESTED:
        model_status = NodeStatus.EMPIRICAL
    elif profile.evidence_status == EvidenceStatus.EMPIRICALLY_SUPPORTED:
        model_status = NodeStatus.PROBABILISTIC
    elif profile.evidence_status in {
        EvidenceStatus.INDIRECTLY_SUPPORTED,
        EvidenceStatus.CONSTRAINED,
    }:
        model_status = NodeStatus.APPROXIMATION

    model_id = f"model.{profile.id}"
    pm.add_node(
        Node(
            id=model_id,
            label=profile.name,
            kind=NodeKind.MODEL,
            status=model_status,
            layer=Layer.INTERIOR,
            domain=profile.domains[0],
            explanatory_weight=5,
            proof_cost=max(1, len(profile.mathematical_frameworks)),
            uncertainty={
                EvidenceStatus.PRECISION_TESTED: 0.08,
                EvidenceStatus.EMPIRICALLY_SUPPORTED: 0.16,
                EvidenceStatus.INDIRECTLY_SUPPORTED: 0.35,
                EvidenceStatus.CONSTRAINED: 0.48,
                EvidenceStatus.UNCONFIRMED: 0.72,
                EvidenceStatus.DISFAVORED: 0.88,
                EvidenceStatus.NOT_APPLICABLE: 0.5,
            }[profile.evidence_status],
            statement=profile.summary,
            tags=list(profile.tags),
            source_ids=list(profile.source_ids),
            evidence_class="theory_profile",
            last_verified=profile.last_verified,
            validity_regime="; ".join(regime.description for regime in profile.validity_regimes),
            uncertainty_kind="theoretical",
            theory_ids=[profile.id],
            formal_systems=list(profile.mathematical_frameworks),
            regime_dimensions={
                regime.id: dict(regime.dimensions) for regime in profile.validity_regimes
            },
        )
    )
    for foundation_id in foundation_ids:
        pm.add_edge(
            Edge(
                foundation_id,
                model_id,
                kind=EdgeKind.DEFINES,
                status=EdgeStatus.ASSUMED,
                uncertainty=pm.nodes[model_id].uncertainty,
                source_ids=list(profile.source_ids),
                evidence_class="theory_profile",
                last_verified=profile.last_verified,
                theory_ids=[profile.id],
                formal_systems=list(profile.mathematical_frameworks),
            )
        )

    for index, result in enumerate(profile.key_results, start=1):
        result_id = f"result.{profile.id}.result_{index}"
        pm.add_node(
            Node(
                id=result_id,
                label=f"Cataloged result {index}",
                kind=NodeKind.THEOREM,
                status=NodeStatus.DERIVED,
                layer=Layer.INTERIOR,
                domain=profile.domains[0],
                uncertainty=pm.nodes[model_id].uncertainty,
                statement=result,
                notes="Cataloged result; derivation and evidence must be expanded in the proof map.",
                source_ids=list(profile.source_ids),
                evidence_class="theory_profile",
                last_verified=profile.last_verified,
                uncertainty_kind="theoretical",
                theory_ids=[profile.id],
                formal_systems=list(profile.mathematical_frameworks),
            )
        )
        pm.add_edge(
            Edge(
                model_id,
                result_id,
                kind=EdgeKind.PROVES,
                status=EdgeStatus.ACTIVE,
                uncertainty=pm.nodes[model_id].uncertainty,
                source_ids=list(profile.source_ids),
                evidence_class="theory_profile",
                last_verified=profile.last_verified,
                theory_ids=[profile.id],
                formal_systems=list(profile.mathematical_frameworks),
            )
        )

    for index, question in enumerate(profile.open_questions, start=1):
        gap_id = f"gap.{profile.id}.question_{index}"
        pm.add_node(
            Node(
                id=gap_id,
                label=f"Open question {index}",
                kind=NodeKind.GAP,
                status=NodeStatus.GAP,
                layer=Layer.BOUNDARY,
                domain=profile.domains[0],
                uncertainty=0.8,
                boundary_weight=3,
                statement=question,
                source_ids=list(profile.source_ids),
                evidence_class="theory_profile",
                last_verified=profile.last_verified,
                uncertainty_kind="theoretical",
                theory_ids=[profile.id],
            )
        )
        pm.add_edge(
            Edge(
                model_id,
                gap_id,
                kind=EdgeKind.BLOCKS,
                status=EdgeStatus.GAP,
                uncertainty=0.8,
                source_ids=list(profile.source_ids),
                evidence_class="theory_profile",
                last_verified=profile.last_verified,
                theory_ids=[profile.id],
            )
        )

    for index, test in enumerate(profile.discriminating_tests, start=1):
        test_id = f"boundary.{profile.id}.test_{index}"
        pm.add_node(
            Node(
                id=test_id,
                label=f"Discriminating test {index}",
                kind=NodeKind.PHENOMENON,
                status=NodeStatus.GAP,
                layer=Layer.BOUNDARY,
                domain=profile.domains[0],
                uncertainty=0.75,
                boundary_weight=3,
                statement=test,
                tags=["discriminating_test"],
                source_ids=list(profile.source_ids),
                evidence_class="theory_profile",
                last_verified=profile.last_verified,
                uncertainty_kind="empirical",
                theory_ids=[profile.id],
            )
        )
        pm.add_edge(
            Edge(
                model_id,
                test_id,
                kind=EdgeKind.EMPIRICALLY_CONSTRAINS,
                status=EdgeStatus.GAP,
                uncertainty=0.75,
                source_ids=list(profile.source_ids),
                evidence_class="theory_profile",
                last_verified=profile.last_verified,
                theory_ids=[profile.id],
            )
        )
    return pm


def render_theory_catalog_report(
    catalog: TheoryCatalog,
    validation: TheoryCatalogValidation | None = None,
) -> str:
    result = validation or validate_theory_catalog(catalog)
    lines = [
        f"# {catalog.title}",
        "",
        catalog.scope,
        "",
        "> This catalog is extensible and representative, not a claim that theory space is closed.",
        "",
        "## Coverage",
        "",
        f"- Profiles: {result.profile_count}",
        f"- Families: {result.family_count}",
        f"- Domains: {result.domain_count}",
        f"- Relations: {result.relation_count}",
        f"- Validation: {'passed' if result.ok else 'failed'}",
        "",
        "## Maturity",
        "",
        "| Maturity | Profiles |",
        "|---|---:|",
    ]
    for maturity in TheoryMaturity:
        lines.append(f"| `{maturity.value}` | {result.maturity_counts[maturity.value]} |")
    lines.extend(
        [
            "",
            "## Profiles",
            "",
            "| Theory | Kind | Maturity | Evidence | Family | Domains |",
            "|---|---|---|---|---|---|",
        ]
    )
    for profile in catalog.select():
        lines.append(
            f"| `{profile.id}` | {profile.kind.value} | {profile.maturity.value} | "
            f"{profile.evidence_status.value} | {profile.family} | {', '.join(profile.domains)} |"
        )
    if result.errors:
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in result.errors)
    if result.warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in result.warnings)
    return "\n".join(lines) + "\n"


def write_theory_catalog_report(
    catalog: TheoryCatalog,
    out_path: str | Path,
    validation: TheoryCatalogValidation | None = None,
) -> Path:
    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_theory_catalog_report(catalog, validation), encoding="utf-8")
    return path
