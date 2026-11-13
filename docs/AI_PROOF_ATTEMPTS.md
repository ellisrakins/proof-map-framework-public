# AI Proof Attempts and Verification Receipts

## Direction

The proof map should be the durable verification and provenance layer for AI-assisted mathematics, not another monolithic solver.

That choice follows the strongest current systems. AlphaEvolve couples generators to automated evaluators and preserves a population of candidate programs. Aletheia iterates between a generator, verifier, and reviser and explicitly permits failure. Recent Lean agents preserve failed attempts and compiler feedback for repair. The common pattern is:

```text
gap -> strategy -> candidate -> verifier feedback -> repair or branch -> accepted artifact
```

The map is valuable at the two ends of that loop: it selects consequential gaps and records what a successful artifact actually establishes.

## Current evidence

This design was reviewed against public results available on 2026-08-05:

- An OpenAI reasoning model produced an externally reviewed disproof of a longstanding unit-distance conjecture. The result illustrates that general-purpose models can now generate original frontier mathematics, while the external review remains essential. See the [official report](https://openai.com/index/model-disproves-discrete-geometry-conjecture/) and linked proof.
- [AlphaProof Nexus](https://arxiv.org/abs/2605.22763) reports compiler-checked Lean proofs for open Erdos and OEIS problems and publishes its [result artifacts](https://github.com/google-deepmind/alphaproof-nexus-results).
- [Aletheia](https://arxiv.org/abs/2602.10177) uses iterative generation, verification, revision, literature search, and abstention for natural-language research mathematics. Its audits show that technical correctness and solving the intended problem are separate questions.
- [Rethlas and Archon](https://arxiv.org/abs/2604.03789) separate informal discovery, formalization, kernel checking, and comparison with a short human-readable specification.
- [AlphaEvolve](https://deepmind.google/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/) combines an ensemble of models with executable evaluators and evolutionary selection; verified constructions and improved bounds are first-class outputs rather than prose claims.
- [OProver](https://arxiv.org/abs/2605.17283) retains Lean feedback, failed attempts, repairs, and retrieved verified proofs as training and search state.
- [OpenProver](https://arxiv.org/abs/2607.09217) uses a planner-worker-verifier architecture, parallel work, durable intermediate findings, formal verification, and optional human steering.

These systems motivate four independent gates:

1. **Artifact integrity** — exact content hashes and a recorded verifier/toolchain version.
2. **Formal correctness** — a kernel or executable checker accepts the artifact.
3. **Statement fidelity** — experts or trusted comparison tools confirm that the formal statement represents the intended problem.
4. **Research assessment** — novelty, significance, citation support, and the human/AI contribution are reviewed separately.

Verified Lean Attempt v1 implements the first two gates for a narrow, reproducible Lean proof term. It deliberately does not claim the latter two.

## Verified Lean Attempt v1

The implementation adds:

```text
proofmap/attempts.py                  obligation, attempt, receipt, policy, Lean verifier
schema/formal_obligation.schema.json immutable statement contract
schema/proof_attempt.schema.json     machine-readable verification receipt
proofmap attempt-check               model-agnostic CLI entry point
```

A `FormalObligation` binds:

- one proof-map target node;
- the exact Lean proposition and its SHA-256 hash;
- the declaration name and imports;
- a pinned Lean release identifier; and
- the explicit set of permitted axioms.

A `ProofAttempt` records:

- the candidate artifact and content hash;
- producer, provider, model/version, and external run identifier;
- prompt hash and parent attempts;
- strategy, token counts, generation time, and estimated cost.

The verifier constructs the theorem header itself, inserts only the candidate proof term, rejects placeholders and common declaration/command constructs, confirms a declared Lean version when supplied, runs Lean, and audits `#print axioms`. A pass therefore applies to the exact obligation statement, not a model-selected substitute.

Every outcome writes an immutable `AttemptReceipt` containing a canonical map-snapshot hash, source-file hash when available, target, obligation, artifact, wrapper, and whole-receipt hashes; the exact verifier version and command; duration; stdout/stderr; transitive axioms; policy findings; and an explicit semantic caveat. Receipt loading recomputes the derivable hashes and rejects contradictory verdict fields.

The source map is never mutated. Even a `VERIFIED` receipt does not automatically change a node to `PROVED`, because kernel verification alone cannot establish that the formal statement faithfully represents the natural-language research problem.

## Run the included example

From the repository root:

```bash
proofmap attempt-check \
  examples/attempts/nat_reflexivity_map.json \
  examples/attempts/nat_reflexivity_obligation.json \
  examples/attempts/nat_reflexivity_candidate.lean \
  --producer example-human \
  --out outputs/attempts/nat_reflexivity_receipt.json
```

Without an editable install, use:

```bash
python -m proofmap.cli attempt-check \
  examples/attempts/nat_reflexivity_map.json \
  examples/attempts/nat_reflexivity_obligation.json \
  examples/attempts/nat_reflexivity_candidate.lean \
  --producer example-human \
  --out outputs/attempts/nat_reflexivity_receipt.json
```

The candidate file is a Lean proof term beginning with `by`, not a complete theorem declaration:

```lean
by
  intro n
  rfl
```

## Outcomes

| Outcome | Meaning |
|---|---|
| `VERIFIED` | Lean accepted the exact statement and all reported axioms were explicitly permitted. |
| `POLICY_REJECTED` | The candidate contained a placeholder or declaration-level construct disallowed by v1. |
| `COMPILER_REJECTED` | Lean rejected the generated theorem. Diagnostics are preserved. |
| `UNTRUSTED_AXIOMS` | Lean accepted the theorem, but `#print axioms` reported an undeclared dependency. |
| `TIMEOUT` | Lean did not finish within the configured budget. |
| `VERIFIER_UNAVAILABLE` | No Lean executable could be resolved. |
| `VERIFIER_ERROR` | The verifier failed or could not interpret the axiom audit; this fails closed. |

CLI exit codes are `0` for `VERIFIED`, `1` for an ordinary candidate rejection or timeout, and `2` for invalid input, unavailable tooling, or an internal verifier error. All expected verification outcomes still write a receipt; invalid input does not.

## Trust boundary

This verifier is a proof-integrity tool, not a hostile-code sandbox. Lean elaboration can execute metaprograms, and future adapters may execute generated programs. Run candidate artifacts only inside an appropriately isolated environment when their producer is not trusted.

Kernel verification proves the encoded proposition relative to its imports and permitted axioms. The receipt confirms the Lean release, but v1 does not yet hash every imported package or project dependency. It also does not by itself prove:

- that the formalization matches the intended natural-language problem;
- that imported declarations are free of bugs outside the kernel's guarantees;
- that an asserted problem was open when the attempt was generated;
- novelty, importance, attribution, or citation accuracy; or
- empirical claims represented elsewhere in a physics proof map.

## Next slices

1. Add an append-only attempt ledger with branch ancestry, critic records, repair feedback, stop reasons, and cost-aware search summaries.
2. Add statement-fidelity reviews and a Comparator-style gate before any map status promotion.
3. Import theorem dependencies and frozen tasks from Lean projects and [Formal Conjectures](https://google-deepmind.github.io/formal-conjectures/).
4. Add evaluator plugins for Lean, executable witnesses, finite counterexamples, CAS certificates, and numerical checks; keep their verification scopes distinct.
5. Add provider-neutral planner/worker/verifier adapters with budgets, cancellation, abstention, and persistent failed branches.
6. Track formal pass@k, false-accept rate, statement-fidelity acceptance, meaningful-solution rate, review time, cost, and replay success under pinned dependencies.
