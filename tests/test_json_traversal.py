"""Traversal optimization preserves JSON limits, bytes and rejection order."""

import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from proofmap.integrity import canonical_bytes, json_value, strict_loads

json_scalars = (
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False)
)
json_scalars |= st.text(alphabet=st.characters(blacklist_categories=("Cs",)))
json_documents = st.recursive(
    json_scalars,
    lambda child: (
        st.lists(child, max_size=8) | st.dictionaries(st.text(alphabet="abcé雪"), child, max_size=8)
    ),
    max_leaves=40,
)


@given(json_documents)
def test_nested_json_keeps_exact_canonical_bytes_and_roundtrip(value):
    expected = json.dumps(
        value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")
    assert canonical_bytes(value) == expected
    assert canonical_bytes(strict_loads(expected)) == expected


@pytest.mark.parametrize("container", [list, tuple, dict])
def test_depth_128_is_accepted_and_129_is_rejected(container):
    value = None
    for _ in range(128):
        value = {"child": value} if container is dict else container([value])
    json_value(value)
    with pytest.raises(ValueError, match="RESOURCE_LIMIT: JSON depth/item limit"):
        json_value([value])


@pytest.mark.parametrize("container", [list, dict])
def test_item_limit_counts_containers_and_every_child_exactly(container):
    values = [None] * (999_999 if container is list else 999_998)
    value = values if container is list else {"children": values}
    json_value(value)
    values.append(None)
    with pytest.raises(ValueError, match="RESOURCE_LIMIT: JSON depth/item limit"):
        json_value(value)


@pytest.mark.parametrize(
    "value, message",
    [
        ([object(), float("inf")], "NONFINITE_OR_TYPE"),
        ((float("inf"), object()), "TYPE: unsupported JSON value"),
        ({"earlier": object(), "later": float("nan")}, "NONFINITE_OR_TYPE"),
        ({"earlier": float("nan"), "later": object()}, "TYPE: unsupported JSON value"),
        ({1: object(), "last": float("nan")}, "TYPE: JSON keys must be strings"),
        ([object(), {1: None}], "TYPE: JSON keys must be strings"),
    ],
)
def test_depth_first_rejection_order_and_dictionary_key_precedence(value, message):
    with pytest.raises(ValueError, match=message):
        json_value(value)


@pytest.mark.parametrize("position", [0, 500, 999])
@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), object(), {False: None}])
def test_no_child_is_skipped_at_any_position(position, invalid):
    values = [None] * 1000
    values[position] = invalid
    with pytest.raises(ValueError):
        json_value({"nested": tuple(values)})


def test_tuples_booleans_unicode_and_shared_subtrees_retain_existing_json_semantics():
    subtree = {"雪": (None, True, False, -3, 0.25)}
    assert canonical_bytes([subtree, subtree]) == (
        '[{"雪":[null,true,false,-3,0.25]},{"雪":[null,true,false,-3,0.25]}]'.encode()
    )


def test_cyclic_container_still_fails_depth_limit():
    value = []
    value.append(value)
    with pytest.raises(ValueError, match="RESOURCE_LIMIT: JSON depth/item limit"):
        json_value(value)


@pytest.mark.parametrize("invalid_index", [None, 0, 1, 2])
def test_dictionary_key_order_subclasses_and_first_invalid_short_circuit(invalid_index):
    class StringKey(str):
        pass

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

    keys = [StringKey("first"), "second", "third"]
    if invalid_index is not None:
        keys[invalid_index] = invalid_index
    value = ObservedKeys.fromkeys(keys)
    if invalid_index is None:
        json_value(value)
        assert visited == keys and values_calls == [True]
    else:
        with pytest.raises(ValueError, match="TYPE: JSON keys must be strings"):
            json_value(value)
        assert visited == keys[: invalid_index + 1] and values_calls == []
