# CI capability and trust boundaries

The current candidate is governed by the [acceptance contract](ALPHA_ACCEPTANCE.md)
and [active requirement/evidence ledger](../acceptance/paper_ci_alpha.json).
Historical development runs exercised the required job contract, isolated integration
and acceptance following independent fidelity reviews. These observations do not
qualify this source snapshot or a newly built package. Run the checks in the new
repository and retain its own commit and artifact identities.

`ci-required` explicitly requires quality, python-tests, schema-migration,
semantic-properties, verification-real, sandbox-security, paper-ci-fixtures,
paper-e2e-isolated, browser-security, package-build, dependency-audit,
workflow-security, windows-regression, and alpha-readiness. The
aggregator runs with `always()`, performs no checkout, has a fixed trusted job
list, and accepts only literal success for every result. Tests cover omitted,
unexpected, failed, cancelled, skipped and neutral results.

`alpha-readiness` consumes the other required jobs' reports and bounded artifacts
from the same checkout and run attempt. It checks source/package identity, actual
collected mandatory tests, installed scenarios, implementation gaps and the target
package version. Missing evidence, mandatory skips and stale or mixed artifacts
fail the gate. It uploads `alpha-acceptance.json` and a readable summary, without
rerunning the matrix. A producer job's success alone cannot establish readiness;
the stable `ci-required` check also requires the acceptance gate to succeed.

Python profiles: Ubuntu 3.10-3.14; Windows 3.12 and 3.14. Windows 3.12 runs
the full suite in four deterministic partitions, each with the same complete
collection inventory and current source/run/attempt identity. Every selected
test retains its actual outcome. Missing, overlapping, duplicate, interrupted,
or mixed-identity partitions fail qualification. Raw partition artifacts remain
separate from the final alpha evidence.

The mandatory `windows-regression` job checks that the four partitions cover
the full inventory exactly once, combines their measured branch-coverage data,
and applies the existing 85% overall and 90% critical-module coverage gates.
It emits one ordinary `python-windows-3.12` pytest report only with a linked
provenance artifact. Alpha readiness independently checks that artifact and
its binding to the final report. A successful subset or an average of coverage
percentages cannot establish a successful full profile. All jobs retain their
20-minute limit; the other six Python profiles retain their complete-suite
execution. Partitioning adds isolated runner setup and aggregation work in
exchange for bounded execution with headroom under Windows runtime variation.

The separate real-Lean script refuses to skip,
recreates reflexivity and Agoh receipts, and reproduces the exact certificate.
The browser job runs actual Chromium. The Docker job runs nonroot read-only,
network-denial, timeout and output-limit checks against an acquired pinned image.
Mocked process-controller tests are distinguished from that actual isolation gate.
The matrix regression driver builds and installs the candidate wheel, checks the
installed package identity and resource bytes, and runs the copied tests outside
the source checkout. Package-build separately checks wheel/sdist metadata and the
installed offline authoring/review scenarios. The final versioned artifacts need
their own qualifying run; a prior development version's results are insufficient.

`scripts/provision_lean_profile.py` acquires the official pinned Lean 4.30.0
release using the reviewed official metadata in `scripts/lean-release-lock.json`.
Preparation downloads only the pinned official archive, verifies its published
size and SHA-256, and records the lock digest and upstream release/asset identities.
The metadata provenance is a pinned snapshot, not a fresh API lookup; no token or
anonymous metadata-API quota is required. A changed upstream archive fails its
checks until a new pin is explicitly reviewed. `--host-dir` provisions the resolved compiler
for the legacy host compatibility test. Without that flag it builds a Linux
worker from the existing pinned Python base and records the actual immutable
image ID, compiler and Std/core material digests. Evaluation is offline; it
never installs missing infrastructure or falls back to host Lean.
`scripts/verify_real.py` still executes
the exact historical certificates; an empty Lake package is not treated as proof. Git
attributes preserve exact JSON/Lean/TeX artifact bytes even on CRLF-default
Windows checkouts; historical receipt hashes are never rewritten to hide drift.
Legacy CLI verification explicitly names `trusted-host` mode; its receipts cannot
replace isolated paper evidence. See [execution modes and exits](CLI_EXECUTION_BOUNDARIES.md)
for the shared success, rejection, invalid-input and infrastructure-error conventions.

Coverage gates are 85% overall combined statement/branch coverage and 90% on
each critical new integrity/kernel/trust/replay/runner module. No coverage paths
are excluded. Coverage failures must remain failures. These thresholds do not
claim exhaustive path correctness or a formal security proof.

`paper-e2e-isolated` builds the package, installs that wheel and its constrained
optional dependencies in a clean temporary environment, and executes outside
the source checkout with isolated Python import settings. The integration driver
creates an original unmapped manuscript and checks ingestion, actual isolated
Lean execution, authenticated evidence resolution through the kernel, rejection
before fidelity approval, exact acceptance after both reviews, revocation,
wrong-role signatures, payload tampering, replay bindings, fresh replay,
same-revision stage reuse, and stale review rejection after a domain revision.
It also invokes the data-only manuscript driver against a checkout containing
a hostile Python module to check that submission imports cannot replace the
installed validator. Missing wheel, runtime, image, Lean, checker, or isolation
capability is a failure with diagnostics, never an arbitrary skip.

All controller and reviewer keys in this job are ephemeral test authority held
only in controller memory. They are never worker input or uploaded artifacts.
This tests authentication contracts; it is not production identity or scholarly
endorsement. Diagnostics contain a small original fixture's bounded outcomes,
checker/environment identities and rejection reasons, with seven-day retention.
No private key or arbitrary manuscript corpus is uploaded.

`paper-ci.yml` installs the validator from the PR's trusted base, reads only
manuscript data from the other checkout, and never executes manuscript scripts,
Lean/TeX code, model calls, or PR-supplied provider settings. Platform changes are
tested separately by the main workflow. No papers yields NOT_APPLICABLE, never
"proved". Errors preserve partial artifacts and retain nonzero exit status.
With no submitted papers, the workflow reports NOT_APPLICABLE before installing
the validator, so its initial implementation PR can bootstrap the base safely.
Actual manuscript submissions still require a trusted base containing the validator.
Both checked-out Git SHAs are recorded as report artifacts. `python -I` excludes
submission-controlled Python paths. Manual dispatch is restricted to main.
Review a public validator commit and pin its full SHA in the choice, default
and equality guard in the workflow. Keep the all-zero rejection guard unchanged.
Until a public pin is set, dispatch fails before checkout. The branch used to
start a dispatch is not a validator pin.
Validator installation uses constraints from that same trusted checkout.

The software workflow runs on pull requests, pushes to `main`, and manual
dispatch, avoiding duplicate feature-push and PR matrices. `constraints-ci.txt`
pins the tested development, parser, verification and audit dependencies without
narrowing public library extras. No stored PASS verdict, compiled submission
library or signing authority is cached. SQLite/CAS stage reuse is explicitly
untrusted analysis, scoped by revision, configuration, implementation and parent
digests; current trust/revocation and fidelity are always re-evaluated.

The workflow uses reviewed Node 24 actions, pinned to these upstream revisions:

- checkout 7.0.1: `3d3c42e5aac5ba805825da76410c181273ba90b1`
- setup-python 7.0.0: `5fda3b95a4ea91299a34e894583c3862153e4b97`
- upload-artifact 7.0.1: `043fb46d1a93c77aae656e7c1c64a875d1fc6a0a`

No duplicate dependency PR was opened and no bot PR was modified or merged.
The nested-action audit found that the prior pinned Lean composite invoked
mutable `elan/master/elan-init.sh` and included conditional `actions/cache@v5`
references. That installer is removed from CI in favor of the checksum-verified
acquisition script. The three Node actions use bundled JavaScript with no
nested `uses`; setup-python can still resolve Python distributions from the
official `actions/python-versions` manifest. Its outer pin does not establish
immutability of that external distribution service.

Default tokens have read-only contents permission. Checkout credentials are not
persisted. No pull_request_target, privileged workflow_run or PR-secret provider
calls are used. Jobs are bounded and artifacts retained seven days. Model/source
text should not be uploaded for confidential manuscripts without authorization.

CodeQL is manual and capability-gated by PROOFMAP_CODEQL_ENABLED. The owner must
verify repository visibility and entitlement before enabling it. It is not a
required job and has no assumed paid entitlement. SARIF is always produced as a
downloadable local artifact; GitHub ingestion is not assumed. Native attestations
are not implemented. Local tests, workflow policy scan and dependency audit are
not represented as equivalent to CodeQL/secret scanning/attestation.

Release workflow only builds wheel/sdist, checks metadata, inventories dependencies,
produces an SBOM/checksums and uploads an **unpublished** artifact. It never tags,
pushes, signs with production keys, publishes packages, or creates GitHub releases.
Dependabot proposes grouped weekly updates with bounded PR counts; no automerge.
Release-build dependency acquisition also uses the reviewed constraints. The local
workflow policy scan checks each checkout, job timeout and artifact retention,
read-only defaults, optional entitlement guards, trusted manuscript separation and
absence of publication/server mutation commands. Actionlint and actual execution
remain separate checks; this policy scan does not certify transitive package contents.

References: [Python version lifecycle](https://devguide.python.org/versions/),
[GitHub code scanning availability](https://docs.github.com/en/code-security/concepts/code-scanning/code-scanning),
[audited prior Lean installer](https://github.com/leanprover/lean-action/blob/50fcf42d2e460296f1a34b402e990d1b24f8b596/scripts/install_elan.sh).

Build shareable packages in a fresh checkout or from a reviewed Git archive.
The manual build-only workflow uses a Git archive, excluding local manuscripts,
stores and other untracked files. Its dependency inventory records package versions
without including filesystem install URLs. CI diagnostic and manuscript-report
artifacts are separate from the source distribution: do not submit private papers
to public CI, and inspect generated reports before sharing them. The local papers/
input directory is ignored by default. To submit an intentionally public manuscript,
force-add only its explicitly reviewed files; never force-add the entire intake folder.
