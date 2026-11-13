# Proof Map Boundary Analysis Toolkit

## Research campaign beta candidate

The **0.9.0b1** candidate adds a persistent local research workflow: automatic
collection intake, exact source-bound goals and immutable snapshots, plans from the
existing evidence planner, explicitly authorized tasks with durable leases and
budgets, isolated verification, human review packets and current-authority
assessment. Offline JSON/Markdown/HTML and qualified graph views expose supported
claims, unknowns, failed checks and pending reviews. Revision impact and validated
dossier export/restore retain history without importing authority.

See the [operating model and CLI walkthrough](docs/CONOPS_RESEARCH_CAMPAIGN.md),
[queue guarantees](docs/RESEARCH_CAMPAIGN_QUEUE.md),
[portable dossiers](docs/CAMPAIGN_DOSSIER.md), and
[implementation progress](docs/advancement/RESEARCH_CAMPAIGN_PROGRESS.md).
The additive [OP-01..10 contract](acceptance/research_campaign_conops_v1.json)
requires exact installed-package observations and the preserved 81-row alpha
qualification. `alpha-readiness`, `conops-readiness` and `ci-required` must pass for
release readiness. Local scenario success and the candidate version do not assert
hosted qualification, production authority, publication or scholarly acceptance.

```sh
proofmap campaign init --name identities --objective "Review selected identities" --out .work/campaign.json
proofmap campaign ingest CAMPAIGN tests/fixtures/campaign/operational
proofmap campaign plan CAMPAIGN --formal-scope supported --out .work/plan.json
proofmap campaign report CAMPAIGN --out .work/campaign-report
proofmap validate-research-conops --profile offline --out .work/conops-offline
```

## Preserved bounded Paper CI Alpha baseline

The preserved alpha implementation ingests local TeX projects and text-bearing PDFs into an
immutable, source-anchored review bundle. It records lexical bindings, bounded
mathematical contexts, local citations and explicit or ambiguous proof links;
supports optional model decomposition with replay; and generates restricted
integer-polynomial obligations, including an explicit linear equality antecedent.
Formal execution, authenticated evidence, independent fidelity review and policy
acceptance remain separate steps.

Offline review includes list/inspect/query commands, attributed interpretation
overrides, linked JSON/Markdown/HTML/SARIF reports and planning-only evidence
actions. Overrides preserve raw sources and model outputs and recompute derived
views. Revision reuse checks dependency/context identities and reauthenticates
historical execution; it never carries an old acceptance verdict into a new run.

The qualified baseline was packaged as **0.8.0a1**. The preserved
[acceptance contract](docs/ALPHA_ACCEPTANCE.md) and
[requirement/evidence ledger](acceptance/paper_ci_alpha.json) govern readiness.
Each candidate's `alpha-acceptance.json` records its exact source/package identities
and qualifying evidence. Release readiness requires all mandatory profiles and
passing `alpha-readiness` and `ci-required` for that candidate; a version number or
focused test total is insufficient. Package-index publication, production authority
and scholarly acceptance are separate.

```sh
proofmap paper ci paper.tex --extractor none --out outputs/review --store .paper-store
proofmap paper list --store .paper-store
proofmap paper inspect RUN_ID --view review --store .paper-store
proofmap paper query --paper PAPER_ID --store .paper-store
proofmap paper report outputs/review --out outputs/report --store .paper-store
```

See [paper CI and offline review](docs/PAPER_CI.md),
[source scopes](docs/PAPER_SOURCE_SCOPES.md),
[formal grammar](docs/PAPER_FORMAL_PROFILE.md), and
[authenticated evidence](docs/PAPER_EVIDENCE.md).

## Completed paper-to-evidence milestone

Supported integer-polynomial manuscripts now produce source-anchored formal
obligations automatically. The workflow connects bounded extraction, isolated
Lean/Std execution, scoped execution authentication, separate fidelity reviews,
immutable audit records and same-revision resume. Missing formal infrastructure
is reported explicitly. See the [executable workflow](docs/PAPER_EVIDENCE.md),
[supported grammar](docs/PAPER_FORMAL_PROFILE.md), and
[increment evidence and limitations](docs/advancement/PAPER_EVIDENCE_INCREMENT.md).

Historical integration tests checked isolated Lean execution and acceptance after two
fidelity reviews under ephemeral test authority. These results apply only to the
original builds. Re-run the gates for this source distribution.

## Trusted-kernel and paper-CI development

The inherited baseline provides policy-qualified AND/OR closure, hardened receipt
loading and rendering, DSSE content authentication, and an offline manuscript
review/indexing pipeline. The dated
[implementation report](docs/advancement/IMPLEMENTATION_REPORT.md) preserves its
historical evidence; [current status](REPO_STATUS.md) describes this candidate.

```sh
python -m pip install -e '.[paper,trust,test,dev]'
proofmap paper ci tests/fixtures/papers/train/basic.tex --extractor none --out outputs/paper_review --store .paper-store
proofmap closure examples/minimal_conops.json --policy deductive-strict-v1
```

The paper command writes a source browser, independent outcome dimensions and
an indexed immutable run. Exit 0 means workflow conformance, **not proof**.
Legacy PROVED/CORE labels are authored metadata, not accepted evidence; legacy
maps now have zero accepted closure unless explicitly justified under policy.
Graph reachability and geometric scores remain visualization/planning heuristics.

Read [kernel/migration](docs/TRUSTED_KERNEL.md), [paper CI](docs/PAPER_CI.md),
[receipt trust/replay](docs/RECEIPT_TRUST.md), and [CI limitations](docs/CI.md).

This is a runnable prototype for the framework developed in the conversation:

> Treat a theory as a typed proof geometry. The core contains primitive laws or axioms. The interior contains definitions, lemmas, bridge principles, limits, effective theories, and derived consequences. The boundary is where the formalism touches phenomena, experiments, approximations, uncertainty, and other theory charts. Defects are proof gaps, seams, unexplained constants, cavities, or unresolved boundary conditions.

The toolkit does not claim to prove physics. It gives a concrete software substrate for identifying and ranking the places where a proofed theory stops being closed.

## What it contains

```text
proofmap/model.py              typed graph model: nodes, edges, epochs, JSON
proofmap/metrics.py            volume, surface area, roundness, density, closure, thickness, defects
proofmap/report.py             markdown reports and CSV ledgers
proofmap/visualize.py          SVG radial proof-sphere renderer
proofmap/surface.py            spherical proof-surface layout model
proofmap/surface_visualize.py  static SVG atlas + standalone interactive HTML surface explorer
proofmap/examples.py           strong–weak interface and dynamic cosmology seed maps
proofmap/lean_export.py        Lean-oriented proof-obligation scaffold
proofmap/lean_check.py         Lean compiler checks for generated scaffold files
proofmap/attempts.py           verifier-gated AI/human proof attempts and immutable receipts
proofmap/conops.py             minimal end-to-end CONOPS validation runner
proofmap/current_physics.py    source-backed current physics backbone map
proofmap/current_validation.py validation runner for the current physics backbone
proofmap/sources.py            source registry and source coverage checks
proofmap/hypothesis.py         conditional candidate-mechanism search and ranking
proofmap/theories.py           extensible theory profiles, relations, bindings, and scaffolds
proofmap/physics_catalog.py    bundled standard/emerging physics support matrix
proofmap/cli.py                command-line entry point
lean-toolchain                 pinned Lean 4 toolchain for scaffold verification
run_demo.py                    one-command generation of all example artifacts
tests/                         smoke tests for model, metrics, and surface visualization
```

## Setup

Use Python 3.10 or newer. To install the toolkit and the full development/test dependencies:

```bash
python -m pip install -e ".[test,paper,trust,dev]" types-jsonschema
```

This also installs the `proofmap` command-line entry point.
For the lightweight core alone, use `python -m pip install -e .`; manuscript,
signature and development dependencies are optional extras.

Lean scaffold checking uses Lean 4 through `elan`, Lean's toolchain manager. This repository pins the tested toolchain in `lean-toolchain`, so running Lean from the repository root will use that version:

```bash
lean --version
```

## Concepts represented in software

| Concept | Software representation |
|---|---|
| Authored core axioms / primitive laws | `Node(layer="CORE", status="CORE")`; no automatic trust |
| Explanatory volume | Weighted reachable interior/boundary claims discounted by uncertainty/status |
| Proof boundary | `Node(layer="BOUNDARY")`, especially phenomena, observations, interfaces, uncertainty nodes |
| Surface area | Weighted boundary complexity, assumptions, empirical patches, interface uncertainty |
| Roundness | Uniformity of derivational distance from core to boundary, multiplied by closure ratio |
| Density | Explanatory volume per proof cost |
| Uncertainty thickness | Weighted boundary uncertainty plus seam uncertainty |
| Holes / cavities | Boundary/exterior nodes not reachable from the core or still gaplike |
| Seams / creases | Cross-domain bridge/interface/approximation edges with uncertainty or weak status |
| Dynamic surface | `Epoch` objects and node active intervals, analyzed by time slice |
| Theory chart | `TheoryProfile` plus `theory_ids` memberships on nodes and edges |
| Validity regime | Open `regime_dimensions` metadata for energy, length, temperature, curvature, and domain-specific scales |
| Theory relation | Typed `EXTENDS`, `REDUCES_TO`, `DUAL_TO`, `ALTERNATIVE_TO`, `CONFLICTS_WITH`, and related links |

## Run

From this folder:

```bash
python run_demo.py
```

or directly:

```bash
python -m proofmap.cli demo --out .
python -m proofmap.cli analyze examples/strong_weak_interface.json
python -m proofmap.cli report examples/dynamic_cosmology.json --out outputs
```

After editable install, the same commands are available as:

```bash
proofmap demo --out .
proofmap analyze examples/strong_weak_interface.json
proofmap report examples/dynamic_cosmology.json --out outputs
proofmap lean-check outputs/*_LeanSketch.lean
proofmap attempt-check examples/attempts/nat_reflexivity_map.json examples/attempts/nat_reflexivity_obligation.json examples/attempts/nat_reflexivity_candidate.lean --producer example-human --out outputs/attempts/nat_reflexivity_receipt.json
proofmap validate-conops --out outputs/conops_validation --require-lean
proofmap validate-current-physics --out outputs/current_physics_backbone --require-lean
proofmap hypothesis-search examples/minimal_conops.json examples/hypotheses/minimal_conops_hypotheses.json --out outputs/hypothesis_search
proofmap theory-validate examples/theories/physics_theory_catalog.json --sources examples/sources/physics_theory_sources.json --map examples/current_physics_backbone.json --require-sources --require-bindings
proofmap theory-list examples/theories/physics_theory_catalog.json --family quantum_gravity
proofmap theory-scaffold examples/theories/physics_theory_catalog.json loop_quantum_gravity --out outputs/theory_scaffolds/loop_quantum_gravity.json
proofmap theory-slice examples/current_physics_backbone.json standard_model --out outputs/theory_slices/standard_model.json --exclude-shared
```

Generated artifacts are placed under `examples/` and `outputs/`.

## Main outputs

After running the demo, inspect:

```text
outputs/strong_weak_interface_report.md
outputs/strong_weak_interface_boundary_ledger.csv
outputs/strong_weak_interface_defects.csv
outputs/strong_weak_interface_metrics.json
outputs/strong_weak_interface_sphere.svg
outputs/strong_weak_interface_surface_atlas.svg
outputs/strong_weak_interface_surface_explorer.html
outputs/strong_weak_interface_surface_points.csv
outputs/strong_weak_interface_surface_layout.json
outputs/strong_weak_interface_LeanSketch.lean

outputs/dynamic_cosmology_report.md
outputs/dynamic_cosmology_boundary_ledger.csv
outputs/dynamic_cosmology_defects.csv
outputs/dynamic_cosmology_metrics.json
outputs/dynamic_cosmology_dynamic_metrics.csv
outputs/dynamic_cosmology_sphere.svg
outputs/dynamic_cosmology_surface_atlas.svg
outputs/dynamic_cosmology_surface_explorer.html
outputs/dynamic_cosmology_surface_points.csv
outputs/dynamic_cosmology_surface_layout.json
outputs/dynamic_cosmology_LeanSketch.lean
```


## Proof surface visualization

The toolkit now has a surface visualization layer. It turns a proof map into spherical coordinates:

```text
longitude = domain / local theory chart
latitude  = cosmic time if epochs exist, otherwise proof distance from the core
radius    = proof layer: core, interior, boundary, exterior
halo      = uncertainty thickness / proof debt
```

Generate surface assets directly:

```bash
python -m proofmap.cli surface examples/dynamic_cosmology.json --out outputs
```

The main outputs are a static SVG atlas, a standalone interactive HTML globe, a CSV point ledger, and a serialized JSON layout. See `docs/PROOF_SURFACE_VISUALIZATION.md` for details.

## Minimal CONOPS validation

Run a compact end-to-end validation that generates a five-node proof map, detects one intentional gap, writes all report/visualization/Lean artifacts, and records a machine-readable summary:

```bash
python -m proofmap.cli validate-conops --out outputs/conops_validation --require-lean
```

The expected defect is `boundary.drag_residual`. The validation summary is written to `outputs/conops_validation/minimal_conops_validation_summary.json`. See `docs/CONOPS_VALIDATION.md`.

## Physics integration plan

The next implementation stage is a source-backed integration of the current operational state of physics. See `docs/PHYSICS_INTEGRATION_PLAN.md` for the staged plan covering the physics backbone, Standard Model, QCD/nuclear, gravity/cosmology, dark sector, source registry, validation profiles, and release milestones.

The first execution slice is implemented as `examples/current_physics_backbone.json` with sources in `examples/sources/current_physics_sources.json`. See `docs/CURRENT_PHYSICS_BACKBONE.md`.

## Platform evaluation

The construct is strongest as an explicit epistemic graph: it keeps laws, derivations, measurements, approximations, sources, and open defects from being silently conflated. That is useful for auditing a theory, locating expensive interfaces, and deciding what work would have the highest closure value.

Its geometry scores are planning heuristics, not physical observables or Bayesian evidence. Lean currently checks generated scaffold syntax, not the truth of the mapped physics. The platform should therefore be described as a theory-audit, hypothesis-triage, and experiment-planning tool rather than an autonomous solver.

## Verifier-gated AI proof attempts

The framework now has a model-agnostic handoff from proof search to formal verification. A formal obligation binds one map node to an exact Lean statement, imports, pinned Lean release, and permitted axioms. An AI or human supplies only the proof term. `attempt-check` rejects placeholders, builds the theorem header itself, runs Lean, audits transitive axioms, and writes an immutable hash-bound receipt with model/run provenance, diagnostics, duration, and cost metadata.

```bash
proofmap attempt-check \
  examples/attempts/nat_reflexivity_map.json \
  examples/attempts/nat_reflexivity_obligation.json \
  examples/attempts/nat_reflexivity_candidate.lean \
  --producer example-human \
  --out outputs/attempts/nat_reflexivity_receipt.json
```

The proof map is not mutated. A verified receipt establishes the encoded Lean statement only; statement fidelity, novelty, significance, citation support, and empirical relevance remain separate review gates. See `docs/AI_PROOF_ATTEMPTS.md`.

## Verified research case study

`research/agoh_2026/` applies those gates to a live mathematical claim. It
disproves the final conjecture in Takashi Agoh's 2026 INTEGERS paper with the
repeated-root counterexample `f(t)=(t-2)^2`, proves a stronger universal
finite-difference theorem, and keeps the source reading, exact arithmetic,
Lean-checked algebra, and still-unconfirmed scholarly priority as distinct
proof-map nodes. See `research/agoh_2026/README.md` for the result and its
verification boundary.

## Conditional hypothesis search

The first solver-oriented layer compares explicit candidate mechanisms for a gap. Each proposal declares inputs, assumptions, predictions, complexity, falsifiability, prior plausibility, and the conditional closure it claims. The engine simulates that closure and ranks candidates by structural value, testability, plausibility, and complexity cost.

```bash
python -m proofmap.cli hypothesis-search \
  examples/minimal_conops.json \
  examples/hypotheses/minimal_conops_hypotheses.json \
  --out outputs/hypothesis_search \
  --basename minimal_conops
```

The output is a value-of-information ranking, not evidence that the top candidate is true. See `docs/HYPOTHESIS_SEARCH.md`.

## Standard and emerging theories

Theory support is now data-driven. A `TheoryCatalog` records theory identity, kind, maturity, evidence status, foundations, mathematical frameworks, validity regimes, results, open questions, discriminating tests, provenance, and typed relations to other theories.

Proof-map nodes and edges can belong to multiple theory charts through `theory_ids`. This lets the same observation, bridge, or open gap participate in the Standard Model, Lambda-CDM, effective theories, or competing quantum-gravity programs without duplicating the claim.

The bundled catalog contains 38 representative profiles across established, effective, active-research, and speculative categories. It is intentionally extensible rather than advertised as an exhaustive or authoritative list. See `docs/THEORY_CATALOG.md`.

## Emerging-theory proof of concept

The Loop Quantum Gravity proof of concept validates the catalog, generates a five-node theory scaffold, detects two explicit closure gaps, writes the complete report and proof-surface bundle, and compiles the generated Lean obligation ledger.

```bash
proofmap theory-scaffold examples/theories/physics_theory_catalog.json loop_quantum_gravity --out outputs/poc/loop_quantum_gravity/lqg_poc.json
proofmap report outputs/poc/loop_quantum_gravity/lqg_poc.json --out outputs/poc/loop_quantum_gravity --basename lqg_poc
proofmap lean-check outputs/poc/loop_quantum_gravity/lqg_poc_LeanSketch.lean
```

The resulting closure ratio is zero by design: the framework keeps incomplete dynamics and observational discrimination as gaps instead of treating profile metadata as proof. See `docs/PROOF_OF_CONCEPT.md`.

## Lean scaffold checking

The Lean export is still a proof-engineering scaffold, not a formalization of the physics. It is now generated as Lean 4 code that should compile as an abstract obligation ledger:

```bash
python -m proofmap.cli lean-check outputs/strong_weak_interface_LeanSketch.lean
python -m proofmap.cli lean-check outputs/*_LeanSketch.lean
```

If `lean` is not on PATH, set `PROOFMAP_LEAN` to the executable path or pass `--lean`:

```bash
python -m proofmap.cli lean-check outputs/*_LeanSketch.lean --lean "$HOME/.elan/bin/lean"
```

## Test

```bash
python -m pytest -q
```

## How to extend it

1. Create a new `ProofMap`.
2. Add core nodes for primitive assumptions or laws.
3. Add interior nodes for definitions, models, bridge principles, and derived laws.
4. Add boundary nodes for observations, interfaces, experiments, uncertainty, empirical constants, and gaps.
5. Add edges from source/explanation to target/dependent claim.
6. Run `analyze`, inspect the defect ledger, then decide the closure path for each defect.

For a new theory, first add a `TheoryProfile` to a catalog and run `theory-scaffold`. The generated map turns declared foundations into core nodes and keeps open questions and discriminating tests as boundary gaps.

A new node can be added like this:

```python
from proofmap import ProofMap, Node, Edge, NodeKind, NodeStatus, Layer

pm = ProofMap("My Theory")
pm.add_node(Node(
    id="core.law",
    label="Primitive law",
    kind=NodeKind.PRIMITIVE_LAW,
    status=NodeStatus.CORE,
    layer=Layer.CORE,
))
pm.add_node(Node(
    id="phenomenon.target",
    label="Target phenomenon",
    kind=NodeKind.PHENOMENON,
    status=NodeStatus.GAP,
    layer=Layer.BOUNDARY,
    uncertainty=0.7,
    boundary_weight=3,
))
pm.add_edge(Edge("core.law", "phenomenon.target"))
```

## Design limitations

- Metrics are heuristic diagnostics, not universal truth measures.
- A high score means the map is internally well-classified, not that the underlying physics is correct.
- Hypothesis rankings are conditional value-of-information estimates, not posterior probabilities or discoveries.
- Theory maturity and evidence labels are structured expert metadata, not automated scientific judgments.
- The bundled theory catalog is representative and extensible, not exhaustive.
- The Lean export is checked for Lean syntax, but its placeholder axioms are not checked theorem proofs.
- A verified proof-attempt receipt checks the exact Lean obligation, but does not establish that the encoding matches the intended natural-language problem or that the result is novel.
- Verified Attempt v1 records the Lean release but does not yet content-hash every imported package or project dependency.
- Candidate Lean artifacts are trusted local inputs; `attempt-check` is a proof-integrity gate, not a hostile-code sandbox.
- Empirical and approximation closures should be treated separately from mathematical proof closure.
