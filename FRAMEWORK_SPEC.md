# Framework Specification: Proof Map Boundary Analysis

## Current normative trust boundary (2026-10-02)

[TRUSTED_KERNEL.md](docs/TRUSTED_KERNEL.md) governs accepted closure, contexts,
first-class AND/OR inferences, evidence bindings, migration and domain-separated
identities. [PAPER_CI.md](docs/PAPER_CI.md) governs source review. The historical
geometry model below is not a definition of mathematical acceptance. Authored
status weights no longer determine closure_ratio. Scenario overlays no longer
promote target statuses. The current
[acceptance contract](docs/ALPHA_ACCEPTANCE.md) and
[mandatory requirement ledger](acceptance/paper_ci_alpha.json) govern alpha
completion; dated advancement reports preserve historical evidence.

The bounded manuscript path distinguishes immutable source syntax, attributed
interpretation, model candidates, formal subjects, execution evidence, fidelity
decisions and policy assessment. Source contexts, citations, proof associations
and AND/OR dependency groups describe author structure. They do not establish the
truth of a claim. Unresolved syntax and ambiguity stay explicit.

The restricted formal profile covers one universally quantified integer variable,
polynomial equality and an optional explicit linear equality antecedent with one
bounded integer root. Supported zero-argument integer-literal macros retain their
source declaration dependencies. Exact arithmetic checks and generated Lean text
are separate from authenticated isolated execution and independent source/formal
fidelity decisions. See [the complete grammar](docs/PAPER_FORMAL_PROFILE.md).

Review overrides append an attributed record, preserve raw sources and model
outputs, and recompute a separate interpreted view. A changed interpretation does
not retain prior execution or acceptance. Dependency-aware revision reuse may
reuse eligible pure artifacts and historical execution only after validating the
current dependencies, environment and authority; current bindings, reviews and
policy assessment remain mandatory. Evidence-action plans and simulations expose
their assumptions and hypothetical effects without granting actual acceptance.

The bounded implementation is packaged as candidate `0.8.0a1`. Required-profile
qualification is evaluated for the exact source and distribution recorded by the
acceptance artifact and required checks. Version metadata does not itself confer
readiness. Software readiness, package-index publication, production authority and
scholarly acceptance are reported independently. The geometry model below remains
a visualization and planning model.

## 1. Object model

A proof map is a directed typed graph with optional theory-chart bindings:

```text
G = (V, E, C, B, T, P, R)
```

where:

```text
V = nodes: axioms, laws, definitions, theorems, models, bridges, observations, phenomena, gaps
E = directed dependency edges from explanatory source to dependent target
C = core nodes: primitive laws / axioms / accepted foundations
B = boundary nodes: phenomena, observations, interfaces, uncertainty, open gaps
T = optional epochs for dynamic surfaces
P = theory profiles and many-to-many node/edge memberships
R = typed relations among theory profiles
```

Edges point outward:

```text
core → definitions → models/theorems → boundary phenomena
```

## 2. Geometry interpretation

| Geometry | Software metric | Meaning |
|---|---|---|
| Center | core nodes | primitive axioms / law kernel |
| Radius | shortest proof distance | derivational depth from core |
| Volume | `explanatory_volume` | weighted explanatory content enclosed by graph |
| Surface area | `surface_area` | boundary complexity and external attachment cost |
| Roundness | `roundness` | uniform derivability from core to boundary |
| Density | `density` | explanatory content per proof cost |
| Thickness | `uncertainty_thickness` | classified uncertainty at boundary and seams |
| Holes/cavities | `hole_count` and defect ledger | unreachable or unresolved boundary regions |
| Seams/creases | `seam_count` and seam defects | approximation or cross-domain interfaces |

## 3. Closure paths

A boundary defect should be classified into one of these closure paths:

```text
mathematical proof
empirical calibration
probabilistic law
approximation/limit theorem
computational/numerical certificate
semantic bridge theorem
independence result
explicit external assumption
```

The point of the software is to prevent these from being conflated.

## 4. Theory-chart layer

The graph vocabulary is stable while theory profiles are open data:

```text
P_i = (identity, kind, maturity, evidence, foundations, mathematics,
       validity regimes, results, open questions, tests, provenance)
```

Claims and dependencies may carry zero, one, or many `theory_ids`. Zero denotes a shared or not-yet-classified element. Many-to-many membership allows an observation or defect to sit on several competing or overlapping charts.

Theory maturity and evidence are orthogonal. For example, an effective theory can be precision tested within a limited regime, while a broad research program can be mathematically developed but empirically unconfirmed.

Validity is multidimensional:

```text
regime = {
  energy, length, time, temperature, curvature, coupling,
  particle number, approximation order, computational cutoff, ...
}
```

The schema leaves these coordinates open so a new scientific domain does not require a software release.

## 5. Dynamic boundary

The active proof boundary may vary with cosmic time, energy scale, temperature, or epistemic state:

```text
∂G(t, E, T, μ)
```

In the current implementation, `Epoch` and node active intervals support time slices:

```python
pm.time_slice(t)
metrics_over_epochs(pm)
```

This represents the idea that the fundamental core may be fixed while the effective surface rules change through phase transitions, coarse-graining, emergence, and observation.

## 6. Entropy/time/energy interpretation

The framework separates three flows:

```text
tangential flow on boundary: time / entropy / physical histories
radial flow through volume: proof / explanation / derivation
shell-to-shell flow: energy scale / effective theory / renormalization / emergence
```

A theory is stronger when every surface trajectory has an interior proof/explanation fiber showing why it is possible, probable, conserved, irreversible, or emergent.

## 7. Current scoring heuristics

The metrics are intentionally interpretable rather than opaque.

### Explanatory volume

```text
sum(weight(node) × status_confidence(node) × reachability_factor × uncertainty_discount)
```

excluding core and exterior nodes.

### Surface area

```text
sum(boundary_weight × status_penalty × (1 + uncertainty))
+
interface/assumption/approximation edge penalties
```

### Roundness

```text
uniformity_of_boundary_proof_distances × closure_ratio
```

where uniformity is the inverse of normalized proof-distance variance.

### Thickness

```text
weighted average boundary uncertainty + seam uncertainty adjustment
```

## 8. Development roadmap

1. Strengthen the included JSON Schema with semantic validation rules.
2. Add an interactive web viewer for proof-sphere maps.
3. Add GraphML/DOT export and NetworkX optional integration.
4. Add proof-assistant connectors for Lean/Rocq/Isabelle source files.
5. Add theorem-dependency import from Lean declarations.
6. Add uncertainty provenance: empirical, computational, probabilistic, approximation, semantic, logical.
7. Add executable slicing across all `regime_dimensions`, beyond the current scalar time and theory slices.
8. Add incompatibility constraints, likelihood updates, and evidence ingestion for competing hypotheses.

The first solver-verification connector is now implemented as Verified Lean Attempt v1. It is deliberately additive: the axiom-oriented visualization scaffold remains separate from exact-statement proof checking.

The original closure optimizer and a first conditional hypothesis-ranking layer are implemented. The latter compares researcher-supplied candidate mechanisms by simulated closure value, explicit predictions, falsifiability, declared plausibility, complexity, and auxiliary assumptions.

## 9. Conditional hypothesis search

A hypothesis catalog extends the proof map with proposals of the form:

```text
H = (targets, inputs, assumptions, predictions, status, uncertainty,
     complexity, falsifiability, prior plausibility, provenance)
```

For each proposal, the engine clones the map, adds the candidate as an assumed interior model, connects its declared inputs, and conditionally changes its targets to the proposed status and uncertainty. It then measures the metric deltas and computes an interpretable value-of-information score:

```text
score(H) = structural_gain
         + testability_bonus
         + plausibility_bonus
         - complexity_penalty
```

This operation does not mutate the source map and does not promote a candidate to accepted evidence. Its output is a priority ordering for proof, simulation, or experiment. A future evidence layer must represent mutually exclusive claims, observation likelihoods, contradiction constraints, and posterior status updates before the platform can support stronger solver claims.

## 10. Verifier-gated proof attempts

An AI or human proof candidate is represented outside the proof map until it passes an explicit verification contract:

```text
FormalObligation = (target node, exact statement hash, imports, toolchain, allowed axioms)
ProofAttempt     = (artifact hash, producer/model/run, parents, strategy, resources)
Verification     = (scope, verifier/version, outcome, diagnostics, axioms, duration)
AttemptReceipt   = (map/source/target hashes, obligation, attempt, verification, receipt hash)
```

Verified Lean Attempt v1 accepts a Lean proof term, generates the theorem header from the obligation, rejects placeholders and common declaration/command constructs, checks a declared Lean version when present, compiles it with Lean, and audits `#print axioms`. The outcome fails closed if the compiler output cannot be interpreted.

The verifier never mutates the source graph and refuses output paths that alias any input. Receipts use immutable in-memory records, single-read artifact hashing, canonical map snapshots, pinned Lean-release checks, and cross-field/content-hash validation on load. Promotion from `GAP` to `PROVED` requires a later statement-fidelity gate confirming that the encoded proposition matches the intended claim. Novelty, significance, literature support, and empirical validation remain orthogonal evidence dimensions.

Attempt receipts are designed as the stable boundary for future planner/worker/verifier agents. Failed candidates, compiler diagnostics, parent attempt ids, compute use, and costs can be retained for repair, branching, abstention, and cost-aware routing.

## Surface Visualization Layer

A proof map can be projected onto a surface model for boundary analysis.

### Surface coordinates

For each node `n`, the renderer computes:

```text
longitude(n) = domain sector + deterministic within-domain offset
latitude(n)  = temporal coordinate when epoch data exists, otherwise proof-distance coordinate
radius(n)    = layer radius: CORE < INTERIOR < BOUNDARY < EXTERIOR
thickness(n) = uncertainty-weighted halo, with penalties for GAP, BLOCKED, EXTERNAL, ASSUMPTION, and APPROXIMATION statuses
```

### Coordinate modes

```text
auto:
    use time mode if the map has epochs or node active intervals;
    otherwise use proof-depth mode

time:
    latitude = log-scaled active cosmic time, with earlier/high-energy regimes near the north/top

proof_depth:
    latitude = shortest proof distance from core; disconnected nodes sit at the unclosed lower boundary
```

### Edge classes

```text
flow edge:
    EdgeKind.FLOWS_TO; interpreted as tangent surface flow

seam edge:
    bridge/interface/limit/approximation/empirical constraint with uncertainty or cross-domain tension

gap edge:
    EdgeStatus.GAP or EdgeStatus.BLOCKED; interpreted as a boundary deformation

proof fiber:
    ordinary proof/dependency relation supporting the surface from core or interior layers
```

### Output contract

A surface bundle contains:

```text
surface_atlas.svg      static unwrapped surface projection
surface_explorer.html  interactive standalone globe projection
surface_points.csv     tabular coordinates and boundary-thickness ledger
surface_layout.json    full serialized layout for downstream renderers
```

This layer operationalizes the claim that time/entropy/energy flow is tangent to the active proof boundary, while proof/explanation paths traverse the enclosed volume.
