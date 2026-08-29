"""Streaming column profiler.

Reads a CSV row by row and emits a compact statistical summary. Never holds
the file in memory, so profile size is independent of row count -- this is
what lets the agent reason about a 50k-row feed without putting rows in
context.

Statistics are chosen so that silent semantic drift becomes visible:
  numeric magnitude        -> unit changes (dollars -> cents)
  zero-fraction rate       -> precision loss
  decimal-place histogram  -> formatting changes
  top-k values             -> enum / case drift
  null rate                -> null surges
  date pattern             -> format changes
  non-ascii rate           -> encoding corruption
  row + duplicate counts   -> duplicate injection
  inferred dtype           -> type changes
"""
import csv, json, re, sys, hashlib
from collections import Counter
from pathlib import Path

DATE_PATTERNS = [
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "YYYY-MM-DD"),
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "DD/MM/YYYY or MM/DD/YYYY"),
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"), "DD-MM-YYYY or MM-DD-YYYY"),
    (re.compile(r"^\d{4}/\d{2}/\d{2}$"), "YYYY/MM/DD"),
    (re.compile(r"^\d{8}$"), "YYYYMMDD"),
]
INT_RE = re.compile(r"^-?\d+$")
FLOAT_RE = re.compile(r"^-?\d*\.\d+$")


class ColumnStats:
    __slots__ = ("name", "n", "nulls", "ints", "floats", "values", "numeric_sum",
                 "numeric_min", "numeric_max", "decimals", "date_fmts",
                 "non_ascii", "lengths", "samples", "distinct_probe", "zero_frac")

    def __init__(self, name):
        self.name = name
        self.n = 0
        self.nulls = 0
        self.ints = 0
        self.floats = 0
        self.values = Counter()
        self.numeric_sum = 0.0
        self.numeric_min = None
        self.numeric_max = None
        self.decimals = Counter()
        self.date_fmts = Counter()
        self.non_ascii = 0
        self.lengths = Counter()
        self.samples = []
        self.distinct_probe = set()
        self.zero_frac = 0

    def add(self, v):
        self.n += 1
        if v == "" or v is None:
            self.nulls += 1
            return
        if len(self.samples) < 5:
            self.samples.append(v)
        if len(self.values) < 5000:
            self.values[v] += 1
        if len(self.distinct_probe) < 20000:
            self.distinct_probe.add(v)
        self.lengths[len(v)] += 1
        if any(ord(c) > 127 for c in v):
            self.non_ascii += 1
        if INT_RE.match(v):
            self.ints += 1
            f = float(v)
            self.decimals[0] += 1
        elif FLOAT_RE.match(v):
            self.floats += 1
            f = float(v)
            self.decimals[len(v.split(".")[1])] += 1
        else:
            for pat, label in DATE_PATTERNS:
                if pat.match(v):
                    self.date_fmts[label] += 1
                    break
            return
        if f == int(f):
            self.zero_frac += 1
        self.numeric_sum += f
        self.numeric_min = f if self.numeric_min is None else min(self.numeric_min, f)
        self.numeric_max = f if self.numeric_max is None else max(self.numeric_max, f)

    def result(self):
        non_null = self.n - self.nulls
        numeric = self.ints + self.floats
        if numeric and numeric >= non_null * 0.95:
            dtype = "int" if self.floats == 0 else "float"
        elif self.date_fmts and sum(self.date_fmts.values()) >= non_null * 0.95:
            dtype = "date"
        elif non_null == 0:
            dtype = "empty"
        else:
            dtype = "str"
        out = {
            "name": self.name,
            "dtype": dtype,
            "null_rate": round(self.nulls / self.n, 4) if self.n else 0.0,
            "distinct_approx": len(self.distinct_probe),
            "distinct_capped": len(self.distinct_probe) >= 20000,
            "samples": self.samples,
        }
        if numeric:
            out["numeric"] = {
                "min": self.numeric_min, "max": self.numeric_max,
                "mean": round(self.numeric_sum / numeric, 4),
                "decimal_places": dict(sorted(self.decimals.items())),
                "zero_fraction_rate": round(self.zero_frac / numeric, 4),
            }
        if self.date_fmts:
            out["date_formats"] = dict(self.date_fmts.most_common(3))
        if self.non_ascii:
            out["non_ascii_rate"] = round(self.non_ascii / max(non_null, 1), 4)
        if dtype == "str" and len(self.distinct_probe) <= 50:
            out["top_values"] = dict(self.values.most_common(20))
        elif dtype == "str":
            out["top_values"] = dict(self.values.most_common(5))
        if self.lengths:
            ks = sorted(self.lengths)
            out["length_min_max"] = [ks[0], ks[-1]]
        return out


def profile(path, top_k=20):
    path = Path(path)
    cols, stats, rows = None, {}, 0
    row_hashes = Counter()
    with open(path, newline="", encoding="utf-8", errors="replace") as f:
        for i, row in enumerate(csv.reader(f)):
            if i == 0:
                cols = row
                stats = {c: ColumnStats(c) for c in cols}
                continue
            rows += 1
            if len(row) != len(cols):
                continue
            h = hashlib.md5("\x1f".join(row).encode()).hexdigest()[:12]
            if len(row_hashes) < 200000:
                row_hashes[h] += 1
            for c, v in zip(cols, row):
                stats[c].add(v)
    dup_rows = sum(c - 1 for c in row_hashes.values() if c > 1)
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "rows": rows,
        "columns": cols,
        "n_columns": len(cols) if cols else 0,
        "duplicate_rows": dup_rows,
        "duplicate_rate": round(dup_rows / rows, 4) if rows else 0.0,
        "column_stats": [stats[c].result() for c in cols] if cols else [],
    }


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    print(json.dumps(profile(args[0]), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
