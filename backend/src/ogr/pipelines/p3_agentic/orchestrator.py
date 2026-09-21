"""P3 Agentic GraphRAG Orchestrator — LangGraph StateGraph implementation.

Source spec: TECHNICAL-SPEC §8.3 · ARCHITECTURE-SPEC §3, §4, §5, §8
Application spec: FR-2, FR-4, FR-5, FR-6, FR-7, FR-11
Plan: implementation-plan-AGENT.md Group 5

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

import json
import logging
import time
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Typed state
# ---------------------------------------------------------------------------

def _append_reducer(existing: list, new: list) -> list:
    """Append-only list reducer for LangGraph state."""
    return (existing or []) + (new or [])


class OrchestratorState(BaseModel):
    """Typed state for the P3 LangGraph StateGraph.

    All fields are updated by nodes returning partial dicts.
    path_taken is an append-only list — never reset mid-run.
    """
    model_config = {"arbitrary_types_allowed": True}

    question: str = ""
    intent: Optional[Any] = None              # IntentSchema
    route_initial: str = ""                   # 'lookup_direct' | 'scoped_aggregate' | 'loop'
    path_taken: List[str] = []               # append-only via reducer
    evidence: List[Dict[str, Any]] = []
    steps: List[Any] = []                     # TraceStep objects
    tokens_used: int = 0
    strategy_changed: bool = False
    stop_reason: str = ""
    resolved_anchors: Optional[Any] = None   # ResolvedAnchors


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_p3_graph(
    llm_model: Any,
    tg_client: Any,
    entity_linker: Any,
    run_config: Any,
):
    """Build and compile the P3 LangGraph StateGraph.

    Returns a compiled graph ready for .invoke() or .stream().
    """
    from langgraph.graph import END, StateGraph

    from ogr.common.contracts import Citation, PipelineRecord, TokenUsage, TraceStep
    from ogr.common.llm import invoke_llm_with_answer_contract
    from ogr.pipelines.p3_agentic.agents.aggregation import run_aggregation
    from ogr.pipelines.p3_agentic.agents.document_retrieval import run_document_retrieval
    from ogr.pipelines.p3_agentic.agents.graph_traversal import run_graph_traversal
    from ogr.pipelines.p3_agentic.agents.multi_hop import run_multi_hop
    from ogr.pipelines.p3_agentic.agents.similarity_search import run_similarity_search
    from ogr.pipelines.p3_agentic.evidence import evaluate_evidence
    from ogr.pipelines.p3_agentic.intent import IntentParser, IntentSchema
    from ogr.pipelines.p3_agentic.router import route
    from ogr.pipelines.p3_agentic.stopping import should_stop
    from ogr.pipelines.p3_agentic.strategy import detect_strategy_change
    from ogr.pipelines.p3_agentic.trace import TraceRecorder

    # Use a mutable wrapper so the recorder persists across node calls within a run
    _state_store: Dict[str, Any] = {}

    # Determine capability (from run_config or env probe)
    supports_tool_calling = getattr(run_config, "llm_supports_tool_calling", False)
    intent_parser = IntentParser(llm_model, supports_tool_calling=supports_tool_calling)

    # -----------------------------------------------------------------------
    # Node implementations
    # -----------------------------------------------------------------------

    def node_parse_intent(state: dict) -> dict:
        question = state.get("question", "")
        intent = intent_parser.parse(question)
        route_decision = route(intent)

        # Store in _state_store so routing functions can read it reliably
        # (plain dict StateGraph doesn't guarantee key propagation across nodes)
        _state_store["route_decision"] = route_decision

        # Initialize trace recorder keyed to this run's route decision
        _state_store["recorder"] = TraceRecorder(route_initial=route_decision)

        return {
            "intent": intent,
            "route_initial": route_decision,
            "path_taken": [],
        }


    def node_link_entities(state: dict) -> dict:
        intent = state.get("intent")
        if intent is None:
            return {}
        anchors = entity_linker.resolve(intent)
        return {"resolved_anchors": anchors}

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
        raw = tg_client._run_query("q1_lookup", params)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
        result = AgentResult(
            evidence=raw or [],
            chunks_returned=len(raw or []),
            citations_count=len(raw or []),
            latency_ms=latency_ms,
            notes="Q1 direct lookup",
        )
        if recorder:
            recorder.record("entity_linking", "Q1", result)

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

        from ogr.pipelines.p3_agentic.agents.aggregation import run_aggregation
        result = run_aggregation(tg_client, intent, anchors)
        if recorder:
            recorder.record("aggregation", f"Q{'2' if intent.operation == 'COUNT' else '3'}", result)

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
        question = state.get("question", "")

        # Guard: if anchors not resolved (e.g. intent parse failed), return empty
        if anchors is None:
            from ogr.pipelines.p3_agentic.agents.agent_result import AgentResult
            result = AgentResult(error="No resolved anchors", notes="anchors=None")
            if recorder:
                recorder.record("graph_traversal", "Q4", result)
            return {
                "evidence": list(state.get("evidence", [])),
                "path_taken": ["traversal"],
                "tokens_used": state.get("tokens_used", 0),
            }

        # Choose appropriate traversal type based on operation
        if intent and intent.operation == "TRAVERSE":
            # Check if it's temporal (has title/event_id) or multi-hop
            if getattr(anchors, "title", None) or getattr(anchors, "event_id", None):
                result = run_multi_hop(tg_client, intent, anchors)
                tool_name = "multi_hop"
                q_name = "Q4→Q1"
            else:
                result = run_graph_traversal(tg_client, anchors)
                tool_name = "traversal"
                q_name = "Q4"
        else:
            result = run_graph_traversal(tg_client, anchors)
            tool_name = "traversal"
            q_name = "Q4"

        if recorder:
            recorder.record("graph_traversal", q_name, result)

        combined_evidence = list(state.get("evidence", [])) + result.evidence
        new_tokens = state.get("tokens_used", 0) + result.tokens_input + result.tokens_output

        return {
            "evidence": combined_evidence,
            "path_taken": [tool_name],
            "tokens_used": new_tokens,
        }

    def node_evaluate_evidence(state: dict) -> dict:
        """Evaluate sufficiency + trigger fallbacks if needed."""
        evidence = state.get("evidence", [])
        intent = state.get("intent")
        anchors = state.get("resolved_anchors")
        question = state.get("question", "")
        recorder: TraceRecorder = _state_store.get("recorder")
        path_taken = state.get("path_taken", [])

        eval_result = evaluate_evidence(
            evidence=evidence,
            intent_operation=getattr(intent, "operation", "TRAVERSE"),
            anchors=anchors,
            model=llm_model,
            question=question,
        )

        # Trigger fallbacks if needed (DP-2 Option A)
        new_evidence = list(evidence)
        new_path = list(path_taken)
        extra_tokens = 0

        if not eval_result.is_sufficient:
            if eval_result.fallback_trigger == "scope_coverage_fail":
                sim_result = run_similarity_search(
                    tg_client,
                    question,
                    k=run_config.k,
                    embedding_model=run_config.embedding_model,
                    embedding_dim=run_config.embedding_dim,
                    triggered_by="scope_coverage_fail",
                )
                if recorder:
                    recorder.record("similarity_search", "Q5", sim_result)
                new_evidence += sim_result.evidence
                new_path.append("similarity_search")
                extra_tokens += sim_result.tokens_input + sim_result.tokens_output

            elif eval_result.fallback_trigger in ("groundedness_fail", "empty_anchor"):
                doc_ids = list({e.get("doc_id", "") for e in evidence if e.get("doc_id")})
                doc_result = run_document_retrieval(
                    tg_client,
                    doc_ids=doc_ids or None,
                    triggered_by=eval_result.fallback_trigger,
                )
                if recorder:
                    recorder.record("document_retrieval", "HAS_CHUNK", doc_result)
                new_evidence += doc_result.evidence
                new_path.append("document_retrieval")
                extra_tokens += doc_result.tokens_input + doc_result.tokens_output

        new_tokens = state.get("tokens_used", 0) + extra_tokens
        _state_store["last_eval"] = eval_result

        return {
            "evidence": new_evidence,
            "path_taken": new_path,
            "tokens_used": new_tokens,
        }

    def node_generate(state: dict) -> dict:
        """Final generation using CORE-02 shared answer contract (byte-identical prompt to P1/P2)."""
        evidence = state.get("evidence", [])
        question = state.get("question", "")
        intent = state.get("intent")
        route_initial = state.get("route_initial", "loop")
        path_taken = state.get("path_taken", [])
        recorder: TraceRecorder = _state_store.get("recorder")

        # Build context from evidence
        context_parts = []
        for i, e in enumerate(evidence[:20], 1):
            text = e.get("text", e.get("event_name", str(e.get("value", ""))))
            doc_id = e.get("doc_id", e.get("event_id", ""))
            chunk_id = e.get("chunk_id")
            context_parts.append(f"[{i}] [Source: {doc_id}]\n{text}")
        context = "\n\n".join(context_parts) or "No relevant evidence found."

        try:
            answer, explanation, tokens, token_source, latency_ms = invoke_llm_with_answer_contract(
                model=llm_model,
                context=context,
                question=question,
            )
            status = "done"
            error_detail = None
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

        # Build citations from evidence
        citations = []
        for e in evidence:
            doc_id = e.get("doc_id", e.get("event_id", ""))
            chunk_id = e.get("chunk_id")
            ref_type = "chunk" if chunk_id else "entity"
            if doc_id:
                citations.append(Citation(
                    source_id=doc_id,
                    chunk_id=chunk_id,
                    ref_type=ref_type,
                ))

        # Derive strategy_changed from path_taken vs route_initial
        strategy_changed, _ = detect_strategy_change(route_initial, path_taken)

        # Determine stop_reason
        last_eval = _state_store.get("last_eval")
        tokens_used = state.get("tokens_used", 0) + tokens.total
        stop_reason = "sufficient_evidence"
        if last_eval and hasattr(last_eval, "is_sufficient"):
            from ogr.pipelines.p3_agentic.stopping import should_stop
            _, stop_reason = should_stop(
                evaluation=last_eval,
                step_count=len(path_taken),
                tokens_used=tokens_used,
                max_steps=getattr(run_config, "max_steps", 6),
                max_tokens=getattr(run_config, "max_tokens_per_query", 20000),
            )

        # Finalize trace
        trace_steps = recorder.finalize() if recorder else []
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
        """Conditional edge from link_entities to the correct path node.

        Reads from _state_store rather than state dict to avoid key loss
        when StateGraph(dict) is used (plain dict state does not guarantee
        merging of all prior keys in every node's state view).
        """
        decision = _state_store.get("route_decision", "loop")
        logger.debug("route_after_parse: → %s", decision)
        return decision

    def route_after_evaluate(state: dict) -> str:
        """Conditional edge from evaluate_evidence to continue or generate."""
        last_eval = _state_store.get("last_eval")
        path_taken = state.get("path_taken", [])
        tokens_used = state.get("tokens_used", 0)

        from ogr.pipelines.p3_agentic.stopping import should_stop
        if last_eval is None:
            return "generate"

        stop, _ = should_stop(
            evaluation=last_eval,
            step_count=len(path_taken),
            tokens_used=tokens_used,
            max_steps=getattr(run_config, "max_steps", 6),
            max_tokens=getattr(run_config, "max_tokens_per_query", 20000),
        )
        return "generate" if stop else "loop_traversal"

    # -----------------------------------------------------------------------
    # Build graph
    # -----------------------------------------------------------------------

    graph = StateGraph(dict)

    graph.add_node("parse_intent", node_parse_intent)
    graph.add_node("link_entities", node_link_entities)
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
        },
    )

    # lookup_direct and scoped_aggregate go directly to generate (no loop)
    graph.add_edge("lookup_direct", "generate")
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

    return graph.compile(), _state_store


def run_p3_agentic(
    query: str,
    llm_model: Optional[Any] = None,
    tg_client: Optional[Any] = None,
    entity_linker: Optional[Any] = None,
    config: Optional[Any] = None,
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
    from ogr.common.config import get_default_config
    from ogr.common.contracts import PipelineRecord, TokenUsage
    from ogr.common.llm import get_chat_model
    from ogr.graph.client import TigerGraphClient
    from ogr.pipelines.p3_agentic.agents.entity_linking import EntityLinker

    cfg = config or get_default_config()
    client = tg_client or TigerGraphClient(cfg)
    model = llm_model or get_chat_model(cfg)

    # Build entity linker from graph vocabularies (or defaults for offline)
    if entity_linker is None:
        games_vocab = client.get_vocabulary("Games") or None
        sports_vocab = client.get_vocabulary("Sport") or None
        venues_vocab = client.get_vocabulary("Venue") or None
        entity_linker = EntityLinker(
            games_vocab=games_vocab,
            sports_vocab=sports_vocab,
            venues_vocab=venues_vocab,
        )

    compiled_graph, state_store = build_p3_graph(model, client, entity_linker, cfg)

    initial_state = {"question": query}
    total_start = time.perf_counter()

    try:
        compiled_graph.invoke(initial_state)
    except Exception as e:
        logger.error("P3 orchestrator failed: %s", e)
        total_latency = (time.perf_counter() - total_start) * 1000.0
        return PipelineRecord(
            pipeline="agentic_graphrag",
            answer="",
            explanation=f"Orchestrator error: {e}",
            citations=[],
            chunks_returned=0,
            citations_count=0,
            tokens=TokenUsage(),
            token_source="provider",
            latency_ms=total_latency,
            trace=[],
            strategy_changed=False,
            stop_reason="error",
            status="error",
            error_detail=str(e),
        )

    record = state_store.get("pipeline_record")
    if record is None:
        total_latency = (time.perf_counter() - total_start) * 1000.0
        return PipelineRecord(
            pipeline="agentic_graphrag",
            answer="",
            explanation="No pipeline record produced",
            citations=[],
            chunks_returned=0,
            citations_count=0,
            tokens=TokenUsage(),
            token_source="provider",
            latency_ms=total_latency,
            trace=[],
            strategy_changed=False,
            stop_reason="error",
            status="error",
            error_detail="state_store missing pipeline_record",
        )

    # Set total latency on the returned record
    record.latency_ms = (time.perf_counter() - total_start) * 1000.0
    return record
