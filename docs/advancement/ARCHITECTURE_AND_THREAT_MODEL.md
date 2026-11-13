# Architecture and threat model

Untrusted inputs: maps, manuscripts, archives, extracted/model text, candidate
proofs, receipts, keys embedded in receipts, browser labels, and dependency code.
Trusted inputs: explicit caller policy/foundation selection and externally
configured trust roots. A parser cannot create either.

Layers: immutable artifact bytes -> source IR -> author assertions/inferences ->
check events -> assessment -> independently authorized acceptance. Indexing,
compilation, signing, and apparent mathematical plausibility never imply acceptance.

The shared kernel requires every premise of an inference and permits alternative
inferences. Fixed points start only from externally selected foundations or
explicit research assumptions. Cycles do not create support. Evidence binds the
exact inference/claim revision, context and policy; stale or unauthenticated
imports cannot close a claim. Logical hypotheses are local to an obligation,
not global research assumptions. Formal proof establishes its encoding only.

Hashes are domain-separated content identities, not authentication or semantic
equivalence. DSSE authenticates exact payload bytes under an external role/scope
key policy, not the truth of a claimed execution. Historical v1 receipts retain
their historical digest algorithm and absolute paths as inert data.

Host Lean compatibility is only for explicitly trusted local code. Host TeX
execution, manuscript build hooks, implicit model endpoints and secrets are
prohibited. Untrusted execution requires a pinned isolated runner; absent that
runner the result is UNAVAILABLE, not fallback host execution.

Reports treat all paper/model text as data. Browser rendering uses inert JSON
and text nodes; no paper HTML/MathML/SVG is executable. Archive paths are bounded,
root-relative, case-collision checked and link-free. Store writes are transactional
and history append-only. No external publishing or server configuration changes
are authorized by implementing this epic.
