"""Text utilities shared by the Writer, Fact-checker and Editor."""

from __future__ import annotations

import html
import re
import unicodedata

CITATION_RE = re.compile(r"\[([A-Z]{1,2}\d{1,2})\]")
QUOTE_RE = re.compile(r"[\"“”][^\"“”]*[\"“”]")
TAG_RE = re.compile(r"<[^>]+>")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"“(])")
WORD_RE = re.compile(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’\-]*|\d+(?:\.\d+)?")
NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")

# Capitalised words that do not, on their own, make a sentence a factual claim.
COMMON_CAPS = frozenset("""
a an and as at but by for from here how i if in it it's its let more most no not now of on or
our so still that that's the their there these they this those to we what when where who why
with yet you your expect verdict touchline takes take source sources according per meanwhile
elsewhere also plus both either neither whatever whoever nobody everyone anyone
one few many much some all any every each until unless while though although even only just
football fans form momentum pressure confidence numbers data history patience nothing everything
results matches games seasons things truth question questions answer reality mood time
every expect credit make give call look think forget remember imagine honestly frankly
sometimes maybe perhaps somebody well sure fair worse better big huge trust watch talk
""".split())


def strip_html(text: str) -> str:
    """Remove tags/entities and collapse whitespace."""
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _open_quote(text: str) -> bool:
    """True if ``text`` ends inside a quotation (curly or straight double quotes)."""
    return text.count("“") > text.count("”") or text.count('"') % 2 == 1


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences (keeps citation markers attached).

    Never splits inside a quotation, so a quoted headline such as
    "“Emery... or Carrick? Man Utd's options”" stays one sentence.
    """
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    out: list[str] = []
    for piece in (s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()):
        if out and _open_quote(out[-1]):
            out[-1] = f"{out[-1]} {piece}"
        else:
            out.append(piece)
    return out


def split_paragraphs(text: str) -> list[str]:
    """Split on blank lines."""
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def citations(sentence: str) -> list[str]:
    """Evidence ids cited in a sentence, e.g. ``[S1]`` -> ``S1``."""
    return CITATION_RE.findall(sentence)


def strip_citations(text: str) -> str:
    """Remove ``[S1]``-style markers."""
    return re.sub(r"\s+([.,;:!?])", r"\1", CITATION_RE.sub("", text)).strip()


def normalise_token(token: str) -> str:
    """Lowercase, strip accents/possessives so 'Atlético's' matches 'atletico'."""
    token = unicodedata.normalize("NFKD", token).encode("ascii", "ignore").decode("ascii")
    token = token.lower().strip("'’-")
    if token.endswith("'s") or token.endswith("’s"):
        token = token[:-2]
    return token


def word_tokens(text: str) -> set[str]:
    """Normalised word/number tokens of ``text``."""
    return {normalise_token(t) for t in WORD_RE.findall(text or "")} - {""}


def factual_tokens(sentence: str) -> list[str]:
    """Tokens that make a sentence a checkable claim: numbers and proper nouns.

    Opinion lines ("That is the kind of win that changes a dressing room.")
    have none and are treated as commentary rather than claims.
    """
    clean = strip_citations(sentence)
    tokens: list[str] = []
    for raw in WORD_RE.findall(clean):
        if NUMBER_RE.fullmatch(raw):
            tokens.append(raw)
        elif raw[0].isupper():
            norm = normalise_token(raw)
            if norm and norm not in COMMON_CAPS:
                tokens.append(norm)
    return tokens


def is_claim(sentence: str) -> bool:
    """True if the sentence asserts something checkable (or cites evidence)."""
    return bool(factual_tokens(sentence) or citations(sentence))


def without_quotes(text: str) -> str:
    """Drop quoted passages (attributed quotes are allowed to match sources verbatim)."""
    return QUOTE_RE.sub(" ", text or "")


def shared_ngram(a: str, b: str, n: int = 10) -> str | None:
    """Return the first ``n``-word sequence shared by ``a`` and ``b`` (copy detection)."""
    words_a = [normalise_token(w) for w in WORD_RE.findall(a)]
    words_b = [normalise_token(w) for w in WORD_RE.findall(b)]
    if len(words_a) < n or len(words_b) < n:
        return None
    grams_b = {tuple(words_b[i:i + n]) for i in range(len(words_b) - n + 1)}
    for i in range(len(words_a) - n + 1):
        gram = tuple(words_a[i:i + n])
        if gram in grams_b:
            return " ".join(gram)
    return None


def word_count(text: str) -> int:
    """Words in ``text`` ignoring citation markers."""
    return len(WORD_RE.findall(strip_citations(text)))


def slugify(text: str, max_len: int = 70) -> str:
    """URL-safe slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text[:max_len].rstrip("-") or "take"
