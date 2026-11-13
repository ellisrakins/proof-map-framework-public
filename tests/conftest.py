"""Shared immutable intake data; every consumer keeps independent mutation inputs."""

import json
from hashlib import sha256
from pathlib import Path

import pytest


def _fixture_tree_material(root):
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _record_fixture_integrity(directory, name, before, after, serialized):
    (directory / name).write_text(
        json.dumps(
            {
                "kind": "TEST_FIXTURE_INTEGRITY",
                "qualification": False,
                "before": before,
                "after": after,
                "unchanged": before == after,
                "serialized_result_sha256": sha256(serialized).hexdigest(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


@pytest.fixture(scope="session")
def _paper_corpus_baseline_session(tmp_path_factory):
    from proofmap.benchmark import benchmark
    from proofmap.integrity import canonical_bytes

    corpus = Path(__file__).parent / "fixtures/papers"
    audit = tmp_path_factory.mktemp("paper-corpus-fixture-audit")
    before = _fixture_tree_material(corpus)
    serialized = canonical_bytes(benchmark(corpus))
    assert _fixture_tree_material(corpus) == before
    yield serialized
    after = _fixture_tree_material(corpus)
    _record_fixture_integrity(audit, "corpus-integrity.json", before, after, serialized)
    assert after == before, "A consumer changed the shared original paper corpus"


@pytest.fixture
def baseline_paper_corpus(_paper_corpus_baseline_session):
    # Each consumer independently decodes the actual, immutable first measurement.
    return json.loads(_paper_corpus_baseline_session)


@pytest.fixture(scope="session")
def _alpha_offline_outcomes_session(tmp_path_factory):
    from proofmap.integrity import canonical_bytes
    from scripts.paper_alpha_offline import run_scenarios

    corpus = (Path(__file__).parent / "fixtures/papers").resolve()
    directory = tmp_path_factory.mktemp("alpha-offline-fixture")
    audit = tmp_path_factory.mktemp("alpha-offline-fixture-audit")
    corpus_before = _fixture_tree_material(corpus)
    serialized = canonical_bytes(run_scenarios(corpus, directory))
    before = _fixture_tree_material(directory)
    assert _fixture_tree_material(corpus) == corpus_before
    yield serialized
    after = _fixture_tree_material(directory)
    corpus_after = _fixture_tree_material(corpus)
    _record_fixture_integrity(audit, "output-integrity.json", before, after, serialized)
    _record_fixture_integrity(
        audit, "corpus-integrity.json", corpus_before, corpus_after, serialized
    )
    assert after == before, "A consumer changed the shared original offline output"
    assert corpus_after == corpus_before, "A consumer changed the offline source corpus"


@pytest.fixture(scope="session")
def _campaign_offline_realism_session(tmp_path_factory):
    # Import inside the fixture so package import-time coverage starts normally.
    from proofmap.campaign.pilot import evaluate_realism

    corpus = Path(__file__).parent / "fixtures/campaign/realism"
    directory = tmp_path_factory.mktemp("campaign-offline-realism")
    evaluate_realism(corpus, directory)
    artifact = directory / "realism-outcomes.json"
    original = artifact.read_bytes()
    # Bytes cannot carry one consumer's mutable negative case into another.
    yield directory, original
    assert artifact.read_bytes() == original, "A consumer changed the shared original artifact"


@pytest.fixture
def campaign_offline_realism(_campaign_offline_realism_session):
    directory, original = _campaign_offline_realism_session
    return directory, json.loads(original)
