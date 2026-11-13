"""Bounded, hashed local dossiers. Imported history is never imported authority."""

from __future__ import annotations

import sqlite3
import stat
import tempfile
import zipfile
from contextlib import closing
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from ..integrity import (
    artifact_digest,
    atomic_write,
    canonical_bytes,
    digest,
    relative_path,
    require_digest,
    rooted_path,
    strict_loads,
)
from ..paper_sources import source_validation_operation

MAX_FILES = 20_000
MAX_FILE_BYTES = 64_000_000
MAX_TOTAL_BYTES = 512_000_000
TABLES = {
    "papers": ("id",),
    "revisions": ("id", "paper_id", "manifest"),
    "runs": ("id", "revision", "analysis", "bundle"),
    "stages": ("id", "cache_key", "revision", "analysis", "stage", "manifest", "output"),
    "reviews": ("id", "revision", "analysis", "body"),
    "audit_records": ("id", "run_id", "revision", "kind", "body"),
    "campaign_records": ("id", "campaign_id", "kind", "body", "sequence"),
    "campaign_heads": ("campaign_id", "snapshot_id"),
}
CAS_FIELDS = {
    "revisions": ("manifest",),
    "runs": ("bundle",),
    "stages": ("manifest", "output"),
    "reviews": ("body",),
    "audit_records": ("body",),
    "campaign_records": ("body",),
}
FORBIDDEN_KEYS = {
    "private_key",
    "controller_key",
    "api_key",
    "password",
    "credentials",
    "access_token",
    "refresh_token",
    "auth_token",
    "cookie",
    "cookies",
    "secret",
    "client_secret",
    "authorization_header",
    "token",
    "private_key_path",
    "controller_key_path",
    "api_key_path",
}


def _member_path(name: str) -> str:
    relative_path(name)
    if any(character in name for character in '<>"|?*'):
        raise ValueError("DOSSIER_NONPORTABLE_FILENAME")
    return name


class _OfflineHTML(HTMLParser):
    """Validate imported report markup before making it navigable locally."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.style = False
        self.csp = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {
            "script",
            "img",
            "svg",
            "iframe",
            "object",
            "embed",
            "form",
            "input",
            "button",
            "link",
            "audio",
            "video",
            "math",
            "base",
        }:
            raise ValueError("DOSSIER_ACTIVE_REPORT_CONTENT")
        attributes = dict(attrs)
        if len(attributes) != len(attrs) or any(
            name.lower().startswith("on") for name in attributes
        ):
            raise ValueError("DOSSIER_ACTIVE_REPORT_ATTRIBUTE")
        for name, value in attrs:
            if name in {"src", "srcset", "action", "formaction", "background", "style"}:
                raise ValueError("DOSSIER_ACTIVE_REPORT_ATTRIBUTE")
            if name == "href" and value is not None:
                target = value.split("#", 1)[0]
                if target:
                    relative_path(target)
        if (
            tag == "meta"
            and (attributes.get("http-equiv") or "").lower() == "content-security-policy"
        ):
            policy = attributes.get("content") or ""
            directives = [tuple(part.strip().split()) for part in policy.split(";") if part.strip()]
            allowed = {
                ("default-src", "'none'"),
                ("style-src", "'unsafe-inline'"),
                ("img-src", "'none'"),
                ("base-uri", "'none'"),
                ("form-action", "'none'"),
            }
            required = {
                ("default-src", "'none'"),
                ("base-uri", "'none'"),
                ("form-action", "'none'"),
            }
            if (
                not required <= set(directives)
                or set(directives) - allowed
                or len(directives) != len(set(directives))
            ):
                raise ValueError("DOSSIER_REPORT_CSP")
            self.csp = True
        elif tag == "meta" and "http-equiv" in attributes:
            raise ValueError("DOSSIER_ACTIVE_META")
        self.style = tag == "style" or self.style

    def handle_endtag(self, tag: str) -> None:
        if tag == "style":
            self.style = False

    def handle_data(self, data: str) -> None:
        if self.style and any(
            value in data.lower() for value in ("url(", "@import", "expression(", "\\")
        ):
            raise ValueError("DOSSIER_ACTIVE_REPORT_STYLE")


def _metadata_without_secrets(value: Any) -> None:
    """Reject secret-bearing configurations; stripping them would change identities."""
    if isinstance(value, dict):
        forbidden = {key.replace("_", "") for key in FORBIDDEN_KEYS}
        if any(str(key).lower().replace("-", "").replace("_", "") in forbidden for key in value):
            raise ValueError("DOSSIER_SECRET_CONFIGURATION")
        for child in value.values():
            _metadata_without_secrets(child)
    elif isinstance(value, list):
        for child in value:
            _metadata_without_secrets(child)
    elif isinstance(value, str) and (
        "-----BEGIN PRIVATE KEY-----" in value
        or "-----BEGIN RSA PRIVATE KEY-----" in value
        or "-----BEGIN EC PRIVATE KEY-----" in value
        or "-----BEGIN OPENSSH PRIVATE KEY-----" in value
    ):
        raise ValueError("DOSSIER_PRIVATE_KEY_MATERIAL")


def _source_material(store: Any, task: dict[str, Any]) -> dict[str, str]:
    """Check retained source-stage CAS without opening the recorded local path."""
    from ..schema import validate

    material = task.get("source_material")
    if not isinstance(material, dict) or set(material) != {"manifest", "artifacts"}:
        raise ValueError("DOSSIER_SOURCE_STAGE_MATERIAL_MISSING")
    manifest = material["manifest"]
    if not isinstance(manifest, dict):
        raise ValueError("DOSSIER_SOURCE_STAGE_MANIFEST")
    normalized = {"$schema": "urn:proofmap:paper-input:1", "schema_version": "1.0", **manifest}
    if (
        validate("paper-input", normalized)
        or manifest.get("revision") != task["target"]["revision"]
    ):
        raise ValueError("DOSSIER_SOURCE_STAGE_MANIFEST")
    expected = digest(
        "paper-manifest.v1",
        {"entrypoint": manifest["entrypoint"], "artifacts": manifest["artifacts"]},
    )
    if manifest["revision"] != expected:
        raise ValueError("DOSSIER_SOURCE_STAGE_REVISION")
    artifacts = material["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {
        row["path"] for row in manifest["artifacts"]
    }:
        raise ValueError("DOSSIER_SOURCE_STAGE_ARTIFACTS")
    for row in manifest["artifacts"]:
        relative_path(row["path"])
        if artifacts[row["path"]] != row["sha256"]:
            raise ValueError("DOSSIER_SOURCE_STAGE_ARTIFACT_DIGEST")
        raw = store.get(row["sha256"])
        if len(raw) != row["size"]:
            raise ValueError("DOSSIER_SOURCE_STAGE_ARTIFACT_SIZE")
    return artifacts


def _rows(db: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    columns = TABLES[table]
    return [
        dict(zip(columns, row, strict=True))
        for row in db.execute("SELECT " + ",".join(columns) + " FROM " + table + " ORDER BY rowid")
    ]


def _closure_indexes(store: Any, db: sqlite3.Connection, campaign_id: str) -> dict[str, Any]:
    """Follow exact stored parent runs/stages; do not guess by similar statements."""
    tables = {table: _rows(db, table) for table in TABLES}
    records = [row for row in tables["campaign_records"] if row["campaign_id"] == campaign_id]
    if not any(row["id"] == campaign_id and row["kind"] == "Campaign" for row in records):
        raise ValueError("UNKNOWN_CAMPAIGN")
    heads = [row for row in tables["campaign_heads"] if row["campaign_id"] == campaign_id]
    if len(heads) != 1:
        raise ValueError("CAMPAIGN_EXPORT_HEAD")
    selected_policies = {
        strict_loads(store.get(row["body"]))["operation_policy"]
        for row in records
        if row["kind"] == "CampaignSnapshot"
    }
    present = {row["id"] for row in records}
    records += [
        {**row, "campaign_id": campaign_id}
        for row in tables["campaign_records"]
        if row["id"] in selected_policies - present and row["kind"] == "OperationPolicy"
    ]
    runs = set()

    def refs(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"run_id", "parent_run", "parent_run_id"} and isinstance(child, str):
                    runs.add(child)
                refs(child)
        elif isinstance(value, list):
            for child in value:
                refs(child)

    for row in records:
        value = strict_loads(store.get(row["body"]))
        if value.get("kind") == "CampaignImport" and isinstance(
            value.get("retained_qualification"), dict
        ):
            # Qualification identity run_id denotes the CI/test producer, not a
            # manuscript run. Its bytes remain retained, but cannot extend the
            # paper-reference closure or supply source/evidence authority.
            value = {
                **value,
                "retained_qualification": {
                    key: child
                    for key, child in value["retained_qualification"].items()
                    if key != "identity"
                },
            }
        refs(value)
    by_run = {row["id"]: row for row in tables["runs"]}
    pending = set(runs)
    processed = set()
    while pending:
        ident = pending.pop()
        if ident not in by_run:
            raise ValueError("DOSSIER_MISSING_RUN_REFERENCE")
        processed.add(ident)
        refs(strict_loads(store.get(by_run[ident]["bundle"])))
        pending |= runs - processed
        if len(processed) > MAX_FILES:
            raise ValueError("DOSSIER_REFERENCE_LIMIT")
    selected_runs = [row for row in tables["runs"] if row["id"] in runs]
    revisions = {row["revision"] for row in selected_runs}
    selected_revisions = [row for row in tables["revisions"] if row["id"] in revisions]
    papers = {row["paper_id"] for row in selected_revisions}
    stages = [row for row in tables["stages"] if row["revision"] in revisions]
    # Parents outside selected revisions are forbidden by the existing stage validator.
    return {
        "papers": [row for row in tables["papers"] if row["id"] in papers],
        "revisions": selected_revisions,
        "runs": selected_runs,
        "stages": stages,
        "reviews": [row for row in tables["reviews"] if row["revision"] in revisions],
        "audit_records": [row for row in tables["audit_records"] if row["run_id"] in runs],
        "campaign_records": records,
        "campaign_heads": heads,
    }


def _qualification(
    files: dict[str, Path] | None, identity: dict[str, Any] | None
) -> tuple[dict[str, bytes], dict[str, Any] | None]:
    if not files:
        if identity:
            raise ValueError("QUALIFICATION_IDENTITY_WITHOUT_RETAINED_PAYLOADS")
        return {}, None
    if not identity or not {"source_fingerprint", "tree", "package_version"} <= identity.keys():
        raise ValueError("QUALIFICATION_REQUIRES_SOURCE_TREE_PACKAGE_IDENTITY")
    _metadata_without_secrets(identity)
    retained = {}
    for name, path in files.items():
        name = _member_path(name)
        if Path(path).is_symlink() or not Path(path).is_file():
            raise ValueError("QUALIFICATION_FILE_MISSING_OR_LINK")
        if Path(path).stat().st_size > MAX_FILE_BYTES:
            raise ValueError("QUALIFICATION_FILE_LIMIT")
        raw = Path(path).read_bytes()
        if b"PRIVATE KEY-----" in raw:
            raise ValueError("DOSSIER_PRIVATE_KEY_MATERIAL")
        if Path(name).suffix.lower() == ".json":
            _metadata_without_secrets(strict_loads(raw))
        retained["qualification/" + name] = raw
    return retained, {
        "identity": identity,
        "payload_availability": "RETAINED_LOCAL_BYTES",
        "integrity": "SHA256_INVENTORY",
        "execution_provenance": "CALLER_SUPPLIED_NOT_SELF_AUTHENTICATING",
        "current_authority": "EXTERNAL_REVALIDATION_REQUIRED",
    }


def _write_archive(out: Path, payloads: dict[str, bytes], fields: dict[str, Any]) -> dict[str, Any]:
    if len(payloads) > MAX_FILES or sum(map(len, payloads.values())) > MAX_TOTAL_BYTES:
        raise ValueError("DOSSIER_ARCHIVE_LIMIT")
    inventory = [
        {"path": name, "sha256": artifact_digest(raw), "size": len(raw)}
        for name, raw in sorted(payloads.items())
    ]
    manifest = {
        "schema_version": "1.0",
        "kind": "CampaignExportManifest",
        **fields,
        "inventory": inventory,
    }
    manifest["id"] = digest("campaign-export-manifest.v1", manifest)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Atomic publication ensures no partial archive is presented as complete.
    with tempfile.TemporaryDirectory(dir=out.parent) as temporary:
        temp = Path(temporary) / "dossier.zip"
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", canonical_bytes(manifest))
            for name, raw in sorted(payloads.items()):
                _member_path(name)
                archive.writestr(name, raw)
        _read_archive(temp)
        atomic_write(out, temp.read_bytes())
    return manifest


@source_validation_operation
def export_campaign(
    store: Any,
    campaign_id: str,
    out: Path,
    *,
    include_source: bool = False,
    qualification_files: dict[str, Path] | None = None,
    qualification_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from .reports import write_campaign_report
    from .store import CampaignStore

    if type(include_source) is not bool:
        raise ValueError("DOSSIER_INCLUDE_SOURCE_FLAG")
    # SQLite backup, then use only that immutable read snapshot throughout export.
    # No copy of the live index file, and no write transaction spans rendering.
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary) / "snapshot"
        root.mkdir()
        with closing(sqlite3.connect(root / "index.sqlite3")) as backup:
            store.db.backup(backup)
            if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("DOSSIER_DATABASE_INTEGRITY")

        class ExportStore(CampaignStore):
            def get(self, sha: str) -> bytes:
                raw = store.get(sha)
                if not isinstance(raw, bytes):
                    raise ValueError("DOSSIER_CAS_BYTES_REQUIRED")
                return raw

        # Snapshot indexes read source immutable CAS bytes, always rehashed.
        snapshot = ExportStore(root)
        try:
            indexes = _closure_indexes(snapshot, snapshot.db, campaign_id)
            objects: dict[str, bytes] = {}
            source_objects = set()
            for table, columns in CAS_FIELDS.items():
                for row in indexes[table]:
                    for column in columns:
                        sha = row[column]
                        raw = snapshot.get(sha)
                        _metadata_without_secrets(strict_loads(raw))
                        objects[sha] = raw
            for row in indexes["runs"]:
                value = strict_loads(objects[row["bundle"]])
                for sha in value["artifacts"].values():
                    source_objects.add(sha)
                    if include_source:
                        raw = snapshot.get(sha)
                        if b"PRIVATE KEY-----" in raw:
                            raise ValueError("DOSSIER_PRIVATE_KEY_MATERIAL")
                        objects[sha] = raw
            for row in indexes["campaign_records"]:
                value = strict_loads(objects[row["body"]])
                if value["kind"] == "Task" and value["target"].get("source_stage"):
                    for sha in _source_material(snapshot, value).values():
                        source_objects.add(sha)
                        if include_source:
                            raw = snapshot.get(sha)
                            if b"PRIVATE KEY-----" in raw:
                                raise ValueError("DOSSIER_PRIVATE_KEY_MATERIAL")
                            objects[sha] = raw
                for retained in value.get("retained_qualification", {}).get("artifacts", []):
                    sha = retained["sha256"]
                    objects[sha] = snapshot.get(sha)
            payloads = {"indexes.json": canonical_bytes(indexes)}
            payloads.update({"objects/" + sha: raw for sha, raw in objects.items()})
            report_dir = Path(temporary) / "report"
            write_campaign_report(snapshot, campaign_id, report_dir)
            for path in report_dir.rglob("*"):
                if path.is_file():
                    payloads["report/" + path.relative_to(report_dir).as_posix()] = (
                        path.read_bytes()
                    )
            retained, qualification = _qualification(qualification_files, qualification_identity)
            payloads.update(retained)
            retained_histories = [
                {
                    "import_record_id": value["id"],
                    "identity": value["retained_qualification"].get("identity"),
                    "artifacts": value["retained_qualification"]["artifacts"],
                    "applicability": "HISTORICAL_PROVENANCE_EXTERNAL_REVALIDATION_REQUIRED",
                }
                for row in indexes["campaign_records"]
                for value in [strict_loads(objects[row["body"]])]
                if value.get("retained_qualification", {}).get("artifacts")
            ]
            snapshot_id = indexes["campaign_heads"][0]["snapshot_id"]
            return _write_archive(
                Path(out),
                payloads,
                {
                    "campaign_id": campaign_id,
                    "snapshot_id": snapshot_id,
                    "raw_manuscripts_included": include_source,
                    "source_excerpts_included": True,
                    "self_contained_replay": include_source,
                    "omitted_source_objects": sorted(source_objects - objects.keys()),
                    "authority_imported": False,
                    "tasks_require_fresh_authorization": True,
                    "qualification": qualification,
                    "retained_qualification_histories": retained_histories,
                    "source_rights_provenance": "Retained input manifests; redistribution rights remain caller responsibility",
                },
            )
        finally:
            snapshot.close()


def _read_archive(path: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    """Validate every member before touching any destination store or directory."""
    payloads: dict[str, bytes] = {}
    names: set[str] = set()
    folded: set[str] = set()
    directories: set[str] = set()
    total = 0
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
            if len(members) > MAX_FILES + 1:
                raise ValueError("DOSSIER_FILE_COUNT_LIMIT")
            for member in members:
                name = _member_path(member.filename)
                mode = member.external_attr >> 16
                if (
                    member.is_dir()
                    or stat.S_ISLNK(mode)
                    or (stat.S_IFMT(mode) not in {0, stat.S_IFREG})
                ):
                    raise ValueError("DOSSIER_LINK_OR_SPECIAL_MEMBER")
                if name in names or name.casefold() in folded:
                    raise ValueError("DOSSIER_DUPLICATE_OR_CASE_COLLISION")
                parts = name.casefold().split("/")
                parents = {"/".join(parts[:end]) for end in range(1, len(parts))}
                if name.casefold() in directories or parents & folded:
                    raise ValueError("DOSSIER_FILE_DIRECTORY_COLLISION")
                names.add(name)
                folded.add(name.casefold())
                directories |= parents
                total += member.file_size
                if (
                    member.file_size > MAX_FILE_BYTES
                    or total > MAX_TOTAL_BYTES
                    or member.flag_bits & 1
                ):
                    raise ValueError("DOSSIER_MEMBER_OR_TOTAL_LIMIT")
                raw = archive.read(member)
                if len(raw) != member.file_size:
                    raise ValueError("DOSSIER_MEMBER_SIZE")
                payloads[name] = raw
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise ValueError("DOSSIER_INVALID_ARCHIVE") from exc
    if "manifest.json" not in payloads:
        raise ValueError("DOSSIER_MANIFEST_MISSING")
    manifest = strict_loads(payloads.pop("manifest.json"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "1.0"
        or manifest.get("kind") != "CampaignExportManifest"
    ):
        raise ValueError("DOSSIER_MANIFEST_SCHEMA")
    if manifest.get("id") != digest(
        "campaign-export-manifest.v1", {k: v for k, v in manifest.items() if k != "id"}
    ):
        raise ValueError("DOSSIER_MANIFEST_DIGEST")
    _metadata_without_secrets(manifest)
    expected = {}
    for row in manifest.get("inventory", []):
        if not isinstance(row, dict) or set(row) != {"path", "sha256", "size"}:
            raise ValueError("DOSSIER_INVENTORY_SCHEMA")
        name = _member_path(row["path"])
        require_digest(row["sha256"])
        if name in expected or type(row["size"]) is not int or row["size"] < 0:
            raise ValueError("DOSSIER_INVENTORY_DUPLICATE_OR_SIZE")
        expected[name] = row
    if set(expected) != set(payloads):
        raise ValueError("DOSSIER_INVENTORY_INCOMPLETE")
    for name, raw in payloads.items():
        if expected[name]["sha256"] != artifact_digest(raw) or expected[name]["size"] != len(raw):
            raise ValueError("DOSSIER_INVENTORY_DIGEST")
        if name.startswith("objects/"):
            sha = name.removeprefix("objects/")
            require_digest(sha)
            if artifact_digest(raw) != sha:
                raise ValueError("DOSSIER_CAS_IDENTITY")
        if name.startswith("report/") and name.endswith(".html"):
            parser = _OfflineHTML()
            parser.feed(raw.decode("utf-8"))
            if not parser.csp:
                raise ValueError("DOSSIER_REPORT_CSP_MISSING")
    return manifest, payloads


def verify_dossier(path: Path) -> dict[str, Any]:
    manifest, _ = _read_archive(Path(path))
    return {"integrity": "PASS", "manifest": manifest, "authority": "NOT_ESTABLISHED_BY_HASHES"}


def extract_dossier_report(archive: Path, out: Path) -> dict[str, Any]:
    """Open partial dossiers offline without manufacturing absent source bytes."""
    manifest, payloads = _read_archive(Path(archive))
    out.mkdir(parents=True, exist_ok=True)
    targets = {
        name: rooted_path(out, name.removeprefix("report/"))
        for name in payloads
        if name.startswith("report/")
    }
    for name, target in targets.items():
        atomic_write(target, payloads[name])
    return {
        "manifest_id": manifest["id"],
        "out": str(out),
        "self_contained_replay": manifest["self_contained_replay"],
    }


def _load_indexes(payloads: dict[str, bytes]) -> dict[str, Any]:
    if "indexes.json" not in payloads:
        raise ValueError("DOSSIER_INDEXES_MISSING")
    indexes = strict_loads(payloads["indexes.json"])
    if not isinstance(indexes, dict) or set(indexes) != set(TABLES):
        raise ValueError("DOSSIER_INDEX_TABLES")
    for table, rows in indexes.items():
        if not isinstance(rows, list) or len(rows) > MAX_FILES:
            raise ValueError("DOSSIER_INDEX_LIMIT")
        ids = set()
        for row in rows:
            if not isinstance(row, dict) or set(row) != set(TABLES[table]):
                raise ValueError("DOSSIER_INDEX_FIELDS")
            key = row["campaign_id"] if table == "campaign_heads" else row["id"]
            if key in ids or not isinstance(key, str):
                raise ValueError("DOSSIER_INDEX_ID_COLLISION")
            ids.add(key)
            for column in CAS_FIELDS.get(table, ()):
                sha = row[column]
                require_digest(sha)
                name = "objects/" + sha
                if name not in payloads:
                    raise ValueError("DOSSIER_REQUIRED_OBJECT_MISSING")
                _metadata_without_secrets(strict_loads(payloads[name]))
    return indexes


def _insert_indexes(store: Any, indexes: dict[str, Any], *, compare_existing: bool) -> None:
    for table, columns in TABLES.items():
        if table == "campaign_records":
            # Sequence is local insertion order; retain exported order, never global IDs.
            rows = sorted(indexes[table], key=lambda row: row["sequence"])
        else:
            rows = indexes[table]
        for row in rows:
            key_column = "campaign_id" if table == "campaign_heads" else "id"
            old = store.db.execute(
                "SELECT " + ",".join(columns) + " FROM " + table + " WHERE " + key_column + "=?",
                (row[key_column],),
            ).fetchone()
            if old:
                prior = dict(zip(columns, old, strict=True))
                target = dict(row)
                if table == "campaign_records":
                    prior.pop("sequence")
                    target.pop("sequence")
                    if prior["kind"] == target["kind"] == "OperationPolicy":
                        prior.pop("campaign_id")
                        target.pop("campaign_id")
                if compare_existing and prior != target:
                    raise ValueError("DOSSIER_EXISTING_IMMUTABLE_COLLISION")
                continue
            target = dict(row)
            if table == "campaign_records":
                target["sequence"] = store.db.execute(
                    "SELECT COALESCE(MAX(sequence),0)+1 FROM campaign_records"
                ).fetchone()[0]
            store.db.execute(
                "INSERT INTO "
                + table
                + "("
                + ",".join(columns)
                + ") VALUES("
                + ",".join("?" for _ in columns)
                + ")",
                tuple(target[column] for column in columns),
            )


def _validate_task_authorization(store: Any, campaign_id: str, task: dict[str, Any]) -> None:
    from ..paper_actions import request_action

    policy = store.get_record(task["policy_id"])
    authorization = store.get_record(task["authorization_id"])
    request = store.get_record(task["request_id"])
    if (
        policy["kind"] != "OperationPolicy"
        or authorization["kind"] != "OperationAuthorization"
        or request["kind"] != "ActionRequest"
        or authorization["campaign_id"] != campaign_id
        or request["campaign_id"] != campaign_id
        or authorization["policy_id"] != task["policy_id"]
        or authorization["snapshot_id"] != task["snapshot_id"]
        or authorization["actor"] != task["actor"]
        or request["actor"] != task["actor"]
        or task["action_id"] not in authorization["action_ids"]
        or task["action"]["id"] != task["action_id"]
        or canonical_bytes(task["action"]["target"]) != canonical_bytes(task["target"])
    ):
        raise ValueError("DOSSIER_TASK_AUTHORIZATION_BINDING")
    snapshot = store.get_record(task["snapshot_id"])
    store.validate_snapshot(snapshot)
    if snapshot["campaign_id"] != campaign_id or snapshot["operation_policy"] != policy["id"]:
        raise ValueError("DOSSIER_TASK_AUTHORIZATION_SNAPSHOT")
    plan_id = authorization["plan_id"]
    if plan_id is None:
        action = task["action"]
        if (
            authorization.get("request_id") != request["id"]
            or authorization["action_ids"] != [task["action_id"]]
            or request.get("stage_kind") != action["paper_action"]["kind"]
            or request["stage_kind"] not in policy["allowed_kinds"]
            or canonical_bytes(request.get("target")) != canonical_bytes(task["target"])
            or request.get("authority") != "EXPLICIT_OPERATOR_REQUEST"
            or any(
                request.get(field) != action.get(field)
                for field in ("config_digest", "replay_digest")
            )
            or action["id"]
            != digest("campaign-stage-action.v1", {k: v for k, v in action.items() if k != "id"})
        ):
            raise ValueError("DOSSIER_TASK_STAGE_REQUEST_BINDING")
        return
    plan = store.get_record(plan_id)
    if (
        plan["kind"] != "CampaignPlan"
        or plan["campaign_id"] != campaign_id
        or request.get("plan_id") != plan_id
        or request.get("authorization_id") != authorization["id"]
        or request.get("action_id") != task["action_id"]
        or request["requested_at"] != authorization["authorized_at"]
    ):
        raise ValueError("DOSSIER_TASK_PLAN_REQUEST_BINDING")
    planned_snapshot = store.get_record(plan["snapshot_id"])
    store.validate_snapshot(planned_snapshot)
    if (
        planned_snapshot["campaign_id"] != campaign_id
        or plan["snapshot_id"] not in {snapshot["id"], snapshot["parent_snapshot"]}
        or any(
            canonical_bytes(snapshot[field]) != canonical_bytes(planned_snapshot[field])
            for field in ("objective", "selections", "goals")
        )
    ):
        raise ValueError("DOSSIER_TASK_PLAN_SNAPSHOT_BINDING")
    available = {action["id"]: action for action in plan["actions"]}
    if (
        set(authorization["action_ids"]) - available.keys()
        or task["action_id"] not in available
        or canonical_bytes(task["action"]) != canonical_bytes(available[task["action_id"]])
    ):
        raise ValueError("DOSSIER_TASK_PLAN_ACTION_BINDING")
    paper_plan = next(
        (
            paper["paper_plan"]
            for paper in plan["papers"]
            if paper["run_id"] == task["target"]["run_id"]
        ),
        None,
    )
    if paper_plan is None:
        raise ValueError("DOSSIER_TASK_PAPER_PLAN_MISSING")
    admitted = request_action(
        paper_plan,
        task["action"]["paper_action"]["id"],
        actor=request["actor"],
        requested_at=request["requested_at"],
    )
    if canonical_bytes(admitted) != canonical_bytes(request.get("pure_request")):
        raise ValueError("DOSSIER_TASK_PURE_REQUEST_BINDING")


def _semantic_validate(store: Any, campaign_id: str, indexes: dict[str, Any]) -> None:
    from .models import validate_ref_material
    from .reports import validate_qualified_ref

    for row in indexes["runs"]:
        bundle = store.inspect(row["id"])["bundle"]
        if (
            bundle["run_manifest"]["run_id"],
            bundle["input_manifest"]["revision"],
            bundle["run_manifest"]["analysis_digest"],
        ) != (row["id"], row["revision"], row["analysis"]):
            raise ValueError("DOSSIER_RUN_INDEX_BINDING")
        paper = store.db.execute(
            "SELECT paper_id FROM revisions WHERE id=?", (row["revision"],)
        ).fetchone()
        if paper is None:
            raise ValueError("DOSSIER_RUN_PAPER_MISSING")
        store._validate_revision_lineage(bundle, paper[0])
        bindings = {
            formal["binding"]["id"]
            for formal in bundle.get("formalizations", [])
            if formal.get("binding")
        }
        for audit in store.list_audit(row["id"]):
            typed = audit.get("record", audit)
            for field in ("revision", "revision_id"):
                if field in typed and typed[field] != row["revision"]:
                    raise ValueError("DOSSIER_AUDIT_REVISION_BINDING")
            for field in ("analysis", "analysis_digest"):
                if field in typed and typed[field] != row["analysis"]:
                    raise ValueError("DOSSIER_AUDIT_ANALYSIS_BINDING")
            for field in ("binding_id", "binding_digest"):
                if field in typed and typed[field] not in bindings:
                    raise ValueError("DOSSIER_AUDIT_SUBJECT_BINDING")
    for row in indexes["stages"]:
        store.stage_by_id(row["id"])
    for row in indexes["reviews"]:
        store.list_reviews(row["revision"], row["analysis"])
    sequences = [row["sequence"] for row in indexes["campaign_records"]]
    if any(type(sequence) is not int or sequence < 1 for sequence in sequences) or len(
        sequences
    ) != len(set(sequences)):
        raise ValueError("DOSSIER_CAMPAIGN_SEQUENCE")
    for row in indexes["campaign_records"]:
        value = store.get_record(row["id"])
        if row["campaign_id"] != campaign_id:
            raise ValueError("DOSSIER_OTHER_CAMPAIGN_RECORD")
        if value.get("campaign_id", campaign_id) != campaign_id:
            raise ValueError("DOSSIER_RECORD_CAMPAIGN_NAMESPACE")
        if value["kind"] == "CampaignSnapshot":
            store.validate_snapshot(value)
            if value["campaign_id"] != campaign_id:
                raise ValueError("DOSSIER_SNAPSHOT_CAMPAIGN")
            if (
                value["parent_snapshot"] is not None
                and store.get_record(value["parent_snapshot"])["kind"] != "CampaignSnapshot"
            ):
                raise ValueError("DOSSIER_SNAPSHOT_PARENT")
        if value["kind"] == "Goal" and value.get("target"):
            validate_ref_material(store, value["target"])
        if value["kind"] == "CampaignRelationCandidate":
            anchors = [validate_qualified_ref(store, value[side]) for side in ("left", "right")]
            if anchors != value["source_anchors"] or value["proof_closure"] is not False:
                raise ValueError("DOSSIER_RELATION_AUTHORITY_OR_ANCHORS")
        if value["kind"] in {"TaskAttempt", "TaskEvent", "TaskResult"}:
            task = store.get_record(value["task_id"])
            if task["kind"] != "Task" or task.get("campaign_id") != campaign_id:
                raise ValueError("DOSSIER_TASK_REFERENCE")
            if value.get("campaign_id") != campaign_id:
                raise ValueError("DOSSIER_TASK_CAMPAIGN_REFERENCE")
            if value["kind"] == "TaskResult" and canonical_bytes(
                value["target"]
            ) != canonical_bytes(task["target"]):
                raise ValueError("DOSSIER_TASK_RESULT_TARGET_BINDING")
            if value["kind"] == "TaskEvent":
                projection = value["projection"]
                if (
                    projection["task_id"] != value["task_id"]
                    or projection["state"] != value["state"]
                ):
                    raise ValueError("DOSSIER_TASK_PROJECTION_BINDING")
                for field, expected_kind in (
                    ("attempt_id", "TaskAttempt"),
                    ("last_result", "TaskResult"),
                ):
                    if projection.get(field) is not None:
                        reference = store.get_record(projection[field])
                        if (
                            reference["kind"] != expected_kind
                            or reference["task_id"] != value["task_id"]
                        ):
                            raise ValueError("DOSSIER_TASK_PROJECTION_REFERENCE")
        if value["kind"] == "Task":
            if value["target"].get("source_stage"):
                _source_material(store, value)
            else:
                validate_ref_material(store, value["target"])
            _validate_task_authorization(store, campaign_id, value)
        for retained in value.get("retained_qualification", {}).get("artifacts", []):
            raw = store.get(retained["sha256"])
            if len(raw) != retained["size"]:
                raise ValueError("DOSSIER_RETAINED_QUALIFICATION_SIZE")
    store.current_snapshot(campaign_id)


def rebuild_campaign_indexes(store: Any) -> None:
    """Rebuild mutable task indexes from immutable events, preserving import barriers."""
    from .queue import rebuild

    rebuild(store)


def _known_import(store: Any, campaign_id: str, manifest_id: str) -> dict[str, Any] | None:
    return next(
        (
            value
            for value in store.records(campaign_id, "CampaignImport")
            if value["manifest_id"] == manifest_id
        ),
        None,
    )


def _import_result(
    manifest: dict[str, Any], indexes: dict[str, Any], import_id: str, *, unchanged: bool = False
) -> dict[str, Any]:
    return {
        "campaign_id": manifest["campaign_id"],
        "snapshot_id": manifest["snapshot_id"],
        "imported_records": len(indexes["campaign_records"]),
        "import_id": import_id,
        "tasks_require_fresh_authorization": True,
        "authority_imported": False,
        "historical_only": True,
        "qualification": manifest.get("qualification"),
        "unchanged": unchanged,
    }


def _fence_import_tasks(
    store: Any,
    campaign_id: str,
    imported_task_ids: set[str],
    local_projections: dict[str, dict[str, Any]],
) -> None:
    """Publish import barriers before any imported task can become visible."""
    from .queue import TERMINAL, _publish

    latest = {value["task_id"]: value for value in store.records(campaign_id, "TaskEvent")}
    for task_id in sorted(imported_task_ids):
        event = latest.get(task_id)
        if event is None:
            continue
        projection = dict(event["projection"])
        local = local_projections.get(task_id)
        if local is not None:
            # A local lease/authorization must not be replaced by archive history.
            if canonical_bytes(local) != canonical_bytes(projection):
                _publish(
                    store,
                    campaign_id,
                    dict(local),
                    actor="import",
                    reason="IMPORT_PRESERVE_LOCAL_STATE",
                    previous=event["id"],
                )
            continue
        old = projection["state"]
        if old in TERMINAL and old not in {"UNAVAILABLE", "ERROR"}:
            continue
        if old == "RUNNING":
            projection["generation"] += 1
        requests = projection.get("model_reserved_requests", 0)
        tokens = projection.get("model_reserved_tokens", 0)
        projection["model_consumed_requests"] = (
            projection.get("model_consumed_requests", 0) + requests
        )
        projection["model_consumed_tokens"] = projection.get("model_consumed_tokens", 0) + tokens
        if requests:
            projection["model_unknown_effect"] = True
        projection.update(
            state="STALE",
            lease_token=None,
            lease_owner=None,
            lease_until=None,
            reserved_seconds=0,
            model_reserved_requests=0,
            model_reserved_tokens=0,
        )
        _publish(
            store,
            campaign_id,
            projection,
            actor="import",
            reason="IMPORT_REQUIRES_FRESH_AUTHORIZATION",
            previous=event["id"],
        )


@source_validation_operation
def import_campaign(archive: Path, store: Any) -> dict[str, Any]:
    from .models import record
    from .queue import _insert
    from .store import CampaignStore

    manifest, payloads = _read_archive(Path(archive))
    if (
        manifest.get("raw_manuscripts_included") is not True
        or manifest.get("self_contained_replay") is not True
        or manifest.get("omitted_source_objects")
    ):
        raise ValueError("DOSSIER_PARTIAL_NOT_SELF_CONTAINED: extract the offline report instead")
    campaign_id = manifest["campaign_id"]
    require_digest(campaign_id)
    indexes = _load_indexes(payloads)
    # Fully reconstruct and semantically validate in an isolated throwaway store first.
    # Destination writes occur only after path/hash/schema/reference checks all pass.
    with tempfile.TemporaryDirectory() as temporary:
        staged = CampaignStore(Path(temporary) / "validated")
        try:
            for name, raw in payloads.items():
                if name.startswith("objects/"):
                    staged.put(raw)
            with staged.db:
                _insert_indexes(staged, indexes, compare_existing=False)
            _semantic_validate(staged, campaign_id, indexes)
            if staged.current_snapshot(campaign_id)["id"] != manifest["snapshot_id"]:
                raise ValueError("DOSSIER_HEAD_BINDING")
            staged.rebuild()
            rebuild_campaign_indexes(staged)
        finally:
            staged.close()
    known = _known_import(store, campaign_id, manifest["id"])
    if known is not None:
        return _import_result(manifest, indexes, known["id"], unchanged=True)
    # Preflight all conflicts before even adding unreachable destination CAS objects.
    for table, columns in TABLES.items():
        for row in indexes[table]:
            key = "campaign_id" if table == "campaign_heads" else "id"
            old = store.db.execute(
                "SELECT " + ",".join(columns) + " FROM " + table + " WHERE " + key + "=?",
                (row[key],),
            ).fetchone()
            if old:
                prior = dict(zip(columns, old, strict=True))
                target = dict(row)
                if table == "campaign_records":
                    prior.pop("sequence")
                    target.pop("sequence")
                    if prior["kind"] == target["kind"] == "OperationPolicy":
                        prior.pop("campaign_id")
                        target.pop("campaign_id")
                if prior != target:
                    raise ValueError("DOSSIER_EXISTING_IMMUTABLE_COLLISION")
    if store.root.is_symlink() or (hasattr(store.root, "is_junction") and store.root.is_junction()):
        raise ValueError("DOSSIER_DESTINATION_LINK")
    for name in payloads:
        if name.startswith("objects/"):
            sha = name.removeprefix("objects/")
            rooted_path(store.root, "objects/" + sha[:2] + "/" + sha[2:])
    for name, raw in payloads.items():
        if name.startswith("objects/"):
            store.put(raw)
    retained_qualification: dict[str, Any] = {
        "identity": (manifest.get("qualification") or {}).get("identity"),
        "artifacts": [],
    }
    for name, raw in payloads.items():
        if name.startswith("qualification/"):
            retained_qualification["artifacts"].append(
                {
                    "path": name.removeprefix("qualification/"),
                    "sha256": store.put(raw),
                    "size": len(raw),
                }
            )
    imported = record(
        "CampaignImport",
        campaign_id=campaign_id,
        manifest_id=manifest["id"],
        authority_imported=False,
        tasks_require_fresh_authorization=True,
        source="LOCAL_HASHED_DOSSIER",
        imported_record_ids=[row["id"] for row in indexes["campaign_records"]],
        retained_qualification=retained_qualification,
    )
    imported_task_ids = {row["id"] for row in indexes["campaign_records"] if row["kind"] == "Task"}
    try:
        store.db.execute("BEGIN IMMEDIATE")
        known = _known_import(store, campaign_id, manifest["id"])
        if known is not None:
            store.db.commit()
            return _import_result(manifest, indexes, known["id"], unchanged=True)
        local_projections = {
            task_id: strict_loads(store.get(sha))
            for task_id, sha in store.db.execute(
                "SELECT task_id,projection FROM campaign_tasks WHERE campaign_id=?",
                (campaign_id,),
            )
            if task_id in imported_task_ids
        }
        _insert_indexes(store, indexes, compare_existing=True)
        _insert(store, campaign_id, imported)
        _fence_import_tasks(store, campaign_id, imported_task_ids, local_projections)
        store.db.commit()
    except BaseException:
        store.db.rollback()
        raise
    rebuild_campaign_indexes(store)
    store.rebuild()
    return _import_result(manifest, indexes, imported["id"])


@source_validation_operation
def audit_campaign(store: Any, campaign_id: str) -> dict[str, Any]:
    indexes = _closure_indexes(store, store.db, campaign_id)
    _semantic_validate(store, campaign_id, indexes)
    objects = set()
    for table, columns in CAS_FIELDS.items():
        for row in indexes[table]:
            for column in columns:
                objects.add(row[column])
                store.get(row[column])
    for row in indexes["runs"]:
        for sha in store.inspect(row["id"])["artifacts"].values():
            objects.add(sha)
            store.get(sha)
    for value in store.records(campaign_id, "CampaignImport"):
        for retained in value.get("retained_qualification", {}).get("artifacts", []):
            objects.add(retained["sha256"])
            store.get(retained["sha256"])
    for task in store.records(campaign_id, "Task"):
        if task["target"].get("source_stage"):
            objects.update(_source_material(store, task).values())
    return {
        "campaign_id": campaign_id,
        "snapshot_id": store.current_snapshot(campaign_id)["id"],
        "integrity": "PASS",
        "checked_objects": len(objects),
        "checked_runs": len(indexes["runs"]),
        "historical_only": True,
        "current_authority": "SEPARATELY_CONFIGURED_REASSESSMENT_REQUIRED",
        "authority_imported": False,
    }


def preserve_qualification(
    files: dict[str, Path], out: Path, *, identity: dict[str, Any]
) -> dict[str, Any]:
    """Owner-operated offline retention; a hosted URL is metadata, never the payload."""
    payloads, qualification = _qualification(files, identity)
    return _write_archive(
        Path(out),
        payloads,
        {
            "campaign_id": None,
            "snapshot_id": None,
            "raw_manuscripts_included": False,
            "source_excerpts_included": False,
            "self_contained_replay": False,
            "omitted_source_objects": [],
            "authority_imported": False,
            "tasks_require_fresh_authorization": True,
            "qualification": qualification,
        },
    )
