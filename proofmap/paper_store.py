"""Offline SQLite index plus content-addressed immutable objects.

Objects are durable before the transaction publishes a run. A crash may leave
unreferenced CAS objects, never a partially promoted paper. No acceptance flag.
"""

from __future__ import annotations

import base64
import builtins
import dataclasses
import inspect
import json
import marshal
import re
import sqlite3
import sys
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
from types import BuiltinFunctionType, CodeType, MappingProxyType
from typing import Any, cast

from .integrity import (
    artifact_digest,
    atomic_write,
    canonical_bytes,
    digest,
    relative_path,
    require_digest,
    strict_loads,
)
from .kernel import KernelMap
from .paper_sources import (
    locator_validation_session,
    source_validation_leaf_operation,
    source_validation_operation,
    validate_locator,
)
from .paper_stages import PURE_STAGES, StageResult, stage_key, validate_stage_output
from .schema import validate

_NATIVE_CONTRACT_ENCODER = marshal.dumps


class _ContractIdentity:
    """Hold an unhashable trusted validator strongly, without numeric-ID reuse."""

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value

    def __hash__(self) -> int:
        return id(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ContractIdentity) and self.value is other.value


def _contract_value(value: Any) -> Any:
    """Only explicit pure structural settings become token digest material."""
    if value is None or type(value) in (str, int, bool, float):
        return value
    if isinstance(value, bytes):
        return {"bytes_sha256": artifact_digest(value)}
    if isinstance(value, re.Pattern):
        return {"pattern": value.pattern, "flags": value.flags}
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _contract_value(dataclasses.asdict(value))
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("MEMO_CONTRACT_SETTING")
        return {key: _contract_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_contract_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_contract_value(item) for item in value), key=canonical_bytes)
    raise ValueError("MEMO_CONTRACT_SETTING")


def _contract_digest(settings: dict[str, Any]) -> str:
    """Canonicalize trusted contract settings without revisiting scalar types.

    This is only optimization metadata. Exact source/record boundaries retain
    their existing strict validators. JSON's encoder rejects unsupported values,
    cycles and nonfinite numbers; the walk preserves string keys and the same
    depth/item limits as the general canonicalizer.
    """
    pending: list[tuple[Any, int]] = [(settings, 0)]
    count = 1
    while pending:
        value, depth = pending.pop()
        if depth > 128 or count > 1_000_000:
            raise ValueError("MEMO_CONTRACT_RESOURCE_LIMIT")
        if isinstance(value, dict):
            if any(not isinstance(key, str) for key in value):
                raise ValueError("MEMO_CONTRACT_STRING_KEYS")
            children = value.values()
        else:
            children = value
        count += len(value)
        if count > 1_000_000:
            raise ValueError("MEMO_CONTRACT_RESOURCE_LIMIT")
        if value and depth >= 128:
            raise ValueError("MEMO_CONTRACT_RESOURCE_LIMIT")
        pending.extend(
            (item, depth + 1) for item in children if isinstance(item, (dict, list, tuple))
        )
    raw = json.dumps(
        settings, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    return artifact_digest(b"proofmap\x00bundle-validation-contract.v1\x00" + raw)


def _default_contract(
    value: Any,
    label: str,
    identities: list[object],
    settings: dict[str, Any],
    seen: set[object],
) -> Any:
    if value is None or type(value) in (str, int, bool, float):
        return value
    registry_type = getattr(sys.modules.get("referencing"), "Registry", None)
    if isinstance(registry_type, type) and isinstance(value, registry_type):
        # Referencing registries are immutable; bind the actual default without
        # repeatedly walking the global JSON Schema meta-registry.
        identities.append((label, registry_type, _ContractIdentity(value)))
        return "immutable_registry_default"
    if isinstance(value, (type, CodeType)) or type(value) is object or value is dataclasses.MISSING:
        identities.append((label, _ContractIdentity(value)))
        return "trusted_default_identity"
    if value is getattr(dataclasses, "_HAS_DEFAULT_FACTORY", None):
        identities.append((label, _ContractIdentity(value)))
        return "dataclass_default_factory"
    if isinstance(value, Enum):
        identities.append((label, type(value)))
        return {"enum": value.name, "value": _contract_value(value.value)}
    if inspect.isfunction(value):
        _function_contract(value, label, identities, settings, seen)
        return "trusted_function_default"
    if isinstance(value, MappingProxyType):
        value = dict(value)
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("MEMO_CONTRACT_DEFAULT")
        return {
            key: _default_contract(item, label + ":" + key, identities, settings, seen)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple, set, frozenset)):
        values = [
            _default_contract(item, label + ":" + str(index), identities, settings, seen)
            for index, item in enumerate(value)
        ]
        return (
            sorted(values, key=canonical_bytes) if isinstance(value, (set, frozenset)) else values
        )
    return _contract_value(value)


def _function_contract(
    function: Any,
    label: str,
    identities: list[object],
    settings: dict[str, Any],
    seen: set[object],
) -> None:
    identities.append((label, function, function.__code__))
    if function in seen:
        return
    seen.add(function)
    settings[label] = {
        "defaults": _default_contract(
            function.__defaults__, label + ":defaults", identities, settings, seen
        ),
        "kwdefaults": _default_contract(
            function.__kwdefaults__, label + ":kwdefaults", identities, settings, seen
        ),
    }
    wrapped = getattr(function, "__wrapped__", None)
    if inspect.isfunction(wrapped):
        _function_contract(wrapped, label + ":wrapped", identities, settings, seen)
    # Decorators close over trusted callables. Mutable observer lists, argument
    # objects and caller/source data are neither retained nor token material.
    for name, cell in zip(function.__code__.co_freevars, function.__closure__ or (), strict=True):
        try:
            closed = cell.cell_contents
        except ValueError:
            continue
        if inspect.isfunction(closed):
            _function_contract(closed, label + ":closure:" + name, identities, settings, seen)
        elif isinstance(closed, CodeType):
            identities.append((label, "closure", name, closed))


def _native_contract_stamp(settings: dict[str, Any]) -> bytes | None:
    """Snapshot trusted metadata with the native encoder, never decode it."""
    encoder = marshal.dumps
    if (
        encoder is not _NATIVE_CONTRACT_ENCODER
        or type(encoder) is not BuiltinFunctionType
        or getattr(encoder, "__name__", None) != "dumps"
        or getattr(encoder, "__module__", None) != "marshal"
        or getattr(encoder, "__self__", None) is not marshal
    ):
        return None
    try:
        return cast(bytes, encoder(settings, 4))
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None


def _contract_certification_context() -> tuple[dict[str, Any], tuple[object, ...]]:
    identities: list[object] = []
    defaults: dict[str, Any] = {}
    if not inspect.isfunction(_contract_digest):
        raise ValueError("MEMO_UNKNOWN_CANONICAL_CONTRACT")
    _function_contract(_contract_digest, "canonical_contract", identities, defaults, set())
    return defaults, tuple(identities)


def _certified_contract_digest(settings: dict[str, Any]) -> str:
    """Reuse successful shape certification after a fresh typed native stamp.

    Every live setting and callable context is reconstructed before this call.
    Misses retain the existing bounded JSON guard and canonical digest. Native
    bytes are transient; only their SHA-256 and trusted guard identities enter
    the operation-local bounded cache. No record, source or verdict is retained.
    """
    defaults, context = _contract_certification_context()
    material = {"settings": settings, "canonical_defaults": defaults}
    stamp = _native_contract_stamp(material)
    if stamp is None:
        return _contract_digest(settings)
    key = (artifact_digest(stamp), context)
    session = locator_validation_session()
    certified = session.certified_contract(key)
    if certified is not None:
        return certified
    canonical_digest = _contract_digest(settings)
    after_defaults, after_context = _contract_certification_context()
    if (
        after_context != context
        or _native_contract_stamp({"settings": settings, "canonical_defaults": after_defaults})
        != stamp
    ):
        raise ValueError("MEMO_CONTRACT_CHANGED_DURING_CERTIFICATION")
    session.remember_contract_certification(key, canonical_digest)
    return canonical_digest


_STRUCTURAL_MODULES = {
    "integrity": (),
    "paper_store": (),
    "paper_records": (),
    "paper_sources": (
        "MAX_FILES",
        "MAX_BYTES",
        "MAX_FILE_BYTES",
        "MAX_ELEMENTS",
        "MAX_PAGES",
        "MAX_PARSE_OUTPUT",
        "MAX_VALIDATION_PDFS",
        "MAX_VALIDATION_TEXT_BYTES",
        "ROLE_NAMES",
    ),
    "schema": (),
    "kernel": ("SCHEMA", "VERSION", "DIMENSIONS", "STATES", "MODES", "POLICIES", "RELATIONS"),
    "attempts": (
        "_SHA256_RE",
        "_LEAN_NAME_RE",
        "_LEAN_IMPORT_RE",
        "_LEAN_TOOLCHAIN_RE",
    ),
    "evidence_records": ("VERSION", "KINDS", "_RECORD_SCHEMAS"),
    "evidence_adapter": ("POLICY",),
    "trust": ("RECORD_PAYLOAD_TYPES",),
    "formalize": (
        "THEOREM_ROLES",
        "METHOD",
        "MAX_STATEMENT_BYTES",
        "MAX_EXPRESSION_BYTES",
        "MAX_NODES",
        "MAX_POWER",
        "MAX_LITERAL",
        "_TOKEN",
        "_BODY",
    ),
    "exact_check": (),
    "execution": ("TOOLCHAIN", "AXIOMS", "CHECKER_DIGEST", "WORKER"),
    "source_semantics": (),
    "semantic_candidates": (
        "DECOMPOSITION_PROMPT",
        "FIDELITY_PROMPT",
        "FIDELITY_INDEPENDENCE",
        "ID",
        "IDS",
        "DECOMPOSITION_ROW",
        "FIDELITY_ROW",
    ),
    "extractor": ("PROMPT", "RESPONSE_SCHEMA", "BUDGET_DEFAULTS"),
    "paper_stages": ("PURE_STAGES",),
    "paper_checkers": (),
    "paper_actions": ("VERSION", "HEURISTIC", "LIMIT"),
    "paper_revision": ("PLAN_VERSION", "MAX_DEPENDENCIES"),
}

_STRUCTURAL_SCHEMAS = (
    "paper-input",
    "document-ir",
    "kernel",
    "source-locator",
    "stage-result",
    "formal_obligation",
    "formalization-binding",
    "verifier-profile",
    "environment-manifest",
    "execution-event",
    "review-decision",
    "acceptance-record",
    "assessment-record",
    "checker-result",
    "semantic-candidate",
    "candidate-fidelity-report",
    "action-planning",
    "formalization-result",
    "paper-records",
    "extractor-config",
    "pipeline-assessment",
)


def _effective_validator_contract(
    validator: Any,
    label: str,
    identities: list[object],
    function_settings: dict[str, Any],
    seen: set[object],
) -> dict[str, Any]:
    if validator.format_checker is not None or validator._ref_resolver is not None:
        raise ValueError("MEMO_UNKNOWN_SCHEMA_RESOLVER")
    identities.extend(
        (
            (label, "instance", _ContractIdentity(validator)),
            (label, "registry", _ContractIdentity(validator._registry)),
            (label, "resolver", _ContractIdentity(validator._resolver)),
            (label, "resolver_registry", _ContractIdentity(validator._resolver._registry)),
        )
    )
    compiled = []
    for index, (checker, keyword, constraint) in enumerate(validator._validators):
        identities.append((label, index, keyword, _ContractIdentity(checker)))
        if not inspect.isfunction(checker):
            raise ValueError("MEMO_UNKNOWN_SCHEMA_CHECKER")
        _function_contract(
            checker,
            label + ":compiled:" + keyword + ":" + str(index),
            identities,
            function_settings,
            seen,
        )
        compiled.append({"keyword": keyword, "constraint": constraint})
    return {
        "schema": validator.schema,
        "compiled": compiled,
        "resolver_base": validator._resolver._base_uri,
        "resolver_previous": list(validator._resolver._previous),
    }


def _bundle_validation_key(
    body_digest: str, bundle: dict[str, Any]
) -> tuple[str, str, tuple[object, ...]] | None:
    """A bounded operation token for CAS-backed structure, never applicability.

    Modules are observed only if already loaded by the actual validation path.
    A lazy import or contract change during validation prevents insertion. Wider
    override/legacy replay paths deliberately keep their full existing checks.
    """
    if not isinstance(bundle, dict) or not isinstance(bundle.get("run_manifest"), dict):
        return None
    run = bundle["run_manifest"]
    context = run.get("analysis_context")
    if (
        bundle.get("interpretation_overrides")
        or (
            run.get("record_contract_version") != "1.0"
            and "schema_version" not in bundle.get("assessment", {})
        )
        or (
            bundle.get("extraction_events")
            and (not isinstance(context, dict) or "extractor_contract" not in context)
        )
    ):
        return None
    settings: dict[str, Any] = {}
    if not inspect.isfunction(validate_bundle):
        return None
    identities: list[object] = []
    function_settings: dict[str, Any] = {}
    seen: set[object] = set()
    try:
        _function_contract(validate_bundle, "validate_bundle", identities, function_settings, seen)
        for name, constants in _STRUCTURAL_MODULES.items():
            module = sys.modules.get("proofmap." + name)
            if module is None:
                settings[name] = None
                continue
            identities.append((name, module))
            settings[name] = {key: _contract_value(getattr(module, key)) for key in constants}
            # Aliases also bind the effective functions used by a validator.
            for key, value in sorted(vars(module).items()):
                if inspect.isfunction(value):
                    _function_contract(value, name + ":" + key, identities, function_settings, seen)
                elif callable(value) and hasattr(value, "cache_info"):
                    identities.append((name, key, _ContractIdentity(value)))
                    wrapped = getattr(value, "__wrapped__", None)
                    if inspect.isfunction(wrapped):
                        _function_contract(
                            wrapped,
                            name + ":" + key + ":wrapped",
                            identities,
                            function_settings,
                            seen,
                        )
                elif isinstance(value, type):
                    identities.append((name, key, value))
                    if value.__module__ == module.__name__:
                        for member_name, member in sorted(vars(value).items()):
                            if isinstance(member, (staticmethod, classmethod)):
                                member = member.__func__
                            if inspect.isfunction(member):
                                _function_contract(
                                    member,
                                    name + ":" + key + ":" + member_name,
                                    identities,
                                    function_settings,
                                    seen,
                                )
                            elif isinstance(member, property):
                                for mode, accessor in (
                                    ("get", member.fget),
                                    ("set", member.fset),
                                    ("del", member.fdel),
                                ):
                                    if accessor is not None:
                                        _function_contract(
                                            accessor,
                                            name + ":" + key + ":" + member_name + ":" + mode,
                                            identities,
                                            function_settings,
                                            seen,
                                        )
        schema_module = sys.modules.get("proofmap.schema")
        records_module = sys.modules.get("proofmap.evidence_records")
        jsonschema_module = sys.modules.get("jsonschema")
        if schema_module is None or records_module is None or jsonschema_module is None:
            return None
        backend = jsonschema_module.Draft202012Validator
        identities.extend(
            (
                ("schema_backend", backend),
                ("schema_type_checker", _ContractIdentity(backend.TYPE_CHECKER)),
            )
        )
        for kind, checkers in (
            ("keyword", backend.VALIDATORS),
            ("type", backend.TYPE_CHECKER._type_checkers),
        ):
            for name, checker in sorted(checkers.items()):
                identities.append((kind, name, _ContractIdentity(checker)))
                if inspect.isfunction(checker):
                    _function_contract(
                        checker,
                        "schema_backend:" + kind + ":" + name,
                        identities,
                        function_settings,
                        seen,
                    )
        for name, member in sorted(vars(backend).items()):
            if inspect.isfunction(member):
                _function_contract(
                    member, "schema_backend:" + name, identities, function_settings, seen
                )
        # Normal schema checks use private cached validators below. The action
        # record path alone reads this small resource directly on every check.
        if "action_plan" in bundle:
            settings["action_schema_resource"] = artifact_digest(
                files("proofmap.resources").joinpath("action-planning.schema.json").read_bytes()
            )
        effective_schemas = {}
        for name in _STRUCTURAL_SCHEMAS:
            validator = schema_module._validator(name)
            effective_schemas["schema:" + name] = _effective_validator_contract(
                validator, "schema:" + name, identities, function_settings, seen
            )
        for name in sorted(records_module._RECORD_SCHEMAS):
            validator = records_module._record_validator(name)
            effective_schemas["record:" + name] = _effective_validator_contract(
                validator, "record:" + name, identities, function_settings, seen
            )
        registry = schema_module._registry()
        identities.append(("registry", _ContractIdentity(registry)))
        settings["registry_resources"] = {
            uri: resource.contents for uri, resource in registry.items()
        }
        settings["effective_schemas"] = effective_schemas
        settings["function_defaults"] = function_settings
        settings["schema_implementation"] = version("jsonschema")
        if any(
            row.get("locator", {}).get("format") == "pdf"
            for row in bundle.get("document_ir", {}).get("elements", [])
        ):
            try:
                settings["pdf_parser_version"] = version("pypdf")
            except PackageNotFoundError:
                settings["pdf_parser_version"] = None
        return body_digest, _certified_contract_digest(settings), tuple(identities)
    except (AttributeError, OSError, TypeError, ValueError, RecursionError, PackageNotFoundError):
        # Unknown trusted configuration disables an optimization, never a check.
        return None


def _validate_lexical_context(
    ir: dict[str, Any],
    elements: dict[str, dict[str, Any]],
    declared: dict[str, dict[str, Any]],
    artifacts: dict[str, bytes] | None,
) -> None:
    """Validate syntax-record structure, never authenticate inferred TeX meanings."""
    metadata = {"lexical_scope", "declaration", "binding_status", "binding_reason"}
    if "lexical_scopes" not in ir:
        if any(metadata & row.keys() for row in elements.values()):
            raise ValueError("LEXICAL_SCOPE_TABLE_MISSING")
        return  # Historical IR did not emit the explicit lexical table.
    scopes = {row["id"]: row for row in ir["lexical_scopes"]}
    if len(scopes) != len(ir["lexical_scopes"]):
        raise ValueError("DUPLICATE_LEXICAL_SCOPE")
    root = scopes.get("tex:global")
    if root is None or root["kind"] != "ROOT":
        raise ValueError("LEXICAL_ROOT_MISSING")

    def anchor(loc: dict[str, Any]) -> None:
        source = declared.get(loc["artifact"])
        if (
            validate("source-locator", loc)
            or source is None
            or source["sha256"] != loc["artifact_sha256"]
            or loc["format"] != "tex"
            or loc["offsets"] != "utf8-bytes-half-open"
            or any(
                loc.get(key) is not None
                for key in ("page", "text_start", "text_end", "parser_version")
            )
            or type(loc["start"]) is not int
            or type(loc["end"]) is not int
            or not 0 <= loc["start"] <= loc["end"] <= source["size"]
        ):
            raise ValueError("LEXICAL_SOURCE_ANCHOR")
        if artifacts is not None:
            raw = artifacts[loc["artifact"]][loc["start"] : loc["end"]]
            if artifact_digest(raw) != loc["excerpt_sha256"]:
                raise ValueError("LEXICAL_SOURCE_EXCERPT")
            raw.decode("utf-8")  # Reject partial UTF-8 code points without executing TeX.

    def contained(loc: dict[str, Any], enclosing: dict[str, Any] | None) -> bool:
        return (
            enclosing is None
            or loc["artifact"] != enclosing["artifact"]  # Includes retain their own source file.
            or enclosing["start"] <= loc["start"] <= loc["end"] <= enclosing["end"]
        )

    for scope in scopes.values():
        if (scope["resolution"] == "RESOLVED") != (not scope["reasons"]):
            raise ValueError("LEXICAL_SCOPE_RESOLUTION")
        if scope["kind"] == "ROOT":
            if scope["id"] != "tex:global" or any(
                scope[name] is not None for name in ("parent", "name", "locator")
            ):
                raise ValueError("LEXICAL_ROOT_SHAPE")
            continue
        if scope["parent"] not in scopes or scope["locator"] is None:
            raise ValueError("LEXICAL_SCOPE_PARENT_OR_ANCHOR")
        if (scope["kind"] == "GROUP" and scope["name"] is not None) or (
            scope["kind"] == "ENVIRONMENT" and scope["name"] is None
        ):
            raise ValueError("LEXICAL_SCOPE_NAME")
        anchor(scope["locator"])
        expected = digest(
            "tex-lexical-scope.v1",
            {
                "revision": ir["revision"],
                "locator": scope["locator"],
                "kind": scope["kind"],
            },
        )
        if scope["id"] != expected:
            raise ValueError("LEXICAL_SCOPE_ID")
        if not contained(scope["locator"], scopes[scope["parent"]]["locator"]):
            raise ValueError("LEXICAL_SCOPE_OUTSIDE_PARENT")
    # A linear walk with completed chains avoids quadratic work for adversarial depth.
    complete: set[str] = set()
    for ident in scopes:
        chain: set[str] = set()
        cursor: str | None = ident
        while cursor is not None and cursor not in complete:
            if cursor in chain:
                raise ValueError("LEXICAL_SCOPE_CYCLE")
            chain.add(cursor)
            cursor = scopes[cursor]["parent"]
        complete.update(chain)

    children: dict[str, builtins.list[str]] = {ident: [] for ident in scopes}
    for ident, scope in scopes.items():
        if scope["parent"] is not None:
            children[scope["parent"]].append(ident)
    opened: dict[str, int] = {}
    closed: dict[str, int] = {}
    pending = [("tex:global", False, 0)]
    clock = 0
    while pending:
        ident, exiting, depth = pending.pop()
        if depth > 64:  # Match the bounded TeX walker; ancestry lookup stays linear overall.
            raise ValueError("RESOURCE_LIMIT: lexical scope nesting")
        clock += 1
        if exiting:
            closed[ident] = clock
        else:
            opened[ident] = clock
            pending.append((ident, True, depth))
            pending.extend((child, False, depth + 1) for child in children[ident])
    order = {ident: index for index, ident in enumerate(elements)}

    def earlier_visible(target: dict[str, Any], use: dict[str, Any]) -> bool:
        before, current = target.get("lexical_scope"), use.get("lexical_scope")
        return (
            before in opened
            and current in opened
            and order[target["id"]] < order[use["id"]]
            and opened[before] <= opened[current] < closed[before]
        )

    declarations = {ident: row for ident, row in elements.items() if "declaration" in row}
    active: dict[str, dict[str, str]] = {ident: {} for ident in scopes}

    def visible_definition(symbol: str | None, lexical_scope: str) -> str | None:
        if symbol is None:
            return None
        current: str | None = lexical_scope
        while current is not None:
            if symbol in active[current]:
                return active[current][symbol]
            current = scopes[current]["parent"]
        return None

    for element in elements.values():
        scope = scopes.get(element.get("lexical_scope"))
        if scope is None:
            raise ValueError("ELEMENT_LEXICAL_SCOPE_MISSING")
        anchor(element["locator"])
        if not contained(element["locator"], scope["locator"]):
            raise ValueError("ELEMENT_OUTSIDE_LEXICAL_SCOPE")
        if "owner" in element and (
            element["owner"] not in elements or element["owner"] == element["id"]
        ):
            raise ValueError("LEXICAL_OWNER_REFERENCE")
        if (element["kind"] == "MACRO_DEFINITION") != ("declaration" in element):
            raise ValueError("MACRO_DECLARATION_KIND")
        if "declaration" in element:
            declaration = element["declaration"]
            previous = declaration["previous_definition"]
            if previous != visible_definition(declaration["symbol"], scope["id"]):
                raise ValueError("MACRO_PREVIOUS_DEFINITION")
            if previous is not None:
                target = declarations.get(previous)
                if (
                    previous == element["id"]
                    or target is None
                    or target["declaration"]["symbol"] != declaration["symbol"]
                    or target["declaration"]["binding_status"] not in {"DEFINED", "REDEFINED"}
                    or not earlier_visible(target, element)
                ):
                    raise ValueError("MACRO_PREVIOUS_DEFINITION")
            if declaration["resolution"] == "RESOLVED" and (
                declaration["binding_status"] in {"INVALID", "UNSUPPORTED"}
                or declaration["symbol"] is None
                or declaration["parameter_count"] is None
                or declaration["replacement"] is None
            ):
                raise ValueError("MACRO_DECLARATION_RESOLUTION")
            if declaration["binding_status"] in {"DEFINED", "REDEFINED"}:
                if declaration["symbol"] is None:
                    raise ValueError("MACRO_DECLARATION_SYMBOL")
                active[scope["id"]][declaration["symbol"]] = element["id"]
        if element["kind"] == "SYMBOL_OCCURRENCE":
            if not {"symbol", "binding_status", "binding_reason"} <= element.keys():
                raise ValueError("MACRO_USE_FIELDS")
            state, reason = element.get("binding_status"), element.get("binding_reason")
            if element.get("text") != "\\" + element.get("symbol", ""):
                raise ValueError("MACRO_USE_TOKEN")
            if state == "RESOLVED":
                target = declarations.get(element.get("definition", ""))
                if (
                    reason is not None
                    or target is None
                    or target["declaration"]["symbol"] != element["symbol"]
                    or target["declaration"]["resolution"] != "RESOLVED"
                    or target["declaration"]["binding_status"] not in {"DEFINED", "REDEFINED"}
                    or not earlier_visible(target, element)
                    or element["definition"] != visible_definition(element["symbol"], scope["id"])
                ):
                    raise ValueError("MACRO_USE_BINDING")
            elif state != "UNRESOLVED" or not reason or "definition" in element:
                raise ValueError("MACRO_USE_UNRESOLVED")
        elif {"binding_status", "binding_reason", "definition"} & element.keys():
            raise ValueError("MACRO_USE_KIND")
        dependencies = element.get("context_dependencies", [])
        if len(dependencies) != len(set(dependencies)) or any(
            ident not in declarations
            or declarations[ident]["declaration"]["resolution"] != "RESOLVED"
            for ident in dependencies
        ):
            raise ValueError("MACRO_CONTEXT_DEPENDENCY")
    complete.clear()
    for ident in declarations:
        chain = set()
        cursor = ident
        while cursor is not None and cursor not in complete:
            if cursor in chain:
                raise ValueError("MACRO_DECLARATION_CYCLE")
            chain.add(cursor)
            cursor = declarations[cursor]["declaration"]["previous_definition"]
        complete.update(chain)


def validate_bundle(bundle: dict[str, Any], artifacts: dict[str, bytes] | None = None) -> None:
    """Validate structure and exact subjects, without authenticating cached verdicts."""
    canonical_bytes(bundle)
    required = {
        "input_manifest",
        "document_ir",
        "assertions",
        "symbols",
        "argument_map",
        "extraction_events",
        "findings",
        "assessment",
        "run_manifest",
    }
    if not isinstance(bundle, dict) or not required <= bundle.keys():
        raise ValueError("INVALID_STORED_BUNDLE")
    from .paper_records import validate_paper_records

    validate_paper_records(bundle)
    manifest, run, ir = bundle["input_manifest"], bundle["run_manifest"], bundle["document_ir"]
    actual = {
        name: digest("paper-bundle-component.v1", value)
        for name, value in bundle.items()
        if name != "run_manifest"
    }
    if run.get("bundle_digests") != actual:
        raise ValueError("STALE_OR_MIXED_PAPER_BUNDLE")
    for name, value in (
        ("paper-input", manifest),
        ("document-ir", ir),
        ("kernel", bundle["argument_map"]),
    ):
        if validate(name, value):
            raise ValueError("INVALID_PAPER_BUNDLE_SCHEMA: " + name)
    revision = manifest["revision"]
    if revision != digest(
        "paper-manifest.v1",
        {"entrypoint": manifest["entrypoint"], "artifacts": manifest["artifacts"]},
    ):
        raise ValueError("INVALID_SOURCE_REVISION")
    if (
        run.get("schema_version") != "1.0"
        or run.get("revision") != revision
        or ir["revision"] != revision
    ):
        raise ValueError("MIXED_PAPER_REVISION")
    if not isinstance(run.get("run_id"), str) or not run["run_id"]:
        raise ValueError("INVALID_RUN_ID")
    require_digest(run["analysis_digest"])
    require_digest(run["policy_digest"])
    declared = {relative_path(row["path"]): row for row in manifest["artifacts"]}
    if len(declared) != len(manifest["artifacts"]) or manifest["entrypoint"] not in declared:
        raise ValueError("INVALID_SOURCE_ARTIFACTS")
    if artifacts is not None:
        if set(artifacts) != set(declared) or any(
            type(row["size"]) is not int
            or len(artifacts[name]) != row["size"]
            or artifact_digest(artifacts[name]) != row["sha256"]
            for name, row in declared.items()
        ):
            raise ValueError("SOURCE_ARTIFACT_MISMATCH")
    elements = {row["id"]: row for row in ir["elements"]}
    if len(elements) != len(ir["elements"]):
        raise ValueError("DUPLICATE_SOURCE_ELEMENT")
    locator_session = locator_validation_session()
    for element in elements.values():
        loc = element["locator"]
        source = declared.get(loc.get("artifact"))
        if (
            element["revision"] != revision
            or source is None
            or source["sha256"] != loc.get("artifact_sha256")
        ):
            raise ValueError("SOURCE_ELEMENT_BINDING")
        if validate("source-locator", loc):
            raise ValueError("INVALID_SOURCE_LOCATOR")
        identity = {"revision": revision, "locator": loc}
        if loc["format"] != "pdf":
            identity["kind"] = element["kind"]
        if element["id"] != digest("source-element.v1", identity):
            raise ValueError("SOURCE_ELEMENT_ID")
        if artifacts is not None:
            validate_locator(loc, artifacts, element["text"], session=locator_session)
    _validate_lexical_context(ir, elements, declared, artifacts)
    if "mathematical_context" in ir or "source_inferences" in ir:
        from .source_semantics import validate_source_semantics

        validate_source_semantics(ir)
    seen = set()
    for assertion in bundle["assertions"]:
        element = elements.get(assertion["id"])
        if (
            assertion["id"] in seen
            or element is None
            or assertion.get("revision") != revision
            or assertion.get("statement") != element["text"]
            or assertion.get("source_ids") != [element["id"]]
        ):
            raise ValueError("ASSERTION_SOURCE_MISMATCH")
        seen.add(assertion["id"])
    KernelMap.from_dict(bundle["argument_map"]).validate()
    for stage in bundle.get("stage_manifests", []):
        StageResult.from_dict(stage)
        if stage["revision"] != revision:
            raise ValueError("STAGE_REVISION_MISMATCH")
    from .attempts import FormalObligation
    from .evidence_records import obligation_identity, validate_record

    bindings = {}
    for row in bundle.get("formalizations", []):
        from .formalize import validate_formalization

        validate_formalization(row)
        if "binding" not in row:
            if row.get("status") == "SUPPORTED":
                raise ValueError("FORMALIZATION_BINDING_MISSING")
            continue
        binding = row["binding"]
        validate_record(binding)
        assertion = next(
            (a for a in bundle["assertions"] if a["id"] == binding["assertion_id"]), None
        )
        if (
            assertion is None
            or row.get("status") != "SUPPORTED"
            or row.get("assertion_id") != binding["assertion_id"]
            or row.get("revision") != revision
            or binding["revision_id"] != revision
            or binding["assertion_digest"] != digest("assertion.v1", assertion)
        ):
            raise ValueError("FORMALIZATION_ASSERTION_MISMATCH")
        from .formalize import definition_context

        context = definition_context(ir, elements[assertion["id"]])
        source_locators = [elements[source_id]["locator"] for source_id in assertion["source_ids"]]
        source_locators.extend(
            elements[dependency["id"]]["locator"] for dependency in context.get("dependencies", [])
        )
        if (
            binding["source_locators"] != source_locators
            or row.get("source_locators") != source_locators
        ):
            raise ValueError("FORMALIZATION_SOURCE_LOCATOR_MISMATCH")
        if any(row.get(name) != binding[name] for name in ("context_digest", "definition_digest")):
            raise ValueError("FORMALIZATION_CONTEXT_MISMATCH")
        if not isinstance(row.get("candidate"), str) or binding[
            "candidate_digest"
        ] != artifact_digest(row["candidate"].encode("utf-8")):
            raise ValueError("FORMALIZATION_CANDIDATE_MISMATCH")
        obligation = FormalObligation.from_dict(row["obligation"])
        if obligation.target_node_id != assertion["id"] or binding[
            "obligation_digest"
        ] != obligation_identity(obligation):
            raise ValueError("FORMALIZATION_OBLIGATION_MISMATCH")
        bindings[binding["id"]] = binding
        history = row.get("historical_execution")
        if history is not None:
            if (
                set(history)
                != {"parent_run_id", "parent_revision", "binding", "obligation", "execution"}
                or "execution_event" in row
            ):
                raise ValueError("HISTORICAL_EXECUTION_FIELDS")
            old_binding = history["binding"]
            validate_record(old_binding)
            old_obligation = FormalObligation.from_dict(history["obligation"])
            old_event = history["execution"]["event"]
            validate_record(old_event)
            if (
                old_binding["revision_id"] != history["parent_revision"]
                or old_binding["obligation_digest"] != obligation_identity(old_obligation)
                or old_event["binding_digest"] != old_binding["id"]
                or old_event["outcome"] != "VERIFIED"
                or not history["parent_run_id"]
            ):
                raise ValueError("HISTORICAL_EXECUTION_BINDING")
            _audit_record({"record": old_event, "envelope": history["execution"].get("envelope")})
    for result in bundle.get("execution_events", []):
        event = result["event"]
        validate_record(event)
        _audit_record({"record": event, "envelope": result.get("envelope")})
        if event.get("binding_digest") not in bindings:
            raise ValueError("EXECUTION_BINDING_MISMATCH")
    for acceptance in bundle.get("acceptance_records", []):
        validate_record(acceptance)
        if acceptance["binding_digest"] not in bindings:
            raise ValueError("ACCEPTANCE_BINDING_MISMATCH")
    for record in bundle.get("assessment_records", []):
        validate_record(record)
        candidates = [
            binding
            for binding in bindings.values()
            if record["subject"] in {binding["assertion_id"], "formal:" + binding["assertion_id"]}
        ]
        if len(candidates) != 1 or record["context_digest"] != candidates[0]["context_digest"]:
            raise ValueError("ASSESSMENT_SUBJECT_BINDING")
    from .semantic_candidates import validate_candidate, validate_fidelity_report

    context = run.get("analysis_context")
    if context is not None:
        from .extractor import chunk_document, extract, semantic_overlay, validate_recorded_event

        extraction_config = context["config"].get("extractor")
        events = bundle["extraction_events"]
        if events:
            if extraction_config is None or context["extractor_mode"] == "none":
                raise ValueError("EXTRACTION_CONFIGURATION_MISSING")
            chunks, _ = chunk_document(ir)
            if len(events) > len(chunks):
                raise ValueError("EXTRACTION_EVENT_COUNT")
            # A budget-limited run may contain a valid prefix of source chunks.
            for chunk, event in zip(chunks, events, strict=False):
                contract = context.get("extractor_contract")
                if contract is None:
                    extract(chunk, extraction_config, replay=event)
                else:
                    prompt_key = {
                        "classification": "classification_prompt",
                        "decomposition": "decomposition_prompt",
                        "candidate-fidelity": "fidelity_prompt",
                    }[extraction_config.get("stage", "classification")]
                    validate_recorded_event(
                        chunk, extraction_config, event, prompt_digest=contract[prompt_key]
                    )
        if canonical_bytes(semantic_overlay(ir, events)) != canonical_bytes(
            bundle.get("semantic_overlay")
        ):
            raise ValueError("SEMANTIC_OVERLAY_DERIVATION")
    candidates = bundle.get("semantic_overlay", {}).get("candidates", [])
    for candidate in candidates:
        validate_candidate(candidate, ir)
    if "candidate_fidelity" in bundle:
        fidelity_prompt = (
            context.get("extractor_contract", {}).get("fidelity_prompt") if context else None
        )
        validate_fidelity_report(
            bundle["candidate_fidelity"], ir, candidates, recorded_prompt_digest=fidelity_prompt
        )
        if (
            context is not None
            and bundle["candidate_fidelity"]["configuration"]
            != context["candidate_fidelity_config"]
        ):
            raise ValueError("FIDELITY_CONFIGURATION_BINDING")
    from .paper_checkers import validate_result

    for result in bundle["assessment"].get("checkers", []):
        if "schema_version" in result:
            validate_result(result)
            if result["revision"] != revision or not set(result["source_ids"]) <= set(elements):
                raise ValueError("CHECKER_SOURCE_BINDING")
            if any(
                finding.get("source") is not None and finding["source"] not in result["source_ids"]
                for finding in result["findings"]
            ):
                raise ValueError("CHECKER_FINDING_SOURCE_BINDING")
    if "action_plan" in bundle:
        from .paper_actions import validate_action_record

        validate_action_record(bundle["action_plan"])
    if "revision_plan" in bundle:
        from .paper_revision import validate_revision_plan

        validate_revision_plan(bundle["revision_plan"], ir)
        if bundle["revision_plan"]["analysis_context"] != run.get("analysis_context"):
            raise ValueError("REVISION_ANALYSIS_CONTEXT")
    if "interpretation_overrides" in bundle:
        from .paper_overrides import validate_override_bundle

        validate_override_bundle(bundle)


def _entity_rows(
    bundle: dict[str, Any],
) -> builtins.list[tuple[str, builtins.list[dict[str, Any]]]]:
    return [
        ("element", bundle["document_ir"]["elements"]),
        ("assertion", bundle["assertions"]),
        ("inference", bundle["argument_map"]["inferences"]),
        ("finding", bundle["findings"]),
        ("revision_decision", bundle.get("revision_plan", {}).get("rows", [])),
        *[
            (name, bundle.get(name, []))
            for name in (
                "formalizations",
                "execution_events",
                "stage_manifests",
                "acceptance_records",
                "assessment_records",
            )
        ],
    ]


def _audit_record(value: dict[str, Any]) -> dict[str, Any]:
    """Check the stored record/envelope relationship, without granting authority."""
    from .evidence_records import validate_record
    from .trust import RECORD_PAYLOAD_TYPES

    if not isinstance(value, dict):
        raise ValueError("AUDIT_RECORD_TYPE")
    if "record" in value and set(value) != {"record", "envelope"}:
        raise ValueError("AUDIT_WRAPPER_FIELDS")
    typed = value.get("record", value)
    validate_record(typed)
    envelope = value.get("envelope")
    if envelope is not None:
        expected_type = RECORD_PAYLOAD_TYPES.get(typed["record_type"])
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"payloadType", "payload", "signatures"}
            or expected_type is None
            or envelope["payloadType"] != expected_type
        ):
            raise ValueError("AUDIT_ENVELOPE_TYPE_OR_FIELDS")
        payload = envelope["payload"]
        if not isinstance(payload, str) or len(payload) > 48_000_000:
            raise ValueError("AUDIT_ENVELOPE_PAYLOAD_TYPE")
        try:
            decoded = strict_loads(base64.b64decode(payload, validate=True))
        except (ValueError, TypeError) as exc:
            raise ValueError("AUDIT_ENVELOPE_PAYLOAD_INVALID") from exc
        if canonical_bytes(decoded) != canonical_bytes(typed):
            raise ValueError("AUDIT_ENVELOPE_RECORD_MISMATCH")
    return dict(typed)


class PaperStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "index.sqlite3")
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3):
            raise ValueError("Unsupported paper store schema version")
        from .campaign.store import backup_before_migration, migrate

        backup_before_migration(self, version)
        with self.db:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS papers(id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY, paper_id TEXT NOT NULL REFERENCES papers(id), manifest TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, revision TEXT NOT NULL REFERENCES revisions(id), analysis TEXT NOT NULL, bundle TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS entities(revision TEXT NOT NULL REFERENCES revisions(id), id TEXT NOT NULL, kind TEXT NOT NULL, body TEXT NOT NULL, PRIMARY KEY(revision,id,kind));
            CREATE TABLE IF NOT EXISTS reviews(id TEXT PRIMARY KEY, revision TEXT NOT NULL REFERENCES revisions(id), analysis TEXT NOT NULL, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS stages(id TEXT PRIMARY KEY, cache_key TEXT NOT NULL, revision TEXT NOT NULL, analysis TEXT NOT NULL, stage TEXT NOT NULL, manifest TEXT NOT NULL, output TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS stages_key ON stages(cache_key);
            CREATE TABLE IF NOT EXISTS audit_records(id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), revision TEXT NOT NULL REFERENCES revisions(id), kind TEXT NOT NULL, body TEXT NOT NULL);
            """)
        migrate(self, version)

    def close(self) -> None:
        self.db.close()

    def put(self, data: bytes) -> str:
        sha = artifact_digest(data)
        target = self.root / "objects" / sha[:2] / sha[2:]
        if target.exists():
            if artifact_digest(target.read_bytes()) != sha:
                raise ValueError("CORRUPT_CAS_OBJECT")
        else:
            atomic_write(target, data)
        return sha

    def get(self, sha: str) -> bytes:
        require_digest(sha)
        raw = (self.root / "objects" / sha[:2] / sha[2:]).read_bytes()
        if artifact_digest(raw) != sha:
            raise ValueError("CORRUPT_CAS_OBJECT")
        return raw

    def ingest(self, paper: str, bundle: dict[str, Any], artifacts: dict[str, bytes]) -> None:
        if not isinstance(paper, str) or not paper.strip():
            raise ValueError("INVALID_PAPER_ID")
        manifest = bundle["input_manifest"]
        run = bundle["run_manifest"]
        existing = self.db.execute(
            "SELECT bundle FROM runs WHERE id=?", (run["run_id"],)
        ).fetchone()
        if existing:
            prior = strict_loads(self.get(existing[0]))["bundle"]
            if canonical_bytes(prior) != canonical_bytes(bundle):
                raise ValueError("Run ID collision with different immutable content")
        # An import can omit already held source bytes; it cannot invent or omit material.
        if not artifacts:
            artifacts = {row["path"]: self.get(row["sha256"]) for row in manifest["artifacts"]}
        validate_bundle(bundle, artifacts)
        self._validate_revision_lineage(bundle, paper)
        blobs = {name: self.put(data) for name, data in artifacts.items()}
        body = {"bundle": bundle, "artifacts": blobs}
        bundle_hash = self.put(canonical_bytes(body))
        manifest_hash = self.put(canonical_bytes(manifest))
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO papers VALUES(?)", (paper,))
            old = self.db.execute(
                "SELECT paper_id,manifest FROM revisions WHERE id=?", (manifest["revision"],)
            ).fetchone()
            if old and old[0] != paper:
                raise ValueError("Revision already indexed under another paper identity")
            if old and old[1] != manifest_hash:
                raise ValueError("Immutable revision manifest collision")
            self.db.execute(
                "INSERT OR IGNORE INTO revisions VALUES(?,?,?)",
                (manifest["revision"], paper, manifest_hash),
            )
            existing = self.db.execute(
                "SELECT bundle FROM runs WHERE id=?", (run["run_id"],)
            ).fetchone()
            if existing and existing[0] != bundle_hash:
                raise ValueError("Run ID collision with different immutable content")
            self.db.execute(
                "INSERT OR IGNORE INTO runs VALUES(?,?,?,?)",
                (run["run_id"], manifest["revision"], run["analysis_digest"], bundle_hash),
            )
            for kind, rows in _entity_rows(bundle):
                for index, row in enumerate(rows):
                    ident = (
                        run["analysis_digest"]
                        + ":"
                        + run["run_id"]
                        + ":"
                        + row.get("id", str(index))
                    )
                    self.db.execute(
                        "INSERT OR IGNORE INTO entities VALUES(?,?,?,?)",
                        (manifest["revision"], ident, kind, self.put(canonical_bytes(row))),
                    )

    def list(self, query: str = "") -> builtins.list[dict[str, str]]:
        return [
            dict(zip(("paper", "revision", "run", "analysis"), row, strict=True))
            for row in self.db.execute(
                "SELECT p.id,r.id,u.id,u.analysis FROM papers p JOIN revisions r ON p.id=r.paper_id JOIN runs u ON r.id=u.revision WHERE instr(p.id,?)>0 ORDER BY p.id,r.id,u.id",
                (query,),
            )
        ]

    @source_validation_leaf_operation
    def inspect(self, run_id: str) -> dict[str, Any]:
        row = self.db.execute("SELECT bundle FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown run")
        value = strict_loads(self.get(row[0]))
        if not isinstance(value, dict):
            raise ValueError("INVALID_STORED_BUNDLE")
        artifacts = {name: self.get(sha) for name, sha in value["artifacts"].items()}
        session = locator_validation_session()
        key = (
            _bundle_validation_key(row[0], value["bundle"])
            if session.structural_reuse_enabled
            else None
        )
        if key is not None and session.bundle_validated(key):
            return value
        validate_bundle(value["bundle"], artifacts)
        # A lazy import or a setting changed by validation has not yet been
        # validated under its new contract. Never retain that changed context.
        if key is not None and _bundle_validation_key(row[0], value["bundle"]) == key:
            session.remember_bundle_validation(key)
        return value

    def latest(self, paper: str) -> dict[str, Any] | None:
        """Validate the most recently published immutable run for this exact paper."""
        row = self.db.execute(
            "SELECT u.id FROM runs u JOIN revisions r ON r.id=u.revision WHERE r.paper_id=? ORDER BY u.rowid DESC LIMIT 1",
            (paper,),
        ).fetchone()
        return self.inspect(row[0])["bundle"] if row is not None else None

    def _validate_revision_lineage(self, bundle: dict[str, Any], paper: str) -> None:
        from .paper_revision import revision_plan

        plan = bundle.get("revision_plan")
        if plan is not None:
            formalizations = {row["assertion_id"]: row for row in bundle.get("formalizations", [])}
            stages = {row["id"]: row for row in bundle.get("stage_manifests", [])}
            for decision in plan["rows"]:
                current = formalizations[decision["assertion_id"]]
                actual_stage = stages.get(decision["pure_stage"])
                if (
                    actual_stage is None
                    or actual_stage["stage"] != "formalization"
                    or actual_stage["inputs"]
                    != {
                        "assertion": decision["assertion_id"],
                        "dependencies": decision["fingerprint"],
                    }
                ):
                    raise ValueError("REVISION_PURE_STAGE_BINDING")
                loaded = self.stage_by_id(actual_stage["id"])
                if (
                    loaded["manifest"] != actual_stage
                    or loaded["output"]["parent_stage"] != decision["parent_stage"]
                ):
                    raise ValueError("REVISION_PURE_STAGE_BINDING")
                if decision["parent_stage"] is not None and decision["pure_execution"] != "REUSED":
                    raise ValueError("REVISION_REUSE_EXECUTION_MISMATCH")
                history = current.get("historical_execution")
                expected_execution = (
                    "HISTORICAL_REUSE"
                    if history is not None
                    else "EXECUTED"
                    if "execution_event" in current
                    else "NOT_RUN"
                )
                event = history["execution"]["event"]["id"] if history is not None else None
                if (
                    decision["formal_execution"] != expected_execution
                    or decision["historical_event"] != event
                    or (history is not None and not decision["reuse_eligible"])
                ):
                    raise ValueError("REVISION_FORMAL_EXECUTION_MISMATCH")
        if plan is not None and plan["parent_run"] is not None:
            if plan["parent_run"] == bundle["run_manifest"]["run_id"]:
                raise ValueError("REVISION_LINEAGE_CYCLE")
            row = self.db.execute(
                "SELECT r.paper_id FROM runs u JOIN revisions r ON r.id=u.revision WHERE u.id=?",
                (plan["parent_run"],),
            ).fetchone()
            if row is None or row[0] != paper:
                raise ValueError("REVISION_PARENT_PAPER")
            parent = self.inspect(plan["parent_run"])["bundle"]
            expected = revision_plan(parent, bundle["document_ir"], plan["analysis_context"])
            if plan["parent_revision"] != expected["parent_revision"]:
                raise ValueError("REVISION_PARENT_BINDING")
            runtime = {
                "pure_stage",
                "parent_stage",
                "pure_execution",
                "cache_validation",
                "formal_execution",
                "historical_event",
            }
            for actual, target in zip(plan["rows"], expected["rows"], strict=True):
                if {k: v for k, v in actual.items() if k not in runtime} != {
                    k: v for k, v in target.items() if k not in runtime
                }:
                    raise ValueError("REVISION_LINEAGE_MISMATCH")
                if actual["parent_stage"] is not None:
                    stage = self.stage_by_id(actual["parent_stage"])
                    if (
                        not actual["reuse_eligible"]
                        or stage["output"]["fingerprint"] != actual["fingerprint"]
                    ):
                        raise ValueError("REVISION_STAGE_DEPENDENCY_MISMATCH")
        for current in bundle.get("formalizations", []):
            history = current.get("historical_execution")
            if history is None:
                continue
            parent = self.inspect(history["parent_run_id"])["bundle"]
            if parent["input_manifest"]["revision"] != history["parent_revision"]:
                raise ValueError("HISTORICAL_PARENT_REVISION")
            if not any(
                row.get("binding") == history["binding"]
                and row.get("obligation") == history["obligation"]
                for row in parent["formalizations"]
            ):
                raise ValueError("HISTORICAL_PARENT_SUBJECT")
            if history["execution"] not in parent["execution_events"]:
                raise ValueError("HISTORICAL_PARENT_EXECUTION")

    def stage_by_id(self, ident: str) -> dict[str, Any]:
        """Read an immutable pure artifact without treating it as current execution."""
        require_digest(ident)
        row = self.db.execute("SELECT manifest,output FROM stages WHERE id=?", (ident,)).fetchone()
        if row is None:
            raise ValueError("REVISION_STAGE_MISSING")
        manifest = StageResult.from_dict(strict_loads(self.get(row[0]))).to_dict()
        if (
            manifest["id"] != ident
            or manifest["output_digest"] != row[1]
            or manifest["stage"] not in PURE_STAGES
        ):
            raise ValueError("REVISION_STAGE_BINDING")
        self._check_stage_parents(manifest, set())
        output = strict_loads(self.get(row[1]))
        validate_stage_output(manifest["stage"], manifest["revision"], output)
        return {"manifest": manifest, "output": output}

    def commit_stage(
        self,
        *,
        revision: str,
        analysis: str,
        stage: str,
        inputs: dict[str, str],
        implementation: str,
        output: dict[str, Any],
        parents: dict[str, str] | None = None,
        namespace: str = "local-controller",
        outcome: str = "PASS",
        findings: builtins.list[dict[str, Any]] | None = None,
        coverage: dict[str, Any] | None = None,
        resource_use: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        key = stage_key(
            revision=revision,
            analysis=analysis,
            stage=stage,
            inputs=inputs,
            implementation=implementation,
            parents=parents,
            namespace=namespace,
        )
        validate_stage_output(stage, revision, output)
        value = {
            **key,
            "record_type": "StageResult",
            "schema_version": "1.0",
            "outcome": outcome,
            "output_digest": self.put(canonical_bytes(output)),
            "findings": findings or [],
            "coverage": coverage or {},
            "resource_use": resource_use or {},
            "cache_provenance": {
                "namespace": namespace,
                "origin": "controller-stage",
                "trust": "UNTRUSTED_ANALYSIS_NOT_EVIDENCE",
            },
        }
        value["id"] = digest("stage-result.v1", value)
        StageResult.from_dict(value)
        self._check_stage_parents(value, set())
        cache_key = digest("stage-cache-key.v1", key)
        manifest_sha = self.put(canonical_bytes(value))
        with self.db:
            old = self.db.execute(
                "SELECT manifest FROM stages WHERE cache_key=? ORDER BY rowid DESC", (cache_key,)
            ).fetchall()
            for (old_sha,) in old:
                prior = strict_loads(self.get(old_sha))
                if prior["id"] == value["id"]:
                    return value
                if prior["outcome"] in {"PASS", "PARTIAL"}:
                    raise ValueError("STAGE_IMMUTABLE_COLLISION")
            self.db.execute(
                "INSERT INTO stages VALUES(?,?,?,?,?,?,?)",
                (
                    value["id"],
                    cache_key,
                    revision,
                    analysis,
                    stage,
                    manifest_sha,
                    value["output_digest"],
                ),
            )
        return value

    def _check_stage_parents(self, value: dict[str, Any], active: set[str]) -> None:
        if value["id"] in active or len(active) > 64:
            raise ValueError("STAGE_PARENT_CYCLE")
        for name, ident in value["parents"].items():
            row = self.db.execute("SELECT manifest FROM stages WHERE id=?", (ident,)).fetchone()
            if row is None:
                raise ValueError("STAGE_PARENT_MISSING")
            parent = StageResult.from_dict(strict_loads(self.get(row[0]))).to_dict()
            if (
                parent["id"] != ident
                or parent["stage"] != name
                or any(parent[k] != value[k] for k in ("revision", "analysis", "namespace"))
            ):
                raise ValueError("STAGE_PARENT_BINDING")
            self.get(parent["output_digest"])
            self._check_stage_parents(parent, active | {value["id"]})

    def load_stage(
        self,
        *,
        revision: str,
        analysis: str,
        stage: str,
        inputs: dict[str, str],
        implementation: str,
        parents: dict[str, str] | None = None,
        namespace: str = "local-controller",
    ) -> dict[str, Any] | None:
        key = stage_key(
            revision=revision,
            analysis=analysis,
            stage=stage,
            inputs=inputs,
            implementation=implementation,
            parents=parents,
            namespace=namespace,
        )
        if stage not in PURE_STAGES:
            return None
        row = self.db.execute(
            "SELECT id,manifest,output FROM stages WHERE cache_key=? ORDER BY rowid DESC LIMIT 1",
            (digest("stage-cache-key.v1", key),),
        ).fetchone()
        if row is None:
            return None
        manifest = StageResult.from_dict(strict_loads(self.get(row[1]))).to_dict()
        if (
            manifest["id"] != row[0]
            or manifest["output_digest"] != row[2]
            or any(manifest[k] != v for k, v in key.items())
        ):
            raise ValueError("STAGE_CACHE_BINDING")
        self._check_stage_parents(manifest, set())
        output = strict_loads(self.get(row[2]))
        validate_stage_output(stage, revision, output)
        if manifest["outcome"] not in {"PASS", "PARTIAL"}:
            return None
        return {"manifest": manifest, "output": output}

    def add_review(self, review: dict[str, Any]) -> str:
        raw = canonical_bytes(review)
        sha = self.put(raw)
        with self.db:
            self.db.execute(
                "INSERT OR IGNORE INTO reviews VALUES(?,?,?,?)",
                (sha, review["revision"], review["analysis_digest"], sha),
            )
        return sha

    def list_reviews(self, revision: str, analysis: str) -> builtins.list[dict[str, Any]]:
        records = []
        for ident, body in self.db.execute(
            "SELECT id,body FROM reviews WHERE revision=? AND analysis=? ORDER BY rowid",
            (revision, analysis),
        ):
            if ident != body:
                raise ValueError("REVIEW_INDEX_BINDING")
            review = strict_loads(self.get(body))
            if review.get("revision") != revision or review.get("analysis_digest") != analysis:
                raise ValueError("REVIEW_INDEX_BINDING")
            records.append(review)
        return records

    def add_audit(self, run_id: str, record: dict[str, Any]) -> str:
        """Append a validated audit record; persistence does not confer authority."""
        return self.add_audits(run_id, [record])[0]

    def add_audits(self, run_id: str, records: builtins.list[dict[str, Any]]) -> builtins.list[str]:
        """Validate every audit against one fresh run snapshot and append atomically.

        Only the indexed batch is transactional. Content-addressed objects may
        remain unreferenced after failure, as with singleton writes. No validation
        result or trust decision is reused across calls.
        """
        if not records:
            return []
        snapshots = []
        for record in records:
            raw = canonical_bytes(record)
            snapshot = strict_loads(raw)
            snapshots.append((raw, snapshot, _audit_record(snapshot)))
        row = self.db.execute("SELECT revision,analysis FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("AUDIT_RUN_MISSING")
        bundle = self.inspect(run_id)["bundle"]
        binding_ids = {
            entry["binding"]["id"]
            for entry in bundle.get("formalizations", [])
            if "binding" in entry
        }
        for _, _, typed in snapshots:
            for field in ("revision", "revision_id"):
                if field in typed and typed[field] != row[0]:
                    raise ValueError("AUDIT_REVISION_MISMATCH")
            for field in ("analysis", "analysis_digest"):
                if field in typed and typed[field] != row[1]:
                    raise ValueError("AUDIT_ANALYSIS_MISMATCH")
            for field in ("binding_id", "binding_digest"):
                if field in typed and typed[field] not in binding_ids:
                    raise ValueError("AUDIT_BINDING_MISMATCH")
        prepared = [
            (
                digest("paper-audit.v1", {"run_id": run_id, "record": snapshot}),
                self.put(raw),
                typed["record_type"],
            )
            for raw, snapshot, typed in snapshots
        ]
        with self.db:
            for ident, body, kind in prepared:
                old = self.db.execute(
                    "SELECT body FROM audit_records WHERE id=?", (ident,)
                ).fetchone()
                if old is not None and old[0] != body:
                    raise ValueError("AUDIT_IMMUTABLE_COLLISION")
                self.db.execute(
                    "INSERT OR IGNORE INTO audit_records VALUES(?,?,?,?,?)",
                    (ident, run_id, row[0], kind, body),
                )
        return [ident for ident, _, _ in prepared]

    def list_audit(self, run_id: str, kind: str | None = None) -> builtins.list[dict[str, Any]]:
        records = []
        for ident, stored_kind, sha in self.db.execute(
            "SELECT id,kind,body FROM audit_records WHERE run_id=? AND (? IS NULL OR kind=?) ORDER BY rowid",
            (run_id, kind, kind),
        ):
            record = strict_loads(self.get(sha))
            typed = _audit_record(record)
            if typed["record_type"] != stored_kind or ident != digest(
                "paper-audit.v1", {"run_id": run_id, "record": record}
            ):
                raise ValueError("AUDIT_BINDING_MISMATCH")
            records.append(record)
        return records

    @source_validation_operation
    def rebuild(self) -> None:
        # Rebuild derived entities from immutable run objects, preserving history.
        rows = list(self.db.execute("SELECT bundle FROM runs ORDER BY id"))
        with self.db:
            self.db.execute("DELETE FROM entities")
            for (sha,) in rows:
                stored = strict_loads(self.get(sha))
                bundle = stored["bundle"]
                validate_bundle(
                    bundle, {name: self.get(sha) for name, sha in stored["artifacts"].items()}
                )
                paper_row = self.db.execute(
                    "SELECT paper_id FROM revisions WHERE id=?",
                    (bundle["input_manifest"]["revision"],),
                ).fetchone()
                if paper_row is None:
                    raise ValueError("REVISION_PARENT_PAPER")
                self._validate_revision_lineage(bundle, paper_row[0])
                revision = bundle["input_manifest"]["revision"]
                for kind, records in _entity_rows(bundle):
                    for index, row in enumerate(records):
                        self.db.execute(
                            "INSERT OR IGNORE INTO entities VALUES(?,?,?,?)",
                            (
                                revision,
                                bundle["run_manifest"]["analysis_digest"]
                                + ":"
                                + bundle["run_manifest"]["run_id"]
                                + ":"
                                + row.get("id", str(index)),
                                kind,
                                self.put(canonical_bytes(row)),
                            ),
                        )
