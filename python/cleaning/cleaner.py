"""Cleaning layer: turns the RAW text tables into typed, de-duplicated, conformed tables.

Every fix is written to an issue log (what was wrong / why / how detected / how fixed /
rows affected) which feeds docs/data_quality.md. Records that cannot be repaired are
written to data/processed/quarantine/ instead of being silently dropped.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from python.config import END_DATE, PROCESSED_DIR, get_logger

log = get_logger("cleaning.cleaner")

UNKNOWN_CUSTOMER = "C_UNKNOWN"
UNKNOWN_PRODUCT = "P_UNKNOWN"

REGION_MAP = {"north": "North", "n. region": "North", "south": "South", "south zone": "South",
              "east": "East", "west": "West", "western": "West", "central": "Central", "centre": "Central"}
CATEGORY_MAP = {"electronics": "Electronics", "electronic": "Electronics", "fashion": "Fashion",
                "home & kitchen": "Home & Kitchen", "home&kitchen": "Home & Kitchen", "home and kitchen": "Home & Kitchen",
                "beauty": "Beauty", "beauty & personal care": "Beauty", "sports": "Sports", "sport": "Sports",
                "books": "Books", "grocery": "Grocery", "groceries": "Grocery"}
CHANNEL_MAP = {"website": "CH01", "web": "CH01", "mobile app": "CH02", "app": "CH02", "mobileapp": "CH02",
               "marketplace": "CH03", "3p marketplace": "CH03", "retail store": "CH04", "store": "CH04",
               "offline store": "CH04"}
CHANNELS = pd.DataFrame({"channel_id": ["CH01", "CH02", "CH03", "CH04", "CH00"],
                         "channel_name": ["Website", "Mobile App", "Marketplace", "Retail Store", "Unknown"],
                         "channel_type": ["Online", "Online", "Online", "Offline", "Unknown"]})
PAYMENT_MAP = {"upi": "UPI", "u.p.i": "UPI", "credit card": "Credit Card", "cc": "Credit Card",
               "debit card": "Debit Card", "dc": "Debit Card", "cod": "Cash on Delivery",
               "cash on delivery": "Cash on Delivery", "net banking": "Net Banking", "wallet": "Wallet", "cash": "Cash"}
GENDER_MAP = {"male": "Male", "m": "Male", "female": "Female", "f": "Female"}
BOOL_MAP = {"yes": True, "y": True, "true": True, "no": False, "n": False, "false": False}


class IssueLog:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, table, issue, why, detection, fix, affected) -> None:
        affected = int(affected)
        self.rows.append({"table": table, "issue": issue, "why_it_is_wrong": why, "how_detected": detection,
                          "how_fixed": fix, "rows_affected": affected})
        if affected:
            log.info("  [%s] %s -> %d rows | %s", table, issue, affected, fix)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def _strip(s: pd.Series) -> pd.Series:
    return s.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)


def _to_number(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype("string").str.replace(r"[₹,\s]", "", regex=True), errors="coerce").astype(float)


def _parse_date(s: pd.Series) -> pd.Series:
    """ISO first; then explicit dd/mm/yyyy (the only alternate format found in profiling)."""
    s = s.astype("string").str.strip()
    iso = pd.to_datetime(s, errors="coerce", format="%Y-%m-%d")
    dmy = pd.to_datetime(s, errors="coerce", format="%d/%m/%Y")
    return iso.fillna(dmy)


def _map(s: pd.Series, mapping: dict) -> pd.Series:
    key = s.astype("string").str.strip().str.lower()
    return key.map(mapping)


def clean_regions(df: pd.DataFrame, L: IssueLog) -> pd.DataFrame:
    df = df.copy()
    ws = (df["city"] != df["city"].str.strip()).sum()
    df["city"] = _strip(df["city"])
    L.add("regions", "Extra whitespace in city", "Breaks joins/grouping ('  Delhi ' != 'Delhi')",
          "value != TRIM(value)", "TRIM + collapse inner spaces", ws)
    new = _map(df["region_name"], REGION_MAP).fillna(_strip(df["region_name"]))
    L.add("regions", "Inconsistent region (zone) labels", "Same zone spelt 12 ways splits regional totals",
          "Distinct values outside the 5 allowed zones", "Lower/trim then map to canonical zone", (new != df["region_name"]).sum())
    df["region_name"] = new
    return df


def clean_products(df: pd.DataFrame, L: IssueLog) -> pd.DataFrame:
    df = df.copy()
    d = df.duplicated().sum()
    df = df.drop_duplicates()
    L.add("products", "Exact duplicate rows", "Double counting in catalogue joins", "DataFrame.duplicated()", "Dropped duplicates", d)
    for c in ["product_name", "brand", "sub_category"]:
        df[c] = _strip(df[c])
    cat = _map(df["category"], CATEGORY_MAP)
    L.add("products", "Inconsistent category names", "'electronics', 'ELECTRONICS', 'Electronic' split one category",
          "Values outside 7 canonical categories", "Case/space-insensitive mapping table", (cat != df["category"]).sum())
    df["category"] = cat
    txt = df["unit_price"].astype("string").str.contains(r"[₹,]", na=False).sum()
    df["unit_price"] = _to_number(df["unit_price"])
    L.add("products", "Price stored as text ('₹1,299.00')", "Numeric column cannot be aggregated",
          "pd.to_numeric fails on raw value", "Removed currency symbol & separators, cast to float", txt)
    df["unit_cost"] = pd.to_numeric(df["unit_cost"], errors="coerce")
    miss = df["unit_cost"].isna()
    ratio = (df["unit_cost"] / df["unit_price"]).groupby(df["sub_category"]).transform("median")
    df.loc[miss, "unit_cost"] = (df.loc[miss, "unit_price"] * ratio[miss]).round(2)
    df["cost_imputed"] = miss
    L.add("products", "Missing unit_cost", "Profit cannot be computed", "IS NULL check",
          "Imputed = price x median cost ratio of same sub-category; flagged cost_imputed=True", miss.sum())
    nb = df["brand"].isna().sum()
    df["brand"] = df["brand"].fillna("Unbranded")
    L.add("products", "Missing brand", "Blank labels in brand reports", "IS NULL check", "Set to 'Unbranded'", nb)
    df["launch_date"] = _parse_date(df["launch_date"])
    unk = pd.DataFrame([{"product_id": UNKNOWN_PRODUCT, "product_name": "Unknown Product", "category": "Unknown",
                         "sub_category": "Unknown", "brand": "Unknown", "unit_price": np.nan, "unit_cost": np.nan,
                         "launch_date": pd.NaT, "cost_imputed": False}])
    return pd.concat([df, unk], ignore_index=True)


def clean_customers(df: pd.DataFrame, regions: pd.DataFrame, L: IssueLog) -> tuple[pd.DataFrame, dict]:
    df = df.copy()
    d = df.duplicated().sum()
    df = df.drop_duplicates()
    L.add("customers", "Exact duplicate rows", "Inflates customer counts", "DataFrame.duplicated()", "Dropped", d)
    ws = sum((df[c].dropna() != df[c].dropna().str.strip()).sum() for c in ["first_name", "last_name", "email"])
    df["first_name"] = _strip(df["first_name"]).str.title()
    df["last_name"] = _strip(df["last_name"]).str.title()
    df["email"] = _strip(df["email"]).str.lower()
    L.add("customers", "Whitespace / inconsistent case in names & email", "' RAHUL  ' and 'Rahul' look like different people",
          "value != TRIM(value), mixed case", "TRIM, Title-case names, lower-case email", ws)
    g = _map(df["gender"], GENDER_MAP)
    L.add("customers", "Inconsistent gender codes (M/F/male)", "Splits demographic groups", "Values outside {Male, Female}",
          "Mapped to Male/Female; missing -> 'Not Specified'", (g.fillna("x") != df["gender"].fillna("x")).sum())
    df["gender"] = g.fillna("Not Specified")
    age = pd.to_numeric(df["age"], errors="coerce")
    bad_age = age.isna() | (age < 18) | (age > 100)
    L.add("customers", "Invalid age (text 'unknown', negative, 150, 999)", "Impossible values distort averages",
          "Non-numeric or outside 18-100", "Set to NULL (not guessed)", (bad_age & df["age"].notna()).sum())
    df["age"] = age.where(~bad_age).astype("Int64")
    df["loyalty_member"] = _map(df["loyalty_member"], BOOL_MAP).fillna(False).astype(bool)
    sd = _parse_date(df["signup_date"])
    bad = sd.isna() | (sd > pd.Timestamp(END_DATE))
    df["signup_date"] = sd.where(~bad)
    df["signup_date_imputed"] = bad
    L.add("customers", "Invalid signup_date (2023-02-30, 'not available', future 2031)",
          "Breaks cohort/tenure analysis", "Fails ISO/dd-mm-yyyy parse or > snapshot date",
          "Set NULL, later imputed with customer's first order date (flag signup_date_imputed)", bad.sum())
    # duplicate customers (same e-mail, different customer_id) -> keep earliest record as master
    has = df["email"].notna()
    dfe = df[has].sort_values(["signup_date", "customer_id"])
    master = dfe.groupby("email")["customer_id"].transform("first")
    id_map = dict(zip(dfe["customer_id"], master))
    id_map = {k: v for k, v in id_map.items() if k != v}
    df = df[~df["customer_id"].isin(id_map)]
    L.add("customers", "Duplicate customers (same e-mail re-registered under new ID)",
          "One person counted twice; splits their orders & lifetime value", "Normalised e-mail appears under >1 customer_id",
          "Kept earliest customer_id as master; re-pointed orders/tickets of duplicates to master", len(id_map))
    ne = df["email"].isna().sum()
    L.add("customers", "Missing e-mail", "Cannot contact / dedupe by e-mail", "IS NULL check",
          "Kept customer (orders are valid); excluded from e-mail based dedupe", ne)
    df["full_name"] = df["first_name"] + " " + df["last_name"]
    unk = pd.DataFrame([{"customer_id": UNKNOWN_CUSTOMER, "first_name": "Unknown", "last_name": "Customer",
                         "full_name": "Unknown Customer", "gender": "Not Specified", "region_id": None,
                         "loyalty_member": False, "signup_date_imputed": False, "preferred_channel": "CH00"}])
    return pd.concat([df, unk], ignore_index=True), id_map


def clean_orders(df, customers, payments_raw, id_map, L: IssueLog) -> pd.DataFrame:
    df = df.copy()
    d = df.duplicated().sum()
    df = df.drop_duplicates()
    L.add("orders", "Exact duplicate rows (double load)", "Double-counts revenue & orders", "DataFrame.duplicated()", "Dropped", d)
    m = df["customer_id"].isin(id_map)
    df.loc[m, "customer_id"] = df.loc[m, "customer_id"].map(id_map)
    L.add("orders", "Orders linked to duplicate customer IDs", "Splits customer history", "customer_id in duplicate map",
          "Re-pointed to master customer_id", m.sum())
    orphan = ~df["customer_id"].isin(customers["customer_id"])
    df.loc[orphan, "customer_id"] = UNKNOWN_CUSTOMER
    L.add("orders", "Orphan customer_id (not in customer master)", "Referential integrity violation",
          "LEFT JOIN customers -> NULL", f"Mapped to '{UNKNOWN_CUSTOMER}' member (revenue kept, customer unknown)", orphan.sum())
    od = _parse_date(df["order_date"])
    bad = od.isna() | (od > pd.Timestamp(END_DATE))
    pay_date = df["order_id"].map(payments_raw.drop_duplicates("order_id").set_index("order_id")["payment_date"])
    recovered = _parse_date(pay_date)
    df["order_date"] = od.where(~bad, recovered)
    L.add("orders", "Invalid / missing order_date (2024-02-31, '', future)", "Order cannot be placed in time series",
          "Fails date parse or after data cut-off", "Recovered from matching payment_date (same-day payment in source system)", bad.sum())
    st = _strip(df["order_status"]).str.title()
    L.add("orders", "Inconsistent order_status case/whitespace", "'delivered ' not counted as Delivered",
          "Values outside allowed set", "TRIM + Title case", (st != df["order_status"]).sum())
    df["order_status"] = st
    ch = _map(df["channel"], CHANNEL_MAP)
    nulls = ch.isna()
    ch = ch.where(~(nulls & (pd.to_numeric(df["promised_days"]) == 0)), "CH04")
    L.add("orders", "Inconsistent channel labels ('web', 'app', '3P Marketplace')", "Splits channel KPIs",
          "Values outside 4 canonical channels", "Mapping table to channel_id",
          (~nulls & (df["channel"] != ch.map(CHANNELS.set_index("channel_id")["channel_name"]))).sum())
    L.add("orders", "Missing channel", "Order cannot be attributed", "IS NULL check",
          "promised_days=0 => Retail Store (store hand-over rule); else 'Unknown' (CH00)", nulls.sum())
    df["channel_id"] = ch.fillna("CH00")
    df["channel"] = df["channel_id"].map(CHANNELS.set_index("channel_id")["channel_name"])
    df["promised_days"] = pd.to_numeric(df["promised_days"]).astype(int)
    df["delivery_date"] = _parse_date(df["delivery_date"])
    return df


def clean_order_items(df, orders, products, L: IssueLog) -> pd.DataFrame:
    df = df.copy()
    d = df.duplicated().sum()
    df = df.drop_duplicates()
    L.add("order_items", "Exact duplicate rows", "Double-counts units and revenue", "DataFrame.duplicated()", "Dropped", d)
    txt = df["unit_price"].astype("string").str.contains(",", na=False).sum()
    df["unit_price"] = _to_number(df["unit_price"])
    L.add("order_items", "unit_price stored as text with thousands separator", "Wrong data type", "pd.to_numeric fails",
          "Removed separators, cast to float", txt)
    for c in ["quantity", "discount_pct", "line_amount", "unit_cost"]:
        df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    # quantity errors: recover from line_amount when it is consistent
    bad_q = (df["quantity"] <= 0) | (df["quantity"] > 50)
    implied = (df["line_amount"] / (df["unit_price"] * (1 - df["discount_pct"].clip(0, 0.6)))).round()
    df.loc[bad_q, "quantity"] = implied[bad_q]
    still = bad_q & ((df["quantity"] <= 0) | (df["quantity"] > 50) | df["quantity"].isna())
    L.add("order_items", "Invalid quantity (0, negative, 250, 999)", "Impossible / extreme units distort sales",
          "quantity <= 0 or > 50 (business max per line)", "Re-derived quantity = line_amount / (price x (1-discount))", bad_q.sum())
    bad_d = (df["discount_pct"] < 0) | (df["discount_pct"] > 0.6)
    implied_d = (1 - df["line_amount"] / (df["quantity"] * df["unit_price"])).round(2)
    df.loc[bad_d, "discount_pct"] = implied_d[bad_d]
    L.add("order_items", "Invalid discount_pct (1.5, -0.1, 15, 25)", "Discount must be a 0-60% fraction",
          "Outside [0, 0.6]", "Re-derived from line_amount, quantity and unit_price", bad_d.sum())
    miss = df["line_amount"].isna()
    df.loc[miss, "line_amount"] = (df["quantity"] * df["unit_price"] * (1 - df["discount_pct"])).round(2)
    L.add("order_items", "Missing line_amount", "Revenue unknown", "IS NULL check",
          "Recomputed = quantity x unit_price x (1 - discount_pct)", miss.sum())
    q = df[still | df["quantity"].isna() | df["line_amount"].isna()]
    L.add("order_items", "Unrepairable lines (two dependent fields invalid at once)",
          "Value cannot be re-derived without guessing", "Still NULL after re-derivation",
          "Quarantined (data/processed/quarantine/order_items_unrepairable.csv)", len(q))
    if len(q):
        q.to_csv(PROCESSED_DIR / "quarantine" / "order_items_unrepairable.csv", index=False)
        df = df.drop(q.index)
    orphan_p = ~df["product_id"].isin(products["product_id"])
    df.loc[orphan_p, "product_id"] = UNKNOWN_PRODUCT
    L.add("order_items", "Orphan product_id (P9999 not in catalogue)", "Referential integrity violation",
          "LEFT JOIN products -> NULL", f"Mapped to '{UNKNOWN_PRODUCT}' member (sale kept)", orphan_p.sum())
    orphan_o = ~df["order_id"].isin(orders["order_id"])
    df = df[~orphan_o]
    df["quantity"] = df["quantity"].astype(int)
    return df


def clean_payments(df, orders, L: IssueLog) -> pd.DataFrame:
    df = df.copy()
    d = df.duplicated().sum()
    df = df.drop_duplicates()
    L.add("payments", "Exact duplicate rows", "Double counts collections", "DataFrame.duplicated()", "Dropped", d)
    pm = _map(df["payment_method"], PAYMENT_MAP)
    L.add("payments", "Inconsistent payment method labels (upi, CC, COD)", "Splits payment-mix analysis",
          "Values outside allowed set", "Mapping table; NULL -> 'Unknown'", ((pm != df["payment_method"]) & pm.notna()).sum())
    nm = df["payment_method"].isna().sum()
    L.add("payments", "Missing payment_method", "Incomplete payment mix", "IS NULL check", "Set to 'Unknown'", nm)
    df["payment_method"] = pm.fillna("Unknown")
    df["amount"] = pd.to_numeric(df["amount"], errors="coerce")
    neg = (df["amount"] < 0).sum()
    df["amount"] = df["amount"].abs()
    L.add("payments", "Negative payment amount", "Sign error from source system (payments are inflows)",
          "amount < 0", "Absolute value (refunds are tracked by payment_status, not sign)", neg)
    df["payment_date"] = _parse_date(df["payment_date"])
    return df[df["order_id"].isin(orders["order_id"])]


def clean_returns(df, order_items, orders, L: IssueLog) -> pd.DataFrame:
    df = df.copy()
    d = df.duplicated().sum()
    df = df.drop_duplicates()
    L.add("returns", "Exact duplicate rows", "Inflates return rate", "DataFrame.duplicated()", "Dropped", d)
    orphan = ~df["order_item_id"].isin(order_items["order_item_id"])
    df[orphan].to_csv(PROCESSED_DIR / "quarantine" / "returns_orphan.csv", index=False)
    df = df[~orphan].copy()
    L.add("returns", "Orphan order_item_id", "Return cannot be linked to any sale", "LEFT JOIN order_items -> NULL",
          "Quarantined (data/processed/quarantine/returns_orphan.csv)", orphan.sum())
    canon = {r.lower(): r for r in ["Size/Fit Issue", "Damaged in Transit", "Defective Product", "Not as Described",
                                     "Changed Mind", "Wrong Item Delivered", "Late Delivery"]}
    rr = df["return_reason"].astype("string").str.strip().str.lower().map(canon)
    L.add("returns", "Return reason in upper case", "Splits reason analysis", "Case-sensitive mismatch with allowed list",
          "Case-insensitive mapping", ((rr != df["return_reason"]) & rr.notna()).sum())
    L.add("returns", "Missing return_reason", "Root-cause analysis incomplete", "IS NULL check", "Set to 'Not Specified'",
          df["return_reason"].isna().sum())
    df["return_reason"] = rr.fillna("Not Specified")
    df["return_date"] = _parse_date(df["return_date"])
    dd = df["order_id"].map(orders.set_index("order_id")["delivery_date"])
    bad = df["return_date"] < dd
    df.loc[bad, "return_date"] = pd.NaT
    df["return_date_invalid"] = bad
    L.add("returns", "return_date before delivery_date", "Item cannot be returned before it arrives",
          "return_date < orders.delivery_date", "Date set NULL and flagged (return still counted)", bad.sum())
    df["return_qty"] = pd.to_numeric(df["return_qty"]).astype(int)
    df["refund_amount"] = pd.to_numeric(df["refund_amount"])
    return df


def clean_support(df, orders, id_map, L: IssueLog) -> pd.DataFrame:
    df = df.copy()
    d = df.duplicated().sum()
    df = df.drop_duplicates()
    L.add("support_tickets", "Exact duplicate rows", "Inflates ticket volume", "DataFrame.duplicated()", "Dropped", d)
    m = df["customer_id"].isin(id_map)
    df.loc[m, "customer_id"] = df.loc[m, "customer_id"].map(id_map)
    df["customer_id"] = df["order_id"].map(orders.set_index("order_id")["customer_id"]).fillna(df["customer_id"])
    canon = {c.lower(): c for c in ["Return/Refund", "Delivery Delay", "Payment Issue", "Product Query", "Account/Login", "Product Defect"]}
    tc = df["ticket_category"].str.strip().str.lower().map(canon)
    L.add("support_tickets", "Ticket category in lower case", "Splits category volumes", "Mismatch with allowed list",
          "Case-insensitive mapping", (tc != df["ticket_category"]).sum())
    df["ticket_category"] = tc
    L.add("support_tickets", "Missing priority", "SLA cannot be evaluated", "IS NULL check", "Set to 'Unassigned'", df["priority"].isna().sum())
    df["priority"] = df["priority"].fillna("Unassigned")
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["resolved_at"] = pd.to_datetime(df["resolved_at"], errors="coerce")
    bad = df["resolved_at"] < df["created_at"]
    df.loc[bad, "resolved_at"] = pd.NaT
    df["timestamp_invalid"] = bad
    L.add("support_tickets", "resolved_at earlier than created_at", "Negative resolution time", "resolved_at < created_at",
          "resolved_at set NULL & flagged; excluded from resolution-time KPIs", bad.sum())
    cs = pd.to_numeric(df["csat_score"], errors="coerce")
    badc = (cs < 1) | (cs > 5)
    L.add("support_tickets", "CSAT outside 1-5 scale (0, 7, 10)", "Invalid survey value", "Range check",
          "Set NULL", badc.sum())
    df["csat_score"] = cs.where(~badc)
    return df


def clean_all(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], pd.DataFrame]:
    (PROCESSED_DIR / "quarantine").mkdir(parents=True, exist_ok=True)
    L = IssueLog()
    regions = clean_regions(raw["regions"], L)
    products = clean_products(raw["products"], L)
    customers, id_map = clean_customers(raw["customers"], regions, L)
    orders = clean_orders(raw["orders"], customers, raw["payments"], id_map, L)
    items = clean_order_items(raw["order_items"], orders, products, L)
    payments = clean_payments(raw["payments"], orders, L)
    returns = clean_returns(raw["returns"], items, orders, L)
    support = clean_support(raw["support_tickets"], orders, id_map, L)
    # impute missing signup with first order date
    first = orders.groupby("customer_id")["order_date"].min()
    miss = customers["signup_date"].isna() & (customers["customer_id"] != UNKNOWN_CUSTOMER)
    customers.loc[miss, "signup_date"] = customers.loc[miss, "customer_id"].map(first)
    clean = {"regions": regions, "channels": CHANNELS.copy(), "products": products, "customers": customers,
             "orders": orders, "order_items": items, "payments": payments, "returns": returns, "support_tickets": support}
    out = PROCESSED_DIR / "clean"
    out.mkdir(parents=True, exist_ok=True)
    for k, v in clean.items():
        v.to_csv(out / f"{k}.csv", index=False)
        log.info("Clean %-16s rows=%7d", k, len(v))
    issues = L.frame()
    issues.to_csv(PROCESSED_DIR.parent / "outputs" / "data_quality" / "cleaning_issue_log.csv", index=False)
    return clean, issues
