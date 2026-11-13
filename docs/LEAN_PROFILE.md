# Isolated Lean/Std profile

`lean-std-int-polynomial-v1` is a bounded profile for Lean **4.30.0**, `Std`, and
explicitly quantified integer polynomial equations. The paper translator admits
a documented subset in `formalize.py`; unsupported prose and hypotheses remain
unformalized. The execution boundary independently limits the Lean terminal
alphabet, bound names, imports, statement size and proof program. Approved proof
programs are exactly `by grind`, `by rfl`, and `by omega`, with whitespace between
the two tokens. Arbitrary Lean proof terms, user tactics, modules, initializers,
plugins, Lake projects, compiled libraries and native evaluation are unsupported.

## Preparation and diagnostics

Preparation is an explicit network-enabled operation on Linux amd64/arm64 with
Docker and `tar --zstd`. It acquires the official `v4.30.0` release archive and
checks its bytes against the SHA-256 published in GitHub's release-asset API. A
missing checksum is fatal. It builds from the repository's digest-pinned Python
base, records the actual immutable image ID, hashes the resolved Lean executable
and full core/Std material tree, and emits an external profile and acquisition
manifest. It does not generate credentials.

```sh
python scripts/provision_lean_profile.py --out /tmp/lean-profile.json
proofmap paper ci tests/fixtures/papers/train/shifted_square.tex \
  --execution-profile /tmp/lean-profile.json --out /tmp/paper-result --store /tmp/paper-store --require-formal
```

Use the paper CLI's current `--help` for source/output options. The preparation
command requires the repository script; execution uses the installed package.
For the separately retained **trusted host compatibility check**, use
`--host-dir /tmp/lean-host --out /tmp/host-acquisition.json`. Its `executable`
field is a resolved compiler path, not an elan shim. Host compatibility is not
isolated execution evidence.

Verification never downloads tools or falls back to host Lean. Missing Docker,
an unacquired pinned Linux image, or an incomplete material resolution yields
an explicit infrastructure result. The mandatory isolated integration CI job
must fail when these capabilities are unavailable.

## What is checked

The controller generates the fixed declaration `proofmap_target` from the
validated obligation. It creates a read-only snapshot containing only two
generated Lean source files, the trusted worker and the profile request. The
first fresh Lean process checks the approved submitted proof program. The second
fresh process reconstructs the *same exact proposition* using trusted `grind`
and checks its axiom set. No candidate-generated `.olean` or executable is fed
to the second process. Both audits must refer to the expected declaration and
may use only `Classical.choice`, `Quot.sound`, and `propext`.

This assurance is recorded as `TRUSTED_RESTRICTED_SOURCE_KERNEL_RECHECK`. It is
two executions of the Lean kernel and trusted tactics, **not** an independent
implementation of Lean's logic or a checker for arbitrary malicious Lean
programs. It deliberately avoids claiming that token blacklisting, stdout, or
unvalidated `.olean` loading is sufficient for general Lean submissions.

The [official Lean validation guidance](https://lean-lang.org/doc/reference/latest/ValidatingProofs/)
distinguishes axiom auditing, rechecking compiled declarations, and comparison
against a trusted target. It cautions that `lean4checker` assumes structurally
valid `.olean` files. General arbitrary proof-program support would require the
stronger validated interchange/comparator path and remains later work. The
[4.30.0 release](https://lean-lang.org/doc/reference/latest/releases/v4.30.0/)
documents the available `grind` ring machinery; the provisioned mandatory test
is the executable compatibility check, and must not be replaced by a mocked
worker test.

The worker verifies actual compiler, version, library tree, checker, platform and
search path against the external profile. Evaluation retains offline network,
non-root UID, read-only mounts/root, no credentials/socket, dropped capabilities,
no-new-privileges, bounded tmpfs/processes/memory/CPU/output/wall time and container
cleanup. The image identity covers additional operating-system dependencies.
Environment completeness is relative to this profile only.

## Authentication and assessment

An optional controller-side raw Ed25519 key signs the event after the controller
validates its own worker records. Signing keys are not copied into the snapshot.
Receipt-content authentication remains its original separate role. Version 2.0
external authority stores scope each key to explicit subjects, profile digests,
roles, revocation status and a UTC validity interval. Evaluation requires an
explicit UTC time. There is no embedded self-authorizing key or implicit wildcard.

`evidence_adapter.resolve_execution` authenticates the event, reconstructs exact
candidate/wrapper/snapshot identities, checks material/output/axiom bindings,
builds the encoded formal claim and inference, and alone supplies the resulting
evidence digests to kernel closure. Signed wrong-subject, wrong-context,
wrong-profile, wrong-output and wrong-role events fail closed.

`assess_binding` re-evaluates that evidence under current authority and requires
separate authenticated source-fidelity and formal-fidelity decisions. Before
those approvals, the encoded theorem can be verified while the paper claim is
`REVIEW_REQUIRED`. Rejections and explicit supersessions persist as history.
Bindings include the paper revision, assertion content, context/definitions,
exact obligation and exact candidate bytes, so a relevant change cannot inherit
an old review. The package never silently produces affirmative human reviews.

New execution events replay through the same `execute` function using
`receipt-replay --binding ... --obligation ... --candidate ... --profile ...`.
Legacy receipt replay remains a local unsigned compatibility record and cannot
supply strict execution-role evidence.

Tests using simulated worker output exercise contracts and rejection behavior;
they are explicitly labeled and do not establish that a Lean image ran. Real
execution, test authentication, fidelity decisions and acceptance counts are
reported separately by the mandatory installed-package integration driver.
