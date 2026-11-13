"""Schema preparation may be reused; records and validation results may not."""

from copy import deepcopy

import pytest
from referencing.exceptions import Unresolvable
from test_kernel import graph

from proofmap import schema as schemas
from proofmap.paper_checkers import make_result


@pytest.fixture(autouse=True)
def isolated_schema_cache():
    schemas._validator.cache_clear()
    schemas._registry.cache_clear()
    yield
    schemas._validator.cache_clear()
    schemas._registry.cache_clear()


@pytest.mark.parametrize("warm", [False, True])
def test_public_schema_mutation_cannot_weaken_private_validation(warm):
    value = graph().to_dict()
    original = schemas.schema("kernel")
    if warm:
        assert not schemas.validate("kernel", value)
    public = schemas.schema("kernel")
    public["required"].clear()
    public["properties"]["schema_version"].clear()
    public["$defs"]["claim"].clear()
    assert schemas.schema("kernel") == original
    assert not schemas.validate("kernel", value)
    value["schema_version"] = "forged"
    assert any(issue.path == "/schema_version" for issue in schemas.validate("kernel", value))
    assert schemas.validate("kernel", {})


@pytest.mark.parametrize("warm", [False, True])
def test_public_referenced_schema_mutation_cannot_weaken_registry(warm):
    result = make_result("test", "PASS")
    value = {"checkers": [result]}
    if warm:
        schemas.validate("pipeline-assessment", value)
    public = schemas.schema("checker-result")
    public["properties"]["checker_version"].clear()
    result["checker_version"] = 123
    issues = schemas.validate("pipeline-assessment", value)
    assert any(issue.path == "/checkers/0/checker_version" for issue in issues)


def test_repeated_validation_rechecks_mutated_input_and_json_boundary():
    value = graph().to_dict()
    expected = deepcopy(value)
    assert not schemas.validate("kernel", value)
    value["claims"][0]["text"] = 17
    assert schemas.validate("kernel", value)
    value.clear()
    value.update(expected)
    assert not schemas.validate("kernel", value)
    value["unexpected"] = float("nan")
    with pytest.raises(ValueError):
        schemas.validate("kernel", value)


def test_repeated_validation_reuses_only_packaged_schema_preparation(monkeypatch):
    value = graph().to_dict()
    assert not schemas.validate("kernel", value)

    def unexpected_reload(name):
        raise AssertionError("A prepared schema was reloaded: " + name)

    monkeypatch.setattr(schemas, "schema", unexpected_reload)
    assert not schemas.validate("kernel", value)
    value["schema_version"] = "invalid"
    assert schemas.validate("kernel", value)


@pytest.mark.parametrize("name", ["../../secret", "https://example.invalid/schema.json"])
def test_unknown_schema_names_remain_rejected(name):
    with pytest.raises(ValueError, match="Unknown packaged schema"):
        schemas.schema(name)
    with pytest.raises(ValueError, match="Unknown packaged schema"):
        schemas.validate(name, {})


def test_unregistered_schema_reference_never_fetches_network(monkeypatch):
    original = schemas.schema

    def foreign_reference(name):
        result = original(name)
        if name == "kernel":
            result["$ref"] = "https://example.invalid/unregistered.json"
        return result

    def unexpected_network(*args, **kwargs):
        raise AssertionError("Schema validation attempted network access")

    monkeypatch.setattr(schemas, "schema", foreign_reference)
    monkeypatch.setattr("socket.create_connection", unexpected_network)
    monkeypatch.setattr("urllib.request.urlopen", unexpected_network)
    for _ in range(2):
        with pytest.raises(Unresolvable):
            schemas.validate("kernel", graph().to_dict())
