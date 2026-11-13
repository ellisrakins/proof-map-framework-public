# Current Physics Backbone

The backbone now includes many-to-many bindings to the extensible catalog in `examples/theories/physics_theory_catalog.json`. Theory and source integrity are checked during `validate-current-physics`; see `docs/THEORY_CATALOG.md`.

This is the first execution slice of the physics integration plan. It creates a source-backed backbone map of the current operational state of fundamental physics.

## Run

```bash
proofmap validate-current-physics --out outputs/current_physics_backbone --require-lean
```

Expected result:

```text
ok: true
node_count: 43
gap_count: 12
seam_count: 20
source_coverage_errors: 0
lean_ok: true
note: Current-physics backbone validation passed
```

## Source Registry

```text
examples/sources/current_physics_sources.json
outputs/current_physics_backbone/current_physics_sources.json
```

Every node and edge in the backbone map references at least one source ID. The validation run fails if a node lacks source IDs, lacks a verification date, or references a missing source.

## Expected Frontier Defects

The validation profile requires these defects to appear:

```text
gap.quantum_gravity
gap.dark_matter_identity
gap.dark_energy_microphysics
gap.neutrino_mass_mechanism
gap.baryon_asymmetry
gap.confinement_mass_gap
```

The current run also surfaces additional boundary debt, including hierarchy/naturalness, initial-condition/inflation selection, measurement foundations, Hubble tension, and S8/growth tension.

## Artifacts

```text
examples/current_physics_backbone.json
outputs/current_physics_backbone/current_physics_backbone.json
outputs/current_physics_backbone/current_physics_backbone_report.md
outputs/current_physics_backbone/current_physics_backbone_metrics.json
outputs/current_physics_backbone/current_physics_backbone_defects.csv
outputs/current_physics_backbone/current_physics_backbone_boundary_ledger.csv
outputs/current_physics_backbone/current_physics_backbone_sphere.svg
outputs/current_physics_backbone/current_physics_backbone_surface_atlas.svg
outputs/current_physics_backbone/current_physics_backbone_surface_explorer.html
outputs/current_physics_backbone/current_physics_backbone_surface_points.csv
outputs/current_physics_backbone/current_physics_backbone_surface_layout.json
outputs/current_physics_backbone/current_physics_backbone_LeanSketch.lean
outputs/current_physics_backbone/current_physics_backbone_validation_summary.json
```
