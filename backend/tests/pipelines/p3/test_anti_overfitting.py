"""Anti-overfitting enforcement.

Grep the whole answer path for eval-set strings and for any qtype read at
runtime. ARCHITECTURE-SPEC §13 calls this the highest-probability failure
mode, so it gets a command, not an intention. These tests are that command.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[3] / "src" / "ogr"

# NFR-7 scopes to "the answer path": the code that turns a question into an
# answer at query time. That is the pipelines and the graph access they use.
#
# Deliberately NOT scanned:
#   ogr/eval/**      — the scoring and reporting path. TECHNICAL-SPEC §9 makes
#                      the per-qtype breakdown "the headline artifact", so
#                      qtype is required there.
#   ogr/common/**    — the record contract. §6.1 and §6.4 both carry a qtype
#                      field, and §7 states the mapping "exists for reporting
#                      only".
# Widening this to all of src/ would fail on code the spec mandates, which
# would make the guard noise rather than a guard.
ANSWER_PATH = sorted((SRC / "pipelines").rglob("*.py")) + sorted((SRC / "graph").rglob("*.py"))

# The forbidden-chain check has no such nuance: text-to-query generation is
# rejected outright (§7), so it scans everything.
ALL_SOURCES = sorted(SRC.rglob("*.py"))


def _code_without_comments_or_docstrings(path: Path) -> str:
    """Return executable source only — comments and docstrings stripped.

    A docstring documenting the qtype mapping is required by the plan; a
    runtime *read* of qtype is forbidden. Only the latter is a violation.
    """
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)

    lines = [line.split("#", 1)[0] for line in source.splitlines()]
    code = "\n".join(lines)
    for doc in docstrings:
        code = code.replace(doc, "")
    return code


def test_no_qtype_read_at_runtime():
    """NFR-7: qtype is an eval-set label and must never reach the answer path."""
    offenders = []
    for path in ANSWER_PATH:
        code = _code_without_comments_or_docstrings(path)
        if re.search(r"\bqtype\b", code):
            offenders.append(str(path.relative_to(SRC)))
    assert not offenders, (
        "qtype is read at runtime in: "
        + ", ".join(offenders)
        + ". Routing must go through the constrained intent schema only (NFR-7)."
    )


def test_no_eval_set_strings_in_answer_path():
    """No eval-set question ids may appear in executable code."""
    offenders = []
    for path in ANSWER_PATH:
        code = _code_without_comments_or_docstrings(path)
        for match in re.findall(r"\b(?:pub|eval|hid)-\d{3}\b", code):
            offenders.append(f"{path.relative_to(SRC)}: {match}")
    assert not offenders, (
        "Eval-set identifiers found in executable code: " + ", ".join(offenders)
    )


def test_answer_path_is_not_empty():
    """A guard that scans nothing always passes. Make that impossible."""
    names = {p.name for p in ANSWER_PATH}
    assert "orchestrator.py" in names and "p1_rag.py" in names, (
        f"The answer-path scan is missing the pipelines it exists to check: {sorted(names)}"
    )


def test_no_text_to_gsql_chain():
    """TECHNICAL-SPEC §7 rejects text-to-query generation by name.

    Dispatch stays operation -> Q1-Q5 (ARCHITECTURE-SPEC, Engineering guards).
    """
    forbidden = ("GraphCypherQAChain", "GraphQAChain", "create_sql_query_chain")
    offenders = []
    for path in ALL_SOURCES:
        source = path.read_text(encoding="utf-8")
        for name in forbidden:
            if name in source:
                offenders.append(f"{path.relative_to(SRC)}: {name}")
    assert not offenders, "Text-to-query chain referenced: " + ", ".join(offenders)
