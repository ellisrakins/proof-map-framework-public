"""Policy for the repository's workflow layout; actionlint checks YAML syntax.

Acquisition declarations are reviewable inputs, not certification of transitive
package contents. Dependency audits and actual isolated jobs remain separate gates.
"""

from __future__ import annotations

import re
from pathlib import Path


def validate_workflow(text: str, name: str) -> list[str]:
    errors: list[str] = []

    def require(ok: bool, code: str) -> None:
        if not ok:
            errors.append(code)

    require(not re.search(r"\b(pull_request_target|workflow_run)\b", text), "UNTRUSTED_TRIGGER")
    require("secrets." not in text, "SECRET_ACCESS")
    header = text.split("\njobs:", 1)[0]
    require(
        bool(re.search(r"^permissions:\s*\n  contents: read\s*$", header, re.M)),
        "READ_ONLY_DEFAULT",
    )
    optional = name == "codeql.yml"
    for permissions in re.finditer(
        r"^( *)permissions:[ \t]*([^\n]*)\n((?:\1 +[^\n]*\n)*)", text, re.M
    ):
        require(not permissions[2].strip(), "INLINE_PERMISSIONS")
        for line in permissions[3].splitlines():
            require(
                line.strip() == "contents: read"
                or (optional and line.strip() == "security-events: write"),
                "UNAUTHORIZED_PERMISSION",
            )
    jobs = re.findall(
        r"^  ([\w-]+):\n(.*?)(?=^  [\w-]+:\n|\Z)", text.split("\njobs:", 1)[-1], re.M | re.S
    )
    require(bool(jobs), "MISSING_JOBS")
    for job_name, job in jobs:
        timeout = re.search(r"^    timeout-minutes: ([0-9]+)\s*$", job, re.M)
        require(timeout is not None and 1 <= int(timeout[1]) <= 30, "UNBOUNDED_JOB:" + job_name)
    for step in re.split(r"^      - ", text, flags=re.M)[1:]:
        match = re.search(r"(?:^|\n\s*)uses:\s*([^\s#]+)", step)
        if not match:
            continue
        value = match[1]
        require(bool(re.fullmatch(r"[A-Za-z0-9_./-]+@[a-f0-9]{40}", value)), "UNPINNED_ACTION")
        if value.startswith("actions/checkout@"):
            require(
                bool(re.search(r"^          persist-credentials: false\s*$", step, re.M)),
                "PERSISTED_CREDENTIALS",
            )
        if value.startswith("actions/upload-artifact@"):
            days = re.search(r"^          retention-days: ([0-9]+)\s*$", step, re.M)
            require(days is not None and 1 <= int(days[1]) <= 7, "UNBOUNDED_ARTIFACT")
        if "codeql" in value or "attest" in value or "upload-sarif" in value:
            require(optional and "codeql-action/" in value, "MANDATORY_HOSTED_ENTITLEMENT")
    for line in text.splitlines():
        if "pip install" in line:
            constraint = (
                "validator/constraints-ci.txt" if name == "paper-ci.yml" else "constraints-ci.txt"
            )
            require("-c " + constraint in line, "UNCONSTRAINED_PYTHON_ACQUISITION")
        if "go install" in line:
            require(
                bool(re.search(r"go install [\w./-]+@v\d+\.\d+\.\d+\s*$", line)),
                "UNPINNED_GO_ACQUISITION",
            )
        if "docker pull" in line:
            require(
                bool(re.search(r"docker pull [\w./-]+@sha256:[a-f0-9]{64}\s*$", line)),
                "UNPINNED_CONTAINER",
            )
    require(not re.search(r"\b(curl|wget)\b", text), "UNREVIEWED_DOWNLOAD")
    require(
        not re.search(r"\b(?:twine\s+upload|gh\s+(?:release|api|repo)|git\s+(?:push|tag))\b", text),
        "PUBLICATION_OR_SERVER_MUTATION",
    )
    if name in {"ci.yml", "paper-ci.yml"}:
        require("cancel-in-progress: true" in header, "SUPERSEDED_RUNS_NOT_CANCELLED")
    if optional:
        require("on: [workflow_dispatch]" in header, "OPTIONAL_NOT_MANUAL")
        require("    if: vars.PROOFMAP_CODEQL_ENABLED == 'true'" in text, "ENTITLEMENT_NOT_GATED")
    if name == "release.yml":
        require("on: [workflow_dispatch]" in header, "RELEASE_NOT_MANUAL")
        require("name: unpublished-build" in text, "MISSING_UNPUBLISHED_ARTIFACT")
        require(
            not re.search(
                r"publish|attest|release-action|pypi",
                text.replace("unpublished-build", "build"),
                re.I,
            ),
            "RELEASE_PUBLICATION_STEP",
        )
    if name == "paper-ci.yml":
        require("github.ref == 'refs/heads/main'" in text, "UNGUARDED_DISPATCH")
        require(
            "ref: ${{ github.event.pull_request.base.sha || inputs.validator-ref }}" in text,
            "UNTRUSTED_VALIDATOR_REVISION",
        )
        require("sparse-checkout: papers" in text, "SUBMISSION_NOT_DATA_ONLY")
        require(
            "python -I validator/scripts/paper_ci_corpus.py manuscript/papers reports" in text,
            "SUBMISSION_IMPORT_PATH",
        )
        require(
            "git -C validator rev-parse HEAD" in text
            and "git -C manuscript rev-parse HEAD" in text,
            "MISSING_REVISION_IDENTITY",
        )
        guard = text.find("- name: Enforce approved dispatch validator")
        require(0 <= guard < text.find("- uses: actions/checkout"), "MISSING_DISPATCH_GUARD")
        allowed = re.search(r"options: \['([a-f0-9]{40})'\]", text)
        require(
            allowed is not None
            and f'test "$VALIDATOR_REF" = "{allowed[1]}"' in text
            and 'test "$VALIDATOR_REF" != "' + "0" * 40 + '"' in text,
            "INVALID_DISPATCH_ALLOWLIST",
        )
    return sorted(set(errors))


def main() -> int:
    failures = {
        path.name: errors
        for path in sorted(Path(".github/workflows").glob("*.yml"))
        if (errors := validate_workflow(path.read_text(), path.name))
    }
    if failures:
        for name, errors in failures.items():
            print(name + ": " + ", ".join(errors))
        return 1
    print(
        "Workflow policy scan passed; actionlint and runtime isolation are separate required checks."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
