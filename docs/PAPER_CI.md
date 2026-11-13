# Bounded Paper CI and offline review

For the current integrated source-to-formal/evidence/review path, use
[PAPER_EVIDENCE.md](PAPER_EVIDENCE.md). The examples below retain the compatible
source-audit and name-only review commands. New authenticated fidelity drafts use
`review-export --dimension ... --assertion ... --execution-profile ...`, then an
explicit decision, `review-sign`, and `review-apply` with external authority.
`paper resume` reuses validated pure stages where their dependencies match.
Historical formal execution can be reused only through current dependency,
environment and authority checks; current bindings and fidelity decisions remain
separate. No resume or revision operation inherits an acceptance verdict.

The current implementation is an alpha publication candidate pending final
qualification. See [the active acceptance contract](ALPHA_ACCEPTANCE.md) and
[current status](../REPO_STATUS.md). Source indexing, model suggestions and
attributed review do not constitute mathematical proof or scholarly acceptance.

```sh
python -m pip install -e '.[paper,trust,test,dev]'
proofmap paper ci tests/fixtures/papers/train/basic.tex --extractor none --policy paper-ci-alpha-v1 --out outputs/paper_review --store .paper-store
proofmap paper list --store .paper-store
proofmap paper inspect RUN_ID --store .paper-store
proofmap paper inspect RUN_ID --view review --store .paper-store
proofmap paper query --paper PAPER_ID --role THEOREM --store .paper-store
proofmap paper report outputs/paper_review --out outputs/linked_report --store .paper-store
proofmap paper review-export outputs/paper_review --author 'Reviewer name' --out review.json
proofmap paper review-apply outputs/paper_review review.json --store .paper-store
proofmap paper diff outputs/old_review outputs/new_review
proofmap paper benchmark --corpus tests/fixtures/papers --out benchmark.json
```

Inputs: local TeX file/directory, bounded ZIP/tar, or PDF. Multiple root candidates
require `--entrypoint`. Links/junctions, absolute paths, traversal, platform device
aliases, duplicate/case-colliding archive files and excessive input sizes are
rejected. No URLs, TeX build scripts, package hooks or latexmk configuration run.

TeX uses pinned pylatexenc 2.11 syntax nodes, not a TeX engine. Original text,
balanced syntax, labels/references, includes, custom theorem names, lexical and
discourse scopes, exact macro definition/use provenance and typed mathematical
contexts are retained. Byte locators are checked against exact UTF-8 artifacts.
Local BibTeX and `bibitem` references and explicit, adjacent, ambiguous or external
proof associations remain source structure, with no truth or dependency inferred
merely from a citation. Explicit conjunctive and alternative reference groups are
kept distinct. Arbitrary TeX execution and general macro interpretation remain
unsupported; the [restricted formal profile](PAPER_FORMAL_PROFILE.md) can translate
supported zero-argument integer-literal macros.

PDF uses the maintained pypdf 6.19.0 adapter: it is a substantially smaller
offline dependency than Docling and requires no model acquisition. It returns
page text, original PDF hash and excerpt hash, not invented TeX offsets or
bounding boxes. Scanned pages are NEEDS_OCR. It does not identify PDF theorems
reliably without additional reviewed extraction. Original born-digital and
image-only PDF fixtures were generated and visually inspected.

Every run produces input_manifest, document_ir, assertions, symbols,
argument_map, extraction_events, findings, assessment and run_manifest JSON,
plus a shared report.json model, report.md, report.html and results.sarif. The source browser works without
JavaScript; text is escaped and content security policy denies scripts/network.
The run manifest binds individual JSON components, detecting mixed/stale bundles.

Assertions stay AUTHOR_ASSERTED. Explicit source premises are conjunctive within
an inference; separately stated alternative arguments remain separate inferences.
They remain author assertions requiring review. Parsing/indexing/signing/compilation do
not confer proof. Exact checking accepts a narrow Q[x] AST with rational constants,
arithmetic and bounded powers, never eval/exec. Optional explicit `exact_checks`
config entries select a source `label`, `left`, and `right`; an unequal encoding
is only a candidate contradiction until domain/source fidelity is reviewed.
`required_stages: ["formal"]` or external `--require-formal` fails UNAVAILABLE
without a prepared profile. The external flag cannot be weakened by manuscript
configuration. Required formal stages need complete discovered-claim coverage.

## Optional model adapter and privacy

Default extractor `none` is offline. `configured` requires an explicit JSON config:

```json
{"extractor":{"provider":"ollama","endpoint":"http://127.0.0.1:11434","model":"YOUR_INSTALLED_MODEL","timeout_seconds":30,"max_output_tokens":2048}}
```

The adapter uses [Ollama's chat protocol](https://docs.ollama.com/api/chat), makes
deterministic bounded requests per document chunk, disables streaming/tools/redirects/proxy inheritance, and
requests a strict classification/dependency schema. There is no selected default
model or live-provider claim. Responses cannot introduce arbitrary source ranges,
commands, unknown source IDs or PROVED status. Suggestions remain in immutable extraction
events and a visible candidate overlay, with AND-premise groups distinct from
certified inferences. Exact requests,
responses and hashes are retained; missing usage/version fields stay unknown.
`replay` consumes the pipeline's exported event list with the same manuscript and
config; no network call occurs:

```sh
proofmap paper ci paper.tex --config extractor.json --extractor replay \
  --replay-event recorded/extraction_events.json --out replayed --store replay-store
```

Document replay objects and legacy single-request event objects are also accepted.
Every request and raw response is revalidated; stale, missing, extra or malformed
records produce an extraction error. A real local fake HTTP server verifies the
export/replay round trip offline in tests.

An extractor configuration with `stage: "decomposition"` requests source-anchored
statement/context/premise candidates and records source coverage explicitly.
Independent advisory checking uses a separate `candidate-fidelity` configuration;
an unconfigured checker reports `UNAVAILABLE`. Its `AGREE`, `DISAGREE` and
`UNCERTAIN` results do not replace authenticated human fidelity decisions, and a
model cannot grant proof or acceptance. Local HTTP test doubles establish protocol
behavior; they do not measure live model quality.

Configured extraction sends source text to the explicitly selected endpoint.
Keep confidential papers offline unless authorized. Local bundles/CAS contain raw
source and model responses; treat them accordingly. Do not commit private keys,
provider credentials or private manuscript outputs. PR CI uses extractor none.

## Store and review

SQLite schema version 2 migrates version 1 in place and uses foreign keys,
parameterized SQL and transactions. Validated pure parsing/extraction stage
outputs are atomically committed and reusable for identical inputs/configuration.
CAS objects are hashed before a run is indexed. Interrupted work can leave orphan
objects but never a partly indexed run. Runs/reviews are append-only; `paper rebuild`
reconstructs derived entity rows. Ingestion never creates trust.

Review apply checks the immutable indexed run plus revision/analysis/assertion
bindings. Name-only attribution is not authentication. The authenticated workflow
requires separate source-fidelity and formal-fidelity decisions plus authenticated
execution evidence. Assessment always rechecks external authority at an explicit
evaluation time. A revised source,
configuration, policy or pipeline code invalidates review reuse. Diff and revision
planning match unambiguous labels, retain move/formatting candidates conservatively,
and propagate explicit source/context dependencies. Changed and unresolved
dependencies trigger recomputation. Eligible pure stages may be reused; eligible
historical execution still requires matching formal/environment identities and
current external authority checks. Reuse creates current bindings and lineage;
fresh current fidelity and policy assessment are required for acceptance.
Loading a supported cached formalization recomputes its bounded exact arithmetic
certificate as an integrity check. A reused formalization producer or historical
Lean execution does not mean that this validation arithmetic was skipped.

## Attributed interpretation overrides

Export an exact-bound draft, edit its `changes` array, and apply it to a new output
directory. The original bundle must still match its immutable indexed run.

```sh
proofmap paper override-export outputs/paper_review --author 'Reviewer name' --out interpretation.json
proofmap paper override-apply outputs/paper_review interpretation.json --out outputs/interpreted --store .paper-store
proofmap paper report outputs/interpreted --out outputs/interpreted_report --store .paper-store
```

Each change contains `kind`, `target`, `scope`, `source_digest`, `value` and a
nonempty `note`. Copy `target` from a draft target's `id` and retain that target's
exact scope and source digest. Supported kinds are `role` (an assertion role),
`proof_for` (an assertion ID or null), and `dependencies` (assertion IDs). Targets
and dependencies must satisfy the supported scope and role restrictions. Stale
drafts, duplicate changes, self-dependencies and invalid scope crossings fail.

Application appends an immutable attributed record and creates `interpreted_ir`,
then recomputes assertions, the argument map, derived formal candidates, findings,
assessment and action plan. Raw `document_ir`, source artifacts and extraction
events stay unchanged. Prior execution, acceptance and fidelity authority are
cleared; changed interpretation requires new evidence and reviews. Attribution is
not authentication, and an override cannot mark a claim proved or accepted.

## Navigable reports and action plans

The shared report model links each claim to source anchors, contexts, proof
associations, formal bindings, evidence, reviews, findings and next steps. HTML is
offline, script-free and keyboard navigable; all formats derive from the same
view and report the installed package version. `inspect --view review` returns
that model; `inspect --assertion ID_OR_UNIQUE_LABEL` narrows it. `query` filters
indexed claims by paper, revision, role, state or finding.

Default reports and queries describe immutable historical run snapshots. For a
current authority evaluation, use `assess` with the external execution profile,
trust store and explicit evaluation time; `--report-out` writes its separate
JSON/Markdown/HTML/SARIF view without rewriting the original run.

`paper_actions.plan_paper_actions` identifies exact-bound evidence/review/context
work. Without explicit current authority inputs, accepted state is unknown.
`simulate_paper_actions` exposes assumptions, hypothetical effects and witnesses;
`request_action` records a request without executing it. These operations are
`PLANNING_ONLY`, preserve actual state and report unmeasured costs/gains as null.

New CLI exit codes: 0 pipeline conformance (not proof), 1 unmet requested closure
or required check, 2 invalid/unsafe input, 3 infrastructure/unavailable verifier,
4 failed receipt authentication. These codes describe the requested workflow;
success never implies that every indexed mathematical assertion is true.
