"""Discover cross-column invariants from sampled rows, then verify them.

Per-column profiles are blind to relationships between columns. A feed whose
`amount` column is shuffled has an identical amount distribution but no longer
satisfies amount == quantity * unit_price.

Samples a bounded number of rows (default 300) regardless of file size, then:
  1. DISCOVERS invariants holding in the reference file -- it is not told
     which relationships to expect.
  2. VERIFIES those same invariants in the candidate file.
"""
import csv, json, random, re, sys
from pathlib import Path

SAMPLE_N = 300
SEED = 7
HOLD = 0.95
TOL = 0.011
NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")


def reservoir(path, n=SAMPLE_N, seed=SEED):
    rng = random.Random(seed)
    out, cols = [], None
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for i, row in enumerate(csv.reader(f)):
            if i == 0:
                cols = row
                continue
            if len(row) != len(cols):
                continue
            if len(out) < n:
                out.append(row)
            else:
                j = rng.randint(0, i - 1)
                if j < n:
                    out[j] = row
    return cols, [dict(zip(cols, r)) for r in out]


def numeric_cols(cols, rows):
    ok = []
    for c in cols:
        vals = [r[c] for r in rows if r.get(c)]
        if vals and sum(bool(NUM_RE.match(v)) for v in vals) >= len(vals) * 0.95:
            ok.append(c)
    return ok


def text_cols(cols, rows):
    ok = []
    for c in cols:
        vals = [r[c] for r in rows if r.get(c)]
        if vals and sum(bool(NUM_RE.match(v)) for v in vals) < len(vals) * 0.5:
            ok.append(c)
    return ok


OPS = {
    "a == b * c": lambda b, c: b * c,
    "a == b + c": lambda b, c: b + c,
    "a == b - c": lambda b, c: b - c,
}


def _num(r, c):
    v = r.get(c, "")
    return float(v) if v and NUM_RE.match(v) else None


def arithmetic_holds(rows, a, b, c, op):
    fn = OPS[op]
    good = tot = 0
    for r in rows:
        av, bv, cv = _num(r, a), _num(r, b), _num(r, c)
        if av is None or bv is None or cv is None:
            continue
        tot += 1
        try:
            if abs(round(fn(bv, cv), 2) - av) <= TOL:
                good += 1
        except (ZeroDivisionError, OverflowError):
            pass
    return (good / tot if tot else 0.0), tot


def _tokens(s):
    return [t for t in re.split(r"[^A-Za-z0-9]+", s.lower()) if len(t) > 2]


def referential_holds(rows, a, b):
    good = tot = 0
    for r in rows:
        av, bv = r.get(a, ""), r.get(b, "")
        if not av or not bv:
            continue
        tot += 1
        toks = _tokens(bv)
        if toks and any(t in av.lower() for t in toks):
            good += 1
    return (good / tot if tot else 0.0), tot


def discover(cols, rows):
    found = []
    nums = numeric_cols(cols, rows)
    for a in nums:
        for b in nums:
            for c in nums:
                if len({a, b, c}) != 3:
                    continue
                for op in OPS:
                    rate, n = arithmetic_holds(rows, a, b, c, op)
                    if n >= 20 and rate >= HOLD:
                        found.append({"kind": "arithmetic",
                                      "expr": op.replace("a", a).replace("b", b).replace("c", c),
                                      "cols": [a, b, c], "op": op,
                                      "ref_hold_rate": round(rate, 4)})
    seen = set()
    found = [f for f in found if not (tuple(sorted(f["cols"])) + (f["op"],) in seen
                                      or seen.add(tuple(sorted(f["cols"])) + (f["op"],)))]
    txt = text_cols(cols, rows)
    for a in txt:
        for b in txt:
            if a == b:
                continue
            rate, n = referential_holds(rows, a, b)
            if n >= 20 and rate >= HOLD:
                found.append({"kind": "referential",
                              "expr": f"{a} contains a token from {b}",
                              "cols": [a, b], "ref_hold_rate": round(rate, 4)})
    return found


def verify(inv, rows):
    if inv["kind"] == "arithmetic":
        a, b, c = inv["cols"]
        return arithmetic_holds(rows, a, b, c, inv["op"])
    a, b = inv["cols"]
    return referential_holds(rows, a, b)


def run(ref_path, cand_path, sample=SAMPLE_N):
    rcols, rrows = reservoir(ref_path, sample)
    ccols, crows = reservoir(cand_path, sample)
    invs = discover(rcols, rrows)
    results = []
    for inv in invs:
        if not all(c in ccols for c in inv["cols"]):
            results.append({**inv, "candidate_hold_rate": None,
                            "status": "columns_missing_in_candidate"})
            continue
        rate, n = verify(inv, crows)
        rate = round(rate, 4)
        results.append({**inv, "candidate_hold_rate": rate, "n_checked": n,
                        "status": "BROKEN" if rate < HOLD else "holds"})
    return {
        "sampled_rows": {"reference": len(rrows), "candidate": len(crows)},
        "invariants_discovered_in_reference": len(invs),
        "invariants": results,
        "broken": [r["expr"] for r in results if r["status"] == "BROKEN"],
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n = SAMPLE_N
    if "--sample" in sys.argv:
        n = int(sys.argv[sys.argv.index("--sample") + 1])
    print(json.dumps(run(args[0], args[1], n), indent=2))


if __name__ == "__main__":
    main()
