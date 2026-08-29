"""Render a drift verdict as the alert a data engineer would actually receive.

The agent emits structured JSON. That is the right interface for machines, but
it is not what lands in someone's inbox at 8am. This turns a verdict plus its
supporting evidence into a report that says what changed, how bad it is, what
breaks downstream, and what to do next.

Usage:
    python -m src.report <verdict.json> [--profiles DIR] [--feed NAME] [--date YYYY-MM-DD]

Example:
    python -m src.report preds/agentv2_S/13_amount_decoupled.json \
        --profiles _profiles/S/13_amount_decoupled --feed orders_feed
"""
import json, sys, textwrap
from pathlib import Path

WIDTH = 74

SEVERITY_ACTION = {
    "critical": "Hold today's load. Do not refresh downstream reports.\n"
                "Contact the data provider before reprocessing.",
    "high":     "Quarantine today's file and re-check affected downstream jobs\n"
                "before the next scheduled refresh.",
    "medium":   "Load may proceed. Flag affected columns for review and confirm\n"
                "with the provider whether this change is intentional.",
    "low":      "No action required. Note the change in the feed's contract log.",
    "none":     "No action required.",
}

IMPACT = {
    "unit_change":
        "Every aggregate over this column is wrong by the scale factor.\n"
        "Revenue totals, averages and threshold filters will all be affected.",
    "precision_loss":
        "Rounding is now baked into the source. Totals will drift from the\n"
        "provider's own figures and the error compounds across aggregations.",
    "cross_column_invariant_broken":
        "Aggregate totals may still look plausible, which is what makes this\n"
        "dangerous. Per-row analysis -- per-order, per-customer, per-segment --\n"
        "and any reconciliation against line items will be silently wrong.",
    "duplicate_rows":
        "Counts and sums are inflated. Anything grouped by a key that is now\n"
        "duplicated will double-count.",
    "null_surge":
        "Joins and filters on this column will silently drop rows. Coverage\n"
        "metrics computed from it will be understated.",
    "enum_value_drift":
        "Filters and CASE expressions matching the old values will stop\n"
        "matching. Rows will fall through into default branches.",
    "date_format_changed":
        "Date parsing will either fail loudly or, worse, succeed with the day\n"
        "and month transposed.",
    "encoding_change":
        "Text comparisons and joins on this column will miss. Customer-facing\n"
        "output will show corrupted characters.",
    "column_renamed":
        "Any query or transform referencing the old name will fail or return\n"
        "nothing.",
    "column_dropped":
        "Downstream jobs reading this column will fail or silently null it.",
    "column_added":
        "Usually benign, but schema-on-read consumers may pick it up\n"
        "unexpectedly.",
    "type_changed":
        "Casts and arithmetic on this column may fail or coerce silently.",
}


def rule(ch="-"):
    return ch * WIDTH


def wrap(text, indent="  "):
    out = []
    for para in text.split("\n"):
        out.extend(textwrap.wrap(para, WIDTH - len(indent)) or [""])
    return "\n".join(indent + l for l in out)


def load_evidence(profiles_dir):
    """Pull the specific numbers that justify the verdict, if available."""
    if not profiles_dir:
        return None, None, None
    d = Path(profiles_dir)
    try:
        inv = json.loads((d / "invariants.json").read_text(encoding="utf-8"))
    except Exception:
        inv = None
    try:
        p1 = json.loads((d / "day1.json").read_text(encoding="utf-8"))
        p2 = json.loads((d / "day2.json").read_text(encoding="utf-8"))
    except Exception:
        p1 = p2 = None
    return inv, p1, p2


def column_evidence(p1, p2, cols):
    """Show the before/after statistics for the affected columns."""
    if not (p1 and p2):
        return []
    s1 = {c["name"]: c for c in p1.get("column_stats", [])}
    s2 = {c["name"]: c for c in p2.get("column_stats", [])}
    lines = []
    for c in cols:
        a, b = s1.get(c), s2.get(c)
        if not (a and b):
            continue
        bits = []
        if a["dtype"] != b["dtype"]:
            bits.append(f"type {a['dtype']} -> {b['dtype']}")
        if abs(a["null_rate"] - b["null_rate"]) > 0.05:
            bits.append(f"nulls {a['null_rate']:.1%} -> {b['null_rate']:.1%}")
        na, nb = a.get("numeric"), b.get("numeric")
        if na and nb:
            if na["mean"] and abs(nb["mean"] - na["mean"]) / abs(na["mean"]) > 0.05:
                bits.append(f"mean {na['mean']:,.2f} -> {nb['mean']:,.2f}")
            if abs(na["zero_fraction_rate"] - nb["zero_fraction_rate"]) > 0.2:
                bits.append(f"whole-number rate {na['zero_fraction_rate']:.1%}"
                            f" -> {nb['zero_fraction_rate']:.1%}")
        if a.get("date_formats") != b.get("date_formats"):
            bits.append(f"date format {list(a.get('date_formats', {}))}"
                        f" -> {list(b.get('date_formats', {}))}")
        if b.get("non_ascii_rate", 0) - a.get("non_ascii_rate", 0) > 0.05:
            bits.append(f"non-ascii {a.get('non_ascii_rate',0):.1%}"
                        f" -> {b.get('non_ascii_rate',0):.1%}")
        lines.append(f"    {c}: " + ("; ".join(bits) if bits
                                     else "all column statistics unchanged"))
    return lines


def render(verdict, inv=None, p1=None, p2=None, feed="feed", date=""):
    sev = (verdict.get("severity") or "none").lower()
    cols = verdict.get("affected_columns") or []
    dtype = verdict.get("defect_type", "none")
    out = []

    header = f"{feed}" + (f"  {date}" if date else "")
    if not verdict.get("has_defect"):
        left = f"NO DRIFT DETECTED - {header}"
        right = "SEVERITY: none"
        out += [rule("="),
                left + " " * max(2, WIDTH - len(left) - len(right)) + right,
                rule("="), ""]
        out.append(wrap("Today's file is consistent with the reference. Column "
                        "statistics and all discovered cross-column relationships "
                        "are within normal day-over-day variation."))
        if inv and inv.get("invariants"):
            out += ["", "  Relationships checked and still holding:"]
            for i in inv["invariants"]:
                out.append(f"    {i['expr']}  ({i.get('candidate_hold_rate')})")
        out += ["", rule(), "  No action required.", rule()]
        return "\n".join(out)

    left = f"DRIFT DETECTED - {header}"
    right = f"SEVERITY: {sev.upper()}"
    out += [rule("="),
            left + " " * max(2, WIDTH - len(left) - len(right)) + right,
            rule("="), ""]

    out.append(f"  WHAT CHANGED")
    out.append(f"    {dtype.replace('_', ' ')}"
               + (f" affecting {', '.join(cols)}" if cols else ""))
    out.append("")

    ev = column_evidence(p1, p2, cols)
    if ev:
        out.append("  COLUMN STATISTICS")
        out += ev
        out.append("")

    if inv and inv.get("invariants"):
        broken = [i for i in inv["invariants"] if i.get("status") == "BROKEN"]
        if broken:
            out.append("  BROKEN RELATIONSHIPS")
            for i in broken:
                n = i.get("n_checked", "?")
                out.append(f"    {i['expr']}")
                out.append(f"      held on {i['ref_hold_rate']:.1%} of rows yesterday, "
                           f"{i['candidate_hold_rate']:.1%} today "
                           f"({n} rows sampled)")
            out.append("")
        holding = [i for i in inv["invariants"] if i.get("status") == "holds"]
        if holding:
            out.append("  RELATIONSHIPS STILL INTACT")
            for i in holding:
                out.append(f"    {i['expr']}")
            out.append("")

    if dtype in IMPACT:
        out.append("  DOWNSTREAM IMPACT")
        out.append(wrap(IMPACT[dtype], indent="    "))
        out.append("")

    out.append("  RECOMMENDED ACTION")
    out.append(wrap(SEVERITY_ACTION.get(sev, SEVERITY_ACTION["none"]), indent="    "))
    out.append("")

    expl = (verdict.get("explanation") or "").strip()
    if expl:
        out.append(rule())
        out.append("  FULL ANALYSIS")
        out.append(wrap(expl, indent="    "))
    out.append(rule())
    return "\n".join(out)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    def opt(name, default=None):
        f = f"--{name}"
        return sys.argv[sys.argv.index(f) + 1] if f in sys.argv else default
    verdict = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    inv, p1, p2 = load_evidence(opt("profiles"))
    print(render(verdict, inv, p1, p2,
                 feed=opt("feed", "feed"), date=opt("date", "")))


if __name__ == "__main__":
    main()
