"""Public operator commands retain identity and authority across a local workflow."""

import pytest

from proofmap.cli import main
from proofmap.integrity import load_json, write_json


def test_public_offline_campaign_workflow_and_revision(tmp_path, capsys):
    store = tmp_path / "store"
    serial = 0

    def invoke(*arguments, code=0, target_store=store):
        nonlocal serial
        serial += 1
        output = tmp_path / f"command-{serial}.json"
        result = main(
            ["campaign", *map(str, arguments), "--store", str(target_store), "--out", str(output)]
        )
        assert result == code, capsys.readouterr()
        return load_json(output) if output.is_file() else None

    source = tmp_path / "paper.tex"
    template = r"\begin{theorem}\label{identity}For every $x\in\mathbb{Z}$, \[(x+1)^2=x^2+2x+1.\]\end{theorem}\begin{proof}Expand.\end{proof}"
    source.write_text(template, encoding="utf-8")
    policy = invoke("policy", "--source-root", tmp_path, "--max-tasks", 5)
    policy_path = tmp_path / "policy.json"
    write_json(policy_path, policy)
    created = invoke(
        "init",
        "--name",
        "CLI audit",
        "--objective",
        "Follow exact source revisions",
        "--policy",
        policy_path,
    )
    cid = created["campaign_id"]
    assert not created["dispatch_authorized"]
    assert invoke("list")[0]["campaign"]["id"] == cid
    capability = invoke("capabilities", cid)
    assert (
        capability["host_fallback"] is False
        and capability["execution_authority"] == "NOT_EVALUATED"
    )
    intake = invoke("ingest", cid, source, "--paper-id", "paper")
    run = intake["manuscripts"][0]["run_id"]
    before = intake["snapshot_id"]
    assert invoke("select", cid, "--run", run)["id"] == before
    goal = invoke("goals", "add", cid, "--run", run, "--label", "identity")
    question = invoke("goals", "add", cid, "--question", "Does rational quantification fit?")
    assert question["origin"] == "RESEARCHER_QUESTION" and question["target"] is None
    assert len(invoke("goals", "list", cid)) == 2
    invoke("goals", "add", cid, "--run", run, "--label", "identity", code=2)
    assert invoke("inspect", cid)["coverage"]["accepted"] == 0
    import test_execution as fixture

    profile_path = tmp_path / "profile.json"
    authority_path = tmp_path / "authority.json"
    write_json(profile_path, fixture.profile().to_dict())
    write_json(authority_path, {"schema_version": "2.0", "keys": []})
    review_args = [
        "--run",
        run,
        "--assertion",
        goal["target"]["assertion_id"],
        "--execution-profile",
        profile_path,
        "--dimension",
        "source-fidelity",
        "--reviewer-id",
        "explicit-reviewer",
        "--reason",
        "Read original source and formalization",
    ]
    abstained = invoke("review-decision", cid, *review_args, "--decision", "ABSTAIN")
    assert abstained["decision"] == "ABSTAIN"
    draft = invoke("review-decision", cid, *review_args, "--decision", "APPROVE")
    assert draft["decision"] == "APPROVE"
    draft_path = tmp_path / "unsigned-review.json"
    write_json(draft_path, draft)
    invoke(
        "review-apply",
        cid,
        "--run",
        run,
        "--review",
        draft_path,
        "--execution-profile",
        profile_path,
        "--trust-store",
        authority_path,
        "--evaluation-time",
        "2026-10-02T00:00:00Z",
        code=2,
    )
    assessment = invoke(
        "assess",
        cid,
        "--execution-profile",
        profile_path,
        "--trust-store",
        authority_path,
        "--evaluation-time",
        "2026-10-02T00:00:00Z",
    )
    assert assessment["counts"]["accepted"] == assessment["counts"]["verified"] == 0
    plan = invoke("plan", cid, "--formal-scope", "selected")
    assert plan["authority"] == "PLANNING_ONLY" and invoke("tasks", cid) == []
    plan_path = tmp_path / "plan.json"
    write_json(plan_path, plan)
    authorization = invoke("authorize", cid, "--plan", plan_path, "--policy", policy_path)
    again = invoke("authorize", cid, "--plan", plan_path, "--policy", policy_path)
    assert {t["task_id"] for t in authorization["tasks"]} == {t["task_id"] for t in again["tasks"]}
    tasks = invoke("tasks", cid)
    check = next(t for t in tasks if t["state"] == "QUEUED")
    invoke("cancel", check["task_id"])
    assert (
        next(t for t in invoke("tasks", cid) if t["task_id"] == check["task_id"])["state"]
        == "CANCELLED"
    )
    invoke("retry", check["task_id"], code=2)
    packets = invoke("review-packet", cid)
    # review-packet owns an output directory, not the ordinary JSON destination.
    assert packets is None
    recovered = invoke("recover", cid)
    assert recovered == []
    stage = invoke(
        "request-stage",
        cid,
        "--kind",
        "REFRESH_REPORT",
        "--run",
        run,
        "--assertion",
        goal["target"]["assertion_id"],
        "--policy",
        policy_path,
    )
    assert stage["task_id"]
    finished = invoke("run", cid, "--max-tasks", 1)
    assert finished["outcomes"][0]["state"] == "SUCCEEDED"
    assert invoke("inspect", cid)["coverage"]["verified"] == 0
    old_snapshot = invoke("inspect", cid)["snapshot"]["id"]
    source.write_text(template.replace("Expand.", "Expand the two factors."), encoding="utf-8")
    revised = invoke("ingest", cid, source, "--paper-id", "paper")
    new_run = revised["manuscripts"][0]["run_id"]
    assert new_run != run
    impact = invoke("impact", cid, "--from", old_snapshot, "--to", revised["snapshot_id"])
    assert impact["kind"] == "CampaignRevisionImpact"
    assertion = invoke("inspect", cid)["papers"][0]["claims"][0]["qualified_ref"]["assertion_id"]
    rebound = invoke(
        "goals",
        "rebind",
        cid,
        "--goal",
        goal["id"],
        "--run",
        new_run,
        "--assertion",
        assertion,
        "--reason",
        "Reviewed source-backed revision mapping",
    )
    assert rebound["from_goal"] == goal["id"]
    invoke(
        "relation",
        cid,
        "--left-run",
        run,
        "--left-assertion",
        goal["target"]["assertion_id"],
        "--right-run",
        new_run,
        "--right-assertion",
        assertion,
        "--relation",
        "POSSIBLE_DUPLICATE",
        "--reason",
        "Historical/current source comparison",
        code=2,
    )
    other_source = tmp_path / "natural.tex"
    other_source.write_text(template.replace(r"\mathbb{Z}", r"\mathbb{N}"), encoding="utf-8")
    other_intake = invoke("ingest", cid, other_source, "--paper-id", "natural")
    other_ref = next(
        row["ref"]
        for row in other_intake["coverage"]["inventory"]
        if row["ref"]["paper_id"] == "natural"
    )
    relation = invoke(
        "relation",
        cid,
        "--left-run",
        new_run,
        "--left-assertion",
        assertion,
        "--right-run",
        other_ref["run_id"],
        "--right-assertion",
        other_ref["assertion_id"],
        "--relation",
        "POSSIBLE_DUPLICATE",
        "--reason",
        "Different quantified domains remain separate",
    )
    assert relation["relation"] == "POSSIBLE_DUPLICATE"
    assert invoke("inspect", cid)["graph"]["edges"][-1]["closure_authority"] is False
    assert (
        main(["campaign", "report", cid, "--store", str(store), "--out", str(tmp_path / "report")])
        == 0
    )
    archive = tmp_path / "dossier.zip"
    assert (
        main(
            [
                "campaign",
                "export",
                cid,
                "--store",
                str(store),
                "--include-source",
                "--out",
                str(archive),
            ]
        )
        == 0
    )
    clean = tmp_path / "clean"
    restored = invoke("import", archive, target_store=clean)
    assert not restored["authority_imported"] and restored["tasks_require_fresh_authorization"]
    assert invoke("audit", cid, target_store=clean)["integrity"] == "PASS"
    assert main(["inspect-dossier", str(archive)]) == 0
    assert main(["inspect-dossier", str(archive), "--out", str(tmp_path / "extracted")]) == 0


def test_public_stage_requires_exact_target_and_review_cannot_overwrite_key(tmp_path, capsys):
    import test_execution as fixture

    store = tmp_path / "store"
    created = tmp_path / "created.json"
    assert (
        main(
            [
                "campaign",
                "init",
                "--name",
                "Operator",
                "--objective",
                "Review",
                "--store",
                str(store),
                "--out",
                str(created),
            ]
        )
        == 0
    )
    cid = load_json(created)["campaign_id"]
    policy = tmp_path / "policy.json"
    assert main(["campaign", "policy", "--out", str(policy)]) == 0
    assert (
        main(
            [
                "campaign",
                "request-stage",
                cid,
                "--kind",
                "ANALYZE_SOURCE",
                "--policy",
                str(policy),
                "--store",
                str(store),
            ]
        )
        == 2
    )
    assert "STAGE_REQUIRES_SOURCE_OR_RUN_AND_ASSERTION" in capsys.readouterr().err
    profile = tmp_path / "profile.json"
    write_json(profile, fixture.profile().to_dict())
    key = tmp_path / "private.key"
    key.write_bytes(bytes(range(32)))
    assert (
        main(
            [
                "campaign",
                "review-decision",
                cid,
                "--run",
                "absent",
                "--assertion",
                "absent",
                "--dimension",
                "source-fidelity",
                "--decision",
                "APPROVE",
                "--reason",
                "Explicit test decision",
                "--reviewer-id",
                "reviewer",
                "--execution-profile",
                str(profile),
                "--key",
                str(key),
                "--out",
                str(key),
                "--store",
                str(store),
            ]
        )
        == 2
    )
    assert "REVIEW_OUTPUT_CANNOT_OVERWRITE_KEY" in capsys.readouterr().err
    assert key.read_bytes() == bytes(range(32))


@pytest.mark.parametrize(
    "option,value",
    [
        ("--max-tasks", "-1"),
        ("--max-attempts", "6"),
        ("--max-wall-seconds", "86401"),
        ("--lease-seconds", "901"),
    ],
)
def test_public_policy_rejects_unbounded_or_negative_budgets(option, value, capsys):
    assert main(["campaign", "policy", option, value]) == 2
    assert "error" in capsys.readouterr().err
