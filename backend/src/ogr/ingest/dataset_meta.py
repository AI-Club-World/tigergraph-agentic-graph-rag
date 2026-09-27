"""Human-readable dataset names — a dataset's id is its file stem
(`data/corpus/<id>.jsonl`), which says little when every upload is called
`corpus.jsonl`.

The display title is resolved, first match wins:

1. `given`    — a title the user typed on upload or rename, stored in the
                sidecar `data/corpus/<id>.meta.json`.
2. `declared` — a dataset-level field the records themselves carry
                (`dataset`, `collection` or `corpus`) with one value in most of them.
3. `inferred` — from the content: the dominant URL source (e.g. Wikipedia),
                the term most document titles share (e.g. "Olympics") and
                the span of years in the titles.
4. `file`     — the file stem.

Scanning a large corpus is not free, so the result (with the document count)
is cached in memory per file version (mtime + size).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

MAX_TITLE = 80
DECLARED_FIELDS = ("dataset", "collection", "corpus")
# A term must appear in this share of titles to name the dataset.
MIN_TOPIC_SHARE = 0.3
# Title words that never name a topic on their own.
_STOP = frozenset(
    "a an and at by de for from in is it la le of on or the to vs with list men's women's mixed "
    "team individual season kg metre metres km m".split()
)
_WORD = re.compile(r"[^\W\d_][\w'’.&-]*", re.UNICODE)
# A 4-digit number followed by a unit is a distance, not a year (1500 metres).
_YEAR = re.compile(r"\b(1[5-9]\d\d|20\d\d)\b(?!\s*(?:m|km|metres?|meters?|yards?|miles?)\b)", re.IGNORECASE)
_HOST = re.compile(r"^https?://(?:www\.)?([^/:]+)", re.IGNORECASE)
_KNOWN_HOSTS = {"wikipedia.org": "Wikipedia", "arxiv.org": "arXiv", "github.com": "GitHub"}

_cache: dict[tuple[str, int, int], dict[str, Any]] = {}


def meta_path(corpus: Path) -> Path:
    return corpus.with_name(f"{corpus.stem}.meta.json")


def read_meta(corpus: Path) -> dict[str, Any]:
    path = meta_path(corpus)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_meta(corpus: Path, *, replace: bool = False, **fields: Any) -> dict[str, Any]:
    """Merge `fields` into the sidecar (a None value leaves a field as it is),
    or with `replace` store exactly `fields` (a None value drops it)."""
    base = {} if replace else read_meta(corpus)
    meta = {**base, **{k: v for k, v in fields.items() if v is not None}}
    meta_path(corpus).write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def clean_title(title: str | None) -> str | None:
    text = " ".join((title or "").split())[:MAX_TITLE]
    return text or None


def describe(corpus: Path) -> dict[str, Any]:
    """`{"title", "title_source", "documents", "description"}` for a corpus file."""
    stat = corpus.stat()
    key = (str(corpus), stat.st_mtime_ns, stat.st_size)
    scanned = _cache.get(key)
    if scanned is None:
        scanned = _scan(corpus)
        for old in [k for k in _cache if k[0] == key[0]]:
            del _cache[old]
        _cache[key] = scanned
    meta = read_meta(corpus)
    given = clean_title(meta.get("title"))
    if given:
        title, source = given, "given"
    elif scanned["declared"]:
        title, source = scanned["declared"], "declared"
    elif scanned["inferred"]:
        title, source = scanned["inferred"], "inferred"
    else:
        title, source = corpus.stem, "file"
    return {
        "title": title,
        "title_source": source,
        "documents": scanned["documents"],
        "description": clean_title(meta.get("description")),
        "source_file": meta.get("source_file"),
    }


def _scan(corpus: Path) -> dict[str, Any]:
    documents = 0
    titles: list[str] = []
    hosts: Counter[str] = Counter()
    declared: Counter[str] = Counter()
    with corpus.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            documents += 1
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict):
                continue
            for field in DECLARED_FIELDS:
                if isinstance(record.get(field), str) and record[field].strip():
                    declared[record[field].strip()] += 1
                    break
            if isinstance(record.get("title"), str):
                titles.append(record["title"])
            if isinstance(record.get("url"), str) and (m := _HOST.match(record["url"])):
                hosts[m.group(1).lower()] += 1
    top_declared = declared.most_common(1)
    return {
        "documents": documents,
        "declared": clean_title(top_declared[0][0])
        if top_declared and top_declared[0][1] > documents / 2 else None,
        "inferred": infer_title(titles, hosts, documents),
    }


def infer_title(titles: list[str], hosts: Counter[str], documents: int) -> str | None:
    """E.g. 'Wikipedia · Olympics · 1988–2022' — None when nothing stands out."""
    parts = [p for p in (_source(hosts, documents), _topic(titles)) if p]
    if not parts:
        return None
    years = _years(titles)
    return clean_title(" · ".join(parts + ([years] if years else [])))


def _source(hosts: Counter[str], documents: int) -> str | None:
    if not hosts:
        return None
    host, count = hosts.most_common(1)[0]
    if count <= documents / 2:
        return None
    for domain, name in _KNOWN_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host


def _topic(titles: list[str]) -> str | None:
    if not titles:
        return None
    counts: Counter[str] = Counter()
    for title in titles:
        words = _WORD.findall(title)
        grams = set()
        for n in (1, 2, 3):
            for i in range(len(words) - n + 1):
                gram = words[i:i + n]
                if gram[0].lower() in _STOP or gram[-1].lower() in _STOP or len(gram[-1]) < 3:
                    continue
                grams.add(" ".join(gram))
        counts.update(grams)
    if not counts:
        return None
    best, best_count = counts.most_common(1)[0]
    if best_count < MIN_TOPIC_SHARE * len(titles):
        return None
    # A longer phrase built on the best term wins when it covers nearly as much.
    longer = [g for g, c in counts.items() if best in g and g != best and c >= 0.9 * best_count]
    return max(longer, key=lambda g: (counts[g], len(g))) if longer else best


def _years(titles: list[str]) -> str | None:
    years = [int(y) for t in titles for y in _YEAR.findall(t)]
    if len(years) < MIN_TOPIC_SHARE * len(titles):
        return None
    low, high = min(years), max(years)
    return str(low) if low == high else f"{low}–{high}"
