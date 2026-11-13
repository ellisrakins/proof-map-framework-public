"""Scoped structural reuse must re-read exact CAS material and fresh context."""

import shutil
from collections import Counter
from copy import deepcopy
from functools import wraps
from pathlib import Path

import pytest

from proofmap import (
    evidence_adapter,
    extractor,
    formalize,
    kernel,
    paper_sources,
    paper_store,
    trust,
)
from proofmap.integrity import artifact_digest, canonical_bytes, digest
from proofmap.paper import ci
from proofmap.paper_store import PaperStore


@pytest.fixture(scope="module")
def immutable_inspect_source(tmp_path_factory):
    directory = tmp_path_factory.mktemp("inspect-source")
    source = directory / "source"
    source.mkdir()
    (source / "main.tex").write_text(
        r"\documentclass{article}\begin{document}\input{claim}\end{document}",
        encoding="utf-8",
    )
    (source / "claim.tex").write_text(
        r"\begin{theorem}\label{identity}For every $q\in\mathbb{Z}$, "
        r"\[(q+2)^2=q^2+4q+4.\]\end{theorem}"
        r"\begin{proof}Direct calculation.\end{proof}",
        encoding="utf-8",
    )
    bundle, code = ci(source, directory / "out", directory / "store")
    assert code == 0
    assert bundle["formalizations"][0]["status"] == "SUPPORTED"
    store = PaperStore(directory / "store")
    try:
        run = bundle["run_manifest"]["run_id"]
        original = store.inspect(run)
        assert len(original["artifacts"]) == 2
        variant = deepcopy(bundle)
        variant["run_manifest"]["run_id"] += "-second"
        store.ingest("main.tex", variant, {})
        runs = (run, variant["run_manifest"]["run_id"])
    finally:
        store.close()
    root = directory / "store"
    before = {
        path.relative_to(root): artifact_digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    yield root, runs, original
    assert {
        path.relative_to(root): artifact_digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    } == before


@pytest.fixture
def inspect_store(tmp_path, immutable_inspect_source):
    root, runs, original = immutable_inspect_source
    copied = tmp_path / "store"
    shutil.copytree(root, copied)
    store = PaperStore(copied)
    try:
        yield store, runs, deepcopy(original)
    finally:
        store.close()


def structural_calls(monkeypatch):
    original = paper_store.validate_bundle
    calls = []

    @wraps(original)
    def counted(bundle, artifacts=None):
        calls.append(
            bundle["run_manifest"]["run_id"] if isinstance(bundle, dict) else "INVALID_MATERIAL"
        )
        return original(bundle, artifacts)

    monkeypatch.setattr(paper_store, "validate_bundle", counted)
    return calls


def body_digest(store, run):
    return store.db.execute("SELECT bundle FROM runs WHERE id=?", (run,)).fetchone()[0]


def rehash(bundle):
    bundle["run_manifest"]["bundle_digests"] = {
        name: digest("paper-bundle-component.v1", value)
        for name, value in bundle.items()
        if name != "run_manifest"
    }


def publish_replacement(store, run, value):
    sha = store.put(canonical_bytes(value))
    with store.db:
        store.db.execute("UPDATE runs SET bundle=? WHERE id=?", (sha, run))
    return sha


def test_hit_rereads_sql_and_every_object_with_independent_return_values(
    inspect_store, monkeypatch
):
    store, (run, _), expected = inspect_store
    calls = structural_calls(monkeypatch)
    reads, queries = [], []
    get = store.get

    def observed(sha):
        reads.append(sha)
        return get(sha)

    monkeypatch.setattr(store, "get", observed)
    store.db.set_trace_callback(queries.append)
    try:
        with paper_sources.source_validation_scope():
            first = store.inspect(run)
            first["bundle"]["assertions"][0]["statement"] = "caller mutation"
            first["artifacts"].clear()
            second = store.inspect(run)
            assert second == expected
            assert second is not first and second["bundle"] is not first["bundle"]
            assert calls == [run]
        wanted = Counter([body_digest(store, run), *expected["artifacts"].values()])
        assert Counter(reads) == Counter({sha: count * 2 for sha, count in wanted.items()})
        assert sum(query.startswith("SELECT bundle FROM runs WHERE id=") for query in queries) == 3
    finally:
        store.db.set_trace_callback(None)


@pytest.mark.parametrize("artifact", ["bundle", "main.tex", "claim.tex"])
def test_hit_still_rejects_changed_cas_bytes(inspect_store, monkeypatch, artifact):
    store, (run, _), expected = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        assert store.inspect(run) == expected
        sha = body_digest(store, run) if artifact == "bundle" else expected["artifacts"][artifact]
        path = store.root / "objects" / sha[:2] / sha[2:]
        original = path.read_bytes()
        path.write_bytes(original + b"\ncorrupt after successful inspection")
        with pytest.raises(ValueError, match="CORRUPT_CAS_OBJECT"):
            store.inspect(run)
        assert calls == [run]  # Fresh material failed before structural reuse.


@pytest.mark.parametrize("artifact", ["bundle", "claim.tex"])
def test_hit_still_rejects_deleted_cas_object(inspect_store, monkeypatch, artifact):
    store, (run, _), expected = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        store.inspect(run)
        sha = body_digest(store, run) if artifact == "bundle" else expected["artifacts"][artifact]
        (store.root / "objects" / sha[:2] / sha[2:]).unlink()
        with pytest.raises(FileNotFoundError):
            store.inspect(run)
        assert calls == [run]


@pytest.mark.parametrize(
    "mutation", ["negative_duration", "locator", "artifact_map", "bundle_type"]
)
def test_hashed_replacement_is_revalidated_and_failed_results_are_not_retained(
    inspect_store, monkeypatch, mutation
):
    store, (run, _), original = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        store.inspect(run)
        changed = deepcopy(original)
        if mutation == "negative_duration":
            changed["bundle"]["run_manifest"]["duration_seconds"] = -1
            reason = "PAPER_RECORD_SCHEMA"
        elif mutation == "locator":
            changed["bundle"]["document_ir"]["elements"][0]["locator"]["excerpt_sha256"] = "f" * 64
            rehash(changed["bundle"])
            reason = "SOURCE_ELEMENT_ID"
        elif mutation == "artifact_map":
            # Both objects remain correctly hashed; their path association is forged.
            changed["artifacts"]["main.tex"] = original["artifacts"]["claim.tex"]
            reason = "SOURCE_ARTIFACT_MISMATCH"
        else:
            changed["bundle"] = []
            reason = "INVALID_STORED_BUNDLE"
        replaced = publish_replacement(store, run, changed)
        assert artifact_digest(store.get(replaced)) == replaced
        for _ in range(2):
            with pytest.raises(ValueError, match=reason):
                store.inspect(run)
        assert calls == [run] + (["INVALID_MATERIAL"] if mutation == "bundle_type" else [run]) * 2


def test_hit_still_queries_missing_run(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        store.inspect(run)
        with store.db:
            store.db.execute("DELETE FROM runs WHERE id=?", (run,))
        with pytest.raises(ValueError, match="Unknown run"):
            store.inspect(run)
        assert calls == [run]


def test_nested_scope_reuses_only_until_outer_exit(inspect_store, monkeypatch):
    store, (run, _), expected = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope() as outer:
        store.inspect(run)
        with paper_sources.source_validation_scope() as inner:
            assert inner is outer
            assert store.inspect(run) == expected
        store.inspect(run)
        assert calls == [run]
    store.inspect(run)
    store.inspect(run)
    assert calls == [run, run, run]


@pytest.mark.parametrize("error", [ValueError, KeyboardInterrupt])
def test_scope_discards_successes_after_exception_exit(inspect_store, monkeypatch, error):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with pytest.raises(error):
        with paper_sources.source_validation_scope():
            store.inspect(run)
            store.inspect(run)
            assert calls == [run]
            raise error("leave the validation operation")
    with paper_sources.source_validation_scope():
        store.inspect(run)
        store.inspect(run)
    assert calls == [run, run]


def test_bounded_lru_eviction_revalidates_material(inspect_store, monkeypatch):
    store, (first, second), _ = inspect_store
    calls = structural_calls(monkeypatch)
    monkeypatch.setattr(paper_sources, "MAX_VALIDATED_BUNDLES", 1)
    with paper_sources.source_validation_scope() as session:
        for run in (first, first, second, second, first):
            store.inspect(run)
            assert len(session._bundle_validations) <= 1
        assert calls == [first, second, first]


def test_disabling_memo_clears_existing_success_and_revalidates(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope() as session:
        store.inspect(run)
        assert session._bundle_validations
        monkeypatch.setattr(paper_sources, "MAX_VALIDATED_BUNDLES", 0)
        store.inspect(run)
        store.inspect(run)
        assert not session._bundle_validations
        assert calls == [run, run, run]


def test_explicit_reset_requires_fresh_structural_validation(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope() as session:
        store.inspect(run)
        store.inspect(run)
        assert calls == [run]
        session.clear_bundle_validations()
        store.inspect(run)
        store.inspect(run)
        assert calls == [run, run]


@pytest.mark.parametrize(
    "contract", ["source_cap", "policy", "relations", "response_schema", "payload_type", "parser"]
)
def test_effective_contract_changes_force_fresh_structural_validation(
    inspect_store, monkeypatch, contract
):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        store.inspect(run)
        if contract == "source_cap":
            monkeypatch.setattr(paper_sources, "MAX_ELEMENTS", paper_sources.MAX_ELEMENTS + 1)
        elif contract == "policy":
            monkeypatch.setitem(evidence_adapter.POLICY, "id", "changed-structural-policy")
        elif contract == "relations":
            monkeypatch.setitem(kernel.RELATIONS, "CITES", kernel.RELATIONS["DEPENDS_ON"])
        elif contract == "response_schema":
            changed = deepcopy(extractor.RESPONSE_SCHEMA)
            changed["properties"]["classifications"]["maxItems"] -= 1
            monkeypatch.setattr(extractor, "RESPONSE_SCHEMA", changed)
        elif contract == "payload_type":
            monkeypatch.setitem(
                trust.RECORD_PAYLOAD_TYPES, "ReviewDecision", "changed-payload-type"
            )
        else:
            parse = paper_sources.parse

            def changed_parse(*args, **kwargs):
                return parse(*args, **kwargs)

            monkeypatch.setattr(paper_sources, "parse", changed_parse)
        store.inspect(run)
        assert calls == [run, run]


def test_changed_formal_limit_rejects_previously_valid_material(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        store.inspect(run)
        monkeypatch.setattr(formalize, "MAX_NODES", 0)
        with pytest.raises(ValueError, match="INVALID_FORMALIZATION_AST_LIMIT"):
            store.inspect(run)
        assert calls == [run, run]


def test_changed_validator_cannot_reuse_earlier_success(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        store.inspect(run)
        validate = paper_store.validate_bundle

        def rejecting(bundle, artifacts=None):
            validate(bundle, artifacts)
            raise ValueError("CURRENT_VALIDATOR_REJECTION")

        monkeypatch.setattr(paper_store, "validate_bundle", rejecting)
        with pytest.raises(ValueError, match="CURRENT_VALIDATOR_REJECTION"):
            store.inspect(run)
        assert calls == [run, run]


def test_changed_validator_code_cannot_reuse_success_under_same_function_identity(
    inspect_store, monkeypatch
):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    original = paper_store.validate_bundle

    def changed_code(bundle, artifacts=None):
        calls.append(bundle["run_manifest"]["run_id"])
        original(bundle, artifacts)
        raise ValueError("CURRENT_VALIDATOR_CODE_REJECTION")

    validator = paper_store.validate_bundle
    # The spy and replacement both close over calls/original in the same order.
    assert validator.__code__.co_freevars == changed_code.__code__.co_freevars
    with paper_sources.source_validation_scope():
        store.inspect(run)
        monkeypatch.setattr(validator, "__code__", changed_code.__code__)
        with pytest.raises(ValueError, match="CURRENT_VALIDATOR_CODE_REJECTION"):
            store.inspect(run)
        assert calls == [run, run]


def test_changed_structural_class_method_cannot_reuse_earlier_success(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        store.inspect(run)

        def rejecting(self):
            raise ValueError("CURRENT_KERNEL_VALIDATOR_REJECTION")

        monkeypatch.setattr(kernel.KernelMap, "validate", rejecting)
        with pytest.raises(ValueError, match="CURRENT_KERNEL_VALIDATOR_REJECTION"):
            store.inspect(run)
        assert calls == [run, run]


def test_changed_private_validator_compiled_keyword_rejects_prior_success(
    inspect_store, monkeypatch
):
    from jsonschema.exceptions import ValidationError

    from proofmap.schema import _validator

    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    validator = _validator("paper-input")
    original = list(validator._validators)

    def rejecting(current, constraint, instance, schema):
        yield ValidationError("CURRENT_COMPILED_KEYWORD_REJECTION")

    try:
        with paper_sources.source_validation_scope():
            store.inspect(run)
            # Same validator object, public schema and class keyword mapping;
            # the effective compiled instance now performs a stricter check.
            validator._validators[0] = (rejecting, original[0][1], original[0][2])
            with pytest.raises(ValueError, match="INVALID_PAPER_BUNDLE_SCHEMA: paper-input"):
                store.inspect(run)
            assert calls == [run, run]
    finally:
        validator._validators[:] = original


def test_changed_parser_default_invalidates_same_callable_contract(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    parser = paper_sources.parse
    with paper_sources.source_validation_scope():
        store.inspect(run)
        monkeypatch.setitem(parser.__kwdefaults__, "timeout_seconds", 46)
        assert paper_sources.parse is parser
        store.inspect(run)
        assert calls == [run, run]


def test_wrapped_validator_code_change_cannot_reuse_success(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    wrapper = paper_store.validate_bundle
    implementation = wrapper.__wrapped__

    def rejecting(bundle, artifacts=None):
        raise ValueError("CURRENT_WRAPPED_VALIDATOR_REJECTION")

    with paper_sources.source_validation_scope():
        store.inspect(run)
        monkeypatch.setattr(implementation, "__code__", rejecting.__code__)
        assert paper_store.validate_bundle is wrapper
        with pytest.raises(ValueError, match="CURRENT_WRAPPED_VALIDATOR_REJECTION"):
            store.inspect(run)
        assert calls == [run, run]


def test_contract_changed_during_validation_cannot_publish_success_token(
    inspect_store, monkeypatch
):
    store, (run, _), _ = inspect_store
    original = paper_store.validate_bundle
    calls = []

    def changed_after_validation(bundle, artifacts=None):
        calls.append(run)
        original(bundle, artifacts)
        if len(calls) == 1:
            monkeypatch.setattr(paper_sources, "MAX_ELEMENTS", paper_sources.MAX_ELEMENTS + 1)

    monkeypatch.setattr(paper_store, "validate_bundle", changed_after_validation)
    with paper_sources.source_validation_scope() as session:
        store.inspect(run)
        assert not session._bundle_validations
        store.inspect(run)
        store.inspect(run)
        assert calls == [run, run]


@pytest.mark.parametrize("history", ["override", "legacy_summary", "legacy_replay"])
def test_wider_historical_paths_conservatively_keep_full_checks(
    inspect_store, immutable_inspect_source, tmp_path, monkeypatch, history
):
    store, (_, _), original = inspect_store
    bundle = deepcopy(original["bundle"])
    if history == "override":
        from proofmap.paper_overrides import apply_override, override_export

        draft = override_export(bundle, "Local memo boundary test")
        target = next(row for row in draft["targets"] if row["kind"] == "ASSERTION")
        draft["changes"] = [
            {
                "kind": "role",
                "target": target["id"],
                "scope": target["scope"],
                "source_digest": target["source_digest"],
                "value": "LEMMA",
                "note": "An explicit attributed interpretation, without authority.",
            }
        ]
        bundle = apply_override(bundle, draft, store)
        assert bundle["interpretation_overrides"]
    else:
        if history == "legacy_replay":
            from test_semantic_candidates import replay_for

            configuration = {
                "provider": "ollama",
                "endpoint": "http://localhost:11434",
                "model": "RECORDED_TEST_INPUT_ONLY",
                "timeout_seconds": 3,
                "max_output_tokens": 128,
            }
            chunks, findings = extractor.chunk_document(bundle["document_ir"])
            assert len(chunks) == 1 and not findings
            recorded = replay_for(
                chunks[0], configuration, {"classifications": [], "dependencies": []}
            )

            def forbidden(*args, **kwargs):
                raise AssertionError("Historical replay contacted a model endpoint")

            monkeypatch.setattr("urllib.request.OpenerDirector.open", forbidden)
            root, _, _ = immutable_inspect_source
            bundle, code = ci(
                root.parent / "source",
                tmp_path / "replayed",
                store.root,
                extractor="replay",
                config={"extractor": configuration},
                replay=recorded,
            )
            assert code == 0 and bundle["extraction_events"]
            bundle["run_manifest"]["analysis_context"].pop("extractor_contract")
            # This historical contract predates recorded prompt/revision plans;
            # it does not assert a modern lineage under a different contract.
            bundle.pop("revision_plan")
        else:
            bundle["assessment"].pop("schema_version")
        bundle["run_manifest"].pop("record_contract_version")
        bundle["run_manifest"]["run_id"] += "-" + history
        rehash(bundle)
        store.ingest("main.tex", bundle, {})
    run = bundle["run_manifest"]["run_id"]
    calls = structural_calls(monkeypatch)
    with paper_sources.source_validation_scope():
        assert canonical_bytes(store.inspect(run)["bundle"]) == canonical_bytes(bundle)
        assert canonical_bytes(store.inspect(run)["bundle"]) == canonical_bytes(bundle)
        assert calls == [run, run]


@pytest.fixture(scope="module")
def immutable_pdf_inspection(tmp_path_factory):
    directory = tmp_path_factory.mktemp("pdf-inspect-source")
    source = Path(__file__).parent / "fixtures/campaign/realism/euclid/book-i-proposition-i.pdf"
    bundle, code = ci(source, directory / "out", directory / "store")
    assert code == 0
    assert bundle["document_ir"]["elements"]
    assert all(row["locator"]["format"] == "pdf" for row in bundle["document_ir"]["elements"])
    root = directory / "store"
    before = {
        path.relative_to(root): artifact_digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    }
    yield root, bundle["run_manifest"]["run_id"]
    assert {
        path.relative_to(root): artifact_digest(path.read_bytes())
        for path in root.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize("change", ["callable", "default"])
def test_real_pdf_parser_contract_change_reconstructs_exact_source_again(
    immutable_pdf_inspection, tmp_path, monkeypatch, change
):
    root, run = immutable_pdf_inspection
    shutil.copytree(root, tmp_path / "store")
    store = PaperStore(tmp_path / "store")
    parser = paper_sources.parse
    calls = []

    @wraps(parser)
    def observed(manifest, files, selected="auto", **kwargs):
        calls.append(tuple(artifact_digest(raw) for raw in files.values()))
        return parser(manifest, files, selected, **kwargs)

    monkeypatch.setattr(paper_sources, "parse", observed)
    try:
        with paper_sources.source_validation_scope():
            expected = store.inspect(run)
            assert store.inspect(run) == expected
            assert len(calls) == 1
            if change == "callable":

                @wraps(parser)
                def replaced(manifest, files, selected="auto", **kwargs):
                    calls.append(tuple(artifact_digest(raw) for raw in files.values()))
                    return parser(manifest, files, selected, **kwargs)

                monkeypatch.setattr(paper_sources, "parse", replaced)
            else:
                monkeypatch.setitem(parser.__kwdefaults__, "timeout_seconds", 46)
            assert store.inspect(run) == expected
            assert len(calls) == 2 and calls[0] == calls[1]
    finally:
        store.close()


def test_leaf_inspections_revalidate_without_token_construction_and_return_fresh_material(
    inspect_store, monkeypatch
):
    store, (run, _), expected = inspect_store
    calls = structural_calls(monkeypatch)
    key_calls, reads, queries = [], [], []
    original_key, original_get = paper_store._bundle_validation_key, store.get
    stored_body = body_digest(store, run)

    @wraps(original_key)
    def counted_key(*args, **kwargs):
        key_calls.append(args[0])
        return original_key(*args, **kwargs)

    def observed_get(sha):
        reads.append(sha)
        return original_get(sha)

    monkeypatch.setattr(paper_store, "_bundle_validation_key", counted_key)
    monkeypatch.setattr(store, "get", observed_get)
    assert paper_sources._validation_session.get() is None
    store.db.set_trace_callback(queries.append)
    try:
        first = store.inspect(run)
        assert paper_sources._validation_session.get() is None
        first["bundle"]["assertions"][0]["statement"] = "caller mutation"
        first["artifacts"].clear()
        second = store.inspect(run)
        assert paper_sources._validation_session.get() is None
    finally:
        store.db.set_trace_callback(None)
    assert second == expected
    assert second is not first and second["bundle"] is not first["bundle"]
    assert calls == [run, run]
    assert key_calls == []
    wanted = Counter([stored_body, *expected["artifacts"].values()])
    assert Counter(reads) == Counter({sha: count * 2 for sha, count in wanted.items()})
    assert sum(query.startswith("SELECT bundle FROM runs WHERE id=") for query in queries) == 2


@pytest.mark.parametrize("changed", ["stored_bundle", "main.tex", "claim.tex", "deleted_run"])
def test_leaf_inspection_rejects_current_source_cas_and_sql_changes(
    inspect_store, monkeypatch, changed
):
    store, (run, _), expected = inspect_store
    calls = structural_calls(monkeypatch)
    original_key, key_calls = paper_store._bundle_validation_key, []

    @wraps(original_key)
    def counted_key(*args, **kwargs):
        key_calls.append(args[0])
        return original_key(*args, **kwargs)

    monkeypatch.setattr(paper_store, "_bundle_validation_key", counted_key)
    assert store.inspect(run) == expected
    corrupted_path, original_bytes = None, None
    if changed == "deleted_run":
        with store.db:
            store.db.execute("DELETE FROM runs WHERE id=?", (run,))
        reason = "Unknown run"
    else:
        sha = (
            body_digest(store, run)
            if changed == "stored_bundle"
            else expected["artifacts"][changed]
        )
        corrupted_path = store.root / "objects" / sha[:2] / sha[2:]
        original_bytes = corrupted_path.read_bytes()
        corrupted_path.write_bytes(original_bytes + b"\nchanged current source/CAS bytes")
        reason = "CORRUPT_CAS_OBJECT"
    try:
        with pytest.raises(ValueError, match=reason):
            store.inspect(run)
        assert paper_sources._validation_session.get() is None
        assert calls == [run]  # Current SQL/hash checks reject before any validator/token lookup.
        assert key_calls == []
    finally:
        if corrupted_path is not None:
            corrupted_path.write_bytes(original_bytes)


@pytest.mark.parametrize("batch", ["manual", "decorated"])
def test_leaf_inspection_inherits_explicit_and_decorated_batch_tokens(
    inspect_store, monkeypatch, batch
):
    store, (run, _), expected = inspect_store
    calls = structural_calls(monkeypatch)
    assert paper_sources._validation_session.get() is None

    def inspect_twice():
        outer = paper_sources._validation_session.get()
        assert outer is not None and outer.structural_reuse_enabled is True
        # A nested leaf request cannot downgrade the deliberately selected batch.
        with paper_sources.source_validation_scope(structural_reuse=False) as inner:
            assert inner is outer and inner.structural_reuse_enabled is True
            assert store.inspect(run) == expected
        assert store.inspect(run) == expected
        assert calls == [run]
        return outer

    if batch == "manual":
        with paper_sources.source_validation_scope() as retained:
            assert inspect_twice() is retained
    else:
        retained = paper_sources.source_validation_operation(inspect_twice)()
    assert paper_sources._validation_session.get() is None
    assert not retained._bundle_validations and not retained._contract_certifications
    # Standalone leaves revalidate afresh after the explicit batch has ended.
    assert store.inspect(run) == expected
    assert calls == [run, run]


@pytest.mark.parametrize("error", [ValueError, KeyboardInterrupt])
def test_leaf_sessions_inherit_disabled_mode_and_reset_after_exception(
    inspect_store, monkeypatch, error
):
    store, (run, _), expected = inspect_store
    calls = structural_calls(monkeypatch)
    retained = []
    original_key, key_calls = paper_store._bundle_validation_key, []

    @wraps(original_key)
    def counted_key(*args, **kwargs):
        key_calls.append(args[0])
        return original_key(*args, **kwargs)

    monkeypatch.setattr(paper_store, "_bundle_validation_key", counted_key)

    @paper_sources.source_validation_leaf_operation
    def leaf_child():
        session = paper_sources._validation_session.get()
        assert session is retained[0] and session.structural_reuse_enabled is False
        assert store.inspect(run) == expected

    @paper_sources.source_validation_operation
    def nested_default_batch():
        session = paper_sources._validation_session.get()
        assert session is retained[0] and session.structural_reuse_enabled is False
        assert store.inspect(run) == expected

    @paper_sources.source_validation_leaf_operation
    def failed_leaf():
        session = paper_sources._validation_session.get()
        assert session is not None and session.structural_reuse_enabled is False
        retained.append(session)
        leaf_child()
        nested_default_batch()
        assert calls == [run, run] and key_calls == []
        raise error("exit nested leaf operation")

    assert paper_sources._validation_session.get() is None
    with pytest.raises(error):
        failed_leaf()
    assert paper_sources._validation_session.get() is None
    assert not retained[0]._bundle_validations and not retained[0]._contract_certifications
    assert store.inspect(run) == expected
    assert calls == [run, run, run] and key_calls == []
