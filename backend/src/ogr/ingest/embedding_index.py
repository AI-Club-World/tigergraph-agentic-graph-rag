"""Which embedding models are stored for the corpus, and switching between
them (config-docs/EMBEDDING-SWITCHING.md).

State lives in `out/embeddings.json` next to the dataset registry:

    {"active": "<model key>",
     "models": {"<key>": {"covered": [chunk ids], "backend": "...", "evicting": false}},
     "job": {... the last re-embed job ...} | null}

`covered` is the set of chunk ids whose embedding for that model is written
AND checkpointed. It is the job's checkpoint: it grows one batch at a time,
only after that batch's upsert returned. A model is *complete* when it
covers every chunk of the corpus (the dataset registry's chunk ids) and no
job is still working on it; only complete models are queryable.

Resuming a failed job re-embeds exactly `corpus − covered`: finished batches
are never redone, and the one batch that failed part-way is written again —
harmless, because an embedding vertex's primary id is its chunk_id, so a
second write overwrites (graph/client.py upsert_embeddings).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from ogr.common.embedding_models import EMBEDDING_MODELS, MAX_STORED_MODELS, EmbeddingModel, resolve_model

logger = logging.getLogger(__name__)

# Chunks per checkpoint — the build's own embedding step (api/main.py).
CHECKPOINT_BATCH = 500

Mode = Literal["replace", "parallel"]
_LOCK = threading.RLock()


class SwitchRefused(Exception):
    """A switch request the server will not carry out, with a machine code."""

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class EmbeddingStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    # ── persistence ────────────────────────────────────────────────────────

    def read(self) -> dict[str, Any]:
        # Under the lock: on Windows os.replace fails while another thread
        # has the file open, so reads and writes must not overlap.
        with _LOCK:
            if not self.path.exists():
                return {"active": None, "models": {}, "job": None}
            data = json.loads(self.path.read_text(encoding="utf-8"))
        data.setdefault("models", {})
        data.setdefault("job", None)
        data.setdefault("active", None)
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        for attempt in range(5):
            try:
                os.replace(tmp, self.path)
                return
            except PermissionError:  # a reader in another process (Windows)
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _mutate(self, change: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with _LOCK:
            data = self.read()
            change(data)
            self._write(data)
            return data

    # ── state changes ──────────────────────────────────────────────────────

    def active(self, default: str | None = None) -> str | None:
        return self.read().get("active") or default

    def set_active(self, key: str) -> None:
        resolve_model(key)
        self._mutate(lambda d: d.update(active=key))

    def reset(self, active: str) -> None:
        """The graph was recreated empty: no model has embeddings any more."""
        self._mutate(lambda d: d.update(active=active, models={}, job=None))

    def add_covered(
        self, key: str, chunk_ids: list[str], backend: str | None = None, indexing: bool | None = None
    ) -> None:
        """`indexing=True`: written, but the vector index is not confirmed
        queryable yet (a build between its load and its index wait)."""

        def change(d: dict[str, Any]) -> None:
            entry = d["models"].setdefault(key, {"covered": [], "evicting": False})
            if indexing is not None:
                entry["indexing"] = indexing
            entry["covered"] = sorted(set(entry["covered"]) | set(chunk_ids))
            entry["updated_at"] = _now()
            if backend:
                entry["backend"] = backend

        self._mutate(change)

    def adopt_coverage(self, covered: dict[str, list[str]]) -> None:
        """Set each model's coverage to what the graph holds (adopting a
        graph this install did not record); models with none are dropped."""

        def change(d: dict[str, Any]) -> None:
            d["models"] = {
                key: {"covered": sorted(set(ids)), "evicting": False, "updated_at": _now()}
                for key, ids in covered.items()
            }

        self._mutate(change)

    def remove_covered(self, chunk_ids: list[str]) -> None:
        """Chunks left the corpus (a dataset rebuild): no model covers them."""
        gone = set(chunk_ids)

        def change(d: dict[str, Any]) -> None:
            for entry in d["models"].values():
                entry["covered"] = sorted(set(entry["covered"]) - gone)

        self._mutate(change)

    def reserve(self, key: str) -> None:
        """The model's slot for a job. A model that was being evicted may be
        half deleted: its coverage cannot be trusted and starts again."""

        def change(d: dict[str, Any]) -> None:
            entry = d["models"].get(key)
            if entry is None or entry.get("evicting"):
                d["models"][key] = {"covered": [], "evicting": False}

        self._mutate(change)

    def finish_indexing(self, key: str) -> None:
        def change(d: dict[str, Any]) -> None:
            if key in d["models"]:
                d["models"][key]["indexing"] = False

        self._mutate(change)

    def mark_evicting(self, key: str) -> None:
        def change(d: dict[str, Any]) -> None:
            if key in d["models"]:
                d["models"][key]["evicting"] = True

        self._mutate(change)

    def drop(self, key: str) -> None:
        self._mutate(lambda d: d["models"].pop(key, None))

    def recover_interrupted(self) -> bool:
        """Record a job left 'running' by a process that is gone as failed —
        resumable — instead of blocking switches, resumes and queries forever.
        Callers only invoke this when no job task is alive in this process."""
        with _LOCK:
            data = self.read()
            job = data.get("job")
            if not job or job.get("status") != "running":
                return False
            job.update(status="failed", error=job.get("error") or "Interrupted by a server restart",
                       updated_at=_now())
            self._write(data)
            return True

    def update_job(self, **fields: Any) -> dict[str, Any]:
        def change(d: dict[str, Any]) -> None:
            if d.get("job"):
                d["job"].update(fields, updated_at=_now())

        return self._mutate(change)["job"]

    # ── derived views ──────────────────────────────────────────────────────

    def stored(self, data: dict[str, Any] | None = None) -> list[str]:
        """Models holding embeddings in the graph (or a slot reserved for a
        job). A model being evicted is not counted: its deletion is pending
        and runs first in the next job."""
        data = data or self.read()
        return [k for k in EMBEDDING_MODELS if k in data["models"] and not data["models"][k].get("evicting")]

    def model_status(self, key: str, corpus: set[str], data: dict[str, Any] | None = None) -> dict[str, Any]:
        data = data or self.read()
        model = EMBEDDING_MODELS[key]
        entry = data["models"].get(key)
        job = data.get("job") or {}
        covered = set(entry["covered"]) if entry else set()
        done, total = len(corpus & covered), len(corpus)
        if job.get("model") == key and job.get("status") in ("running", "failed"):
            state = "building" if job["status"] == "running" else "failed"
        elif entry is None:
            state = "not_stored"
        elif entry.get("evicting"):
            state = "evicting"
        elif entry.get("indexing"):
            state = "indexing"
        elif total and done == total:
            state = "complete"
        else:
            state = "incomplete"
        return {
            **model.public(),
            "state": state,
            "stored": entry is not None,
            "complete": state == "complete",
            "chunks_done": done,
            "chunks_total": total,
            "backend": (entry or {}).get("backend"),
            "active": data.get("active") == key,
        }

    def complete_models(self, corpus: set[str]) -> list[str]:
        data = self.read()
        return [k for k in EMBEDDING_MODELS if self.model_status(k, corpus, data)["complete"]]

    def overview(self, corpus: set[str], default_active: str) -> dict[str, Any]:
        data = self.read()
        return {
            "active": data.get("active") or default_active,
            "cap": MAX_STORED_MODELS,
            "stored": self.stored(data),
            "models": [self.model_status(k, corpus, data) for k in EMBEDDING_MODELS],
            "job": _public_job(data.get("job")),
            "chunks_total": len(corpus),
        }

    # ── switching ──────────────────────────────────────────────────────────

    def plan(self, target: str, corpus: set[str], default_active: str) -> dict[str, Any]:
        """What each option would do right now — the dialog's real numbers."""
        data = self.read()
        target = resolve_model(target).key
        active = data.get("active") or default_active
        stored = self.stored(data)
        status = self.model_status(target, corpus, data)
        others = [k for k in stored if k != target]
        replace_outgoing = active if active in stored and active != target else None
        after_replace = [k for k in others if k != replace_outgoing]
        return {
            "target": status,
            "active": active,
            "cap": MAX_STORED_MODELS,
            "stored": stored,
            "chunks_total": len(corpus),
            # Already embedded for the whole corpus: switching is instant.
            "instant": status["complete"],
            "parallel": {
                "needs_eviction": len(others) >= MAX_STORED_MODELS,
                "evictable": others if len(others) >= MAX_STORED_MODELS else [],
                "stored_after": len(others) + 1 if len(others) < MAX_STORED_MODELS else MAX_STORED_MODELS,
            },
            "replace": {
                "deletes": replace_outgoing,
                "needs_eviction": len(after_replace) >= MAX_STORED_MODELS,
                "evictable": after_replace if len(after_replace) >= MAX_STORED_MODELS else [],
                "keeps": after_replace,
            },
        }

    def begin_switch(
        self, target: str, mode: Mode | None, evict: str | None, corpus: set[str], default_active: str
    ) -> dict[str, Any]:
        """Validate a switch and record it: an instant switch, or a new job.
        Raises SwitchRefused; never picks an option for the user."""
        with _LOCK:
            data = self.read()
            job = data.get("job") or {}
            if job.get("status") == "running":
                raise _job_running()
            plan = self.plan(target, corpus, default_active)
            key = plan["target"]["key"]
            if plan["instant"]:
                self.set_active(key)
                return {"switched": True, "active": key}
            if mode not in ("replace", "parallel"):
                raise SwitchRefused(
                    "mode_required",
                    f"{plan['target']['label']} has no complete embeddings. Choose 'replace' (force a full "
                    "re-embed) or 'parallel' (keep parallel indices).",
                )
            option = plan[mode]
            if option["needs_eviction"]:
                if not evict:
                    raise SwitchRefused(
                        "eviction_required",
                        f"{len(plan['stored'])}/{plan['cap']} models are stored; pick one to evict before "
                        f"{plan['target']['label']} is embedded.",
                        evictable=option["evictable"],
                    )
                if evict not in option["evictable"]:
                    raise SwitchRefused(
                        "invalid_eviction",
                        f"{evict!r} cannot be evicted here; choose one of {option['evictable']}",
                        evictable=option["evictable"],
                    )
            elif evict:
                raise SwitchRefused(
                    "eviction_not_needed",
                    f"No eviction is needed: {len(plan['stored'])}/{plan['cap']} stored.",
                )
            outgoing = plan["replace"]["deletes"] if mode == "replace" else None
            # Replacing, or evicting the active model, makes the new model active
            # at once: queries then wait for it (or pick a complete model).
            active_now = key if mode == "replace" or evict == plan["active"] else plan["active"]
            new_job = {
                "id": str(uuid.uuid4()),
                "model": key,
                "mode": mode,
                "delete": [k for k in (outgoing, evict) if k],
                "status": "running",
                "phase": "queued",
                "chunks_done": plan["target"]["chunks_done"],
                "chunks_total": len(corpus),
                "batches_done": 0,
                "batches_total": 0,
                "batch_size": CHECKPOINT_BATCH,
                "attempts": 1,
                "error": None,
                "started_at": _now(),
                "updated_at": _now(),
            }
            # An eviction a failed earlier job never finished is carried over:
            # it runs first here, so its model neither lingers half-deleted
            # nor keeps counting against the cap (unless it is the target).
            pending = [
                k for k in (job.get("delete") or [])
                if k != key and (data["models"].get(k) or {}).get("evicting")
            ]
            new_job["delete"] = list(dict.fromkeys(pending + new_job["delete"]))
            for k in new_job["delete"]:
                data["models"].setdefault(k, {"covered": []})["evicting"] = True
            data["active"] = active_now
            data["job"] = new_job
            self._write(data)
            return {"switched": False, "active": active_now, "job": _public_job(new_job)}

    def begin_resume(self) -> dict[str, Any]:
        with _LOCK:
            data = self.read()
            job = data.get("job")
            if not job or job.get("status") != "failed":
                raise SwitchRefused("nothing_to_resume", "There is no failed re-embed job to resume.")
            job.update(status="running", error=None, attempts=job.get("attempts", 1) + 1, updated_at=_now())
            self._write(data)
            return _public_job(job)

    def begin_complete(self, key: str, corpus: set[str]) -> dict[str, Any]:
        """Embed the chunks a stored model is missing (e.g. a dataset built
        while it was not active). Needs no eviction: the model is stored."""
        with _LOCK:
            data = self.read()
            if (data.get("job") or {}).get("status") == "running":
                raise _job_running()
            if key not in data["models"] or data["models"][key].get("evicting"):
                raise SwitchRefused("not_stored", f"{key} is not stored; switch to it instead.")
            status = self.model_status(key, corpus, data)
            if status["complete"]:
                raise SwitchRefused("already_complete", f"{status['label']} already covers every chunk.")
            data["job"] = {
                "id": str(uuid.uuid4()), "model": key, "mode": "complete", "delete": [],
                "status": "running", "phase": "queued", "chunks_done": status["chunks_done"],
                "chunks_total": len(corpus), "batches_done": 0, "batches_total": 0,
                "batch_size": CHECKPOINT_BATCH, "attempts": 1, "error": None,
                "started_at": _now(), "updated_at": _now(),
            }
            self._write(data)
            return _public_job(data["job"])


def _job_running() -> SwitchRefused:
    return SwitchRefused("embedding_job_running", "A re-embed job is running; wait for it to finish.")


def _public_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    return {k: v for k, v in job.items() if k != "chunk_ids"}


def run_job(
    store: EmbeddingStore,
    client: Any,
    corpus: Callable[[], set[str]],
    embed: Callable[[EmbeddingModel, list[str]], list[list[float]]],
    wait_ready: Callable[[], None],
    backend: Callable[[EmbeddingModel], str] = lambda _m: "",
) -> dict[str, Any]:
    """Carry out the recorded job: delete what it replaces or evicts, then
    embed `corpus − covered` in checkpointed batches, then wait for the
    vector index. Any failure leaves the job 'failed' with its error and every
    finished batch checkpointed; `begin_resume` + `run_job` continues it."""
    job = store.read()["job"]
    model = resolve_model(job["model"])
    try:
        # 1. Deletions come first: the new model's job starts only once the
        #    model it replaces or evicts is gone (the 2-model cap).
        for key in job.get("delete", []):
            if key in store.read()["models"]:
                store.update_job(phase="deleting", deleting=key)
                client.delete_embeddings(EMBEDDING_MODELS[key])
                store.drop(key)
        store.update_job(phase="embedding", deleting=None)
        store.reserve(model.key)

        # 2. Embed what is missing, one checkpointed batch at a time.
        chunk_ids = corpus()
        covered = set(store.read()["models"][model.key]["covered"])
        missing = sorted(chunk_ids - covered)
        batches = [missing[i:i + CHECKPOINT_BATCH] for i in range(0, len(missing), CHECKPOINT_BATCH)]
        store.update_job(batches_total=len(batches), batches_done=0, chunks_total=len(chunk_ids),
                         chunks_done=len(chunk_ids & covered))
        tier = backend(model)
        for number, batch in enumerate(batches, 1):
            texts = client.get_chunk_texts(batch)
            absent = [cid for cid in batch if cid not in texts]
            if absent:
                raise LookupError(
                    f"{len(absent)} chunks are not in the graph (e.g. {absent[0]}); rebuild the dataset"
                )
            vectors = embed(model, [texts[cid] for cid in batch])
            client.upsert_embeddings(model, list(zip(batch, vectors, strict=True)))
            store.add_covered(model.key, batch, tier)  # the checkpoint
            done = len(chunk_ids & covered) + sum(map(len, batches[:number]))
            store.update_job(batches_done=number, chunks_done=done)

        # 3. The HNSW index builds asynchronously; not complete until queryable.
        store.update_job(phase="indexing")
        wait_ready()
        store.finish_indexing(model.key)
        final = store.update_job(status="complete", phase="done")
        if job["mode"] == "parallel":
            store.set_active(model.key)  # the model the user chose, now ready
        return final
    except Exception as e:  # noqa: BLE001 - recorded on the job, resumable
        logger.error("Re-embed job %s (%s) failed: %s", job["id"], model.key, e)
        return store.update_job(status="failed", error=str(e)[:500])
