"""Validate installed scenario diagnostics without rerunning their producers."""

from __future__ import annotations

import argparse
import base64
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError("ALPHA_SCENARIO: " + reason)


def validate_isolated(value: dict[str, Any]) -> None:
    """Reauthenticate actual proof facts and current reviews in revision scenario B."""
    from proofmap.attempts import FormalObligation
    from proofmap.evidence_adapter import assess_binding
    from proofmap.evidence_records import FormalizationBinding, VerifierProfile
    from proofmap.formalize import definition_context, validate_formalization
    from proofmap.integrity import artifact_digest, canonical_bytes, digest, relative_path
    from proofmap.paper import assertion_layer
    from proofmap.paper_revision import dependency_snapshot, validate_revision_plan
    from proofmap.paper_sources import LocatorValidationSession, validate_locator
    from proofmap.paper_store import _validate_lexical_context
    from proofmap.schema import validate
    from proofmap.source_semantics import validate_source_semantics
    from proofmap.trust import authenticated_record

    row = value["alpha_revision"]
    require(row["status"] == "PASS", "revision scenario failed")
    require(row["authentication"] == "EPHEMERAL_TEST_AUTHORITY_ONLY", "test authority label")
    profile = VerifierProfile.from_dict(value["profile"])
    trust, timestamp = row["trust_store"], row["evaluation_time"]
    for name in ("initial_ir", "revised_ir", "unresolved_ir"):
        require(not validate("document-ir", row[name]), "source IR schema")
        validate_source_semantics(row[name])
    for phase in ("initial", "revised", "unresolved"):
        ir = row[phase + "_ir"]
        manifest = row[phase + "_input_manifest"]
        encoded = row[phase + "_sources"]
        require(not validate("paper-input", manifest), "input manifest schema")
        require(
            isinstance(encoded, dict)
            and len(encoded) == 1
            and all(isinstance(value, str) and len(value) <= 100_000 for value in encoded.values()),
            "bounded original source",
        )
        sources = {
            relative_path(name): base64.b64decode(value, validate=True)
            for name, value in encoded.items()
        }
        declared = {item["path"]: item for item in manifest["artifacts"]}
        require(
            set(sources) == set(declared) and len(declared) == len(manifest["artifacts"]),
            "source artifact set",
        )
        require(
            manifest["entrypoint"] in sources
            and manifest["revision"]
            == ir["revision"]
            == digest(
                "paper-manifest.v1",
                {"entrypoint": manifest["entrypoint"], "artifacts": manifest["artifacts"]},
            ),
            "source manifest revision",
        )
        require(
            all(
                declared[name]["sha256"] == artifact_digest(raw)
                and declared[name]["size"] == len(raw)
                for name, raw in sources.items()
            ),
            "source artifact digest",
        )
        locator_session = LocatorValidationSession()
        for element in ir["elements"]:
            locator = element["locator"]
            require(
                locator["format"] == "tex"
                and element["revision"] == ir["revision"]
                and element["id"]
                == digest(
                    "source-element.v1",
                    {"revision": ir["revision"], "locator": locator, "kind": element["kind"]},
                ),
                "source element identity",
            )
            validate_locator(locator, sources, element["text"], session=locator_session)
        assertions = {a["id"]: a for a in assertion_layer(ir)[0]}
        elements = {element["id"]: element for element in ir["elements"]}
        require(len(elements) == len(ir["elements"]), "duplicate source element")
        _validate_lexical_context(ir, elements, declared, sources)
        formals = row[phase + "_formalizations"]
        require(
            len(formals) == len(assertions)
            and {formal["assertion_id"] for formal in formals} == set(assertions),
            "formal/source subject set",
        )
        for formal in formals:
            validate_formalization(formal)
            element = elements[formal["assertion_id"]]
            require(formal["revision"] == ir["revision"], "formal/source revision")
            if formal["status"] != "SUPPORTED":
                require(
                    formal["source_locators"] == [element["locator"]], "unsupported source locator"
                )
                continue
            binding = FormalizationBinding.from_dict(formal["binding"])
            context = definition_context(ir, element)
            locators = [
                element["locator"],
                *[elements[dependency["id"]]["locator"] for dependency in context["dependencies"]],
            ]
            require(
                binding.revision_id == ir["revision"]
                and binding.assertion_digest == digest("assertion.v1", assertions[element["id"]])
                and canonical_bytes(binding.source_locators) == canonical_bytes(locators),
                "formal/source binding",
            )
    validate_revision_plan(row["revision_plan"], row["revised_ir"])
    validate_revision_plan(row["unresolved_plan"], row["unresolved_ir"])
    decisions = {r["label"]: r for r in row["revision_plan"]["rows"]}
    require(set(decisions) == {"branch-a", "branch-b"}, "two independent source branches")
    a, b = decisions["branch-a"], decisions["branch-b"]
    prior = dependency_snapshot(row["initial_ir"])
    require(
        row["revision_plan"]["parent_revision"] == row["initial_ir"]["revision"],
        "prior revision lineage",
    )
    for decision in decisions.values():
        previous = prior.get(decision["previous_assertion_id"])
        require(
            previous is not None
            and previous["logical_id"] == decision["logical_id"]
            and previous["fingerprint"] == decision["previous_fingerprint"],
            "prior dependency fingerprint",
        )
    require(
        a["fingerprint"] != a["previous_fingerprint"]
        and "DEFINITION_OR_MACRO_CHANGED" in a["changes"],
        "actual A definition change",
    )
    require(a["pure_execution"] == "EXECUTED" and not a["reuse_eligible"], "A invalidation")
    require(
        b["pure_execution"] == "REUSED"
        and b["cache_validation"] == "BOUNDED_EXACT_CERTIFICATE_RECOMPUTED"
        and b["formal_execution"] == "HISTORICAL_REUSE"
        and b["reuse_eligible"]
        and b["fingerprint"] == b["previous_fingerprint"]
        and bool(b["parent_stage"]),
        "B eligible completed reuse",
    )
    dimensions = ("ingested", "formalized", "verified", "reviewed", "accepted")
    for phase, vector in (
        ("initial_before_review", (2, 2, 2, 0, 0)),
        ("initial_after_review", (2, 2, 2, 2, 2)),
        ("revised_before_review", (2, 2, 2, 0, 0)),
        ("revised_after_review", (2, 2, 2, 2, 2)),
    ):
        require(
            all(type(row[phase][key]) is int for key in dimensions)
            and tuple(row[phase][key] for key in dimensions) == vector,
            "outcome vector " + phase,
        )
    require(
        row["after_revocation"]["verified"] == row["after_revocation"]["accepted"] == 0,
        "revoked outcome",
    )
    old_events, current_events = row["initial_execution_events"], row["revised_execution_events"]
    require(
        type(row["initial_execution_count"]) is int
        and type(row["revised_execution_count"]) is int
        and row["initial_execution_count"] == len(old_events) == 2
        and row["revised_execution_count"] == len(current_events) == 1,
        "measured execution count",
    )
    require(row["historical_events_unchanged"] is True, "immutable event history")
    require(
        type(row["stale_reviews_rejected"]) is int and row["stale_reviews_rejected"] == 4,
        "stale review rejection count",
    )
    require(len(row["initial_reviews"]) == len(row["current_reviews"]) == 4, "review count")
    require(
        len(row["initial_formalizations"]) == len(row["revised_formalizations"]) == 2,
        "formalization count",
    )
    current_b = next(
        r for r in row["revised_formalizations"] if r["assertion_id"] == b["assertion_id"]
    )
    require(current_b == row["reused_formalization"], "reused row substitution")
    history = current_b["historical_execution"]
    require("execution_event" not in current_b, "historical fact cannot claim a fresh event")
    require(history["execution"] in old_events, "historical event substitution")
    require(history["binding"] != current_b["binding"], "fresh source binding required")
    require(
        history["parent_run_id"] == row["revision_plan"]["parent_run"]
        and history["parent_revision"] == row["initial_ir"]["revision"],
        "historical run lineage",
    )
    require(
        any(
            formal.get("binding") == history["binding"]
            and formal.get("obligation") == history["obligation"]
            for formal in row["initial_formalizations"]
        ),
        "historical source material",
    )
    require(
        "x = 2" in current_b["obligation"]["statement"]
        and "\u2192" in current_b["obligation"]["statement"],
        "antecedent lost",
    )
    for phase, formals, events, reviews in (
        ("initial", row["initial_formalizations"], old_events, row["initial_reviews"]),
        ("revised", row["revised_formalizations"], current_events, row["current_reviews"]),
    ):
        for formal in formals:
            binding = FormalizationBinding.from_dict(formal["binding"])
            obligation = FormalObligation.from_dict(formal["obligation"])
            event = next(
                (e for e in events if e["event"]["binding_digest"] == binding.digest), None
            )
            history = formal.get("historical_execution")
            require((event is None) != (history is None), "unique execution source")
            if event is not None:
                require(
                    authenticated_record(event["envelope"]) == event["event"], "event substitution"
                )
            current_reviews = [
                e for e in reviews if authenticated_record(e)["binding_digest"] == binding.digest
            ]
            require(len(current_reviews) == 2, "two exact-bound review dimensions")
            envelope = event["envelope"] if event else None

            def assessment(
                authority: dict[str, Any],
                decisions: list[Any],
                current_binding: FormalizationBinding = binding,
                current_obligation: FormalObligation = obligation,
                execution: Any = envelope,
                historical: Any = history,
            ) -> Any:
                return assess_binding(
                    current_binding,
                    current_obligation,
                    profile,
                    execution,
                    decisions,
                    authority,
                    evaluation_time=timestamp,
                    historical_execution=historical,
                )

            require(
                assessment(trust, []).assessment == "REVIEW_REQUIRED", "unreviewed proof status"
            )
            require(
                assessment(trust, current_reviews).assessment == "ACCEPTED_UNDER_POLICY",
                "authenticated current reviews",
            )
            revoked = deepcopy(trust)
            for key in revoked["keys"]:
                if "verification-execution" in key["roles"]:
                    key["revoked"] = True
            require(
                assessment(revoked, current_reviews).formal_status == "UNVERIFIED",
                "current revocation policy",
            )
            if phase == "revised":
                require(
                    assessment(trust, row["initial_reviews"]).assessment != "ACCEPTED_UNDER_POLICY",
                    "historical reviews cannot authorize current source",
                )
    unresolved = next(r for r in row["unresolved_plan"]["rows"] if r["label"] == "branch-a")
    require(
        type(row["unresolved_execution_count"]) is int
        and row["unresolved_execution_count"] == 0
        and row["unresolved_execution_events"] == []
        and type(row["unresolved_exit_code"]) is int
        and row["unresolved_exit_code"] == 1,
        "unknown context produces no execution and fails full formal coverage",
    )
    require(
        not unresolved["reuse_eligible"]
        and unresolved["pure_execution"] == "EXECUTED"
        and any("UNRESOLVED" in reason for reason in unresolved["reasons"]),
        "unresolved context fallback",
    )
    unresolved_a = next(
        r
        for r in row["unresolved_formalizations"]
        if r["assertion_id"] == unresolved["assertion_id"]
    )
    require(
        unresolved_a["status"] != "SUPPORTED" and "historical_execution" not in unresolved_a,
        "unresolved assertion cannot inherit proof",
    )


def main() -> int:
    from proofmap.integrity import load_json, write_json
    from scripts.alpha_evidence import identity
    from scripts.check_alpha_acceptance import ROOT, _artifact

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kind", required=True, choices=("alpha-isolated-scenarios", "alpha-offline-scenarios")
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    require(args.source.resolve() != args.out.resolve(), "distinct source and output required")
    expected = identity(ROOT, ROOT / "acceptance/paper_ci_alpha.json")
    _artifact(args.kind, args.source, expected)
    write_json(args.out, load_json(args.source))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
