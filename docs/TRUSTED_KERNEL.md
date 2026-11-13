# Trusted kernel and migration contract

The new API is `proofmap.kernel`. The legacy `Node`, `Edge`, `ProofMap` API
remains available. `migrate(legacy_dict)` retains the original graph in `legacy`,
preserves authored status as historical information, groups all incoming
PROVES/DEPENDS_ON/DEFINES prerequisites into one conjunctive REVIEW_REQUIRED
inference, and creates no accepted foundation. Migration is idempotent.
DEPENDS_ON still means prerequisite -> dependent, never the reverse.

`closure(graph, policy=..., foundations=..., assumptions=..., trusted_evidence=...)`
computes a least fixed point. Every premise must be supported; alternative
inferences are OR alternatives. An inference needs a resolved PASS artifact
whose content digest is explicitly trusted by the caller and whose subject,
context, definition revision, mode, and policy binding match. Status labels,
nonempty artifact IDs, reachability, cycles, and signatures alone are insufficient.
The caller must not pass untrusted graph-provided digests as trusted evidence.

Foundations/assumptions are `(context_id, claim_id)` pairs. Research assumptions
are allowed only by conditional-research-v1. The output preserves minimal
alternative assumption/foundation sets and a witness; it does not union OR
branches into an unnecessarily strong assumption. Unconditional alternatives
take precedence in the closed/conditional partition. Resource truncation is
explicit. Contradictions are reported but never trigger explosion.

Logical hypotheses and quantifier order are retained in claims. This alpha
implementation refuses unverified scope discharge; it does not infer that a
local hypothesis is a globally available claim. Paper extraction leaves
unresolved natural-language quantifiers/hypotheses in the original source text.

Named policies: deductive-strict-v1, computational-reproducible-v1,
empirical-support-v1, conditional-research-v1, paper-assertion-v1. Closure states
are policy/dimension qualified. The paper policy has no accepting inference mode.
Assessment dimensions retain deduction, computation, empirical support and
contradiction, approximation, source/formal fidelity, independent review and
novelty separately. Several dimensions currently remain NOT_ASSESSED.

## Identities

Raw artifacts use conventional SHA-256 of bytes. Structured identities hash
`proofmap NUL domain NUL canonical-JSON`. Distinct domains cover semantic graphs,
inference obligations, policy, evidence, paper manifests, analysis configurations,
source elements, run components and reviews. Entity and set-field order is
canonicalized; hypothesis/quantifier sequence is preserved. No mathematical or
Unicode equivalence is claimed. Semantic graph identity excludes labels,
migration warnings and the retained legacy presentation, but includes authored
states, statements, contexts, inferences and evidence. A historical v1 receipt's
digest algorithm is not rewritten.

Strict JSON rejects duplicate keys, nonfinite numbers, bool-as-number, invalid
paths and unknown versioned fields. New schemas are installed package resources
with `urn:proofmap:*` identities. Legacy schemas remain in their original paths;
packaged copies use project URNs. `schema.validate` returns structured issues.
Some older APIs still raise ValueError rather than the complete issue taxonomy.

## CLI

```sh
proofmap validate examples/minimal_conops.json
proofmap migrate examples/minimal_conops.json --out migrated.json
proofmap canonicalize migrated.json --out canonical.json
proofmap digest migrated.json
proofmap closure migrated.json --policy deductive-strict-v1 --target boundary.drag_residual
```

Legacy geometry is explicitly heuristic. `closure_ratio` now consumes semantic
closure (zero for unaccepted legacy maps), not a weighted authored-status score.
Optimizer/hypothesis scenarios retain original target statuses and store separate
proposed-action metadata. They never generate accepted evidence.
