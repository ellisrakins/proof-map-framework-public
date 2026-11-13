"""Fixed mandatory checks. Never infer this list from attacker-controlled results."""

REQUIRED = [
    "quality",
    "python-tests",
    "schema-migration",
    "semantic-properties",
    "verification-real",
    "sandbox-security",
    "paper-ci-fixtures",
    "paper-e2e-isolated",
    "browser-security",
    "package-build",
    "dependency-audit",
    "workflow-security",
    "windows-regression",
    "alpha-readiness",
    "conops-readiness",
]


def accepted(results: dict[str, dict[str, str | None]]) -> bool:
    return set(results) == set(REQUIRED) and all(
        results[name].get("result") == "success" for name in REQUIRED
    )
