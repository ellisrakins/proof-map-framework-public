# Minimal CONOPS competing mechanisms

Candidate mechanisms for the intentional drop-time residual. The catalog is designed to demonstrate conditional structural value, prediction specificity, and falsifiability scoring.

> Scores are conditional value-of-information estimates. They do not establish that a candidate is true.

## Baseline

- Map: `Minimal CONOPS Validation Map`
- Gaps: 1
- Seams: 4
- Closure ratio: 0.2132

## Ranking

| Rank | Hypothesis | Score | Structural gain | Testability | Complexity penalty | Targets |
|---:|---|---:|---:|---:|---:|---|
| 1 | `hypothesis.quadratic_drag` | 4.317 | 2.498 | 1.87 | 0.68 | `boundary.drag_residual` |
| 2 | `hypothesis.clock_bias` | 3.862 | 2.276 | 1.55 | 0.384 | `boundary.drag_residual` |
| 3 | `hypothesis.free_correction` | 0.9035 | 1.623 | 0.14 | 1.14 | `boundary.drag_residual` |

## Candidate details

### Quadratic air-drag model

- Conditional status: `APPROXIMATION` at uncertainty 0.16
- Assumptions: The object remains in the quadratic-drag regime.; Air density is measured independently.
- Predictions: Residual magnitude scales approximately with velocity squared.; Residual changes predictably with air density.; Vacuum runs suppress the residual.

### Sensor clock-bias model

- Conditional status: `APPROXIMATION` at uncertainty 0.22
- Assumptions: The timing offset is stable within each run.
- Predictions: The residual is approximately independent of drop height.; An external timing reference reproduces the offset.

### Unconstrained empirical correction

- Conditional status: `APPROXIMATION` at uncertainty 0.4
- Assumptions: The fitted correction remains valid outside the observed sample.
- Predictions: none stated
