# Round-1 archive

Items from Round 1 that the Round-2 system (`build.sh`, `run.sh`, `ogr.r2`, the API and the web app) does not use. They are kept for reference, are not imported or read by any code, and are not part of the backend package (`backend/src`). Paths inside are relative to the repository root, e.g. `archive-round-1/docs/round-1/`.

## `docs/round-1/`

The Round-1 documentation: functional and technical specifications, architecture and UI specs, the embedding-model switching design, the deployment and run guides, and the submission write-up. Its `submission/` folder holds the Round-1 public- and hidden-set reports and the raw hidden-set export. The Round-2 documents are in `docs/round-2/`.

## `docs/archive/round-1/`

`SCORE-AUDIT.md`, a self-audit of the Round-1 system against that round's rubric, with the fixes made and the before/after scores. The Round-2 working notes remain in `docs/archive/round-2-exploration/`.

## `acceptance/holdout/`

`eval_hidden.jsonl`, the Round-1 holdout question set, run once by the Round-1 `holdout` target. Round 2 has its own question files under `docs/round-2/data/`.

## `Makefile`

The Round-1 one-command reproduce pipeline (install, check, verify, build, benchmark, timing, holdout, report and export). Run from the repository root with `make -f archive-round-1/Makefile <target>`. Round 2 uses `build.sh` and `run.sh`.
