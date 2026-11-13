# Trusted kernel and Paper CI implementation report

A later development revision completed the bounded paper-to-evidence milestone.
Its hosted tests exercised isolated Lean, separate fidelity reviews and rejection
after a source revision under ephemeral test authority. See the
[historical outcomes](PAPER_EVIDENCE_INCREMENT.md#merged-milestone-closure).

The report below describes the September 23, 2026 development baseline.
Its scope and limitations are historical. It does not qualify the current export.

## Outcome and release decision

A working development increment was implemented and verified: policy-qualified
AND/OR inference, conservative migration, hardened receipt loading, external DSSE
content authentication, a fail-closed isolated-runner interface, real source/PDF
ingestion, a one-command source-review pipeline, SQLite/CAS persistence, attributed
reviews, initial revision analysis, reports, packaged schemas and CI configuration.

**The full epic is not complete. Version remains 0.6.0, not 0.8.0a1.** In addition
to the unavailable Docker/hosted execution, there are genuine implementation gaps:
authenticated runner acceptance, complete environment capture, paper semantic/formal
checker integration, full revision invalidation/cache reuse, complete schemas and
the larger required evaluation corpus. These are not silently deferred or disguised
as environmental problems. See [requirements traceability](REQUIREMENTS_TRACEABILITY.md).

No new mathematical discovery, full-paper proof, novelty adjudication or scholarly
acceptance is claimed. The existing Agoh exact certificate and Lean factorization
were freshly reproduced; historical research artifacts were not modified.

## Repository and execution environment

- Environment for these historical observations: Windows, Python 3.12.14 and Lean 4.30.0.
- Original baseline: 48 passed, no skips, 27.12 s; statement coverage 2916/3466 = 84.13%.
- No Docker executable was available. No GitHub Actions run, remote entitlement,
  production key, live model, external review or other platform matrix result is assumed.
- No push, tag, PR, package publication, release, branch-protection modification or
  licensing change occurred. The owner's licensing decision remains unresolved.

## Gate status

| Gate | Result |
|---|---|
| G0 | Local baseline, defect investigation, regressions, threat model and ledgers implemented; CI configuration added |
| G1 | Core AND/OR and trust-binding semantics implemented/tested; richer relation/context/event-assessment semantics incomplete |
| G2 | Strict ingestion, identities, migration and status-preserving analysis implemented; uniform validation/action optimization incomplete |
| G3 | Receipt, DSSE, host Lean and browser checks pass; actual isolation unavailable locally, trusted execution attestation/environment closure incomplete |
| G4 | Supported TeX/archive/PDF inputs produce anchored IR; full scoping/bibliography/PDF assertion extraction incomplete |
| G5 | Offline pipeline/store/review/report and real optional protocol adapter work; semantic/formal checker integration and strict acceptance incomplete |
| G6 | Initial diff, stale-review rejection, tiny benchmark and wheel end-to-end pass; full dependency invalidation, independent reuse/resume and expanded goldens incomplete |

## Confirmed defects and changes

| Finding | Fix and regression evidence |
|---|---|
| F01: graph reachability treated as derivability | First-class inferences require every premise; OR alternatives evaluated separately. `test_kernel.py` checks conjunction, cycles, alternatives, contradictions, stale and untrusted evidence |
| F02: authored status and simulations implied proof | Semantic closure replaces status-weighted closure ratio; optimizer/hypothesis overlays retain original statuses. Existing hypothesis test updated for the intentional contract change |
| F03: permissive JSON/numeric input | Duplicate keys, nonfinite floats, booleans-as-numbers, invalid types and unsafe paths rejected by integrity/model boundaries. Adversarial tests in `test_trust_regressions.py` and `test_extended_boundaries.py` |
| F04: identity depended on collection insertion order | Domain-separated structured identities and canonical entity/set ordering; Hypothesis permutation tests, immutable subject/revision bindings |
| F05: reload could bypass verification semantics | Actual boolean verdict, nonboolean integer return code, scope/policy/version/axiom rules and nonempty stored receipt digest enforced on load/serialization/signing/verification |
| F06: host compiler was not isolation | Dedicated pinned, offline Linux runner and portable replay fail UNAVAILABLE without infrastructure. Legacy host APIs remain trusted-local only; actual isolation is not claimed |
| F07: explorer inline JSON/HTML injection | Inert escaped JSON, text-node DOM construction, safe CSV fields and Lean comments/namespaces. Real Chromium attack tests cover the explorer and new static paper report |
| F08–F10: missing CI/pipeline and unsupported capability assumptions | Mandatory job configuration, fail-closed aggregator, offline paper workflow, guarded optional CodeQL, build-only release; no assumed paid entitlement or hosted success |

Additional regressions reject a mixed paper bundle, a self-consistently forged review
of an indexed run, duplicate review targets, configuration-index collisions, repeated
ambiguous labels, invalid model response schemas and untrusted extra artifacts in
closure explanations. Store rebuild reproduces indexed content across configurations.

## Semantics and compatibility

`proofmap.kernel` is shared by legacy migration and paper argument maps. Foundations
and optional research assumptions are external, context-qualified choices. Parser or
model output cannot select trusted foundations. Logical hypotheses/quantifiers remain
local data; unverified scope discharge is refused. Cycles never seed closure.

Every accepted inference needs a resolved PASS artifact with matching inference/claim
subject, context, definition revision, policy and mode, and a digest explicitly trusted
by the caller. This caller API is not itself an authenticated runner service. Support
witnesses retain minimal alternative assumption/foundation sets; resource truncation
is visible. Contradictions are reported without logical explosion.

Deduction, computation, empirical support/contradiction, approximation, source/formal
fidelity, review and novelty remain separate dimensions. Paper assertions and explicit
source dependencies are AUTHOR_ASSERTED/REVIEW_REQUIRED. Several analyses truthfully
remain NOT_ASSESSED/NOT_RUN. The paper policy has no accepting inference mode.

Legacy migration retains original data, groups incoming proof-like prerequisites
conjunctively, and never promotes CORE/PROVED strings. Closure ratio is now zero for
unaccepted legacy maps; an empty denominator is not 100%. Other geometry is documented
as heuristic. Legacy CLI names remain, but uniform legacy exit codes and an explicit
trusted-local command switch are still contract gaps.

## Receipt trust and execution

Historical Verified Attempt v1 digest bytes are preserved. DSSE uses Ed25519 from
cryptography and signs exact payload bytes; verification authenticates before parsing.
External trust roots supply key role, exact subject scope and revocation. Embedded
keys cannot authorize themselves. Only receipt-content authentication is implemented;
execution provenance and mathematical acceptance explicitly remain NOT_ESTABLISHED.

Replay takes a caller-provided artifact root, relative manifest and pinned image.
Historical absolute paths are inert. It checks candidate/map/wrapper bindings and
runs a snapshot of explicitly listed files, recording parent event, image, actual
version and executable-hash output. Complete transitive import capture, validated
environment manifests and trusted-runner signing/acceptance are unfinished.

Runner controls include no pulls/network, nonroot UID, read-only root/source, dropped
capabilities, no-new-privileges, no mounted socket/secrets, bounded tmpfs, memory/CPU/PID
limits, combined output cap and bounded execution. Timeout attempts to kill the whole
container; failed cleanup returns ERROR. Controller unit tests are not isolation proof.
No TeX engine/build hooks run. The Linux security test is required by CI but skipped
locally because Docker is unavailable. Dedicated Lean/TeX profiles need more work.

Fresh trusted-host Lean checks, not isolated execution claims:

- Version 4.30.0, compiler commit `d024af099ca4bf2c86f649261ebf59565dc8c622`.
- Natural-number reflexivity: VERIFIED encoding; no axioms.
- Agoh factorization: VERIFIED encoding; `Classical.choice`, `Quot.sound`, `propext`.
- Exact integer certificate matched the unchanged repository certificate.

## Source-first pipeline and a reproducible example

From the repository root, after installing `.[test,paper,trust,dev]` and types-jsonschema:

```powershell
.venv\Scripts\python.exe -m proofmap.cli paper ci tests/fixtures/papers/train/basic.tex --extractor none --out .work/paper-ci-example --store .work/paper-ci-store
```

This command ran with exit 0 and produced two authored assertions and one explicit
author dependency, **zero accepted/verified claims**, formal proof NOT_RUN, fidelity
NOT_REVIEWED and scholarly acceptance NOT_ASSESSED. Exit 0 means pipeline conformance.
Output location: `.work/paper-ci-example/`, including `report.html`, `report.md`,
`results.sarif`, input manifest, IR, assertions, symbols, argument map, extraction
events, findings, assessment and a component-digest-bound run manifest. The default
store is `.paper-store`; this example uses an explicit isolated scratch store.
Scratch outputs are ignored by git and not release artifacts.

Supported acquisition is local TeX file/directory, bounded ZIP/tar, or PDF. There is
no implicit URL fetch. Paths, links, ambiguity, case collisions and size budgets are
checked. TeX parsing uses actual **pylatexenc 2.11** syntax nodes with byte-accurate
anchors, includes, labels/references, basic theorem/proof/equation handling and macro
provenance. It does not execute or fully expand TeX. Full macro scope, local BibTeX,
quantifier semantics and difficult proof associations remain unresolved.

The PDF fallback is actual **pypdf 6.19.0**, not a placeholder. It provides reconstructed
page text, original PDF/excerpt hashes and explicit missing boxes/OCR. Image-only pages
produce NEEDS_OCR; no source offsets or successful theorem extraction are invented.
The born-digital example was run with `--parser pypdf` into `.work/pdf-ci-example/`
(exit 0, PARTIAL extraction, zero extracted assertions, unknown verified fraction).
Both original PDF fixtures were generated with reportlab, rendered with Poppler and
visually inspected under the PDF skill workflow. They are tests, not submitted papers.

The optional Ollama `/api/chat` adapter performs real requests to an explicitly selected
endpoint/model. Local fake-HTTP protocol and offline replay tests ran; no live model
was configured or invoked. Schema-bound suggestions cannot create source ranges,
unknown IDs, commands or proof status. Raw requests/responses, hashes and available
usage are retained; missing model version/usage stays unknown. Suggestions are not yet
integrated into richer prose/implicit-dependency analysis. Confidential source is sent
only when configured mode is explicitly selected; mandatory PR CI remains offline.

Exact checking is a bounded AST-only rational polynomial language Q[x], never eval/exec.
An explicitly encoded false equality is a candidate contradiction, not a blocking
refutation of the paper: fidelity and domain correspondence require review. Required
formal checking currently returns UNAVAILABLE/exit 3, not a false PASS.

## Store, reviews and revision handling

SQLite foreign keys/transactions index immutable content-addressed objects and runs.
Ingest is automatic; list/inspect/rebuild work offline. Entities are analysis/run-scoped,
preventing configuration or repeated-model-run collisions. Duplicate run IDs cannot replace immutable bytes.
Review apply compares against the indexed run and exact revision/analysis/assertion
bindings. Repeated identical reviews are idempotent. A reviewer name is attribution,
not authenticated identity. Only source-fidelity review is presently supported; a
missing formalization cannot receive formal acceptance.

Revision diff matches unique labels, flags source reanchoring/statement changes and
propagates explicit dependencies. New source/config/policy/code invalidates review
reuse. Full macro/hypothesis/unlabelled definition invalidation and safe independent
cache reuse remain incomplete. There is no unsupported automatic reuse claim.

## Verification record

Commands below were actually run; local Python is `.venv/Scripts/python.exe`.
For real verification, PROOFMAP_LEAN was set to the direct compiler above and
PROOFMAP_BROWSER_TEST=1. No provider credentials were needed.

| Command / check | Observed result |
|---|---|
| `python -m pytest -q -p no:cacheprovider --junitxml=.work-junit.xml --cov=proofmap --cov-branch --cov-fail-under=85 --cov-report=term --cov-report=json:.work-coverage.json` | Exit 0; **182 passed, 1 skipped, 67.08 s**. Only actual Docker isolation skipped |
| `python scripts/check_critical_coverage.py .work-coverage.json` | Exit 0; all five required module identities present and >=90% combined coverage |
| `python -m ruff check proofmap tests` | Exit 0 |
| `python -m ruff format --check proofmap tests` | Exit 0; 59 files formatted |
| `python scripts/check_types.py` | Exit 0; strict mypy on 15 new modules |
| `python scripts/verify_real.py` | Exit 0; fresh reflexivity/Agoh Lean checks and exact certificate reproduction |
| `.work/actionlint/actionlint.exe` (1.7.12) | Exit 0 over added workflows; downloaded binary checksum verified against official release |
| `python scripts/workflow_security.py` | Exit 0; a policy scan, not a comprehensive security audit |
| `python -m pip_audit --format json --output .work-audit.json` | Exit 0, no known vulnerabilities after updating the local old pip to 26.2.1 |
| `python -m proofmap.cli paper ci ...` (TeX and PDF examples above) | Exit 0; real parsers, offline report and automatic index |
| `python -m proofmap.cli paper benchmark --corpus tests/fixtures/papers --out .work-benchmark.json` | Exit 0; two original labeled fixtures |
| `python -m build` / `python -m twine check dist/*` | Exit 0; wheel and sdist built; metadata passed |
| `python scripts/wheel_smoke.py` | Exit 0 after correcting a test argument-order bug; fresh environment away from checkout, core schema/CLI, optional dependencies, paper CI/list/assess and packaged kernel schema |
| `git diff --check` | Exit 0; research/agoh_2026 remains unchanged |

Coverage is **86.93% combined**: 4714/5213 statements = **90.43%** and
1346/1758 branches = **76.56%**. There are zero excluded lines. Combined percentages
are not represented as standalone branch coverage. Critical combined values:
integrity 90.34%, kernel 95.70%, replay 95.51%, runner 96.48%, trust 98.02%.
The existing receipt module remains 79% combined and the parser 75%; further coverage
and adversarial testing are warranted even though current numeric gates pass.

An additional local discovery-disabled diagnostic (not a real Linux/matrix run)
passed 178 tests with five explicitly unavailable Lean/browser/Docker skips, 86.40%
combined coverage and the critical gate. The initial diagnostic harness preimported
modules before coverage and overrode explicit test doubles, causing misleading
failures; it was corrected, not used as product evidence. Actual full-run evidence
above retains real Lean and browser execution.

Benchmark scope: one train and one heldout manuscript, three labeled assertions
(3/3), one explicit dependency (1/1), two proof associations (2/2), and 21/21 checked
anchors. Empty dependency denominators are null. Fidelity agreement/finding precision
have zero labeled samples and null metrics. This tiny corpus is not evidence of
general mathematical comprehension or population accuracy. The prescribed complete
golden corpus and all evaluation dimensions remain unfinished.

## CI, packaging and next increment

Added workflows: ci.yml, paper-ci.yml, codeql.yml and release.yml, plus Dependabot,
CODEOWNERS and a PR template. The required-status aggregator rejects missing, skipped,
cancelled or failed mandatory jobs. Ubuntu Python 3.10–3.14 and Windows 3.12/3.14 are
configured; only local Windows 3.12 results are observed. Real Lean, real browser,
actual sandbox, schema/property, package, audit and workflow jobs are mandatory.

Manuscript CI installs the validator from the trusted base and treats submission
checkout as data only. The first PR must bootstrap a base containing the validator.
No live-model secrets or untrusted build hooks execute. Optional CodeQL requires owner
enablement/entitlement; local SARIF does not imply GitHub ingestion. Release workflow
is build-only, without publish/tag/production signing. Branch settings are documented,
not changed. A solo maintainer is warned against impossible external-approval rules.

The next concrete increment is the missing execution-to-acceptance boundary: finish
the environment manifest, dedicated isolated Lean runner/profile and trusted-runner
event binding; then execute the real Linux isolation/replay tests on a prepared host.
Continue with paper formal/semantic checker integration, full definition/hypothesis
invalidation and independent cache reuse, complete stage schemas and expanded goldens.
Only after those requirements and hosted gates pass should the alpha version advance.
