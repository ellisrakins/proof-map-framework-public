from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from proofmap.cli import main
from proofmap.examples import build_minimal_conops_map
from proofmap.integrity import (
    ValidationIssue,
    atomic_write,
    canonical_bytes,
    csv_cell,
    digest,
    finite_number,
    json_value,
    relative_path,
    rooted_path,
    strict_loads,
)
from proofmap.kernel import Claim, Context, Inference, KernelMap, closure, migrate, semantic_digest
from proofmap.paper import ci
from proofmap.schema import schema, validate


def test_packaged_schema_roundtrips():
    import jsonschema

    for name in (
        "kernel",
        "source-locator",
        "paper-input",
        "document-ir",
        "formal_obligation",
        "proof_attempt",
        "proofmap",
        "source",
        "theory_catalog",
        "hypothesis",
    ):
        jsonschema.Draft202012Validator.check_schema(schema(name))
    g = migrate(build_minimal_conops_map().to_dict())
    assert not validate("kernel", g.to_dict())
    assert validate("kernel", {"schema_version": "999"})
    with pytest.raises(ValueError):
        schema("../../secret")
    assert ValidationIssue("TEST", "/", "sample").to_dict()["severity"] == "ERROR"


@given(st.permutations(["a", "b", "c", "d"]))
def test_property_graph_order_does_not_change_identity(order):
    g = KernelMap(tuple(Claim(c, c, "c", "r") for c in order), (Context("c", "r"),))
    h = replace(g, claims=tuple(sorted(g.claims, key=lambda c: c.id)))
    assert semantic_digest(g) == semantic_digest(h)
    assert closure(g).to_dict() == closure(h).to_dict()


@pytest.mark.parametrize(
    "value", [float("nan"), {"a": float("inf")}, {1: "not-string-key"}, object()]
)
def test_json_boundary_nonfinite_and_nonjson(value):
    with pytest.raises(ValueError):
        json_value(value)


@pytest.mark.parametrize("value", ["../a", "a/../b", "a.", "a ", "nul", "a//b", "a\x00b", "D:/a"])
def test_path_aliases(value):
    with pytest.raises(ValueError):
        relative_path(value)


def test_integrity_helpers(tmp_path):
    with pytest.raises(ValueError):
        finite_number(-1, "n", minimum=0)
    with pytest.raises(ValueError):
        digest("Bad Domain", {})
    with pytest.raises(ValueError):
        strict_loads('{"n":NaN}')
    path = tmp_path / "new" / "file"
    atomic_write(path, "original")
    atomic_write(path, b"replaced")
    assert path.read_bytes() == b"replaced"
    assert rooted_path(tmp_path, "new/file") == path
    assert csv_cell("=danger") == "'=danger"
    assert csv_cell(4) == 4
    assert canonical_bytes({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_kernel_rejects_invalid_graphs():
    g = KernelMap((Claim("a", "a", "c", "r"),), (Context("c", "r"),))
    bad = [
        replace(g, claims=g.claims * 2),
        replace(g, contexts=()),
        replace(g, claims=(replace(g.claims[0], status="NOT_A_STATUS"),)),
        replace(g, inferences=(Inference("i", "a", ("missing",), "c"),)),
        replace(g, contexts=(Context("c", ""),)),
    ]
    for invalid in bad:
        with pytest.raises(ValueError):
            closure(invalid)
    with pytest.raises(ValueError):
        closure(g, policy="unknown")
    with pytest.raises(ValueError):
        closure(g, assumptions=(("c", "a"),))
    value = g.to_dict()
    value["schema_version"] = "999"
    with pytest.raises(ValueError):
        KernelMap.from_dict(value)


def test_new_cli_commands(tmp_path):
    path = str(tmp_path / "migrated.json")
    assert main(["migrate", "examples/minimal_conops.json", "--out", path]) == 0
    for command in ("digest", "canonicalize", "validate"):
        assert main([command, path]) == 0
    assert main(["closure", path, "--foundation", "malformed"]) == 2
    assert main(["closure", path, "--target", "missing"]) == 2
    b, _ = ci(Path("tests/fixtures/papers/train/basic.tex"), tmp_path / "out", tmp_path / "store")
    run = b["run_manifest"]["run_id"]
    assert main(["paper", "inspect", run, "--store", str(tmp_path / "store")]) == 0
    assert main(["paper", "rebuild", "--store", str(tmp_path / "store")]) == 0
    assert main(["paper", "assess", str(tmp_path / "out")]) == 0
    assert main(["paper", "diff", str(tmp_path / "out"), str(tmp_path / "out")]) == 0
    review = str(tmp_path / "review.json")
    assert (
        main(["paper", "review-export", str(tmp_path / "out"), "--author", "test", "--out", review])
        == 0
    )
    assert (
        main(
            [
                "paper",
                "review-apply",
                str(tmp_path / "out"),
                review,
                "--store",
                str(tmp_path / "store"),
            ]
        )
        == 0
    )


def test_born_digital_and_scanned_pdf_fixtures(tmp_path):
    for stem in ("born_digital", "scan"):
        b, _ = ci(
            Path("tests/fixtures/papers/pdf") / (stem + ".pdf"), tmp_path / stem, tmp_path / "store"
        )
        assert b["document_ir"]["parser"]["ocr"] is False
        if stem == "scan":
            assert any(f["code"] == "NEEDS_OCR" for f in b["findings"])
        else:
            assert "2*x = x+x" in b["document_ir"]["elements"][0]["text"]


def test_large_iterative_graph():
    from proofmap.model import Edge, Node, ProofMap

    pm = ProofMap("large")
    for i in range(3000):
        pm.add_node(Node(str(i), str(i), "THEOREM", "PROVED", "INTERIOR"))
    for i in range(2999):
        pm.add_edge(Edge(str(i), str(i + 1)))
    assert pm.detect_cycles() == []
    result = closure(migrate(pm.to_dict()))
    assert len(result.open) == 3000
