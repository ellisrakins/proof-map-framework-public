"""Fresh, fail-closed execution of the bounded Lean/Std integer profile.

The controller constructs the target, snapshot, material checks and signed event.
Proof text can select only one approved trusted tactic. It cannot choose code,
imports, an environment or a declaration. Arbitrary Lean remains unsupported.
"""

from __future__ import annotations

import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .attempts import FormalObligation, parse_lean_axioms
from .evidence_records import (
    EnvironmentManifest,
    ExecutionEvent,
    FormalizationBinding,
    VerifierProfile,
    obligation_identity,
)
from .integrity import artifact_digest, canonical_bytes, digest, strict_loads
from .runner import Limits, run

WORKER = Path(__file__).with_name("lean_worker.py").read_bytes()
CHECKER_DIGEST = artifact_digest(WORKER)
TOOLCHAIN = "leanprover/lean4:v4.30.0"
AXIOMS = ("Classical.choice", "Quot.sound", "propext")


def _validate_statement(statement: str) -> None:
    if len(statement) > 16000:
        raise ValueError("UNSUPPORTED_PROFILE_STATEMENT_LIMIT")
    match = re.fullmatch(
        r"∀\s*\(([a-z][a-z0-9_]*(?:\s+[a-z][a-z0-9_]*)*)\s*:\s*Int\),\s*(.+)", statement, re.S
    )
    if not match:
        raise ValueError("UNSUPPORTED_PROFILE_QUANTIFIER")
    variables = match[1].split()
    if len(variables) > 8 or len(set(variables)) != len(variables):
        raise ValueError("UNSUPPORTED_PROFILE_VARIABLES")
    body = match[2]
    tokens = re.findall(r"[a-z][a-z0-9_]*|[0-9]+|[()+*^=→-]", body)
    if "".join(tokens) != re.sub(r"\s+", "", body) or len(tokens) > 2048:
        raise ValueError("UNSUPPORTED_PROFILE_EXPRESSION")
    if any(re.match(r"[a-z]", token) and token not in variables for token in tokens):
        raise ValueError("UNSUPPORTED_PROFILE_FREE_SYMBOL")
    if any(token.isdigit() and len(token) > 12 for token in tokens):
        raise ValueError("UNSUPPORTED_PROFILE_NUMERAL")
    # Lean itself decides well-formedness; the finite terminal alphabet and bound
    # variable names above cannot contain declarations, commands or tactic code.
    if "=" not in tokens:
        raise ValueError("UNSUPPORTED_PROFILE_EQUATION")


def render_wrapper(obligation: FormalObligation, candidate: bytes) -> str:
    FormalObligation.from_dict(obligation.to_dict())
    if (
        obligation.toolchain != TOOLCHAIN
        or tuple(obligation.imports) != ("Std",)
        or set(obligation.allowed_axioms) != set(AXIOMS)
    ):
        raise ValueError("UNSUPPORTED_PROFILE_OBLIGATION")
    _validate_statement(obligation.statement)
    if len(candidate) > 128:
        raise ValueError("UNSUPPORTED_CANDIDATE")
    try:
        words = candidate.decode("utf-8").split()
    except UnicodeError as exc:
        raise ValueError("UNSUPPORTED_CANDIDATE_ENCODING") from exc
    if len(words) != 2 or words[0] != "by" or words[1] not in {"grind", "rfl", "omega"}:
        raise ValueError("UNSUPPORTED_CANDIDATE: approved programs are by grind/rfl/omega")
    # The submitted declaration name is data; only the fixed declaration runs.
    return (
        "import Std\nset_option maxHeartbeats 800000\n"
        + "theorem proofmap_target : "
        + obligation.statement
        + " := by\n  "
        + words[1]
        + "\n#print axioms proofmap_target\n"
    )


def execute(
    binding: FormalizationBinding | dict[str, Any],
    obligation: FormalObligation,
    candidate: bytes,
    profile: VerifierProfile | dict[str, Any],
    *,
    controller_id: str = "local-unsigned",
    private_key: bytes | None = None,
    parent_event: str | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Execute a fresh attempt; private signing material never enters the snapshot."""
    binding = FormalizationBinding.from_dict(
        binding.to_dict() if isinstance(binding, FormalizationBinding) else binding
    )
    profile = VerifierProfile.from_dict(
        profile.to_dict() if isinstance(profile, VerifierProfile) else profile
    )
    if (
        binding.obligation_digest != obligation_identity(obligation)
        or binding.assertion_id != obligation.target_node_id
        or binding.candidate_digest != artifact_digest(candidate)
    ):
        raise ValueError("EXECUTION_BINDING_MISMATCH")
    if profile.checker_digest != CHECKER_DIGEST:
        raise ValueError("UNSUPPORTED_PROFILE_CHECKER")
    wrapper = render_wrapper(obligation, candidate)
    recheck = render_wrapper(obligation, b"by grind")
    snapshot = {
        "Candidate.lean": wrapper.encode(),
        "Recheck.lean": recheck.encode(),
        "worker.py": WORKER,
        "request.json": canonical_bytes({"profile": profile.to_dict()}),
    }
    snapshot_digest = digest(
        "execution-snapshot.v1", {k: artifact_digest(v) for k, v in snapshot.items()}
    )
    with tempfile.TemporaryDirectory(prefix="proofmap-execution-") as folder:
        root = Path(folder)
        root.chmod(0o755)
        for name, raw in snapshot.items():
            (root / name).write_bytes(raw)
            (root / name).chmod(0o644)
        cancellation = {"cancelled": cancelled} if cancelled is not None else {}
        result = run(
            profile.image,
            root,
            ("/usr/local/bin/python", "-I", "/src/worker.py"),
            Limits(**profile.limits),
            **cancellation,
        )
    actual: dict[str, Any] = {}
    complete = False
    compiler = "NOT_RUN"
    checker = "NOT_RUN"
    axioms: list[str] = []
    outcome = (
        result.execution_status
        if result.execution_status in {"UNAVAILABLE", "TIMEOUT", "ERROR"}
        else "VERIFIER_ERROR"
    )
    outputs = {
        "worker_stdout": result.stdout,
        "worker_stderr": result.stderr,
        "candidate_source": candidate.decode("utf-8"),
    }
    reason = result.stderr or "Worker did not establish complete environment"
    if result.execution_status == "PASS":
        try:
            report = strict_loads(result.stdout)
            actual = report["actual"]
            complete = (
                report["outcome"] == "CHECKED"
                and all(
                    actual[key] == getattr(profile, key)
                    for key in (
                        "lean_sha256",
                        "library_digest",
                        "checker_digest",
                        "platform",
                        "executable",
                        "search_path",
                    )
                )
                and "version 4.30.0," in actual["version"]
            )
            if not complete:
                raise ValueError("ENVIRONMENT_MATERIAL_MISMATCH")
            generated = report["results"]["Candidate"]
            checked = report["results"].get("Recheck")
            compiler = (
                "PASS"
                if type(generated["returncode"]) is int and generated["returncode"] == 0
                else "FAIL"
            )
            if compiler == "FAIL":
                outcome = "COMPILER_REJECTED"
                reason = (
                    "Candidate did not establish the encoded theorem; this is not a counterexample."
                )
            elif (
                checked is not None
                and type(checked["returncode"]) is int
                and checked["returncode"] == 0
            ):
                first = parse_lean_axioms(
                    generated["stdout"] + "\n" + generated["stderr"], "proofmap_target"
                )
                second = parse_lean_axioms(
                    checked["stdout"] + "\n" + checked["stderr"], "proofmap_target"
                )
                if (
                    first is not None
                    and second is not None
                    and not (set(first) | set(second)) - set(AXIOMS)
                ):
                    axioms = sorted(set(first) | set(second))
                    checker = "PASS"
                    outcome = "VERIFIED"
                    reason = "Restricted source checked in two fresh Lean processes; no submitted compiled artifacts."
            actual["image"] = profile.image
        except (ValueError, TypeError, KeyError):
            complete = False
            outcome = "VERIFIER_ERROR"
            reason = "Malformed worker report or material mismatch"
    environment = EnvironmentManifest.build(
        profile_digest=profile.digest,
        complete=complete,
        actual=actual,
        completeness_scope=profile.name,
        reason=reason,
    )
    event = ExecutionEvent.build(
        binding_digest=binding.digest,
        revision_id=binding.revision_id,
        assertion_id=binding.assertion_id,
        obligation_digest=binding.obligation_digest,
        profile_digest=profile.digest,
        candidate_digest=artifact_digest(candidate),
        wrapper_digest=artifact_digest(wrapper.encode()),
        snapshot_digest=snapshot_digest,
        controller_digest=artifact_digest(Path(__file__).read_bytes()),
        controller_id=controller_id,
        parent_event=parent_event,
        environment=environment.to_dict(),
        outcome=outcome,
        compiler_outcome=compiler,
        checker_outcome=checker,
        axioms=axioms,
        outputs=outputs,
        output_digests={k: digest("execution-output.v1", v) for k, v in outputs.items()},
        duration_seconds=result.duration_seconds,
        assurance="TRUSTED_RESTRICTED_SOURCE_KERNEL_RECHECK",
    )
    envelope = None
    if private_key is not None:
        from .trust import sign_record

        envelope = sign_record(event.to_dict(), private_key, controller_id)
    value: dict[str, Any] = {"event": event.to_dict(), "envelope": envelope}
    if cancelled is not None:
        value["runner_status"] = result.execution_status
    return value


def replay_execution(
    event: dict[str, Any],
    binding: FormalizationBinding,
    obligation: FormalObligation,
    candidate: bytes,
    profile: VerifierProfile,
    **kwargs: Any,
) -> dict[str, Any]:
    previous = ExecutionEvent.from_dict(event)
    if (
        previous.binding_digest != binding.digest
        or previous.profile_digest != profile.digest
        or previous.candidate_digest != artifact_digest(candidate)
    ):
        raise ValueError("REPLAY_BINDING_MISMATCH")
    return execute(binding, obligation, candidate, profile, parent_event=previous.digest, **kwargs)
