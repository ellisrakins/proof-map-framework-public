"""Exact scalar shortcuts preserve the strict JSON boundary and fallback hooks."""

import pytest

from proofmap import integrity


class IntegerValue(int):
    pass


class TextValue(str):
    pass


class FloatValue(float):
    pass


@pytest.mark.parametrize(
    "value, expected",
    [
        (None, b"null"),
        (True, b"true"),
        (False, b"false"),
        (0, b"0"),
        (-3, b"-3"),
        ("雪", '"雪"'.encode()),
        ('"\n\x00', b'"\\"\\n\\u0000"'),
    ],
)
def test_exact_builtin_scalars_keep_expected_canonical_bytes(value, expected):
    integrity.json_value(value)
    assert integrity.canonical_bytes(value) == expected
    assert integrity.strict_loads(expected) == value


@pytest.mark.parametrize("value, expected", [(IntegerValue(7), b"7"), (TextValue("s"), b'"s"')])
def test_integer_and_string_subclasses_retain_existing_acceptance(value, expected):
    integrity.json_value(value)
    assert integrity.canonical_bytes(value) == expected


def test_foreign_class_equality_is_not_called_by_exact_scalar_detection():
    class EqualityTrap(type):
        def __eq__(self, other):
            raise AssertionError("Scalar detection must use identity, not class equality")

    class ForeignValue(metaclass=EqualityTrap):
        pass

    with pytest.raises(ValueError, match="TYPE: unsupported JSON value"):
        integrity.json_value(ForeignValue())


def test_foreign_isinstance_fallback_remains_observable():
    observed = []

    class ForeignString:
        @property
        def __class__(self):
            observed.append(True)
            return str

    integrity.json_value(ForeignString())
    assert observed


def test_builtin_floats_still_call_current_finite_number_in_traversal_order(monkeypatch):
    original = integrity.finite_number
    calls = []

    def observed(value, name, *, minimum=None):
        calls.append((value, name, minimum))
        return original(value, name, minimum=minimum)

    monkeypatch.setattr(integrity, "finite_number", observed)
    integrity.json_value({"values": [None, "s", True, False, 3, -2, 1.25, -0.0]})
    assert calls == [(-0.0, "JSON number", None), (1.25, "JSON number", None)]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), FloatValue(1.25)])
def test_nonfinite_values_and_float_subclasses_retain_real_numeric_rejection(monkeypatch, value):
    original = integrity.finite_number
    calls = []

    def observed(number, name, *, minimum=None):
        calls.append(number)
        return original(number, name, minimum=minimum)

    monkeypatch.setattr(integrity, "finite_number", observed)
    with pytest.raises(ValueError, match="NONFINITE_OR_TYPE JSON number"):
        integrity.json_value([None, value])
    assert len(calls) == 1 and calls[0] is value


def test_nonstring_key_still_short_circuits_before_values_or_later_nonfinite_number():
    visited = []
    values_calls = []

    class ObservedKeys(dict):
        def __iter__(self):
            for key in super().__iter__():
                visited.append(key)
                yield key

        def values(self):
            values_calls.append(True)
            return super().values()

    value = ObservedKeys([(TextValue("first"), None), (False, True), ("last", float("nan"))])
    with pytest.raises(ValueError, match="TYPE: JSON keys must be strings"):
        integrity.json_value(value)
    assert visited == ["first", False]
    assert values_calls == []


def test_scalar_at_depth_limit_is_counted_before_shortcut():
    value = True
    for _ in range(128):
        value = [value]
    integrity.json_value(value)
    with pytest.raises(ValueError, match="RESOURCE_LIMIT: JSON depth/item limit"):
        integrity.json_value([value])


def test_mixed_exact_scalars_still_count_toward_every_item_at_limit():
    value = [None, False, 7, "s"] * 249_999 + [0, True, None]
    integrity.json_value(value)
    value.append("one too many")
    with pytest.raises(ValueError, match="RESOURCE_LIMIT: JSON depth/item limit"):
        integrity.json_value(value)


def test_cyclic_container_with_exact_scalar_still_hits_original_depth_limit():
    value = [False]
    value.append(value)
    with pytest.raises(ValueError, match="RESOURCE_LIMIT: JSON depth/item limit"):
        integrity.json_value(value)


def test_mixed_tuple_unicode_and_subclasses_keep_exact_bytes_and_fresh_decode():
    value = {"z": (None, True, IntegerValue(7)), "é": TextValue("雪"), "a": -0.0}
    expected = '{"a":-0.0,"z":[null,true,7],"é":"雪"}'.encode()
    assert integrity.canonical_bytes(value) == expected
    decoded = integrity.strict_loads(expected)
    assert decoded == {"a": -0.0, "z": [None, True, 7], "é": "雪"}
    assert decoded is not value and decoded["z"] is not value["z"]
