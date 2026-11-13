# Requirements traceability

## Active alpha candidate contract - 2026-10-02 UTC

The machine-readable [acceptance manifest](../../acceptance/paper_ci_alpha.json)
is the current requirement/test/evidence ledger. Its
[mandatory inventory](../../acceptance/mandatory_requirements.json) preserves
inherited scope and original section references. See
[ALPHA_ACCEPTANCE.md](../ALPHA_ACCEPTANCE.md) for source-bound execution evidence,
required profiles, installed-distribution scenarios and the readiness command.
A documentation row or focused passing test cannot itself close a mandatory row.

Earlier increments added grouped extraction, exported replay and lexical scopes.
Their qualification applies only to the earlier sources. The rows below describe
capabilities and their limits; newly published sources require fresh evidence.

| Current capability | Implementation and review entry points | Qualification boundary |
|---|---|---|
| Uniform contracts and independent assessment dimensions | `paper_records.py`, `evidence_records.py`, packaged schemas | Strict records do not authenticate their author or prove their contents |
| Source scopes, context and explicit author structure | `paper_sources.py`, `source_semantics.py`, [source guide](../PAPER_SOURCE_SCOPES.md) | Local bibliography/proof links, typed contexts and AND/OR groups remain author assertions |
| Anchored semantic candidates and advisory fidelity | `extractor.py`, `semantic_candidates.py` | Configured provider/replay is explicit; unconfigured fidelity is unavailable; model agreement is not a human review |
| Restricted conditional source formalization | `formalize.py`, [formal profile](../PAPER_FORMAL_PROFILE.md) | Supported grammar only; generated obligations still require real execution and separate fidelity decisions |
| Evidence-action planning | `paper_actions.py` | Actual authority is evaluated only with explicit external inputs; simulations remain hypothetical |
| Dependency-aware revision reuse | `paper_revision.py`, `paper_stages.py`, `paper_store.py` | Recompute changed dependencies and current bindings; reauthenticate historical execution; never inherit acceptance |
| Immutable interpretation and offline review | `paper_overrides.py`, `paper_reports.py`, `paper_cli.py`, `tests/test_paper_review_workflow.py` | Preserve raw IR/events; rebuild interpreted assertions/map/reports; clear old execution and review authority |
| Original corpus and measured evaluation | `tests/fixtures/papers`, `benchmark.py`, `benchmark_scenarios.py` | Labelled parsing/model/revision/review measures stay distinct; unknown measurements stay null |
| Installed distribution scenarios and gate | `scripts/paper_alpha_offline.py`, `scripts/paper_e2e_isolated.py`, `scripts/check_alpha_acceptance.py` | Final source/package identities and required environment profiles must match; source-mode checks do not qualify installed mode |

This table describes candidate implementation paths, not final success. The
manifest retains the exact requirement IDs, selectors, profiles and unmet evidence
conditions. Broader unrestricted TeX semantics, OCR, universal proving and
production credentials are outside the documented bounded software contract;
their absence must not be substituted for a missing mandatory bounded feature.

The bounded implementation is packaged as candidate `0.8.0a1`. Its execution
records determine `software_alpha_validation` for the exact source and versioned
distribution. `package_release_ready` is true only when its acceptance artifact is
`READY` and required `alpha-readiness` and `ci-required` checks succeed. The active
ledger retains every mandatory implementation and qualification obligation; this
summary neither substitutes focused tests for required profiles nor asserts a
hosted result. Production authority and package-index publication are
`not_requested`; scholarly acceptance remains `NOT_ASSESSED`.

## Preserved update - 2026-09-27 UTC

A historical paper-to-evidence increment passed its bounded integration milestone,
including isolated Lean, authenticated execution, fidelity reviews and rejection
after source revision under ephemeral test authority. General formalization,
PDF semantics and other broader alpha requirements were outside that milestone.

## Historical full-alpha requirement snapshot

Section numbers below refer to the original development requirements. This is partial implementation, not a
declaration that every required gate reached completion. "Incomplete" is an
implementation gap, not a fabricated environment blocker or authorized deferral.

| Epic requirement | Implementation / evidence | Status or precise gap |
|---|---|---|
| 3.1 baseline, inventory, branch, old requirements | BASELINE_AUDIT, this ledger, test_trust_regressions | Implemented locally; original 48 tests passed |
| 3.1 threat model and scientific boundaries | ARCHITECTURE_AND_THREAT_MODEL, focused guides | Implemented documentation, not security certification |
| 3.2 early CI | .github/workflows/ci.yml | Implemented; no hosted result observed |
| 4.1 shared claims, contexts, inference, evidence, assessments | kernel.py, test_kernel | Core implemented; full event persistence and relation-specific contracts incomplete |
| 4.2 AND/OR fixed point, no cyclic seeding | kernel.closure, property tests | Implemented and tested |
| 4.2 subject/context/policy/evidence matching | inference_digest/closure tests | Implemented; caller-selected digest trust is an API boundary, not deployed runner attestation |
| 4.3 hypotheses, scope, explicit foundations | Claim fields and scope tests | Conservative refusal implemented; rich scope discharge incomplete |
| 4.4 policies, independent dimensions | POLICIES, Assessment | Selectors implemented; several dimensions NOT_ASSESSED |
| 4.5 support alternatives, assumptions, contradictions | ClosureResult, test_kernel | Bounded witnesses implemented; some missing/stale diagnostic categories combined |
| 5.1 strict parsing and semantic validation | integrity/model/kernel/schema, adversarial tests | Core boundaries implemented; uniform structured issues across all legacy fields incomplete |
| 5.2 identity and insertion invariance | integrity/kernel, test_extended_boundaries | Implemented; no mathematical-equivalence claim |
| 5.2 complete analysis/environment identities | paper code/parser/config digest, replay | Incomplete transitive environment/formal dependency capture |
| 5.3 conservative idempotent migration | migrate, regression/property tests | Implemented; retained legacy provenance, no accepted foundation |
| 5.4 metrics and immutable scenarios | metrics/optimizer/hypothesis | Status safety implemented; full evidence-action optimizer incomplete |
| 6.1 centralized receipt semantics | attempts/trust, regression/trust tests | Historical contract hardened; future execution-attestation contract incomplete |
| 6.2 exact-byte DSSE and external roles/scopes/revocation | trust, test_trust | Implemented receipt-content role only; never claims trusted execution |
| 6.2 production execution signatures/key lifecycle | RECEIPT_TRUST.md | No private keys committed; trusted-runner signing not implemented |
| 6.3 portable replay, inert historical paths, parent event | replay/trust_cli, test_replay | Bindings/interface implemented; actual isolated Lean replay blocked by absent Docker/image |
| 6.3 complete resolved imports/compiler/environment | replay version/hash output | Incomplete; image/snapshot is not a fully validated dependency manifest |
| 6.4 pinned offline nonroot bounded worker | runner, controller tests | Implemented; mocks are explicitly not isolation evidence |
| 6.4 actual isolation controls | test_runner, sandbox-security job | Blocked locally: Docker unavailable; hosted test configured but not run |
| 6.4 separate TeX/Lean profiles and host compatibility | no TeX execution; legacy host Lean retained | Incomplete profiles/explicit host-mode CLI; no silent paper-pipeline host fallback |
| 6.5 legacy HTML injection | surface_visualize, real Chromium tests | Implemented and actually tested |
| 6.5 report/CSV/Lean injection boundaries | paper, CSV helpers, lean_export, browser tests | Tested surfaces implemented; exhaustive Markdown/URL/export coverage incomplete |
| 7.1 stage schemas, provenance, resume/cache | manifests and component hashes | Partial; full per-stage schemas and interruption resume incomplete |
| 7.2 local bounded input contracts | paper_sources.acquire, source tests | TeX/PDF/directory/ZIP/tar, ambiguity, portable paths, collision/link rejection implemented |
| 7.3 real syntax parser, includes, labels/refs/proofs/math/macros | pylatexenc 2.11, anchored IR | Working subset; full macro scoping, BibTeX and complex proof associations incomplete |
| 7.4 real offline PDF fallback | pypdf 6.19.0, original rendered fixtures | Page text and NEEDS_OCR implemented; no OCR/boxes/PDF theorem-extraction claim |
| 7.5 locators and provenance | locator validation, schemas, anchor benchmark | Exact TeX checks implemented; independent PDF page-text re-extraction validation incomplete |
| 8.1 source assertions versus accepted evidence | assertion_layer and assessments | No auto-promotion implemented; semantic hypotheses/quantifiers unresolved |
| 8.2 scoped symbols and argument structure | macro/symbol occurrences, explicit dependencies | Rich semantic scope/dependency analysis incomplete |
| 8.3 genuine optional model protocol/replay | extractor, real local HTTP protocol test | Ollama adapter implemented; no live model configured/invoked |
| 8.3 prose/implicit-reference and formalization stages | suggestions retained as extraction_events | Incomplete: no richer graph integration or bounded formalization |
| 8.4 source/citation/dependency checkers | checker contract and source findings | Partial; some analyses remain PARTIAL/NOT_RUN |
| 8.4 exact computation/counterexample | bounded Q[x] AST and label binding | Narrow exact checker implemented; unreviewed encoding is nonblocking |
| 8.4 author-required formal artifacts | formal requirement returns UNAVAILABLE, exit 3 | Fail-closed behavior implemented; paper formal stage incomplete |
| 8.5 outcome vector/denominators/exit status | paper assessment tests | Conservative vector implemented; full checker taxonomy/coverage incomplete |
| 8.6 automatic store/CAS/rebuild | paper_store, paper_integrity tests | Transactions, immutable runs, config isolation implemented; full cache/event/query tables incomplete |
| 8.7 review and acceptance | review_export/apply and immutable indexed-run check | Source-fidelity review subset implemented; authenticated mathematical acceptance bridge incomplete |
| 8.8 useful offline reports/source browser | JSON/MD/HTML/SARIF and real browser | Basic views implemented; advanced filters/navigation/graph view incomplete |
| 9.1 revision diff and invalidation | paper.diff, stale review tests | Label matching/explicit edges only; full hypothesis/macro/unlabelled change propagation and independent reuse incomplete |
| 9.2 labeled golden evaluation | 2-paper train/heldout corpus, benchmark | Tiny benchmark implemented; expanded cases, adapted Agoh paper and all requested metrics incomplete |
| 9.3 bounded processing/performance | iterative 3,000-node tests and input/closure/expression budgets | Several bounds implemented; parser worker deadlines/full scalability/resume incomplete |
| 10 CLI/resources/bundle/exits | kernel_cli/trust_cli/paper_cli/schema | Documented commands and installed resources work; full legacy harmonization/stage contracts incomplete |
| 11.1 workflow security | pinned/read-only/bounded workflows, actionlint/policy scan | Configuration implemented; not proof of complete transitive dependency pinning |
| 11.2 matrix/lint/types/tests/audit/package | ci.yml and commands in report | Local Windows 3.12 observed; Linux/other Python and hosted jobs unobserved |
| 11.3 fail-closed required status | aggregator plus tests | Missing, cancelled, skipped and non-success rejected |
| 11.4 trusted-base manuscript workflow | paper-ci.yml, paper_ci_corpus | Data-only split implemented; first-base bootstrap and manual protected-SHA path incomplete |
| 11.5 optional hosted features | capability-gated manual CodeQL, local SARIF | Entitlement not assumed; native attestations not implemented |
| 11.6 updates/build-only release/protection | .github, BRANCH_PROTECTION | Config/docs implemented; no actual server rule/release/tag/publish change |
| 12 mandatory test catalog | old and new regression suites | Large tested subset, not complete catalog; actual isolation skipped locally |
| 13 docs/release hygiene/evidence | README/spec/status/changelog/guides/report | Implemented; 0.6.0 retained because full alpha gates are not met |
| 2 explicitly deferred work | No crawler, universal solver, arbitrary TeX, autonomous whole-paper proof, hosted journal/billing | Explicitly deferred by prompt; not a reason to drop unfinished alpha work |
| License/production keys/server policy/publishing | Existing licensing and remote state preserved | Separate owner decision/authority needed; no license invented |

Historical plan (2026-09-23; superseded by the active manifest): finish authenticated execution-to-evidence integration and validate
real Linux isolation; then paper formal/semantic checkers, definition/hypothesis-aware
invalidation and independent cache reuse, broader goldens, complete stage contracts,
and hosted matrix validation. A green local suite is not the full alpha gate.
