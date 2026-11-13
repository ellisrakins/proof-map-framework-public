import base64
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)

from proofmap.trust import pae, sign, verify


def material():
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    public = base64.b64encode(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    payload = Path("research/agoh_2026/agoh_factorization_receipt.json").read_bytes()
    subject = json.loads(payload)["target_node_id"]
    trust = {
        "schema_version": "1.0",
        "keys": [
            {
                "id": "test",
                "public_key": public,
                "role": "receipt-content",
                "subjects": [subject],
                "revoked": False,
            }
        ],
    }
    return private, payload, trust


def test_pae_utf8_lengths():
    assert pae("é", b"abc") == b"DSSEv1 2 \xc3\xa9 3 abc"


def test_signature_authenticates_content_not_execution():
    key, payload, trust = material()
    result = verify(sign(payload, key, "test"), trust)
    assert result.authenticated
    assert result.execution_provenance == "NOT_ESTABLISHED"
    assert result.mathematical_acceptance == "NOT_ESTABLISHED"


@pytest.mark.parametrize("change", ["bytes", "type", "revoked", "role", "subject", "untrusted"])
def test_signature_fail_closed(change):
    key, payload, trust = material()
    envelope = sign(payload, key, "test")
    if change == "bytes":
        envelope["payload"] = base64.b64encode(payload + b" ").decode()
    elif change == "type":
        envelope["payloadType"] = "different"
    elif change == "revoked":
        trust["keys"][0]["revoked"] = True
    elif change == "role":
        trust["keys"][0]["role"] = "runner"
    elif change == "subject":
        trust["keys"][0]["subjects"] = []
    else:
        trust["keys"] = []
    with pytest.raises(ValueError):
        verify(envelope, trust)


@pytest.mark.parametrize(
    "change",
    [
        "empty-sig",
        "extra-sig",
        "unknown-key",
        "unknown-store",
        "duplicates",
        "bad-scope",
        "bad-base64",
        "bad-payload-type",
    ],
)
def test_external_trust_schema_rejected(change):
    key, payload, trust = material()
    envelope = sign(payload, key, "test")
    if change == "empty-sig":
        envelope["signatures"] = []
    elif change == "extra-sig":
        envelope["signatures"][0]["public_key"] = "attacker-key"
    elif change == "unknown-key":
        trust["keys"][0]["extra"] = True
    elif change == "unknown-store":
        trust["schema_version"] = "999"
    elif change == "duplicates":
        trust["keys"] *= 2
    elif change == "bad-scope":
        trust["keys"][0]["subjects"] = "not-an-array"
    elif change == "bad-base64":
        envelope["payload"] = "!!!"
    else:
        envelope["payload"] = 1
    with pytest.raises(ValueError):
        verify(envelope, trust)


def test_sign_requires_key_id_and_valid_receipt():
    key, payload, _ = material()
    with pytest.raises(ValueError):
        sign(payload, key, "")
    with pytest.raises(ValueError):
        sign(b"{}", key, "test")
