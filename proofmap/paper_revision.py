"""Dependency-local revision matching; cached analysis never confers proof authority.

Producer reuse avoids formalize_assertion and eligible isolated worker executions.
Loading a supported pure result still recomputes its bounded exact certificate;
cache_validation records that validation separately from producer invocation.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .integrity import canonical_bytes, digest, require_digest

PLAN_VERSION = "1.0"
MAX_DEPENDENCIES = 10000


def _semantic(value: Any) -> Any:
    """Remove occurrence coordinates, retaining the declared mathematical content."""
    if isinstance(value, list):
        return [_semantic(row) for row in value]
    if isinstance(value, dict):
        return {
            name: _semantic(item)
            for name, item in value.items()
            if name
            not in {
                "id",
                "revision",
                "locator",
                "scope",
                "lexical_scope",
                "owner",
                "previous_definition",
                "definition",
                "start",
                "end",
                "source_ids",
            }
        }
    return value


def _scope(ir: dict[str, Any], element: dict[str, Any]) -> list[dict[str, Any]]:
    elements = {row["id"]: row for row in ir["elements"]}
    scopes = {row["id"]: row for row in ir["scopes"]}
    result = []
    cursor: Any = element["scope"]
    seen: set[str] = set()
    while cursor in scopes:
        if cursor in seen or len(seen) > 64:
            raise ValueError("REVISION_SCOPE_CYCLE")
        seen.add(cursor)
        row = scopes[cursor]
        if row.get("element") in elements:
            source = elements[row["element"]]
            result.append({"kind": source["kind"], "text": source["text"]})
        cursor = row.get("parent")
    lexical = {row["id"]: row for row in ir.get("lexical_scopes", [])}
    cursor = element.get("lexical_scope")
    seen.clear()
    while cursor in lexical:
        if cursor in seen or len(seen) > 64:
            raise ValueError("REVISION_SCOPE_CYCLE")
        seen.add(cursor)
        row = lexical[cursor]
        result.append({"kind": row["kind"], "name": row["name"]})
        cursor = row["parent"]
    return result


def dependency_snapshot(ir: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Record exact supported context, explicit dependencies and ambiguity reasons."""
    from .formalize import definition_context

    elements = {row["id"]: row for row in ir["elements"]}
    claims = [row for row in ir["elements"] if row["kind"] == "ASSERTION"]
    if len(claims) > MAX_DEPENDENCIES:
        raise ValueError("REVISION_DEPENDENCY_LIMIT")
    labels: dict[str, list[str]] = {}
    for element in ir["elements"]:
        for label in element["labels"]:
            labels.setdefault(label, []).append(element["id"])
    snapshots: dict[str, dict[str, Any]] = {}
    for element in claims:
        reasons: list[str] = []
        identity = None
        if len(element["labels"]) == 1 and len(labels[element["labels"][0]]) == 1:
            identity = digest(
                "paper-logical-match.v1",
                {
                    "label": element["labels"][0],
                    "role": element.get("role"),
                    "scope": _scope(ir, element),
                },
            )
        else:
            reasons.append("AMBIGUOUS_LOGICAL_IDENTITY")
        context = definition_context(ir, element)
        if context.get("resolution") == "UNRESOLVED" or context.get("entries"):
            reasons.append("UNRESOLVED_SEMANTIC_CONTEXT")
        proofs = [
            row
            for row in ir["elements"]
            if row["kind"] == "PROOF" and row.get("proof_for") == element["id"]
        ]
        owned = {element["id"], *(row["id"] for row in proofs)}
        # Math and macro argument nodes may own references below the proof.
        # Resolve the complete source-owner tree, not just direct children.
        pending = True
        while pending:
            descendants = {row["id"] for row in ir["elements"] if row.get("owner") in owned}
            pending = bool(descendants - owned)
            owned.update(descendants)
        proof_contexts = [definition_context(ir, proof) for proof in proofs]
        if any(
            context.get("resolution") == "UNRESOLVED" or context.get("entries")
            for context in proof_contexts
        ):
            reasons.append("UNRESOLVED_PROOF_CONTEXT")
        references = [
            row
            for row in ir["references"]
            if row["owner"] in owned
            and not (row["kind"] == "REFERENCE" and row.get("purpose") == "PROOF_ASSOCIATION")
        ]
        dependencies = []
        ref_content = []
        for reference in references:
            targets = reference["targets"]
            if len(targets) != 1 or targets[0] not in elements:
                reasons.append("UNRESOLVED_CITATION_OR_DEPENDENCY")
            else:
                dependencies.append(targets[0])
            ref_content.append(
                {
                    "key": reference["key"],
                    "kind": reference["kind"],
                    "targets": [
                        _semantic(elements[target]) for target in targets if target in elements
                    ],
                }
            )
        ambiguous_proofs = [
            row for row in ir["elements"] if row["kind"] == "PROOF" and row.get("proof_for") is None
        ]
        if any(row["scope"] == element["scope"] for row in ambiguous_proofs):
            reasons.append("AMBIGUOUS_PROOF_ASSOCIATION")
        if ir.get("parser", {}).get("execution") in {"ERROR", "TIMEOUT", "UNAVAILABLE"}:
            reasons.append("PARSER_DID_NOT_COMPLETE")
        components = {
            "statement": digest(
                "paper-statement-content.v1", {"text": element["text"], "role": element.get("role")}
            ),
            "definitions": digest("paper-definition-dependencies.v1", _semantic(context)),
            "proof": digest(
                "paper-proof-content.v1",
                {"text": [row["text"] for row in proofs], "context": _semantic(proof_contexts)},
            ),
            "citations": digest("paper-citation-content.v1", ref_content),
        }
        snapshots[element["id"]] = {
            "assertion_id": element["id"],
            "logical_id": identity,
            "label": element["labels"][0] if len(element["labels"]) == 1 else None,
            "components": components,
            "dependencies": sorted(set(dependencies)),
            "reasons": sorted(set(reasons)),
            "fingerprint": digest("paper-dependencies.v1", components),
        }
    # A resolved explicit premise carries the whole transitive semantic context.
    visiting: set[str] = set()
    done: set[str] = set()

    def finish(ident: str, depth: int = 0) -> None:
        row = snapshots[ident]
        if ident in done:
            return
        if ident in visiting or depth > 64:
            row["reasons"] = sorted(set(row["reasons"] + ["UNRESOLVED_DEPENDENCY_CYCLE"]))
            return
        visiting.add(ident)
        dependencies = []
        for target in row["dependencies"]:
            if target in snapshots:
                finish(target, depth + 1)
                dependency = snapshots[target]
                dependencies.append(dependency["fingerprint"])
                if dependency["reasons"]:
                    row["reasons"] = sorted(set(row["reasons"] + ["UNRESOLVED_PREMISE_CONTEXT"]))
            else:
                dependencies.append(digest("paper-source-premise.v1", _semantic(elements[target])))
        row["fingerprint"] = digest(
            "paper-dependencies.v1",
            {"components": row["components"], "premises": sorted(dependencies)},
        )
        visiting.remove(ident)
        done.add(ident)

    for ident in snapshots:
        finish(ident)
    return snapshots


def revision_plan(
    old: dict[str, Any] | None, ir: dict[str, Any], analysis_context: dict[str, Any]
) -> dict[str, Any]:
    current = dependency_snapshot(ir)
    before = dependency_snapshot(old["document_ir"]) if old else {}
    by_logical = {row["logical_id"]: row for row in before.values() if row["logical_id"]}
    old_elements = {row["id"]: row for row in old["document_ir"]["elements"]} if old else {}
    elements = {row["id"]: row for row in ir["elements"]}
    old_context = old["run_manifest"].get("analysis_context", {}) if old else {}
    config_changes = (
        [
            name.upper() + "_CHANGED"
            for name in sorted(set(old_context) | set(analysis_context))
            if old_context.get(name) != analysis_context.get(name)
        ]
        if old
        else []
    )
    rows = []
    for ident, snapshot in current.items():
        prior = by_logical.get(snapshot["logical_id"])
        reasons = list(snapshot["reasons"])
        changes: list[str] = []
        if prior is None:
            reasons.append("NO_UNAMBIGUOUS_PRIOR_SUBJECT")
        else:
            reasons.extend(prior["reasons"])
            names = {
                "statement": "STATEMENT_OR_HYPOTHESIS_CHANGED",
                "definitions": "DEFINITION_OR_MACRO_CHANGED",
                "proof": "PROOF_CHANGED",
                "citations": "CITATION_OR_DEPENDENCY_CHANGED",
            }
            changes.extend(
                names[key]
                for key in names
                if prior["components"][key] != snapshot["components"][key]
            )
            if prior["fingerprint"] != snapshot["fingerprint"] and not changes:
                changes.append("TRANSITIVE_DEPENDENCY_CHANGED")
            if elements[ident]["locator"] != old_elements[prior["assertion_id"]]["locator"]:
                changes.append("SOURCE_REANCHORED")
        reasons.extend(change for change in changes if change != "SOURCE_REANCHORED")
        reasons.extend(change for change in config_changes if change != "TRUST_CHANGED")
        rows.append(
            {
                **snapshot,
                "previous_assertion_id": prior["assertion_id"] if prior else None,
                "previous_fingerprint": prior["fingerprint"] if prior else None,
                "changes": sorted(set(changes)),
                "reasons": sorted(set(reasons)),
                "reuse_eligible": prior is not None and not reasons,
                "pure_stage": None,
                "parent_stage": None,
                "pure_execution": "NOT_RUN",
                "cache_validation": "NOT_A_SUPPORTED_CACHE_HIT",
                "formal_execution": "NOT_RUN",
                "historical_event": None,
                "reviews": "CURRENT_BINDING_REQUIRED",
            }
        )
    value: dict[str, Any] = {
        "schema_version": PLAN_VERSION,
        "revision": ir["revision"],
        "parent_run": old["run_manifest"]["run_id"] if old else None,
        "parent_revision": old["input_manifest"]["revision"] if old else None,
        "analysis_context": deepcopy(analysis_context),
        "configuration_changes": config_changes,
        "rows": rows,
    }
    return value


def validate_revision_plan(plan: dict[str, Any], ir: dict[str, Any]) -> None:
    if not isinstance(plan, dict) or set(plan) != {
        "schema_version",
        "revision",
        "parent_run",
        "parent_revision",
        "analysis_context",
        "configuration_changes",
        "rows",
    }:
        raise ValueError("REVISION_PLAN_FIELDS")
    if plan["schema_version"] != PLAN_VERSION or plan["revision"] != ir["revision"]:
        raise ValueError("REVISION_PLAN_BINDING")
    if plan["parent_revision"] is not None:
        require_digest(plan["parent_revision"])
    if (plan["parent_run"] is None) != (plan["parent_revision"] is None):
        raise ValueError("REVISION_PLAN_PARENT")
    expected = dependency_snapshot(ir)
    rows = plan["rows"]
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise ValueError("REVISION_PLAN_SUBJECTS")
    seen = set()
    extra = {
        "previous_assertion_id",
        "previous_fingerprint",
        "changes",
        "reuse_eligible",
        "pure_stage",
        "parent_stage",
        "pure_execution",
        "cache_validation",
        "formal_execution",
        "historical_event",
        "reviews",
    }
    for row in rows:
        original = expected.get(row.get("assertion_id", "")) if isinstance(row, dict) else None
        if original is None or row["assertion_id"] in seen or set(row) != set(original) | extra:
            raise ValueError("REVISION_PLAN_SUBJECTS")
        seen.add(row["assertion_id"])
        for name in set(original) - {"reasons"}:
            if row[name] != original[name]:
                raise ValueError("REVISION_DEPENDENCY_FINGERPRINT")
        if not set(original["reasons"]) <= set(row["reasons"]):
            raise ValueError("REVISION_HIDDEN_UNCERTAINTY")
        if type(row["reuse_eligible"]) is not bool or (
            row["reuse_eligible"]
            and (row["reasons"] or row["previous_fingerprint"] != row["fingerprint"])
        ):
            raise ValueError("REVISION_UNSAFE_REUSE")
        if row["pure_execution"] not in {"NOT_RUN", "EXECUTED", "REUSED"} or row[
            "formal_execution"
        ] not in {"NOT_RUN", "EXECUTED", "HISTORICAL_REUSE"}:
            raise ValueError("REVISION_EXECUTION_STATUS")
        if row["reviews"] != "CURRENT_BINDING_REQUIRED":
            raise ValueError("REVISION_REVIEW_REUSE_FORBIDDEN")
        expected_validation = (
            "BOUNDED_EXACT_CERTIFICATE_RECOMPUTED"
            if row["pure_execution"] == "REUSED"
            else "NOT_A_SUPPORTED_CACHE_HIT"
        )
        if row["cache_validation"] != expected_validation:
            raise ValueError("REVISION_CACHE_VALIDATION_STATUS")
        for field in (
            "previous_assertion_id",
            "previous_fingerprint",
            "pure_stage",
            "parent_stage",
            "historical_event",
        ):
            if row[field] is not None:
                require_digest(row[field])
    canonical_bytes(plan)


def prepare_formalizations(
    ir: dict[str, Any],
    plan: dict[str, Any],
    store: Any,
    analysis: str,
    implementation: str,
    previous: dict[str, Any] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Load verified pure stage bytes or actually compute the affected assertion."""
    from .formalize import formalize_assertion, rebind_formalization

    rows = []
    manifests = []
    reused = []
    plans = {row["assertion_id"]: row for row in plan["rows"]}
    prior_stages = {
        row["inputs"].get("assertion"): row
        for row in (previous or {}).get("stage_manifests", [])
        if row["stage"] == "formalization"
    }
    for element in ir["elements"]:
        if element["kind"] != "ASSERTION":
            continue
        decision = plans[element["id"]]
        key = {
            "revision": ir["revision"],
            "analysis": analysis,
            "stage": "formalization",
            "inputs": {"assertion": element["id"], "dependencies": decision["fingerprint"]},
            "implementation": implementation,
        }
        cached = store.load_stage(**key)
        parent = None
        row = None
        if cached is not None:
            row = cached["output"]["row"]
            decision["pure_execution"] = "REUSED"
        elif decision["reuse_eligible"] and previous is not None:
            prior_stage = prior_stages.get(decision["previous_assertion_id"])
            if prior_stage is not None:
                loaded = store.stage_by_id(prior_stage["id"])
                if (
                    loaded["manifest"] != prior_stage
                    or loaded["output"]["fingerprint"] != decision["fingerprint"]
                ):
                    raise ValueError("REVISION_STAGE_DEPENDENCY_MISMATCH")
                if loaded["manifest"]["outcome"] == "PASS":
                    proposed = rebind_formalization(
                        loaded["output"]["row"], previous["document_ir"], ir, element
                    )
                    if proposed["status"] == "SUPPORTED":
                        row = proposed
                        parent = prior_stage["id"]
                        decision["pure_execution"] = "REUSED"
        if row is None:
            row = formalize_assertion(ir, element)
            decision["pure_execution"] = "EXECUTED"
        if cached is None:
            valid_parser = ir.get("parser", {}).get("execution") not in {
                "ERROR",
                "TIMEOUT",
                "UNAVAILABLE",
            }
            manifest = store.commit_stage(
                **key,
                output={"row": row, "fingerprint": decision["fingerprint"], "parent_stage": parent},
                outcome="PASS"
                if row["status"] == "SUPPORTED" and valid_parser
                else "NOT_APPLICABLE",
            )
        else:
            manifest = cached["manifest"]
            parent = cached["output"]["parent_stage"]
        decision["pure_stage"] = manifest["id"]
        decision["parent_stage"] = parent
        manifests.append(manifest)
        if decision["pure_execution"] == "REUSED":
            decision["cache_validation"] = "BOUNDED_EXACT_CERTIFICATE_RECOMPUTED"
            reused.append(manifest["id"])
        rows.append(deepcopy(row))
    return rows, manifests, reused


def historical_candidates(previous: dict[str, Any] | None, plan: dict[str, Any]) -> dict[str, Any]:
    """Offer immutable old executions for independent, current authority validation."""
    if previous is None:
        return {}
    prior_rows = {row["assertion_id"]: row for row in previous.get("formalizations", [])}
    events = {row["event"]["id"]: row for row in previous.get("execution_events", [])}
    result = {}
    for decision in plan["rows"]:
        if not decision["reuse_eligible"]:
            continue
        row = prior_rows.get(decision["previous_assertion_id"], {})
        event = events.get(row.get("execution_event"))
        if (
            event is not None
            and event["event"]["outcome"] == "VERIFIED"
            and event.get("envelope") is not None
        ):
            result[decision["assertion_id"]] = {
                "parent_run_id": previous["run_manifest"]["run_id"],
                "parent_revision": previous["input_manifest"]["revision"],
                "binding": row["binding"],
                "obligation": row["obligation"],
                "execution": event,
            }
        elif row.get("historical_execution") is not None:
            result[decision["assertion_id"]] = deepcopy(row["historical_execution"])
    return result


def record_formal_execution(plan: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    by_id = {row["assertion_id"]: row for row in rows}
    for decision in plan["rows"]:
        row = by_id[decision["assertion_id"]]
        if "historical_execution" in row:
            decision["formal_execution"] = "HISTORICAL_REUSE"
            decision["historical_event"] = row["historical_execution"]["execution"]["event"]["id"]
        elif "execution_event" in row:
            decision["formal_execution"] = "EXECUTED"
