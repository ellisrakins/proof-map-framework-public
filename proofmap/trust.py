"""DSSE Ed25519 receipt authentication against external, scoped trust roots.

Signatures authenticate content, NOT execution or mathematical/source fidelity.
No embedded key, role, or claimed runner becomes a trust root.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Any, Mapping

from .attempts import AttemptReceipt
from .integrity import strict_loads

PAYLOAD_TYPE = "application/vnd.proofmap.attempt-receipt.v1+json"


def pae(payload_type: str, payload: bytes) -> bytes:
    name = payload_type.encode("utf-8")
    return (
        b"DSSEv1 "
        + str(len(name)).encode()
        + b" "
        + name
        + b" "
        + str(len(payload)).encode()
        + b" "
        + payload
    )


def _decode(value: Any) -> bytes:
    if not isinstance(value, str) or len(value) > 48_000_000:
        raise ValueError("Invalid base64 field")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid base64 field") from exc


def validate_payload(payload: bytes) -> AttemptReceipt:
    return AttemptReceipt.from_dict(strict_loads(payload))


def sign(payload: bytes, private_key: bytes, key_id: str) -> dict[str, Any]:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    validate_payload(payload)
    if not key_id:
        raise ValueError("External key identifier is required")
    key = Ed25519PrivateKey.from_private_bytes(private_key)
    sig = key.sign(pae(PAYLOAD_TYPE, payload))
    return {
        "payloadType": PAYLOAD_TYPE,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [{"keyid": key_id, "sig": base64.b64encode(sig).decode("ascii")}],
    }


@dataclass(frozen=True)
class Authentication:
    authenticated: bool
    key_id: str
    role: str
    subject: str
    execution_provenance: str = "NOT_ESTABLISHED"
    mathematical_acceptance: str = "NOT_ESTABLISHED"


def verify(envelope: Mapping[str, Any], trust_store: Mapping[str, Any]) -> Authentication:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if (
        set(envelope) != {"payloadType", "payload", "signatures"}
        or envelope["payloadType"] != PAYLOAD_TYPE
    ):
        raise ValueError("DSSE payload type or fields rejected")
    if set(trust_store) != {"schema_version", "keys"} or trust_store["schema_version"] != "1.0":
        raise ValueError("Unsupported external trust store")
    payload = _decode(envelope["payload"])
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 16:
        raise ValueError("Signature count rejected")
    keys = trust_store["keys"]
    if not isinstance(keys, list) or len({k["id"] for k in keys}) != len(keys):
        raise ValueError("Duplicate/invalid trust keys")
    if len(keys) > 1024:
        raise ValueError("Trust store key limit")
    for key in keys:
        if (
            not isinstance(key.get("id"), str)
            or not key["id"]
            or type(key.get("revoked")) is not bool
            or not isinstance(key.get("subjects"), list)
            or any(not isinstance(x, str) or not x for x in key["subjects"])
        ):
            raise ValueError("Invalid external trust key scope/types")
    for signature in signatures:
        if set(signature) != {"keyid", "sig"}:
            raise ValueError("Unknown signature fields")
        for key in keys:
            if set(key) != {"id", "public_key", "role", "subjects", "revoked"}:
                raise ValueError("Unknown trust key fields")
            if (
                key["id"] != signature["keyid"]
                or key["revoked"] is not False
                or key["role"] != "receipt-content"
            ):
                continue
            try:
                Ed25519PublicKey.from_public_bytes(_decode(key["public_key"])).verify(
                    _decode(signature["sig"]), pae(PAYLOAD_TYPE, payload)
                )
            except InvalidSignature:
                continue
            # Decode semantics only after authenticating exact original bytes.
            receipt = validate_payload(payload)
            if receipt.target_node_id not in key["subjects"]:
                continue
            return Authentication(True, key["id"], key["role"], receipt.target_node_id)
    raise ValueError("No valid, nonrevoked, externally trusted signature for this subject")


RECORD_PAYLOAD_TYPES = {
    "ExecutionEvent": "application/vnd.proofmap.execution-event.v1+json",
    "ReviewDecision": "application/vnd.proofmap.review-decision.v1+json",
}


def sign_record(record: Mapping[str, Any], private_key: bytes, key_id: str) -> dict[str, Any]:
    """Low-level controller/reviewer primitive, never a generic PASS-upload service.

    Execution callers must use execute(), which constructs records from its own
    worker run before invoking this primitive. A signature attributes bytes only.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from .evidence_records import validate_record
    from .integrity import canonical_bytes

    validate_record(record)
    payload_type = RECORD_PAYLOAD_TYPES.get(str(record["record_type"]))
    if payload_type is None or not isinstance(key_id, str) or not key_id:
        raise ValueError("Unsupported signable record/key id")
    payload = canonical_bytes(dict(record))
    signature = Ed25519PrivateKey.from_private_bytes(private_key).sign(pae(payload_type, payload))
    return {
        "payloadType": payload_type,
        "payload": base64.b64encode(payload).decode("ascii"),
        "signatures": [{"keyid": key_id, "sig": base64.b64encode(signature).decode("ascii")}],
    }


def _evaluation_time(value: Any) -> Any:
    from datetime import datetime, timezone

    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Explicit UTC evaluation time required")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise ValueError("Invalid authority validity time") from exc


def authenticated_record(envelope: Mapping[str, Any]) -> dict[str, Any]:
    """Decode a record only after verify_record succeeded at the call site."""
    from .evidence_records import validate_record

    record = strict_loads(_decode(envelope["payload"]))
    validate_record(record)
    return dict(record)


def verify_record(
    envelope: Mapping[str, Any],
    trust_store: Mapping[str, Any],
    *,
    role: str,
    subject: str,
    profile_digest: str,
    evaluation_time: str,
) -> Authentication:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from .integrity import require_digest

    roles = {"verification-execution", "source-fidelity-review", "formal-fidelity-review"}
    if role not in roles:
        raise ValueError("Unsupported evidence authority role")
    expected_type = RECORD_PAYLOAD_TYPES[
        "ExecutionEvent" if role == "verification-execution" else "ReviewDecision"
    ]
    if (
        not isinstance(envelope, dict)
        or set(envelope) != {"payloadType", "payload", "signatures"}
        or envelope["payloadType"] != expected_type
    ):
        raise ValueError("DSSE evidence payload type/fields rejected")
    require_digest(profile_digest)
    now = _evaluation_time(evaluation_time)
    if (
        not isinstance(trust_store, dict)
        or set(trust_store) != {"schema_version", "keys"}
        or trust_store["schema_version"] != "2.0"
    ):
        raise ValueError("Execution/review requires external trust store 2.0")
    keys = trust_store["keys"]
    if not isinstance(keys, list) or len(keys) > 1024:
        raise ValueError("Invalid trust keys")
    ids: set[str] = set()
    for key in keys:
        if not isinstance(key, dict) or set(key) != {
            "id",
            "public_key",
            "roles",
            "subjects",
            "profiles",
            "revoked",
            "not_before",
            "not_after",
        }:
            raise ValueError("Unknown external authority fields")
        if (
            not isinstance(key["id"], str)
            or not key["id"]
            or key["id"] in ids
            or type(key["revoked"]) is not bool
        ):
            raise ValueError("Invalid or duplicate authority")
        ids.add(key["id"])
        for field in ("roles", "subjects", "profiles"):
            if not isinstance(key[field], list) or any(
                not isinstance(x, str) or not x for x in key[field]
            ):
                raise ValueError("Invalid authority scope")
        for configured in key["profiles"]:
            require_digest(configured)
        before, after = _evaluation_time(key["not_before"]), _evaluation_time(key["not_after"])
        if before >= after:
            raise ValueError("Invalid authority validity interval")
        if not set(key["roles"]) <= roles | {"receipt-content"}:
            raise ValueError("Unknown authority role")
        if len(_decode(key["public_key"])) != 32:
            raise ValueError("Invalid public key")
    payload = _decode(envelope["payload"])
    signatures = envelope["signatures"]
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= 16:
        raise ValueError("Invalid signature count")
    for signature in signatures:
        if not isinstance(signature, dict) or set(signature) != {"keyid", "sig"}:
            raise ValueError("Unknown signature fields")
        for key in keys:
            if (
                key["id"] != signature["keyid"]
                or key["revoked"]
                or role not in key["roles"]
                or subject not in key["subjects"]
                or profile_digest not in key["profiles"]
                or not _evaluation_time(key["not_before"])
                <= now
                < _evaluation_time(key["not_after"])
            ):
                continue
            try:
                Ed25519PublicKey.from_public_bytes(_decode(key["public_key"])).verify(
                    _decode(signature["sig"]), pae(expected_type, payload)
                )
            except InvalidSignature:
                continue
            record = authenticated_record(envelope)
            if record["assertion_id"] != subject or record["profile_digest"] != profile_digest:
                raise ValueError("Authenticated record subject/profile mismatch")
            if role == "verification-execution":
                if record["controller_id"] != key["id"]:
                    raise ValueError("Authenticated controller identity mismatch")
            elif record["dimension"] + "-review" != role or record["reviewer_id"] != key["id"]:
                raise ValueError("Authenticated review dimension/identity mismatch")
            return Authentication(
                True,
                key["id"],
                role,
                subject,
                execution_provenance="AUTHENTICATED"
                if role == "verification-execution"
                else "NOT_ESTABLISHED",
            )
    raise ValueError("No current nonrevoked external authority for subject/profile/role")
