"""Import contracts reject self-consistent hash edits; schema validity is not trust."""

from copy import deepcopy
from pathlib import Path

import pytest

from proofmap.integrity import digest, write_json
from proofmap.paper import ci, load_bundle
from proofmap.paper_checkers import make_result
from proofmap.paper_records import paper_record_issues, validate_paper_records
from proofmap.paper_store import validate_bundle
from proofmap.schema import validate


@pytest.fixture(scope="module")
def source_bundle(tmp_path_factory):
    folder = tmp_path_factory.mktemp("source-contract")
    result, code = ci(
        Path("tests/fixtures/papers/train/basic.tex"),
        folder / "out",
        folder / "store",
        config={"exact_checks": [{"label": "eq:one", "left": "1+1", "right": "2"}]},
    )
    assert code == 0
    return result


def rehash(bundle):
    bundle["run_manifest"]["bundle_digests"] = {
        name: digest("paper-bundle-component.v1", value)
        for name, value in bundle.items()
        if name != "run_manifest"
    }


def test_current_bundle_validates_all_public_tables_without_authority(source_bundle):
    validate_paper_records(source_bundle)
    validate_bundle(source_bundle)
    assert not paper_record_issues(source_bundle)
    assert not validate("pipeline-assessment", source_bundle["assessment"])
    assert source_bundle["assessment"]["outcomes"]["coverage"]["accepted_claims"] == 0
    assert not source_bundle["assessment"]["closure"]["closed"]


@pytest.mark.parametrize(
    "mutation, code",
    [
        ("negative-duration", "PAPER_RECORD_SCHEMA"),
        ("boolean-exit", "PAPER_RECORD_SCHEMA"),
        ("unknown-run-field", "PAPER_RECORD_SCHEMA"),
        ("new-version", "PAPER_RECORD_SCHEMA"),
        ("missing-duration", "RUN_RECORD_INCOMPLETE"),
        ("missing-extractor-contract", "RUN_EXTRACTOR_CONTRACT_MISSING"),
        ("missing-context", "RUN_CONTEXT_MISSING"),
        ("invented-source-proof", "PAPER_RECORD_SCHEMA"),
        ("invented-dimension", "PAPER_RECORD_SCHEMA"),
        ("role", "ASSERTION_RECORD_CONTEXT"),
        ("proof-association", "ASSERTION_PROOF_ASSOCIATION"),
        ("source-context", "ASSERTION_SOURCE_CONTEXT"),
        ("symbol-content", "SYMBOL_SOURCE_PROJECTION"),
        ("missing-symbol", "PAPER_RECORD_TABLE_INCOMPLETE"),
        ("missing-assertion", "PAPER_RECORD_TABLE_INCOMPLETE"),
        ("missing-field", "ASSERTION_RECORD_INCOMPLETE"),
        ("acceptance-count", "PIPELINE_ASSESSMENT_COUNTS"),
        ("fraction", "PIPELINE_ASSESSMENT_COUNTS"),
        ("source-closure", "PIPELINE_ASSESSMENT_CLOSURE"),
        ("required-stages", "PIPELINE_ASSESSMENT_REQUIRED_STAGES"),
        ("pipeline-status", "PIPELINE_ASSESSMENT_STATUS"),
        ("exact-outcome", "PIPELINE_ASSESSMENT_CHECKER_OUTCOME"),
        ("finding-certificate", "FINDING_CERTIFICATE_BINDING"),
    ],
)
def test_rehashed_malformed_import_cannot_gain_status(source_bundle, mutation, code):
    bundle = deepcopy(source_bundle)
    run, assertions = bundle["run_manifest"], bundle["assertions"]
    summary = bundle["assessment"]
    if mutation == "negative-duration":
        run["duration_seconds"] = -1
    elif mutation == "boolean-exit":
        run["exit_code"] = False
    elif mutation == "unknown-run-field":
        run["trusted"] = True
    elif mutation == "new-version":
        run["schema_version"] = "2.0"
    elif mutation == "missing-duration":
        del run["duration_seconds"]
    elif mutation == "missing-extractor-contract":
        del run["analysis_context"]["extractor_contract"]
    elif mutation == "missing-context":
        del run["analysis_context"]
    elif mutation == "invented-source-proof":
        assertions[0]["status"] = "VERIFIED"
    elif mutation == "invented-dimension":
        assertions[0]["assessment"]["deductive"] = "PASS"
    elif mutation == "role":
        assertions[0]["role"] = "CONJECTURE"
    elif mutation == "proof-association":
        next(row for row in assertions if row["proof_ids"])["proof_ids"] = []
    elif mutation == "source-context":
        next(row for row in assertions if row["source_context"])["source_context"] = []
    elif mutation == "symbol-content":
        bundle["symbols"][0] = deepcopy(bundle["symbols"][0])
        bundle["symbols"][0]["text"] = "Invented definition"
    elif mutation == "missing-symbol":
        bundle["symbols"].pop()
    elif mutation == "missing-assertion":
        assertions.pop()
    elif mutation == "missing-field":
        del assertions[0]["hypotheses"]
    elif mutation == "acceptance-count":
        summary["outcomes"]["coverage"]["accepted_claims"] = 1
    elif mutation == "fraction":
        summary["outcomes"]["coverage"]["kernel_verified_fraction"] = 0.5
    elif mutation == "source-closure":
        summary["closure"]["closed"] = [assertions[0]["id"]]
    elif mutation == "required-stages":
        summary["missing_required_stages"] = ["formal"]
    elif mutation == "pipeline-status":
        summary["outcomes"]["pipeline_execution"] = "FAIL"
        run["exit_code"] = 1
    elif mutation == "exact-outcome":
        summary["outcomes"]["computational"] = "FAIL"
    else:
        next(row for row in bundle["findings"] if "certificate_digest" in row)[
            "certificate_digest"
        ] = "0" * 64
    rehash(bundle)
    with pytest.raises(ValueError, match=code):
        validate_bundle(bundle)
    assert paper_record_issues(bundle)


def test_load_bundle_rejects_rehashed_aggregate_acceptance(source_bundle, tmp_path):
    bundle = deepcopy(source_bundle)
    bundle["assessment"]["outcomes"]["coverage"]["accepted_claims"] = 1
    rehash(bundle)
    for name, value in bundle.items():
        write_json(tmp_path / (name + ".json"), value)
    with pytest.raises(ValueError, match="PIPELINE_ASSESSMENT_COUNTS"):
        load_bundle(tmp_path)


def test_unmarked_historical_tables_may_omit_measurements_without_fabricating_them(source_bundle):
    bundle = deepcopy(source_bundle)
    bundle["run_manifest"].pop("record_contract_version")
    bundle["run_manifest"].pop("analysis_context")
    bundle["symbols"] = []
    for assertion in bundle["assertions"]:
        for name in ("role", "proof_ids", "assessment", "source_context"):
            assertion.pop(name)
    validate_paper_records(bundle)
    bundle["assertions"][0]["status"] = "VERIFIED"
    with pytest.raises(ValueError, match="PAPER_RECORD_SCHEMA"):
        validate_paper_records(bundle)


@pytest.mark.parametrize("mutation", [None, "status", "event", "diagnostic"])
def test_invalid_extractor_input_is_only_preserved_as_failed_diagnostic(source_bundle, mutation):
    bundle = deepcopy(source_bundle)
    run = bundle["run_manifest"]
    run["analysis_context"]["extractor_mode"] = "configured"
    run["analysis_context"]["config"]["extractor"] = {}
    bundle["findings"].append(
        {"code": "EXTRACTOR_ERROR", "classification": "INFRASTRUCTURE", "blocking_eligible": False}
    )
    summary = bundle["assessment"]
    summary["checkers"] = [
        make_result("model-extraction", "ERROR") if row["checker"] == "model-extraction" else row
        for row in summary["checkers"]
    ]
    summary["outcomes"]["pipeline_execution"] = "ERROR"
    run["exit_code"] = 3
    if mutation is None:
        validate_paper_records(bundle)
        return
    if mutation == "status":
        summary["checkers"] = [
            make_result("model-extraction", "PASS") if row["checker"] == "model-extraction" else row
            for row in summary["checkers"]
        ]
    elif mutation == "event":
        bundle["extraction_events"] = [{"invented": "successful model result"}]
    else:
        bundle["findings"].pop()
    with pytest.raises(ValueError, match="EXTRACTOR_CONFIG_FIELDS"):
        validate_paper_records(bundle)


@pytest.mark.parametrize("drop_summary_version", [False, True])
@pytest.mark.parametrize("claim", ["accepted", "verified", "closure", "fidelity", "boolean-count"])
def test_removed_version_markers_cannot_bypass_present_authority_projections(
    source_bundle, drop_summary_version, claim
):
    bundle = deepcopy(source_bundle)
    bundle["run_manifest"].pop("record_contract_version")
    if drop_summary_version:
        bundle["assessment"].pop("schema_version")
    outcomes = bundle["assessment"]["outcomes"]
    if claim == "accepted":
        outcomes["coverage"]["accepted_claims"] = 1
    elif claim == "verified":
        outcomes["coverage"]["kernel_verified"] = 1
        outcomes["kernel_verification"] = "PASS"
    elif claim == "closure":
        bundle["assessment"]["closure"]["closed"] = [bundle["assertions"][0]["id"]]
    elif claim == "fidelity":
        outcomes["formal_statement_fidelity"] = "APPROVE"
    else:
        outcomes["coverage"]["accepted_claims"] = False
    rehash(bundle)
    with pytest.raises(ValueError, match="PIPELINE_ASSESSMENT_"):
        validate_bundle(bundle)


def test_historical_import_can_omit_unknown_measurements_and_old_checker_metadata(source_bundle):
    bundle = deepcopy(source_bundle)
    bundle["run_manifest"].pop("record_contract_version")
    bundle["run_manifest"].pop("analysis_context")
    for name in ("revision_plan", "assessment_records", "action_plan"):
        bundle.pop(name)
    summary = bundle["assessment"]
    summary.pop("schema_version")
    summary["outcomes"].pop("coverage")
    summary["outcomes"].pop("kernel_verification")
    summary["checkers"] = [
        {key: row[key] for key in ("checker", "execution_status", "findings")}
        for row in summary["checkers"]
    ]
    rehash(bundle)
    validate_bundle(bundle)
    summary["outcomes"]["coverage"] = {"accepted_claims": 1}
    rehash(bundle)
    with pytest.raises(ValueError, match="PIPELINE_ASSESSMENT_COUNTS"):
        validate_bundle(bundle)
