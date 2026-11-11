"""Tests for the VGG16 photo tagger, its agent and the photo plumbing (all offline)."""
# pylint: disable=redefined-outer-name

import io
import sqlite3

import numpy as np
import pytest
from PIL import Image

from touchline_takes.agents.photo_tagger import ImageFetcher, ImageFetchError, PhotoTaggerAgent
from touchline_takes.config import DATA_DIR
from touchline_takes.db import Database
from touchline_takes.models.photo_tagger import (PhotoTagger, VGG16Backbone, colour_histogram,
                                                 load_folder, load_image, model_available,
                                                 vgg16_weights_cached)
from touchline_takes.state import NewsroomState
from touchline_takes.tools.feeds import parse_feed
from touchline_takes.tools.synthetic_photos import TAGS, make_photo, write_dataset

from tests.conftest import FakeResponse, FakeSession, make_story

SIZE = 32


class HistogramBackbone:
    """Cheap stand-in backbone (colour histograms) so head training is fast in tests."""

    name = "histogram"
    input_size = SIZE

    def features(self, images):
        """Colour-histogram features."""
        return colour_histogram(images, bins=4)


@pytest.fixture(scope="module")
def dataset(tmp_path_factory):
    """A tiny synthetic dataset on disk."""
    root = tmp_path_factory.mktemp("photos")
    write_dataset(root, per_tag=12, size=64)
    return load_folder(root, size=SIZE)


def jpeg_bytes(tag="crowd", seed=1, size=64) -> bytes:
    """Encode a synthetic photo as JPEG."""
    buffer = io.BytesIO()
    make_photo(tag, seed, size).save(buffer, format="JPEG")
    return buffer.getvalue()


def test_synthetic_photos_are_deterministic(dataset):
    """Same seed, same image; the dataset has every tag."""
    assert np.array_equal(np.asarray(make_photo("stadium", 3, 64)),
                          np.asarray(make_photo("stadium", 3, 64)))
    images, tags, paths = dataset
    assert images.shape == (48, SIZE, SIZE, 3) and sorted(set(tags)) == sorted(TAGS)
    assert all(p.endswith(".jpg") for p in paths)


def test_load_image_and_histogram():
    """Images are centre-cropped and resized; junk bytes are rejected."""
    wide = io.BytesIO()
    Image.new("RGB", (300, 100), (255, 0, 0)).save(wide, format="PNG")
    pixels = load_image(wide.getvalue(), size=SIZE)
    assert pixels.shape == (SIZE, SIZE, 3) and pixels[..., 0].min() == 255
    with pytest.raises(ValueError):
        load_image(b"not an image")
    hist = colour_histogram(pixels[None, ...], bins=4)
    assert hist.shape == (1, 64) and hist.sum() == pytest.approx(1.0)


def test_tagger_fit_tag_save_load(dataset, tmp_path):
    """The head trains, reports metrics vs baselines, tags images and round-trips to disk."""
    images, tags, _ = dataset
    tagger = PhotoTagger(HistogramBackbone())
    report = tagger.fit(images, tags, epochs=30)
    assert report["n_test"] == 12 and report["labels"] == sorted(TAGS)
    for key in ("transfer_vgg16", "baselines"):
        assert key in report
    assert report["transfer_vgg16"]["accuracy"] > report["baselines"]["majority_class"][
        "accuracy"]
    tagged = tagger.tag(images[:3], top_k=2, min_prob=0.0)
    assert len(tagged) == 3 and set(tagged[0][0]) == {"tag", "prob"}
    tagger.save(tmp_path / "model")
    assert model_available(tmp_path / "model")
    loaded = PhotoTagger.load(tmp_path / "model", backbone_factory=lambda _s: HistogramBackbone())
    assert np.allclose(loaded.predict_proba(images[:5]), tagger.predict_proba(images[:5]),
                       atol=1e-5)


def test_vgg16_architecture_offline(dataset, tmp_path):
    """Real VGG16 architecture (random weights, 32px): 512-d features and block5 fine-tuning."""
    images, tags, _ = dataset
    backbone = VGG16Backbone(weights=None, input_size=SIZE)
    assert backbone.features(images[:4]).shape == (4, 512)
    assert not backbone.base.trainable
    tagger = PhotoTagger(backbone)
    tagger.fit(images, tags, epochs=2)
    report = tagger.fine_tune(images, tags, epochs=1, head_epochs=2)
    assert "fine_tuned_block5" in report and tagger.finetuned is not None
    trainable = {w.path.split("/")[0] for w in tagger.finetuned.trainable_weights}
    assert any("block5" in str(w.path) for w in tagger.finetuned.trainable_weights)
    assert not any("block1" in str(w.path) for w in tagger.finetuned.trainable_weights)
    assert trainable  # head + block5 only
    assert backbone.features(images[:1]).shape == (1, 512)  # shared extractor untouched
    tagger.save(tmp_path / "ft")
    loaded = PhotoTagger.load(tmp_path / "ft",
                              backbone_factory=lambda s: VGG16Backbone(weights=None, input_size=s))
    assert loaded.finetuned is not None
    assert np.allclose(loaded.predict_proba(images[:2]), tagger.predict_proba(images[:2]),
                       atol=1e-4)


@pytest.mark.skipif(not vgg16_weights_cached(), reason="ImageNet VGG16 weights not cached")
def test_imagenet_vgg16_beats_majority(tmp_path):
    """With the real ImageNet weights, transfer learning beats the majority baseline."""
    write_dataset(tmp_path, per_tag=8, size=128, seed=11)
    images, tags, _ = load_folder(tmp_path, size=128)
    report = PhotoTagger(VGG16Backbone("imagenet", input_size=128)).fit(images, tags, epochs=40)
    assert report["transfer_vgg16"]["accuracy"] > report["baselines"]["majority_class"][
        "accuracy"]


def test_image_fetcher():
    """HTTP photos are size- and type-checked; local paths can't escape the sample folder."""
    session = FakeSession({
        "ok.jpg": FakeResponse(content=jpeg_bytes(), headers={"Content-Type": "image/jpeg"}),
        "page": FakeResponse(text="<html>", headers={"Content-Type": "text/html"}),
        "huge": FakeResponse(content=b"x" * (6 * 1024 * 1024),
                             headers={"Content-Type": "image/jpeg"})})
    fetcher = ImageFetcher(str(DATA_DIR), session=session)
    assert fetcher.fetch("https://img.test/ok.jpg").startswith(b"\xff\xd8")
    for bad in ("https://img.test/page", "https://img.test/huge", "ftp://x/y.jpg",
                "../README.md", "sample_photos/missing.jpg", "https://img.test/404"):
        with pytest.raises(ImageFetchError):
            fetcher.fetch(bad)
    assert fetcher.fetch("sample_photos/brighton-var-row.jpg")


class StubTagger:
    """Tagger double: everything is a crowd."""

    class backbone:  # pylint: disable=invalid-name,too-few-public-methods
        """Backbone double."""

        input_size = SIZE

    @staticmethod
    def tag(images):
        """One tag list per image."""
        return [[{"tag": "crowd", "prob": 0.9}] for _ in images]


def test_photo_tagger_agent(db):
    """Stories with photos get tags; failures are logged; no model means a clean skip."""
    good = make_story(1, image_url="sample_photos/brighton-var-row.jpg")
    broken = make_story(2, image_url="sample_photos/nope.jpg")
    plain = make_story(3)
    for story in (good, broken, plain):
        db.insert_story(story)
    fetcher = ImageFetcher(str(DATA_DIR))
    state = PhotoTaggerAgent(db, fetcher, StubTagger).run(
        NewsroomState(stories=[good, broken, plain]))
    assert state.metrics["photo_tagger"] == {"candidates": 2, "tagged": 1, "failed": 1}
    assert db.get_story(good.id).image_tags == [{"tag": "crowd", "prob": 0.9}]
    assert any(log.action == "photo_error" for log in state.logs)
    skipped = PhotoTaggerAgent(db, fetcher, lambda: None).run(NewsroomState(stories=[broken]))
    assert skipped.metrics["photo_tagger"]["skipped"] == "no trained photo model"


def test_feed_photo_url_and_db_migration(tmp_path):
    """media:thumbnail is captured at ingest; old databases gain the photo columns."""
    rss = ('<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">'
           '<channel><title>W</title><item><title>T</title><link>https://x.test/1</link>'
           '<media:thumbnail url="https://img.test/1.jpg" width="240"/></item></channel></rss>')
    assert parse_feed(rss)[0].image_url == "https://img.test/1.jpg"
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE stories (id TEXT PRIMARY KEY, title TEXT NOT NULL, summary TEXT "
                 "NOT NULL, url TEXT UNIQUE, source TEXT, published TEXT, body TEXT DEFAULT '', "
                 "league TEXT, teams TEXT DEFAULT '[]', topic TEXT, sentiment TEXT, "
                 "sentiment_score REAL DEFAULT 0, emotion TEXT, classified INTEGER DEFAULT 0, "
                 "used INTEGER DEFAULT 0, ingested_at TEXT)")
    conn.commit()
    conn.close()
    database = Database(str(path))
    database.insert_story(make_story(9, image_url="https://img.test/9.jpg"))
    assert database.untagged_photo_stories()[0].image_url == "https://img.test/9.jpg"
