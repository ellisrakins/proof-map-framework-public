"""Native certificates preserve current canonical guards and structural rules."""

from copy import deepcopy
from functools import wraps

import pytest
from test_paper_store_inspect_memo import (
    immutable_inspect_source as immutable_inspect_source,
)
from test_paper_store_inspect_memo import (
    inspect_store as inspect_store,
)
from test_paper_store_inspect_memo import (
    structural_calls,
)

from proofmap import paper_sources, paper_store
from proofmap.schema import _validator


def canonical_calls(monkeypatch):
    original = paper_store._contract_digest
    calls = []

    @wraps(original)
    def observed(settings):
        calls.append(deepcopy(settings))
        return original(settings)

    monkeypatch.setattr(paper_store, "_contract_digest", observed)
    return calls


def test_certificate_preserves_digest_with_aliases_and_current_mutable_values(monkeypatch):
    shared = [1, True, None, "é"]
    settings = {"a": shared, "b": shared}
    separate = {"a": list(shared), "b": list(shared)}
    expected = paper_store._contract_digest(settings)
    assert paper_store._contract_digest(separate) == expected
    calls = canonical_calls(monkeypatch)
    with paper_sources.source_validation_scope() as session:
        assert paper_store._certified_contract_digest(settings) == expected
        assert paper_store._certified_contract_digest(settings) == expected
        assert len(calls) == 1
        assert paper_store._certified_contract_digest(separate) == expected
        shared.append(2)
        changed = paper_store._certified_contract_digest(settings)
        assert changed != expected
        assert paper_store._certified_contract_digest(settings) == changed
        for (stamp_digest, context), canonical_digest in session._contract_certifications.items():
            assert isinstance(stamp_digest, str) and len(stamp_digest) == 64
            assert isinstance(context, tuple)
            assert isinstance(canonical_digest, str) and len(canonical_digest) == 64
        assert session._contract_certifications
    assert not session._contract_certifications


def test_invalid_live_contract_cannot_hit_a_valid_typed_certificate():
    cyclic = {}
    cyclic["value"] = cyclic
    deep = {"value": 1}
    for _ in range(128):
        deep = {"value": deep}
    invalid = [
        {1: "same"},
        {True: "same"},
        {"value": float("nan")},
        {"value": float("inf")},
        cyclic,
        deep,
        {"value": [0] * 1_000_000},
    ]
    with paper_sources.source_validation_scope() as session:
        paper_store._certified_contract_digest({"1": "same"})
        paper_store._certified_contract_digest({"true": "same"})
        paper_store._certified_contract_digest({"value": 1})
        before = dict(session._contract_certifications)
        for settings in invalid:
            for _ in range(2):
                with pytest.raises((TypeError, ValueError, RecursionError, OverflowError)):
                    paper_store._certified_contract_digest(settings)
                assert dict(session._contract_certifications) == before


def test_native_stamp_unknown_and_subclass_inputs_execute_no_python_hooks():
    hooks = []

    def observed_hook(*args, **kwargs):
        hooks.append("EXECUTED")
        raise AssertionError("Native metadata snapshot executed a Python input hook")

    class HookedDict(dict):
        __iter__ = items = values = __getitem__ = observed_hook

    class HookedList(list):
        __iter__ = __getitem__ = observed_hook

    class HookedTuple(tuple):
        __iter__ = __getitem__ = observed_hook

    class HookedInt(int):
        __int__ = __index__ = observed_hook

    class HookedFloat(float):
        __float__ = observed_hook

    class HookedString(str):
        __str__ = observed_hook

    values = [
        object(),
        HookedDict(value=1),
        HookedList([1]),
        HookedTuple((1,)),
        HookedInt(1),
        HookedFloat(1),
        HookedString("value"),
    ]
    with paper_sources.source_validation_scope() as session:
        paper_store._certified_contract_digest({"value": 1})
        before = dict(session._contract_certifications)
        for value in values:
            assert paper_store._native_contract_stamp({"value": value}) is None
            assert not hooks
            assert dict(session._contract_certifications) == before


@pytest.mark.parametrize("encoder", ["constant", "wrong_builtin"])
def test_forged_native_encoder_cannot_hide_changed_compiled_constraint(
    inspect_store, monkeypatch, encoder
):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    canonical = paper_store._contract_digest
    native_encoder = paper_store.marshal.dumps
    captured_stamps = []

    @wraps(canonical)
    def observed(settings):
        defaults, _ = paper_store._contract_certification_context()
        captured_stamps.append(
            native_encoder({"settings": settings, "canonical_defaults": defaults}, 4)
        )
        return canonical(settings)

    monkeypatch.setattr(paper_store, "_contract_digest", observed)
    validator = _validator("paper-input")
    original = list(validator._validators)
    type_index = next(i for i, (_, name, _) in enumerate(original) if name == "type")
    schema_before = deepcopy(validator.schema)
    try:
        with paper_sources.source_validation_scope() as session:
            store.inspect(run)
            store.inspect(run)
            assert calls == [run]
            assert captured_stamps and session._contract_certifications
            before = dict(session._contract_certifications)
            stamp_count = len(captured_stamps)
            if encoder == "constant":
                prior_stamp = captured_stamps[-1]
                monkeypatch.setattr(paper_store.marshal, "dumps", lambda *args: prior_stamp)
            else:
                monkeypatch.setattr(paper_store.marshal, "dumps", paper_store.marshal.loads)
            function, keyword, _ = original[type_index]
            # Same public schema and actual keyword function; the cached compiled
            # constraint now rejects every previously valid input object.
            validator._validators[type_index] = (function, keyword, "null")
            assert validator.schema == schema_before
            assert validator._validators[type_index][0] is function
            with pytest.raises(ValueError, match="INVALID_PAPER_BUNDLE_SCHEMA: paper-input"):
                store.inspect(run)
            assert calls == [run, run]
            assert len(captured_stamps) > stamp_count  # Fresh canonical fallback ran.
            assert dict(session._contract_certifications) == before
    finally:
        validator._validators[:] = original


@pytest.mark.parametrize("change", ["function", "code"])
def test_current_canonical_guard_cannot_reuse_an_earlier_certificate(monkeypatch, change):
    settings = {"value": 1}
    with paper_sources.source_validation_scope() as session:
        paper_store._certified_contract_digest(settings)
        before = dict(session._contract_certifications)

        def rejecting(settings):
            raise ValueError("CURRENT_CANONICAL_GUARD_REJECTION")

        if change == "function":
            monkeypatch.setattr(paper_store, "_contract_digest", rejecting)
        else:
            original = paper_store._contract_digest
            assert original.__code__.co_freevars == rejecting.__code__.co_freevars
            monkeypatch.setattr(original, "__code__", rejecting.__code__)
        with pytest.raises(ValueError, match="CURRENT_CANONICAL_GUARD_REJECTION"):
            paper_store._certified_contract_digest(settings)
        assert dict(session._contract_certifications) == before


def test_mid_certification_mutation_cannot_publish_a_success(monkeypatch):
    original = paper_store._contract_digest
    calls = []

    @wraps(original)
    def mutating(settings):
        calls.append(1)
        result = original(settings)
        settings["value"] += 1
        return result

    monkeypatch.setattr(paper_store, "_contract_digest", mutating)
    with paper_sources.source_validation_scope() as session:
        for _ in range(2):
            with pytest.raises(ValueError, match="MEMO_CONTRACT_CHANGED_DURING_CERTIFICATION"):
                paper_store._certified_contract_digest({"value": 1})
            assert not session._contract_certifications
        assert len(calls) == 2


def test_changed_canonical_default_rejects_same_callable_and_code(monkeypatch):
    original = paper_store._contract_digest

    def current(settings, *, reject=False):
        if reject:
            raise ValueError("CURRENT_CANONICAL_DEFAULT_REJECTION")
        return original(settings)

    monkeypatch.setattr(paper_store, "_contract_digest", current)
    with paper_sources.source_validation_scope() as session:
        paper_store._certified_contract_digest({"value": 1})
        before = dict(session._contract_certifications)
        code = current.__code__
        monkeypatch.setitem(current.__kwdefaults__, "reject", True)
        assert current.__code__ is code and paper_store._contract_digest is current
        with pytest.raises(ValueError, match="CURRENT_CANONICAL_DEFAULT_REJECTION"):
            paper_store._certified_contract_digest({"value": 1})
        assert dict(session._contract_certifications) == before


def test_certificate_lru_and_zero_limit_preserve_full_guard(monkeypatch):
    calls = canonical_calls(monkeypatch)
    monkeypatch.setattr(paper_sources, "MAX_VALIDATED_BUNDLES", 1)
    with paper_sources.source_validation_scope() as session:
        for value in (1, 1, 2, 2, 1):
            paper_store._certified_contract_digest({"value": value})
            assert len(session._contract_certifications) == 1
        assert [row["value"] for row in calls] == [1, 2, 1]
        monkeypatch.setattr(paper_sources, "MAX_VALIDATED_BUNDLES", 0)
        for _ in range(2):
            paper_store._certified_contract_digest({"value": 1})
            assert not session._contract_certifications
        assert [row["value"] for row in calls] == [1, 2, 1, 1, 1]


def test_nested_reset_and_baseexception_discard_both_success_caches(inspect_store, monkeypatch):
    store, (run, _), _ = inspect_store
    calls = structural_calls(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        with paper_sources.source_validation_scope() as outer:
            store.inspect(run)
            assert outer._contract_certifications and outer._bundle_validations
            with paper_sources.source_validation_scope() as inner:
                assert inner is outer
                store.inspect(run)
            assert calls == [run]
            outer.clear_bundle_validations()
            assert not outer._contract_certifications and not outer._bundle_validations
            store.inspect(run)
            assert calls == [run, run]
            assert outer._contract_certifications and outer._bundle_validations
            raise KeyboardInterrupt("leave the complete validation operation")
    assert not outer._contract_certifications and not outer._bundle_validations
    with paper_sources.source_validation_scope() as fresh:
        assert not fresh._contract_certifications and not fresh._bundle_validations
        store.inspect(run)
        store.inspect(run)
        assert calls == [run, run, run]
