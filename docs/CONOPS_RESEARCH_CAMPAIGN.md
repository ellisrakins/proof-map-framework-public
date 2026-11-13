# Local research campaign operations

The campaign workflow extends the qualified Paper CI Alpha. Its additive contract
is [research_campaign_conops_v1.json](../acceptance/research_campaign_conops_v1.json).
The frozen 81-row [alpha contract](../acceptance/paper_ci_alpha.json) remains a
separate required gate. `validate-conops` is the compatible legacy five-node
artifact smoke test; `validate-research-conops` exercises campaign operations.

## Roles and authority

An operator selects local sources, objectives, exact targets, profiles and budgets.
An interpretation reviewer can propose an attributed correction using the existing
paper override commands. An execution controller signs exact execution events,
with its key outside the untrusted container. Source and formal fidelity reviewers
make explicit decisions under separately supplied roles, scopes and validity
intervals. An auditor can inspect, retain and restore history. None of these roles
implies scholarly acceptance or novelty, and task completion never grants review
authority. Test authorities are visibly `EPHEMERAL_TEST_AUTHORITY_ONLY`.

## Public CLI walkthrough

Every command has `--help`. IDs below are returned by commands. No graph JSON is
required. A directory with `main.tex` is one multi-file manuscript. A collection
contains standalone TeX/PDF/archive files or child manuscript directories; a child
with multiple TeX entry-point candidates requires an explicit entry point. Symlinks,
unsupported inputs and ambiguous target labels fail closed.

```sh
proofmap campaign init --name "Polynomial pilot" --objective "Audit selected proof boundaries" --store .paper-store
proofmap campaign capabilities CAMPAIGN --execution-profile profile.json --store .paper-store
proofmap campaign ingest CAMPAIGN papers/ --extractor none --store .paper-store
proofmap campaign inspect CAMPAIGN --store .paper-store
proofmap campaign goals add CAMPAIGN --run RUN --label THEOREM_LABEL --store .paper-store
proofmap campaign goals add CAMPAIGN --question "What remains outside the integer profile?" --store .paper-store
proofmap campaign plan CAMPAIGN --formal-scope supported --out plan.json --store .paper-store
proofmap campaign policy --execution-profile profile.json --max-tasks 20 --max-wall-seconds 600 --out operations.json
proofmap campaign authorize CAMPAIGN --plan plan.json --policy operations.json --store .paper-store
proofmap campaign run CAMPAIGN --until review --max-tasks 20 --controller-config controller.json --store .paper-store
proofmap campaign tasks CAMPAIGN --store .paper-store
proofmap campaign review-packet CAMPAIGN --execution-profile profile.json --out packets --store .paper-store
proofmap campaign review-decision CAMPAIGN --run RUN --assertion CLAIM --execution-profile profile.json --dimension source-fidelity --decision APPROVE --reason "Compared each source anchor and context" --reviewer-id SOURCE_REVIEWER --key external-source-key --out source-review.json --store .paper-store
proofmap campaign review-apply CAMPAIGN --run RUN --review source-review.json --execution-profile profile.json --trust-store external-authority.json --evaluation-time UTC_TIME --store .paper-store
proofmap campaign review-decision CAMPAIGN --run RUN --assertion CLAIM --execution-profile profile.json --dimension formal-fidelity --decision APPROVE --reason "Compared domain, hypotheses and encoded statement" --reviewer-id FORMAL_REVIEWER --key external-formal-key --out formal-review.json --store .paper-store
proofmap campaign review-apply CAMPAIGN --run RUN --review formal-review.json --execution-profile profile.json --trust-store external-authority.json --evaluation-time UTC_TIME --store .paper-store
proofmap campaign assess CAMPAIGN --execution-profile profile.json --trust-store external-authority.json --evaluation-time UTC_TIME --store .paper-store
proofmap campaign ingest CAMPAIGN revisions/ --store .paper-store
proofmap campaign impact CAMPAIGN --from SNAPSHOT_A --to SNAPSHOT_B --store .paper-store
proofmap campaign goals rebind CAMPAIGN --goal GOAL --run NEW_RUN --assertion NEW_CLAIM --reason "The source-backed revision mapping identifies this claim" --store .paper-store
proofmap campaign report CAMPAIGN --out campaign-report --store .paper-store
proofmap campaign export CAMPAIGN --include-source --out dossier.zip --store .paper-store
proofmap campaign import dossier.zip --store clean-store
proofmap campaign audit CAMPAIGN --store clean-store
```

Use `REJECT` with a reason for an explicit rejection. `ABSTAIN` records a handoff
without a signed fidelity approval. Signing without `--key` produces a typed draft.
The same reviewed target is unchanged; a correction creates a new immutable paper
run through `proofmap paper override-apply`, then `campaign select CAMPAIGN --run RUN`.
Always use `paper --help` for that existing override interface.

The controller file is operator-owned and excluded from VCS/export. It contains
`profile` (a validated object or a local profile-file path), `controller_id`,
`private_key_path`, and optionally `trust_store` and `evaluation_time`. Keys never
enter the verifier snapshot. Production identities are supplied independently;
there is no bundled production authority. The prepared verifier profile is the
existing pinned offline Linux Lean/Std profile, with no host fallback or arbitrary
Lean project execution.

## Plans, scope and operation states

`supported` limits attempted work to supported discovered claims (and selected goals
when goals are present), while retaining unsupported inventory. `selected` enforces
the exact selected goal set and exposes unsupported blockers. `all` retains strict
all-discovered coverage. None changes `paper --require-formal`. Reports separately
count discovered claims, unresolved regions, supported targets, attempts, verified
statements, reviewed bindings and accepted targets. Zero eligible claims and subset
success cannot produce full-paper verification.

Plans reuse `plan_paper_actions`, remain `PLANNING_ONLY`, and confer no execution
permission. `authorize` records the operator's exact request separately. The fixed
ranking policy prioritizes prerequisites and goal relevance; unknown effort remains
null and blocker counts are not probabilities or scientific productivity metrics.

The queue records `REQUESTED`, `AUTHORIZED`, `QUEUED`, `RUNNING`, and terminal
`SUCCEEDED`, `CHECK_FAILED`, `UNAVAILABLE`, `ERROR`, `CANCELLED` or `STALE` states.
Unsupported/prerequisite work is `BLOCKED`. Review tasks remain `AWAITING_REVIEW`
until an authenticated explicit decision yields `DECISION_RECORDED` or `REJECTED`.
These are work states. A compiler rejection does not establish a paper counterexample.
The bounded runner stops at review, unsupported work, exhausted budgets or errors.
Operational handoff is valid software behavior; queue exhaustion does not solve a
research goal. Infrastructure/blocking outcomes use exit 3; invalid input uses exit 2.

`request-stage` explicitly authorizes ingestion/reparse, recorded/configured
extraction or pure analysis with operator-owned inputs. Recorded extraction is a
protocol replay. Live extraction requires opt-in disclosure plus request/token/time
budgets; neither model replies nor manuscript metadata can authorize another task.

## Persistence, leases and recovery

Campaign schema 3 adds tables to the existing SQLite/CAS store. Opening a schema
1/2 store creates a consistent SQLite backup in `backups/pre-campaign-vN-*.sqlite3`
and verifies integrity before applying additive migrations. Old CAS payloads and
subject digests remain unchanged. Rollback requires closing all connections, saving
the current database and CAS, and restoring the verified pre-upgrade database using
SQLite backup into an explicitly chosen store. The old package can read that database;
new campaign indexes are unavailable to it. No source/CAS garbage collection occurs.

Snapshots pin paper/run/source revisions, exact goal refs and operation-policy
digests. Membership changes create immutable snapshots and provenance events; the
current-head pointer is derived. A removed goal stays historical and unresolved.
Goal rebinding requires an explicit source-backed mapping event. Candidate links
retain endpoint domains/contexts; matching labels/text never merges propositions
or transmits deductive closure.

Short `BEGIN IMMEDIATE` transactions fence competing claims. No parser, model or
Lean work runs while a database write transaction is held. Default concurrency is
one. Semantic work keys exclude evaluation timestamps, while dispatch and reuse
recheck material/profile/policy applicability. Expensive execution and pure stages
can reuse completed identical work. Authentication, policy reassessment and report
refresh reuse only pending/running work; each explicit request after completion
creates a fresh evaluation against supplied external authority/time. Prerequisites
use the latest applicable evaluation, so an older success cannot bypass a later
failure. Attempts can repeat after a crash;
only the current unexpired lease/generation can attach current results. Late results,
failed attempts, budget reservations, cancellation and cleanup diagnostics remain
auditable. This is bounded at-least-once attempted delivery, not exactly-once external
effects. A possibly completed external model request is `UNKNOWN_EFFECT` and requires
reconciliation, rather than silently retrying duplicated cost. `campaign recover`
recovers expired leases within attempt limits. `campaign cancel TASK` requests worker
termination; cleanup failure remains an error. Revision/policy changes stale affected
authorization without erasing historical execution.

Non-Lean adapters run in a controller-owned Windows job or POSIX process group,
with lease heartbeats throughout startup and work. Cancellation and wall deadlines
terminate the adapter and its parser descendants within a bounded cleanup scope.
`CANCEL_REQUESTED` keeps the task running until cleanup is confirmed; cleanup
failure records `ERROR`. Controller signing keys stay outside these workers.
Source workers may retain immutable CAS/run evidence, but current campaign
membership is promoted together with the TaskResult under the controller's lease
and current-subject fence. Cancelled, stale or failed-cleanup work cannot promote
membership. Termination cannot undo an external model request already received;
its reserved requests/tokens remain conservatively charged as unknown effects.

Configured `campaign ingest` uses the same durable queue reservations across
manuscripts and repeated calls. Remaining request/token or time budget can leave
extraction queued; retained source and its status remain inspectable. Explicit
`campaign retry TASK` is limited to eligible errors/unavailability within the
attempt cap and rejects external model requests with unknown effects. A capability
report checks local key readability/format separately from external authority;
configured model endpoints are reported without sending manuscript content.

## Offline views and portable dossiers

The report's JSON, Markdown, HTML and graph ledger share one model. HTML is
script-free, escaped, CSP-constrained and navigable through source, formal target,
actions, execution and reviews. Graph nodes retain exact qualified identities and
are `PRESENTATION_ONLY`. They cannot authorize kernel closure. The timeline records
research history, not physical epochs; geometric scores are diagnostics.

Export takes a consistent SQLite read backup and hashes the reachable records,
CAS objects, sources, reports and optional qualification artifacts. The default
omits raw manuscripts and is explicitly not a self-contained replay dossier;
source excerpts in retained analysis are disclosed. `--include-source` opts into
full local retention. No external upload occurs. Import validates archive paths,
links, collisions, resource limits, schemas, digest inventory and semantic references
in a staging store before destination publication. Imported execution/review envelopes
remain history until separately supplied local authority authenticates them. Imported
active tasks become stale and require fresh authorization. Private keys,
authentication secrets, controller configuration and executable hooks are excluded.
Public key identifiers and historical lease fencing tokens remain audit data;
import never activates them as authority or usable leases.

Repeated source checks inside one public operation share pure PDF reconstruction
through a nested validation session. The key binds the actual reread source bytes,
parser version and effective limits. The session retains at most 16 PDFs and 16 MB
of reconstructed UTF-8 text, returns independent page lists, and is discarded when
the operation exits. Every CAS digest, source locator, assertion and semantic
reference is still checked. Authority, signatures, policy acceptance and evaluation
time are recomputed; no assessment verdict is cached. A separate operation starts
with a fresh session.

## Qualification and measured pilots

```sh
proofmap validate-research-conops --profile offline --out .work/conops-offline
proofmap validate-research-conops --profile isolated --execution-profile profile.json --out .work/conops-isolated
proofmap campaign-pilot --corpus tests/fixtures/campaign/realism --out .work/campaign-pilot
proofmap preserve-qualification --files qualification-files.json --identity candidate-identity.json --out .work/software-evidence.zip
proofmap inspect-dossier .work/software-evidence.zip
```

`qualification-files.json` is an operator-selected mapping from archive names to
local evidence files. Include the distribution, source identity, checksums,
acceptance JSON, logs and observed outcomes. The utility retains those bytes and
verifies checksums; it does not upgrade their readiness verdict.

Qualification must use the installed public package outside the checkout. The
fixed OP-01..10 inventory combines installed offline/isolated scenarios, Chromium
navigation/security tests and rights-backed realism measurements. Current-source
identities and actual artifacts feed `conops-readiness`; historical alpha logs are
baseline evidence and never copied into a new passing requirement.

The realism fixtures are explicitly adapted historical mathematical excerpts by
three independent authors, with rights, original sources, transformations and retained
hashes in their provenance manifest. They include a born-digital PDF and multi-file
TeX. They do not represent contemporary papers, a live-model benchmark, full
formalization accuracy or an external user pilot. Per-document raw counts and macro
averages preserve denominators; unlabeled fidelity and novelty remain unknown.
Optional live-model evaluation requires explicit endpoint/model/disclosure and
resource settings. `NOT_MEASURED` is retained when it is not run.
