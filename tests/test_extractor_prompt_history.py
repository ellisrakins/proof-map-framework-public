"""Historical prompt audit is distinct from replay under the current prompt."""

from copy import deepcopy

import pytest
from test_semantic_candidates import CONFIG, document, fidelity_replay_fixture, replay_for

from proofmap import extractor, semantic_candidates
from proofmap.extractor import extract, extract_document, validate_recorded_event
from proofmap.integrity import artifact_digest, canonical_bytes, digest
from proofmap.semantic_candidates import validate_fidelity_report


def historical(stage="classification"):
    ir = document()
    config = {**CONFIG, "stage": stage}
    result = {"classifications": [], "dependencies": []}
    if stage == "decomposition":
        result["candidates"] = []
    output = extract_document(ir, config, replay=replay_for(ir, config, result))
    return ir, config, output["events"][0]


@pytest.mark.parametrize("stage", ["classification", "decomposition"])
def test_prior_prompt_event_can_be_audited_but_not_reused_for_current_prompt(monkeypatch, stage):
    ir, config, event = historical(stage)
    before = canonical_bytes(event)
    if stage == "classification":
        monkeypatch.setattr(extractor, "PROMPT", extractor.PROMPT + " Revised instructions.")
    else:
        monkeypatch.setattr(semantic_candidates, "DECOMPOSITION_PROMPT", "Revised decomposition.")

    def forbidden(*args, **kwargs):
        raise AssertionError("Historical audit contacted a model")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)
    validate_recorded_event(ir, config, event, prompt_digest=event["prompt_digest"])
    assert canonical_bytes(event) == before
    with pytest.raises(ValueError, match="STALE_EXTRACTION_REPLAY"):
        extract(ir, config, replay=event)


@pytest.mark.parametrize(
    "mutation", ["contract", "prompt", "source", "format", "options", "result", "usage", "model"]
)
def test_historical_prompt_mode_still_rejects_record_substitution(monkeypatch, mutation):
    ir, config, event = historical()
    prompt_digest = event["prompt_digest"]
    monkeypatch.setattr(extractor, "PROMPT", "New current prompt")
    if mutation == "contract":
        prompt_digest = "0" * 64
    elif mutation == "prompt":
        event["request"]["messages"][0]["content"] += " forged"
        event["prompt_digest"] = artifact_digest(
            event["request"]["messages"][0]["content"].encode()
        )
    elif mutation == "source":
        event["request"]["messages"][1]["content"] = "forged source"
    elif mutation == "format":
        event["request"]["format"]["additionalProperties"] = True
        event["schema_digest"] = digest("extraction-schema.v1", event["request"]["format"])
    elif mutation == "options":
        event["request"]["options"]["temperature"] = 1
    elif mutation == "result":
        event["result"]["classifications"] = [{"element": ir["elements"][0]["id"], "kind": "PROSE"}]
    elif mutation == "usage":
        event["usage"]["eval_count"] = 1
    else:
        event["model_reported"] = "forged model"
    event["request_sha256"] = artifact_digest(canonical_bytes(event["request"]))
    with pytest.raises(ValueError, match="EXTRACTION"):
        validate_recorded_event(ir, config, event, prompt_digest=prompt_digest)


def test_historical_prompt_does_not_admit_unknown_response_schema(monkeypatch):
    ir, config, event = historical()
    changed = deepcopy(extractor.RESPONSE_SCHEMA)
    changed["properties"]["classifications"]["maxItems"] = 255
    monkeypatch.setattr(extractor, "RESPONSE_SCHEMA", changed)
    with pytest.raises(ValueError, match="STALE_EXTRACTION_REPLAY"):
        validate_recorded_event(ir, config, event, prompt_digest=event["prompt_digest"])


def test_historical_prompt_requires_full_event_and_never_generates(monkeypatch):
    ir, config, event = historical()

    def forbidden(*args, **kwargs):
        raise AssertionError("Historical mode attempted generation")

    monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)
    with pytest.raises(ValueError, match="REQUIRES_FULL_REPLAY"):
        extract(ir, config, _recorded_prompt_digest=event["prompt_digest"])
    legacy = {
        k: event[k] for k in ("request_sha256", "config_digest", "raw_response", "response_sha256")
    }
    with pytest.raises(ValueError, match="REQUIRES_FULL_REPLAY"):
        validate_recorded_event(ir, config, legacy, prompt_digest=event["prompt_digest"])


def test_fidelity_history_retains_prior_prompt_and_rejects_new_prompt_replay(monkeypatch):
    ir, candidates, report = fidelity_replay_fixture()
    before = canonical_bytes(report)
    old_prompt = report["events"][0]["prompt_digest"]
    monkeypatch.setattr(semantic_candidates, "FIDELITY_PROMPT", "New fidelity comparison prompt")
    validate_fidelity_report(report, ir, candidates, recorded_prompt_digest=old_prompt)
    assert canonical_bytes(report) == before
    with pytest.raises(ValueError, match="STALE_EXTRACTION_REPLAY"):
        validate_fidelity_report(report, ir, candidates)
    with pytest.raises(ValueError, match="RECORDED_PROMPT_MISMATCH"):
        validate_fidelity_report(report, ir, candidates, recorded_prompt_digest="0" * 64)
