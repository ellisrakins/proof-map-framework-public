"""Record validator reuse preserves every input and semantic boundary."""

from copy import deepcopy

import pytest
from test_execution import binding, profile, simulated_execution

from proofmap import evidence_records
from proofmap.integrity import digest
from proofmap.schema import schema


@pytest.fixture(autouse=True)
def isolated_record_validators():
    evidence_records._record_validator.cache_clear()
    yield
    evidence_records._record_validator.cache_clear()


@pytest.mark.parametrize("warm", [False, True])
def test_public_schema_mutation_cannot_change_record_validation(warm):
    value = profile().to_dict()
    evidence_records._record_validator.cache_clear()
    if warm:
        evidence_records.validate_record(value)
    public = schema("verifier-profile")
    public["required"].clear()
    public["properties"]["image"].clear()
    value["image"] = "not-a-pinned-image"
    value["id"] = digest("verifier-profile.v1", {k: v for k, v in value.items() if k != "id"})
    with pytest.raises(ValueError, match="RECORD_SCHEMA"):
        evidence_records.validate_record(value)


@pytest.mark.parametrize("mutation", ["nested", "nan", "tuple", "identity"])
def test_warm_validator_rechecks_same_mutated_record(mutation):
    value = (binding() if mutation == "tuple" else profile()).to_dict()
    original = deepcopy(value)
    evidence_records.validate_record(value)
    if mutation == "nested":
        value["limits"]["wall_seconds"] = "unbounded"
    elif mutation == "nan":
        value["limits"]["wall_seconds"] = float("nan")
    elif mutation == "tuple":
        # Direct validation deliberately keeps its original JSON Schema array
        # semantics; canonicalization must not silently normalize this input.
        value["source_locators"] = tuple(value["source_locators"])
    else:
        value["id"] = "f" * 64
    with pytest.raises(ValueError):
        evidence_records.validate_record(value)
    value.clear()
    value.update(original)
    evidence_records.validate_record(value)


def test_warm_validator_rechecks_semantics_even_after_identity_is_recomputed():
    value = binding().to_dict()
    evidence_records.validate_record(value)
    value["source_locators"][0]["file"] = "../outside.tex"
    value["id"] = digest("formalization-binding.v1", {k: v for k, v in value.items() if k != "id"})
    with pytest.raises(ValueError):
        evidence_records.validate_record(value)


def test_repeated_execution_record_validation_reuses_resources_but_rechecks_nested_record(
    monkeypatch,
):
    result, _, _ = simulated_execution(monkeypatch)
    value = result["event"]
    evidence_records._record_validator.cache_clear()
    accesses = []
    files = evidence_records.files

    def counted(package):
        accesses.append(package)
        return files(package)

    monkeypatch.setattr(evidence_records, "files", counted)
    evidence_records.validate_record(value)
    assert len(accesses) == 2  # ExecutionEvent and its EnvironmentManifest.
    evidence_records.validate_record(value)
    assert len(accesses) == 2
    # This change is schema-valid and the outer identity is recomputed, but the
    # nested environment identity must still be independently checked.
    value["environment"]["reason"] = "forged environment reason"
    value["id"] = digest("execution-event.v1", {k: v for k, v in value.items() if k != "id"})
    with pytest.raises(ValueError, match="RECORD_IDENTITY_MISMATCH"):
        evidence_records.validate_record(value)
    assert len(accesses) == 2


@pytest.mark.parametrize("kind", ["../../secret", "https://example.invalid/schema"])
def test_private_record_factory_rejects_nonpackaged_schema_without_resource_access(
    monkeypatch, kind
):
    def unexpected_access(*args):
        raise AssertionError("Nonpackaged record schema was accessed")

    monkeypatch.setattr(evidence_records, "files", unexpected_access)
    with pytest.raises(ValueError, match="RECORD_TYPE_UNSUPPORTED"):
        evidence_records._record_validator(kind)
