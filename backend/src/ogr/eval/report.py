"""Run report and submission export — from one batch run file.

`report` answers the guidebook's question for a run: where does the agentic
pipeline measurably beat plain RAG, and is it worth its tokens? Per question
type it gives the accuracy gap and token ratio with a verdict; it shows how
often the necessity router answered in one query (and the tokens that
saved), which agents and tools ran, and why runs stopped. Every number is
computed from the records (scores via `history.view_record`, the one
scorer); the only estimate is labelled as such.

`export` writes the raw outputs the organisers ask for on the hidden set —
per question and pipeline: answer, tokens, citations, and the agentic trace.
"""

from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from ogr.eval.history import read_run, view_record

__all__ = ["build_report", "export_run", "WORTH_IT", "OVERKILL"]

PIPELINES = ("rag", "graphrag", "agentic_graphrag")
LABELS = {"rag": "RAG", "graphrag": "GraphRAG", "agentic_graphrag": "Agentic GraphRAG"}
QTYPES = ("lookup", "aggregation", "superlative", "temporal", "multi_hop")
# Same thresholds as the dashboard's worth-it table (frontend/src/Dashboard.tsx).
WORTH_IT = 0.5
OVERKILL = 0.05


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _fmt(value: float | None, digits: int = 2) -> str:
    return "—" if value is None else f"{value:.{digits}f}"


def _int(value: float | None) -> str:
    return "—" if value is None else f"{round(value):,}"


def _answered(view: dict[str, Any], pipeline: str) -> dict[str, Any] | None:
    record = view["record"]["pipelines"].get(pipeline)
    return record if record and record.get("status") != "error" else None


def _route(view: dict[str, Any]) -> str:
    """'direct' when the router answered in one query, else 'loop'."""
    agentic = view["record"]["pipelines"].get("agentic_graphrag") or {}
    return "direct" if agentic.get("stop_reason") == "direct_route" else "loop"


def _verdict(gap: float | None, n: int) -> str:
    if not n or gap is None:
        return "—"
    return "Worth it" if gap >= WORTH_IT else "Overkill" if gap <= OVERKILL else "Marginal"


def _agentic_tokens(view: dict[str, Any]) -> int:
    return view["record"]["pipelines"]["agentic_graphrag"]["tokens"]["total"]


def _em(view: dict[str, Any], pipeline: str) -> float:
    return view["scores"].get(pipeline, {}).get("em", 0)


def build_report(path: Path) -> str:
    run_config, records = read_run(path)
    views = [view_record(r) for r in records]
    scored = [v for v in views if v["scores"]]
    lines: list[str] = []
    out = lines.append

    out(f"# Run report: `{path.stem}`\n")
    out(f"- Questions: **{len(views)}** ({len(scored)} with ground truth)")
    out(f"- LLM (all three pipelines): `{run_config.get('llm_provider')}/{run_config.get('llm_model')}`")
    out(f"- Embeddings: `{run_config.get('embedding_model')}` via `{run_config.get('embedding_backend')}`")
    out(f"- Mode: `{run_config.get('latency_mode')}`, pool {run_config.get('pool_size')}, "
        f"k={run_config.get('k')}, max steps {run_config.get('max_steps')}")
    out(f"- Started: {run_config.get('started_at', '—')}\n")

    # ── Headline ──
    out("## Headline\n")
    out("| Pipeline | EM | F1 | Completeness | Grounded | Median tokens "
        "| Mean in / out | Mean latency | Errors |")
    out("|---|---|---|---|---|---|---|---|---|")
    for p in PIPELINES:
        runs = [v["record"]["pipelines"][p] for v in views if p in v["record"]["pipelines"]]
        ok = [r for r in runs if r.get("status") != "error"]
        sc = [v["scores"][p] for v in scored if p in v["scores"]]
        grounded = [
            v["grounding"][p] for v in views if p in v.get("grounding", {}) and _answered(v, p)
        ]
        score = {k: _fmt(_mean([s[k] for s in sc])) for k in ("em", "f1", "completeness")}
        tok_in = _int(_mean([r["tokens"]["input"] for r in ok]))
        tok_out = _int(_mean([r["tokens"]["output"] for r in ok]))
        latency = _fmt((_mean([r["latency_ms"] for r in ok]) or 0) / 1000, 1)
        out(
            f"| {LABELS[p]} | {score['em']} | {score['f1']} | {score['completeness']} "
            f"| {_fmt(_mean(grounded))} | {_int(_median([r['tokens']['total'] for r in ok]))} "
            f"| {tok_in} / {tok_out} | {latency} s | {len(runs) - len(ok)} |"
        )
    out("")

    # ── Is the agent worth it, per question type ──
    if scored:
        out("## Where the agent pays for itself\n")
        out("Agentic − RAG accuracy gap and the token cost of it, per question type. "
            f"Verdict: gap ≥ {WORTH_IT} worth it, ≤ {OVERKILL} overkill, else marginal.\n")
        out("| Type | n | RAG EM | GraphRAG EM | Agentic EM | Agentic − RAG "
            "| Agentic ÷ RAG tokens | Verdict |")
        out("|---|---|---|---|---|---|---|---|")
        for qtype in QTYPES:
            rows = [v for v in scored if v.get("qtype") == qtype]
            em = {
                p: _mean([v["scores"][p]["em"] for v in rows if p in v["scores"]]) for p in PIPELINES
            }
            agentic_em, rag_em = em["agentic_graphrag"], em["rag"]
            gap = None if agentic_em is None or rag_em is None else agentic_em - rag_em
            ratios = [
                _agentic_tokens(v) / v["record"]["pipelines"]["rag"]["tokens"]["total"]
                for v in rows
                if _answered(v, "rag") and _answered(v, "agentic_graphrag")
                and v["record"]["pipelines"]["rag"]["tokens"]["total"]
            ]
            out(
                f"| {qtype} | {len(rows)} | {_fmt(rag_em)} | {_fmt(em['graphrag'])} "
                f"| {_fmt(agentic_em)} | {_fmt(gap)} | {_fmt(_median(ratios))}× "
                f"| {_verdict(gap, len(rows))} |"
            )
        wins = [v["qid"] for v in scored if _em(v, "agentic_graphrag") > _em(v, "rag")]
        losses = [v["qid"] for v in scored if _em(v, "agentic_graphrag") < _em(v, "rag")]
        out(f"\nAgentic right where RAG was wrong: **{len(wins)}** ({', '.join(wins) or '—'})  ")
        out(f"RAG right where Agentic was wrong: **{len(losses)}** ({', '.join(losses) or '—'})\n")

    # ── Necessity routing ──
    out("## Necessity routing\n")
    by_route: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for v in views:
        if _answered(v, "agentic_graphrag"):
            by_route[_route(v)].append(v)
    out("| Route | Questions | Median agentic tokens | Agentic EM |")
    out("|---|---|---|---|")
    for route in ("direct", "loop"):
        rows = by_route.get(route, [])
        toks = [_agentic_tokens(v) for v in rows]
        ems = [_em(v, "agentic_graphrag") for v in rows if "agentic_graphrag" in (v["scores"] or {})]
        out(f"| {route} | {len(rows)} | {_int(_median(toks))} | {_fmt(_mean(ems))} |")
    direct, loop = by_route.get("direct", []), by_route.get("loop", [])
    if direct and loop:
        loop_median = _median([_agentic_tokens(v) for v in loop]) or 0
        spent = sum(_agentic_tokens(v) for v in direct)
        saved = max(0.0, loop_median * len(direct) - spent)
        out(f"\n*Estimate:* answering the {len(direct)} direct-route questions through the "
            f"loop at the loop's median cost would have spent about **{_int(saved)}** more "
            "tokens.\n")
    else:
        out("")

    # ── What the agent did ──
    agentic = [
        v["record"]["pipelines"]["agentic_graphrag"]
        for v in views
        if "agentic_graphrag" in v["record"]["pipelines"]
    ]
    steps = [s for r in agentic for s in r.get("trace") or []]
    if steps:
        out("## Agents and tools\n")
        out("| Agent | Invocations | Tokens | Tokens / call | Time / call |")
        out("|---|---|---|---|---|")
        agg: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for s in steps:
            agg[s["agent_type"]].append(s)
        for agent, rows in sorted(agg.items(), key=lambda kv: -len(kv[1])):
            tokens = sum(s["tokens"]["total"] for s in rows)
            out(f"| {agent} | {len(rows)} | {tokens:,} | {_int(tokens / len(rows))} "
                f"| {_int(_mean([s['latency_ms'] for s in rows]))} ms |")
        tools = Counter(s["tool_called"] for s in steps)
        out("\nTools called: " + ", ".join(f"`{t}` ×{n}" for t, n in tools.most_common()) + "\n")
        stops = Counter(r.get("stop_reason") or "none" for r in agentic)
        changed = sum(1 for r in agentic if r.get("strategy_changed"))
        out("Stop reasons: " + ", ".join(f"`{k}` ×{n}" for k, n in stops.most_common()))
        out(f"  \nStrategy changed on **{changed}** of {len(agentic)} questions; "
            f"median {_int(_median([len(r.get('trace') or []) for r in agentic]))} trace steps.\n")
    return "\n".join(lines)


def export_run(path: Path) -> dict[str, Any]:
    """The submission shape: run config plus, per question, every pipeline's
    answer, token use, latency, citations and (agentic) full trace."""
    run_config, records = read_run(path)
    questions = []
    for r in records:
        pipelines = {}
        for name, p in (r.get("record") or {}).get("pipelines", {}).items():
            pipelines[name] = {
                "answer": p.get("answer"),
                "explanation": p.get("explanation"),
                "status": p.get("status"),
                "tokens": p.get("tokens"),
                "token_source": p.get("token_source"),
                "latency_ms": p.get("latency_ms"),
                "chunks_returned": p.get("chunks_returned"),
                "citations": p.get("citations"),
                **({"trace": p.get("trace"), "strategy_changed": p.get("strategy_changed"),
                    "stop_reason": p.get("stop_reason")} if name == "agentic_graphrag" else {}),
            }
        questions.append({
            "qid": r.get("question_id"),
            "question": r.get("question_text"),
            "qtype": r.get("qtype"),
            "pipelines": pipelines,
        })
    return {"run_id": path.stem, "run_config": run_config, "questions": questions}


def write_export(path: Path, out: Path) -> int:
    data = export_run(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(data["questions"])
