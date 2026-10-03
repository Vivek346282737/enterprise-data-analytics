"""RFM customer segmentation (explainable, rule-based).

Recency   = days between the customer's last order and the snapshot date (2026-01-01). Lower = better.
Frequency = number of distinct (non-cancelled) orders.
Monetary  = total net revenue.
Each metric is scored 1-5 by quintile (5 = best). Frequency is ranked first to break ties.

Segment rules (evaluated top to bottom, first match wins):
  New         first order within the last 90 days
  High Value  R >= 3 and F >= 4 and M >= 4
  Loyal       R >= 3 and F >= 3
  At Risk     R <= 2 and (F >= 3 or M >= 4)   - used to buy often / spend a lot, but not recently
  Hibernating R = 1                            - long inactive, low value (churn proxy)
  Occasional  everyone else
"""
from __future__ import annotations

import pandas as pd

from python.config import ANALYSIS_DATE, OUTPUT_DIR, get_logger

log = get_logger("analysis.segmentation")


def rfm(fact_sales: pd.DataFrame, dim_date: pd.DataFrame) -> pd.DataFrame:
    snap = pd.Timestamp(ANALYSIS_DATE)
    f = fact_sales[fact_sales["customer_key"] != -1].merge(dim_date[["date_key", "date"]], on="date_key")
    g = f.groupby("customer_key").agg(last_order=("date", "max"), first_order=("date", "min"),
                                      frequency=("order_id", "nunique"), monetary=("net_revenue", "sum")).reset_index()
    g["recency_days"] = (snap - g["last_order"]).dt.days
    g["r_score"] = pd.qcut(g["recency_days"].rank(method="first"), 5, labels=[5, 4, 3, 2, 1]).astype(int)
    g["f_score"] = pd.qcut(g["frequency"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    g["m_score"] = pd.qcut(g["monetary"].rank(method="first"), 5, labels=[1, 2, 3, 4, 5]).astype(int)
    g["rfm_score"] = g["r_score"].astype(str) + g["f_score"].astype(str) + g["m_score"].astype(str)
    is_new = (snap - g["first_order"]).dt.days <= 90

    def seg(row, new):
        if new:
            return "New"
        r, fq, m = row.r_score, row.f_score, row.m_score
        if r >= 3 and fq >= 4 and m >= 4:
            return "High Value"
        if r >= 3 and fq >= 3:
            return "Loyal"
        if r <= 2 and (fq >= 3 or m >= 4):
            return "At Risk"
        if r == 1:
            return "Hibernating"
        return "Occasional"

    g["segment"] = [seg(row, n) for row, n in zip(g.itertuples(), is_new)]
    g["monetary"] = g["monetary"].round(2)
    summary = g.groupby("segment").agg(customers=("customer_key", "count"), avg_recency_days=("recency_days", "mean"),
                                       avg_orders=("frequency", "mean"), avg_revenue=("monetary", "mean"),
                                       total_revenue=("monetary", "sum")).reset_index()
    summary["customer_share_pct"] = (100 * summary["customers"] / summary["customers"].sum()).round(2)
    summary["revenue_share_pct"] = (100 * summary["total_revenue"] / summary["total_revenue"].sum()).round(2)
    summary = summary.round(2).sort_values("total_revenue", ascending=False)
    out = OUTPUT_DIR / "segmentation"
    out.mkdir(parents=True, exist_ok=True)
    g.to_csv(out / "customer_rfm.csv", index=False)
    summary.to_csv(out / "segment_summary.csv", index=False)
    for _, r in summary.iterrows():
        log.info("Segment %-12s customers=%5d revenue_share=%.1f%%", r["segment"], r["customers"], r["revenue_share_pct"])
    return g
