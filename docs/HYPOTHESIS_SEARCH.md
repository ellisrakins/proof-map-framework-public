# Conditional Hypothesis Search

The hypothesis-search layer moves the toolkit from defect ranking toward structured work on unknown frameworks.

It does not generate truth or prove a candidate mechanism. It compares explicit proposals under a conditional question:

> If this mechanism closed the stated targets at the proposed uncertainty, how much structural value would it add, and how costly and testable is it?

## Workflow

```text
open defect
  -> candidate mechanisms
  -> explicit assumptions
  -> discriminating predictions
  -> conditional closure simulation
  -> complexity/testability ranking
  -> experiment or formal proof
  -> evidence-backed status update
```

The final evidence-backed status update remains outside the conditional search. A high score is a reason to test a candidate, not a reason to accept it.

## Run

```bash
proofmap hypothesis-search \
  examples/minimal_conops.json \
  examples/hypotheses/minimal_conops_hypotheses.json \
  --out outputs/hypothesis_search \
  --basename minimal_conops
```

Expected ranking:

```text
hypothesis.quadratic_drag
hypothesis.clock_bias
hypothesis.free_correction
```

The quadratic-drag mechanism ranks first because it offers strong conditional closure and several discriminating predictions. The unconstrained correction ranks last because it can fit the residual without explaining it or risking clear falsification.

## Score Components

The score combines:

```text
structural gain
  explanatory volume
  closure ratio
  roundness
  density
  surface/thickness reduction

testability bonus
  falsifiability
  number of explicit predictions

plausibility bonus
  declared prior plausibility

penalties
  model complexity
  auxiliary assumptions
  missing predictions
```

All weights are heuristic and visible in `proofmap/hypothesis.py`. They should eventually become configurable validation-profile parameters.

## Catalog Contract

Hypothesis catalogs conform to `schema/hypothesis.schema.json` and include:

```text
id
label
description
target_nodes
input_nodes
assumptions
predictions
proposed_status
proposed_uncertainty
complexity
falsifiability
prior_plausibility
domain
source_ids
last_verified
```

## Current Limits

- Candidate mechanisms are supplied by researchers; the engine does not invent them.
- Priors and complexity values are judgments, not objective constants.
- Conditional target status changes are simulations, not evidence updates.
- The engine does not yet model mutually exclusive candidates, joint fits, likelihoods, or contradiction constraints.
- Lean output checks scaffold syntax, not the scientific semantics of a proposal.

The next solver-oriented step is a constraint layer that represents incompatible claims, required observations, and candidate-specific likelihood/evidence updates.
