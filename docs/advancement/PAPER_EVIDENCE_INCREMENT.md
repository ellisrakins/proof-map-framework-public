# Paper-to-evidence integration increment

The bounded paper-to-evidence integration milestone is complete. The full
0.8.0a1 alpha remains incomplete, and package version remains 0.6.0. The inherited
[traceability ledger](REQUIREMENTS_TRACEABILITY.md)
continues to describe unfinished broader requirements.

## Merged milestone closure

The bounded integration milestone passed its historical 19-job hosted gate,
including isolated formal execution. These results describe that development
revision. This public source requires independent qualification.

The main-run outcome vector is **1 ingested, 1 formalized, 1 verified, 0 reviewed,
0 accepted** before fidelity review, and **1, 1, 1, 1, 1** after both fidelity
reviews. After the source-domain revision it is **1, 0, 0, 0, 0**, with one prior
binding invalidated. These are accepted-under-policy test results marked
`EPHEMERAL_TEST_AUTHORITY_ONLY`; they do not establish production approval,
scholarly acceptance or general mathematical comprehension. The original PR and
local observations below remain separate, dated evidence.

The follow-up branch `codex/paper-evidence-completion` addresses atomic extraction
groups containing a theorem, its owned math and proof, and exported replay-event
list round-trips while preserving legacy and aggregate compatibility.

## Completion follow-up validation

The implementation closed two audited integration gaps: splitting a theorem
from its parser-owned math/proof
at a request boundary, and refusing the pipeline's own exported replay-event list.
Regressions reproduced both failures before their fixes. Oversized complete
groups now produce explicit resource findings while independent groups continue.
Replay validates revision, configuration, request identity, response bytes and
event count for exported lists, document records and legacy single events.
Invalid inputs produce a persisted extraction error, and model output remains
candidate interpretation without proof authority.

Fresh Windows/Python 3.12.14 acceptance: **370 passed, 1 skipped in 554.57s**.
The skip is the actual Linux Docker isolation test, unavailable on this host.
Real host Lean and Chromium regressions ran. Coverage, including parser workers,
is **6,122/6,734 statements (90.91%)**, **1,903/2,412 branch destinations
(78.90%)**, or **87.74% combined** using the same formula and unchanged 85% gate
documented below. All five critical modules remain above 90% combined coverage.

The full command used the local acceptance recipe below with
`COVERAGE_FILE=.work/.coverage-paper-completion`, coverage output
`.work-paper-completion-coverage.json`, and JUnit output
`.work-paper-completion-junit.xml`. Ruff lint/format (87 files), strict typing
(30 files), Actionlint, workflow security, wheel/sdist build, Twine metadata and
installed-wheel smoke all exited 0. Independent code review found no actionable
issues, and its focused extraction/replay suite passed 31 tests.

The fresh 13-manuscript benchmark retained **338/338 validated anchors**, **285/285
labeled roles**, two explicit dependencies, and **10 supported formalizations/14
theorem-like claims**. Its verification and fidelity stages remain unexecuted;
these counts are extraction/translation measurements, not verification results.

## Baseline and authority

The historical baseline and development increment were tested separately.
The changes included parser/extractor/translator integration, typed schemas,
executor and evidence adapters, review/store/CLI/report changes, an expanded
regression corpus, packaging constraints and a mandatory workflow.

Initial Windows/Python 3.12.14 suite: 182 passed, 4 failed, 3 skipped; 86.96%
combined statement/branch coverage. All four failures came from resolving Lean
through the sandbox's unconfigured elan shim. Selecting the already installed
direct Lean 4.30.0 compiler made all 28 affected-module tests pass. Baseline lint,
format and strict typing passed. These observations supersede neither the dated
September 23 report nor its historical results.

## Implemented boundary

The installed package parses and indexes source automatically. Typed roles,
bounded model chunks and candidate dependency groups enrich the source graph.
The bounded integer-polynomial grammar consumes an entire source statement,
records expression trees and exact source spans, and constructs its Lean target
at runtime. Definitions, examples and remarks remain separate coverage roles.
Unresolved macros and hypotheses conservatively block automatic formalization.

An external profile selects the pinned Lean 4.30.0/Std worker. Network-enabled
acquisition is a separate preparation operation; evaluation performs no downloads.
The offline nonroot container validates compiler/library/checker material, checks
the generated declaration and independently reconstructs it in a second fresh
Lean process using an approved tactic. No submitted compiled artifact is loaded.
This assurance covers restricted generated source and the admitted short proof
programs; it does not claim safe verification of arbitrary malicious Lean code.

The controller constructs execution events and keeps private signing keys outside
the worker. DSSE roles distinguish receipt content, verification execution,
source fidelity and formal fidelity. External authority binds identities to exact
subjects/profiles and explicit validity intervals. A shared adapter checks signed
outputs and subject/material identities before supplying evidence to the kernel.
Source assertions remain AUTHOR_ASSERTED. Mathematical acceptance is a separate
derived assessment requiring current execution authority and both fidelity reviews.
Name-only historical reviews are retained as unauthenticated attribution.

SQLite/CAS persists immutable runs, stage records, bindings, execution events and
audit decisions. Parsing and completed extraction chunks are committed atomically
and can resume after an interruption. Cache bytes and schemas are checked; a cache
namespace never supplies execution trust. Assessment always rechecks current
authority and revocation. Changed source revisions invalidate every previous
source/formal link until reviewed anew; this is conservative revision invalidation,
not fine-grained semantic reuse.

## Requirement and test mapping

| Boundary | Implementation | Regression evidence |
|---|---|---|
| Versioned typed records / offline schemas | evidence_records, paper_stages, packaged JSON schemas | test_execution, test_paper_store_stages |
| Restricted source-to-formal translation | formalize, paper_sources | test_paper_fragment |
| Chunking, exported replay and candidate graph | extractor, paper.assertion_layer / overlay | test_extraction_chunks, test_paper_replay_cli, test_paper_evidence_pipeline |
| Fresh isolated execution / replay | execution, lean_worker, runner, replay | test_execution, test_runner; mandatory paper-e2e-isolated job |
| Scoped DSSE, adapter, fidelity | trust, evidence_adapter, paper_evidence | test_execution, test_paper_evidence_pipeline |
| Immutable storage / resume | paper_store, paper_stages | test_paper_store_stages, test_paper_integrity |
| Revision safety | paper.diff, exact binding IDs | test_paper_fragment, test_paper_evidence_pipeline |
| Source/report safety | PDF locator reconstruction, paper_reports, escaped reports | test_paper_fragment, test_browser_security, UTF-8/CRLF SARIF test |
| Installed package / workflow | wheel_smoke, paper_e2e_isolated, ci-required | package smoke and workflow regression checks |

Simulated workers test contracts only. The mandatory integrated job fails if
Docker, the image or Lean is missing. The measured historical hosted outcomes
are recorded below and do not qualify a different build.

## Observed hosted outcomes

The historical development integration run reported 19 successful jobs, including
the seven Python/OS combinations and the isolated integration. Its diagnostics
reported the following test outcomes:

| Stage | Ingested | Formalized | Verified | Reviewed | Accepted |
|---|---:|---:|---:|---:|---:|
| Before fidelity reviews | 1 | 1 | 1 | 0 | 0 |
| After both fidelity reviews | 1 | 1 | 1 | 1 | 1 |
| After source domain revision | 1 | 0 | 0 | 0 | 0 |

Lean 4.30.0/Std ran in the acquired Linux/amd64 container; compilation and the
independent fresh-process check passed. Fresh isolated replay was VERIFIED.
One validated stage was reused, and the domain revision invalidated one binding.
Revoked authority, wrong-role signatures, tampering, stale review and replay-binding
mismatch were rejected. Authentication is explicitly
`EPHEMERAL_TEST_AUTHORITY_ONLY`: the accepted record tests the policy contract,
not production approval or scholarly endorsement.

A separate installed-validator, data-only check passed for one paper; the
historical no-submission job returned NOT_APPLICABLE. Neither result establishes
semantic execution on manuscripts.

## Observed local outcomes

The offline `shifted_square.tex` demonstration produced **1 ingested theorem,
1 supported formalization, 0 verified, 0 reviewed and 0 accepted claims**.
Its ordinary indexing command exited 0; the same input with `--require-formal`
exited 3 with an explicit unavailable capability. No execution event or human
approval was fabricated. Resuming the identical input reused one validated parsing
stage. Changing the quantified domain from integers to rationals invalidated the
one historical source binding and left the revised claim unaccepted. This is
source-link invalidation; there was no previously accepted proof in this local run.

An additional **actual installed-wheel data-only check passed** in a fresh venv,
using `python -I` from a separate committed manuscript checkout containing a
malicious shadow `proofmap` package and a poisoned `PYTHONPATH`. Imports resolved
to the installed package. The trusted copied corpus script
reported PASS for one paper: ingested 1, formalized 1, verified 0, reviewed 0,
accepted 0, execution events 0. No Docker/profile execution was attempted by this
separate check. Bounded local records are under
`.work/paper-evidence/data-only-local`.

Actual host Lean 4.30.0 checked ten source-derived obligations: nine compiled with
the allowed axioms and the false identity was rejected. These are host compatibility
results, separate from the isolated evidence chain. Historical Agoh arithmetic and
Lean factorization were reproduced through `scripts/verify_real.py`; historical
research files were not modified.

The expanded benchmark has 13 original/regression manuscripts, including six new
held-out manuscripts across different formula/scope families. It reports 288
authored assertions, 14 theorem-like claims and 10 supported formalizations.
All 338 checked anchors validate; roles match all 285 labeled assertions and the
two labeled explicit dependencies are found. Candidate-dependency precision/recall
is unknown because this benchmark has zero labeled model outputs. It performs no
formal execution and has zero fidelity decisions: verified obligations are 0/10,
not a claim that all ten statements are true. Fidelity agreement and other
unmeasured population-quality statistics remain null. The long-input fixture
dominates the role count; these small corpus results do not establish general
mathematical comprehension.

The required isolated driver was also invoked with a missing profile and returned
failure as intended. Launcher errors use `launcher-failure.json`; worker failures
retain their separate `failure.json`. That fail-closed diagnostic is not a substitute
for running the full integration on Linux Docker.

## Reproducible validation commands

Final local checkpoint on the implementation commit: **348 passed, 1 skipped**
in 379.16 seconds. The single skip is
`tests/test_runner.py::test_real_linux_isolation_and_limits`, which requires an
acquired image and Linux Docker. Actual Chromium and explicit host Lean tests ran.
The final focused storage/review/driver/workflow run also passed all 62 tests.

Coverage includes bounded parser subprocesses: 6,049/6,668 statements (90.72%)
and 1,857/2,372 branch destinations (78.29%), for **87.46% combined coverage**,
calculated as `(covered statements + covered branches) / (statements + branches)`.
The unchanged 85% gate passes. Existing per-module 90% combined gates pass:
integrity 91.23%, kernel 95.70%, trust 99.15%, runner 96.48%, replay 95.74%.
These coverage percentages measure executed code, not proof correctness.

| Final check | Observed result |
|---|---|
| Ruff lint / format | PASS; 86 files formatted |
| Strict mypy | PASS; 30 source files |
| Actionlint / workflow security policy | PASS / PASS |
| Wheel and sdist / Twine metadata | Built successfully / both PASS |
| Fresh environment installed-wheel smoke | PASS, away from source checkout |
| Trusted validator / hostile data-only submission | PASS; both actual Git SHAs recorded, installed import retained |
| Existing arithmetic / host Lean verification driver | PASS, Agoh factorization VERIFIED |
| Dependency advisory scan | Exit 0; no known vulnerabilities in 73 audited dependencies |
| Staged and unstaged whitespace checks | PASS |

Regression-first checks reproduced the audit payload mismatch and manual-dispatch
guard failures before their fixes. A final report regression reproduced missing
review identities; current reports now show exact authenticated review decisions
and update verification status and fraction after revocation. Original run reports
and past compilation facts remain immutable. A no-isolation build shortcut failed
because this development venv lacks setuptools; the standard isolated build
acquired its declared temporary backend and passed. This is a resolved local setup
failure, separate from the subsequently successful hosted Docker acceptance job.

Run from the repository with the declared extras installed. The local interpreter
was `.venv/Scripts/python.exe` on Windows/Python 3.12.14. `PROOFMAP_LEAN` selected
the already installed direct Lean 4.30.0 executable, and `PROOFMAP_BROWSER_TEST=1`
enabled actual Chromium regressions. Neither enables isolated paper execution.

```powershell
$env:PROOFMAP_LEAN = (Get-Command lean -CommandType Application).Source
$env:PROOFMAP_BROWSER_TEST='1'
$env:COVERAGE_FILE='.work/.coverage-paper-final'
.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider --cov=proofmap --cov-branch --cov-fail-under=85 --cov-report=json:.work-paper-final-coverage.json --junitxml=.work-paper-final-junit.xml
.\.venv\Scripts\python.exe scripts/check_critical_coverage.py .work-paper-final-coverage.json
.\.venv\Scripts\python.exe scripts/check_types.py
.\.venv\Scripts\python.exe scripts/workflow_security.py
.\.work\actionlint\actionlint.exe
.\.venv\Scripts\python.exe -m build
.\.venv\Scripts\python.exe -m twine check dist/*
.\.venv\Scripts\python.exe scripts/wheel_smoke.py
.\.venv\Scripts\python.exe scripts/verify_real.py
.\.venv\Scripts\python.exe -m pip_audit --format json --output .work-paper-dependency-audit.json
.\.venv\Scripts\python.exe -m proofmap.cli paper benchmark --corpus tests/fixtures/papers --out .work-paper-benchmark.json
```

Ruff check and format check covered `proofmap`, `tests`, and the CI, corpus,
isolated-driver, provisioning, workflow-policy, typing and wheel-smoke scripts
listed explicitly in `.github/workflows/ci.yml`. Strict typing covers 30 modules
and scripts. The installed-wheel smoke executes away from the checkout and includes
packaged schemas, source-derived translation, explicit unavailable formal checking,
and validated same-revision resume.

The local dependency advisory scan found no known vulnerabilities among 73 audited
dependencies. The local `proof-map-boundary-analysis` package was the one unaudited
entry among 74 records because it is not published on PyPI. This is an advisory
database result, not an audit of the package's own implementation.

## Remaining execution gates

At this checkpoint the Windows environment lacked the supported Linux container.
Historical hosted integration and replay results apply to their original builds only.
Live Ollama and production review identities were not configured. Model
protocol/replay and review-authority contracts have tests; test signatures are
not production approvals.

## Later work

Full PDF theorem/proof semantics and OCR; arbitrary mathematical prose and proof
search; general Lean projects/metaprogramming or Mathlib; macro scope equivalence;
independent cross-revision proof reuse; production identities and scholarly review;
the remaining full-alpha gates in the inherited ledger. No novelty, priority,
publication or universal-truth claim follows from an accepted-under-policy record.

See [the executable workflow](../PAPER_EVIDENCE.md) for setup and commands.
