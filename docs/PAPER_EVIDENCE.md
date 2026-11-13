# Source-to-evidence workflow

Install `.[paper,trust]` using Python 3.10 or newer. Default acquisition and indexing
are offline. Manuscripts cannot request an endpoint, key, image, trust root or
weaker acceptance policy. Review is never needed to ingest/index a manuscript.

## Offline recipe

```sh
python -m pip install '.[paper,trust]'
proofmap paper ci tests/fixtures/papers/train/shifted_square.tex --out .work/paper --store .work/paper-store
proofmap paper assess .work/paper
proofmap paper resume tests/fixtures/papers/train/shifted_square.tex --out .work/resumed --store .work/paper-store
proofmap paper preflight
```

Choose any manuscript using the [bounded grammar](PAPER_FORMAL_PROFILE.md); no
prewritten map JSON is needed. Without an external execution profile the run
indexes and formalizes supported assertions, but records formal checking NOT_RUN.
Adding `--require-formal` makes missing infrastructure UNAVAILABLE with exit 3.
`--require-formal` requires complete coverage of discovered theorem-like claims;
an unsupported assertion is never counted as a verified obligation.

## Prepare the isolated profile separately

On a Linux Docker host, run the repository preparation script:

```sh
python scripts/provision_lean_profile.py --out .work/lean-profile.json
proofmap paper preflight --execution-profile .work/lean-profile.json
proofmap paper ci tests/fixtures/papers/train/shifted_square.tex --out .work/checked --store .work/paper-store --execution-profile .work/lean-profile.json --require-formal
```

Preparation acquires checksum-verified official Lean 4.30.0 material and constructs
a locally digest-pinned worker. The profile records the actual compiler, libraries,
checker and platform. Verification never silently installs tools or uses host Lean.
An unsigned successful execution is inspectable but supplies no trusted evidence.

## Explicit execution and reviewer authority

The operator separately configures a version 2 external trust JSON with keys
containing `id`, base64 raw Ed25519 `public_key`, `roles`, exact `subjects`, exact
profile digests in `profiles`, `revoked`, `not_before` and `not_after` (UTC ISO times).
Supported roles are `verification-execution`, `source-fidelity-review` and
`formal-fidelity-review`; `receipt-content` cannot authorize execution. Read the
indexed assertion IDs and the profile ID to configure the intended scope. Never
place a private key or trust root in the manuscript directory.

```sh
proofmap paper ci paper.tex --out checked --store store --execution-profile profile.json --controller-key controller.key --controller-id controller --trust-store trust.json --evaluation-time 2026-09-27T00:00:00Z --require-formal
proofmap paper review-export checked --assertion ASSERTION_ID --dimension source-fidelity --author reviewer --execution-profile profile.json --out source-review.json
```

Read the source passage, interpretation and exact encoded obligation. The exported
draft has a null decision. An authorized reviewer must explicitly set it to APPROVE
or REJECT; then sign and apply it:

```sh
proofmap paper review-sign source-review.json --key reviewer.key --out source-review.dsse.json
proofmap paper review-apply checked source-review.dsse.json --store store --execution-profile profile.json --trust-store trust.json --evaluation-time 2026-09-27T00:00:00Z
```

Repeat export/review/sign/apply with `--dimension formal-fidelity` for the formal
encoding. The same person may hold both externally authorized roles, but names
alone are not authority. `supersedes` explicitly names an earlier review record;
unresolved conflicting decisions prevent acceptance.

```sh
proofmap paper assess checked --store store --execution-profile profile.json --trust-store trust.json --evaluation-time 2026-09-27T00:00:00Z --out current-assessment.json
proofmap paper diff checked revised --out revision-diff.json
```

Add `--report-out current-review` to `assess` or authenticated `review-apply` for
separate current JSON, Markdown, HTML and SARIF reports. Current reports include
the authenticated reviewer identities and decisions, and recompute verification
counts/status after authority changes; past compilation remains historical.
The original run remains immutable. To supply an approved author proof program, use `paper ci --candidate
candidate.lean --candidate-for ASSERTION_ID`; the exact candidate bytes join the
formalization binding and changing them invalidates the old review. The supported
programs are listed in [the execution profile](LEAN_PROFILE.md).

Assessment reads immutable events and current external authority; it never promotes
authored statuses. Freshly changed source/domain/hypothesis context has a new binding
and cannot receive an old review. Old formal results remain historical facts.
Legacy `attempt-check` remains trusted-local compatibility execution and is not the
paper pipeline's sandbox. No live model or production credentials are required by CI.
