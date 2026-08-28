"""Reference baseline: conventional schema validation (no LLM, no agent)."""
import csv, json, sys
from pathlib import Path
CASES = Path("eval/cases")

def read(path):
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return r.fieldnames, list(r)

def infer(vals):
    vals = [v for v in vals if v != ""]
    if not vals:
        return "empty"
    try:
        [int(v) for v in vals]; return "int"
    except ValueError:
        pass
    try:
        [float(v) for v in vals]; return "float"
    except ValueError:
        pass
    return "str"

def check(day1, day2):
    c1, r1 = read(day1)
    c2, r2 = read(day2)
    s1, s2 = set(c1), set(c2)
    dropped, added = sorted(s1 - s2), sorted(s2 - s1)
    if dropped and added:
        return {"has_defect": True, "affected_columns": dropped,
                "defect_type": "column_renamed", "severity": "high",
                "explanation": f"columns {dropped} disappeared and {added} appeared"}
    if dropped:
        return {"has_defect": True, "affected_columns": dropped,
                "defect_type": "column_dropped", "severity": "high",
                "explanation": f"columns missing in day2: {dropped}"}
    if added:
        return {"has_defect": True, "affected_columns": added,
                "defect_type": "column_added", "severity": "low",
                "explanation": f"unexpected new columns: {added}"}
    for c in c1:
        t1 = infer([r[c] for r in r1])
        t2 = infer([r[c] for r in r2])
        if t1 != t2 and "empty" not in (t1, t2):
            return {"has_defect": True, "affected_columns": [c],
                    "defect_type": "type_changed", "severity": "high",
                    "explanation": f"{c} dtype changed {t1} -> {t2}"}
    return {"has_defect": False, "affected_columns": [], "defect_type": "none",
            "severity": "none", "explanation": "schema matches reference"}

def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "preds/schema_baseline")
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for d in sorted(CASES.iterdir()):
        if not d.is_dir():
            continue
        (out / f"{d.name}.json").write_text(json.dumps(check(d/"day1.csv", d/"day2.csv"), indent=2))
        n += 1
    print(f"schema baseline: wrote {n} predictions -> {out}")

if __name__ == "__main__":
    main()
