"""Driver regression checks; source-mode results cannot qualify installed execution."""

import json
from copy import deepcopy

import pytest

from scripts.paper_alpha_offline import validate_outcomes


@pytest.fixture
def source_outcomes(_alpha_offline_outcomes_session):
    return json.loads(_alpha_offline_outcomes_session)


def test_offline_scenarios_execute_public_interfaces_and_remain_source_evidence(source_outcomes):
    validate_outcomes(source_outcomes, require_installed=False)
    assert source_outcomes["profile"] == "source-checkout-test"
    assert source_outcomes["scenarios"]["C"]["required_formal_exit"] == 3
    assert source_outcomes["scenarios"]["D"]["provider"]["requests"][0]["path"] == "/api/chat"
    assert source_outcomes["scenarios"]["D"]["override"]["accepted_claims"] == 0
    with pytest.raises(ValueError, match="installed-wheel"):
        validate_outcomes(source_outcomes)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda v: v["scenarios"]["C"].update(offline_assertions=True),
        lambda v: v["scenarios"]["C"].update(required_formal_exit=0),
        lambda v: v["scenarios"]["C"].update(report_files=[]),
        lambda v: v["scenarios"]["D"].update(resolved_citations=0),
        lambda v: v["scenarios"]["D"]["pdf"]["scan.pdf"].update(finding_codes=[]),
        lambda v: v["scenarios"]["D"]["provider"].update(replayed_candidate_ids=[]),
        lambda v: v["scenarios"]["D"]["provider"].update(authority="VERIFIED"),
        lambda v: v["scenarios"]["D"]["override"].update(derived_raw_ir_digest="0" * 64),
        lambda v: v["scenarios"]["D"]["override"].update(accepted_claims=1),
        lambda v: v["scenarios"]["D"]["override"].update(attribution_authenticated=True),
    ],
)
def test_missing_or_promoted_offline_outcomes_fail(source_outcomes, mutation):
    forged = deepcopy(source_outcomes)
    mutation(forged)
    with pytest.raises(ValueError):
        validate_outcomes(forged, require_installed=False)
