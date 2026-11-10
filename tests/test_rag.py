"""Tests for the RAG research tools."""

import pytest

from touchline_takes.config import Settings
from touchline_takes.tools.embeddings import HashingTfidfEmbeddings, build_embeddings
from touchline_takes.tools.feeds import FeedClient
from touchline_takes.tools.llm import FakeLLM
from touchline_takes.tools.rag import (ChromaVectorStore, Document, InMemoryVectorStore,
                                       ResearchIndex, SentenceTextSplitter, StoryLoader,
                                       build_vector_store)


@pytest.fixture(scope="module")
def stories():
    """Bundled sample stories."""
    return FeedClient(Settings().sample_feed_dir).load_samples()


def test_loader_and_splitter(stories):
    """Documents carry metadata; the splitter respects chunk size and overlaps."""
    docs = StoryLoader(stories[:1]).load()
    assert docs[0].metadata["url"] == stories[0].url
    splitter = SentenceTextSplitter(chunk_size=60, chunk_overlap=1)
    chunks = splitter.split_documents([Document("One two three. Four five six. Seven eight "
                                                "nine ten eleven twelve. Thirteen.", {"a": 1})])
    assert len(chunks) >= 2 and chunks[0].metadata == {"a": 1, "chunk": 0}
    assert chunks[1].page_content.startswith("Four five six.")


def test_embeddings_are_stable_and_normalised():
    """Same text, same vector; unit length."""
    emb = HashingTfidfEmbeddings()
    a, b = emb.embed_documents(["Arsenal win", "Arsenal win"])
    assert a == b and abs(sum(x * x for x in a) - 1) < 1e-9
    assert isinstance(build_embeddings(Settings()), HashingTfidfEmbeddings)


@pytest.mark.parametrize("store_factory", [
    InMemoryVectorStore, lambda: ChromaVectorStore(None, "test_collection")])
def test_index_retrieve_and_answer(stories, store_factory):
    """Indexing is incremental; retrieval and extractive QA find the right story."""
    index = ResearchIndex(store_factory(), HashingTfidfEmbeddings())
    assert index.index_stories(stories) > 0
    assert index.index_stories(stories) == 0
    answer = index.ask("How long is the Aston Villa captain ruled out for?")
    assert answer.mode == "extractive" and "six weeks" in answer.answer
    assert "villa" in answer.sources[0]["url"]
    assert index.ask("What is the capital of quantum chromodynamics?").mode == "none"
    related = index.related("Liverpool Everton derby", k=2)
    assert related and "Liverpool" in related[0]["title"]


def test_persistent_chroma(tmp_path, stories):
    """The Chroma store persists between instances."""
    first = ResearchIndex(ChromaVectorStore(str(tmp_path)), HashingTfidfEmbeddings())
    added = first.index_stories(stories)
    second = ResearchIndex(ChromaVectorStore(str(tmp_path)), HashingTfidfEmbeddings())
    assert len(second.store.ids()) == added
    settings = Settings(vector_store="chroma", chroma_dir=str(tmp_path / "x"))
    assert isinstance(build_vector_store(settings, HashingTfidfEmbeddings()), ChromaVectorStore)


def test_qa_with_llm(stories):
    """With an LLM configured, the answer comes from the model with sources attached."""
    llm = FakeLLM(["Six weeks, per [1]."])
    index = ResearchIndex(InMemoryVectorStore(), HashingTfidfEmbeddings(), llm=llm)
    index.index_stories(stories)
    answer = index.ask("Aston Villa captain injury")
    assert answer.mode == "llm" and answer.answer == "Six weeks, per [1]."
    assert "CONTEXT:" in llm.calls[0]["prompt"] and answer.sources
