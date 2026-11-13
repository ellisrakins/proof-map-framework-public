"""Proof Map Boundary Analysis toolkit."""

from importlib import import_module as _import_module
from typing import TYPE_CHECKING as _TYPE_CHECKING
from typing import Any as _Any

if _TYPE_CHECKING:
    from .attempts import (
        AttemptOutcome,
        AttemptReceipt,
        FormalObligation,
        ProofAttempt,
        VerificationRecord,
        check_proof_attempt,
        parse_lean_axioms,
        render_verification_wrapper,
        validate_candidate_source,
    )
    from .conops import run_conops_validation
    from .current_physics import (
        build_current_physics_backbone_map,
        build_current_physics_source_registry,
    )
    from .current_validation import run_current_physics_backbone_validation
    from .hypothesis import (
        HypothesisCatalog,
        HypothesisEvaluation,
        HypothesisProposal,
        evaluate_hypothesis,
        rank_hypotheses,
        simulate_hypothesis,
        write_hypothesis_search,
    )
    from .lean_check import check_lean_file, check_lean_files, resolve_lean_executable
    from .metrics import analyze, identify_defects, metrics_over_epochs
    from .model import (
        Edge,
        EdgeKind,
        EdgeStatus,
        Epoch,
        Layer,
        Node,
        NodeKind,
        NodeStatus,
        ProofMap,
    )
    from .optimizer import rank_closure_candidates, simulate_closure
    from .physics_catalog import build_physics_theory_catalog, build_physics_theory_source_registry
    from .sources import Source, SourceRegistry, validate_source_coverage
    from .surface import build_surface_layout
    from .theories import (
        EvidenceStatus,
        TheoryBindingValidation,
        TheoryCatalog,
        TheoryCatalogValidation,
        TheoryKind,
        TheoryMaturity,
        TheoryProfile,
        TheoryRelation,
        TheoryRelationKind,
        ValidityRegime,
        build_theory_scaffold,
        render_theory_catalog_report,
        validate_theory_bindings,
        validate_theory_catalog,
        write_theory_catalog_report,
    )

_EXPORTS: dict[str, tuple[str, str]] = {
    "Edge": ("model", "Edge"),
    "EdgeKind": ("model", "EdgeKind"),
    "EdgeStatus": ("model", "EdgeStatus"),
    "Epoch": ("model", "Epoch"),
    "Layer": ("model", "Layer"),
    "Node": ("model", "Node"),
    "NodeKind": ("model", "NodeKind"),
    "NodeStatus": ("model", "NodeStatus"),
    "ProofMap": ("model", "ProofMap"),
    "analyze": ("metrics", "analyze"),
    "identify_defects": ("metrics", "identify_defects"),
    "metrics_over_epochs": ("metrics", "metrics_over_epochs"),
    "rank_closure_candidates": ("optimizer", "rank_closure_candidates"),
    "simulate_closure": ("optimizer", "simulate_closure"),
    "AttemptOutcome": ("attempts", "AttemptOutcome"),
    "AttemptReceipt": ("attempts", "AttemptReceipt"),
    "FormalObligation": ("attempts", "FormalObligation"),
    "ProofAttempt": ("attempts", "ProofAttempt"),
    "VerificationRecord": ("attempts", "VerificationRecord"),
    "check_proof_attempt": ("attempts", "check_proof_attempt"),
    "parse_lean_axioms": ("attempts", "parse_lean_axioms"),
    "render_verification_wrapper": ("attempts", "render_verification_wrapper"),
    "validate_candidate_source": ("attempts", "validate_candidate_source"),
    "build_surface_layout": ("surface", "build_surface_layout"),
    "check_lean_file": ("lean_check", "check_lean_file"),
    "check_lean_files": ("lean_check", "check_lean_files"),
    "resolve_lean_executable": ("lean_check", "resolve_lean_executable"),
    "run_conops_validation": ("conops", "run_conops_validation"),
    "build_current_physics_backbone_map": ("current_physics", "build_current_physics_backbone_map"),
    "build_current_physics_source_registry": (
        "current_physics",
        "build_current_physics_source_registry",
    ),
    "run_current_physics_backbone_validation": (
        "current_validation",
        "run_current_physics_backbone_validation",
    ),
    "Source": ("sources", "Source"),
    "SourceRegistry": ("sources", "SourceRegistry"),
    "validate_source_coverage": ("sources", "validate_source_coverage"),
    "HypothesisCatalog": ("hypothesis", "HypothesisCatalog"),
    "HypothesisEvaluation": ("hypothesis", "HypothesisEvaluation"),
    "HypothesisProposal": ("hypothesis", "HypothesisProposal"),
    "evaluate_hypothesis": ("hypothesis", "evaluate_hypothesis"),
    "rank_hypotheses": ("hypothesis", "rank_hypotheses"),
    "simulate_hypothesis": ("hypothesis", "simulate_hypothesis"),
    "write_hypothesis_search": ("hypothesis", "write_hypothesis_search"),
    "EvidenceStatus": ("theories", "EvidenceStatus"),
    "TheoryBindingValidation": ("theories", "TheoryBindingValidation"),
    "TheoryCatalog": ("theories", "TheoryCatalog"),
    "TheoryCatalogValidation": ("theories", "TheoryCatalogValidation"),
    "TheoryKind": ("theories", "TheoryKind"),
    "TheoryMaturity": ("theories", "TheoryMaturity"),
    "TheoryProfile": ("theories", "TheoryProfile"),
    "TheoryRelation": ("theories", "TheoryRelation"),
    "TheoryRelationKind": ("theories", "TheoryRelationKind"),
    "ValidityRegime": ("theories", "ValidityRegime"),
    "build_theory_scaffold": ("theories", "build_theory_scaffold"),
    "render_theory_catalog_report": ("theories", "render_theory_catalog_report"),
    "validate_theory_bindings": ("theories", "validate_theory_bindings"),
    "validate_theory_catalog": ("theories", "validate_theory_catalog"),
    "write_theory_catalog_report": ("theories", "write_theory_catalog_report"),
    "build_physics_theory_catalog": ("physics_catalog", "build_physics_theory_catalog"),
    "build_physics_theory_source_registry": (
        "physics_catalog",
        "build_physics_theory_source_registry",
    ),
}

# Reload preserves the module dictionary; refresh aliases on their next access.
for _export_name in _EXPORTS:
    globals().pop(_export_name, None)
del _export_name
_MODULE_NAMES = (
    "integrity",
    "lean_check",
    "model",
    "attempts",
    "examples",
    "lean_export",
    "kernel",
    "metrics",
    "paper_actions",
    "optimizer",
    "report",
    "surface",
    "surface_visualize",
    "visualize",
    "conops",
    "sources",
    "current_physics",
    "theories",
    "physics_catalog",
    "current_validation",
    "hypothesis",
)

__all__ = [
    "Edge",
    "EdgeKind",
    "EdgeStatus",
    "Epoch",
    "Layer",
    "Node",
    "NodeKind",
    "NodeStatus",
    "ProofMap",
    "analyze",
    "identify_defects",
    "metrics_over_epochs",
    "rank_closure_candidates",
    "simulate_closure",
    "AttemptOutcome",
    "AttemptReceipt",
    "FormalObligation",
    "ProofAttempt",
    "VerificationRecord",
    "check_proof_attempt",
    "parse_lean_axioms",
    "render_verification_wrapper",
    "validate_candidate_source",
    "build_surface_layout",
    "check_lean_file",
    "check_lean_files",
    "resolve_lean_executable",
    "run_conops_validation",
    "build_current_physics_backbone_map",
    "build_current_physics_source_registry",
    "run_current_physics_backbone_validation",
    "Source",
    "SourceRegistry",
    "validate_source_coverage",
    "HypothesisCatalog",
    "HypothesisEvaluation",
    "HypothesisProposal",
    "evaluate_hypothesis",
    "rank_hypotheses",
    "simulate_hypothesis",
    "write_hypothesis_search",
    "EvidenceStatus",
    "TheoryBindingValidation",
    "TheoryCatalog",
    "TheoryCatalogValidation",
    "TheoryKind",
    "TheoryMaturity",
    "TheoryProfile",
    "TheoryRelation",
    "TheoryRelationKind",
    "ValidityRegime",
    "build_theory_scaffold",
    "render_theory_catalog_report",
    "validate_theory_bindings",
    "validate_theory_catalog",
    "write_theory_catalog_report",
    "build_physics_theory_catalog",
    "build_physics_theory_source_registry",
]


def __getattr__(name: str) -> _Any:
    if name in _EXPORTS:
        module_name, symbol_name = _EXPORTS[name]
        value = getattr(_import_module("." + module_name, __name__), symbol_name)
    elif name in _MODULE_NAMES:
        value = _import_module("." + name, __name__)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_MODULE_NAMES))
