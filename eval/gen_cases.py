"""Generate 12 deterministic drift-detection cases."""
import csv, json, random, hashlib, sys
from pathlib import Path

SEED = 20260828
ROWS = 200
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "eval/cases")

COLS = ["order_id", "customer_id", "customer_name", "order_date",
        "status", "quantity", "unit_price", "amount", "email", "discount_pct"]
FIRST = ["Aditi", "Rahul", "Meera", "Vikram", "Sana", "Arjun", "Nisha", "Kabir",
         "Priya", "Rohan", "Zara", "Dev", "Anya", "Ishaan", "Tara", "Omar"]
LAST = ["Sharma", "Iyer", "Khan", "Reddy", "Bose", "Nair", "Gill", "Menon",
        "Kapoor", "Rao", "Das", "Chopra", "Verma", "Joshi"]
STATUS = ["pending", "shipped", "delivered", "cancelled"]

def base_rows(rng, n=ROWS, start_id=1000):
    rows = []
    for i in range(n):
        qty = rng.randint(1, 9)
        price = round(rng.uniform(4.99, 899.99), 2)
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        rows.append({
            "order_id": start_id + i,
            "customer_id": f"C{rng.randint(10000, 99999)}",
            "customer_name": name,
            "order_date": f"2026-08-{rng.randint(1, 27):02d}",
            "status": rng.choice(STATUS),
            "quantity": qty,
            "unit_price": f"{price:.2f}",
            "amount": f"{round(qty * price, 2):.2f}",
            "email": "" if rng.random() < 0.02 else
                     f"{name.split()[0].lower()}{rng.randint(1,99)}@example.com",
            "discount_pct": f"{rng.choice([0, 0, 0, 5, 10, 15]):.1f}",
        })
    return rows

def write_csv(path, rows, cols=None):
    cols = cols or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

def d_rename(rows, cols, rng):
    for r in rows:
        r["cust_id"] = r.pop("customer_id")
    cols = ["cust_id" if c == "customer_id" else c for c in cols]
    return rows, cols, dict(defect_type="column_renamed", affected_columns=["customer_id"],
        severity="high", schema_check_catches=True, description="customer_id renamed to cust_id")

def d_drop(rows, cols, rng):
    for r in rows:
        r.pop("discount_pct")
    cols = [c for c in cols if c != "discount_pct"]
    return rows, cols, dict(defect_type="column_dropped", affected_columns=["discount_pct"],
        severity="high", schema_check_catches=True, description="discount_pct column removed")

def d_add(rows, cols, rng):
    for r in rows:
        r["promo_code"] = rng.choice(["", "", "SAVE10", "FREESHIP"])
    return rows, cols + ["promo_code"], dict(defect_type="column_added",
        affected_columns=["promo_code"], severity="low", schema_check_catches=True,
        description="new promo_code column appeared")

def d_type(rows, cols, rng):
    for r in rows:
        r["order_id"] = f"ORD-{r['order_id']}"
    return rows, cols, dict(defect_type="type_changed", affected_columns=["order_id"],
        severity="high", schema_check_catches=True,
        description="order_id changed from integer to prefixed string")

def d_dateformat(rows, cols, rng):
    for r in rows:
        y, m, d = r["order_date"].split("-")
        r["order_date"] = f"{d}/{m}/{y}"
    return rows, cols, dict(defect_type="date_format_changed", affected_columns=["order_date"],
        severity="high", schema_check_catches=False,
        description="order_date switched from ISO to DD/MM/YYYY")

def d_nulls(rows, cols, rng):
    for r in rows:
        if rng.random() < 0.60:
            r["email"] = ""
    return rows, cols, dict(defect_type="null_surge", affected_columns=["email"],
        severity="medium", schema_check_catches=False,
        description="email null rate jumped from ~2% to ~60%")

def d_units(rows, cols, rng):
    for r in rows:
        r["amount"] = str(int(round(float(r["amount"]) * 100)))
    return rows, cols, dict(defect_type="unit_change", affected_columns=["amount"],
        severity="critical", schema_check_catches=False,
        description="amount switched from dollars to cents (100x)")

def d_enum(rows, cols, rng):
    for r in rows:
        r["status"] = r["status"].upper()
    return rows, cols, dict(defect_type="enum_value_drift", affected_columns=["status"],
        severity="high", schema_check_catches=False,
        description="status values changed to uppercase")

def d_precision(rows, cols, rng):
    for r in rows:
        r["amount"] = f"{round(float(r['amount'])):.2f}"
        r["unit_price"] = f"{round(float(r['unit_price'])):.2f}"
    return rows, cols, dict(defect_type="precision_loss",
        affected_columns=["amount", "unit_price"], severity="high",
        schema_check_catches=False,
        description="monetary values rounded to whole units, decimals lost")

def d_encoding(rows, cols, rng):
    for r in rows:
        if rng.random() < 0.3:
            r["customer_name"] = r["customer_name"].replace("a", "\u00c3\u00a1")
    return rows, cols, dict(defect_type="encoding_change", affected_columns=["customer_name"],
        severity="medium", schema_check_catches=False,
        description="mojibake in customer_name from encoding mismatch")

def d_dupes(rows, cols, rng):
    extra = [dict(r) for r in rng.sample(rows, int(len(rows) * 0.15))]
    return rows + extra, cols, dict(defect_type="duplicate_rows",
        affected_columns=["order_id"], severity="critical", schema_check_catches=False,
        description="15% of rows duplicated, causing double counting")

def d_none(rows, cols, rng):
    return rows, cols, dict(defect_type="none", affected_columns=[], severity="none",
        schema_check_catches=False,
        description="no drift; normal day-over-day variation only")

CASES = [
    ("01_column_renamed", d_rename), ("02_column_dropped", d_drop),
    ("03_column_added", d_add), ("04_type_changed", d_type),
    ("05_date_format_changed", d_dateformat), ("06_null_surge", d_nulls),
    ("07_unit_change_currency", d_units), ("08_enum_value_drift", d_enum),
    ("09_precision_loss", d_precision), ("10_encoding_change", d_encoding),
    ("11_duplicate_rows", d_dupes), ("12_control_no_defect", d_none),
]

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for i, (cid, fn) in enumerate(CASES):
        rng = random.Random(SEED + i)
        d = OUT / cid
        d.mkdir(exist_ok=True)
        day1 = base_rows(rng, start_id=1000)
        day2 = base_rows(rng, start_id=2000)
        rows, cols, truth = fn(day2, list(COLS), rng)
        write_csv(d / "day1.csv", day1, COLS)
        write_csv(d / "day2.csv", rows, cols)
        truth.update(case_id=cid, has_defect=(truth["defect_type"] != "none"))
        (d / "truth.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
        index.append({k: truth[k] for k in ("case_id", "has_defect", "defect_type",
                                            "severity", "schema_check_catches")})
    (OUT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    h = hashlib.sha256()
    for p in sorted(OUT.rglob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    print(f"generated {len(CASES)} cases -> {OUT}")
    print(f"corpus sha256: {h.hexdigest()[:16]}")
    hard = [c for c in index if not c["schema_check_catches"] and c["has_defect"]]
    print(f"schema-invisible defects: {len(hard)}/{len(index)-1}")

if __name__ == "__main__":
    main()
