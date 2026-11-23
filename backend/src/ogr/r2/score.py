"""Deterministic fact-level partial-credit scorer for the PUBLIC questions (our own measurement).

The organisers' key is unknown; this is an approximation of "fact by fact with partial credit".

Method (also exposed as ACCURACY_METHOD):
* Status: gold not_in_corpus -> 1 iff prediction is not_in_corpus with a null/empty answer, else 0.
  Gold answered/partial with predicted not_in_corpus -> 0. answered<->partial mismatch keeps the
  content score but halves it.
* Gold answer -> atomic facts: every leaf of a string/number/list/dict (nested; keys are ignored
  for matching, nulls skipped), normalised with common.names.normalize_answer (case, accents,
  punctuation, number words/zeros; so NOC codes and numbers are canonical). A gold PROSE string
  (explanations) yields key facts instead: numbers, capitalised names/acronyms and a leading
  yes/no polarity. A leaf of more than 3 words counts as found when >=50% of its words appear
  (credit = fraction), otherwise a leaf must appear exactly.
* Prediction: JSON object/list (or a JSON string) is flattened the same way and scored by F1
  (recall over gold facts, precision over predicted leaves that match a gold fact). Free text is
  scored by recall only: a gold fact is present when its normalised form is a whole-word
  substring of the normalised text (numbers are whole tokens). Facts are compared as sets.
* Overall accuracy_pct = mean per-question score x 100.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ogr.common.names import normalize_answer

ACCURACY_METHOD = (
    "Own deterministic fact-level partial-credit scorer (ogr.r2.score): status must match "
    "(not_in_corpus only if predicted not_in_corpus with no answer); gold answers are flattened to atomic "
    "facts (normalised strings, numbers, list items, dict values; prose answers reduced to numbers, "
    "capitalised names and yes/no polarity); score = F1 against facts found in a structured prediction, "
    "or recall of facts present as whole-word matches in a free-text prediction; mean over questions."
)

_STOP_CAPS = {
    "the", "it", "he", "she", "they", "this", "that", "these", "those", "both", "no", "yes", "a", "an",
    "in", "on", "at", "of", "and", "but", "as", "his", "her", "its", "their", "there", "one", "two", "six",
    "competition", "because", "after", "before", "when", "while", "all", "only", "some", "any", "not",
}
_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_CAP = re.compile(r"[A-ZÀ-ÖØ-Þ][\w'’.\-]*(?:\s+[A-ZÀ-ÖØ-Þ][\w'’.\-]*)*")
_SOFT_WORDS = 3
_SOFT_MIN = 0.5


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return normalize_answer(str(value))
    if isinstance(value, float) and value == int(value):
        value = int(value)
    return normalize_answer(str(value))


def _leaves(value: Any) -> list[str]:
    """Normalised atomic leaves of a JSON-like value; nulls and empty leaves skipped."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [x for v in value.values() for x in _leaves(v)]
    if isinstance(value, (list, tuple)):
        return [x for v in value for x in _leaves(v)]
    n = _norm(value)
    return [n] if n else []


def _prose_facts(text: str) -> list[str]:
    facts: list[str] = []
    stripped = text.strip()
    lead = normalize_answer(stripped.split(maxsplit=1)[0]) if stripped else ""
    if lead in ("yes", "no"):
        facts.append(f"@polarity:{lead}")
    for m in _NUM.finditer(text):
        facts.append(_norm(m.group(0)))
    for m in _CAP.finditer(text):
        phrase = m.group(0).strip(" .,;:")
        words = phrase.split()
        while words and normalize_answer(words[0]) in _STOP_CAPS:
            words.pop(0)
        if not words:
            continue
        n = normalize_answer(" ".join(words))
        if n and not n.isdigit():
            facts.append(n)
    seen: list[str] = []
    for f in facts:
        if f not in seen:
            seen.append(f)
    return seen


def gold_facts(answer: Any) -> list[str]:
    if isinstance(answer, str):
        short = len(answer.split()) <= 6 and not re.search(r"[.!?]\s+\S", answer)
        return _leaves(answer) if short else _prose_facts(answer)
    seen: list[str] = []
    for f in _leaves(answer):
        if f not in seen:
            seen.append(f)
    return seen


def _contains(haystack: str, needle: str) -> bool:
    return bool(needle) and f" {needle} " in f" {haystack} "


def _credit(fact: str, text_norm: str, text_tokens: set[str], pred_first: str) -> float:
    if fact.startswith("@polarity:"):
        return 1.0 if pred_first == fact.split(":", 1)[1] else 0.0
    if _contains(text_norm, fact):
        return 1.0
    words = fact.split()
    if len(words) > _SOFT_WORDS:
        frac = sum(1 for w in words if w in text_tokens) / len(words)
        return frac if frac >= _SOFT_MIN else 0.0
    return 0.0


def _parse_structured(answer: Any) -> Any | None:
    if isinstance(answer, (dict, list)):
        return answer
    if isinstance(answer, str) and answer.strip()[:1] in "[{":
        try:
            parsed = json.loads(answer)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, (dict, list)) else None
    return None


def score_answer(gold_status: str, gold_answer: Any, pred_status: str, pred_answer: Any) -> float:
    empty = pred_answer in (None, "", [], {})
    if gold_status == "not_in_corpus":
        return 1.0 if pred_status == "not_in_corpus" and empty else 0.0
    if pred_status == "not_in_corpus" or empty:
        return 0.0
    facts = gold_facts(gold_answer)
    factor = 1.0 if pred_status == gold_status else 0.5
    if not facts:
        return factor
    structured = _parse_structured(pred_answer)
    if structured is not None:
        leaves = _leaves(structured)
        text_norm = " ; ".join(leaves)
        first = ""
    else:
        text = pred_answer if isinstance(pred_answer, str) else json.dumps(pred_answer, ensure_ascii=False)
        text_norm = normalize_answer(text)
        leaves = []
        first = text_norm.split(" ", 1)[0] if text_norm else ""
    tokens = set(text_norm.replace(" ; ", " ").split())
    recall = sum(_credit(f, text_norm, tokens, first) for f in facts) / len(facts)
    if structured is None:
        return factor * recall
    uniq = list(dict.fromkeys(leaves))
    if not uniq:
        return 0.0
    gold_set = [f for f in facts if not f.startswith("@")]
    hit = 0.0
    for leaf in uniq:
        ltoks = set(leaf.split())
        hit += max((_credit(g, leaf, ltoks, "") for g in gold_set), default=0.0)
    precision = min(1.0, hit / len(uniq))
    f1 = 0.0 if recall + precision == 0 else 2 * recall * precision / (recall + precision)
    return factor * f1


def score_set(gold: list[dict], preds: list[dict]) -> dict:
    """gold: question rows (qid, status, answer); preds: answer rows. Missing prediction scores 0."""
    by_qid = {p["qid"]: p for p in preds}
    per_q: dict[str, float] = {}
    for g in gold:
        p = by_qid.get(g["qid"])
        per_q[g["qid"]] = 0.0 if p is None else round(
            score_answer(g["status"], g.get("answer"), p.get("status", ""), p.get("answer")), 4)
    mean = sum(per_q.values()) / len(per_q) if per_q else 0.0
    return {"accuracy_pct": round(mean * 100, 1), "per_question": per_q, "method": ACCURACY_METHOD}
