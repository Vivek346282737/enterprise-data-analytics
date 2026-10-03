"""Transform clean tables into the analytical STAR SCHEMA (data mart).

Facts : FactSales (grain = one order line of a non-cancelled order)
        FactReturns (grain = one returned order line)
        FactSupport (grain = one support ticket)
Dims  : DimDate, DimCustomer, DimProduct, DimRegion, DimChannel
Surrogate integer keys are generated for every dimension; key -1 = 'Unknown' member.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from python.config import ANALYSIS_DATE, END_DATE, MART_DIR, TABLEAU_DIR, get_logger

log = get_logger("transformation.star")

SLA_HOURS = {"Critical": 8, "High": 24, "Medium": 48, "Low": 72, "Unassigned": 72}


def _date_key(s: pd.Series) -> pd.Series:
    return pd.to_numeric(pd.to_datetime(s).dt.strftime("%Y%m%d"), errors="coerce").astype("Int64")


def build_dim_date(start="2022-07-01", end="2026-01-31") -> pd.DataFrame:
    d = pd.DataFrame({"date": pd.date_range(start, end, freq="D")})
    d["date_key"] = d["date"].dt.strftime("%Y%m%d").astype(int)
    d["year"] = d["date"].dt.year
    d["quarter"] = "Q" + d["date"].dt.quarter.astype(str)
    d["month"] = d["date"].dt.month
    d["month_name"] = d["date"].dt.strftime("%b")
    d["year_month"] = d["date"].dt.strftime("%Y-%m")
    d["month_start"] = d["date"].dt.to_period("M").dt.start_time
    d["week_of_year"] = d["date"].dt.isocalendar().week.astype(int)
    d["day_of_week"] = d["date"].dt.dayofweek + 1
    d["day_name"] = d["date"].dt.strftime("%a")
    d["is_weekend"] = d["day_of_week"] >= 6
    d["is_festive_season"] = d["month"].isin([10, 11])
    d["fiscal_year"] = np.where(d["month"] >= 4, "FY" + (d["year"] + 1).astype(str).str[-2:], "FY" + d["year"].astype(str).str[-2:])
    return d[["date_key", "date", "year", "quarter", "month", "month_name", "year_month", "month_start",
              "week_of_year", "day_of_week", "day_name", "is_weekend", "is_festive_season", "fiscal_year"]]


def _with_key(df: pd.DataFrame, key: str, unknown_id_col: str, unknown_id: str) -> pd.DataFrame:
    df = df.copy().reset_index(drop=True)
    df.insert(0, key, np.arange(1, len(df) + 1))
    df.loc[df[unknown_id_col] == unknown_id, key] = -1
    return df


def build_mart(clean: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    reg, ch, prod, cust = clean["regions"], clean["channels"], clean["products"], clean["customers"]
    orders, items, pays = clean["orders"], clean["order_items"], clean["payments"]

    dim_region = _with_key(reg[["region_id", "city", "state", "region_name", "country"]], "region_key", "region_id", "__none__")
    dim_channel = _with_key(ch, "channel_key", "channel_id", "CH00")
    p = prod.copy()
    p["price_band"] = pd.cut(p["unit_price"], [0, 500, 2000, 10000, np.inf],
                             labels=["Budget (<500)", "Mid (500-2K)", "Premium (2K-10K)", "Luxury (10K+)"]).astype(str)
    p.loc[p["unit_price"].isna(), "price_band"] = "Unknown"
    dim_product = _with_key(p[["product_id", "product_name", "category", "sub_category", "brand", "unit_price",
                               "unit_cost", "price_band", "cost_imputed"]], "product_key", "product_id", "P_UNKNOWN")

    # ---------- FactSales ----------
    o = orders[orders["order_status"] != "Cancelled"].copy()
    pay1 = pays.drop_duplicates("order_id").set_index("order_id")["payment_method"]
    f = items.merge(o[["order_id", "customer_id", "order_date", "channel_id", "region_id", "order_status",
                       "promised_days", "delivery_date"]], on="order_id", how="inner")
    f["gross_amount"] = (f["quantity"] * f["unit_price"]).round(2)
    f["net_revenue"] = f["line_amount"].round(2)
    f["discount_amount"] = (f["gross_amount"] - f["net_revenue"]).round(2)
    f["cost_amount"] = (f["quantity"] * f["unit_cost"]).round(2)
    f["profit"] = (f["net_revenue"] - f["cost_amount"]).round(2)
    f["delivery_days"] = (pd.to_datetime(f["delivery_date"]) - pd.to_datetime(f["order_date"])).dt.days
    f["is_on_time"] = (f["delivery_days"] <= f["promised_days"]).astype("boolean").mask(f["delivery_days"].isna())
    f["delivery_days"] = f["delivery_days"].astype("Int64")
    f["payment_method"] = f["order_id"].map(pay1).fillna("Unknown")
    returned = set(clean["returns"]["order_item_id"])
    f["is_returned"] = f["order_item_id"].isin(returned)
    f["date_key"] = _date_key(f["order_date"])

    # ---------- DimCustomer (with first-order / cohort attributes) ----------
    c = cust.copy()
    first = f.groupby("customer_id")["order_date"].min()
    c["first_order_date"] = c["customer_id"].map(first)
    c["cohort_month"] = pd.to_datetime(c["first_order_date"]).dt.strftime("%Y-%m")
    c["age_band"] = pd.cut(c["age"].astype(float), [17, 24, 34, 44, 54, 120],
                           labels=["18-24", "25-34", "35-44", "45-54", "55+"]).astype(str).replace("nan", "Unknown")
    c["preferred_channel"] = c["preferred_channel"].map(ch.set_index("channel_id")["channel_name"]).fillna("Unknown")
    c = c.merge(reg[["region_id", "city", "state", "region_name"]], on="region_id", how="left")
    dim_customer = _with_key(c[["customer_id", "full_name", "gender", "age", "age_band", "region_id", "city", "state",
                                "region_name", "signup_date", "loyalty_member", "preferred_channel",
                                "first_order_date", "cohort_month", "signup_date_imputed"]],
                             "customer_key", "customer_id", "C_UNKNOWN")

    keys = {
        "customer": dim_customer.set_index("customer_id")["customer_key"],
        "product": dim_product.set_index("product_id")["product_key"],
        "region": dim_region.set_index("region_id")["region_key"],
        "channel": dim_channel.set_index("channel_id")["channel_key"],
    }

    def add_keys(df):
        df["customer_key"] = df["customer_id"].map(keys["customer"]).fillna(-1).astype(int)
        df["region_key"] = df["region_id"].map(keys["region"]).fillna(-1).astype(int)
        df["channel_key"] = df["channel_id"].map(keys["channel"]).fillna(-1).astype(int)
        return df

    f = add_keys(f)
    f["product_key"] = f["product_id"].map(keys["product"]).fillna(-1).astype(int)
    f.insert(0, "sales_key", np.arange(1, len(f) + 1))
    fact_sales = f[["sales_key", "order_item_id", "order_id", "date_key", "customer_key", "product_key", "region_key",
                    "channel_key", "quantity", "unit_price", "discount_pct", "gross_amount", "discount_amount",
                    "net_revenue", "cost_amount", "profit", "payment_method", "order_status", "delivery_days",
                    "is_on_time", "is_returned"]]

    # ---------- FactReturns ----------
    r = clean["returns"].merge(f[["order_item_id", "date_key", "customer_key", "product_key", "region_key", "channel_key"]],
                               on="order_item_id", how="inner").rename(columns={"date_key": "order_date_key"})
    r["return_date_key"] = _date_key(r["return_date"])
    r.insert(0, "return_key", np.arange(1, len(r) + 1))
    fact_returns = r[["return_key", "return_id", "order_item_id", "order_id", "order_date_key", "return_date_key",
                      "customer_key", "product_key", "region_key", "channel_key", "return_qty", "refund_amount",
                      "return_reason", "return_status", "return_date_invalid"]]

    # ---------- FactSupport ----------
    s = clean["support_tickets"].merge(orders[["order_id", "region_id", "channel_id"]], on="order_id", how="left")
    s = add_keys(s)
    s["created_date_key"] = _date_key(s["created_at"])
    s["resolution_hours"] = ((s["resolved_at"] - s["created_at"]).dt.total_seconds() / 3600).round(2)
    s["sla_target_hours"] = s["priority"].map(SLA_HOURS)
    s["sla_met"] = (s["resolution_hours"] <= s["sla_target_hours"]).astype("boolean").mask(s["resolution_hours"].isna())
    s.insert(0, "ticket_key", np.arange(1, len(s) + 1))
    fact_support = s[["ticket_key", "ticket_id", "order_id", "created_date_key", "customer_key", "region_key", "channel_key",
                      "created_at", "resolved_at", "resolution_hours", "ticket_category", "priority", "ticket_status",
                      "agent_channel", "csat_score", "sla_target_hours", "sla_met", "timestamp_invalid"]]

    mart = {"DimDate": build_dim_date(), "DimCustomer": dim_customer, "DimProduct": dim_product,
            "DimRegion": dim_region, "DimChannel": dim_channel, "FactSales": fact_sales,
            "FactReturns": fact_returns, "FactSupport": fact_support}
    log.info("Star schema built: FactSales=%d FactReturns=%d FactSupport=%d", len(fact_sales), len(fact_returns), len(fact_support))
    return mart


def add_segments(mart: dict[str, pd.DataFrame], rfm: pd.DataFrame) -> None:
    cols = ["customer_key", "recency_days", "frequency", "monetary", "r_score", "f_score", "m_score", "rfm_score", "segment"]
    dc = mart["DimCustomer"].drop(columns=[c for c in cols[1:] if c in mart["DimCustomer"]])
    dc = dc.merge(rfm[cols], on="customer_key", how="left")
    dc["segment"] = dc["segment"].fillna("No Purchase")
    for c in ["recency_days", "frequency", "r_score", "f_score", "m_score"]:
        dc[c] = dc[c].astype("Int64")
    mart["DimCustomer"] = dc


def write_mart(mart: dict[str, pd.DataFrame]) -> None:
    MART_DIR.mkdir(parents=True, exist_ok=True)
    TABLEAU_DIR.mkdir(parents=True, exist_ok=True)
    for name, df in mart.items():
        df.to_csv(MART_DIR / f"{name}.csv", index=False)
    # Tableau: denormalised flat extracts (one row per grain, all attributes joined)
    dd = mart["DimDate"][["date_key", "date", "year", "quarter", "month", "month_name", "year_month"]]
    dc = mart["DimCustomer"][["customer_key", "customer_id", "gender", "age_band", "loyalty_member", "cohort_month", "segment"]]
    dp = mart["DimProduct"][["product_key", "product_id", "product_name", "category", "sub_category", "brand", "price_band"]]
    dr = mart["DimRegion"][["region_key", "city", "state", "region_name"]]
    dch = mart["DimChannel"][["channel_key", "channel_name", "channel_type"]]
    sales = (mart["FactSales"].merge(dd, on="date_key", how="left").merge(dc, on="customer_key", how="left")
             .merge(dp, on="product_key", how="left").merge(dr, on="region_key", how="left").merge(dch, on="channel_key", how="left"))
    sales.rename(columns={"date": "order_date"}).to_csv(TABLEAU_DIR / "tableau_sales.csv", index=False)
    mart["DimCustomer"].to_csv(TABLEAU_DIR / "tableau_customers.csv", index=False)
    (mart["FactReturns"].merge(dp, on="product_key", how="left").merge(dr, on="region_key", how="left")
     .merge(dch, on="channel_key", how="left").to_csv(TABLEAU_DIR / "tableau_returns.csv", index=False))
    (mart["FactSupport"].merge(dr, on="region_key", how="left").merge(dch, on="channel_key", how="left")
     .to_csv(TABLEAU_DIR / "tableau_support.csv", index=False))
    log.info("Wrote %d mart tables to %s and 4 Tableau extracts to %s", len(mart), MART_DIR.name, TABLEAU_DIR.name)
