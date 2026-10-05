"""Tests for GRAPH-09's BuildEvent emitter."""

from __future__ import annotations

from ogr.ingest.progress import BuildEvent, BuildProgress


class TestBuildProgress:
    def test_emits_nothing_without_a_subscriber(self):
        progress = BuildProgress()
        progress.start("chunk_embed", ["rag", "graphrag", "agentic_graphrag"], items_total=2951)
        progress.finish("chunk_embed", ["rag", "graphrag", "agentic_graphrag"], items_done=2951)

    def test_start_progress_finish_sequence(self):
        events: list[BuildEvent] = []
        progress = BuildProgress(on_event=events.append)

        progress.start("chunk_embed", ["rag"], items_total=10)
        progress.progress("chunk_embed", ["rag"], items_done=5, items_total=10)
        progress.finish("chunk_embed", ["rag"], items_done=10)

        assert [e.status for e in events] == ["running", "running", "done"]
        assert events[-1].items_done == 10
        assert events[-1].elapsed_ms >= 0

    def test_tokens_are_always_zero(self):
        """AD-6: no LLM runs during ingestion — the figure is stated, not hidden."""
        events: list[BuildEvent] = []
        progress = BuildProgress(on_event=events.append)
        progress.start("load", ["graphrag", "agentic_graphrag"])
        progress.finish("load", ["graphrag", "agentic_graphrag"], items_done=100)
        assert all(e.tokens == 0 for e in events)

    def test_pipeline_affected_fans_out_to_a_list(self):
        """DP-6: one shared build, stages fan out to the pipelines they unblock."""
        events: list[BuildEvent] = []
        progress = BuildProgress(on_event=events.append)
        progress.start("query_library_install", ["rag", "graphrag", "agentic_graphrag"])
        assert events[0].pipeline_affected == ["rag", "graphrag", "agentic_graphrag"]

    def test_ready_event_flips_the_readiness_badge(self):
        events: list[BuildEvent] = []
        progress = BuildProgress(on_event=events.append)
        progress.ready(["rag"], note="chunk+embed and Q5 done")
        assert events[0].status == "ready"
        assert events[0].pipeline_affected == ["rag"]

    def test_error_event_carries_a_note(self):
        events: list[BuildEvent] = []
        progress = BuildProgress(on_event=events.append)
        progress.start("load", ["graphrag"])
        progress.error("load", ["graphrag"], note="TigerGraph unreachable")
        assert events[-1].status == "error"
        assert events[-1].note == "TigerGraph unreachable"
