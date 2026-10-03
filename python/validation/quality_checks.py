"""Rule-based data-quality checks + data-quality scoring.

The same engine is run on the RAW layer (before cleaning) and on the CLEAN layer (after
cleaning) so the improvement is measurable. Each check returns one result row:
table, dimension, check, column, failed_rows, checked_rows, pass_rate.
Dimensions: Completeness, Uniqueness, Validity, Consistency, Integrity.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from python.config import OUTPUT_DIR, get_logger

log = get_logger("validation.quality")

CANON = {
    "region_name": {"North", "South", "East", "West", "Central"},
    "category": {"Electronics", "Fashion", "Home & Kitchen", "Beauty", "Sports", "Books", "Grocery"},
    "gender": {"Male", "Female"},
    "channel": {"Website", "Mobile App", "Marketplace", "Retail Store"},
    "order_status": {"Delivered", "Cancelled", "Shipped"},
    "payment_method": {"UPI", "Credit Card", "Debit Card", "Net Banking", "Cash on Delivery", "Wallet", "Cash"},
    "return_reason": {"Size/Fit Issue", "Damaged in Transit", "Defective Product", "Not as Described",
                      "Changed Mind", "Wrong Item Delivered", "Late Delivery"},
    "ticket_category": {"Return/Refund", "Delivery Delay", "Payment Issue", "Product Query", "Account/Login", "Product Defect"},
    "priority": {"Low", "Medium", "High", "Critical"},
}

# table -> rules. Works for raw and clean (clean adds channel_id instead of channel text).
SPEC = {
    "regions": {"pk": "region_id", "required": ["region_id", "city", "region_name"],
                "domain": ["region_name"], "text": ["city", "region_name"]},
    "customers": {"pk": "customer_id", "required": ["customer_id", "first_name", "email", "region_id", "signup_date"],
                  "numeric": {"age": (18, 100)}, "date": {"signup_date": ("2022-01-01", "2025-12-31")},
                  "domain": ["gender"], "text": ["first_name", "last_name", "email"], "business_key": "email",
                  "fk": [("region_id", "regions", "region_id")]},
    "products": {"pk": "product_id", "required": ["product_id", "product_name", "category", "unit_price", "unit_cost"],
                 "numeric": {"unit_price": (1, 500000), "unit_cost": (0.01, 500000)},
                 "domain": ["category"], "text": ["product_name", "category"]},
    "orders": {"pk": "order_id", "required": ["order_id", "customer_id", "order_date", "region_id"],
               "date": {"order_date": ("2023-01-01", "2025-12-31")},
               "domain": ["channel", "order_status"], "text": ["order_status"],
               "fk": [("customer_id", "customers", "customer_id"), ("region_id", "regions", "region_id")]},
    "order_items": {"pk": "order_item_id", "required": ["order_item_id", "order_id", "product_id", "quantity", "unit_price", "line_amount"],
                    "numeric": {"quantity": (1, 50), "unit_price": (1, 1_000_000), "discount_pct": (0, 0.6), "line_amount": (0, 5_000_000)},
                    "fk": [("order_id", "orders", "order_id"), ("product_id", "products", "product_id")], "outlier": "line_amount"},
    "payments": {"pk": "payment_id", "required": ["payment_id", "order_id", "payment_method", "amount"],
                 "numeric": {"amount": (0, 10_000_000)}, "domain": ["payment_method"],
                 "fk": [("order_id", "orders", "order_id")]},
    "returns": {"pk": "return_id", "required": ["return_id", "order_item_id", "return_date", "return_reason"],
                "numeric": {"return_qty": (1, 50), "refund_amount": (0, 5_000_000)},
                "date": {"return_date": ("2023-01-01", "2026-01-31")}, "domain": ["return_reason"],
                "fk": [("order_item_id", "order_items", "order_item_id")]},
    "support_tickets": {"pk": "ticket_id", "required": ["ticket_id", "order_id", "created_at", "priority", "ticket_category"],
                        "numeric": {"csat_score": (1, 5)}, "domain": ["ticket_category", "priority"],
                        "fk": [("order_id", "orders", "order_id")]},
}


def _res(table, dim, check, col, failed, total):
    total = int(total)
    failed = int(failed)
    return {"table": table, "dimension": dim, "check": check, "column": col, "failed_rows": failed,
            "checked_rows": total, "pass_rate": round(100 * (1 - failed / total), 2) if total else 100.0}


def run_checks(tables: dict[str, pd.DataFrame], layer: str) -> pd.DataFrame:
    results = []
    for t, rule in SPEC.items():
        if t not in tables:
            continue
        df = tables[t]
        n = len(df)
        for c in rule.get("required", []):
            if c in df:
                results.append(_res(t, "Completeness", "not_null", c, df[c].isna().sum(), n))
        results.append(_res(t, "Uniqueness", "exact_duplicate_rows", "*", df.duplicated().sum(), n))
        pk = rule["pk"]
        results.append(_res(t, "Uniqueness", "duplicate_primary_key", pk, df[pk].duplicated().sum(), n))
        if bk := rule.get("business_key"):
            key = df[bk].dropna().astype(str).str.strip().str.lower()
            results.append(_res(t, "Uniqueness", "duplicate_business_key", bk, key.duplicated().sum(), len(key)))
        for c, (lo, hi) in rule.get("numeric", {}).items():
            if c not in df:
                continue
            raw = df[c].dropna()
            num = pd.to_numeric(raw, errors="coerce")
            results.append(_res(t, "Validity", "numeric_type", c, num.isna().sum(), len(raw)))
            results.append(_res(t, "Validity", f"range_{lo}_{hi}", c, ((num < lo) | (num > hi)).sum(), num.notna().sum()))
        for c, (lo, hi) in rule.get("date", {}).items():
            raw = df[c].dropna()
            d = pd.to_datetime(raw.astype(str), errors="coerce", format="ISO8601")
            results.append(_res(t, "Validity", "valid_iso_date", c, d.isna().sum(), len(raw)))
            results.append(_res(t, "Validity", "date_in_business_window", c,
                                ((d < pd.Timestamp(lo)) | (d > pd.Timestamp(hi))).sum(), d.notna().sum()))
        for c in rule.get("domain", []):
            col = c if c in df else ("channel_name" if c == "channel" and "channel_name" in df else None)
            if col is None:
                continue
            raw = df[col].dropna()
            results.append(_res(t, "Consistency", "allowed_values", col, (~raw.isin(CANON[c])).sum(), len(raw)))
        for c in rule.get("text", []):
            raw = df[c].dropna().astype(str)
            results.append(_res(t, "Consistency", "no_extra_whitespace", c, (raw != raw.str.strip()).sum(), len(raw)))
        for c, pt, pc in rule.get("fk", []):
            if pt in tables and c in df:
                parent = set(tables[pt][pc].dropna())
                v = df[c].dropna()
                results.append(_res(t, "Integrity", f"fk_{pt}", c, (~v.isin(parent)).sum(), len(v)))
        if oc := rule.get("outlier"):
            v = pd.to_numeric(df[oc], errors="coerce").dropna()
            q1, q3 = v.quantile([0.25, 0.75])
            hi = q3 + 3 * (q3 - q1)  # extreme outliers (3 x IQR) are flagged, not failed
            results.append(_res(t, "Validity", "extreme_outlier_3xIQR(info)", oc, (v > hi).sum(), len(v)))
    # cross-table business rules
    if {"orders", "support_tickets"} <= tables.keys():
        s = tables["support_tickets"]
        ca = pd.to_datetime(s["created_at"], errors="coerce")
        ra = pd.to_datetime(s["resolved_at"], errors="coerce")
        results.append(_res("support_tickets", "Validity", "resolved_after_created", "resolved_at", (ra < ca).sum(), ra.notna().sum()))
    res = pd.DataFrame(results)
    res.insert(0, "layer", layer)
    out = OUTPUT_DIR / "data_quality"
    out.mkdir(parents=True, exist_ok=True)
    res.to_csv(out / f"dq_checks_{layer}.csv", index=False)
    return res


def quality_score(results: pd.DataFrame) -> pd.DataFrame:
    """Score = mean pass rate per table x dimension (info-only checks excluded); overall = mean of tables."""
    r = results[~results["check"].str.contains(r"\(info\)")]
    by = r.groupby(["layer", "table", "dimension"])["pass_rate"].mean().unstack("dimension")
    by["dq_score"] = by.mean(axis=1)
    by = by.round(2).reset_index()
    return by


def summarize(results: pd.DataFrame) -> float:
    sc = quality_score(results)
    overall = round(float(sc["dq_score"].mean()), 2)
    failed = results[(results["failed_rows"] > 0) & ~results["check"].str.contains(r"\(info\)")]
    log.info("[%s] checks=%d failing_checks=%d failed_rows=%d overall_DQ_score=%.2f",
             results["layer"].iat[0], len(results), len(failed), failed["failed_rows"].sum(), overall)
    return overall
