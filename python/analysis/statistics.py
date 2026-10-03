"""Practical statistics: descriptive stats, distributions, correlation, outliers and
hypothesis tests. Results are reported exactly as computed (no p-hacking: tests and
thresholds were fixed before looking at results, alpha = 0.05)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

from python.config import OUTPUT_DIR, get_logger

log = get_logger("analysis.statistics")
OUT = OUTPUT_DIR / "statistics"
ALPHA = 0.05


def describe(series: pd.Series) -> dict:
    s = series.dropna()
    mode = s.round(-1).mode()
    return {"count": int(s.count()), "mean": s.mean(), "median": s.median(), "mode_rounded_10": float(mode.iat[0]) if len(mode) else None,
            "std": s.std(), "min": s.min(), "p25": s.quantile(.25), "p75": s.quantile(.75), "p90": s.quantile(.90),
            "p95": s.quantile(.95), "p99": s.quantile(.99), "max": s.max(), "skewness": stats.skew(s), "kurtosis": stats.kurtosis(s)}


def iqr_outliers(s: pd.Series, k: float = 1.5) -> dict:
    q1, q3 = s.quantile([.25, .75])
    lo, hi = q1 - k * (q3 - q1), q3 + k * (q3 - q1)
    n = int(((s < lo) | (s > hi)).sum())
    return {"lower_fence": lo, "upper_fence": hi, "outliers": n, "outlier_pct": 100 * n / len(s)}


def run_statistics(sales: pd.DataFrame, mart: dict[str, pd.DataFrame]) -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    orders = sales.groupby("order_id").agg(order_value=("net_revenue", "sum"), profit=("profit", "sum"),
                                           items=("quantity", "sum"), gross=("gross_amount", "sum"),
                                           discount=("discount_amount", "sum"), channel=("channel_name", "first"),
                                           loyalty=("loyalty_member", "first"), delivery_days=("delivery_days", "first"),
                                           customer_key=("customer_key", "first")).reset_index()
    orders["discount_rate"] = orders["discount"] / orders["gross"]
    orders["margin_pct"] = 100 * orders["profit"] / orders["order_value"]
    out: dict = {}

    desc = pd.DataFrame({"order_value": describe(orders["order_value"]), "items_per_order": describe(orders["items"]),
                         "discount_rate": describe(orders["discount_rate"]),
                         "delivery_days_online": describe(orders.loc[orders["channel"] != "Retail Store", "delivery_days"])})
    desc.round(3).to_csv(OUT / "descriptive_statistics.csv")
    out["descriptive"] = desc.round(3).to_dict()
    by_ch = orders.groupby("channel")["order_value"].describe(percentiles=[.25, .5, .75, .9]).round(2)
    by_ch.to_csv(OUT / "order_value_by_channel.csv")
    log_ov = np.log(orders["order_value"])
    out["distribution"] = {"order_value_skew": float(stats.skew(orders["order_value"])),
                           "log_order_value_skew": float(stats.skew(log_ov)),
                           "interpretation": "Order value is strongly right-skewed (few large Electronics baskets); "
                                             "median is a more representative 'typical order' than mean; log scale is close to symmetric."}
    out["outliers_order_value"] = iqr_outliers(orders["order_value"])
    corr = orders[["order_value", "items", "discount_rate", "margin_pct", "delivery_days"]].corr(method="spearman").round(3)
    corr.to_csv(OUT / "correlation_spearman.csv")
    out["correlation"] = corr.to_dict()

    tests = []
    # Test 1: deep discounts vs AOV
    deep = orders.loc[orders["discount_rate"] >= 0.15, "order_value"]
    low = orders.loc[orders["discount_rate"] < 0.15, "order_value"]
    u = stats.mannwhitneyu(deep, low, alternative="two-sided")
    t = stats.ttest_ind(np.log(deep), np.log(low), equal_var=False)
    tests.append({"name": "Deep discount (>=15%) vs low discount (<15%) - order value",
                  "hypothesis": "Orders with deeper discounts have a different order value than lightly discounted orders.",
                  "h0": "Median order value is the same for both groups.", "h1": "Median order value differs.",
                  "metric": "Order net value (INR)", "method": "Mann-Whitney U (non-normal data) + Welch t-test on log(order value)",
                  "group_a_n": len(deep), "group_b_n": len(low), "group_a_median": deep.median(), "group_b_median": low.median(),
                  "p_value_mannwhitney": u.pvalue, "p_value_welch_log": t.pvalue, "significant": bool(u.pvalue < ALPHA)})
    # Test 2: return rate Marketplace vs Website (two-proportion z-test)
    lines = sales.groupby("channel_name")["is_returned"].agg(["sum", "count"])
    a, b = lines.loc["Marketplace"], lines.loc["Website"]
    p1, p2 = a["sum"] / a["count"], b["sum"] / b["count"]
    pp = (a["sum"] + b["sum"]) / (a["count"] + b["count"])
    z = (p1 - p2) / np.sqrt(pp * (1 - pp) * (1 / a["count"] + 1 / b["count"]))
    pz = 2 * (1 - stats.norm.cdf(abs(z)))
    tests.append({"name": "Return rate: Marketplace vs Website", "hypothesis": "Marketplace order lines are returned more often than Website lines.",
                  "h0": "Return rates are equal.", "h1": "Return rates differ.", "metric": "Returned lines / total lines",
                  "method": "Two-proportion z-test", "group_a_n": int(a["count"]), "group_b_n": int(b["count"]),
                  "group_a_rate_pct": 100 * p1, "group_b_rate_pct": 100 * p2, "z": z, "p_value": pz, "significant": bool(pz < ALPHA)})
    # Test 3: loyalty members vs non-members - orders per customer
    cust = orders[orders["customer_key"] != -1].groupby(["customer_key", "loyalty"]).size().reset_index(name="orders")
    lm, nm = cust.loc[cust["loyalty"] == True, "orders"], cust.loc[cust["loyalty"] == False, "orders"]
    u3 = stats.mannwhitneyu(lm, nm, alternative="two-sided")
    tests.append({"name": "Loyalty members vs non-members - orders per customer",
                  "hypothesis": "Loyalty-programme members place more orders.", "h0": "Distribution of orders per customer is the same.",
                  "h1": "Distributions differ.", "metric": "Orders per customer (2023-2025)", "method": "Mann-Whitney U",
                  "group_a_n": len(lm), "group_b_n": len(nm), "group_a_mean": lm.mean(), "group_b_mean": nm.mean(),
                  "p_value": u3.pvalue, "significant": bool(u3.pvalue < ALPHA)})
    # Test 4: resolution time vs CSAT
    fs = mart["FactSupport"].dropna(subset=["resolution_hours", "csat_score"])
    rho, prho = stats.spearmanr(fs["resolution_hours"], fs["csat_score"])
    tests.append({"name": "Ticket resolution time vs CSAT", "hypothesis": "Slower resolution is associated with lower CSAT.",
                  "h0": "No monotonic association (rho = 0).", "h1": "rho != 0.", "metric": "Spearman rho",
                  "method": "Spearman rank correlation", "group_a_n": len(fs), "rho": rho, "p_value": prho, "significant": bool(prho < ALPHA)})
    # Test 5: is order value different across channels (Kruskal-Wallis)
    groups = [g["order_value"].values for _, g in orders.groupby("channel")]
    kw = stats.kruskal(*groups)
    tests.append({"name": "Order value across 4 sales channels", "hypothesis": "Typical order value differs by channel.",
                  "h0": "All channels share the same order-value distribution.", "h1": "At least one channel differs.",
                  "metric": "Order net value", "method": "Kruskal-Wallis H", "group_a_n": len(orders), "h_stat": kw.statistic,
                  "p_value": kw.pvalue, "significant": bool(kw.pvalue < ALPHA)})
    out["tests"] = tests
    pd.DataFrame(tests).to_csv(OUT / "hypothesis_tests.csv", index=False)
    with open(OUT / "statistics_summary.json", "w") as fh:
        json.dump(out, fh, indent=2, default=lambda x: float(x) if isinstance(x, (np.floating, np.integer)) else str(x))
    for tst in tests:
        p = tst.get("p_value", tst.get("p_value_mannwhitney"))
        log.info("Test %-55s p=%.4g significant=%s", tst["name"][:55], p, tst["significant"])
    return out
