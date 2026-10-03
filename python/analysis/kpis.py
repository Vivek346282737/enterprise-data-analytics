"""KPI generation from the star schema. Every output is saved to data/outputs/kpis/*.csv."""
from __future__ import annotations

import numpy as np
import pandas as pd

from python.config import ANALYSIS_DATE, OUTPUT_DIR, get_logger

log = get_logger("analysis.kpis")
OUT = OUTPUT_DIR / "kpis"


def sales_view(m: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """FactSales joined to all dimensions (analysis convenience view)."""
    return (m["FactSales"]
            .merge(m["DimDate"][["date_key", "date", "year", "month", "year_month"]], on="date_key")
            .merge(m["DimProduct"][["product_key", "product_id", "product_name", "category", "sub_category", "brand"]], on="product_key")
            .merge(m["DimRegion"][["region_key", "city", "state", "region_name"]], on="region_key", how="left")
            .merge(m["DimChannel"][["channel_key", "channel_name"]], on="channel_key")
            .merge(m["DimCustomer"][["customer_key", "customer_id", "segment", "loyalty_member", "cohort_month"]], on="customer_key"))


def _perf(df: pd.DataFrame, by, total_rev: float) -> pd.DataFrame:
    g = df.groupby(by).agg(revenue=("net_revenue", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"),
                           units=("quantity", "sum"), customers=("customer_key", "nunique"),
                           discount=("discount_amount", "sum"), gross=("gross_amount", "sum"),
                           lines=("sales_key", "count"), returned_lines=("is_returned", "sum")).reset_index()
    g["profit_margin_pct"] = 100 * g["profit"] / g["revenue"]
    g["aov"] = g["revenue"] / g["orders"]
    g["avg_discount_pct"] = 100 * g["discount"] / g["gross"]
    g["return_rate_pct"] = 100 * g["returned_lines"] / g["lines"]
    g["revenue_share_pct"] = 100 * g["revenue"] / total_rev
    return g.round(2).sort_values("revenue", ascending=False)


def compute_kpis(m: dict[str, pd.DataFrame], clean: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame | dict]:
    OUT.mkdir(parents=True, exist_ok=True)
    s = sales_view(m)
    total_rev = s["net_revenue"].sum()
    orders_all = clean["orders"]
    res: dict[str, pd.DataFrame | dict] = {}

    headline = {
        "total_revenue": total_rev, "total_cost": s["cost_amount"].sum(), "total_profit": s["profit"].sum(),
        "profit_margin_pct": 100 * s["profit"].sum() / total_rev, "total_orders": s["order_id"].nunique(),
        "total_customers": s.loc[s["customer_key"] != -1, "customer_key"].nunique(),
        "units_sold": int(s["quantity"].sum()), "aov": total_rev / s["order_id"].nunique(),
        "orders_per_customer": s.loc[s["customer_key"] != -1, "order_id"].nunique() / s.loc[s["customer_key"] != -1, "customer_key"].nunique(),
        "avg_discount_pct": 100 * s["discount_amount"].sum() / s["gross_amount"].sum(),
        "return_rate_lines_pct": 100 * s["is_returned"].mean(),
        "refund_value": m["FactReturns"]["refund_amount"].sum(),
        "refund_pct_of_revenue": 100 * m["FactReturns"]["refund_amount"].sum() / total_rev,
        "cancellation_rate_pct": 100 * (orders_all["order_status"] == "Cancelled").mean(),
        "on_time_delivery_pct": 100 * s.drop_duplicates("order_id")["is_on_time"].mean(),
        "avg_delivery_days_online": s[s["channel_name"] != "Retail Store"].drop_duplicates("order_id")["delivery_days"].mean(),
    }
    repeat = s[s["customer_key"] != -1].groupby("customer_key")["order_id"].nunique()
    headline["repeat_customer_pct"] = 100 * (repeat >= 2).mean()
    fs = m["FactSupport"]
    headline.update({"support_tickets": len(fs), "tickets_per_100_orders": 100 * len(fs) / orders_all["order_id"].nunique(),
                     "median_resolution_hours": fs["resolution_hours"].median(), "sla_met_pct": 100 * fs["sla_met"].mean(),
                     "avg_csat": fs["csat_score"].mean()})
    headline = {k: round(float(v), 2) for k, v in headline.items()}
    pd.Series(headline, name="value").rename_axis("kpi").to_csv(OUT / "headline_kpis.csv")
    res["headline"] = headline

    # monthly trend with MoM, YoY, running and rolling totals
    mo = s.groupby("year_month").agg(revenue=("net_revenue", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"),
                                     customers=("customer_key", "nunique"), units=("quantity", "sum")).reset_index()
    mo["aov"] = mo["revenue"] / mo["orders"]
    mo["profit_margin_pct"] = 100 * mo["profit"] / mo["revenue"]
    mo["mom_growth_pct"] = 100 * mo["revenue"].pct_change()
    mo["yoy_growth_pct"] = 100 * mo["revenue"].pct_change(12)
    mo["running_revenue"] = mo["revenue"].cumsum()
    mo["rolling_3m_revenue"] = mo["revenue"].rolling(3).sum()
    mo["rolling_12m_revenue"] = mo["revenue"].rolling(12).sum()
    first = m["DimCustomer"].dropna(subset=["cohort_month"]).groupby("cohort_month").size()
    mo["new_customers"] = mo["year_month"].map(first).fillna(0).astype(int)
    res["monthly"] = mo.round(2)

    yr = s.groupby("year").agg(revenue=("net_revenue", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"),
                               customers=("customer_key", "nunique")).reset_index()
    yr["aov"] = yr["revenue"] / yr["orders"]
    yr["yoy_revenue_growth_pct"] = 100 * yr["revenue"].pct_change()
    yr["profit_margin_pct"] = 100 * yr["profit"] / yr["revenue"]
    res["yearly"] = yr.round(2)

    res["category"] = _perf(s, "category", total_rev)
    res["region"] = _perf(s, "region_name", total_rev)
    res["city"] = _perf(s, ["region_name", "city"], total_rev)
    res["channel"] = _perf(s, "channel_name", total_rev)
    prod = _perf(s, ["product_id", "product_name", "category"], total_rev)
    prod["revenue_rank"] = prod["revenue"].rank(ascending=False, method="dense").astype(int)
    res["product"] = prod
    res["discount_band"] = _perf(s.assign(discount_band=pd.cut(s["discount_pct"], [-0.01, 0, 0.10, 0.20, 0.60],
                                                               labels=["0%", "1-10%", "11-20%", ">20%"]).astype(str)),
                                 "discount_band", total_rev)
    res["payment_method"] = _perf(s, "payment_method", total_rev)

    # Pareto: share of revenue from top 20% customers / products
    cust_rev = s[s["customer_key"] != -1].groupby("customer_key")["net_revenue"].sum().sort_values(ascending=False)
    cum = cust_rev.cumsum() / cust_rev.sum()
    pareto = pd.DataFrame({"customer_rank_pct": np.arange(1, len(cum) + 1) / len(cum) * 100, "cum_revenue_pct": cum.values * 100})
    res["pareto_customers"] = pareto.iloc[:: max(1, len(pareto) // 200)].round(2)
    top20 = cust_rev.head(int(len(cust_rev) * 0.2)).sum() / cust_rev.sum() * 100
    p_rev = s.groupby("product_key")["net_revenue"].sum().sort_values(ascending=False)
    top20p = p_rev.head(int(len(p_rev) * 0.2)).sum() / p_rev.sum() * 100
    headline["top20pct_customers_revenue_share"] = round(float(top20), 2)
    headline["top20pct_products_revenue_share"] = round(float(top20p), 2)

    # cohort retention (share of cohort ordering again N months after first order)
    cs = s[s["customer_key"] != -1][["customer_key", "year_month", "cohort_month"]].drop_duplicates()
    cs["period"] = (pd.PeriodIndex(cs["year_month"], freq="M") - pd.PeriodIndex(cs["cohort_month"], freq="M")).map(lambda x: x.n)
    coh = cs.groupby(["cohort_month", "period"])["customer_key"].nunique().unstack(fill_value=0)
    ret = (coh.div(coh[0], axis=0) * 100).round(1)
    res["cohort_retention"] = ret.loc[:, [c for c in ret.columns if c <= 12]].reset_index()
    headline["avg_month1_retention_pct"] = round(float(ret[1].iloc[:-1].mean()), 2)
    headline["avg_month3_retention_pct"] = round(float(ret[3].iloc[:-3].mean()), 2)

    # returns & operations
    fr = m["FactReturns"].merge(m["DimProduct"][["product_key", "category"]], on="product_key")
    rr = fr.groupby("return_reason").agg(returns=("return_key", "count"), refund=("refund_amount", "sum")).reset_index()
    rr["share_pct"] = 100 * rr["returns"] / rr["returns"].sum()
    res["return_reasons"] = rr.round(2).sort_values("returns", ascending=False)
    res["return_reason_by_category"] = fr.pivot_table(index="category", columns="return_reason", values="return_key", aggfunc="count", fill_value=0).reset_index()
    sup = fs.groupby("ticket_category").agg(tickets=("ticket_key", "count"), median_resolution_hours=("resolution_hours", "median"),
                                            sla_met_pct=("sla_met", "mean"), avg_csat=("csat_score", "mean")).reset_index()
    sup["sla_met_pct"] *= 100
    res["support_category"] = sup.round(2).sort_values("tickets", ascending=False)
    sp = fs.groupby("priority").agg(tickets=("ticket_key", "count"), median_resolution_hours=("resolution_hours", "median"),
                                    sla_target_hours=("sla_target_hours", "first"), sla_met_pct=("sla_met", "mean")).reset_index()
    sp["sla_met_pct"] *= 100
    res["support_priority"] = sp.round(2)
    dl = s.drop_duplicates("order_id")
    dl = dl[dl["channel_name"] != "Retail Store"].groupby("region_name").agg(
        avg_delivery_days=("delivery_days", "mean"), on_time_pct=("is_on_time", "mean")).reset_index()
    dl["on_time_pct"] *= 100
    res["delivery_by_region"] = dl.round(2)

    # top customers & CLV proxy
    tc = s[s["customer_key"] != -1].groupby(["customer_key", "customer_id", "segment"]).agg(
        revenue=("net_revenue", "sum"), profit=("profit", "sum"), orders=("order_id", "nunique"),
        first=("date", "min"), last=("date", "max")).reset_index()
    tc["tenure_months"] = ((pd.Timestamp(ANALYSIS_DATE) - tc["first"]).dt.days / 30.44).clip(lower=3)
    tc["clv_proxy"] = (tc["revenue"] / tc["orders"]) * tc["orders"] / tc["tenure_months"] * 12 * (headline["profit_margin_pct"] / 100) * 3
    res["top_customers"] = tc.sort_values("revenue", ascending=False).head(50).round({"revenue": 2, "profit": 2, "tenure_months": 2, "clv_proxy": 2})
    res["clv_by_segment"] = tc.groupby("segment").agg(customers=("customer_key", "count"), avg_revenue=("revenue", "mean"),
                                                      avg_clv_proxy=("clv_proxy", "median")).reset_index().round(2)
    pd.Series(headline, name="value").rename_axis("kpi").to_csv(OUT / "headline_kpis.csv")
    for k, v in res.items():
        if isinstance(v, pd.DataFrame):
            v.to_csv(OUT / f"{k}.csv", index=False)
    log.info("Revenue=%.0f Profit=%.0f Margin=%.2f%% Orders=%d Customers=%d AOV=%.0f ReturnRate=%.2f%%",
             headline["total_revenue"], headline["total_profit"], headline["profit_margin_pct"], headline["total_orders"],
             headline["total_customers"], headline["aov"], headline["return_rate_lines_pct"])
    return res
