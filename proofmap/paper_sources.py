"""Bounded manuscript acquisition and syntax-preserving source IR.

No TeX engine, build hook, URL fetch, macro execution or OCR is invoked.
Unsupported constructs are retained as source, never invented mathematics.
"""

from __future__ import annotations

import base64
import io
import math
import os
import re
import stat
import subprocess
import sys
import tarfile
import zipfile
from collections import OrderedDict
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import wraps
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from types import FunctionType
from typing import Any, ParamSpec, TypeVar

from .integrity import (
    artifact_digest,
    canonical_bytes,
    digest,
    relative_path,
    rooted_path,
    strict_loads,
)

MAX_FILES = 256
MAX_BYTES = 16_000_000
MAX_FILE_BYTES = 4_000_000
MAX_ELEMENTS = 20_000
MAX_PAGES = 100
MAX_PARSE_OUTPUT = 64_000_000
MAX_VALIDATION_PDFS = 16
MAX_VALIDATION_TEXT_BYTES = MAX_BYTES
MAX_VALIDATED_BUNDLES = 128
ROLE_NAMES = {
    "theorem": "THEOREM",
    "lemma": "LEMMA",
    "proposition": "PROPOSITION",
    "corollary": "COROLLARY",
    "conjecture": "CONJECTURE",
    "definition": "DEFINITION",
    "assumption": "ASSUMPTION",
    "hypothesis": "ASSUMPTION",
    "remark": "REMARK",
    "example": "EXAMPLE",
}


@dataclass(frozen=True)
class SourceLocator:
    artifact: str
    artifact_sha256: str
    format: str
    start: int | None = None
    end: int | None = None
    page: int | None = None
    excerpt_sha256: str = ""
    offsets: str = "utf8-bytes-half-open"
    text_start: int | None = None
    text_end: int | None = None
    parser_version: str | None = None


@dataclass(frozen=True)
class InputManifest:
    revision: str
    entrypoint: str
    artifacts: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"$schema": "urn:proofmap:paper-input:1", "schema_version": "1.0", **asdict(self)}


def acquire(path: Path, entrypoint: str | None = None) -> tuple[InputManifest, dict[str, bytes]]:
    """Read into bounded memory; archives never write members to the filesystem."""
    files: dict[str, bytes] = {}
    seen: set[str] = set()
    total = 0

    def add(name: str, size: int, read: Any) -> None:
        nonlocal total
        relative_path(name)
        if name.casefold() in seen:
            raise ValueError("ARCHIVE_CASE_COLLISION")
        seen.add(name.casefold())
        if size > MAX_FILE_BYTES or size < 0 or len(files) >= MAX_FILES or total + size > MAX_BYTES:
            raise ValueError("RESOURCE_LIMIT: manuscript files/bytes")
        data = read(MAX_FILE_BYTES + 1)
        if len(data) != size:
            raise ValueError("ARTIFACT_SIZE_MISMATCH")
        total += len(data)
        files[name] = data

    if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
        raise ValueError("UNSAFE_PATH: input link")
    if path.is_dir():
        for folder, dirs, names in os.walk(path, followlinks=False):
            for name in dirs + names:
                candidate = Path(folder) / name
                portable = candidate.relative_to(path).as_posix()
                rooted_path(path, portable)
                if candidate.is_file():
                    with candidate.open("rb") as stream:
                        add(portable, candidate.stat().st_size, stream.read)
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            if len(archive.infolist()) > MAX_FILES:
                raise ValueError("RESOURCE_LIMIT: archive members")
            for member in archive.infolist():
                relative_path(member.orig_filename.rstrip("/"))
                if member.is_dir():
                    relative_path(member.filename.rstrip("/"))
                    continue
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) and not stat.S_ISREG(mode)):
                    raise ValueError("UNSAFE_ARCHIVE_MEMBER")
                if member.flag_bits & 1 or member.file_size > max(1, member.compress_size) * 200:
                    raise ValueError("UNSAFE_ARCHIVE_COMPRESSION")
                with archive.open(member) as zip_stream:
                    add(member.filename, member.file_size, zip_stream.read)
    elif tarfile.is_tarfile(path):
        with tarfile.open(path) as tar_archive:
            for index, tar_member in enumerate(tar_archive):
                if index >= MAX_FILES:
                    raise ValueError("RESOURCE_LIMIT: archive members")
                relative_path(tar_member.name.rstrip("/"))
                if tar_member.isdir():
                    continue
                if not tar_member.isfile():
                    raise ValueError("UNSAFE_ARCHIVE_MEMBER")
                tar_stream = tar_archive.extractfile(tar_member)
                if tar_stream is None:
                    raise ValueError("UNREADABLE_ARCHIVE_MEMBER")
                with tar_stream:
                    add(tar_member.name, tar_member.size, tar_stream.read)
    else:
        with path.open("rb") as stream:
            add(path.name, path.stat().st_size, stream.read)
    if not files:
        raise ValueError("EMPTY_MANUSCRIPT")
    if entrypoint is None:
        candidates = sorted(name for name in files if name.endswith((".tex", ".pdf")))
        roots = [
            name
            for name in candidates
            if name.endswith(".tex") and b"\\documentclass" in files[name]
        ]
        if len(roots) == 1:
            entrypoint = roots[0]
        elif len(candidates) == 1:
            entrypoint = candidates[0]
        else:
            raise ValueError("AMBIGUOUS_ENTRYPOINT: specify --entrypoint")
    relative_path(entrypoint)
    if entrypoint not in files:
        raise ValueError("MISSING_ENTRYPOINT")
    artifacts = tuple(
        {"path": name, "sha256": artifact_digest(data), "size": len(data)}
        for name, data in sorted(files.items())
    )
    revision = digest("paper-manifest.v1", {"entrypoint": entrypoint, "artifacts": artifacts})
    return InputManifest(revision, entrypoint, artifacts), files


def _pdf_pages(raw: bytes) -> list[str]:
    from pypdf import Configuration, PdfReader

    Configuration.zlib_maximum_output_length = MAX_BYTES
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
        raise ValueError("UNSUPPORTED_OR_OVERSIZE_PDF")
    texts = []
    for page in reader.pages:
        text = page.extract_text(extraction_mode="plain") or ""
        if len(text.encode("utf-8")) > MAX_FILE_BYTES:
            raise ValueError("RESOURCE_LIMIT: PDF text")
        texts.append(text)
    return texts


def _pdf_parser_context() -> tuple[str, tuple[object, ...]] | None:
    """Live trusted parser identities/defaults, without importing PDF adapters."""
    settings: dict[str, Any] = {}
    identities: list[object] = []
    active: set[FunctionType] = set()
    complete: set[FunctionType] = set()

    def bind(function: Any, name: str) -> bool:
        if not isinstance(function, FunctionType) or len(complete) + len(active) >= 64:
            return False
        identities.append((name, function, function.__code__))
        if function in active:
            return False
        if function in complete:
            return True
        active.add(function)
        settings[name] = {"defaults": function.__defaults__, "kwdefaults": function.__kwdefaults__}
        wrapped = getattr(function, "__wrapped__", None)
        if wrapped is not None and not bind(wrapped, name + ":wrapped"):
            return False
        for closed_name, cell in zip(
            function.__code__.co_freevars, function.__closure__ or (), strict=True
        ):
            try:
                closed = cell.cell_contents
            except ValueError:
                continue
            if isinstance(closed, FunctionType) and not bind(
                closed, name + ":closure:" + closed_name
            ):
                return False
        active.remove(function)
        complete.add(function)
        return True

    try:
        for name, function in (
            ("parse", parse),
            ("worker", _parse_in_worker),
            ("pdf", parse_pdf),
            ("pages", _pdf_pages),
        ):
            if not bind(function, name):
                return None
        return digest("pdf-parser-context.v1", settings), tuple(identities)
    except (TypeError, ValueError, AttributeError):
        return None


class LocatorValidationSession:
    """Bounded pure reconstruction/structural tokens; never current authority."""

    def __init__(self, *, structural_reuse: bool = True) -> None:
        # Unknown runtime flags conservatively disable structural tokens.
        self._structural_reuse = structural_reuse is True
        self._pages: OrderedDict[tuple[str, tuple[object, ...]], tuple[tuple[str, ...], int]] = (
            OrderedDict()
        )
        self._text_bytes = 0
        self._bundle_validations: OrderedDict[tuple[str, str, tuple[object, ...]], None] = (
            OrderedDict()
        )
        self._contract_certifications: OrderedDict[tuple[str, tuple[object, ...]], str] = (
            OrderedDict()
        )

    def clear_bundle_validations(self) -> None:
        self._bundle_validations.clear()
        self._contract_certifications.clear()

    @property
    def structural_reuse_enabled(self) -> bool:
        return self._limit_structural_tokens()

    def _limit_structural_tokens(self) -> bool:
        if self._structural_reuse is not True or MAX_VALIDATED_BUNDLES <= 0:
            self.clear_bundle_validations()
            return False
        while len(self._bundle_validations) > MAX_VALIDATED_BUNDLES:
            self._bundle_validations.popitem(last=False)
        while len(self._contract_certifications) > MAX_VALIDATED_BUNDLES:
            self._contract_certifications.popitem(last=False)
        return True

    def certified_contract(self, key: tuple[str, tuple[object, ...]]) -> str | None:
        if not self._limit_structural_tokens() or key not in self._contract_certifications:
            return None
        self._contract_certifications.move_to_end(key)
        return self._contract_certifications[key]

    def remember_contract_certification(
        self, key: tuple[str, tuple[object, ...]], canonical_digest: str
    ) -> None:
        if not self._limit_structural_tokens():
            return
        # Only fixed-size digests and trusted code identities are retained.
        # The native serialization and live settings never enter the session.
        self._contract_certifications[key] = canonical_digest
        self._contract_certifications.move_to_end(key)
        self._limit_structural_tokens()

    def bundle_validated(self, key: tuple[str, str, tuple[object, ...]]) -> bool:
        if not self._limit_structural_tokens():
            return False
        if key not in self._bundle_validations:
            return False
        self._bundle_validations.move_to_end(key)
        return True

    def remember_bundle_validation(self, key: tuple[str, str, tuple[object, ...]]) -> None:
        if not self._limit_structural_tokens():
            return
        self._bundle_validations[key] = None
        self._bundle_validations.move_to_end(key)
        self._limit_structural_tokens()

    def pdf_pages(self, raw: bytes) -> list[str]:
        source_digest = artifact_digest(raw)
        try:
            parser_version: str | None = version("pypdf")
        except PackageNotFoundError:
            # Let the existing isolated parser report the unavailable optional adapter.
            parser_version = None
        parser_context = _pdf_parser_context()
        content_key = digest(
            "pdf-validation-reconstruction.v1",
            {
                "source": source_digest,
                "parser": "pypdf",
                "parser_version": parser_version,
                "parser_context": parser_context[0] if parser_context is not None else None,
                "timeout_seconds": 45,
                "max_bytes": MAX_BYTES,
                "max_file_bytes": MAX_FILE_BYTES,
                "max_pages": MAX_PAGES,
                "max_files": MAX_FILES,
                "max_elements": MAX_ELEMENTS,
                "max_parse_output": MAX_PARSE_OUTPUT,
            },
        )
        key = (content_key, parser_context[1]) if parser_context is not None else None
        if key is None or key not in self._pages:
            artifacts = ({"path": "source.pdf", "sha256": source_digest, "size": len(raw)},)
            manifest = InputManifest(
                digest("paper-manifest.v1", {"entrypoint": "source.pdf", "artifacts": artifacts}),
                "source.pdf",
                artifacts,
            )
            ir = parse(manifest, {"source.pdf": raw}, "pypdf")
            if ir["parser"]["execution"] != "COMPLETED":
                raise ValueError("PDF_RECONSTRUCTION_TIMEOUT")
            pages = tuple(el["text"] for el in ir["elements"])
            size = sum(len(page.encode("utf-8")) for page in pages)
            if (
                key is not None
                and _pdf_parser_context() == parser_context
                and MAX_VALIDATION_PDFS > 0
                and size <= MAX_VALIDATION_TEXT_BYTES
            ):
                while self._pages and (
                    len(self._pages) >= MAX_VALIDATION_PDFS
                    or self._text_bytes + size > MAX_VALIDATION_TEXT_BYTES
                ):
                    _, (_, removed) = self._pages.popitem(last=False)
                    self._text_bytes -= removed
                self._pages[key] = (pages, size)
                self._text_bytes += size
            else:
                return list(pages)
        assert key is not None
        self._pages.move_to_end(key)
        # Callers cannot mutate the immutable reconstruction retained for other checks.
        return list(self._pages[key][0])


_validation_session: ContextVar[LocatorValidationSession | None] = ContextVar(
    "source_validation_session", default=None
)
_P = ParamSpec("_P")
_R = TypeVar("_R")


def locator_validation_session() -> LocatorValidationSession:
    return _validation_session.get() or LocatorValidationSession()


@contextmanager
def source_validation_scope(*, structural_reuse: bool = True) -> Iterator[LocatorValidationSession]:
    """Reuse exact-byte reconstruction within the inherited operation scope."""
    existing = _validation_session.get()
    if existing is not None:
        yield existing
        return
    # Nested operations always inherit the existing session unchanged.
    session = LocatorValidationSession(structural_reuse=structural_reuse)
    token = _validation_session.set(session)
    try:
        yield session
    finally:
        session.clear_bundle_validations()
        _validation_session.reset(token)


def source_validation_operation(function: Callable[_P, _R]) -> Callable[_P, _R]:
    @wraps(function)
    def operation(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with source_validation_scope():
            return function(*args, **kwargs)

    return operation


def source_validation_leaf_operation(function: Callable[_P, _R]) -> Callable[_P, _R]:
    """Share reconstruction while avoiding tokens in a standalone leaf call."""

    @wraps(function)
    def operation(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        with source_validation_scope(structural_reuse=False):
            return function(*args, **kwargs)

    return operation


def validate_locator(
    locator: dict[str, Any],
    files: dict[str, bytes],
    excerpt: str,
    *,
    session: LocatorValidationSession | None = None,
) -> None:
    loc = SourceLocator(**locator)
    if loc.artifact not in files or artifact_digest(files[loc.artifact]) != loc.artifact_sha256:
        raise ValueError("STALE_SOURCE_LOCATOR")
    if loc.format == "tex":
        if (
            loc.offsets != "utf8-bytes-half-open"
            or loc.text_start is not None
            or loc.text_end is not None
            or loc.parser_version is not None
            or loc.page is not None
            or type(loc.start) is not int
            or type(loc.end) is not int
            or not 0 <= loc.start <= loc.end <= len(files[loc.artifact])
        ):
            raise ValueError("INVALID_SOURCE_RANGE")
        raw = files[loc.artifact][loc.start : loc.end]
        if raw.decode("utf-8") != excerpt or artifact_digest(raw) != loc.excerpt_sha256:
            raise ValueError("SOURCE_EXCERPT_MISMATCH")
    elif loc.format == "pdf":
        if (
            type(loc.page) is not int
            or loc.page < 1
            or loc.start is not None
            or loc.end is not None
            or loc.offsets != "reconstructed-text-no-source-offsets"
        ):
            raise ValueError("INVALID_PDF_LOCATOR")
        pages = (session or locator_validation_session()).pdf_pages(files[loc.artifact])
        if loc.page > len(pages):
            raise ValueError("INVALID_PDF_PAGE")
        reconstructed = pages[loc.page - 1]
        # Historical locators represented entire pages; retain an explicit reader.
        if loc.text_start is None and loc.text_end is None and loc.parser_version is None:
            actual = reconstructed
        else:
            if (
                loc.parser_version != version("pypdf")
                or type(loc.text_start) is not int
                or type(loc.text_end) is not int
                or not 0 <= loc.text_start <= loc.text_end <= len(reconstructed)
            ):
                raise ValueError("INVALID_PDF_RECONSTRUCTION_RANGE")
            actual = reconstructed[loc.text_start : loc.text_end]
        if actual != excerpt or artifact_digest(actual.encode("utf-8")) != loc.excerpt_sha256:
            raise ValueError("SOURCE_EXCERPT_MISMATCH")
    else:
        raise ValueError("UNSUPPORTED_LOCATOR")


def parse_tex(manifest: InputManifest, files: dict[str, bytes]) -> dict[str, Any]:
    from pylatexenc.latex2text import get_default_latex_context_db as get_symbol_context
    from pylatexenc.latexwalker import (
        LatexWalker,
        LatexWalkerParseError,
        get_default_latex_context_db,
    )
    from pylatexenc.macrospec import MacroSpec

    elements: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    labels: dict[str, list[str]] = {}
    references: list[dict[str, Any]] = []
    bibliography_requests: list[tuple[str, str, str]] = []
    scopes: list[dict[str, Any]] = [{"id": "global", "parent": None}]
    lexical_scopes: list[dict[str, Any]] = [
        {
            "id": "tex:global",
            "parent": None,
            "kind": "ROOT",
            "name": None,
            "locator": None,
            "resolution": "RESOLVED",
            "reasons": [],
        }
    ]
    # TeX grouping and mathematical discourse are different hierarchies. Sections
    # change discourse ownership but do not restore TeX definitions.
    frames: list[dict[str, Any]] = [{"record": lexical_scopes[0], "bindings": {}}]
    declarations: dict[str, dict[str, Any]] = {}
    section_stack: list[tuple[int, str]] = []
    declaration_commands = {"newcommand", "renewcommand", "providecommand", "DeclareMathOperator"}
    dynamic_commands = {
        "def",
        "gdef",
        "edef",
        "xdef",
        "let",
        "futurelet",
        "global",
        "globaldefs",
        "catcode",
        "csname",
        "endcsname",
        "expandafter",
        "noexpand",
        "aftergroup",
        "begingroup",
        "endgroup",
        "bgroup",
        "egroup",
        "if",
        "ifx",
        "ifnum",
        "ifdefined",
        "else",
        "fi",
        "newenvironment",
        "renewenvironment",
        "provideenvironment",
    }
    theorem_envs = set(ROLE_NAMES)
    environment_roles = dict(ROLE_NAMES)
    environment_declarations: dict[str, str] = {}
    context = get_default_latex_context_db()
    # The syntax database omits many zero-argument math symbols (including
    # \\in). Consult the bundled symbol catalog only for known names; never
    # render, expand, or infer mathematical meaning from its text mappings.
    symbol_context = get_symbol_context()

    def known_macro(symbol: str) -> bool:
        return (
            context.get_macro_spec(symbol) is not None
            or symbol_context.get_macro_spec(symbol) is not None
        )

    context.add_context_category(
        "proofmap",
        macros=[
            MacroSpec("newtheorem", "*{[{["),
            MacroSpec("cref", "{"),
            MacroSpec("Cref", "{"),
            MacroSpec("eqref", "{"),
            MacroSpec("bibliography", "{"),
            MacroSpec("bibitem", "[{"),
            MacroSpec("addbibresource", "[{"),
            MacroSpec("citep", "*[[{"),
            MacroSpec("citet", "*[[{"),
            MacroSpec("autocite", "*[[{"),
            MacroSpec("parencite", "*[[{"),
            MacroSpec("include", "{"),
        ],
        prepend=True,
    )
    visited: set[str] = set()
    included: list[str] = []

    def finding(code: str, source: str, detail: str = "") -> None:
        findings.append(
            {
                "code": code,
                "source": source,
                "detail": detail,
                "classification": "REVIEW_REQUIRED",
                "blocking_eligible": False,
            }
        )

    def arguments(node: Any, text: str) -> list[str]:
        result = []
        for arg in getattr(getattr(node, "nodeargd", None), "argnlist", ()) or ():
            if arg is not None:
                raw = text[arg.pos : arg.pos + arg.len]
                result.append(raw[1:-1] if raw.startswith(("{", "[")) else raw)
        return result

    def poison(code: str, source: str, detail: str, *, global_effect: bool = False) -> None:
        for frame in frames if global_effect else frames[-1:]:
            record = frame["record"]
            record["resolution"] = "UNRESOLVED"
            if code not in record["reasons"]:
                record["reasons"].append(code)
        finding(code, source, detail)

    def parse_file(name: str, active: tuple[str, ...], scope: str) -> str:
        if name in active:
            poison(
                "INCLUDE_CYCLE", name, "Included declarations are unresolved", global_effect=True
            )
            return scope
        if name in visited:
            poison(
                "REPEATED_INCLUDE",
                name,
                "Retained once; repeated execution semantics unresolved",
                global_effect=True,
            )
            return scope
        if len(active) >= 32:
            raise ValueError("RESOURCE_LIMIT: include nesting")
        if name not in files:
            poison(
                "MISSING_INCLUDE", name, "Included declarations are unresolved", global_effect=True
            )
            return scope
        visited.add(name)
        text = files[name].decode("utf-8")
        # Character -> original UTF-8 byte offsets, built once (not per anchor).
        offsets = [0]
        for ch in text:
            offsets.append(offsets[-1] + len(ch.encode("utf-8")))
        artifact_hash = artifact_digest(files[name])
        try:
            nodes, _, _ = LatexWalker(
                text, latex_context=context, tolerant_parsing=False
            ).get_latex_nodes(pos=0)
        except (ValueError, RecursionError, LatexWalkerParseError) as exc:
            poison("TEX_PARSE_ERROR", name, type(exc).__name__, global_effect=True)
            nodes = []

        def locator(node: Any) -> SourceLocator:
            start, end = node.pos, node.pos + node.len
            excerpt = text[start:end]
            return SourceLocator(
                name,
                artifact_hash,
                "tex",
                offsets[start],
                offsets[end],
                excerpt_sha256=artifact_digest(excerpt.encode("utf-8")),
            )

        def emit(node: Any, kind: str, current: str) -> dict[str, Any]:
            if len(elements) >= MAX_ELEMENTS:
                raise ValueError("RESOURCE_LIMIT: source elements")
            excerpt = text[node.pos : node.pos + node.len]
            loc = locator(node)
            identifier = digest(
                "source-element.v1",
                {"revision": manifest.revision, "locator": asdict(loc), "kind": kind},
            )
            element: dict[str, Any] = {
                "id": identifier,
                "revision": manifest.revision,
                "kind": kind,
                "scope": current,
                "lexical_scope": frames[-1]["record"]["id"],
                "text": excerpt,
                "locator": asdict(loc),
                "labels": [],
                "references": [],
                "citations": [],
                "proof_for": None,
                "quality": "SYNTAX_ONLY",
                "math_ast": None,
            }
            elements.append(element)
            return element

        def push_frame(node: Any, kind: str, frame_name: str | None = None) -> None:
            if len(lexical_scopes) >= MAX_ELEMENTS:
                raise ValueError("RESOURCE_LIMIT: lexical scopes")
            loc = asdict(locator(node))
            parent = frames[-1]
            record = {
                "id": digest(
                    "tex-lexical-scope.v1",
                    {"revision": manifest.revision, "locator": loc, "kind": kind},
                ),
                "parent": parent["record"]["id"],
                "kind": kind,
                "name": frame_name,
                "locator": loc,
                "resolution": parent["record"]["resolution"],
                "reasons": list(parent["record"]["reasons"]),
            }
            lexical_scopes.append(record)
            frames.append({"record": record, "bindings": dict(parent["bindings"])})

        def argument_nodes(node: Any) -> list[Any]:
            return list(getattr(getattr(node, "nodeargd", None), "argnlist", ()) or ())

        def argument_text(node: Any | None) -> str | None:
            if node is None:
                return None
            raw = text[node.pos : node.pos + node.len]
            return raw[1:-1] if type(node).__name__ == "LatexGroupNode" else raw

        def replacement_tokens(node: Any, depth: int = 0) -> list[str]:
            if depth > 64:
                raise ValueError("RESOURCE_LIMIT: macro replacement nesting")
            result = []
            if type(node).__name__ == "LatexMacroNode":
                result.append(node.macroname)
            for child in getattr(node, "nodelist", ()) or ():
                result.extend(replacement_tokens(child, depth + 1))
            for child in argument_nodes(node):
                if child is not None:
                    result.extend(replacement_tokens(child, depth + 1))
            return result

        def declare(node: Any, current: str) -> None:
            el = emit(node, "MACRO_DEFINITION", current)
            macro = node.macroname
            raw_args = argument_nodes(node)
            # Keep positional optional arguments; a starred declaration and an
            # omitted arity/default must not shift the macro name or body.
            is_operator = macro == "DeclareMathOperator"
            symbol_arg = raw_args[1] if len(raw_args) > 1 else None
            symbol_text = argument_text(symbol_arg)
            symbol_match = re.fullmatch(r"\\([A-Za-z]+|[^A-Za-z\s])", symbol_text or "")
            symbol = symbol_match[1] if symbol_match else None
            arity_text = (
                argument_text(raw_args[2]) if not is_operator and len(raw_args) > 2 else None
            )
            default = argument_text(raw_args[3]) if not is_operator and len(raw_args) > 3 else None
            body_index = 2 if is_operator else 4
            body = raw_args[body_index] if len(raw_args) > body_index else None
            arity = (
                0
                if arity_text is None
                else int(arity_text.strip())
                if re.fullmatch(r"[0-9]", arity_text.strip())
                else None
            )
            bindings = frames[-1]["bindings"]
            previous = bindings.get(symbol)
            builtin = symbol is not None and known_macro(symbol)
            existing = previous is not None or builtin
            structural = symbol in (
                {
                    "begin",
                    "end",
                    "section",
                    "subsection",
                    "subsubsection",
                    "input",
                    "include",
                    "newtheorem",
                    "label",
                    "ref",
                    "eqref",
                    "cref",
                    "Cref",
                    "cite",
                    "citep",
                    "citet",
                    "autocite",
                    "parencite",
                    "bibliography",
                    "addbibresource",
                    "bibitem",
                }
                | theorem_envs
                | {"end" + env for env in theorem_envs}
                | {
                    "proof",
                    "endproof",
                    "document",
                    "enddocument",
                    "equation",
                    "endequation",
                    "align",
                    "endalign",
                    "gather",
                    "endgather",
                }
            )
            valid = (
                symbol is not None
                and body is not None
                and arity is not None
                and 0 <= arity <= 9
                and (default is None or arity > 0)
            )
            if macro in {"newcommand", "DeclareMathOperator"} and existing:
                valid = False
            if macro == "renewcommand" and not existing:
                valid = False
            status = "INVALID"
            if valid:
                status = (
                    "PRESERVED"
                    if macro == "providecommand" and existing
                    else ("REDEFINED" if existing else "DEFINED")
                )
            metadata = {
                "command": macro,
                "symbol": symbol,
                "parameter_count": arity,
                "optional_default": default,
                "replacement": argument_text(body),
                "replacement_tokens": replacement_tokens(body) if body is not None else [],
                "binding_status": status,
                "previous_definition": previous,
                "resolution": frames[-1]["record"]["resolution"] if valid else "UNRESOLVED",
            }
            if structural:
                metadata.update(binding_status="UNSUPPORTED", resolution="UNRESOLVED")
            el["declaration"] = metadata
            declarations[el["id"]] = el
            if structural:
                poison("UNSUPPORTED_STRUCTURAL_MACRO_DECLARATION", el["id"], symbol or "")
            elif not valid:
                poison("INVALID_MACRO_DECLARATION", el["id"], macro + ": " + (symbol_text or ""))
            elif status != "PRESERVED":
                bindings[symbol] = el["id"]
            finding("MACRO_EXPANSION_NOT_PERFORMED", el["id"], macro)

        def macro_resolution(symbol: str) -> str | None:
            bindings = frames[-1]["bindings"]
            visiting: set[str] = set()
            checked: set[str] = set()

            def visit(token: str, depth: int) -> str | None:
                if token in visiting:
                    return "MACRO_CYCLE"
                if depth > 32 or len(checked) > 256:
                    return "MACRO_DEPENDENCY_LIMIT"
                if token in dynamic_commands | declaration_commands | {
                    "input",
                    "include",
                    "usepackage",
                    "RequirePackage",
                }:
                    return "DYNAMIC_MACRO_REPLACEMENT"
                if token not in bindings:
                    return None if known_macro(token) else "UNRESOLVED_MACRO_REPLACEMENT"
                if token in checked:
                    return None
                visiting.add(token)
                declaration = declarations[bindings[token]]["declaration"]
                if declaration["resolution"] != "RESOLVED":
                    return "UNRESOLVED_MACRO_DECLARATION"
                for dependency in declaration["replacement_tokens"]:
                    reason = visit(dependency, depth + 1)
                    if reason:
                        return reason
                visiting.remove(token)
                checked.add(token)
                return None

            return visit(symbol, 0)

        def occurrence(node: Any, current: str, owner: dict[str, Any] | None) -> None:
            macro = node.macroname
            binding = frames[-1]["bindings"].get(macro)
            tainted = frames[-1]["record"]["resolution"] != "RESOLVED"
            if binding is None and not tainted and known_macro(macro):
                return

            class Token:
                pos = node.pos
                len = 1 + len(macro)

            el = emit(Token(), "SYMBOL_OCCURRENCE", current)
            el["symbol"] = macro
            if owner:
                el["owner"] = owner["id"]
            reason = (
                "UNRESOLVED_LEXICAL_SCOPE"
                if tainted
                else "UNDECLARED_MACRO"
                if binding is None
                else macro_resolution(macro)
            )
            el["binding_status"] = "UNRESOLVED" if reason else "RESOLVED"
            el["binding_reason"] = reason
            if reason:
                finding(reason, el["id"], macro)
                if reason in {"DYNAMIC_MACRO_REPLACEMENT", "UNRESOLVED_MACRO_REPLACEMENT"}:
                    # We do not execute replacements. A body can introduce a
                    # global assignment, directly or through an unknown macro;
                    # even an enclosing group cannot restore certainty here.
                    poison(reason, el["id"], macro, global_effect=True)
            else:
                el["definition"] = binding
                if owner:
                    dependencies = owner.setdefault("context_dependencies", [])
                    if binding not in dependencies:
                        dependencies.append(binding)
            if binding is not None and declarations[binding]["declaration"]["parameter_count"]:
                poison(
                    "UNEXPANDED_MACRO_ARGUMENTS",
                    el["id"],
                    "Argument substitution can change lexical grouping; no expansion was performed",
                    global_effect=True,
                )

        def walk(
            items: list[Any],
            current: str,
            owner: dict[str, Any] | None = None,
            depth: int = 0,
            reference_purpose: str | None = None,
        ) -> str:
            if depth > 64:
                raise ValueError("RESOURCE_LIMIT: TeX syntax nesting")
            previous: dict[str, Any] | None = None
            for node_index, node in enumerate(items):
                typ = type(node).__name__
                if typ == "LatexCommentNode":
                    continue
                if typ == "LatexCharsNode":
                    if node.chars.strip():
                        if owner is None:
                            emit(node, "PROSE", current)
                            previous = None
                    continue
                if typ == "LatexEnvironmentNode":
                    env = node.environmentname
                    if env == "document":
                        push_frame(node, "ENVIRONMENT", env)
                        current = walk(node.nodelist, current, depth=depth + 1)
                        frames.pop()
                        continue
                    kind = (
                        "ASSERTION"
                        if env in theorem_envs
                        else "PROOF"
                        if env == "proof"
                        else "EQUATION"
                        if env in {"equation", "equation*", "align", "align*", "gather"}
                        else "BIBLIOGRAPHY"
                        if env == "thebibliography"
                        else "UNSUPPORTED_ENVIRONMENT"
                    )
                    el = emit(node, kind, current)
                    el["environment"] = env
                    if kind == "ASSERTION":
                        el["role"] = environment_roles.get(env, "UNRESOLVED")
                        if env in environment_declarations:
                            el["environment_declaration"] = environment_declarations[env]
                        if el["role"] == "UNRESOLVED":
                            finding("UNRESOLVED_ENVIRONMENT_ROLE", el["id"], env)
                    if kind == "PROOF":
                        header = re.match(r"\\begin\{proof\}(?:\[([^\]]*)\])?", el["text"])
                        proof_title = header[1] if header else None
                        el["proof_association"] = {
                            "status": "UNRESOLVED",
                            "method": "NONE",
                            "candidate_targets": [],
                            "reference_keys": [],
                            "external_keys": [],
                        }
                        if proof_title:
                            el["proof_association"]["reference_keys"] = [
                                key.strip()
                                for match in re.finditer(
                                    r"\\(?:ref|eqref|cref|Cref)\{([^{}]+)\}", proof_title
                                )
                                for key in match[1].split(",")
                            ]
                            el["proof_association"]["external_keys"] = [
                                key.strip()
                                for match in re.finditer(
                                    r"\\cite(?:p|t)?(?:\[[^\]]*\]){0,2}\{([^{}]+)\}", proof_title
                                )
                                for key in match[1].split(",")
                            ]
                        if previous and previous["kind"] == "ASSERTION" and not proof_title:
                            el["proof_for"] = previous["id"]
                            el["proof_association"].update(
                                status="RESOLVED",
                                method="ADJACENT",
                                candidate_targets=[previous["id"]],
                            )
                        lower = el["text"].lower()
                        if "omitted" in lower or "sketch" in lower:
                            el["quality"] = "OMITTED_OR_SKETCH"
                    if kind == "UNSUPPORTED_ENVIRONMENT":
                        finding("UNSUPPORTED_ENVIRONMENT", el["id"], env)
                    local = current + "/" + el["id"][:16]
                    scopes.append({"id": local, "parent": current, "element": el["id"]})
                    push_frame(node, "ENVIRONMENT", env)
                    saved_sections = list(section_stack)
                    for argument in argument_nodes(node):
                        if argument is not None:
                            walk(
                                [argument],
                                local,
                                el,
                                depth + 1,
                                reference_purpose="PROOF_ASSOCIATION"
                                if kind == "PROOF"
                                else reference_purpose,
                            )
                    walk(node.nodelist, local, el, depth + 1)
                    section_stack[:] = saved_sections
                    frames.pop()
                    previous = el
                elif typ == "LatexMacroNode":
                    macro = node.macroname
                    args = arguments(node, text)
                    if macro in {"input", "include"}:
                        if len(args) != 1:
                            poison(
                                "UNSUPPORTED_INCLUDE",
                                name,
                                "Unresolved include argument",
                                global_effect=True,
                            )
                            continue
                        target = args[0] + ("" if args[0].endswith(".tex") else ".tex")
                        parent = str(Path(name).parent.as_posix())
                        target = target if parent == "." else parent + "/" + target
                        relative_path(target)
                        included.append(target)
                        current = parse_file(target, active + (name,), current)
                    elif macro == "newtheorem" and args:
                        theorem_envs.add(args[0])
                        declaration = emit(node, "ENVIRONMENT_DEFINITION", current)
                        environment_declarations[args[0]] = declaration["id"]
                        # A declared display name does not authorize a mathematical role.
                        environment_roles.setdefault(args[0], "UNRESOLVED")
                    elif macro in declaration_commands:
                        declare(node, current)
                    elif macro in dynamic_commands:
                        el = emit(node, "MACRO_DEFINITION", current)
                        el["declaration"] = {
                            "command": macro,
                            "symbol": None,
                            "parameter_count": None,
                            "optional_default": None,
                            "replacement": None,
                            "replacement_tokens": [],
                            "binding_status": "UNSUPPORTED",
                            "previous_definition": None,
                            "resolution": "UNRESOLVED",
                        }
                        declarations[el["id"]] = el
                        poison(
                            "UNSUPPORTED_DYNAMIC_DECLARATION",
                            el["id"],
                            macro,
                            global_effect=macro
                            in {"global", "globaldefs", "gdef", "xdef", "aftergroup"},
                        )
                    elif macro in {"section", "subsection", "subsubsection"}:
                        el = emit(node, "SECTION", current)
                        level = {"section": 1, "subsection": 2, "subsubsection": 3}[macro]
                        while section_stack and section_stack[-1][0] >= level:
                            section_stack.pop()
                        parent_scope = section_stack[-1][1] if section_stack else "global"
                        current = parent_scope + "/" + el["id"][:16]
                        scopes.append({"id": current, "parent": parent_scope, "element": el["id"]})
                        section_stack.append((level, current))
                        for argument in argument_nodes(node):
                            if argument is not None:
                                walk([argument], current, el, depth + 1)
                        previous = None
                    elif macro == "label" and args:
                        el = owner or emit(node, "LABEL", current)
                        el["labels"].append(args[-1])
                        labels.setdefault(args[-1], []).append(el["id"])
                    elif (
                        macro
                        in {
                            "ref",
                            "eqref",
                            "cref",
                            "Cref",
                            "cite",
                            "citep",
                            "citet",
                            "autocite",
                            "parencite",
                        }
                        and args
                    ):
                        citation = macro in {"cite", "citep", "citet", "autocite", "parencite"}
                        el = emit(node, "CITATION" if citation else "REFERENCE", current)
                        for key in args[-1].split(","):
                            if not key.strip():
                                finding("EMPTY_REFERENCE_KEY", el["id"])
                                continue
                            ref = {
                                "element": el["id"],
                                "owner": owner["id"] if owner else None,
                                "key": key.strip(),
                                "kind": el["kind"],
                                "targets": [],
                                "purpose": reference_purpose
                                or ("BIBLIOGRAPHIC_CITATION" if citation else "SOURCE_REFERENCE"),
                            }
                            references.append(ref)
                            if owner:
                                owner["citations" if citation else "references"].append(key.strip())
                    elif macro in {"bibliography", "addbibresource"} and args:
                        for target in args[-1].split(","):
                            target = target.strip()
                            target += "" if target.endswith(".bib") else ".bib"
                            parent = str(Path(name).parent.as_posix())
                            target = target if parent == "." else parent + "/" + target
                            relative_path(target)
                            bibliography_requests.append(
                                (target, current, frames[-1]["record"]["id"])
                            )
                    elif macro == "bibitem" and args:
                        last = next(
                            (
                                later.pos
                                for later in items[node_index + 1 :]
                                if type(later).__name__ == "LatexMacroNode"
                                and later.macroname == "bibitem"
                            ),
                            items[-1].pos + items[-1].len,
                        )

                        class BibItem:
                            pos = node.pos
                            len = last - node.pos

                        el = emit(BibItem(), "BIBLIOGRAPHIC_REFERENCE", current)
                        el["key"] = args[-1]
                    elif macro in {
                        "write",
                        "write18",
                        "openout",
                        "read",
                        "usepackage",
                        "RequirePackage",
                    }:
                        el = emit(node, "UNSUPPORTED_MACRO", current)
                        poison("UNEXECUTED_TEX_CONSTRUCT", el["id"], macro)
                    else:
                        occurrence(node, current, owner)
                        if macro not in frames[-1]["bindings"] and not known_macro(macro):
                            el = emit(node, "UNSUPPORTED_MACRO", current)
                            finding("UNSUPPORTED_MACRO", el["id"], macro)
                        # Builtin formatting wrappers can contain real macro uses
                        # and declarations. Their parsed argument groups retain
                        # lexical boundaries; declaration bodies above are inert.
                        for argument in argument_nodes(node):
                            if argument is not None and macro not in {
                                "documentclass",
                                "bibliography",
                                "bibliographystyle",
                            }:
                                walk(
                                    [argument],
                                    current,
                                    owner,
                                    depth + 1,
                                    reference_purpose=reference_purpose,
                                )
                elif typ == "LatexMathNode":
                    el = emit(node, "MATH_EXPRESSION", current)
                    if owner:
                        el["owner"] = owner["id"]
                    push_frame(node, "GROUP")
                    walk(node.nodelist, current, el, depth + 1, reference_purpose=reference_purpose)
                    frames.pop()
                elif typ == "LatexGroupNode":
                    push_frame(node, "GROUP")
                    saved_sections = list(section_stack)
                    walk(
                        node.nodelist,
                        current,
                        owner,
                        depth + 1,
                        reference_purpose=reference_purpose,
                    )
                    section_stack[:] = saved_sections
                    frames.pop()
            return current

        current_scope = walk(nodes, scope)
        if not nodes:
            # Even parser failure preserves the source for honest partial analysis.
            class Whole:
                pos = 0
                len = len(text)

            emit(Whole(), "UNPARSED_SOURCE", scope)
        return current_scope

    parse_file(manifest.entrypoint, (), "global")
    from .source_semantics import bibliography_elements, enrich_source_semantics

    loaded_bibliography: set[str] = set()
    for target, scope, lexical_scope in bibliography_requests:
        if target in loaded_bibliography:
            continue
        loaded_bibliography.add(target)
        if target not in files:
            finding("MISSING_BIBLIOGRAPHY", target)
            continue
        bib_elements, bib_findings = bibliography_elements(
            manifest.revision, target, files[target], scope, lexical_scope
        )
        if len(elements) + len(bib_elements) > MAX_ELEMENTS:
            raise ValueError("RESOURCE_LIMIT: bibliography entries")
        elements.extend(bib_elements)
        findings.extend(bib_findings)
    for key, targets in labels.items():
        if len(targets) != 1:
            finding("AMBIGUOUS_LABEL", key)
    bibkeys: dict[str, list[str]] = {}
    for el in elements:
        if el["kind"] == "BIBLIOGRAPHIC_REFERENCE":
            bibkeys.setdefault(el["key"], []).append(el["id"])
    for ref in references:
        if ref["kind"] == "REFERENCE":
            ref["targets"] = labels.get(ref["key"], [])
            if len(ref["targets"]) != 1:
                finding("MISSING_OR_AMBIGUOUS_REFERENCE", ref["element"], ref["key"])
        else:
            ref["targets"] = bibkeys.get(ref["key"], [])
            if len(ref["targets"]) != 1:
                finding(
                    "AMBIGUOUS_CITATION" if ref["targets"] else "UNRESOLVED_CITATION",
                    ref["element"],
                    ref["key"],
                )
    for el in elements:
        if el["kind"] != "PROOF":
            continue
        association = el["proof_association"]
        if association["reference_keys"]:
            targets = [
                target for key in association["reference_keys"] for target in labels.get(key, [])
            ]
            eligible = {e["id"] for e in elements if e["kind"] == "ASSERTION"}
            association["candidate_targets"] = list(
                dict.fromkeys(target for target in targets if target in eligible)
            )
            unique = (
                len(association["reference_keys"]) == 1
                and len(targets) == 1
                and targets[0] in eligible
            )
            association.update(status="RESOLVED" if unique else "AMBIGUOUS", method="EXPLICIT")
            el["proof_for"] = targets[0] if unique else None
        elif association["external_keys"]:
            association.update(status="EXTERNAL", method="EXTERNAL")
        if association["status"] in {"UNRESOLVED", "AMBIGUOUS"}:
            finding("AMBIGUOUS_PROOF_ASSOCIATION", el["id"])
    for el in elements:
        validate_locator(el["locator"], files, el["text"])
    ir = {
        "$schema": "urn:proofmap:document-ir:1",
        "schema_version": "1.0",
        "revision": manifest.revision,
        "parser": {"name": "pylatexenc", "version": version("pylatexenc")},
        "elements": elements,
        "scopes": scopes,
        "lexical_scopes": lexical_scopes,
        "references": references,
        "findings": findings,
        "included": included,
        "fidelity": "SYNTAX_ONLY",
        "status": "PARTIAL" if findings else "PASS",
    }
    enrich_source_semantics(ir)
    return ir


def parse_pdf(manifest: InputManifest, files: dict[str, bytes]) -> dict[str, Any]:
    raw = files[manifest.entrypoint]
    pages = _pdf_pages(raw)
    elements: list[dict[str, Any]] = []
    findings = []
    for index, text in enumerate(pages, 1):
        loc = SourceLocator(
            manifest.entrypoint,
            artifact_digest(raw),
            "pdf",
            page=index,
            excerpt_sha256=artifact_digest(text.encode("utf-8")),
            offsets="reconstructed-text-no-source-offsets",
            text_start=0,
            text_end=len(text),
            parser_version=version("pypdf"),
        )
        eid = digest("source-element.v1", {"revision": manifest.revision, "locator": asdict(loc)})
        elements.append(
            {
                "id": eid,
                "revision": manifest.revision,
                "kind": "PDF_PAGE_TEXT",
                "text": text,
                "scope": "page:" + str(index),
                "locator": asdict(loc),
                "labels": [],
                "references": [],
                "citations": [],
                "proof_for": None,
                "quality": "RECONSTRUCTED",
                "math_ast": None,
            }
        )
        if not text.strip():
            findings.append(
                {
                    "code": "NEEDS_OCR",
                    "source": eid,
                    "classification": "REVIEW_REQUIRED",
                    "blocking_eligible": False,
                }
            )
    return {
        "$schema": "urn:proofmap:document-ir:1",
        "schema_version": "1.0",
        "revision": manifest.revision,
        "parser": {
            "name": "pypdf",
            "version": version("pypdf"),
            "ocr": False,
            "boxes": "UNAVAILABLE",
            "options": {"extraction_mode": "plain", "strict": True},
        },
        "elements": elements,
        "scopes": [],
        "references": [],
        "findings": findings,
        "fidelity": "RECONSTRUCTED_TEXT",
        "status": "PARTIAL",
    }


def _parse_in_worker(
    manifest: InputManifest, files: dict[str, bytes], parser: str
) -> dict[str, Any]:
    if manifest.entrypoint.endswith(".tex") and parser in {"auto", "pylatexenc"}:
        return parse_tex(manifest, files)
    if manifest.entrypoint.endswith(".pdf") and parser in {"auto", "pypdf"}:
        return parse_pdf(manifest, files)
    raise ValueError("UNSUPPORTED_FORMAT_OR_PARSER")


def parse(
    manifest: InputManifest,
    files: dict[str, bytes],
    parser: str = "auto",
    *,
    timeout_seconds: float = 45,
) -> dict[str, Any]:
    """Run risky third-party parsing in a killable process with a wall deadline.

    Source bytes, parser choice and acquisition limits are controller input. A
    timeout retains the exact input revision and an explicit partial outcome.
    """
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 0 < timeout_seconds <= 60
    ):
        raise ValueError("PARSER_TIMEOUT_LIMIT")
    request = canonical_bytes(
        {
            "manifest": asdict(manifest),
            "parser": parser,
            "files": {name: base64.b64encode(raw).decode("ascii") for name, raw in files.items()},
        }
    )
    try:
        completed = subprocess.run(
            [sys.executable, "-m", "proofmap.paper_parse_worker"],
            input=request,
            capture_output=True,
            timeout=timeout_seconds,
            check=False,
            cwd=Path(__file__).resolve().parent.parent,
        )
    except subprocess.TimeoutExpired:
        return {
            "$schema": "urn:proofmap:document-ir:1",
            "schema_version": "1.0",
            "revision": manifest.revision,
            "parser": {"name": parser, "execution": "TIMEOUT", "timeout_seconds": timeout_seconds},
            "elements": [],
            "scopes": [],
            "references": [],
            "findings": [
                {
                    "code": "PARSER_TIMEOUT",
                    "source": manifest.revision,
                    "classification": "RESOURCE_LIMIT",
                    "blocking_eligible": False,
                }
            ],
            "fidelity": "UNAVAILABLE",
            "status": "PARTIAL",
        }
    if len(completed.stdout) > MAX_PARSE_OUTPUT:
        raise ValueError("RESOURCE_LIMIT: parser output")
    if completed.returncode != 0:
        raise ValueError("PARSER_WORKER_FAILED")
    response = strict_loads(completed.stdout)
    if response.get("error"):
        raise ValueError(response["error"])
    ir = response["ir"]
    if not isinstance(ir, dict):
        raise ValueError("PARSER_INVALID_OUTPUT")
    ir["parser"]["execution"] = "COMPLETED"
    ir["parser"]["deadline_seconds"] = timeout_seconds
    return ir
