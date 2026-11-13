# Campaign dossiers and offline retention

`proofmap campaign report CAMPAIGN --store STORE --out REPORT` generates a single
shared projection as `campaign-report.json`, `campaign-report.md`, and accessible,
script-free `campaign-report.html`. `graph-ledger.json` preserves a separate
qualified identity for each selected claim. Paper links open the existing source,
context, formal statement, execution and review views. Retained reviewer handoffs
are linked under `review-packets/`. Local input paths and fencing tokens are
redacted in presentation; their immutable audit records remain in the protected
store.

The HTML and Markdown also retain campaign plans, ranking, blockers and conditional
assumptions with their original snapshot and evaluation time. Dependency edges
carry exact inference records, qualified identities and source/model provenance.
Author references and model suggestions remain visibly distinct, unauthenticated
inferential support; accepting an endpoint does not certify its dependency.

A report with no supplied authority is a historical dossier. Its current verified,
reviewed and accepted counts are zero. A current view requires all three external
inputs: `--execution-profile`, `--trust-store`, and `--evaluation-time`. Rendering
uses the existing evidence adapter and does not write an assessment or change
paper runs. Execution outcome, source/formal fidelity, current acceptance and
scholarly novelty remain separate. The graph ledger is `PRESENTATION_ONLY` and
provides no closure authority. A candidate cross-paper link does not merge claims
or establish implication, equivalence or contradiction.

`proofmap campaign impact CAMPAIGN --from SNAPSHOT_A --to SNAPSHOT_B --store STORE`
uses the existing dependency-aware revision planner. It distinguishes matched,
moved, changed and unresolved claims, records observed pure-artifact reuse, and
keeps removed goals unresolved. New exact source bindings require new fidelity
reviews even when pure mathematical analysis can be reused. An operator must
explicitly rebind a goal through a source-backed mapping. Policy and trust changes
require current reassessment; historical successful execution remains historical.

## Export and restore

```sh
proofmap campaign export CAMPAIGN --store STORE --out partial-dossier.zip
proofmap campaign export CAMPAIGN --store STORE --include-source --out full-dossier.zip
proofmap campaign import full-dossier.zip --store CLEAN_STORE
proofmap campaign audit CAMPAIGN --store CLEAN_STORE
```

The default archive excludes raw manuscript files and explicitly reports
`raw_manuscripts_included=false`, `source_excerpts_included=true`, and
`self_contained_replay=false`. It retains navigable reports and historical
metadata, including extracted source excerpts. It cannot be restored into an
operational store as if the omitted manuscript bytes existed. The library's
`extract_dossier_report(archive, output_directory)` opens this partial offline
view without reconstructing absent material.

```sh
proofmap inspect-dossier partial-dossier.zip --out offline-report
```

`--include-source` retains exact source bytes from the content-addressed store,
including source-stage requests whose input paths are no longer present. Export
does not follow recorded source paths. Source rights remain those of the supplied
manuscripts; this command performs no external upload.

Export takes a supported SQLite backup snapshot and follows exact campaign,
run-lineage and stage references. It does not copy a live database file. Every
archive payload has its size and conventional SHA-256 recorded in `manifest.json`.
The manifest itself has a domain-separated digest. All referenced objects are
read back and verified before the archive is published atomically.

Restore validates portable paths, links, case collisions, bounded sizes, schemas,
hashes, subject bindings and semantic references in a throwaway store before any
destination writes. Reimport is idempotent; conflicting immutable IDs fail.
Indexes are reconstructed from retained objects and events. Imported active jobs
become `STALE`, with `IMPORT_REQUIRES_FRESH_AUTHORIZATION` recorded as an event.
Old leases cannot dispatch work. Review and execution signatures are retained as
untrusted evidence; only independently supplied local authority can authenticate
them. No trust-store file becomes a local trust root on import. Hash integrity is
not signature authentication or mathematical acceptance.

## Retaining software qualification

The library API `preserve_qualification(files, archive, identity=identity)` retains
owner-selected acceptance reports, produced artifacts and checksums. Supply the
exact source fingerprint, tree and package version; hosted run/attempt identities
and package digests may be included as provenance. A URL alone is rejected as a
replacement for retained payloads. `verify_dossier(archive)` performs local digest
verification independently of upstream URL availability.

```sh
proofmap preserve-qualification --files retention-files.json --identity candidate-identity.json --out qualification.zip
proofmap inspect-dossier qualification.zip
```

`retention-files.json` maps intended archive names to local artifact paths.
Re-export manifests identify retained qualification histories explicitly; they do
not treat another candidate's old retained result as the current candidate's
qualification.

`export_campaign(..., qualification_files=files,
qualification_identity=identity)` includes the same evidence in a campaign
dossier. Restore retains these bytes in CAS, so a later export can preserve them
again. The manifest separates local payload availability, integrity, caller
provenance and required external trust evaluation. Secret-bearing configuration
and recognized private-key material are rejected. Select only intended
qualification outputs; do not include controller credentials or private reviewer
keys. No command changes repository retention settings or publishes an archive.

Owner preservation checklist:

1. Select the final candidate's acceptance reports, logs and built distribution.
2. Record exact source/tree/package and hosted run/attempt identities.
3. Preserve the payload bytes locally and verify their archive inventory.
4. Keep an independently managed authority configuration outside the archive.
5. Restore into a clean store, audit the historical dossier, and reassess with
   explicit current authority/time before using any acceptance projection.
