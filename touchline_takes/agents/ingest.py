"""Ingest agent: pull feeds, normalise, dedupe by embedding similarity, store."""

from __future__ import annotations

from touchline_takes.agents.base import Agent
from touchline_takes.db import Database
from touchline_takes.state import NewsroomState, Story
from touchline_takes.tools.embeddings import Embeddings, cosine_matrix
from touchline_takes.tools.feeds import FeedClient, skip_reason


class IngestAgent(Agent):
    """Fetches RSS stories and stores the genuinely new ones."""

    name = "ingest"

    def __init__(self, db: Database, feeds: FeedClient, embeddings: Embeddings,
                 feed_urls: list[str], threshold: float = 0.8, offline: bool = False,
                 history: int = 300, allow_fallback: bool = True) -> None:
        super().__init__()
        self.db = db
        self.feeds = feeds
        self.embeddings = embeddings
        self.feed_urls = feed_urls
        self.threshold = threshold
        self.offline = offline
        self.history = history
        self.allow_fallback = allow_fallback

    def dedupe(self, candidates: list[Story], existing: list[Story]
               ) -> tuple[list[Story], list[tuple[Story, Story, float]]]:
        """Split ``candidates`` into unique stories and (dup, original, score) triples."""
        if not candidates:
            return [], []
        cand_vecs = self.embeddings.embed_documents([s.text for s in candidates])
        pool: list[Story] = list(existing)
        pool_vecs = self.embeddings.embed_documents([s.text for s in pool]) if pool else []
        unique: list[Story] = []
        duplicates: list[tuple[Story, Story, float]] = []
        for story, vec in zip(candidates, cand_vecs):
            if pool_vecs:
                sims = cosine_matrix([vec], pool_vecs)[0]
                best = int(sims.argmax())
                if sims[best] >= self.threshold:
                    duplicates.append((story, pool[best], float(sims[best])))
                    continue
            unique.append(story)
            pool.append(story)
            pool_vecs = list(pool_vecs) + [vec]
        return unique, duplicates

    def run(self, state: NewsroomState) -> NewsroomState:
        result = self.feeds.fetch_all(self.feed_urls, offline=self.offline,
                                      allow_fallback=self.allow_fallback)
        for err in result.errors:
            self.log(state, "feed_error", err)
        if result.used_fallback:
            self.log(state, "fallback", "using bundled sample feeds")
        elif not result.stories and result.errors:
            self.log(state, "no_stories", "every feed failed and sample fallback is disabled")
        fetched = result.stories
        seen_urls: set[str] = set()
        fresh = []
        skipped = 0
        for story in fetched:
            if story.url in seen_urls or self.db.story_url_exists(story.url):
                continue
            reason = skip_reason(story)
            if reason:
                seen_urls.add(story.url)
                skipped += 1
                self.log(state, "skipped", f"{reason}: {story.source}: {story.title}", story.id)
                continue
            seen_urls.add(story.url)
            fresh.append(story)
        unique, duplicates = self.dedupe(fresh, self.db.recent_stories(self.history))
        for dup, original, score in duplicates:
            self.log(state, "duplicate", f"near-duplicate of {original.id} "
                     f"({score:.2f}): {dup.title}", dup.id)
        for story in unique:
            if self.db.insert_story(story):
                state.new_stories.append(story)
                self.log(state, "stored", f"{story.source}: {story.title}", story.id)
        state.metrics["ingest"] = {
            "fetched": len(fetched), "new": len(state.new_stories),
            "duplicates": len(duplicates), "skipped": skipped, "fallback": result.used_fallback}
        return state
