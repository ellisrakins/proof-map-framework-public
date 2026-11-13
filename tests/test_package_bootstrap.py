"""Public package objects keep their identities while bootstrap imports stay lazy."""

import json
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path

import pytest

# Fixed inventory from the original eager package, including its original __all__ order.
ORIGINAL_ALL = [
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
ORIGINAL_EXPORTS = {
    "AttemptOutcome": ["attempts", "AttemptOutcome"],
    "AttemptReceipt": ["attempts", "AttemptReceipt"],
    "FormalObligation": ["attempts", "FormalObligation"],
    "ProofAttempt": ["attempts", "ProofAttempt"],
    "VerificationRecord": ["attempts", "VerificationRecord"],
    "check_proof_attempt": ["attempts", "check_proof_attempt"],
    "parse_lean_axioms": ["attempts", "parse_lean_axioms"],
    "render_verification_wrapper": ["attempts", "render_verification_wrapper"],
    "validate_candidate_source": ["attempts", "validate_candidate_source"],
    "run_conops_validation": ["conops", "run_conops_validation"],
    "build_current_physics_backbone_map": ["current_physics", "build_current_physics_backbone_map"],
    "build_current_physics_source_registry": [
        "current_physics",
        "build_current_physics_source_registry",
    ],
    "run_current_physics_backbone_validation": [
        "current_validation",
        "run_current_physics_backbone_validation",
    ],
    "HypothesisCatalog": ["hypothesis", "HypothesisCatalog"],
    "HypothesisEvaluation": ["hypothesis", "HypothesisEvaluation"],
    "HypothesisProposal": ["hypothesis", "HypothesisProposal"],
    "evaluate_hypothesis": ["hypothesis", "evaluate_hypothesis"],
    "rank_hypotheses": ["hypothesis", "rank_hypotheses"],
    "simulate_hypothesis": ["hypothesis", "simulate_hypothesis"],
    "write_hypothesis_search": ["hypothesis", "write_hypothesis_search"],
    "check_lean_file": ["lean_check", "check_lean_file"],
    "check_lean_files": ["lean_check", "check_lean_files"],
    "resolve_lean_executable": ["lean_check", "resolve_lean_executable"],
    "analyze": ["metrics", "analyze"],
    "identify_defects": ["metrics", "identify_defects"],
    "metrics_over_epochs": ["metrics", "metrics_over_epochs"],
    "Edge": ["model", "Edge"],
    "EdgeKind": ["model", "EdgeKind"],
    "EdgeStatus": ["model", "EdgeStatus"],
    "Epoch": ["model", "Epoch"],
    "Layer": ["model", "Layer"],
    "Node": ["model", "Node"],
    "NodeKind": ["model", "NodeKind"],
    "NodeStatus": ["model", "NodeStatus"],
    "ProofMap": ["model", "ProofMap"],
    "rank_closure_candidates": ["optimizer", "rank_closure_candidates"],
    "simulate_closure": ["optimizer", "simulate_closure"],
    "build_physics_theory_catalog": ["physics_catalog", "build_physics_theory_catalog"],
    "build_physics_theory_source_registry": [
        "physics_catalog",
        "build_physics_theory_source_registry",
    ],
    "Source": ["sources", "Source"],
    "SourceRegistry": ["sources", "SourceRegistry"],
    "validate_source_coverage": ["sources", "validate_source_coverage"],
    "build_surface_layout": ["surface", "build_surface_layout"],
    "EvidenceStatus": ["theories", "EvidenceStatus"],
    "TheoryBindingValidation": ["theories", "TheoryBindingValidation"],
    "TheoryCatalog": ["theories", "TheoryCatalog"],
    "TheoryCatalogValidation": ["theories", "TheoryCatalogValidation"],
    "TheoryKind": ["theories", "TheoryKind"],
    "TheoryMaturity": ["theories", "TheoryMaturity"],
    "TheoryProfile": ["theories", "TheoryProfile"],
    "TheoryRelation": ["theories", "TheoryRelation"],
    "TheoryRelationKind": ["theories", "TheoryRelationKind"],
    "ValidityRegime": ["theories", "ValidityRegime"],
    "build_theory_scaffold": ["theories", "build_theory_scaffold"],
    "render_theory_catalog_report": ["theories", "render_theory_catalog_report"],
    "validate_theory_bindings": ["theories", "validate_theory_bindings"],
    "validate_theory_catalog": ["theories", "validate_theory_catalog"],
    "write_theory_catalog_report": ["theories", "write_theory_catalog_report"],
}
ORIGINAL_MODULES = [
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
]

CHILD = r"""
import importlib,json,sys
from pathlib import Path
request = json.loads(sys.argv[1])
assert sys.flags.isolated == 1
sys.path.insert(0, request['package_parent'])
import proofmap as package
assert Path(package.__file__).resolve() == Path(request['package_parent'])/'proofmap'/'__init__.py'
assert package.__all__ == request['all']
assert 'analyze' not in vars(package) and 'ProofMap' not in vars(package)
assert set(vars(package)).issubset(dir(package))
assert set(request['all']+request['modules']).issubset(dir(package))
mode = request['mode']
if mode == 'submodule-first':
    model = importlib.import_module('proofmap.model')
    sources = importlib.import_module('proofmap.paper_sources')
    assert package.Edge is model.Edge and package.model is model
    assert package.paper_sources is sources
elif mode == 'retry-and-reentrant':
    original = package._import_module
    attempted = []
    def failed(module, anchor):
        attempted.append((module,anchor))
        raise ImportError('DEPENDENCY_NOT_AVAILABLE')
    package._import_module = failed
    try:
        for attempt in range(2):
            try:
                value = package.analyze
            except ImportError as error:
                assert str(error) == 'DEPENDENCY_NOT_AVAILABLE'
            else:
                raise AssertionError('Dependency failure was hidden')
            assert 'analyze' not in vars(package)
    finally:
        package._import_module = original
    assert len(attempted) == 2
    nested = []
    def importing(module, anchor):
        if module == '.metrics':
            nested.append(package.Edge)
        return original(module, anchor)
    package._import_module = importing
    try:
        analyze = package.analyze
    finally:
        package._import_module = original
    assert analyze is importlib.import_module('proofmap.metrics').analyze
    assert nested == [importlib.import_module('proofmap.model').Edge]
    assert vars(package)['analyze'] is analyze and package.analyze is analyze
elif mode == 'reload':
    model = importlib.import_module('proofmap.model')
    original_edge = model.Edge
    assert package.Edge is original_edge
    marker = object()
    package.reload_compatibility_marker = marker
    replacement = object()
    try:
        model.Edge = replacement
        importlib.reload(package)
        assert 'Edge' not in vars(package)
        assert package.Edge is replacement
        assert vars(package)['Edge'] is replacement
        assert package.reload_compatibility_marker is marker
        assert 'reload_compatibility_marker' in dir(package)
        assert package.__all__ == request['all']
    finally:
        model.Edge = original_edge
        importlib.reload(package)
        del package.reload_compatibility_marker
    assert 'Edge' not in vars(package) and package.Edge is original_edge
for name in request['all']:
    module,symbol = request['mapping'][name]
    expected = getattr(importlib.import_module('proofmap.'+module),symbol)
    assert getattr(package,name) is expected
    assert getattr(package,name) is expected
for module in request['modules']:
    assert getattr(package,module) is importlib.import_module('proofmap.'+module)
namespace = {}
exec('from proofmap import *',namespace)
assert set(namespace)-{'__builtins__'} == set(request['all'])
assert all(namespace[name] is getattr(package,name) for name in request['all'])
package.compatibility_marker = object()
assert 'compatibility_marker' in dir(package)
del package.compatibility_marker
for attempt in range(2):
    try:
        value = package.absent_public_api_attribute
    except AttributeError:
        pass
    else:
        raise AssertionError('Unknown attribute did not raise AttributeError')
for name,module in tuple(sys.modules.items()):
    if name == 'proofmap' or name.startswith('proofmap.'):
        assert Path(module.__file__).resolve().is_relative_to(
            Path(request['package_parent'])/'proofmap')
print(json.dumps({'exports':len(request['all']),'modules':len(request['modules']),'mode':mode}))
"""


@pytest.mark.parametrize("mode", ["normal", "submodule-first", "retry-and-reentrant", "reload"])
def test_package_bootstrap_preserves_original_public_objects(mode):
    spec = find_spec("proofmap")
    assert spec is not None and spec.origin is not None
    package_parent = Path(spec.origin).resolve().parent.parent
    request = {
        "package_parent": str(package_parent),
        "all": ORIGINAL_ALL,
        "mapping": ORIGINAL_EXPORTS,
        "modules": ORIGINAL_MODULES,
        "mode": mode,
    }
    child = subprocess.run(
        [sys.executable, "-I", "-c", CHILD, json.dumps(request)],
        capture_output=True,
        text=True,
        check=False,
        timeout=45,
    )
    assert child.returncode == 0, child.stdout + child.stderr
    assert json.loads(child.stdout) == {"exports": 58, "modules": 21, "mode": mode}
