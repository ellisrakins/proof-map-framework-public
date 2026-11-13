# Evidence-action planning

`proofmap.paper_actions` derives proposed work from actual kernel closure
failures or exact paper/formal bindings. A missing premise proof, current
execution evidence, authentication, a scope correction and a fidelity review
are different actions with different required artifacts and verifier/reviewer
modes. Every action binds its subject, context, policy, prerequisites and
counterfactual condition. Unsupported context transformations require a new
supported interpretation and plan; the planner does not guess their closure.

The public functions return versioned JSON records validated by the packaged
`action-planning.schema.json` and `validate_action_record`:

- `plan_evidence_actions(graph, **authority)` uses the same policy, foundations,
  research assumptions and externally trusted evidence inputs as kernel closure.
- `plan_paper_actions(bundle, profile=None, trust_store=None,
  evaluation_time=None, reviews=())` plans offline by default. Current authority
  is unknown in that mode; cached acceptance labels do not establish it. Supply
  all three authority inputs to re-evaluate execution and review envelopes.
- `simulate_evidence_actions(graph, action_ids, **authority)` and
  `simulate_paper_actions(bundle, action_ids, **authority)` recompute the current
  plan and return actual and hypothetical closure separately. Each new
  hypothetical result names its action assumptions and inference witness.
  Unselected prerequisites block dependent actions. Unsupported scopes and
  research assumptions never become unconditional foundations.
- `request_action(plan, action_id, actor=..., requested_at=...)` returns an
  auditable `REQUESTED` record, with unauthenticated attribution and `NOT_RUN`
  execution. It does not execute, sign, write artifacts or mutate a store.
  Actual execution and authenticated reviews remain separate existing APIs.
- `rank_evidence_actions(plan, costs=None)` uses the named
  `conditional-closure-planning` version `1` heuristic: fewer prerequisites,
  then more declared blockers, then caller-estimated comparable effort.
  Its ordering is a planning convention, not scientific value. Unknown
  expected gain, cost and score remain null; supplied effort is explicitly
  labeled. A hypothetical delta assumes success and is not an expected gain.

Plans, requests and simulations always carry `authority: PLANNING_ONLY`.
They contain no fabricated receipts, accepted assessments or signing keys.
Ordinary visualization relations cannot increase accepted or hypothetical
deductive closure. Planning rejects mismatched subjects, stale selected action
IDs, malformed records and dangling prerequisites. Work and witness budgets
bound graph processing; resource-limit errors do not declare success.

The legacy `optimizer.simulate_closure` and `rank_closure_candidates` signatures
remain available as adapters. They preserve authored statuses and uncertainty;
the old `proposed_uncertainty` argument is deprecated and has no effect.
Actual geometric deltas remain zero. The returned scenario metadata contains
the explicit counterfactual record, and ranked candidates identify their action
IDs and blocker-count heuristic. Legacy authored statuses are never accepted
evidence. Existing hypothesis geometry remains advisory and does not supply
kernel authority.

The focused planning tests use explicitly simulated worker output and ephemeral
test signatures for authentication regressions. Those tests exercise planning
and authentication contracts; they do not demonstrate real Lean execution or
prove a mathematical claim.
