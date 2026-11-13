# Research campaign queue and authority boundary

`proofmap.campaign.operations` connects the existing paper action planner to an
operator-authorized SQLite queue. `paper_actions.request_action()` remains pure.
Plans are `PLANNING_ONLY`; an authorization record and immutable request must exist
before dispatch. The operation policy and mathematical assessment policy have
separate identities. A selected execution profile alone does not evaluate current
authority: current assessment additionally needs external trust and an explicit
UTC evaluation time.

## State transitions

An automatic task moves through `REQUESTED`, `AUTHORIZED`, `QUEUED`, `RUNNING` and
one of `SUCCEEDED`, `CHECK_FAILED`, `UNAVAILABLE`, `ERROR`, `CANCELLED`, or `STALE`.
Unsupported or unauthorized adapter work is `BLOCKED`. Human work is
`AWAITING_REVIEW` until an explicit, externally authenticated decision is recorded
or rejected. A queued cancellation is terminal immediately. A running cancellation
records `CANCEL_REQUESTED` and retains `RUNNING` plus `cancel_requested=true` until
the worker confirms container cleanup. Failed cleanup ends in `ERROR`.

These are task states. `SUCCEEDED` never means `ACCEPTED_UNDER_POLICY`, fidelity
approval, or scholarly novelty. Review packets retain original source files,
anchors, the interpretation, scoped context, formal encoding and execution records.
Approval and rejection commands require a reason; its immutable handoff identity is
included in the signed review method. An abstention remains a handoff and supplies
no mathematical approval.

## Delivery and persistence

The admitted beta profile is one running task per campaign. Claims and completion
use short `BEGIN IMMEDIATE` transactions on separate controller connections. Every
projection is retained in a CAS-backed `TaskEvent`; `queue.rebuild()` recreates the
mutable index from ordered events. Each attempt retains its parent, lease token,
owner, generation, deadline, reservations, result and usage. Expired leases require
explicit recovery. An old generation, expired token, stale target or cancelled
worker cannot promote current evidence. Task result, eligible execution audit and
completion state are committed together. Cancelled workers retain diagnostic
results without publishing execution into current paper evidence.

Work identity binds exact paper/run/revision/assertion/interpretation/binding,
adapter, profile, inputs and policy, and excludes evaluation timestamps. Replanning
or repeated authorization reuses eligible work. Cancelled and stale work needs a
fresh explicit request. Source stage requests acquire and retain the exact bounded
manifest and bytes in the existing CAS before authorization; export never follows
their local source path.

Recovery provides at least once execution delivery. Fencing provides one current
result publication for a lease. Execution that completed externally before a
controller crash can be repeated after recovery; there is no claim of exactly once
external effects. A known failed or unavailable task can be explicitly retried
within its attempt and policy budgets. A model request with unknown external
effects remains `ERROR` and cannot automatically retry.

## Bounds and adapters

Task attempts and wall time have durable campaign reservations. Dispatch reserves
the verifier limit plus bounded cleanup allowance, or bounded parser/model time;
actual elapsed usage is retained. A run ends at a task, budget, idle or review
boundary. No missing execution infrastructure invokes a host verifier fallback.

Model tasks reserve their configured maximum requests and output tokens globally
across campaign attempts. Completed or possibly sent reservations are charged
conservatively. Known non-dispatch releases the reservation. Reserved token charges
are resource accounting, not measured model usage or scientific accuracy.

Source ingestion, reparsing, exact replay and explicitly configured extraction call
the existing bounded intake APIs. Pure analysis/formalization/exact computation and
report adapters call the established implementations. Formal verification uses the
existing isolated restricted Lean adapter. Authentication and reassessment call the
existing external trust validators. Source/formal/context/bridge review stays human.
Extraction configuration and replay digests are bound at request time and checked
again at dispatch; model output cannot authorize work, select credentials, sign a
review, or approve a proposition.

The queue tests exercise concurrent SQLite claims, duplicate authorization,
reconstruction, killed controllers, expired leases, late results, cancellation,
revision invalidation, reservations and external authority rejection. Dedicated
`PROOFMAP_SANDBOX_TEST=1` tests additionally observe running real Linux containers
and their termination, isolation, timeout and output limits. Simulated verifier
fixtures test record/trust contracts only and are never isolated-execution evidence.
