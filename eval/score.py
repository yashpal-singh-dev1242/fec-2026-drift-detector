"""Score drift-detection predictions against ground truth."""
import json, sys
from pathlib import Path

VOCAB = ["column_renamed", "column_dropped", "column_added", "type_changed",
         "date_format_changed", "null_surge", "unit_change", "enum_value_drift",
         "precision_loss", "encoding_change", "duplicate_rows", "cross_column_invariant_broken", "none"]
CASES_DIR = Path("eval/cases")

def load_truth():
    return {p.parent.name: json.loads(p.read_text())
            for p in sorted(CASES_DIR.glob("*/truth.json"))}

def jaccard(a, b):
    a, b = set(a), set(b)
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b) if (a | b) else 1.0

def score_case(pred, truth):
    det = bool(pred.get("has_defect")) == bool(truth["has_defect"])
    d = {"detection": det, "localization": None, "classification": None, "loc_jaccard": None}
    if not det:
        return 0.0, d
    if not truth["has_defect"]:
        return 1.0, d
    loc_exact = set(pred.get("affected_columns") or []) == set(truth["affected_columns"])
    loc_j = jaccard(pred.get("affected_columns") or [], truth["affected_columns"])
    cls = (pred.get("defect_type") or "").strip() == truth["defect_type"]
    d.update(localization=loc_exact, classification=cls, loc_jaccard=round(loc_j, 3))
    return round(0.4 + 0.3 * loc_exact + 0.3 * cls, 3), d

def main():
    pred_dir = Path(sys.argv[1])
    label = "run"
    if "--label" in sys.argv:
        label = sys.argv[sys.argv.index("--label") + 1]
    truths = load_truth()
    rows, missing = [], []
    for cid, truth in truths.items():
        f = pred_dir / f"{cid}.json"
        if not f.exists():
            missing.append(cid)
            rows.append({"case_id": cid, "composite": 0.0, "detection": False,
                         "localization": None, "classification": None,
                         "loc_jaccard": None, "note": "MISSING PREDICTION"})
            continue
        try:
            pred = json.loads(f.read_text())
        except json.JSONDecodeError as e:
            rows.append({"case_id": cid, "composite": 0.0, "detection": False,
                         "localization": None, "classification": None,
                         "loc_jaccard": None, "note": f"UNPARSEABLE: {e}"})
            continue
        comp, d = score_case(pred, truth)
        rows.append({"case_id": cid, "composite": comp, **d,
                     "predicted_type": pred.get("defect_type"),
                     "true_type": truth["defect_type"]})
    defects = [r for r in rows if truths[r["case_id"]]["has_defect"]]
    controls = [r for r in rows if not truths[r["case_id"]]["has_defect"]]
    invisible = [r for r in rows if truths[r["case_id"]]["has_defect"]
                 and not truths[r["case_id"]]["schema_check_catches"]]
    def pct(xs, key):
        vals = [x[key] for x in xs if x.get(key) is not None]
        return round(100 * sum(bool(v) for v in vals) / len(vals), 1) if vals else 0.0
    summary = {
        "label": label,
        "primary_score": round(sum(r["composite"] for r in rows) / len(rows), 3),
        "detection_accuracy_pct": pct(rows, "detection"),
        "recall_on_defects_pct": pct(defects, "detection"),
        "recall_schema_invisible_pct": pct(invisible, "detection"),
        "false_positive_rate_pct": round(
            100 * sum(1 for r in controls if not r["detection"]) / max(len(controls), 1), 1),
        "localization_exact_pct_of_detected": pct(defects, "localization"),
        "classification_pct_of_detected": pct(defects, "classification"),
        "n_cases": len(rows), "n_missing": len(missing),
    }
    Path("results").mkdir(exist_ok=True)
    out = Path("results") / f"{label}.json"
    out.write_text(json.dumps({"summary": summary, "per_case": rows}, indent=2))
    print(f"\n=== {label} ===")
    print(f"{'case':<26}{'comp':>6}{'det':>6}{'loc':>6}{'cls':>6}  predicted -> true")
    for r in rows:
        f = lambda v: "-" if v is None else ("Y" if v else "n")
        print(f"{r['case_id']:<26}{r['composite']:>6}{f(r.get('detection')):>6}"
              f"{f(r.get('localization')):>6}{f(r.get('classification')):>6}  "
              f"{str(r.get('predicted_type')):<22}{r.get('true_type','')}"
              + (f"  [{r['note']}]" if r.get("note") else ""))
    print("\n--- summary ---")
    for k, v in summary.items():
        print(f"  {k:<36}{v}")
    print(f"\nwrote {out}")

if __name__ == "__main__":
    main()
