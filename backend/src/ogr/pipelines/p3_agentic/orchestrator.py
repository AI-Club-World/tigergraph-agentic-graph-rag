"""P3 Agentic GraphRAG Orchestrator — LangGraph StateGraph implementation.

Source spec: TECHNICAL-SPEC §8.3 · ARCHITECTURE-SPEC §3, §4, §5, §8
Application spec: FR-2, FR-4, FR-5, FR-6, FR-7, FR-11

ARCHITECTURE-SPEC §8 runtime view implemented as a LangGraph StateGraph:
  Nodes:
    parse_intent    → IntentParser → IntentSchema
    link_entities   → EntityLinker → ResolvedAnchors
    [tool agents]   → AgentResult (one per operation type)
    evaluate_evidence → EvidenceEvaluation
    generate        → PipelineRecord (CORE-02 shared answer contract)

  Conditional edges:
    parse_intent    → necessity router → lookup_direct | scoped_aggregate | loop
    evaluate_evidence → stopping criteria → continue | generate | END

  path_taken: append-only reducer — never set imperatively
  strategy_changed: DERIVED by comparing path_taken vs route_initial (FR-6)

CORE-02 guarantee: generation prompt is byte-identical to P1/P2 except for
the retrieved context block. Any prompt difference is a confound in the
measured accuracy gap.

LOOKUP must traverse ZERO loop edges — verified by test_routing_lookup_direct.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import replace
from typing import Annotated, Any

from typing_extensions import TypedDict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed state
# ---------------------------------------------------------------------------

def append_reducer(existing: list | None, new: list | None) -> list:
    """Append-only list reducer for LangGraph state.

    Without a reducer, a node returning {"path_taken": [x]} REPLACES the list.
    That silently disarms the step budget, because step_count = len(path_taken)
    then never grows across loop iterations.
    """
    return (existing or []) + (new or [])


def _evidence_key(item: dict[str, Any]) -> str:
    return json.dumps(item, sort_keys=True, default=str)


def evidence_reducer(existing: list | None, new: list | None) -> list:
    """Append-only, but an item already held is not added again: a tool that
    returns rows the run already has adds nothing, so evidence (and the
    citations built from it) never repeats and "no new evidence" is visible."""
    merged = list(existing or [])
    seen = {_evidence_key(e) for e in merged}
    for item in new or []:
        key = _evidence_key(item)
        if key not in seen:
            seen.add(key)
            merged.append(item)
    return merged


class OrchestratorState(TypedDict, total=False):
    """Typed state for the P3 LangGraph StateGraph.

    path_taken, evidence and steps accumulate; every other field is replaced
    by the node that writes it.
    """
    question: str
    intent: Any | None                     # IntentSchema
    route_initial: str                        # lookup_direct | scoped_aggregate | loop
    path_taken: Annotated[list[str], append_reducer]
    evidence: Annotated[list[dict[str, Any]], evidence_reducer]
    steps: Annotated[list[Any], append_reducer]   # TraceStep objects
    tokens_used: int
    strategy_changed: bool
    stop_reason: str
    resolved_anchors: Any | None           # ResolvedAnchors


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_p3_graph(
    llm_model: Any,
    tg_client: Any,
    entity_linker: Any,
    run_config: Any,
    on_step: Any | None = None,
):
    """Build and compile the P3 LangGraph StateGraph.

    Args:
        on_step: optional subscriber receiving each TraceStep as it is recorded,
            so one emitter serves both the batch array and a live stream (AD-2).

    Returns a compiled graph ready for .invoke() or .stream().
    """
    from langgraph.graph import END, StateGraph

    from ogr.common.contracts import (
        SNIPPET_CHARS,
        Citation,
        PipelineRecord,
        TokenUsage,
        format_evidence_context,
        format_evidence_item,
    )
    from ogr.common.llm import (
        LLMRateLimitError,
        invoke_llm_with_answer_contract,
        resolve_tool_calling_support,
    )
    from ogr.common.rerank import rerank
    from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
    from ogr.pipelines.p3_agentic.agents.aggregation import run_aggregation
    from ogr.pipelines.p3_agentic.agents.document_retrieval import run_document_retrieval
    from ogr.pipelines.p3_agentic.agents.entity_linking import narrow_to_games
    from ogr.pipelines.p3_agentic.agents.graph_traversal import run_graph_traversal
    from ogr.pipelines.p3_agentic.agents.multi_hop import run_multi_hop, run_venue_events
    from ogr.pipelines.p3_agentic.agents.similarity_search import run_similarity_search
    from ogr.pipelines.p3_agentic.evidence import EvidenceEvaluation, evaluate_evidence
    from ogr.pipelines.p3_agentic.intent import IntentParser
    from ogr.pipelines.p3_agentic.router import loop_tool_candidates, route
    from ogr.pipelines.p3_agentic.stopping import should_stop
    from ogr.pipelines.p3_agentic.strategy import detect_strategy_change
    from ogr.pipelines.p3_agentic.trace import TraceRecorder

    # Use a mutable wrapper so the recorder persists across node calls within a run.
    # `actions`: (tool, args) already run, so no action repeats with the same inputs.
    _state_store: dict[str, Any] = {"actions": set()}

    # Capability probe: 'auto' inspects the model, true/false force it (PLAT-08).
    supports_tool_calling = resolve_tool_calling_support(
        llm_model, getattr(run_config, "llm_supports_tool_calling", "auto")
    )
    # One token-accounting setting for every call in the run (DP-5).
    reports_usage = getattr(run_config, "llm_reports_token_usage", "auto")
    intent_parser = IntentParser(
        llm_model, supports_tool_calling=supports_tool_calling, reports_usage=reports_usage
    )

    # -----------------------------------------------------------------------
    # Node implementations
    # -----------------------------------------------------------------------

    def node_parse_intent(state: dict) -> dict:
        question = state.get("question", "")
        t0 = time.perf_counter()
        intent = intent_parser.parse(question)
        parse_ms = (time.perf_counter() - t0) * 1000.0
        route_decision = route(intent)

        # Initialize trace recorder keyed to this run's route decision
        _state_store["recorder"] = TraceRecorder(
            route_initial=route_decision,
            on_step=on_step,
        )

        # The intent parse is an LLM call and is the entry point to P3; its
        # tokens count against the per-query budget like any other (DP-5).
        parse_tokens = getattr(intent_parser, "last_tokens", None)
        parse_total = parse_tokens.total if parse_tokens else 0
        if parse_total:
            # The orchestrator's planning step: what to investigate and which route.
            _state_store["recorder"].record(
                "orchestrator",
                "intent_parser",
                AgentResult(
                    tokens_input=parse_tokens.input,
                    tokens_output=parse_tokens.output,
                    latency_ms=parse_ms,
                    notes=f"intent parse via {intent_parser.extraction_path}; route {route_decision}",
                ),
            )

        return {
            "intent": intent,
            "route_initial": route_decision,
            "tokens_used": state.get("tokens_used", 0) + parse_total,
        }


    def node_link_entities(state: dict) -> dict:
        intent = state.get("intent")
        if intent is None:
            return {}
        t0 = time.perf_counter()
        anchors = entity_linker.resolve(intent)
        recorder: TraceRecorder = _state_store.get("recorder")
        if recorder:
            found = {
                k: v for k, v in (
                    ("event", getattr(anchors, "event_id", None) or getattr(anchors, "title", None)),
                    ("games", getattr(anchors, "games", None)),
                    ("sport", getattr(anchors, "sport", None)),
                    ("venue", getattr(anchors, "venue", None)),
                ) if v
            }
            recorder.record(
                "entity_linking",
                "entity_linker",
                AgentResult(
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    notes="resolved " + (", ".join(f"{k}={v}" for k, v in found.items()) or "no anchor"),
                ),
            )
        return {"resolved_anchors": anchors}

    def node_disambiguate(state: dict) -> dict:
        """AD-15: an ambiguous venue with no sport/event discriminator ends the
        run with the candidates named. Deterministic — no retrieval and no
        generation call, because no model output can pick the right venue."""
        anchors = state.get("resolved_anchors")
        recorder: TraceRecorder = _state_store.get("recorder")
        candidates = anchors.disambiguation_candidates.get("venue", [])
        shown = ", ".join(candidates[:10])
        if len(candidates) > 10:
            shown += f" (+{len(candidates) - 10} more)"

        _, stop_reason = should_stop(
            evaluation=EvidenceEvaluation(
                is_sufficient=False,
                scope_coverage_pass=False,
                groundedness_pass=False,
                fallback_trigger="none",
                notes="not evaluated: anchor ambiguous",
            ),
            step_count=0,
            tokens_used=state.get("tokens_used", 0),
            has_disambiguation_candidates=True,
        )
        if recorder:
            recorder.record(
                "entity_linking",
                "entity_linker",
                AgentResult(notes=f"venue ambiguous: {len(candidates)} candidates"),
            )
        trace_steps = recorder.finalize() if recorder else []
        tokens = recorder.cumulative_tokens() if recorder else TokenUsage()
        if recorder:
            recorder.reconcile_assert(tokens.total)

        _state_store["pipeline_record"] = PipelineRecord(
            pipeline="agentic_graphrag",
            answer=f"Which venue did you mean: {shown}?",
            explanation=(
                f"The venue in the question matches {len(candidates)} venues and the question names "
                "no sport or event to tell them apart, so no answer was guessed (AD-15)."
            ),
            citations=[],
            chunks_returned=0,
            citations_count=0,
            tokens=TokenUsage(input=tokens.input, output=tokens.output, total=tokens.total),
            token_source=getattr(intent_parser, "last_token_source", "provider"),
            latency_ms=0.0,
            trace=trace_steps,
            strategy_changed=False,
            stop_reason=stop_reason,
            status="done",
            error_detail=None,
        )
        return {"stop_reason": stop_reason}

    def node_lookup_direct(state: dict) -> dict:
        """Direct Q1 lookup — NO loop, ZERO loop edges traversed."""
        intent = state.get("intent")
        anchors = state.get("resolved_anchors")
        recorder: TraceRecorder = _state_store.get("recorder")

        t0 = time.perf_counter()
        params = {
            "title": getattr(anchors, "title", "") or "",
            "event_id": getattr(anchors, "event_id", "") or "",
            "target_field": getattr(intent, "target_field", "") or "",
        }
        raw = tg_client._run_query("q1_lookup", params) or []
        raw = narrow_to_games(raw, getattr(anchors, "games", None))
        latency_ms = (time.perf_counter() - t0) * 1000.0

        result = AgentResult(
            evidence=raw or [],
            chunks_returned=len(raw or []),
            citations_count=len(raw or []),
            latency_ms=latency_ms,
            notes="Q1 direct lookup",
        )
        if recorder:
            recorder.record("graph_traversal", "Q1", result, path_name="lookup")
        _state_store["actions"].add(("lookup",))

        return {
            "evidence": raw or [],
            "path_taken": ["lookup"],
            "tokens_used": state.get("tokens_used", 0),
        }

    def node_scoped_aggregate(state: dict) -> dict:
        """Q2/Q3 aggregation — one scoped query, no loop."""
        intent = state.get("intent")
        anchors = state.get("resolved_anchors")
        recorder: TraceRecorder = _state_store.get("recorder")

        result = run_aggregation(tg_client, intent, anchors)
        if recorder:
            recorder.record(
                "aggregation",
                f"Q{'2' if intent.operation == 'COUNT' else '3'}",
                result,
                path_name="aggregation",
            )

        new_tokens = state.get("tokens_used", 0) + result.tokens_input + result.tokens_output
        return {
            "evidence": result.evidence,
            "path_taken": ["aggregation"],
            "tokens_used": new_tokens,
        }

    def node_loop_traversal(state: dict) -> dict:
        """One iteration of the agentic loop — graph traversal."""
        intent = state.get("intent")
        anchors = state.get("resolved_anchors")
        recorder: TraceRecorder = _state_store.get("recorder")

        # Guard: if anchors not resolved (e.g. intent parse failed), return empty
        if anchors is None:
            if ("traversal",) in _state_store["actions"]:
                _state_store["primary_exhausted"] = True
                return {}
            _state_store["actions"].add(("traversal",))
            _state_store["primary_exhausted"] = True
            result = AgentResult(error="No resolved anchors", notes="anchors=None")
            if recorder:
                recorder.record("graph_traversal", "Q4", result, path_name="traversal")
            return {
                "evidence": [],
                "path_taken": ["traversal"],
            }

        # The next action depends on what has been tried: the first pass makes
        # the same choice P2 does (router.first_loop_tool); later passes take
        # the next applicable tool not yet run, because re-running one with
        # the same anchors returns the same rows. None left: nothing to do.
        tried = {a[0] for a in _state_store["actions"]}
        candidates = loop_tool_candidates(intent, anchors) if intent else ["traversal"]
        tool = next((t for t in candidates if t not in tried), None)
        if tool is None:
            _state_store["primary_exhausted"] = True
            return {}
        _state_store["actions"].add((tool,))
        if tool == "lookup":
            t0 = time.perf_counter()
            rows = narrow_to_games(
                tg_client._run_query("q1_lookup", {
                    "title": anchors.title or "",
                    "event_id": anchors.event_id or "",
                    "target_field": intent.target_field or "",
                }) or [],
                anchors.games,
            )
            result = AgentResult(
                evidence=rows, chunks_returned=len(rows), citations_count=len(rows),
                latency_ms=(time.perf_counter() - t0) * 1000.0, notes="Q1 lookup on the named event",
            )
            tool_name, q_name = "lookup", "Q1"
        elif tool == "multi_hop":
            result = run_multi_hop(tg_client, intent, anchors)
            tool_name, q_name = "multi_hop", "Q1→Q4→Q1"
        elif tool == "venue":
            result = run_venue_events(tg_client, intent, anchors)
            tool_name, q_name = "multi_hop", "Q4(HELD_AT)→Q1"
        else:
            result = run_graph_traversal(tg_client, anchors)
            tool_name, q_name = "traversal", "Q4"

        if recorder:
            agent = "multi_hop_reasoning" if tool in ("multi_hop", "venue") else "graph_traversal"
            recorder.record(agent, q_name, result, path_name=tool_name)

        # evidence and path_taken accumulate through the reducer — return only
        # what this step added.
        return {
            "evidence": result.evidence,
            "path_taken": [tool_name],
            "tokens_used": state.get("tokens_used", 0) + result.tokens_input + result.tokens_output,
        }

    def node_evaluate_evidence(state: dict) -> dict:
        """Evaluate sufficiency + trigger fallbacks if needed."""
        evidence = state.get("evidence", [])
        intent = state.get("intent")
        anchors = state.get("resolved_anchors")
        question = state.get("question", "")
        recorder: TraceRecorder = _state_store.get("recorder")

        # A loop iteration that added no new evidence would get the same
        # temperature-0 verdict again, so the previous one is reused instead
        # of paying for another groundedness call.
        evidence_key = frozenset(_evidence_key(e) for e in evidence)
        previous = _state_store.get("last_eval")
        unchanged = previous is not None and _state_store.get("last_eval_key") == evidence_key
        t0 = time.perf_counter()
        if unchanged:
            reused = "; evidence unchanged, verdict reused"
            eval_result = replace(
                previous,
                tokens_input=0,
                tokens_output=0,
                notes=previous.notes if previous.notes.endswith(reused) else previous.notes + reused,
            )
        else:
            eval_result = evaluate_evidence(
                evidence=evidence,
                intent_operation=getattr(intent, "operation", "TRAVERSE"),
                anchors=anchors,
                model=llm_model,
                reports_usage=reports_usage,
                question=question,
            )
        eval_ms = (time.perf_counter() - t0) * 1000.0
        _state_store["last_eval_key"] = evidence_key

        # Trigger fallbacks if needed (DP-2 Option A). Only the additions are
        # returned; the reducer appends them to the accumulated state.
        new_evidence: list = []
        new_path: list = []
        # The groundedness check is the loop's only LLM call. Counting it is
        # what arms the token budget (DP-3) and DP-5 requires every model call
        # be attributed to a step_n, so it is recorded as one.
        extra_tokens = eval_result.tokens_input + eval_result.tokens_output
        if recorder:
            recorder.record(
                "evidence_evaluation",
                "evidence_evaluator",
                AgentResult(
                    evidence=[],
                    chunks_returned=0,
                    citations_count=0,  # it evaluates evidence; it cites nothing
                    tokens_input=eval_result.tokens_input,
                    tokens_output=eval_result.tokens_output,
                    latency_ms=eval_ms,
                    notes=f"{len(evidence)} evidence items; {eval_result.notes}",
                ),
            )

        acted = False
        if not eval_result.is_sufficient:
            doc_ids = sorted({e.get("doc_id", "") for e in evidence if e.get("doc_id")})
            actions = _state_store["actions"]
            if eval_result.fallback_trigger == "scope_coverage_fail" and ("similarity_search",) in actions:
                # Already searched the same question: only document retrieval is new.
                trigger = "groundedness_fail" if doc_ids else None
            else:
                trigger = eval_result.fallback_trigger
            already = ("document_retrieval", tuple(doc_ids)) in actions
            if trigger in ("groundedness_fail", "empty_anchor") and already:
                trigger = None  # these documents' chunks are already in the evidence
            if trigger == "scope_coverage_fail":
                _state_store["actions"].add(("similarity_search",))
                acted = True
                sim_result = run_similarity_search(
                    tg_client,
                    question,
                    k=run_config.k,
                    embedding_model=run_config.embedding_model,
                    embedding_dim=run_config.embedding_dim,
                    triggered_by="scope_coverage_fail",
                )
                if recorder:
                    recorder.record("similarity_search", "Q5", sim_result, path_name="similarity_search")
                new_evidence += sim_result.evidence
                new_path.append("similarity_search")
                extra_tokens += sim_result.tokens_input + sim_result.tokens_output

            elif trigger in ("groundedness_fail", "empty_anchor"):
                _state_store["actions"].add(("document_retrieval", tuple(doc_ids)))
                acted = True
                doc_result = run_document_retrieval(
                    tg_client,
                    doc_ids=doc_ids or None,
                    triggered_by=trigger,
                )
                # HAS_CHUNK returns every chunk in document order; best first
                # lets groundedness and the [:20] context see the relevant ones.
                doc_result.evidence = rerank(question, doc_result.evidence)
                if recorder:
                    recorder.record(
                        "document_retrieval",
                        "HAS_CHUNK",
                        doc_result,
                        path_name="document_retrieval",
                    )
                new_evidence += doc_result.evidence
                new_path.append("document_retrieval")
                extra_tokens += doc_result.tokens_input + doc_result.tokens_output

        new_tokens = state.get("tokens_used", 0) + extra_tokens
        _state_store["last_eval"] = eval_result
        # Nothing new came back and nothing new was tried: another pass would
        # repeat this one exactly.
        _state_store["idle"] = unchanged and not acted

        return {
            "evidence": new_evidence,
            "path_taken": new_path,
            "tokens_used": new_tokens,
        }

    def node_generate(state: dict) -> dict:
        """Final generation using CORE-02 shared answer contract (byte-identical prompt to P1/P2)."""
        evidence = state.get("evidence", [])
        question = state.get("question", "")
        route_initial = state.get("route_initial", "loop")
        path_taken = state.get("path_taken", [])
        recorder: TraceRecorder = _state_store.get("recorder")

        # Structured graph rows first, in retrieval order; prose chunks from
        # the fallbacks reranked against the question before truncation (G-2).
        prose_sources = ("similarity_search", "document_retrieval")
        structured = [e for e in evidence if e.get("source") not in prose_sources]
        prose = rerank(question, [e for e in evidence if e.get("source") in prose_sources])
        # Same renderer as P2 (structured rows keep every field).
        shown = (structured + prose)[:20]
        context = format_evidence_context(shown, empty="No relevant evidence found.")

        try:
            answer, explanation, tokens, token_source, latency_ms = invoke_llm_with_answer_contract(
                model=llm_model,
                context=context,
                question=question,
                reports_usage=reports_usage,
            )
            status = "done"
            error_detail = None
        except LLMRateLimitError:
            raise  # DP-3: stop the run; the user switches model
        except Exception as e:
            logger.error("P3 generation failed: %s", e)
            answer = ""
            explanation = f"Generation error: {e}"
            tokens = TokenUsage()
            token_source = "provider"
            latency_ms = 0.0
            status = "error"
            error_detail = str(e)

        if recorder:
            recorder.record_llm_generation(
                tokens_input=tokens.input,
                tokens_output=tokens.output,
                latency_ms=latency_ms,
            )

        # Citations are exactly the evidence the model was shown, once each
        # (the same source for P2: doc_id, else event_id).
        citations = []
        cited: set[tuple[str, str | None]] = set()
        for e in shown:
            doc_id = e.get("doc_id") or e.get("event_id") or ""
            chunk_id = e.get("chunk_id")
            if doc_id and (doc_id, chunk_id) not in cited:
                cited.add((doc_id, chunk_id))
                citations.append(Citation(
                    source_id=doc_id,
                    chunk_id=chunk_id,
                    ref_type="chunk" if chunk_id else "entity",
                    snippet=format_evidence_item(e)[:SNIPPET_CHARS] or None,
                ))

        # Derive strategy_changed — never set imperatively. The route-vs-path
        # comparison catches an off-route tool; the step scan additionally
        # catches a fallback that fired inside its own route (DP-2).
        strategy_changed, _ = detect_strategy_change(route_initial, path_taken)

        # Why the investigation stopped, as decided when it stopped (not
        # recomputed now with the generation tokens added). A one-query route
        # is never evaluated, so it does not claim sufficient evidence.
        stop_reason = _state_store.get("stop_reason") or "direct_route"

        # Finalize trace
        trace_steps = recorder.finalize() if recorder else []
        strategy_changed = strategy_changed or any(s.strategy_change for s in trace_steps)
        cumulative = recorder.cumulative_tokens() if recorder else tokens
        final_tokens = TokenUsage(
            input=cumulative.input,
            output=cumulative.output,
            total=cumulative.total,
        )
        if recorder:
            recorder.reconcile_assert(final_tokens.total)

        _state_store["pipeline_record"] = PipelineRecord(
            pipeline="agentic_graphrag",
            answer=answer,
            explanation=explanation,
            citations=citations,
            chunks_returned=len(evidence),
            citations_count=len(citations),
            tokens=final_tokens,
            token_source=token_source,
            latency_ms=latency_ms,
            trace=trace_steps,
            strategy_changed=strategy_changed,
            stop_reason=stop_reason,
            status=status,
            error_detail=error_detail,
        )
        return {}

    # -----------------------------------------------------------------------
    # Routing functions (conditional edges)
    # -----------------------------------------------------------------------

    def route_after_parse(state: dict) -> str:
        """Conditional edge from link_entities to the correct path node."""
        anchors = state.get("resolved_anchors")
        if anchors is not None and anchors.needs_disambiguation:
            return "disambiguate"
        decision = state.get("route_initial") or "loop"
        logger.debug("route_after_parse: → %s", decision)
        return decision

    def route_after_evaluate(state: dict) -> str:
        """Conditional edge from evaluate_evidence to continue or generate."""
        last_eval = _state_store.get("last_eval")
        path_taken = state.get("path_taken", [])
        tokens_used = state.get("tokens_used", 0)

        if last_eval is None:
            _state_store["stop_reason"] = "error"
            return "generate"

        stop, reason = should_stop(
            evaluation=last_eval,
            step_count=len(path_taken),
            tools_tried=path_taken,
            tokens_used=tokens_used,
            max_steps=getattr(run_config, "max_steps", 6),
            max_tokens=getattr(run_config, "max_tokens_per_query", 20000),
        )
        if not stop and _state_store.get("idle") and _state_store.get("primary_exhausted"):
            stop, reason = True, "no_further_action_available"
        if stop:
            _state_store["stop_reason"] = reason
            _state_store["stop_after_step"] = len(path_taken)
        return "generate" if stop else "loop_traversal"

    def route_after_lookup(state: dict) -> str:
        """A direct lookup that found nothing is not answered from nothing:
        the orchestrator escalates to the loop (a strategy change)."""
        if state.get("evidence"):
            return "generate"
        logger.debug("route_after_lookup: Q1 returned nothing → loop")
        return "loop_traversal"

    # -----------------------------------------------------------------------
    # Build graph
    # -----------------------------------------------------------------------

    graph = StateGraph(OrchestratorState)

    graph.add_node("parse_intent", node_parse_intent)
    graph.add_node("link_entities", node_link_entities)
    graph.add_node("disambiguate", node_disambiguate)
    graph.add_node("lookup_direct", node_lookup_direct)
    graph.add_node("scoped_aggregate", node_scoped_aggregate)
    graph.add_node("loop_traversal", node_loop_traversal)
    graph.add_node("evaluate_evidence", node_evaluate_evidence)
    graph.add_node("generate", node_generate)

    graph.set_entry_point("parse_intent")
    graph.add_edge("parse_intent", "link_entities")

    # Necessity router as conditional edge
    graph.add_conditional_edges(
        "link_entities",
        route_after_parse,
        {
            "lookup_direct": "lookup_direct",
            "scoped_aggregate": "scoped_aggregate",
            "loop": "loop_traversal",
            "disambiguate": "disambiguate",
        },
    )

    # lookup_direct and scoped_aggregate answer from one query; an empty
    # lookup escalates to the loop instead.
    graph.add_conditional_edges(
        "lookup_direct", route_after_lookup, {"generate": "generate", "loop_traversal": "loop_traversal"}
    )
    graph.add_edge("scoped_aggregate", "generate")

    # Loop: traversal → evaluate → continue | generate
    graph.add_edge("loop_traversal", "evaluate_evidence")
    graph.add_conditional_edges(
        "evaluate_evidence",
        route_after_evaluate,
        {
            "generate": "generate",
            "loop_traversal": "loop_traversal",
        },
    )

    graph.add_edge("generate", END)
    graph.add_edge("disambiguate", END)

    return graph.compile(), _state_store


def _prepare_run(
    llm_model: Any | None,
    tg_client: Any | None,
    entity_linker: Any | None,
    config: Any | None,
    on_step: Any | None = None,
):
    """Resolve defaults and compile the graph. Shared by the sync and stream entry points."""
    from ogr.common.config import get_default_config
    from ogr.common.llm import get_chat_model
    from ogr.graph.client import TigerGraphClient
    from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker

    cfg = config or get_default_config()
    client = tg_client or TigerGraphClient(cfg)
    model = llm_model or get_chat_model(cfg)

    # Build entity linker from graph vocabularies (or defaults for offline)
    if entity_linker is None:
        entity_linker = EntityLinker(
            games_vocab=client.get_vocabulary("Games") or None,
            sports_vocab=client.get_vocabulary("Sport") or None,
            venues_vocab=client.get_vocabulary("Venue") or None,
        )

    return build_p3_graph(model, client, entity_linker, cfg, on_step=on_step)


def _error_record(detail: str, latency_ms: float, state_store: dict | None = None) -> Any:
    """A PipelineRecord for a run that could not complete (NFR-2: never raise).
    The steps already taken, and the tokens they spent, stay on the record:
    a failed investigation still cost what it cost."""
    from ogr.common.contracts import PipelineRecord, TokenUsage

    recorder = (state_store or {}).get("recorder")
    steps = recorder.finalize() if recorder else []
    spent = recorder.cumulative_tokens() if recorder else TokenUsage()
    return PipelineRecord(
        pipeline="agentic_graphrag",
        answer="",
        explanation=f"Orchestrator error: {detail}",
        citations=[],
        chunks_returned=0,
        citations_count=0,
        tokens=TokenUsage(input=spent.input, output=spent.output, total=spent.total),
        token_source="provider",
        latency_ms=latency_ms,
        trace=steps,
        strategy_changed=False,
        stop_reason="error",
        status="error",
        error_detail=detail,
    )


async def astream_p3_agentic(
    query: str,
    llm_model: Any | None = None,
    tg_client: Any | None = None,
    entity_linker: Any | None = None,
    config: Any | None = None,
) -> Any:  # AsyncIterator[TraceStep | PipelineRecord]
    """Stream a P3 run: each TraceStep as its node completes, then the record.

    Built on LangGraph `astream_events`, so the trace is assembled exactly once
    (AD-1, AD-2). The TraceRecorder is the single emitter; its steps feed both
    this stream and the `trace` array on the final PipelineRecord. Assembling
    the trace twice is how the live demo and the submitted metrics drift apart.

    Yields TraceStep objects, then exactly one PipelineRecord last.
    """
    # Off the event loop: preparing connects to TigerGraph, fetches three
    # vocabularies and builds the client — seconds on Savanna, during which
    # every other request and SSE stream would stall.
    from ogr.common.llm import LLMRateLimitError

    compiled_graph, state_store = await asyncio.to_thread(
        _prepare_run, llm_model, tg_client, entity_linker, config
    )
    total_start = time.perf_counter()
    emitted = 0

    def _drain():
        """Yield any steps the recorder has produced but not yet streamed."""
        nonlocal emitted
        recorder = state_store.get("recorder")
        if recorder is None:
            return []
        steps = recorder.finalize()
        new = steps[emitted:]
        emitted = len(steps)
        return new

    try:
        async for event in compiled_graph.astream_events({"question": query}):
            # A node finishing is the point at which its step exists.
            if event.get("event") not in ("on_chain_end", "on_chain_stream"):
                continue
            for step in _drain():
                yield step
    except LLMRateLimitError:
        raise  # DP-3: same as run_p3_agentic — the caller stops, it is not an answer
    except Exception as e:  # noqa: BLE001 - fault isolation, never raise to the caller
        logger.error("P3 stream failed: %s", e)
        for step in _drain():
            yield step
        yield _error_record(str(e), (time.perf_counter() - total_start) * 1000.0, state_store)
        return

    # Anything recorded after the last observed event (e.g. the generate node).
    for step in _drain():
        yield step

    record = state_store.get("pipeline_record")
    if record is None:
        yield _error_record(
            "state_store missing pipeline_record", (time.perf_counter() - total_start) * 1000.0
        )
        return

    record.latency_ms = (time.perf_counter() - total_start) * 1000.0
    yield record


def run_p3_agentic(
    query: str,
    llm_model: Any | None = None,
    tg_client: Any | None = None,
    entity_linker: Any | None = None,
    config: Any | None = None,
) -> Any:  # PipelineRecord
    """Run the P3 Agentic GraphRAG pipeline for a single query.

    Args:
        query: The question to answer.
        llm_model: LangChain chat model instance.
        tg_client: TigerGraphClient instance.
        entity_linker: EntityLinker instance (built from graph vocabularies).
        config: RunConfig instance.

    Returns:
        PipelineRecord with full trace, strategy_changed, stop_reason.
    """
    from ogr.common.llm import LLMRateLimitError

    compiled_graph, state_store = _prepare_run(llm_model, tg_client, entity_linker, config)
    total_start = time.perf_counter()

    try:
        compiled_graph.invoke({"question": query})
    except LLMRateLimitError:
        raise  # DP-3: stop the run; the user switches model
    except Exception as e:
        logger.error("P3 orchestrator failed: %s", e)
        return _error_record(str(e), (time.perf_counter() - total_start) * 1000.0, state_store)

    record = state_store.get("pipeline_record")
    if record is None:
        return _error_record(
            "state_store missing pipeline_record", (time.perf_counter() - total_start) * 1000.0
        )

    # Set total latency on the returned record
    record.latency_ms = (time.perf_counter() - total_start) * 1000.0
    return record
