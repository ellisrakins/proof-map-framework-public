# Minimal CONOPS Validation Map — Proof Boundary Analysis

A compact proof-map used to validate the concept of operations: author a typed map, analyze its boundary, produce artifacts, export Lean obligations, and confirm the expected open proof debt is detected.

## Geometry metrics

| Metric | Value | Interpretation |
|---|---:|---|
| `explanatory_volume` | 4.441 | Weighted amount of nontrivial content currently enclosed by the proof map. |
| `surface_area` | 14.13 | Boundary complexity: open interfaces, assumptions, empirical patches, and uncertainty. |
| `roundness` | 0.2132 | Uniform derivability from the core; higher means less jagged proof distance across the boundary. |
| `density` | 0.3019 | Explanatory volume per unit proof/derivation cost. |
| `closure_ratio` | 0.2132 | Weighted share of boundary nodes with a classified closure path. |
| `uncertainty_thickness` | 0.525 | Average thickness of probabilistic, empirical, approximate, or unresolved boundary regions. |
| `hole_count` | 1 | Boundary/exterior nodes not derivably connected to the core or still gaplike. |
| `seam_count` | 4 | Cross-domain or approximation interfaces with tension/uncertainty. |
| `gap_count` | 1 | Nodes explicitly marked as gap, blocked, or external. |
| `unexplained_parameter_count` | 0 | Empirical/assumed constants that remain boundary defects. |

## Diagnosis

- 1 boundary/exterior nodes are gaplike or not reachable from the core.
- 4 interface or cross-domain seam edges detected.
- 1 gaplike nodes require closure work.

## Highest-severity proof-boundary defects

| Rank | Defect | Type | Severity | Closure path | Affected downstream nodes |
|---:|---|---|---:|---|---|
| 1 | `boundary.drag_residual` | proof_gap | 7.75 | modeling + proof | boundary.sensor_measurement |
| 2 | `model.drop_prediction->boundary.drag_residual` | seam_or_interface_tension | 2.475 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | model.drop_prediction, boundary.drag_residual |
| 3 | `boundary.drag_residual->boundary.sensor_measurement` | seam_or_interface_tension | 2.4 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | boundary.drag_residual, boundary.sensor_measurement |
| 4 | `bridge.calibration_model->boundary.sensor_measurement` | seam_or_interface_tension | 1.312 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | bridge.calibration_model, boundary.sensor_measurement |
| 5 | `model.drop_prediction->boundary.sensor_measurement` | seam_or_interface_tension | 1.003 | classify as proof, limit theorem, approximation theorem, empirical calibration, or independence result | model.drop_prediction, boundary.sensor_measurement |

## Closure-priority simulation

This estimates which single-node closure would most improve the current proof geometry. It is a heuristic planning aid, not a proof result.

| Rank | Candidate | Current → proposed | Δ volume | Δ surface | Δ roundness | Δ closure | Δ thickness | Score | Rationale |
|---:|---|---|---:|---:|---:|---:|---:|---:|---|
| 1 | `boundary.drag_residual` | GAP → PROVED | 3.68 | -5.423 | 0.552 | 0.552 | -0.342 | 5.528 | mathematical proof closure |
| 2 | `bridge.calibration_model` | APPROXIMATION → DERIVED | 0.1766 | 0 | 0 | 0 | 0 | 0.0392 | replace approximation with limit/matching theorem and controlled error |

## Boundary ledger

| Node | Layer | Status | Domain | Theories | Proof distance | Uncertainty | Statement |
|---|---|---|---|---|---:|---:|---|
| `boundary.drag_residual` | BOUNDARY | GAP | experiment | — | 2 | 0.65 | The residual between ideal prediction and measurement needs a drag or calibration closure. |
| `boundary.sensor_measurement` | BOUNDARY | EMPIRICAL | experiment | — | 2 | 0.18 | A sensor reports the observed drop time in the validation run. |

## Proof map nodes

| Node | Kind | Status | Layer | Domain | Theories | Weight | Cost | Sources | Notes |
|---|---|---|---|---|---|---:|---:|---|---|
| `boundary.drag_residual` | GAP | GAP | BOUNDARY | experiment | — | 4 | 3 | — | This intentional gap proves the validator detects unresolved boundary debt. |
| `boundary.sensor_measurement` | OBSERVATION | EMPIRICAL | BOUNDARY | experiment | — | 3 | 1 | — | A sensor reports the observed drop time in the validation run. |
| `core.motion_law` | PRIMITIVE_LAW | CORE | CORE | mechanics | — | 4 | 1 | — | A simplified constant-acceleration law governs the test object. |
| `bridge.calibration_model` | BRIDGE | APPROXIMATION | INTERIOR | instrumentation | — | 2 | 2 | — | A provisional sensor calibration maps raw timestamps into the measured drop time. |
| `model.drop_prediction` | THEOREM | DERIVED | INTERIOR | mechanics | — | 3 | 2 | — | The ideal law predicts a drop time from height and acceleration. |

## How to read this map

- **Volume** is explanatory content enclosed by the current formal structure.
- **Surface area** is boundary complexity: external assumptions, empirical attachments, patches, and open interfaces.
- **Roundness** is high when boundary phenomena have similar derivational distance from the compact core.
- **Thickness** is classified uncertainty: probabilistic law, approximation, measurement error, computational limits, or unresolved proof debt.
- **Seams** are force/domain/theory interfaces where local charts must be glued by bridge principles.
