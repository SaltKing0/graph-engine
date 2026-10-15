"""Local model code must stay untrusted; real model checks need only [st]."""
from __future__ import annotations

import importlib.util
import json
import sys
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from graph_engine.embedder import Embedder, get_embedder
from graph_engine.reranker import CrossEncoderReranker, get_reranker
from tools.memory_benchmark.embeddings import LocalEmbeddings


@pytest.fixture
def st(tmp_path: Path, monkeypatch):
    if importlib.util.find_spec("sentence_transformers") is None:
        pytest.skip("requires optional [st] extra")
    import sentence_transformers
    from transformers import dynamic_module_utils

    # Trusted fixture control must also keep dynamic-module cache writes in tmp.
    cache = tmp_path / "modules-cache"
    monkeypatch.setattr(dynamic_module_utils, "HF_MODULES_CACHE", str(cache))
    monkeypatch.syspath_prepend(str(cache))
    return sentence_transformers


def test_semantic_dependency_pin_enforces_local_trust() -> None:
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    assert project["project"]["optional-dependencies"]["st"] == ["sentence-transformers==6.1.0"]
    assert "sentence-transformers==6.1.0" in (root / "requirements.txt").read_text().splitlines()
    assert not any("sentence-transformers" in dep for dep in project["project"]["dependencies"])


def test_engine_loaders_explicitly_disable_custom_code(monkeypatch) -> None:
    calls = []

    def model(name, **kwargs):
        calls.append((name, kwargs))
        return object()

    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=model, CrossEncoder=model))
    embedder = get_embedder("st", "/Models/Embedding")
    assert calls == []  # The embedder remains lazy.
    embedder._ensure_model()
    embedder._ensure_model()
    monkeypatch.setenv("IDEAGRAPH_RERANKER", "/Models/Reranker")
    get_reranker()
    assert calls == [("/Models/Embedding", {"trust_remote_code": False}),
                     ("/Models/Reranker", {"trust_remote_code": False})]


@pytest.fixture
def untrusted_model(tmp_path: Path) -> tuple[Path, Path]:
    """A benign custom class writes a marker if its module is ever imported."""
    path = tmp_path / "UntrustedModel"
    path.mkdir()
    marker = tmp_path / "custom-code-executed"
    (path / "custom.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported')\n"
        "class Custom:\n"
        "    @classmethod\n"
        "    def load(cls, *args, **kwargs):\n"
        "        raise RuntimeError('custom loader executed')\n"
    )
    (path / "modules.json").write_text(json.dumps([
        {"idx": 0, "name": "0", "path": "", "type": "custom.Custom"},
    ]))
    return path, marker


@pytest.mark.parametrize("loader", ["upstream", "embedder", "benchmark", "reranker"])
def test_local_custom_module_is_rejected_before_import(untrusted_model, monkeypatch, loader, st) -> None:
    path, marker = untrusted_model
    if loader == "reranker":
        (path / "config_sentence_transformers.json").write_text(
            json.dumps({"model_type": "CrossEncoder"}))
    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    with pytest.raises(ValueError, match="trust_remote_code=True"):
        if loader == "upstream":
            st.SentenceTransformer(str(path), local_files_only=True, trust_remote_code=False)
        elif loader == "embedder":
            get_embedder("st", str(path)).embed("test")
        elif loader == "benchmark":
            LocalEmbeddings(path, seed=7)
        else:
            monkeypatch.setenv("IDEAGRAPH_RERANKER", str(path))
            get_reranker()
    assert not marker.exists(), "custom Python was executed despite disabled trust"


def test_custom_module_fixture_detects_import_when_trusted(untrusted_model, st) -> None:
    path, marker = untrusted_model
    with pytest.raises(RuntimeError, match="custom loader executed"):
        st.SentenceTransformer(str(path), local_files_only=True, trust_remote_code=True)
    assert marker.read_text() == "imported"


@pytest.fixture
def local_models(tmp_path: Path, monkeypatch, st) -> tuple[Path, Path]:
    """Tiny real BERT models: no Hub, download, or pre-trained weights needed."""
    import torch
    from sentence_transformers.base.modules import Transformer
    from sentence_transformers.sentence_transformer.modules import Pooling
    from transformers import BertConfig, BertModel, BertForSequenceClassification, BertTokenizer

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    torch.manual_seed(7)
    backbone = tmp_path / "Backbone"
    backbone.mkdir()
    vocab = backbone / "vocab.txt"
    vocab.write_text("[PAD]\n[UNK]\n[CLS]\n[SEP]\n[MASK]\nhello\nworld\nquery\ndocument\n")
    tokenizer = BertTokenizer(vocab_file=str(vocab))
    tokenizer.save_pretrained(backbone)
    config = BertConfig(vocab_size=9, hidden_size=16, num_hidden_layers=1,
                        num_attention_heads=2, intermediate_size=32, num_labels=1)
    BertModel(config).save_pretrained(backbone)
    encoder = st.SentenceTransformer(modules=[
        Transformer(str(backbone), max_seq_length=32),
        Pooling(16),
    ], device="cpu")
    embedding = tmp_path / "EmbeddingModel"
    encoder.save_pretrained(str(embedding))
    reranker = tmp_path / "RerankerModel"
    BertForSequenceClassification(config).save_pretrained(reranker)
    tokenizer.save_pretrained(reranker)
    return embedding, reranker


def test_real_local_embedding_override_and_offline_benchmark(local_models, monkeypatch) -> None:
    import numpy as np
    from graph_engine.runtime import make_engine, reset_engine_cache

    embedding, _ = local_models
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER", "st")
    monkeypatch.setenv("IDEAGRAPH_EMBEDDER_MODEL", str(embedding))
    monkeypatch.setenv("IG_BRAIN_PATH", str(embedding.parent / "brain"))
    monkeypatch.setenv("IG_BRAIN_MODE", "local")
    reset_engine_cache()
    try:
        engine = make_engine()
        assert isinstance(engine.embedder, Embedder)
        assert engine.embedder.model_name == str(embedding)
        texts = ["hello world", "query document"]
        vectors = engine.embedder.embed_batch(texts)
        assert np.asarray(vectors).shape == (2, 16)
        assert np.isfinite(vectors).all()
        assert np.allclose(engine.embedder.embed(texts[0]), vectors[0], atol=1e-6)
        offline = LocalEmbeddings(embedding, seed=7)
        batch = offline.embed_batch(texts)
        assert np.allclose(offline.embed(texts[0]), batch[0], atol=1e-6)
        assert np.allclose(np.linalg.norm(batch, axis=1), 1, atol=1e-6)
        assert offline.metadata["dimension"] == 16
        assert offline.metadata["trust_remote_code"] is False
        assert offline.metadata["local_files_only"] is True
        assert offline.metadata["sentence_transformers_version"] == "6.1.0"
    finally:
        reset_engine_cache()


def test_real_cross_encoder_override_preserves_scores(local_models, monkeypatch) -> None:
    import numpy as np

    _, reranker_path = local_models
    monkeypatch.setenv("IDEAGRAPH_RERANKER", str(reranker_path))
    reranker = get_reranker()
    assert isinstance(reranker, CrossEncoderReranker)
    candidates = [("a", "hello world", 0.1), ("b", "query document", 0.2)]
    hits, scores = reranker.rerank_with_scores("hello query", candidates, k=1)
    assert set(scores) == {"a", "b"}
    assert all(np.isfinite(score) for score in scores.values())
    assert hits == sorted(candidates, key=lambda cand: scores[cand[0]], reverse=True)[:1]
    assert reranker.rerank("hello query", candidates, k=2) == sorted(
        candidates, key=lambda cand: scores[cand[0]], reverse=True)
    assert reranker.rerank_with_scores("hello", [], k=2) == ([], {})


def test_vector_model_identity_tracks_local_files_and_loaded_snapshot(tmp_path, monkeypatch):
    from graph_engine.vector_cache import model_identity, model_key
    path = tmp_path / 'local-model'
    path.mkdir()
    weights = path / 'weights.bin'
    weights.write_bytes(b'first weights')
    calls = []
    def load(name, **options):
        calls.append(options)
        return SimpleNamespace(max_seq_length=32, truncate_dim=None)
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=load))
    first = Embedder(str(path))
    original = model_key(None, model_identity(first))
    assert model_key(None, model_identity(Embedder(str(path)))) == original
    weights.write_bytes(b'other weights')  # same dimensions and file size
    assert model_key(None, model_identity(first)) == original  # still loaded old weights
    assert model_key(None, model_identity(Embedder(str(path)))) != original
    assert all(options == {'trust_remote_code': False} for options in calls)


def test_vector_remote_revision_identity_is_complete_or_instance_scoped(monkeypatch):
    from graph_engine.vector_cache import model_identity, model_key
    calls = []
    def load(name, **options):
        calls.append(options)
        return SimpleNamespace(max_seq_length=32, truncate_dim=None)
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=load))
    def key(adapter):
        return model_key(None, model_identity(adapter))
    # An unpinned model name alone cannot prove identical repository contents.
    assert key(Embedder('model')) != key(Embedder('model'))
    revision = 'a' * 40
    first = Embedder('model', revision=revision)
    assert key(first) == key(Embedder('model', revision=revision))
    original = key(first)
    first.revision = 'b' * 40
    assert key(first) != original
    assert calls[-1] == {'trust_remote_code': False, 'revision': 'b' * 40}


def test_vector_identity_uses_resolved_st_repository_revision(monkeypatch):
    from graph_engine.vector_cache import model_identity, model_key
    revision = 'c' * 40
    def load(name, **options):
        return SimpleNamespace(model_card_data=SimpleNamespace(
            base_model='sentence-transformers/model', base_model_revision=revision))
    monkeypatch.setitem(sys.modules, 'sentence_transformers', SimpleNamespace(SentenceTransformer=load))
    first = model_key(None, model_identity(Embedder('model')))
    assert model_key(None, model_identity(Embedder('model'))) == first
    revision = 'd' * 40
    assert model_key(None, model_identity(Embedder('model'))) != first
