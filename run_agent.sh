#!/usr/bin/env bash
# Usage: ./run_agent.sh <SCALE> <LABEL> [case_id ...]
# Profiles each case in Docker, then asks the agent to diagnose from profiles only.
set -u
SCALE="${1:-S}"; LABEL="${2:-agent_${SCALE}}"; shift 2 || true
CASES_DIR="eval/cases"; [ "$SCALE" != "S" ] && CASES_DIR="eval/cases_${SCALE}"
PRED="preds/${LABEL}"; PROF="_profiles/${SCALE}"
mkdir -p "$PRED" "$PROF" _raw

SCHEMA='{"type":"object","properties":{"has_defect":{"type":"boolean"},"affected_columns":{"type":"array","items":{"type":"string"}},"defect_type":{"type":"string","enum":["column_renamed","column_dropped","column_added","type_changed","date_format_changed","null_surge","unit_change","enum_value_drift","precision_loss","encoding_change","duplicate_rows","none"]},"severity":{"type":"string","enum":["none","low","medium","high","critical"]},"explanation":{"type":"string"}},"required":["has_defect","affected_columns","defect_type","severity","explanation"]}'

LIST="$*"; [ -z "$LIST" ] && LIST=$(ls "$CASES_DIR")

for C in $LIST; do
  [ -d "$CASES_DIR/$C" ] || continue
  [ -f "$PRED/$C.json" ] && { echo "skip $C (cached)"; continue; }
  printf '%-26s ' "$C"
  mkdir -p "$PROF/$C"
  docker run --rm -v "//c/Users/yashp/projects/fec-2026://app" -w //app drift sh -c "
    python -m src.tools.profile $CASES_DIR/$C/day1.csv > $PROF/$C/day1.json
    python -m src.tools.profile $CASES_DIR/$C/day2.csv > $PROF/$C/day2.json" || { echo "PROFILE FAIL"; continue; }
  {
    echo "You are auditing a daily data feed for silent contract drift."
    echo "You are given STATISTICAL PROFILES of yesterday's and today's files."
    echo "You do NOT have the raw rows. Diagnose from the profiles alone."
    echo ""
    echo "Look for drift that would corrupt downstream analytics even though the"
    echo "file still loads and parses: changed units or magnitude, lost precision,"
    echo "changed value vocabulary, changed date format, null surges, encoding"
    echo "corruption, duplicated rows, renamed/dropped/added columns, type changes."
    echo "Day-over-day identifier ranges differing is normal and is NOT drift."
    echo ""
    echo "=== PROFILE: YESTERDAY ==="; cat "$PROF/$C/day1.json"
    echo ""
    echo "=== PROFILE: TODAY ==="; cat "$PROF/$C/day2.json"
  } | claude -p --output-format json --json-schema "$SCHEMA" --model sonnet \
      --disallowedTools "Bash Read Write Edit Glob Grep WebSearch WebFetch Task" \
      > "_raw/${LABEL}_$C.json" 2>&1
  python -c "
import json,io
d=json.load(io.open('_raw/${LABEL}_$C.json',encoding='utf-8'))
if d.get('is_error'): print('ERROR:', str(d)[:120]); raise SystemExit
r=json.loads(d['result'])
io.open('$PRED/$C.json','w',encoding='utf-8').write(json.dumps(r,ensure_ascii=False,indent=2))
u=d.get('usage',{})
tot=u.get('cache_creation_input_tokens',0)+u.get('cache_read_input_tokens',0)+u.get('input_tokens',0)
print('ok  %6d tok  \$%.3f  %s' % (tot, d.get('total_cost_usd',0), r['defect_type']))
"
done
