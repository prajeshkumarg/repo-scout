"""Embedding: text to vectors, locally via fastembed.

The embedder sits behind a small protocol so tests can fake it and the
backend can be swapped (hosted APIs, other models) without touching
ingest or search. The model runs in-process over ONNX: no API key, no
per-request cost, no rate limits, and no network after the one-time
model download.

The default model is jina-embeddings-v2-base-code: trained on code
retrieval, 768 dimensions, matching the pgvector column.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from typing import Protocol

from fastembed import TextEmbedding

from chunking.chunker import Chunk

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """What ingest and search need from an embedding backend."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    def embed_query(self, text: str) -> list[float]: ...


def embedding_text(chunk: Chunk) -> str:
    """The text that gets embedded: a path:range header plus the content.

    The header names the file, so a query like "the auth middleware" can
    land on a chunk whose body never says the word auth. The content stays
    stored raw; only this composed text is embedded.
    """
    return f"{chunk.path}:{chunk.start_line}-{chunk.end_line}\n{chunk.content}"


class _Model(Protocol):
    """The slice of fastembed's TextEmbedding that we use."""

    def embed(self, documents: Iterable[str], **kwargs: object) -> Iterable[object]: ...


class LocalEmbedder:
    """Embeds chunks and queries with a local fastembed model.

    Chunks and queries go through the same model; fastembed models have
    no query/document asymmetry. The path header in `embedding_text` does
    the heavy lifting for file identity instead.
    """

    def __init__(
        self,
        model_name: str,
        batch_size: int = 100,
        model: _Model | None = None,
    ) -> None:
        # The first use downloads the ONNX weights (~0.6 GB) and caches
        # them; after that the model is fully offline.
        self._model = model if model is not None else TextEmbedding(model_name)
        self._batch_size = batch_size

    def embed_documents(
        self,
        texts: list[str],
        on_progress: Callable[[int, int], None] | None = None,
    ) -> list[list[float]]:
        """Embed every text, reporting (done, total) after each batch.

        Embedding is by far the longest stage, so its progress is the
        only one worth reporting as a fraction rather than a milestone.
        """
        vectors: list[list[float]] = []
        total = len(texts)
        for start in range(0, total, self._batch_size):
            batch = texts[start : start + self._batch_size]
            vectors.extend(self._embed(batch))
            done = start + len(batch)
            logger.info("[embed] %d/%d texts embedded", done, total)
            if on_progress is not None:
                on_progress(done, total)
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]

    def _embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.embed(texts)]
