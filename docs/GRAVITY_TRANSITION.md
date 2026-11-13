# Newton to Einstein: a regime-transition test case

`proofmap.gravity_example.build_gravity_transition_map()` creates a curated,
source-backed teaching map with 23 nodes and 36 explanatory links. It is not
extracted from a user's paper, a formal derivation, or an evidence-acceptance event.
The Studio can present this as an independent example.

## Read the transition

Start with Newtonian potential gravity and its classical kinematics. Special
relativity changes the spacetime setting; it does not itself supply gravity.
Local equivalence and curved spacetime lead into the GR portion. Then follow
**both** approximation bridges: geodesic motion to Newtonian acceleration, and
Einstein's field equations to Poisson's equation. The regime node supplies the
assumptions rather than pretending Newton follows without qualifications.

The Mercury and light-bending nodes show why useful Newtonian approximations
have precision limits. Light is not slow, even in a weak field. The example
separates local inertial behavior from globally absent curvature and leaves
quantum-gravity completion outside its scope.

This is a conceptual dependency map, not a time simulation. Its guided path is
in `metadata.guided_path`. Node statuses describe authored textbook/empirical
roles, not acceptance by ProofMap. Required numeric uncertainty fields use zero
only as a schema placeholder with `uncertainty_kind=NOT_ASSESSED`; a presentation
must not interpret them as measured confidence. No edge uses `PROVES`.

## Sources and traceability

Each node and edge has `source_ids`, resolved by `metadata.sources`:

- [Einstein's own exposition](https://www.gutenberg.org/files/5001/5001-h/5001-h.htm),
  Parts I-II and Appendix III: SR/GR distinction, equivalence, geometry and tests.
- [Milotti, The Newtonian limit](https://wwwusers.ts.infn.it/~milotti/Didattica/GravitationalWaves/handouts/11-NewtonianLimit.pdf),
  sections 1-2: assumptions and the two approximation bridges. The example
  explicitly uses the opposite metric-sign convention (-,+,+,+) for its g00
  expression; the physical acceleration is unchanged.
- [Shapiro and Shapiro, gravitational deflection](https://www.einstein-online.info/en/spotlight/light_deflection/):
  GR versus the historical corpuscular comparison and its applicability.
- [Stanford Gravity Probe B](https://einstein.stanford.edu/SPACETIME/spacetime3.html):
  observational constraints and the limits of classical completion.

Tests check schema/round-trip validity, source coverage, both regime bridges,
SR/GR distinctions, and absence of formal-proof/acceptance claims. They do **not**
prove the physical theories or independently validate observations.

```sh
python -m pytest tests/test_gravity_example.py -q
```

## Boundary analysis workflow

Six `metadata.boundary_walkthrough` stages scope Newton's closure, expose frontier
obligations, trace assumptions, introduce a candidate, demand coverage and limit
recovery, then reorganize the explanation. Every stage includes `id`, `title`,
`detail`, `node_ids`, `question`, `evidence`, `action`, `outcome`, and `source_ids`.
The UI can highlight nodes without claiming a new scientific calculation occurred.

The gaps differ: Mercury is a precision residual; instantaneous interaction is
a compatibility tension (Einstein, Part I, XV); photons require a propagation
bridge outside the slow-body limit. These constraints do not uniquely select GR.

**Collapse** here means curated explanatory reorganization, not graph-driven
discovery or proof of Einstein's equations. Newton remains a controlled regime,
and gaps remain visible as historical obligations with independent validation
requirements. No invented closure percentage or quantitative result is supplied.

## Entropy research extension

Three appended stages (nine total) distinguish the proposals, audit their
assumptions, and demand discriminating evidence before any further collapse.
They do not portray entropy gravity as an established successor to GR.

- [Jacobson 1995](https://arxiv.org/abs/gr-qc/9504004): a conditional
  equation-of-state argument using local equilibrium, horizon area entropy,
  Clausius balance and Unruh temperature. This is not Verlinde's force proposal.
- [Verlinde 2011](https://arxiv.org/abs/1001.0785): a holographic-screen and
  equipartition construction (preprint 2010), with a proposed relativistic
  generalization.
- [Verlinde 2016](https://arxiv.org/abs/1611.02269): a distinct de Sitter/entropy
  displacement proposal (journal 2017) motivating apparent-dark-matter effects.

The microscopic/nonequilibrium and empirical-discrimination nodes are evaluation
obligations, not claims of refutation or confirmation. No observational data are
fit here; no numerical ranking, universal completion or dark-matter elimination
is asserted. Existing six Newton-to-GR stages are preserved unchanged.
