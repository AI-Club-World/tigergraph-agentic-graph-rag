"""Answer normalization and multi-person name splitting.

Source spec: TECHNICAL-SPEC §9 · Plan: implementation-plan-UI.md Group 1 (EVAL-01)

Two pure functions, no LLM, no I/O — NFR-6 requires scoring be deterministic
and reproducible run-to-run for identical inputs.

SQuAD-style normalization: lowercase, strip punctuation, drop the articles
a/an/the, collapse whitespace — extended so a correct answer is not marked
wrong for its typography or number format: Unicode dashes and quotes and
every Unicode punctuation mark are treated as punctuation, accents are folded
("Sebastián" = "Sebastian"), and number words up to twenty become digits
with leading zeros dropped ("five" = "05" = "5").

Multi-person rule: 2 of the 100 public answers concatenate names (pub-015,
pub-099), and the corpus concatenates `gold` the same way. They are split on
lowercase->uppercase boundaries into a name set and scored as set overlap.
A predicted list is also split on the separators a model writes — commas,
semicolons, "and", "&" — so "A, B and C" is the same set as "ABC".

The prefix guard is the load-bearing part. The unguarded rule mis-splits
`Rosannagh MacLennan` (pub-067) into "Rosannagh Mac" + "Lennan", turning a
correct answer into a wrong one. Guarded prefixes: Mc, Mac, O', Di, De, Van,
Le, La.
"""

from __future__ import annotations

import re
import unicodedata

__all__ = ["normalize_answer", "split_multi_person", "split_names", "normalized_name_set", "tokenize"]

# Name particles that legitimately carry an internal capital. A lowercase->
# uppercase boundary immediately after one of these is part of the surname,
# not a join between two people.
GUARDED_PREFIXES: tuple[str, ...] = ("Mac", "Mc", "Van", "Di", "De", "Le", "La", "O'")

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_WHITESPACE = re.compile(r"\s+")
# A predicted list: "A, B and C", "A; B", "A & B" (a word "and", not a substring).
_LIST_SEPARATORS = re.compile(r"\s*(?:,|;|&|\band\b)\s*")
_NUMBER_WORDS = {
    w: str(i) for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
        "fifteen sixteen seventeen eighteen nineteen twenty".split()
    )
}


def _fold(text: str) -> str:
    """Accents off; every Unicode punctuation mark (–, —, ’, “ …) becomes a space."""
    decomposed = unicodedata.normalize("NFKD", text)
    chars = []
    for ch in decomposed:
        category = unicodedata.category(ch)
        if category == "Mn":
            continue  # a combining accent
        chars.append(" " if category.startswith("P") else ch)
    return "".join(chars)


def _canonical_token(token: str) -> str:
    token = _NUMBER_WORDS.get(token, token)
    if token.isdigit():
        return str(int(token))  # "05" -> "5"
    return token


def normalize_answer(text: str) -> str:
    """Lowercase, accents and punctuation off, no articles, canonical numbers, single spaces."""
    if not text:
        return ""
    # Apostrophes join a word ("Men's" -> "mens"); other punctuation separates.
    lowered = re.sub(r"['’ʼ`]", "", text.lower())
    without_articles = _ARTICLES.sub(" ", _fold(lowered))
    tokens = _WHITESPACE.sub(" ", without_articles).strip().split()
    return " ".join(_canonical_token(t) for t in tokens)


def tokenize(text: str) -> list[str]:
    """Normalized whitespace tokens over the answer's names, used for token F1.
    Concatenated names are split first, so "Dani KingLaura Trott" yields
    "dani king laura trott", not the non-word "kinglaura"."""
    return [token for name in split_names(text) for token in normalize_answer(name).split()]


def split_multi_person(text: str) -> list[str]:
    """Split a concatenated multi-person answer into individual names.

    Splits at each lowercase->uppercase boundary inside a word, unless the
    word so far ends in a guarded particle (Mac, Mc, Van, Di, De, Le, La, O').

        "Jane SmithJohn Doe"   -> ["Jane Smith", "John Doe"]
        "Rosannagh MacLennan"  -> ["Rosannagh MacLennan"]   # guard holds

    A string with no such boundary comes back as a single-element list, so
    callers can treat every answer as a name set uniformly.
    """
    if not text:
        return []

    pieces: list[str] = []
    start = 0
    word_start = 0

    for i in range(1, len(text)):
        previous, current = text[i - 1], text[i]

        if previous.isspace():
            word_start = i
        if not (previous.islower() and current.isupper()):
            continue

        # The fragment of the current word before this boundary decides it.
        fragment = text[max(word_start, start):i]
        if fragment.endswith(GUARDED_PREFIXES):
            continue

        pieces.append(text[start:i].strip())
        start = i
        word_start = i

    pieces.append(text[start:].strip())
    return [piece for piece in pieces if piece]


def split_names(text: str) -> list[str]:
    """The names in an answer: split on list separators, then on
    concatenation boundaries (`split_multi_person`)."""
    if not text:
        return []
    return [name for part in _LIST_SEPARATORS.split(text) for name in split_multi_person(part)]


def normalized_name_set(text: str) -> frozenset[str]:
    """Normalized set of names in an answer — the unit EM compares.

    A single-valued answer yields a one-element set, so the same comparison
    serves both the ordinary case and the concatenated-name case.
    """
    names = (normalize_answer(part) for part in split_names(text))
    return frozenset(name for name in names if name)
