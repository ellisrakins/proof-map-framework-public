# Physics Integration Plan

Snapshot date: 2026-06-05

This plan describes how to integrate the current operational state of physics into the Proof Map Boundary Analysis framework. The goal is not to encode "all physics" at once. The goal is to build a versioned, source-backed graph that separates established law kernels, effective theories, empirical anchors, approximation seams, and open boundary debt.

## 1. Integration Objective

Build a source-backed `current_physics` proof-map family that answers four questions:

1. What are the currently accepted core law kernels and local theory charts?
2. Which phenomena are derivable, computed, empirically calibrated, approximate, or still open?
3. Where do the main seams sit between domains: quantum field theory, general relativity, thermodynamics, cosmology, nuclear physics, condensed matter, and measurement?
4. Which open problems most increase surface area or uncertainty thickness?

The first successful release should produce:

```text
examples/current_physics_backbone.json
examples/current_physics_standard_model.json
examples/current_physics_gravity_cosmology.json
examples/current_physics_dark_sector.json
outputs/current_physics_*/...
```

Each map should pass:

```text
python -m pytest -q
proofmap validate-conops --require-lean
proofmap lean-check outputs/current_physics_*/*_LeanSketch.lean
```

## 2. Source Baseline

Use a source registry instead of hard-coding claims without provenance. Each imported claim should record source URL, source type, date checked, and whether it is a review, official result, dataset, or theory paper.

Initial source registry:

| Domain | Baseline source | Integration use |
|---|---|---|
| Particle data and reviews | [Particle Data Group Review of Particle Physics 2024](https://pdg.lbl.gov/2024/index.html) | Standard Model parameters, particle listings, reviews, constants, search limits |
| Neutrino sector | [PDG 2025 Neutrino Masses, Mixing, and Oscillations](https://pdg.lbl.gov/2025/reviews/rpp2025-rev-neutrino-mixing.pdf) | PMNS mixing, oscillation evidence, mass-mechanism gap |
| Standard Model/Higgs status | [CERN Standard Model](https://home.cern/science/physics/standard-model/) and [CERN Higgs ten-year review](https://www.home.cern/news/press-release/physics/higgs-boson-ten-years-after-its-discovery) | SM completeness limits, Higgs confirmation, missing pieces |
| Precision frontier | [DOE/Fermilab Muon g-2 final result](https://www.energy.gov/science/articles/muon-g-2-announces-most-precise-measurement-magnetic-anomaly-muon) | Precision test node, theory-baseline seam |
| CMB/LambdaCDM | [Planck 2018 cosmological parameters](https://arxiv.org/abs/1807.06209) | Base LambdaCDM core, CMB empirical anchor, cosmological parameter constraints |
| BAO/dark energy | [DESI DR2 BAO results guide](https://www.desi.lbl.gov/2025/03/19/desi-dr2-results-march-19-guide/) | Expansion-history boundary, dynamic dark-energy tension |
| Gravitational waves | [LVK GWTC-5.0/O4b catalog](https://ligo.org/detections/o4b-catalog/) | GR strong-field empirical anchors and population constraints |
| Direct neutrino mass | [KATRIN latest results](https://www.katrin.kit.edu/1271.php) | Absolute neutrino-mass boundary |
| Direct dark matter searches | [LZ experiment status/results](https://lz.lbl.gov/) | WIMP-search constraints and dark-matter identity gap |

Policy:

- Prefer PDG, collaboration papers, experiment pages, and official datasets over secondary summaries.
- Treat conference talks and press pages as pointers, not final proof anchors, unless no paper/dataset exists yet.
- Re-check time-sensitive experimental claims before each tagged release.

## 3. Graph Architecture

### Map Family

Use multiple connected maps instead of one oversized graph.

```text
current_physics_backbone
  core law kernels and shared mathematical structures

current_physics_standard_model
  QFT, gauge sectors, Higgs, flavor, neutrinos, precision tests

current_physics_qcd_nuclear
  confinement, hadrons, lattice, EFT, nuclear structure

current_physics_gravity_cosmology
  GR, black holes, gravitational waves, FLRW, CMB, BAO, structure

current_physics_dark_sector
  dark matter, dark energy, modified gravity, direct/indirect/collider constraints

current_physics_emergence
  thermodynamics, condensed matter, chemistry, complex systems, measurement
```

The backbone map should stay small enough to inspect manually. Domain maps can be detailed and cross-linked by shared node IDs.

### Layer Conventions

| Layer | Physics meaning |
|---|---|
| `CORE` | accepted law kernels or formal postulates inside a domain |
| `INTERIOR` | derived structures, effective theories, computational machinery, bridge principles |
| `BOUNDARY` | observations, precision measurements, experiments, empirical constants, approximation limits |
| `EXTERIOR` | speculative models, beyond-current-framework hypotheses, unresolved replacement candidates |

### Status Conventions

| Status | Use in physics maps |
|---|---|
| `CORE` | core theory accepted for a chart, not absolute final truth |
| `PROVED` | mathematically/formally proved inside a stated framework |
| `DERIVED` | standard derivation accepted in the physics literature |
| `COMPUTED` | numerical/lattice/simulation result with quantified limits |
| `EMPIRICAL` | measured or fitted input |
| `PROBABILISTIC` | statistical law, stochastic effective model, likelihood result |
| `ASSUMPTION` | explicit auxiliary assumption |
| `APPROXIMATION` | EFT, perturbation, closure, coarse-graining, idealization |
| `GAP` | recognized open problem or unclosed explanation |
| `EXTERNAL` | hypothesis outside the accepted local chart |

Do not use `CORE` to mean "true in nature." Use it to mean "core for this chart."

## 4. Schema and Code Extensions

Before importing large physics maps, add these optional fields to `Node` and `Edge`:

```text
source_ids: list[str]
evidence_class: review | collaboration_result | dataset | derivation | simulation | textbook | hypothesis
last_verified: ISO date
validity_regime: energy/time/curvature/density/temperature bounds
uncertainty_kind: empirical | theoretical | computational | approximation | semantic | logical
formalization_status: none | scaffold | partial | checked
```

Add a source registry artifact:

```text
schema/source.schema.json
examples/sources/current_physics_sources.json
proofmap/sources.py
```

Acceptance criteria:

- Every nontrivial node in `current_physics_*` has at least one `source_id`.
- Boundary nodes distinguish measurement uncertainty from approximation uncertainty.
- Effective theories declare a validity regime.

## 5. Domain Integration Plan

### Phase A: Accepted Backbone

Create `examples/current_physics_backbone.json` with about 40 to 70 nodes.

Core nodes:

```text
core.quantum_mechanics
core.special_relativity
core.quantum_field_theory
core.standard_model_gauge_structure
core.general_relativity
core.statistical_mechanics
core.measurement_statistics
```

Boundary/gap nodes:

```text
gap.quantum_gravity
gap.dark_matter_identity
gap.dark_energy_microphysics
gap.baryon_asymmetry
gap.neutrino_mass_mechanism
gap.hierarchy_naturalness
gap.confinement_mass_gap
gap.initial_conditions_inflation
gap.measurement_problem
```

Validation target:

- The top defects should be the known open frontiers above.
- No map should imply Standard Model plus GR is globally closed.

### Phase B: Standard Model Map

Create a Standard Model map with these domains:

```text
qft
gauge_symmetry
qcd
electroweak
higgs
flavor
neutrino
precision_tests
collider_constraints
```

Key seams:

- Higgs Yukawa structure and unexplained fermion masses.
- CKM/PMNS empirical parameters.
- Strong CP problem.
- Neutrino mass mechanism beyond minimal SM.
- Muon g-2 as a precision test with theory-baseline uncertainty.
- QCD confinement and Yang-Mills mass gap.

Validation target:

- Higgs-sector nodes should be mostly `DERIVED`/`EMPIRICAL`, not `GAP`.
- Neutrino mass mechanism remains `GAP`.
- QCD nonperturbative bridge has high seam count.

### Phase C: Gravity and Cosmology Map

Create a dynamic map using cosmic time/energy scale:

```text
planck_boundary
inflation_or_initial_conditions
reheating
electroweak
qcd_hadronization
nucleosynthesis
recombination_cmb
structure_formation
late_time_acceleration
gravitational_wave_astrophysics
observers_and_measurements
```

Core/interior:

```text
core.general_relativity
core.quantum_field_theory_on_curved_background
bridge.flrw_cosmology
bridge.perturbation_theory
bridge.n_body_structure_formation
```

Boundary anchors:

```text
obs.cmb_planck
obs.bao_desi
obs.supernovae_distance_ladder
obs.gravitational_wave_catalog
obs.large_scale_structure
```

Gaps/tensions:

```text
gap.quantum_gravity_initial_singularity
gap.inflation_model_selection
gap.dark_energy_dynamics
gap.hubble_tension
gap.s8_growth_tension
gap.dark_matter_identity
```

Validation target:

- Base LambdaCDM should have high volume and high empirical support.
- Dark-energy dynamics and late-time tensions should thicken the boundary, not replace the whole core by default.

### Phase D: Dark Sector and Beyond-Standard-Model Map

Create a search/constraint map rather than a claim map.

Candidate exterior families:

```text
external.wimp
external.axion_alp
external.sterile_neutrino
external.hidden_sector
external.modified_gravity
external.early_dark_energy
external.dynamical_dark_energy
external.supersymmetry
```

Boundary constraints:

```text
obs.lz_wimp_limits
obs.collider_missing_energy
obs.indirect_gamma_ray_limits
obs.cmb_neutrino_mass_constraints
obs.desi_dark_energy_constraints
obs.gravitational_wave_modified_propagation
```

Validation target:

- Exterior hypotheses should not be counted as closed volume unless explicitly connected by successful constraints or derivations.
- Constraints should reduce viable exterior area while leaving identity gaps visible.

### Phase E: Emergence and Effective Theory

Integrate:

```text
thermodynamic_limit
renormalization_group
hydrodynamics
condensed_matter_effective_theories
phase_transitions
chemistry_from_qed_and_many_body_approximations
measurement_and_decoherence
complex_systems
```

Validation target:

- Approximation edges dominate the seams.
- `validity_regime` fields are required for every effective theory.

## 6. Validation Strategy

Each physics map gets an explicit validation profile:

```text
expected_gap_ids
expected_min_seam_count
expected_boundary_nodes
expected_source_coverage
required_artifacts
lean_check_required
```

Add a generic command:

```bash
proofmap validate examples/current_physics_backbone.json --profile validation/current_physics_backbone.json
```

Until that generic validator exists, add focused tests:

```text
tests/test_current_physics_backbone.py
tests/test_standard_model_map.py
tests/test_gravity_cosmology_map.py
tests/test_dark_sector_map.py
```

Core validation checks:

1. All source-backed nodes have source IDs.
2. All gap/tension nodes expected by the profile appear in the defect ledger.
3. Lean scaffold compiles.
4. Report, metrics, surface layout, CSV ledgers, and JSON map are non-empty.
5. Dynamic maps produce epoch rows and surface mode `time`.
6. Source dates are present and parseable.

## 7. First Implementation Slice

Start with `current_physics_backbone`, not the detailed Standard Model.

### Work Items

1. Add source registry support.
2. Add a `build_current_physics_backbone_map()` function.
3. Add `proofmap validate-current-physics` or generic profile validation.
4. Generate:

```text
examples/current_physics_backbone.json
outputs/current_physics_backbone/current_physics_backbone_report.md
outputs/current_physics_backbone/current_physics_backbone_metrics.json
outputs/current_physics_backbone/current_physics_backbone_defects.csv
outputs/current_physics_backbone/current_physics_backbone_surface_explorer.html
outputs/current_physics_backbone/current_physics_backbone_LeanSketch.lean
outputs/current_physics_backbone/current_physics_backbone_validation_summary.json
```

5. Add tests asserting expected gaps:

```text
gap.quantum_gravity
gap.dark_matter_identity
gap.dark_energy_microphysics
gap.neutrino_mass_mechanism
gap.baryon_asymmetry
gap.confinement_mass_gap
```

### Done Criteria

- `python -m pytest -q` passes.
- `proofmap lean-check outputs/current_physics_backbone/*_LeanSketch.lean` passes.
- Validation summary reports `ok: true`.
- Top defect table is plausible to a domain expert.
- Every nontrivial node has at least one source ID.

## 8. Release Milestones

### v0.4: Source-backed backbone

- Source registry.
- Backbone map.
- Validation profile.
- Generated artifacts.

### v0.5: Standard Model and QCD/Nuclear maps

- SM graph with Higgs, flavor, neutrino, precision tests.
- QCD/nuclear seam graph.
- Tests for known open gaps.

### v0.6: Gravity/Cosmology dynamic map

- Dynamic LambdaCDM/GR map.
- Planck, DESI, supernova, gravitational-wave anchors.
- Tension nodes for H0, S8, evolving dark-energy hints.

### v0.7: Dark sector and BSM constraints

- Search/constraint graph for dark matter and dark energy candidates.
- Exterior hypothesis handling.

### v0.8: Source refresh and review loop

- CLI source audit.
- Stale-source warnings.
- Optional export of source coverage metrics.

## 9. Review Rules

Use the following review gates before accepting a physics node:

1. Is this a law kernel, derived relation, empirical input, approximation, or open problem?
2. What source supports it?
3. What is its validity regime?
4. What uncertainty kind applies?
5. Does the node hide multiple claims that should be split?
6. Does an edge mean proof, approximation, empirical calibration, or mere correlation?
7. Is the claim current as of the release date?

Any ambiguous item should enter as a boundary node or seam, not as a core node.

## 10. Immediate Next Step

Implement v0.4:

```text
source registry
current_physics_backbone map
current_physics_backbone validation profile
generated validation run
```

This is the smallest credible step from the current minimal CONOPS validation to a real physics integration.

## 11. Execution Status

v0.4 has been implemented as the source-backed current physics backbone:

```text
examples/current_physics_backbone.json
examples/sources/current_physics_sources.json
outputs/current_physics_backbone/current_physics_backbone_validation_summary.json
```

Validation result:

```text
ok: true
node_count: 43
gap_count: 12
seam_count: 20
source_coverage_errors: 0
lean_ok: true
```

Next implementation milestone: v0.5, the detailed Standard Model plus QCD/nuclear seam maps.
