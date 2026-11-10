"""Tests for text helpers."""

from touchline_takes.tools import text


def test_split_sentences_keeps_citations():
    """Citation markers stay with their sentence."""
    out = text.split_sentences("Arsenal won 2-1 [S1]. That changes everything. Next up: Spurs.")
    assert out == ["Arsenal won 2-1 [S1].", "That changes everything.", "Next up: Spurs."]


def test_factual_tokens_and_claims():
    """Numbers and proper nouns are claims; pure opinion is not."""
    assert text.factual_tokens("Arsenal won 2-1 at the Emirates [S1].") == [
        "arsenal", "2", "1", "emirates"]
    assert not text.is_claim("That is the kind of win that changes a dressing room.")
    assert text.is_claim("It was a rout [S2].")


def test_normalise_token_strips_accents_and_possessive():
    """Accents and possessives normalise away."""
    assert text.normalise_token("Atlético's") == "atletico"


def test_shared_ngram_detects_copying():
    """Long shared word runs are detected, short ones are not."""
    src = "Arsenal came from behind to beat Chelsea 2-1 at the Emirates on Saturday afternoon"
    assert text.shared_ngram("Today Arsenal came from behind to beat Chelsea 2-1 at the "
                             "Emirates on Saturday", src, n=10)
    assert text.shared_ngram("Arsenal beat Chelsea", src, n=10) is None


def test_slugify_and_strip_html():
    """Slugs are URL-safe; HTML is stripped."""
    assert text.slugify("Arsenal v Chelsea: the Touchline Take!") == (
        "arsenal-v-chelsea-the-touchline-take")
    assert text.strip_html("<p>Hello&nbsp;<b>world</b></p>") == "Hello world"
    assert text.word_count("Arsenal won [S1].") == 2
