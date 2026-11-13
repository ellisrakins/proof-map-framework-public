# Receipt authentication and isolated replay

Historical Verified Attempt v1 receipts remain readable, content-bound,
unsigned historical reports. They are not authenticated executions and are not
automatically promoted into the kernel. Loading now rejects `verified:null`,
boolean return codes, missing stored hashes, unauthorized/sorryAx axioms,
wrong scopes, inconsistent policies, and pinned-version mismatches. Semantic
validation also runs when serializing.

`receipt-sign` signs the exact input bytes using DSSE Ed25519 from cryptography.
`receipt-verify` checks the signature before parsing the payload and requires a
separately supplied trust store. PAE uses UTF-8 byte lengths, not character counts.
Legacy receipt signatures use only `receipt-content`; they do **not** assert execution
provenance. New versioned execution/review payloads use separate
`verification-execution`, `source-fidelity-review`, and `formal-fidelity-review`
roles with externally scoped subjects, profiles, revocation and validity intervals.
See [the profile/trust contract](LEAN_PROFILE.md) and [CLI workflow](PAPER_EVIDENCE.md).
Revocation and exact subject scopes are checked on every verification.
No embedded key can grant itself trust.

```sh
proofmap receipt-sign receipt.json --key private.key --key-id reviewer-1 --out signed.json
proofmap receipt-verify signed.json --trust-store trust.json
proofmap receipt-replay receipt.json --artifact-root inputs --manifest replay.json --image registry/lean@sha256:ACTUAL_DIGEST --out replay-event.json
```

The private key input is raw 32-byte Ed25519 material; do not commit it. The
external trust store has `schema_version: "1.0"` and `keys`, each containing
`id`, base64 raw `public_key`, `role: "receipt-content"`, a string-array `subjects`,
and boolean `revoked`. There is no production key included in the repository.

A replay manifest contains schema_version 1.0, relative `candidate` and `map`
paths, and a `files` map from portable relative paths to exact SHA-256 values.
All local modules required for replay must be listed. The isolated snapshot
contains only listed files plus the regenerated wrapper. Old absolute paths in
the receipt are inert; replay never reads them. Input, obligation, wrapper,
image, actual version and executable hash output are recorded. The old event
is retained as parent. A new unsigned local event is not a trusted-runner signature.

The container runner requires a locally acquired digest-pinned Linux image;
there is no automatic pull or host fallback. It drops capabilities, uses a
nonroot UID, read-only root/source, no network, bounded writable tmpfs, no socket
or secret mounts, and time/memory/CPU/PID/output limits. Timeout kills the container.
This host lacks Docker, so actual Linux isolation and isolated Lean replay remain
unverified here. The CI sandbox job must pass before describing this as validated
hostile-code isolation. Host `attempt-check` and `lean-check` remain **trusted
local compatibility APIs**, not hostile-input APIs. No TeX engine is executed.

Protocol reference: [DSSE specification](https://github.com/secure-systems-lab/dsse/blob/master/protocol.md).
