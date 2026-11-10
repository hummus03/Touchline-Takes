"""Research tools (RAG): loader -> splitter -> embeddings -> vector store -> retriever -> QA.

The pieces mirror LangChain's abstractions (``Document``, text splitter,
``VectorStore``, retriever, QA chain) without the dependency, so swapping in
``langchain_chroma.Chroma`` and a LangChain retrieval chain later is mechanical.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from touchline_takes.state import Story
from touchline_takes.tools.embeddings import Embeddings, cosine_matrix
from touchline_takes.tools.llm import LLMClient, LLMError
from touchline_takes.tools.text import split_sentences

LOGGER = logging.getLogger(__name__)


@dataclass
class Document:
    """A chunk of text plus metadata."""

    page_content: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------- loader
class StoryLoader:
    """Turns stored stories into documents."""

    def __init__(self, stories: Iterable[Story]) -> None:
        self.stories = list(stories)

    def load(self) -> list[Document]:
        """One document per story."""
        return [Document(f"{s.title}. {s.summary} {s.body}".strip(), {
            "story_id": s.id, "title": s.title, "source": s.source, "url": s.url,
            "published": s.published, "league": s.league or "",
            "teams": ", ".join(s.teams)}) for s in self.stories]


# ----------------------------------------------------------------------- splitter
class SentenceTextSplitter:
    """Packs whole sentences into chunks of at most ``chunk_size`` characters with overlap."""

    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 1) -> None:
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap  # sentences carried into the next chunk

    def split_text(self, text: str) -> list[str]:
        """Split one text."""
        sentences = split_sentences(text)
        chunks, current = [], []
        for sentence in sentences:
            if current and len(" ".join(current + [sentence])) > self.chunk_size:
                chunks.append(" ".join(current))
                current = current[-self.chunk_overlap:] if self.chunk_overlap else []
            current.append(sentence)
        if current:
            chunks.append(" ".join(current))
        return chunks

    def split_documents(self, docs: Iterable[Document]) -> list[Document]:
        """Split documents, tagging each chunk with its index."""
        out = []
        for doc in docs:
            for i, chunk in enumerate(self.split_text(doc.page_content)):
                out.append(Document(chunk, {**doc.metadata, "chunk": i}))
        return out


# ----------------------------------------------------------------------- stores
class VectorStore(ABC):
    """Minimal vector store interface."""

    @abstractmethod
    def add(self, ids: list[str], docs: list[Document], vectors: list[list[float]]) -> None:
        """Add (or overwrite) documents."""

    @abstractmethod
    def query(self, vector: list[float], k: int) -> list[tuple[Document, float]]:
        """Top-``k`` documents by cosine similarity."""

    @abstractmethod
    def ids(self) -> set[str]:
        """Stored ids."""


class InMemoryVectorStore(VectorStore):
    """Numpy-backed store (tests, or when Chroma is unavailable)."""

    def __init__(self) -> None:
        self._ids: list[str] = []
        self._docs: list[Document] = []
        self._vecs: list[list[float]] = []

    def add(self, ids, docs, vectors):
        for id_, doc, vec in zip(ids, docs, vectors):
            if id_ in self._ids:
                idx = self._ids.index(id_)
                self._docs[idx], self._vecs[idx] = doc, vec
            else:
                self._ids.append(id_)
                self._docs.append(doc)
                self._vecs.append(vec)

    def query(self, vector, k):
        if not self._vecs:
            return []
        sims = cosine_matrix([vector], self._vecs)[0]
        order = np.argsort(-sims)[:k]
        return [(self._docs[i], float(sims[i])) for i in order]

    def ids(self):
        return set(self._ids)


class ChromaVectorStore(VectorStore):
    """Persistent Chroma collection; embeddings are supplied by us (no model downloads)."""

    def __init__(self, persist_dir: str | None, collection: str = "touchline_takes") -> None:
        import chromadb  # pylint: disable=import-outside-toplevel
        from chromadb.config import Settings as ChromaSettings  # pylint: disable=import-outside-toplevel

        chroma_settings = ChromaSettings(anonymized_telemetry=False)
        if persist_dir:
            self.client = chromadb.PersistentClient(path=persist_dir, settings=chroma_settings)
        else:
            self.client = chromadb.EphemeralClient(settings=chroma_settings)
        self.collection = self.client.get_or_create_collection(
            collection, embedding_function=None, metadata={"hnsw:space": "cosine"})

    def add(self, ids, docs, vectors):
        if not ids:
            return
        self.collection.upsert(ids=ids, embeddings=vectors,
                               documents=[d.page_content for d in docs],
                               metadatas=[{k: v for k, v in d.metadata.items()
                                           if isinstance(v, (str, int, float, bool))}
                                          for d in docs])

    def query(self, vector, k):
        count = self.collection.count()
        if not count:
            return []
        res = self.collection.query(query_embeddings=[vector], n_results=min(k, count),
                                    include=["documents", "metadatas", "distances"])
        return [(Document(doc, dict(meta or {})), 1.0 - float(dist)) for doc, meta, dist in zip(
            res["documents"][0], res["metadatas"][0], res["distances"][0])]

    def ids(self):
        return set(self.collection.get(include=[])["ids"])


# ----------------------------------------------------------------------- retriever
class Retriever:
    """Embeds a query and returns the most similar chunks."""

    def __init__(self, store: VectorStore, embeddings: Embeddings, k: int = 4,
                 min_score: float = 0.05) -> None:
        self.store = store
        self.embeddings = embeddings
        self.k = k
        self.min_score = min_score

    def get_relevant_documents(self, query: str, k: int | None = None
                               ) -> list[tuple[Document, float]]:
        """Chunks scoring above ``min_score``."""
        hits = self.store.query(self.embeddings.embed_query(query), k or self.k)
        return [(d, s) for d, s in hits if s >= self.min_score]


# ----------------------------------------------------------------------- QA chain
@dataclass
class Answer:
    """A grounded answer with its sources."""

    answer: str
    sources: list[dict[str, str]]
    mode: str


class QAChain:
    """Retrieval QA: LLM-written answer when configured, extractive answer otherwise."""

    SYSTEM = ("You answer questions for Touchline Takes readers using ONLY the numbered "
              "context. Cite context numbers like [1]. If the context does not contain the "
              "answer, say you don't know. Keep it under 120 words, punchy but accurate.")
    NOT_FOUND = "Nothing in the Touchline Takes archive covers that yet. Try another question."

    def __init__(self, retriever: Retriever, llm: LLMClient | None = None) -> None:
        self.retriever = retriever
        self.llm = llm

    @staticmethod
    def _sources(hits: list[tuple[Document, float]]) -> list[dict[str, str]]:
        seen, out = set(), []
        for doc, _ in hits:
            key = doc.metadata.get("url") or doc.metadata.get("title")
            if key not in seen:
                seen.add(key)
                out.append({"title": doc.metadata.get("title", ""),
                            "source": doc.metadata.get("source", ""),
                            "url": doc.metadata.get("url", "")})
        return out

    def _extractive(self, question: str, hits: list[tuple[Document, float]]) -> str | None:
        sentences, refs, weights, seen = [], [], [], set()
        for i, (doc, score) in enumerate(hits, start=1):
            for sentence in split_sentences(doc.page_content):
                key = re.sub(r"\W+", " ", sentence.lower()).strip()
                if key in seen:
                    continue
                seen.add(key)
                sentences.append(sentence)
                refs.append(i)
                weights.append(score)
        if not sentences:
            return None
        # Sum of IDF weights of question terms present in each sentence (rare terms
        # such as "winner" outweigh names repeated across every sentence).
        vec = TfidfVectorizer(stop_words="english", binary=True, norm=None).fit(
            sentences + [question])
        query = vec.transform([question])
        query.data[:] = 1.0
        overlap = (vec.transform(sentences) @ query.T).toarray().ravel()
        sims = overlap * np.asarray(weights) / max(weights)
        best = [i for i in np.argsort(-sims, kind="stable")[:3] if overlap[i] > 1.0]
        if not best:
            return None
        picked = sorted(best)
        return "From our archive: " + " ".join(
            f"{sentences[i]} [{refs[i]}]" for i in picked)

    def ask(self, question: str) -> Answer:
        """Answer ``question`` from stored coverage."""
        question = re.sub(r"\s+", " ", question or "").strip()[:300]
        if not question:
            return Answer("Ask a football question first.", [], "empty")
        hits = self.retriever.get_relevant_documents(question)
        if not hits:
            return Answer(self.NOT_FOUND, [], "none")
        if self.llm is not None:
            context = "\n".join(f"[{i}] {d.page_content}" for i, (d, _) in enumerate(hits, 1))
            try:
                resp = self.llm.complete(f"CONTEXT:\n{context}\n\nQUESTION: {question}",
                                         self.SYSTEM, max_tokens=400)
                return Answer(resp.text, self._sources(hits), "llm")
            except LLMError as exc:
                LOGGER.warning("QA LLM failed, using extractive answer: %s", exc)
        text = self._extractive(question, hits)
        if not text:
            return Answer(self.NOT_FOUND, [], "none")
        return Answer(text, self._sources(hits), "extractive")


# ----------------------------------------------------------------------- facade
class ResearchIndex:
    """Keeps the vector store in sync with stored stories and serves the Writer and /ask."""

    def __init__(self, store: VectorStore, embeddings: Embeddings,
                 splitter: SentenceTextSplitter | None = None, llm: LLMClient | None = None
                 ) -> None:
        self.store = store
        self.embeddings = embeddings
        self.splitter = splitter or SentenceTextSplitter()
        self.retriever = Retriever(store, embeddings)
        self.qa = QAChain(self.retriever, llm)

    def index_stories(self, stories: Iterable[Story]) -> int:
        """Embed and store stories that are not indexed yet; returns chunks added."""
        known = self.store.ids()
        chunks = self.splitter.split_documents(StoryLoader(stories).load())
        new = [(f"{c.metadata['story_id']}:{c.metadata['chunk']}", c) for c in chunks]
        new = [(i, c) for i, c in new if i not in known]
        if not new:
            return 0
        vectors = self.embeddings.embed_documents([c.page_content for _, c in new])
        self.store.add([i for i, _ in new], [c for _, c in new], vectors)
        return len(new)

    def related(self, query: str, k: int = 3, exclude_ids: tuple[str, ...] = ()
                ) -> list[dict[str, Any]]:
        """Distinct stories related to ``query`` (for the Writer)."""
        out, seen = [], set(exclude_ids)
        for doc, score in self.retriever.get_relevant_documents(query, k=k * 4):
            sid = doc.metadata.get("story_id")
            if sid in seen or score < 0.12:
                continue
            seen.add(sid)
            out.append({"story_id": sid, "title": doc.metadata.get("title", ""),
                        "source": doc.metadata.get("source", ""),
                        "url": doc.metadata.get("url", ""), "score": score,
                        "text": doc.page_content})
            if len(out) >= k:
                break
        return out

    def ask(self, question: str) -> Answer:
        """Visitor Q&A."""
        return self.qa.ask(question)


def build_vector_store(settings, embeddings: Embeddings) -> VectorStore:
    """Chroma if configured and importable, otherwise in-memory."""
    if settings.vector_store == "chroma":
        try:
            return ChromaVectorStore(settings.chroma_dir, f"stories_{embeddings.name}".replace(
                "-", "_"))
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.warning("Chroma unavailable (%s); using in-memory vector store", exc)
    return InMemoryVectorStore()
