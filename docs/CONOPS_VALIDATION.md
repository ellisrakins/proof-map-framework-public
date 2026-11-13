# Minimal CONOPS Validation

This validation run proves the project concept of operations on a deliberately small map.

## Workflow

```text
typed proof map
  -> metrics and defect detection
  -> markdown/CSV/JSON reports
  -> radial and surface visualizations
  -> Lean scaffold export
  -> optional Lean compiler check
  -> validation summary
```

The seed map has five nodes:

```text
core.motion_law
model.drop_prediction
bridge.calibration_model
boundary.sensor_measurement
boundary.drag_residual
```

`boundary.drag_residual` is intentionally left as a gap. A successful validation run must detect exactly that proof-boundary debt while still producing all artifacts.

## Run

```bash
proofmap validate-conops --out outputs/conops_validation --require-lean
```

Expected terminal shape:

```text
summary: outputs\conops_validation\minimal_conops_validation_summary.json
ok: true
gap_count: 1
seam_count: 4
expected_defect: True
lean_ok: true
note: CONOPS validation passed
```

## Validation Artifacts

```text
outputs/conops_validation/minimal_conops.json
outputs/conops_validation/minimal_conops_report.md
outputs/conops_validation/minimal_conops_metrics.json
outputs/conops_validation/minimal_conops_defects.csv
outputs/conops_validation/minimal_conops_boundary_ledger.csv
outputs/conops_validation/minimal_conops_sphere.svg
outputs/conops_validation/minimal_conops_surface_atlas.svg
outputs/conops_validation/minimal_conops_surface_explorer.html
outputs/conops_validation/minimal_conops_surface_points.csv
outputs/conops_validation/minimal_conops_surface_layout.json
outputs/conops_validation/minimal_conops_LeanSketch.lean
outputs/conops_validation/minimal_conops_validation_summary.json
```

The validation summary is the machine-readable result for automation.
