from __future__ import annotations

from pathlib import Path

from proofmap.campaign.operations import plan_campaign, tasks
from proofmap.campaign.reports import campaign_report_model
from proofmap.campaign.service import add_goal, capabilities, coverage, ingest, initialize
from proofmap.campaign.store import CampaignStore


def test_actual_unresolved_roles_have_one_campaign_inventory_denominator(tmp_path: Path) -> None:
    sources = tmp_path / "manuscripts"
    sources.mkdir()
    statements = {
        "unknown.tex": ("unresolved", "Unresolved", "For every integer $n$, $n+0=n$."),
        "unsupported.tex": ("theorem", "Theorem", "For every real number $x$, $x+0=x$."),
        "supported.tex": (
            "theorem",
            "Theorem",
            r"For every $x\in\mathbb{Z}$, \[(x+1)^2=x^2+2x+1.\]",
        ),
    }
    for name, (environment, heading, statement) in statements.items():
        (sources / name).write_text(
            "\\documentclass{article}\n\\newtheorem{"
            + environment
            + "}{"
            + heading
            + "}\n\\begin{document}\n\\begin{"
            + environment
            + "}"
            + statement
            + "\\end{"
            + environment
            + "}\n\\end{document}\n",
            encoding="utf-8",
        )
    store = CampaignStore(tmp_path / "store")
    try:
        campaign_id = initialize(store, "Unknown roles", "Preserve visible source gaps")[
            "campaign_id"
        ]
        intake = ingest(store, campaign_id, sources)
        assert len(intake["manuscripts"]) == 3
        assert all(row["exit_code"] == 0 for row in intake["manuscripts"])
        add_goal(store, campaign_id, question="Does this unanchored question have a proof?")
        view = coverage(store, campaign_id)
        plan = plan_campaign(store, campaign_id)
        report = campaign_report_model(store, campaign_id)
        capability = capabilities(store, campaign_id)

        assert view["unresolved_regions"] == 1
        assert report["coverage"]["unresolved_regions"] == 1
        assert sum(paper["counts"]["unresolved_regions"] for paper in plan["papers"]) == 1
        assert capability["coverage"]["unresolved_regions"] == 1
        assert view["discovered"] == report["coverage"]["discovered"] == 3
        assert view["supported"] == report["coverage"]["supported"] == 1
        assert len(view["inventory"]) == 3
        assert report["goals"][0]["state"] == "RESEARCHER_QUESTION"
        assert any(
            blocker["code"] == "UNANCHORED_RESEARCH_QUESTION" for blocker in plan["blockers"]
        )
        assert view["full_verification"] is False and view["authority_evaluated"] is False
        assert report["coverage"]["verified"] == report["coverage"]["accepted"] == 0
        assert report["graph"]["closure_authority"] is False
        assert plan["authority"] == "PLANNING_ONLY" and tasks(store, campaign_id) == []
    finally:
        store.close()
