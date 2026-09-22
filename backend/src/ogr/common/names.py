"""Answer normalization and multi-person name splitting.

Source spec: TECHNICAL-SPEC §9 · Plan: implementation-plan-UI.md Group 1 (EVAL-01)

Two pure functions, no LLM, no I/O — NFR-6 requires scoring be deterministic
and reproducible run-to-run for identical inputs.

SQuAD-style normalization: lowercase, strip punctuation, drop the articles
a/an/the, collapse whitespace.

Multi-person rule: 2 of the 100 public answers concatenate names (pub-015,
pub-099), and the corpus concatenates `gold` the same way. They are split on
lowercase->uppercase boundaries into a name set and scored as set overlap.

The prefix guard is the load-bearing part. The unguarded rule mis-splits
`Rosannagh MacLennan` (pub-067) into "Rosannagh Mac" + "Lennan", turning a
correct answer into a wrong one. Guarded prefixes: Mc, Mac, O', Di, De, Van,
Le, La.
"""

from __future__ import annotations

import re
import string

__all__ = ["normalize_answer", "split_multi_person", "normalized_name_set", "tokenize"]

# Name particles that legitimately carry an internal capital. A lowercase->
# uppercase boundary immediately after one of these is part of the surname,
# not a join between two people.
GUARDED_PREFIXES: tuple[str, ...] = ("Mac", "Mc", "Van", "Di", "De", "Le", "La", "O'")

_ARTICLES = re.compile(r"\b(a|an|the)\b")
_WHITESPACE = re.compile(r"\s+")
_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


def normalize_answer(text: str) -> str:
    """SQuAD-style normalization: lowercase, no punctuation, no articles, single spaces."""
    if not text:
        return ""
    lowered = text.lower()
    without_articles = _ARTICLES.sub(" ", lowered)
    without_punct = without_articles.translate(_PUNCT_TABLE)
    return _WHITESPACE.sub(" ", without_punct).strip()


def tokenize(text: str) -> list[str]:
    """Normalized whitespace tokens, used for token F1."""
    normalized = normalize_answer(text)
    return normalized.split() if normalized else []


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


def normalized_name_set(text: str) -> frozenset[str]:
    """Normalized set of names in an answer — the unit EM compares.

    A single-valued answer yields a one-element set, so the same comparison
    serves both the ordinary case and the concatenated-name case.
    """
    return frozenset(
        normalized
        for normalized in (normalize_answer(part) for part in split_multi_person(text))
        if normalized
    )
