from __future__ import annotations

from functools import lru_cache
from importlib.resources import files
from typing import TYPE_CHECKING, Any

from .integrity import ValidationIssue, canonical_bytes, strict_loads

if TYPE_CHECKING:
    from jsonschema.protocols import Validator
    from referencing import Registry


def schema(name: str) -> dict[str, Any]:
    """Return a fresh public copy, isolated from the private validator resources."""
    if name not in {
        "kernel",
        "source-locator",
        "paper-input",
        "stage-result",
        "document-ir",
        "formal_obligation",
        "proof_attempt",
        "proofmap",
        "source",
        "theory_catalog",
        "hypothesis",
        "formalization-binding",
        "verifier-profile",
        "environment-manifest",
        "execution-event",
        "review-decision",
        "acceptance-record",
        "assessment-record",
        "checker-result",
        "semantic-candidate",
        "candidate-fidelity-report",
        "interpretation-override",
        "action-planning",
        "formalization-result",
        "paper-records",
        "extractor-config",
        "pipeline-assessment",
        "campaign-record",
    }:
        raise ValueError("Unknown packaged schema")
    value = strict_loads(files("proofmap.resources").joinpath(name + ".schema.json").read_bytes())
    if not isinstance(value, dict):
        raise ValueError("Invalid packaged schema")
    return value


@lru_cache(maxsize=1)
def _registry() -> Registry[Any]:
    from referencing import Registry, Resource

    # Register only known package resources. The registry's default retriever
    # rejects unknown resources without network access.
    known = {
        "urn:proofmap:document-ir:1": "document-ir",
        "urn:proofmap:verifier-profile:1": "verifier-profile",
        "urn:proofmap:extractor-config:1": "extractor-config",
        "urn:proofmap:checker-result:1": "checker-result",
    }
    return Registry().with_resources(
        (uri, Resource.from_contents(schema(resource))) for uri, resource in known.items()
    )


@lru_cache(maxsize=None)
def _validator(name: str) -> Validator:
    from jsonschema import Draft202012Validator

    # Only allowlisted packaged schemas are cached. These private dictionaries
    # are never returned by schema(); input records and verdicts are never cached.
    resource = schema(name)
    return Draft202012Validator(resource, registry=_registry())


def validate(name: str, value: Any) -> list[ValidationIssue]:
    value = strict_loads(canonical_bytes(value))
    validator = _validator(name)
    return [
        ValidationIssue(
            "SCHEMA_" + str(e.validator).upper(),
            "/" + "/".join(map(str, e.absolute_path)),
            e.message,
        )
        for e in sorted(validator.iter_errors(value), key=lambda e: str(e.absolute_path))
    ]
