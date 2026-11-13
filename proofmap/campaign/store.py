"""Additive PaperStore migration; immutable CAS records back every projection."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from typing import Any, cast

from ..integrity import canonical_bytes, strict_loads
from ..paper_sources import source_validation_operation
from ..paper_store import PaperStore
from .models import validate_record, validate_ref_material


def backup_before_migration(store: PaperStore, previous_version: int) -> None:
    db = store.db
    existing = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' LIMIT 1").fetchone()
    if previous_version in (1, 2) or (previous_version == 0 and existing):
        directory = store.root / "backups"
        directory.mkdir(exist_ok=True)
        backup_path = directory / (
            "pre-campaign-v" + str(previous_version) + "-" + uuid.uuid4().hex + ".sqlite3"
        )
        with closing(sqlite3.connect(backup_path)) as backup:
            db.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("CAMPAIGN_MIGRATION_BACKUP_INVALID")


def migrate(store: PaperStore, previous_version: int) -> None:
    db = store.db
    db.execute("PRAGMA busy_timeout=5000")
    with db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS campaign_records(
            id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, kind TEXT NOT NULL,
            body TEXT NOT NULL, sequence INTEGER UNIQUE NOT NULL);
        CREATE INDEX IF NOT EXISTS campaign_kind ON campaign_records(campaign_id,kind,sequence);
        CREATE TABLE IF NOT EXISTS campaign_heads(campaign_id TEXT PRIMARY KEY,snapshot_id TEXT NOT NULL);
        """)
    from .queue import migrate as migrate_queue

    migrate_queue(db)
    with db:
        db.execute("PRAGMA user_version=3")


class CampaignStore(PaperStore):
    @property
    def paper(self) -> PaperStore:
        return self

    def add_record(self, value: dict[str, Any], campaign_id: str) -> str:
        validate_record(value)
        raw = canonical_bytes(value)
        sha = self.put(raw)
        # CAS publication precedes indexing, including concurrent duplicate writers.
        try:
            self.db.execute("BEGIN IMMEDIATE")
            prior = self.db.execute(
                "SELECT campaign_id,body FROM campaign_records WHERE id=?", (value["id"],)
            ).fetchone()
            if (
                prior
                and prior != (campaign_id, sha)
                and not (value["kind"] == "OperationPolicy" and prior[1] == sha)
            ):
                raise ValueError("CAMPAIGN_IMMUTABLE_COLLISION")
            self.db.execute(
                "INSERT OR IGNORE INTO campaign_records SELECT ?,?,?,?,COALESCE(MAX(sequence),0)+1 FROM campaign_records",
                (value["id"], campaign_id, value["kind"], sha),
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
        return str(value["id"])

    def get_record(self, ident: str) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT body,kind FROM campaign_records WHERE id=?", (ident,)
        ).fetchone()
        if row is None:
            raise ValueError("UNKNOWN_CAMPAIGN_RECORD")
        value = strict_loads(self.get(row[0]))
        validate_record(value)
        if value["id"] != ident or value["kind"] != row[1]:
            raise ValueError("CAMPAIGN_INDEX_BINDING")
        return cast(dict[str, Any], value)

    def records(self, campaign_id: str, kind: str | None = None) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id FROM campaign_records WHERE campaign_id=? AND (? IS NULL OR kind=?) ORDER BY sequence",
            (campaign_id, kind, kind),
        ).fetchall()
        records = [self.get_record(row[0]) for row in rows]
        # Immutable operation policies can be selected by several campaigns.
        # Their shared identity carries no mathematical trust.
        if kind in (None, "OperationPolicy"):
            policies = {
                r["operation_policy"] for r in self.records(campaign_id, "CampaignSnapshot")
            }
            present = {r["id"] for r in records}
            records.extend(self.get_record(ident) for ident in sorted(policies - present))
        return records

    @source_validation_operation
    def current_snapshot(self, campaign_id: str) -> dict[str, Any]:
        if self.get_record(campaign_id)["kind"] != "Campaign":
            raise ValueError("NOT_A_CAMPAIGN")
        row = self.db.execute(
            "SELECT snapshot_id FROM campaign_heads WHERE campaign_id=?", (campaign_id,)
        ).fetchone()
        if row is None:
            raise ValueError("CAMPAIGN_SNAPSHOT_MISSING")
        snapshot = self.get_record(row[0])
        if snapshot.get("campaign_id") != campaign_id:
            raise ValueError("CAMPAIGN_SNAPSHOT_NAMESPACE")
        self.validate_snapshot(snapshot)
        return snapshot

    @source_validation_operation
    def validate_snapshot(self, snapshot: dict[str, Any]) -> None:
        validate_record(snapshot)
        if snapshot["kind"] != "CampaignSnapshot":
            raise ValueError("NOT_A_CAMPAIGN_SNAPSHOT")
        campaign_id = snapshot["campaign_id"]
        if self.get_record(campaign_id)["kind"] != "Campaign":
            raise ValueError("CAMPAIGN_SNAPSHOT_NAMESPACE")
        if snapshot["parent_snapshot"] is not None:
            parent = self.get_record(snapshot["parent_snapshot"])
            if parent["kind"] != "CampaignSnapshot" or parent.get("campaign_id") != campaign_id:
                raise ValueError("CAMPAIGN_SNAPSHOT_PARENT_NAMESPACE")
        if self.get_record(snapshot["operation_policy"])["kind"] != "OperationPolicy":
            raise ValueError("CAMPAIGN_POLICY_REFERENCE")
        for selected in snapshot["selections"]:
            bundle = self.inspect(selected["run_id"])["bundle"]
            paper = self.db.execute(
                "SELECT paper_id FROM revisions WHERE id=?", (selected["revision"],)
            ).fetchone()
            if bundle["input_manifest"]["revision"] != selected["revision"] or paper != (
                selected["paper_id"],
            ):
                raise ValueError("CAMPAIGN_RUN_REFERENCE")
        # Removed goal targets remain resolvable historically, even outside current membership.
        for goal in snapshot["goals"]:
            validate_record(goal)
            if goal["kind"] != "Goal":
                raise ValueError("CAMPAIGN_GOAL_REFERENCE")
            if goal.get("target"):
                validate_ref_material(self, goal["target"])
            if goal.get("campaign_id") != campaign_id:
                raise ValueError("CAMPAIGN_GOAL_NAMESPACE")
            if self.get_record(goal["id"]) != goal:
                raise ValueError("CAMPAIGN_GOAL_REFERENCE")

    def set_current_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.validate_snapshot(snapshot)
        campaign_id = snapshot["campaign_id"]
        self.add_record(snapshot, campaign_id)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            prior = self.db.execute(
                "SELECT snapshot_id FROM campaign_heads WHERE campaign_id=?", (campaign_id,)
            ).fetchone()
            if prior and prior[0] not in {snapshot["id"], snapshot["parent_snapshot"]}:
                raise ValueError("CAMPAIGN_SNAPSHOT_CONCURRENT_UPDATE")
            if not prior and snapshot["parent_snapshot"] is not None:
                raise ValueError("CAMPAIGN_SNAPSHOT_PARENT_MISSING")
            self.db.execute(
                "INSERT INTO campaign_heads VALUES(?,?) ON CONFLICT(campaign_id) DO UPDATE SET snapshot_id=excluded.snapshot_id",
                (campaign_id, snapshot["id"]),
            )
            self.db.commit()
        except BaseException:
            self.db.rollback()
            raise
