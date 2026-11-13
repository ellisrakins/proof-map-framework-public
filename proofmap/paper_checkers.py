"""Explicit stage requirements. Partial coverage never means a proof passed."""

from __future__ import annotations

from typing import Any, Callable

from .integrity import canonical_bytes, digest

REGISTRY: dict[str, Callable[..., dict[str, Any]]] = {}


def make_result(
    name: str,
    status: str,
    findings: list[dict[str, Any]] | None = None,
    *,
    revision: str | None = None,
    source_ids: list[str] | None = None,
    coverage: dict[str, Any] | None = None,
    configuration: dict[str, Any] | None = None,
    certificate_references: list[str] | None = None,
    seconds: float | None = None,
) -> dict[str, Any]:
    """Versioned execution reporting, without upgrading a finding into proof."""
    from importlib.metadata import version

    normalized = []
    for finding in findings or []:
        normalized.append(
            {
                **finding,
                "severity": finding.get("severity", "warning"),
                "source": finding.get("source"),
                "classification": finding.get("classification", "ADVISORY"),
                "message": finding.get("message", finding.get("detail", finding["code"])),
                "remediation": finding.get(
                    "remediation",
                    "Inspect source and checker details; supply current evidence or resolve the unsupported region.",
                ),
                "blocking_eligible": finding.get("blocking_eligible", False),
            }
        )
    result = {
        "schema_version": "1.0",
        "checker": name,
        "checker_version": version("proof-map-boundary-analysis"),
        "execution_status": status,
        "revision": revision,
        "source_ids": sorted(set(source_ids or [])),
        "findings": normalized,
        "coverage": coverage
        or {
            "attempted": None,
            "eligible": None,
            "supported": None,
            "denominator": "Not measured by this checker",
            "reason": "Unknown is not zero.",
        },
        "configuration_digest": digest("checker-configuration.v1", configuration or {}),
        "certificate_digest": None,
        "certificate_references": certificate_references or [],
        "trust": "LOCAL_ANALYSIS_NOT_PROOF",
        "blocking_eligible": False,
        "resource_use": {"seconds": seconds, "peak_memory_bytes": None},
    }
    validate_result(result)
    return result


def validate_result(result: dict[str, Any]) -> None:
    from .schema import validate

    canonical_bytes(result)
    if validate("checker-result", result):
        raise ValueError("INVALID_CHECKER_RESULT")
    counts = result["coverage"]
    known = {key: counts[key] for key in ("attempted", "eligible", "supported")}
    if (
        known["attempted"] is not None
        and known["eligible"] is not None
        and known["attempted"] > known["eligible"]
    ) or (
        known["supported"] is not None
        and known["attempted"] is not None
        and known["supported"] > known["attempted"]
    ):
        raise ValueError("INVALID_CHECKER_COVERAGE")
    if result["execution_status"] in {"NOT_RUN", "UNAVAILABLE"} and any(
        value not in (None, 0) for key, value in known.items() if key != "eligible"
    ):
        raise ValueError("UNEXECUTED_CHECKER_COVERAGE")


def register(name: str, function: Callable[..., dict[str, Any]]) -> None:
    if name in REGISTRY and REGISTRY[name] is not function:
        raise ValueError("DUPLICATE_CHECKER")
    REGISTRY[name] = function


def run_checker(name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    return REGISTRY[name](*args, **kwargs)


def exact_polynomial(left: str, right: str) -> dict[str, Any]:
    from .exact_check import equality

    return {
        "check": "PASS" if equality(left, right) else "FAIL",
        "mode": "COMPUTATIONAL",
        "domain": "Q[x]",
    }


register("exact-polynomial", exact_polynomial)


def required_failures(
    stages: list[dict[str, Any]], required: list[str], *, allow_partial: set[str] | None = None
) -> list[str]:
    if not isinstance(required, list) or any(not isinstance(value, str) for value in required):
        raise ValueError("UNKNOWN_REQUIRED_STAGE")
    for stage in stages:
        validate_result(stage)
    statuses = {s["checker"]: s["execution_status"] for s in stages}
    if len(statuses) != len(stages) or len(required) != len(set(required)):
        raise ValueError("DUPLICATE_CHECKER_REQUIREMENT")
    if not isinstance(required, list) or any(
        not isinstance(x, str) or x not in statuses for x in required
    ):
        raise ValueError("UNKNOWN_REQUIRED_STAGE")
    if allow_partial is not None and (
        not isinstance(allow_partial, set)
        or any(not isinstance(name, str) for name in allow_partial)
    ):
        raise ValueError("INVALID_PARTIAL_PROFILE")
    allowed = allow_partial or set()
    if not allowed <= set(required):
        raise ValueError("PARTIAL_POLICY_OUTSIDE_REQUIRED_PROFILE")
    return [
        s
        for s in required
        if statuses[s] != "PASS" and not (s in allowed and statuses[s] == "PARTIAL")
    ]
