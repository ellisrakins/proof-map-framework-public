"""Reject rehashed malformed lexical records without promoting extracted meanings."""

from copy import deepcopy

import pytest

from proofmap.integrity import canonical_bytes, digest, write_json
from proofmap.kernel import KernelMap
from proofmap.paper import load_bundle
from proofmap.paper_sources import acquire, parse_tex
from proofmap.paper_store import PaperStore, validate_bundle
from proofmap.schema import validate


def rehash(bundle):
    bundle["run_manifest"]["bundle_digests"] = {
        name: digest("paper-bundle-component.v1", value)
        for name, value in bundle.items()
        if name != "run_manifest"
    }


def bundle_for_source(tmp_path, text):
    source = tmp_path / "source.tex"
    source.write_text(text, encoding="utf-8")
    manifest, files = acquire(source)
    ir = parse_tex(manifest, files)
    bundle = {
        "input_manifest": manifest.to_dict(),
        "document_ir": ir,
        "assertions": [],
        "symbols": [],
        "argument_map": KernelMap().to_dict(),
        "extraction_events": [],
        "findings": ir["findings"],
        "assessment": {},
        "run_manifest": {
            "schema_version": "1.0",
            "revision": manifest.revision,
            "run_id": "lexical-structure-test",
            "analysis_digest": "a" * 64,
            "policy_digest": "b" * 64,
        },
    }
    rehash(bundle)
    validate_bundle(bundle, files)
    return bundle, files


@pytest.fixture
def scoped_bundle(tmp_path):
    return bundle_for_source(
        tmp_path,
        r"\newcommand{\foo}{1}\foo{\renewcommand{\foo}{2}\foo}"
        r"$\foo+\missing$\begin{theorem}A source assertion.\end{theorem}",
    )


def declarations(ir):
    return [element for element in ir["elements"] if "declaration" in element]


def uses(ir):
    return [element for element in ir["elements"] if element["kind"] == "SYMBOL_OCCURRENCE"]


def save_bundle(path, bundle):
    path.mkdir()
    for name, value in bundle.items():
        write_json(path / (name + ".json"), value)


def test_current_lexical_ir_roundtrips_store_and_bundle(tmp_path, scoped_bundle, monkeypatch):
    bundle, files = scoped_bundle
    # Boundary checks consume anchored records; they never rerun a TeX interpreter/parser.
    monkeypatch.setattr("proofmap.paper_sources.parse_tex", lambda *a, **k: pytest.fail("reparse"))
    assert not validate("document-ir", bundle["document_ir"])
    validate_bundle(bundle)
    path = tmp_path / "bundle"
    save_bundle(path, bundle)
    assert load_bundle(path)["document_ir"] == bundle["document_ir"]
    store = PaperStore(tmp_path / "store")
    try:
        store.ingest("syntactic fixture", bundle, files)
        assert canonical_bytes(
            store.inspect(bundle["run_manifest"]["run_id"])["bundle"]
        ) == canonical_bytes(bundle)
    finally:
        store.close()
    assert not bundle["argument_map"]["evidence"]


def test_historical_ir_without_lexical_fields_remains_readable(scoped_bundle):
    bundle, files = scoped_bundle
    ir = bundle["document_ir"]
    ir.pop("lexical_scopes")
    for element in ir["elements"]:
        for field in ("lexical_scope", "declaration", "binding_status", "binding_reason"):
            element.pop(field, None)
    rehash(bundle)
    assert not validate("document-ir", ir)
    validate_bundle(bundle, files)


@pytest.mark.parametrize(
    "source",
    [
        r"\newcommand{\foo}{1}\providecommand{\foo}{2}\foo",
        r"\renewcommand{\sin}{sine}\sin",
        r"\newcommand*{\foo}[2][x]{#1+#2}\foo",
        r"\DeclareMathOperator*{\foo}{lim}\foo",
        r"\newcommand{\foo}[10]{#1}\foo",
        r"\newcommand{\foo}{1}\foo{\global\def\foo{2}}\foo",
        r"\newcommand{\foo}{1}\foo{\let\foo\bar\foo}\foo",
        r"\newcommand{\foo}{\foo}\foo",
        r"$\newcommand{\foo}{1}\foo$",
    ],
)
def test_unresolved_and_temporal_syntax_snapshots_remain_valid(tmp_path, source):
    # Final scope taint must not invalidate a resolved occurrence recorded earlier.
    bundle, files = bundle_for_source(tmp_path, source)
    validate_bundle(bundle, files)
    validate_bundle(bundle)


@pytest.mark.parametrize(
    "mutation",
    [
        "no_table",
        "duplicate_scope",
        "missing_root",
        "missing_parent",
        "self_parent",
        "element_missing_scope",
        "element_unknown_scope",
        "unknown_owner",
        "wrong_scope_status",
        "declaration_previous_missing",
        "declaration_previous_self",
        "declaration_symbol",
        "declaration_resolved_invalid",
        "declaration_missing",
        "resolved_use_missing_definition",
        "resolved_use_wrong_kind",
        "resolved_use_reason",
        "unresolved_use_definition",
        "unresolved_use_no_reason",
        "missing_binding_reason",
        "context_missing",
        "context_wrong_kind",
        "context_duplicate",
        "metadata_wrong_kind",
    ],
)
def test_rehashed_invalid_links_and_statuses_fail(scoped_bundle, mutation):
    bundle, files = scoped_bundle
    ir = bundle["document_ir"]
    first, second = declarations(ir)
    use = uses(ir)[0]
    unresolved = next(row for row in uses(ir) if row["binding_status"] == "UNRESOLVED")
    nested = ir["lexical_scopes"][1]
    math = next(row for row in ir["elements"] if row["kind"] == "MATH_EXPRESSION")
    if mutation == "no_table":
        ir.pop("lexical_scopes")
    elif mutation == "duplicate_scope":
        ir["lexical_scopes"].append(deepcopy(nested))
    elif mutation == "missing_root":
        ir["lexical_scopes"].pop(0)
    elif mutation == "missing_parent":
        nested["parent"] = "absent"
    elif mutation == "self_parent":
        nested["parent"] = nested["id"]
    elif mutation == "element_missing_scope":
        use.pop("lexical_scope")
    elif mutation == "element_unknown_scope":
        use["lexical_scope"] = "absent"
    elif mutation == "unknown_owner":
        use["owner"] = "absent"
    elif mutation == "wrong_scope_status":
        nested["resolution"] = "UNRESOLVED"
        nested["reasons"] = []
    elif mutation == "declaration_previous_missing":
        second["declaration"]["previous_definition"] = "absent"
    elif mutation == "declaration_previous_self":
        second["declaration"]["previous_definition"] = second["id"]
    elif mutation == "declaration_symbol":
        second["declaration"]["symbol"] = "another"
    elif mutation == "declaration_resolved_invalid":
        first["declaration"]["binding_status"] = "INVALID"
    elif mutation == "declaration_missing":
        first.pop("declaration")
    elif mutation == "resolved_use_missing_definition":
        use.pop("definition")
    elif mutation == "resolved_use_wrong_kind":
        use["definition"] = use["id"]
    elif mutation == "resolved_use_reason":
        use["binding_reason"] = "Unresolved yet labeled resolved"
    elif mutation == "unresolved_use_definition":
        unresolved["definition"] = first["id"]
    elif mutation == "unresolved_use_no_reason":
        unresolved["binding_reason"] = None
    elif mutation == "missing_binding_reason":
        use.pop("binding_reason")
    elif mutation == "context_missing":
        math["context_dependencies"] = ["absent"]
    elif mutation == "context_wrong_kind":
        math["context_dependencies"] = [use["id"]]
    elif mutation == "context_duplicate":
        math["context_dependencies"] = [first["id"], first["id"]]
    else:
        first["binding_status"] = "RESOLVED"
    rehash(bundle)
    with pytest.raises(ValueError):
        validate_bundle(bundle, files)


@pytest.mark.parametrize("mutation", ["end", "reversed", "artifact", "digest", "excerpt", "bool"])
def test_rehashed_scope_anchors_are_checked(scoped_bundle, mutation):
    bundle, files = scoped_bundle
    ir = bundle["document_ir"]
    scope = ir["lexical_scopes"][1]
    old_id, loc = scope["id"], scope["locator"]
    if mutation == "end":
        loc["end"] = 1_000_000
    elif mutation == "reversed":
        loc["end"] = loc["start"] - 1
    elif mutation == "artifact":
        loc["artifact"] = "missing.tex"
    elif mutation == "digest":
        loc["artifact_sha256"] = "f" * 64
    elif mutation == "excerpt":
        loc["excerpt_sha256"] = "f" * 64
    else:
        loc["start"] = True
    scope["id"] = digest(
        "tex-lexical-scope.v1",
        {
            "revision": ir["revision"],
            "locator": loc,
            "kind": scope["kind"],
        },
    )
    for element in ir["elements"]:
        if element["lexical_scope"] == old_id:
            element["lexical_scope"] = scope["id"]
    rehash(bundle)
    with pytest.raises(ValueError):
        validate_bundle(bundle, files)


def test_bad_scope_reference_fails_load_and_store_after_rehash(tmp_path, scoped_bundle):
    bundle, files = scoped_bundle
    uses(bundle["document_ir"])[0]["lexical_scope"] = "absent"
    rehash(bundle)
    path = tmp_path / "invalid-bundle"
    save_bundle(path, bundle)
    with pytest.raises(ValueError, match="LEXICAL_SCOPE"):
        load_bundle(path)
    store = PaperStore(tmp_path / "invalid-store")
    try:
        with pytest.raises(ValueError, match="LEXICAL_SCOPE"):
            store.ingest("invalid", bundle, files)
        assert store.list() == []
    finally:
        store.close()


@pytest.mark.parametrize(
    "mutation", ["future_use", "closed_scope_use", "future_previous", "cyclic_previous"]
)
def test_rehashed_binding_cannot_reference_future_or_closed_scope(scoped_bundle, mutation):
    bundle, files = scoped_bundle
    ir = bundle["document_ir"]
    first, second = declarations(ir)
    if mutation == "future_use":
        uses(ir)[0]["definition"] = second["id"]
        second["lexical_scope"] = "tex:global"  # Same ancestor; ordering alone must reject.
    elif mutation == "closed_scope_use":
        later = next(
            row
            for row in uses(ir)
            if row["symbol"] == "foo"
            and row["locator"]["start"] > second["locator"]["end"]
            and row["lexical_scope"] != second["lexical_scope"]
        )
        later["definition"] = second["id"]
    elif mutation == "future_previous":
        first["declaration"]["previous_definition"] = second["id"]
        second["declaration"]["previous_definition"] = None
        second["lexical_scope"] = "tex:global"
    else:
        first["declaration"]["previous_definition"] = second["id"]
    rehash(bundle)
    with pytest.raises(
        ValueError, match="MACRO_(USE_BINDING|PREVIOUS_DEFINITION|DECLARATION_CYCLE)"
    ):
        validate_bundle(bundle, files)


@pytest.mark.parametrize("mutation", ["superseded_use", "shadowed_use", "superseded_previous"])
def test_rehashed_bindings_cannot_bypass_latest_declaration(tmp_path, mutation):
    source = (
        r"\newcommand{\foo}{1}{\renewcommand{\foo}{2}\foo}"
        if mutation == "shadowed_use"
        else r"\newcommand{\foo}{1}\renewcommand{\foo}{2}\renewcommand{\foo}{3}\foo"
    )
    bundle, files = bundle_for_source(tmp_path, source)
    ir = bundle["document_ir"]
    definitions = declarations(ir)
    if mutation == "superseded_previous":
        definitions[-1]["declaration"]["previous_definition"] = definitions[0]["id"]
    else:
        uses(ir)[-1]["definition"] = definitions[0]["id"]
    rehash(bundle)
    with pytest.raises(ValueError, match="MACRO_(USE_BINDING|PREVIOUS_DEFINITION)"):
        validate_bundle(bundle, files)


@pytest.mark.parametrize(
    "field,value",
    [
        ("parameter_count", True),
        ("parameter_count", 10),
        ("replacement_tokens", [2]),
        ("resolution", "ACCEPTED"),
        ("binding_status", "VERIFIED"),
    ],
)
def test_declaration_schema_rejects_future_or_wrong_types(scoped_bundle, field, value):
    bundle, _ = scoped_bundle
    ir = bundle["document_ir"]
    declarations(ir)[0]["declaration"][field] = value
    assert validate("document-ir", ir)
