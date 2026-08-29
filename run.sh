#!/usr/bin/env bash
# Reproduction entry point. See REPRODUCTION.md.
#
#   ./run.sh verify        rebuild corpus, check hashes, re-score everything.
#                          No API calls, no cost, no Claude Code needed.
#   ./run.sh baseline-schema   deterministic schema baseline (no API)
#   ./run.sh agent-v1 <S|M|L>  live agent run, profiling only   (needs Claude Code)
#   ./run.sh agent-v2 <S|M|L>  live agent run, + invariants     (needs Claude Code)
set -euo pipefail
IMG=drift
HERE="$(cd "$(dirname "$0")" && pwd)"
# Docker bind-mount paths differ between Git Bash on Windows (which needs a
# leading // to stop MSYS rewriting the path) and Linux/macOS.
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*) MOUNT="//${HERE#/}" ;;
  *)                    MOUNT="$HERE" ;;
esac
dk() { docker run --rm -v "${MOUNT}://app" -w //app "$IMG" "$@"; }

case "${1:-verify}" in
verify)
  echo "== building image =="
  docker build -q -t "$IMG" "$HERE" >/dev/null
  echo "== regenerating corpus (deterministic) =="
  dk python eval/gen_cases.py --scale S eval/cases | tail -2
  echo
  echo "== expected S csv sha256: 931dfa2524951ebb =="
  echo
  echo "== re-scoring every committed prediction set =="
  dk python eval/baseline_schema.py preds/schema_baseline >/dev/null
  for L in schema_baseline prompt_baseline agent_S agentv2_S agentv2_L; do
    [ -d "preds/$L" ] || continue
    dk python eval/score.py "preds/$L" --label "${L}_verify" 2>/dev/null \
      | grep -E "primary_score|recall_on_defects|false_positive|n_missing" \
      | sed "s/^/  [$L] /"
  done
  echo
  echo "== done. All numbers above are recomputed from committed predictions. =="
  ;;
baseline-schema)
  dk sh -c "python eval/baseline_schema.py preds/schema_baseline && python eval/score.py preds/schema_baseline --label schema_baseline"
  ;;
agent-v1) shift; "$HERE/run_agent.sh" "${1:-S}" "agent_${1:-S}" ;;
agent-v2) shift; "$HERE/run_agent_v2.sh" "${1:-S}" "agentv2_${1:-S}" ;;
*) sed -n '2,10p' "$0"; exit 1 ;;
esac
