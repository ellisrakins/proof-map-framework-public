# Repository status - research campaign beta candidate, 2026-10-03 UTC

The **0.9.0b1** source contains the
research-campaign workflow described in
[CONOPS_RESEARCH_CAMPAIGN.md](docs/CONOPS_RESEARCH_CAMPAIGN.md). Campaign snapshots
pin exact manuscripts/runs/goals and operation policies. The existing planner feeds
an explicitly authorized, bounded durable queue. Source/replay/pure/exact/isolated
adapters retain execution and human handoffs; fresh external authority evaluates
fidelity and policy acceptance. Shared offline reports and presentation-only graph
relations expose unknowns. Revision impact, validated restore and qualification
retention preserve history without importing authority.

The historical 0.8.0a1 baseline passed 81 alpha requirements on its own revision.

The frozen [alpha contract](acceptance/paper_ci_alpha.json) remains unchanged.
The explicit [successor compatibility profile](acceptance/paper_ci_beta_compatibility.json)
preserves its 81 obligations; the additive
[OP-01..10 contract](acceptance/research_campaign_conops_v1.json) supplies the
operational gate. A release candidate must pass alpha-readiness,
conops-readiness and ci-required against its own source and distribution.
Prior qualification of other source bytes is not a qualification of this copy.

| State | Declaration |
|---|---|
| Research campaign implementation | A–F implementation and tests are present; exact candidate results govern validation |
| Isolated development scenario | Actual pinned Lean: two verified, zero accepted before review; one accepted after two explicit independent test decisions; conflict/revision remove acceptance |
| Queue delivery | Bounded attempts with leases and fencing; crash/race/budget/container cancellation observed; external effects can repeat after a crash |
| Release readiness | `false` until exact candidate alpha and CONOPS profiles plus aggregate checks pass |
| Live-model quality / external user pilot | `NOT_MEASURED` / `NOT_PERFORMED` |
| Production authority / distribution publication | `NOT_CONFIGURED` / `NOT_REQUESTED` |
| Scholarly acceptance | `NOT_ASSESSED` |

The narrow formal grammar and parser limits remain in force. A pending human
review or unsupported mathematical goal can remain open after the software workflow
works; task success does not establish mathematical acceptance. Consult
[implementation progress](docs/advancement/RESEARCH_CAMPAIGN_PROGRESS.md),
[queue guarantees](docs/RESEARCH_CAMPAIGN_QUEUE.md) and
[dossier behavior](docs/CAMPAIGN_DOSSIER.md).

## Historical results

Earlier alpha and paper-to-evidence milestones were tested on their own source
revisions. Development history, hosted diagnostics and machine-local evidence are
not bundled with this source snapshot. A public build must qualify its own exact
source, dependencies and execution environment; prior results cannot be reused
as a release verdict.
