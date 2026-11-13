"""Execution coverage and finding semantics are distinct from proof outcomes."""

from copy import deepcopy

import pytest

from proofmap.paper_checkers import make_result, required_failures, validate_result


def test_execution_partial_is_allowed_only_by_explicit_trusted_profile():
    rows = [make_result("syntax", "PASS"), make_result("semantic", "PARTIAL")]
    assert required_failures(rows, ["syntax", "semantic"]) == ["semantic"]
    assert not required_failures(rows, ["syntax", "semantic"], allow_partial={"semantic"})
    assert rows[1]["coverage"]["attempted"] is None
    assert rows[1]["trust"] == "LOCAL_ANALYSIS_NOT_PROOF"


@pytest.mark.parametrize(
    "status",
    ["ERROR", "TIMEOUT", "UNAVAILABLE", "REJECTED", "COUNTEREXAMPLE", "NOT_RUN", "UNSUPPORTED"],
)
def test_distinct_nonpass_states_never_satisfy_pass_or_partial_policy(status):
    row = make_result("formal", status)
    assert row["execution_status"] == status
    assert required_failures([row], ["formal"], allow_partial={"formal"}) == ["formal"]


def test_findings_retain_classification_source_remediation_and_certificate_binding():
    row = make_result(
        "exact",
        "COUNTEREXAMPLE",
        [
            {
                "code": "COUNTEREXAMPLE",
                "classification": "EXACT_COUNTEREXAMPLE",
                "source": "claim",
                "detail": "x=0 violates candidate equality",
            }
        ],
        revision="a" * 64,
        source_ids=["claim"],
        certificate_references=["b" * 64],
        coverage={
            "attempted": 1,
            "eligible": 1,
            "supported": 1,
            "denominator": "source-derived exact equalities",
            "reason": None,
        },
    )
    assert row["findings"][0]["classification"] == "EXACT_COUNTEREXAMPLE"
    assert row["findings"][0]["remediation"]
    assert row["certificate_references"] == ["b" * 64]
    assert not row["blocking_eligible"]
    validate_result(row)


@pytest.mark.parametrize(
    "mutation", ["future", "boolean", "overflow", "nan", "unexecuted", "accepted", "certificate"]
)
def test_checker_record_rejects_malformed_or_impossible_claims(mutation):
    row = deepcopy(make_result("syntax", "PASS"))
    if mutation == "future":
        row["schema_version"] = "2.0"
    elif mutation == "boolean":
        row["coverage"]["eligible"] = True
    elif mutation == "overflow":
        row["coverage"].update(eligible=0, attempted=1)
    elif mutation == "nan":
        row["resource_use"]["seconds"] = float("nan")
    elif mutation == "unexecuted":
        row["execution_status"] = "NOT_RUN"
        row["coverage"]["attempted"] = 1
    elif mutation == "accepted":
        row["trust"] = "ACCEPTED_PROOF"
    else:
        row["certificate_references"] = ["invented"]
    with pytest.raises(ValueError):
        validate_result(row)


def test_duplicate_missing_and_outside_profile_requirements_fail():
    row = make_result("syntax", "PASS")
    with pytest.raises(ValueError, match="DUPLICATE"):
        required_failures([row, row], ["syntax"])
    with pytest.raises(ValueError, match="DUPLICATE"):
        required_failures([row], ["syntax", "syntax"])
    with pytest.raises(ValueError, match="UNKNOWN"):
        required_failures([row], ["missing"])
    with pytest.raises(ValueError, match="OUTSIDE"):
        required_failures([row], ["syntax"], allow_partial={"missing"})


def test_required_stage_cannot_omit_the_versioned_execution_contract():
    with pytest.raises(ValueError, match="CHECKER_RESULT"):
        required_failures([{"checker": "formal", "execution_status": "PASS"}], ["formal"])


def test_whole_document_checker_uses_parser_bound_not_model_chunk_bound():
    from proofmap.paper_sources import MAX_ELEMENTS

    row = make_result("syntax", "PASS", source_ids=[f"source-{i}" for i in range(270)])
    assert len(row["source_ids"]) == 270
    with pytest.raises(ValueError, match="CHECKER_RESULT"):
        make_result("syntax", "PASS", source_ids=[f"source-{i}" for i in range(MAX_ELEMENTS + 1)])


@pytest.mark.parametrize("invalid", [True, False, ["syntax"], {False}])
def test_partial_profile_rejects_wrong_types(invalid):
    with pytest.raises(ValueError, match="PARTIAL_PROFILE"):
        required_failures([make_result("syntax", "PASS")], ["syntax"], allow_partial=invalid)
