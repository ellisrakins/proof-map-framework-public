"""Exact report escaping compatibility with the implementation at 3600a7c."""

import html

import pytest
from hypothesis import given
from hypothesis import strategies as st

from proofmap.integrity import markdown_text


def original_markdown_text(value):
    """Frozen compatibility oracle, including escaping order and quote spelling."""
    return "".join(
        f"&#{ord(char)};" if char in "|`[]()!*_#" else html.escape(char)
        for char in str(value).replace("\r", " ").replace("\n", " ")
    )


unicode_text = st.text(alphabet=st.integers(0, 0x10FFFF).map(chr), max_size=2048)


@given(unicode_text)
def test_markdown_escape_matches_original_for_unicode_text(value):
    assert markdown_text(value) == original_markdown_text(value)


@given(unicode_text, unicode_text)
def test_generated_entities_are_not_reescaped_across_text_boundaries(left, right):
    assert markdown_text(left + right) == original_markdown_text(left + right)
    assert markdown_text(left + right) == markdown_text(left) + markdown_text(right)


@pytest.mark.parametrize(
    "value, expected",
    [
        ("|`[]()!*_#", "&#124;&#96;&#91;&#93;&#40;&#41;&#33;&#42;&#95;&#35;"),
        ("&<>\"'", "&amp;&lt;&gt;&quot;&#x27;"),
        ("before\r\nafter\rfinal\n", "before  after final "),
        ("&#124;|", "&amp;&#35;124;&#124;"),
        ("&amp; &quot; &#x27;", "&amp;amp; &amp;quot; &amp;&#35;x27;"),
        (
            '[x](javascript:alert("x"))',
            "&#91;x&#93;&#40;javascript:alert&#40;&quot;x&quot;&#41;&#41;",
        ),
        (
            "</script><img src=x onerror='alert(1)'>",
            "&lt;/script&gt;&lt;img src=x onerror=&#x27;alert&#40;1&#41;&#x27;&gt;",
        ),
    ],
)
def test_markdown_and_html_injection_payloads_keep_exact_inert_entities(value, expected):
    assert markdown_text(value) == original_markdown_text(value) == expected


@pytest.mark.parametrize("value", [None, True, False, 0, -1, 0.25, ("[x]", "\r\n"), {"<x>": "&"}])
def test_nonstring_inputs_keep_existing_string_conversion(value):
    assert markdown_text(value) == original_markdown_text(value)


def test_control_characters_unicode_and_lone_surrogates_are_preserved():
    value = "".join(map(chr, range(256))) + "\u03bb\u96ea\U0001f600\u2028\u2029\ud800\udfff"
    assert markdown_text(value) == original_markdown_text(value)


def test_input_string_conversion_occurs_exactly_once():
    class Rendered:
        def __init__(self):
            self.calls = 0

        def __str__(self):
            self.calls += 1
            return '<label title="[x]">\r\n&'

    value = Rendered()
    assert markdown_text(value) == original_markdown_text('<label title="[x]">\r\n&')
    assert value.calls == 1
