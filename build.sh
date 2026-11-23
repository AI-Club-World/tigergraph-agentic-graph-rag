#!/usr/bin/env bash
# Build the TigerGraph graph from the Round 2 corpus and write out/r2/graph_counts.json.
# Usage: ./build.sh corpus.jsonl      (run from any directory; reads .env at the repo root if present)
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: $0 <corpus.jsonl>" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORPUS="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi
mkdir -p "$ROOT/out/r2"
cd "$ROOT/backend"
export PYTHONPATH="$ROOT/backend/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m ogr.cli r2-build --corpus "$CORPUS"
