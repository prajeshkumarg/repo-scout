"""Embedder tests with a fake model. No network, per testing rules."""

import numpy as np

from chunking.chunker import Chunk
from embedding import LocalEmbedder, embedding_text


class FakeModel:
    """Records embed() calls and returns fixed vectors."""

    def __init__(self, dims: int = 768) -> None:
        self.dims = dims
        self.calls: list[list[str]] = []

    def embed(self, documents: list[str]):
        self.calls.append(list(documents))
        return [np.full(self.dims, 0.5) for _ in documents]


def make_embedder(batch_size: int = 100) -> tuple[LocalEmbedder, FakeModel]:
    model = FakeModel()
    embedder = LocalEmbedder(
        model_name="unused-in-tests", batch_size=batch_size, model=model
    )
    return embedder, model


def test_embeds_every_text():
    embedder, model = make_embedder()

    vectors = embedder.embed_documents(["a", "b"])

    assert model.calls == [["a", "b"]]
    assert all(len(v) == 768 for v in vectors)


def test_query_embeds_a_single_text():
    embedder, model = make_embedder()

    vector = embedder.embed_query("what does main do")

    assert model.calls == [["what does main do"]]
    assert len(vector) == 768


def test_batches_are_respected():
    embedder, model = make_embedder(batch_size=100)

    embedder.embed_documents(["chunk"] * 250)

    assert [len(call) for call in model.calls] == [100, 100, 50]


def test_embedding_text_prepends_path_header():
    chunk = Chunk(
        path="src/auth/session.py",
        language="python",
        symbol_kind="function",
        symbol_name="create_session",
        start_line=40,
        end_line=118,
        content="def create_session():\n    pass\n",
    )
    assert embedding_text(chunk) == (
        "src/auth/session.py:40-118\ndef create_session():\n    pass\n"
    )
