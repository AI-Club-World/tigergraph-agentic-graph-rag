# Vector spike notes (Group 0, implementation-plan-GRAPH.md)

**Status: NOT YET EXECUTED.**

`scripts/spike_vector.py` was authored on 2026-09-21 but could not be run
against the live TigerGraph Savanna workspace from the authoring session:
outbound network access to `tgcloud.io` was blocked by that session's egress
policy (`CONNECT tunnel failed, response 403`).

The TigerVector DDL and `vectorSearch()` call syntax in the script are marked
`UNVERIFIED` — confirming or correcting them against a live connection is the
entire point of this spike (see implementation-plan-GRAPH.md Research
Summary: "the one area with a documented async-lag gotcha is the one area
with no reference material"). Do not treat Gate G0 as passed until someone
with `tgcloud.io` access has run

```
pip install -r scripts/requirements-spike.txt
python scripts/spike_vector.py
```

with `TG_HOST` / `TG_USERNAME` / `TG_PASSWORD` / `TG_SECRET` /
`TG_GRAPHNAME` set (env or a local, git-ignored `.env`), and this file has a
`## Run ...` section below reporting `status: PASS` with real
`schema_install_s` / `vector_index_lag_s` timings.

Per the plan's rollback note: if `vectorSearch()` turns out to be
unavailable on the provisioned Savanna version, stop and escalate — it
invalidates Q5, P1 and AGENT-05 across the other implementation plans, and
there is no external vector-store fallback.
