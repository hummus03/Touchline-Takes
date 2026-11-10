"""Embedding providers: an offline hashed TF-IDF embedder and an optional hosted one."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

import numpy as np
import requests
from sklearn.feature_extraction.text import HashingVectorizer


class Embeddings(ABC):
    """Interface mirroring LangChain's ``Embeddings`` so it can be swapped in later."""

    name = "base"

    @abstractmethod
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of documents."""

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query."""
        return self.embed_documents([text])[0]


class HashingTfidfEmbeddings(Embeddings):
    """Offline, stateless TF-style embeddings via the hashing trick.

    Uses unigram+bigram term frequencies (sublinear, English stop words removed)
    hashed into a fixed number of dimensions and L2-normalised, so vectors are
    stable across runs and can live in a persistent vector store.
    """

    name = "tfidf-hashing"

    def __init__(self, n_features: int = 2048) -> None:
        self.n_features = n_features
        self._vectorizer = HashingVectorizer(
            n_features=n_features, alternate_sign=False, norm="l2", ngram_range=(1, 2),
            stop_words="english", lowercase=True, strip_accents="unicode")

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        matrix = self._vectorizer.transform(list(texts))
        matrix.data = np.log1p(matrix.data)  # sublinear tf
        dense = matrix.toarray()
        norms = np.linalg.norm(dense, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (dense / norms).tolist()


class OpenAIEmbeddings(Embeddings):
    """Hosted embeddings via any OpenAI-compatible ``/embeddings`` endpoint."""

    name = "openai"

    def __init__(self, api_key: str, model: str, base_url: str, timeout: float = 20.0,
                 session: requests.Session | None = None) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        resp = self.session.post(
            f"{self.base_url}/embeddings",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "input": list(texts)}, timeout=self.timeout)
        resp.raise_for_status()
        return [item["embedding"] for item in resp.json()["data"]]


def cosine_matrix(a: Sequence[Sequence[float]], b: Sequence[Sequence[float]]) -> np.ndarray:
    """Cosine similarity between every row of ``a`` and every row of ``b``."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    mat_a = np.asarray(a, dtype=float)
    mat_b = np.asarray(b, dtype=float)
    mat_a = mat_a / np.clip(np.linalg.norm(mat_a, axis=1, keepdims=True), 1e-12, None)
    mat_b = mat_b / np.clip(np.linalg.norm(mat_b, axis=1, keepdims=True), 1e-12, None)
    return mat_a @ mat_b.T


def build_embeddings(settings) -> Embeddings:
    """Pick the embeddings provider from settings, falling back to the offline one."""
    if settings.embeddings_provider == "openai" and settings.openai_api_key:
        return OpenAIEmbeddings(settings.openai_api_key, settings.embeddings_model,
                                settings.openai_base_url, settings.request_timeout)
    return HashingTfidfEmbeddings()
