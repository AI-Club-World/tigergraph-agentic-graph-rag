#!/usr/bin/env bash
# Answer a question set, then self-score (public only) and update out/r2/metrics.json.
# Usage: ./run.sh questions_public.jsonl answers_public.jsonl
#        ./run.sh questions_hidden.jsonl answers_hidden.jsonl
# The metrics set ("public" or "hidden") is inferred from the questions file name: a name containing
# "hidden" -> hidden, "public" -> public; otherwise public if the first line has gold answers, else
# hidden. Each run replaces its own block of metrics.json and keeps the other. Run from any directory.
set -euo pipefail

if [ $# -ne 2 ]; then
  echo "usage: $0 <questions.jsonl> <answers.jsonl>" >&2
  exit 2
fi
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QUESTIONS="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
mkdir -p "$(dirname "$2")"
ANSWERS="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
if [ -f "$ROOT/.env" ]; then
  set -a
  # shellcheck disable=SC1091
  . "$ROOT/.env"
  set +a
fi
mkdir -p "$ROOT/out/r2"
METRICS="$ROOT/out/r2/metrics.json"

HAS_GOLD=0
if head -n 1 "$QUESTIONS" | grep -q '"status"'; then HAS_GOLD=1; fi
case "$(basename "$QUESTIONS")" in
  *hidden*) SET=hidden ;;
  *public*) SET=public ;;
  *) if [ "$HAS_GOLD" = 1 ]; then SET=public; else SET=hidden; fi ;;
esac

cd "$ROOT/backend"
export PYTHONPATH="$ROOT/backend/src${PYTHONPATH:+:$PYTHONPATH}"
START=$(date +%s.%N)
python3 -m ogr.cli r2-run --questions "$QUESTIONS" --out "$ANSWERS"
ELAPSED=$(python3 -c "import sys; print(round(float(sys.argv[1]) - float(sys.argv[2]), 1))" "$(date +%s.%N)" "$START")

if [ "$HAS_GOLD" = 1 ]; then
  python3 -m ogr.cli r2-score --questions "$QUESTIONS" --answers "$ANSWERS" --out "$ROOT/out/r2/score_$SET.json"
  python3 -m ogr.cli r2-metrics --set "$SET" --answers "$ANSWERS" --questions "$QUESTIONS" \
    --run-time-s "$ELAPSED" --out "$METRICS"
else
  python3 -m ogr.cli r2-metrics --set "$SET" --answers "$ANSWERS" --run-time-s "$ELAPSED" --out "$METRICS"
fi
