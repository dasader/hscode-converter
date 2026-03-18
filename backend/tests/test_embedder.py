import pytest
from app.data.embedder import HskEmbedder


def test_build_embedding_text():
    text = HskEmbedder.build_embedding_text("리튬이온 축전지", "Lithium-ion accumulators")
    assert "리튬이온 축전지" in text
    assert "Lithium-ion accumulators" in text


def test_build_embedding_text_no_english():
    text = HskEmbedder.build_embedding_text("리튬이온 축전지", None)
    assert "리튬이온 축전지" in text


def test_chunk_list():
    items = list(range(10))
    chunks = list(HskEmbedder.chunk_list(items, 3))
    assert len(chunks) == 4
    assert chunks[0] == [0, 1, 2]
    assert chunks[-1] == [9]
