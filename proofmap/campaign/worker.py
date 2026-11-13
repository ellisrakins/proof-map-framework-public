"""Private non-Lean adapter worker. No signing authority or membership promotion."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from ..integrity import canonical_bytes, digest, load_json
from .store import CampaignStore


def perform(store: CampaignStore, request: dict[str, Any]) -> dict[str, Any]:
    from .operations import SOURCE_STAGES, _assessment_for_run, _bundle, _view

    task = store.get_record(request["task_id"])
    kind, config = request["kind"], request["config"]
    evidence: dict[str, Any] | None = None
    status, error = "ERROR", None
    if kind in SOURCE_STAGES:
        from ..paper_sources import InputManifest, parse
        from .service import ingest

        target = task["target"]
        if kind == "REPARSE_SOURCE":
            material = task["source_material"]
            ir = parse(
                InputManifest(**material["manifest"]),
                {name: store.get(sha) for name, sha in material["artifacts"].items()},
                timeout_seconds=min(45, request["reserve"]),
            )
            evidence = {"document_ir": ir}
            status = "SUCCEEDED" if ir["parser"]["execution"] == "COMPLETED" else "UNAVAILABLE"
        else:
            extractor_config, replay = (
                config.get("extractor_config"),
                config.get("extractor_replay"),
            )
            if kind in {"EXTRACT_CONFIGURED", "EXTRACT_RECORDED"}:
                if (
                    extractor_config is None
                    or digest("campaign-stage-config.v1", extractor_config)
                    != task["action"]["config_digest"]
                ):
                    raise ValueError("CAMPAIGN_STAGE_CONFIG_CHANGED")
                if kind == "EXTRACT_RECORDED" and (
                    replay is None
                    or digest("campaign-stage-replay.v1", replay) != task["action"]["replay_digest"]
                ):
                    raise ValueError("CAMPAIGN_STAGE_REPLAY_CHANGED")
            mode = (
                "configured"
                if kind == "EXTRACT_CONFIGURED"
                else "replay"
                if kind == "EXTRACT_RECORDED"
                else "none"
            )
            evidence = ingest(
                store,
                task["campaign_id"],
                Path(target["source_path"]),
                extractor=mode,
                config={"extractor": extractor_config} if extractor_config else None,
                replay=replay,
                entrypoint=target.get("entrypoint"),
                paper_id=target["paper_id"],
                actor=request["actor"],
                _task_id=task["id"],
                _lease_token=request["lease_token"],
                _lease_generation=request["generation"],
                _defer_selection=True,
            )
            status = (
                "SUCCEEDED"
                if all(row["exit_code"] == 0 for row in evidence["manuscripts"])
                else "CHECK_FAILED"
            )
    else:
        bundle = _bundle(store, task["target"]["run_id"])
        row = next(
            r
            for r in bundle["formalizations"]
            if r["assertion_id"] == task["target"]["assertion_id"]
        )
        if kind in {"EXACT_COMPUTATION", "FORMALIZE_SUPPORTED", "ANALYZE_SOURCE"}:
            from ..formalize import formalize_document

            fresh = next(
                r
                for r in formalize_document(bundle.get("interpreted_ir", bundle["document_ir"]))
                if r["assertion_id"] == row["assertion_id"]
            )
            evidence = {
                "formalization": fresh,
                "scope": "ENCODED_INTEGER_POLYNOMIAL; source fidelity unreviewed",
            }
            status = (
                "SUCCEEDED"
                if kind != "EXACT_COMPUTATION" or fresh.get("exact_check", {}).get("equal")
                else "CHECK_FAILED"
            )
        elif kind == "REFRESH_REPORT":
            from ..paper_reports import report_model

            evidence = {
                "report": report_model(
                    _view(store, bundle),
                    {
                        name: store.get(sha)
                        for name, sha in store.inspect(task["target"]["run_id"])[
                            "artifacts"
                        ].items()
                    },
                )
            }
            status = "SUCCEEDED"
        elif kind in {"AUTHENTICATE_EVIDENCE", "REASSESS_POLICY"}:
            if not all(config.get(name) for name in ("profile", "trust_store", "evaluation_time")):
                status, error = "UNAVAILABLE", "CURRENT_EXTERNAL_AUTHORITY_REQUIRED"
            else:
                evidence = _assessment_for_run(
                    store,
                    bundle,
                    config["profile"],
                    config["trust_store"],
                    config["evaluation_time"],
                )
                selected = next(
                    r for r in evidence["records"] if r["assertion_id"] == row["assertion_id"]
                )
                status = "SUCCEEDED" if selected["formal_status"] == "VERIFIED" else "CHECK_FAILED"
        else:
            raise ValueError("UNIMPLEMENTED_ADAPTER_REJECTED")
    return {"state": status, "evidence": evidence, "error": error}


def main() -> None:
    # Waiting for this gate prevents adapter descendants and external requests
    # before the controller has assigned process ownership.
    request_path = Path(sys.stdin.buffer.read(4097).decode("utf-8"))
    try:
        if request_path.stat().st_size > 8_000_000:
            raise ValueError("CAMPAIGN_WORKER_INPUT_LIMIT")
        request = load_json(request_path)
        store = CampaignStore(Path(request["store_root"]))
        try:
            response = perform(store, request)
        finally:
            store.close()
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
        response = {"state": "ERROR", "error": type(exc).__name__ + ":" + str(exc)[:256]}
    sys.stdout.buffer.write(canonical_bytes(response))


if __name__ == "__main__":
    main()
