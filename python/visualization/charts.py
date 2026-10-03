"""Reusable matplotlib chart helpers + the EDA chart set (saved to data/outputs/charts)."""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import numpy as np
import pandas as pd

from python.config import CHART_DIR, get_logger

log = get_logger("visualization.charts")
BLUE, ORANGE, GREEN, RED, GREY = "#2563EB", "#F59E0B", "#10B981", "#EF4444", "#6B7280"
PALETTE = [BLUE, ORANGE, GREEN, "#8B5CF6", RED, "#06B6D4", "#EC4899", GREY]
plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlesize": 12, "font.size": 9.5, "axes.grid": True,
                     "grid.alpha": 0.25})


def lakh_cr(x, _=None):
    """Indian number format for axes: ₹ L (lakh) / ₹ Cr (crore)."""
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:.1f} Cr"
    if abs(x) >= 1e5:
        return f"₹{x / 1e5:.0f} L"
    return f"₹{x:,.0f}"


def save(fig, name: str) -> str:
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    path = CHART_DIR / f"{name}.png"
    fig.tight_layout()
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return str(path)


def bar(df, x, y, title, name, color=BLUE, fmt=lakh_cr, horizontal=False, top=None):
    d = df.sort_values(y, ascending=horizontal).tail(top) if top else df
    fig, ax = plt.subplots(figsize=(8, 4.2))
    if horizontal:
        ax.barh(d[x].astype(str), d[y], color=color)
        ax.xaxis.set_major_formatter(mtick.FuncFormatter(fmt))
    else:
        ax.bar(d[x].astype(str), d[y], color=color)
        ax.yaxis.set_major_formatter(mtick.FuncFormatter(fmt))
        plt.setp(ax.get_xticklabels(), rotation=0 if len(d) < 7 else 35, ha="right" if len(d) >= 7 else "center")
    ax.set_title(title)
    return save(fig, name)


def make_eda_charts(k: dict, sales: pd.DataFrame, rfm: pd.DataFrame, dq_scores: pd.DataFrame) -> list[str]:
    paths = []
    mo = k["monthly"].copy()
    mo["dt"] = pd.to_datetime(mo["year_month"])
    fig, ax = plt.subplots(figsize=(10, 4.2))
    ax.plot(mo["dt"], mo["revenue"], color=BLUE, lw=2, label="Revenue")
    ax.plot(mo["dt"], mo["profit"], color=GREEN, lw=2, label="Profit")
    ax.plot(mo["dt"], mo["rolling_3m_revenue"] / 3, color=ORANGE, ls="--", lw=1.4, label="Revenue (3-month avg)")
    ax.yaxis.set_major_formatter(mtick.FuncFormatter(lakh_cr))
    ax.set_title("Monthly Revenue & Profit, 2023-2025 (synthetic data)")
    ax.legend(frameon=False)
    paths.append(save(fig, "01_monthly_revenue_profit"))

    fig, ax = plt.subplots(figsize=(10, 3.8))
    yoy = mo.dropna(subset=["yoy_growth_pct"])
    ax.bar(yoy["dt"], yoy["yoy_growth_pct"], width=20, color=[GREEN if v >= 0 else RED for v in yoy["yoy_growth_pct"]])
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_title("Year-over-Year Revenue Growth by Month")
    paths.append(save(fig, "02_yoy_growth"))

    paths.append(bar(k["category"], "category", "revenue", "Revenue by Category", "03_revenue_by_category", horizontal=True))
    fig, ax = plt.subplots(figsize=(8, 4))
    c = k["category"].sort_values("profit_margin_pct")
    ax.barh(c["category"], c["profit_margin_pct"], color=GREEN)
    ax.xaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_title("Profit Margin by Category")
    paths.append(save(fig, "04_margin_by_category"))
    paths.append(bar(k["region"], "region_name", "revenue", "Revenue by Region (Zone)", "05_revenue_by_region", color=ORANGE))
    paths.append(bar(k["channel"], "channel_name", "revenue", "Revenue by Sales Channel", "06_revenue_by_channel", color="#8B5CF6"))
    paths.append(bar(k["product"], "product_name", "revenue", "Top 10 Products by Revenue", "07_top_products", horizontal=True, top=10))

    p = k["pareto_customers"]
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.plot(p["customer_rank_pct"], p["cum_revenue_pct"], color=BLUE, lw=2)
    ax.axvline(20, color=GREY, ls="--")
    ax.set_xlabel("% of customers (ranked by revenue)")
    ax.set_ylabel("Cumulative % of revenue")
    ax.set_title("Customer Revenue Concentration (Pareto)")
    paths.append(save(fig, "08_pareto_customers"))

    coh = k["cohort_retention"].set_index("cohort_month")
    coh = coh.loc[coh.index >= "2024-01", [c for c in coh.columns if 1 <= int(c) <= 12]]
    fig, ax = plt.subplots(figsize=(10, 6))
    im = ax.imshow(coh.values, cmap="Blues", aspect="auto", vmin=0)
    ax.set_xticks(range(coh.shape[1]), [str(c) for c in coh.columns])
    ax.set_yticks(range(coh.shape[0]), coh.index)
    ax.set_xlabel("Months since first order")
    ax.set_title("Monthly Cohort Retention % (2024-2025 cohorts)")
    ax.grid(False)
    fig.colorbar(im, ax=ax, label="% of cohort active")
    paths.append(save(fig, "09_cohort_retention"))

    seg = rfm.groupby("segment").agg(customers=("customer_key", "count"), revenue=("monetary", "sum")).reset_index()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    seg = seg.sort_values("revenue")
    axes[0].barh(seg["segment"], seg["customers"], color=GREY)
    axes[0].set_title("Customers by RFM Segment")
    axes[1].barh(seg["segment"], seg["revenue"], color=BLUE)
    axes[1].xaxis.set_major_formatter(mtick.FuncFormatter(lakh_cr))
    axes[1].set_title("Revenue by RFM Segment")
    paths.append(save(fig, "10_rfm_segments"))

    rr = k["return_reasons"].sort_values("returns")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(rr["return_reason"], rr["returns"], color=RED)
    ax.set_title("Returns by Reason")
    paths.append(save(fig, "11_return_reasons"))

    ov = sales.groupby("order_id")["net_revenue"].sum()
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    axes[0].hist(ov.clip(upper=ov.quantile(.99)), bins=60, color=BLUE)
    axes[0].axvline(ov.mean(), color=RED, ls="--", label=f"Mean ₹{ov.mean():,.0f}")
    axes[0].axvline(ov.median(), color=GREEN, ls="--", label=f"Median ₹{ov.median():,.0f}")
    axes[0].legend(frameon=False)
    axes[0].set_title("Order Value Distribution (clipped at P99)")
    axes[1].hist(np.log10(ov), bins=60, color=ORANGE)
    axes[1].set_title("log10(Order Value) - near symmetric")
    paths.append(save(fig, "12_order_value_distribution"))

    sc = k["support_category"].sort_values("tickets")
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.barh(sc["ticket_category"], sc["median_resolution_hours"], color="#06B6D4")
    ax.set_xlabel("Median resolution time (hours)")
    ax.set_title("Support: Median Resolution Time by Ticket Category")
    paths.append(save(fig, "13_support_resolution"))

    d = dq_scores.pivot_table(index="table", columns="layer", values="dq_score").reset_index()
    fig, ax = plt.subplots(figsize=(9, 4))
    x = np.arange(len(d))
    ax.bar(x - 0.2, d["raw"], 0.4, label="Raw", color=GREY)
    ax.bar(x + 0.2, d["clean"], 0.4, label="Clean", color=GREEN)
    ax.set_xticks(x, d["table"], rotation=25, ha="right")
    ax.set_ylim(min(90, d["raw"].min() - 1), 100.5)
    ax.set_title("Data Quality Score by Table: Raw vs Clean")
    ax.legend(frameon=False)
    paths.append(save(fig, "14_data_quality_score"))

    db = k["discount_band"].set_index("discount_band").loc[["0%", "1-10%", "11-20%", ">20%"]].reset_index()
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.bar(db["discount_band"], db["profit_margin_pct"], color=ORANGE)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter())
    ax.set_title("Profit Margin by Discount Band")
    paths.append(save(fig, "15_discount_vs_margin"))
    log.info("Saved %d charts to %s", len(paths), CHART_DIR)
    return paths
