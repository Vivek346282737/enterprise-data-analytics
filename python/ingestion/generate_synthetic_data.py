"""Generate the SYNTHETIC raw dataset for the fictional company "UrbanCart Retail Pvt. Ltd.".

All data produced here is synthetic (fully reproducible with RANDOM_SEED). It models a
multi-region Indian omni-channel retailer for 2023-2025 with realistic behaviour:
  * year-on-year growth, weekly pattern and festive-season (Oct-Nov) peaks
  * long-tail product popularity and heavy-tailed customer activity (Pareto-like)
  * category-specific price, margin and return-rate profiles
  * channel-specific discounting and payment-method mix
  * customer churn (each customer has a finite active lifetime)

After the clean data is simulated, realistic DATA-QUALITY DEFECTS are injected
(duplicates, inconsistent labels, whitespace, bad dates, wrong types, outliers, orphans)
so the cleaning layer has real work to do. Nothing here represents a real company.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from python.config import END_DATE, RANDOM_SEED, RAW_DIR, START_DATE, get_logger

log = get_logger("ingestion.generate")

N_CUSTOMERS = 12_000
N_PRODUCTS = 520
N_ORDERS = 56_000

CITIES = [  # region_id, city, state, zone, population weight
    ("R01", "Delhi", "Delhi", "North", 9), ("R02", "Gurugram", "Haryana", "North", 4),
    ("R03", "Jaipur", "Rajasthan", "North", 4), ("R04", "Lucknow", "Uttar Pradesh", "North", 4),
    ("R05", "Chandigarh", "Chandigarh", "North", 2), ("R06", "Bengaluru", "Karnataka", "South", 9),
    ("R07", "Chennai", "Tamil Nadu", "South", 6), ("R08", "Hyderabad", "Telangana", "South", 7),
    ("R09", "Kochi", "Kerala", "South", 3), ("R10", "Coimbatore", "Tamil Nadu", "South", 2),
    ("R11", "Kolkata", "West Bengal", "East", 6), ("R12", "Bhubaneswar", "Odisha", "East", 2),
    ("R13", "Patna", "Bihar", "East", 3), ("R14", "Guwahati", "Assam", "East", 2),
    ("R15", "Jamshedpur", "Jharkhand", "East", 2), ("R16", "Mumbai", "Maharashtra", "West", 10),
    ("R17", "Pune", "Maharashtra", "West", 6), ("R18", "Ahmedabad", "Gujarat", "West", 5),
    ("R19", "Surat", "Gujarat", "West", 3), ("R20", "Panaji", "Goa", "West", 1),
    ("R21", "Bhopal", "Madhya Pradesh", "Central", 2), ("R22", "Indore", "Madhya Pradesh", "Central", 3),
    ("R23", "Nagpur", "Maharashtra", "Central", 2), ("R24", "Raipur", "Chhattisgarh", "Central", 1),
]
ZONE_DELIVERY_DAYS = {"North": 3.2, "South": 3.0, "West": 2.8, "East": 4.3, "Central": 3.8}

# category: (share of catalogue, lognormal median price, sigma, cost ratio range, return prob, popularity boost)
CATEGORIES = {
    "Electronics":    (0.17, 9000, 0.9, (0.78, 0.88), 0.075, 1.0),
    "Fashion":        (0.22, 1300, 0.6, (0.42, 0.58), 0.150, 1.3),
    "Home & Kitchen": (0.17, 1800, 0.8, (0.55, 0.70), 0.060, 1.0),
    "Beauty":         (0.12, 600, 0.6, (0.45, 0.60), 0.045, 1.1),
    "Sports":         (0.10, 1600, 0.8, (0.55, 0.70), 0.070, 0.8),
    "Books":          (0.10, 450, 0.4, (0.60, 0.75), 0.030, 0.7),
    "Grocery":        (0.12, 350, 0.5, (0.72, 0.85), 0.012, 1.4),
}
SUBCATS = {
    "Electronics": ["Smartphones", "Laptops", "Audio", "Wearables", "Accessories"],
    "Fashion": ["Men Apparel", "Women Apparel", "Footwear", "Ethnic Wear", "Accessories"],
    "Home & Kitchen": ["Cookware", "Appliances", "Furnishing", "Storage", "Decor"],
    "Beauty": ["Skincare", "Haircare", "Makeup", "Fragrance"],
    "Sports": ["Fitness", "Outdoor", "Team Sports", "Cycling"],
    "Books": ["Fiction", "Non-Fiction", "Academic", "Children"],
    "Grocery": ["Staples", "Snacks", "Beverages", "Personal Care"],
}
BRANDS = ["Nexora", "Veltrix", "Kavya", "UrbanLeaf", "Solace", "Trendo", "Haveli", "Zephyr",
          "Aarav", "Lumio", "Pragati", "Orbit", "Mitti", "Kriti", "Vayu", "Ember"]
CHANNELS = {  # channel_id: (name, type, share, avg discount shift)
    "CH01": ("Website", "Online", 0.30, 0.00),
    "CH02": ("Mobile App", "Online", 0.33, 0.01),
    "CH03": ("Marketplace", "Online", 0.25, 0.04),
    "CH04": ("Retail Store", "Offline", 0.12, -0.03),
}
FIRST = ["Aarav", "Vivaan", "Aditya", "Arjun", "Rohan", "Karan", "Rahul", "Amit", "Sanjay", "Vikram",
         "Ananya", "Diya", "Priya", "Sneha", "Pooja", "Kavya", "Neha", "Isha", "Riya", "Meera",
         "Farhan", "Imran", "Ayesha", "Zoya", "Harpreet", "Gurpreet", "Joseph", "Maria", "Suresh", "Lakshmi",
         "Deepak", "Nikhil", "Tanvi", "Shreya", "Manish", "Ritu", "Abhishek", "Swati", "Varun", "Divya"]
LAST = ["Sharma", "Verma", "Gupta", "Singh", "Kumar", "Patel", "Shah", "Reddy", "Nair", "Iyer",
        "Das", "Banerjee", "Mukherjee", "Khan", "Fernandes", "Joshi", "Mehta", "Rao", "Pillai", "Prasad",
        "Mishra", "Yadav", "Chopra", "Kapoor", "Bose", "Menon", "Agarwal", "Sinha", "Thakur", "Ghosh"]
RETURN_REASONS = ["Size/Fit Issue", "Damaged in Transit", "Defective Product", "Not as Described",
                  "Changed Mind", "Wrong Item Delivered", "Late Delivery"]


def _seasonal_daily_weights(dates: pd.DatetimeIndex) -> np.ndarray:
    """Demand index per day = trend x weekly pattern x monthly seasonality x festive spikes."""
    t = (dates - dates[0]).days.to_numpy() / 365.0
    trend = 1.0 * (1.22 ** t)                                    # ~22% annual growth
    dow = np.array([0.95, 0.92, 0.94, 0.98, 1.05, 1.18, 1.12])[dates.dayofweek]
    month = np.array([0.92, 0.85, 0.95, 0.93, 0.97, 0.90, 0.93, 1.02, 1.00, 1.35, 1.45, 1.10])[dates.month - 1]
    spike = np.ones(len(dates))
    for y in dates.year.unique():                               # sale events (Republic day, Independence day)
        for m, d0, d1, f in [(1, 20, 26, 1.4), (8, 10, 15, 1.5)]:
            spike[(dates.year == y) & (dates.month == m) & (dates.day >= d0) & (dates.day <= d1)] *= f
    return trend * dow * month * spike


def build_clean_tables(rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    start, end = pd.Timestamp(START_DATE), pd.Timestamp(END_DATE)

    # ---------------- regions ----------------
    regions = pd.DataFrame(CITIES, columns=["region_id", "city", "state", "region_name", "weight"])
    regions["country"] = "India"

    # ---------------- products ----------------
    cat_names = list(CATEGORIES)
    cat_share = np.array([CATEGORIES[c][0] for c in cat_names])
    prod_cat = rng.choice(cat_names, size=N_PRODUCTS, p=cat_share / cat_share.sum())
    rows = []
    for i, cat in enumerate(prod_cat, start=1):
        _, med, sig, (cr_lo, cr_hi), _, _ = CATEGORIES[cat]
        sub = rng.choice(SUBCATS[cat])
        price = float(np.clip(rng.lognormal(np.log(med), sig), med * 0.15, med * 12))
        price = round(price / 10) * 10 - 1 if price > 100 else round(price)
        cost = round(price * rng.uniform(cr_lo, cr_hi), 2)
        brand = rng.choice(BRANDS)
        rows.append({"product_id": f"P{i:04d}", "product_name": f"{brand} {sub} {rng.integers(100, 999)}",
                     "category": cat, "sub_category": sub, "brand": brand,
                     "unit_price": float(price), "unit_cost": cost,
                     "launch_date": (start - pd.Timedelta(days=365) +
                                     pd.Timedelta(days=int(rng.integers(0, 3 * 365)))).date()})
    products = pd.DataFrame(rows)
    # long-tail popularity (Zipf-like), boosted per category
    pop = rng.pareto(2.5, N_PRODUCTS) + 0.25
    pop *= products["category"].map(lambda c: CATEGORIES[c][5]).to_numpy()
    products_launch = pd.to_datetime(products["launch_date"]).to_numpy()

    # ---------------- customers ----------------
    city_w = regions["weight"].to_numpy(float)
    cust_region = rng.choice(regions["region_id"], N_CUSTOMERS, p=city_w / city_w.sum())
    # signups: some before the analysis window, growing over time
    signup_start = pd.Timestamp("2022-07-01")
    span = (end - signup_start).days
    signup_offsets = np.sort((rng.beta(1.3, 1.0, N_CUSTOMERS) * span).astype(int))
    signup = signup_start + pd.to_timedelta(signup_offsets, unit="D")
    fn = rng.choice(FIRST, N_CUSTOMERS)
    ln = rng.choice(LAST, N_CUSTOMERS)
    cid = [f"C{i:05d}" for i in range(1, N_CUSTOMERS + 1)]
    ch_ids = list(CHANNELS)
    ch_share = np.array([CHANNELS[c][2] for c in ch_ids])
    customers = pd.DataFrame({
        "customer_id": cid,
        "first_name": fn, "last_name": ln,
        "email": [f"{f.lower()}.{l.lower()}{i}@example.com" for i, (f, l) in enumerate(zip(fn, ln), 1)],
        "phone": [f"9{rng.integers(100000000, 999999999)}" for _ in range(N_CUSTOMERS)],
        "gender": rng.choice(["Male", "Female"], N_CUSTOMERS, p=[0.54, 0.46]),
        "age": np.clip(rng.normal(33, 9, N_CUSTOMERS).round(), 18, 72).astype(int),
        "region_id": cust_region,
        "signup_date": signup.date,
        "preferred_channel": rng.choice(ch_ids, N_CUSTOMERS, p=ch_share),
        "loyalty_member": rng.random(N_CUSTOMERS) < 0.28,
    })
    activity = rng.lognormal(0, 1.0, N_CUSTOMERS) * np.where(customers["loyalty_member"], 1.6, 1.0)
    lifetime_days = rng.exponential(700, N_CUSTOMERS) + 60
    active_until = signup + pd.to_timedelta(lifetime_days.astype(int), unit="D")

    # ---------------- orders ----------------
    days = pd.date_range(start, end, freq="D")
    w = _seasonal_daily_weights(days)
    order_days = np.sort(rng.choice(len(days), N_ORDERS, p=w / w.sum()))
    order_dates = days[order_days]
    signup_np = signup.to_numpy()
    active_np = active_until.to_numpy()
    cum_act = np.cumsum(activity)
    cust_idx = np.empty(N_ORDERS, dtype=int)
    eligible_n = np.searchsorted(signup_np, order_dates.to_numpy(), side="right")
    for k in range(N_ORDERS):
        n = max(eligible_n[k], 1)
        for _ in range(30):  # rejection sampling to respect churn (active_until)
            j = int(np.searchsorted(cum_act[:n], rng.random() * cum_act[n - 1]))
            if active_np[j] >= order_dates[k].to_datetime64():
                break
        cust_idx[k] = j
    cust_pref = customers["preferred_channel"].to_numpy()[cust_idx]
    rand_ch = rng.choice(ch_ids, N_ORDERS, p=ch_share)
    channel = np.where(rng.random(N_ORDERS) < 0.7, cust_pref, rand_ch)
    zone = regions.set_index("region_id")["region_name"]
    order_region = customers["region_id"].to_numpy()[cust_idx]
    zones = zone.loc[order_region].to_numpy()
    deliver_days = np.maximum(1, rng.gamma(4, np.array([ZONE_DELIVERY_DAYS[z] for z in zones]) / 4)).round()
    deliver_days = np.where(channel == "CH04", 0, deliver_days)  # store purchases are handed over instantly
    status = np.where(rng.random(N_ORDERS) < 0.025, "Cancelled", "Delivered")
    late_window = order_dates > (end - pd.Timedelta(days=5))
    status = np.where(late_window & (status == "Delivered") & (deliver_days > 2), "Shipped", status)
    orders = pd.DataFrame({
        "order_id": [f"O{i:06d}" for i in range(1, N_ORDERS + 1)],
        "customer_id": customers["customer_id"].to_numpy()[cust_idx],
        "order_date": order_dates.date,
        "channel_id": channel,
        "region_id": order_region,
        "order_status": status,
        "promised_days": np.where(channel == "CH04", 0, 5),
    })
    od = pd.to_datetime(orders["order_date"])
    orders["delivery_date"] = np.where(orders["order_status"] == "Delivered",
                                       (od + pd.to_timedelta(deliver_days, unit="D")).dt.date, None)

    # ---------------- order items ----------------
    n_items = np.minimum(1 + rng.poisson(0.95, N_ORDERS), 7)
    item_order = np.repeat(np.arange(N_ORDERS), n_items)
    n_lines = len(item_order)
    line_dates = od.to_numpy()[item_order]
    pop_norm = pop / pop.sum()
    prod_idx = rng.choice(N_PRODUCTS, n_lines, p=pop_norm)
    # products not yet launched -> resample among launched products
    bad = products_launch[prod_idx] > line_dates
    for _ in range(5):
        if not bad.any():
            break
        prod_idx[bad] = rng.choice(N_PRODUCTS, bad.sum(), p=pop_norm)
        bad = products_launch[prod_idx] > line_dates
    prod_idx[bad] = int(np.argmin(products_launch))
    pcat = products["category"].to_numpy()[prod_idx]
    qty = np.where(pcat == "Grocery", 1 + rng.poisson(1.6, n_lines), 1 + rng.poisson(0.25, n_lines))
    years_since = (pd.to_datetime(line_dates) - start).days.to_numpy() / 365.0
    list_price = products["unit_price"].to_numpy()[prod_idx] * (1.04 ** np.floor(years_since))  # annual price revision
    cost = products["unit_cost"].to_numpy()[prod_idx] * (1.04 ** np.floor(years_since))
    month = pd.to_datetime(line_dates).month
    ch_line = channel[item_order]
    base_disc = 0.06 + np.array([CHANNELS[c][3] for c in ch_line]) + np.where(np.isin(month, [10, 11]), 0.06, 0)
    disc = np.clip(rng.normal(base_disc, 0.05), 0, 0.40)
    disc = (np.round(disc / 0.05) * 0.05).round(2)
    gross = qty * list_price
    net = gross * (1 - disc)
    order_items = pd.DataFrame({
        "order_item_id": [f"OI{i:07d}" for i in range(1, n_lines + 1)],
        "order_id": orders["order_id"].to_numpy()[item_order],
        "product_id": products["product_id"].to_numpy()[prod_idx],
        "quantity": qty.astype(int),
        "unit_price": list_price.round(2),
        "unit_cost": cost.round(2),
        "discount_pct": disc,
        "line_amount": net.round(2),
    })

    # ---------------- payments ----------------
    order_total = order_items.groupby("order_id")["line_amount"].sum()
    pay_methods = {
        "CH01": (["UPI", "Credit Card", "Debit Card", "Net Banking", "Cash on Delivery", "Wallet"], [.38, .22, .14, .06, .14, .06]),
        "CH02": (["UPI", "Credit Card", "Debit Card", "Net Banking", "Cash on Delivery", "Wallet"], [.50, .16, .10, .03, .11, .10]),
        "CH03": (["UPI", "Credit Card", "Debit Card", "Net Banking", "Cash on Delivery", "Wallet"], [.36, .18, .12, .04, .24, .06]),
        "CH04": (["UPI", "Credit Card", "Debit Card", "Cash", "Wallet"], [.45, .20, .15, .17, .03]),
    }
    methods = np.empty(N_ORDERS, dtype=object)
    for ch, (m, p) in pay_methods.items():
        mask = channel == ch
        methods[mask] = rng.choice(m, mask.sum(), p=p)
    pay_status = np.where(orders["order_status"] == "Cancelled",
                          np.where(np.isin(methods, ["Cash on Delivery", "Cash"]), "Voided", "Refunded"), "Completed")
    payments = pd.DataFrame({
        "payment_id": [f"PAY{i:06d}" for i in range(1, N_ORDERS + 1)],
        "order_id": orders["order_id"],
        "payment_date": orders["order_date"],
        "payment_method": methods,
        "amount": orders["order_id"].map(order_total).round(2).to_numpy(),
        "payment_status": pay_status,
    })

    # ---------------- returns ----------------
    oi = order_items.merge(orders[["order_id", "order_date", "channel_id", "order_status", "delivery_date"]], on="order_id")
    oi["category"] = oi["product_id"].map(products.set_index("product_id")["category"])
    p_ret = oi["category"].map(lambda c: CATEGORIES[c][4]).to_numpy()
    p_ret = p_ret * np.where(oi["channel_id"] == "CH03", 1.35, 1.0) * np.where(oi["channel_id"] == "CH04", 0.6, 1.0)
    p_ret = p_ret * (1 + oi["discount_pct"].to_numpy())  # deep-discount purchases are returned slightly more often
    is_ret = (rng.random(len(oi)) < p_ret) & (oi["order_status"] == "Delivered").to_numpy()
    r = oi[is_ret].copy()
    reason_p = {
        "Fashion": [.45, .08, .07, .15, .15, .05, .05],
        "Electronics": [.02, .20, .35, .15, .10, .10, .08],
    }
    default_p = [.05, .25, .20, .18, .17, .08, .07]
    r["return_reason"] = [rng.choice(RETURN_REASONS, p=reason_p.get(c, default_p)) for c in r["category"]]
    r["return_date"] = (pd.to_datetime(r["delivery_date"]) + pd.to_timedelta(rng.integers(1, 15, len(r)), unit="D")).dt.date
    r["return_qty"] = np.maximum(1, (r["quantity"] * rng.uniform(0.5, 1.0, len(r))).round()).astype(int)
    r["refund_amount"] = (r["line_amount"] / r["quantity"] * r["return_qty"]).round(2)
    returns = r[["order_item_id", "order_id", "product_id", "return_date", "return_qty", "return_reason", "refund_amount"]].copy()
    returns.insert(0, "return_id", [f"RET{i:06d}" for i in range(1, len(returns) + 1)])
    returns["return_status"] = rng.choice(["Refunded", "Replaced"], len(returns), p=[0.82, 0.18])

    # ---------------- support tickets ----------------
    returned_orders = set(returns["order_id"])
    o2 = orders.copy()
    o2["late"] = (pd.to_datetime(o2["delivery_date"]) - pd.to_datetime(o2["order_date"])).dt.days > o2["promised_days"]
    p_ticket = 0.06 + 0.25 * o2["order_id"].isin(returned_orders) + 0.20 * o2["late"].fillna(False) \
        + 0.15 * (o2["order_status"] == "Cancelled")
    t = o2[rng.random(len(o2)) < p_ticket].copy()
    cats = []
    for _, row in t.iterrows():
        if row["order_id"] in returned_orders and rng.random() < 0.6:
            cats.append("Return/Refund")
        elif row["late"] is True and rng.random() < 0.7:
            cats.append("Delivery Delay")
        elif row["order_status"] == "Cancelled" and rng.random() < 0.6:
            cats.append("Payment Issue")
        else:
            cats.append(rng.choice(["Product Query", "Account/Login", "Payment Issue", "Delivery Delay", "Product Defect"],
                                   p=[.32, .14, .16, .20, .18]))
    t["ticket_category"] = cats
    t["priority"] = rng.choice(["Low", "Medium", "High", "Critical"], len(t), p=[.30, .42, .22, .06])
    t["created_at"] = pd.to_datetime(t["order_date"]) + pd.to_timedelta(rng.integers(0, 10, len(t)), unit="D") \
        + pd.to_timedelta(rng.integers(8 * 60, 22 * 60, len(t)), unit="min")
    base_h = t["priority"].map({"Low": 52, "Medium": 34, "High": 18, "Critical": 7}).to_numpy() \
        * t["ticket_category"].map({"Return/Refund": 1.3, "Delivery Delay": 1.0, "Payment Issue": 1.1,
                                     "Product Query": 0.6, "Account/Login": 0.5, "Product Defect": 1.4}).to_numpy()
    res_h = rng.gamma(2.2, base_h / 2.2)
    t["resolved_at"] = t["created_at"] + pd.to_timedelta(res_h.round(1), unit="h")
    open_mask = t["created_at"] > (pd.Timestamp(END_DATE) - pd.Timedelta(days=4))
    t.loc[open_mask, "resolved_at"] = pd.NaT
    t["ticket_status"] = np.where(t["resolved_at"].isna(), "Open", "Resolved")
    csat = np.clip(np.round(4.6 - res_h / 40 + rng.normal(0, 0.8, len(t))), 1, 5)
    t["csat_score"] = np.where(t["ticket_status"] == "Resolved", csat, np.nan)
    t["agent_channel"] = rng.choice(["Chat", "Email", "Phone"], len(t), p=[.48, .30, .22])
    support = t[["order_id", "customer_id", "created_at", "resolved_at", "ticket_category", "priority",
                 "ticket_status", "agent_channel", "csat_score"]].reset_index(drop=True)
    support.insert(0, "ticket_id", [f"TK{i:06d}" for i in range(1, len(support) + 1)])

    channels = pd.DataFrame([(k, v[0], v[1]) for k, v in CHANNELS.items()], columns=["channel_id", "channel_name", "channel_type"])
    orders = orders.merge(payments[["order_id"]], on="order_id")  # keep column order stable
    return {"regions": regions.drop(columns="weight"), "customers": customers, "products": products,
            "orders": orders, "order_items": order_items, "payments": payments, "returns": returns,
            "support_tickets": support, "channels": channels}


# ------------------------------------------------------------------------------------------
# Data-quality defect injection (RAW layer only)
# ------------------------------------------------------------------------------------------
def inject_quality_issues(t: dict[str, pd.DataFrame], rng: np.random.Generator) -> dict[str, pd.DataFrame]:
    def pick(df, frac):
        return rng.choice(df.index, size=max(1, int(len(df) * frac)), replace=False)

    # regions: inconsistent zone labels + whitespace
    reg = t["regions"].copy()
    variants = {"North": ["north", "NORTH", "N. Region"], "South": ["south ", "South Zone"],
                "East": ["east", "EAST "], "West": ["west", "Western"], "Central": ["central", "Centre"]}
    for i in pick(reg, 0.35):
        reg.at[i, "region_name"] = rng.choice(variants[reg.at[i, "region_name"]])
    reg.loc[pick(reg, 0.2), "city"] = reg["city"].map(lambda s: f"  {s} ")

    # customers
    c = t["customers"].copy()
    c["age"] = c["age"].astype(object)
    c["signup_date"] = c["signup_date"].astype(str)
    c.loc[pick(c, 0.03), "email"] = None
    c.loc[pick(c, 0.02), "phone"] = None
    c.loc[pick(c, 0.015), "gender"] = None
    c.loc[pick(c, 0.04), "first_name"] = c["first_name"].map(lambda s: f" {s.upper()}  ")
    c.loc[pick(c, 0.03), "last_name"] = c["last_name"].map(lambda s: f"{s.lower()} ")
    c.loc[pick(c, 0.004), "age"] = rng.choice([-1, 0, 150, 212, 999], size=int(len(c) * 0.004))
    c.loc[pick(c, 0.01), "age"] = "unknown"
    bad_dates = ["2023-02-30", "2024-13-05", "31/12/2024", "not available", "2031-01-01"]
    c.loc[pick(c, 0.006), "signup_date"] = rng.choice(bad_dates, size=int(len(c) * 0.006))
    gmap = {"Male": ["M", "male"], "Female": ["F", "female"]}
    for i in pick(c, 0.05):
        if c.at[i, "gender"] in gmap:
            c.at[i, "gender"] = rng.choice(gmap[c.at[i, "gender"]])
    c["loyalty_member"] = c["loyalty_member"].map({True: "Yes", False: "No"})
    c.loc[pick(c, 0.02), "loyalty_member"] = rng.choice(["Y", "N", "TRUE", "false"], int(len(c) * 0.02))
    # duplicate customers: same person re-registered with new id (email case/whitespace differs)
    dup_src = c.loc[pick(c, 0.025)].dropna(subset=["email"]).copy()
    dup_src["email"] = dup_src["email"].str.upper().map(lambda s: f" {s}")
    start_id = len(t["customers"]) + 1
    dup_src["customer_id"] = [f"C{i:05d}" for i in range(start_id, start_id + len(dup_src))]
    dup_map = dict(zip(dup_src["customer_id"], c.loc[dup_src.index, "customer_id"]))
    exact = c.loc[pick(c, 0.01)]  # exact duplicate rows (double load)
    c = pd.concat([c, dup_src, exact], ignore_index=True)

    # products
    p = t["products"].copy()
    p["unit_price"] = p["unit_price"].astype(object)
    cat_var = {"Electronics": ["electronics", "ELECTRONICS", "Electronic"], "Fashion": ["fashion", "Fashion "],
               "Home & Kitchen": ["Home&Kitchen", "home & kitchen", "Home and Kitchen"],
               "Beauty": ["beauty", "Beauty & Personal Care"], "Sports": ["sports", "Sport"],
               "Books": ["books", "BOOKS"], "Grocery": ["grocery", "Groceries"]}
    for i in pick(p, 0.15):
        p.at[i, "category"] = rng.choice(cat_var[p.at[i, "category"]])
    p.loc[pick(p, 0.03), "unit_cost"] = np.nan
    p.loc[pick(p, 0.02), "brand"] = None
    for i in pick(p, 0.05):  # price stored as text with currency symbol / thousands separator
        p.at[i, "unit_price"] = f"₹{float(p.at[i, 'unit_price']):,.2f}"
    p.loc[pick(p, 0.01), "product_name"] = p["product_name"].map(lambda s: f"  {s}")
    p = pd.concat([p, p.loc[pick(p, 0.01)]], ignore_index=True)

    # orders
    o = t["orders"].copy()
    o["order_date"] = o["order_date"].astype(str)
    ch_var = {"CH01": ["Website", "web", "WEBSITE "], "CH02": ["Mobile App", "app", "MobileApp"],
              "CH03": ["Marketplace", "marketplace", "3P Marketplace"], "CH04": ["Retail Store", "store", "Offline Store"]}
    o["channel"] = [rng.choice(ch_var[x]) for x in o["channel_id"]]
    o = o.drop(columns="channel_id")
    o.loc[pick(o, 0.008), "channel"] = None
    # a share of orders from re-registered people are placed through their duplicate account
    src_to_dup = {v: k for k, v in dup_map.items()}
    m = o["customer_id"].isin(src_to_dup) & (rng.random(len(o)) < 0.35)
    o.loc[m, "customer_id"] = o.loc[m, "customer_id"].map(src_to_dup)
    o.loc[pick(o, 0.002), "customer_id"] = [f"C{rng.integers(90000, 99999)}" for _ in range(int(len(o) * 0.002))]  # orphans
    o.loc[pick(o, 0.003), "order_date"] = rng.choice(["2024-02-31", "2025-00-10", "20/05/2024", "", "2027-03-15"],
                                                     int(len(o) * 0.003))
    o.loc[pick(o, 0.01), "order_status"] = o["order_status"].map(lambda s: s.lower() + " ")
    o = pd.concat([o, o.loc[pick(o, 0.006)]], ignore_index=True)

    # order items
    oi = t["order_items"].copy()
    oi["quantity"] = oi["quantity"].astype(object)
    oi["unit_price"] = oi["unit_price"].astype(object)
    idx = pick(oi, 0.003)
    oi.loc[idx, "quantity"] = rng.choice([0, -1, -2, 250, 999], len(idx))
    oi.loc[pick(oi, 0.002), "discount_pct"] = rng.choice([1.5, -0.1, 15.0, 25.0], int(len(oi) * 0.002))
    for i in pick(oi, 0.01):
        oi.at[i, "unit_price"] = f"{float(oi.at[i, 'unit_price']):,.2f}"
    oi.loc[pick(oi, 0.004), "line_amount"] = np.nan
    oi.loc[pick(oi, 0.0008), "product_id"] = "P9999"
    oi = pd.concat([oi, oi.loc[pick(oi, 0.005)]], ignore_index=True)

    # payments
    pay = t["payments"].copy()
    var = {"UPI": ["upi", "U.P.I"], "Credit Card": ["credit card", "CC"], "Cash on Delivery": ["COD", "cod"],
           "Debit Card": ["debit card", "DC"]}
    for i in pick(pay, 0.06):
        if pay.at[i, "payment_method"] in var:
            pay.at[i, "payment_method"] = rng.choice(var[pay.at[i, "payment_method"]])
    pay.loc[pick(pay, 0.006), "payment_method"] = None
    pay.loc[pick(pay, 0.003), "amount"] = -pay["amount"].abs()
    pay = pd.concat([pay, pay.loc[pick(pay, 0.004)]], ignore_index=True)

    # returns: return date before delivery, invalid qty, orphan item, duplicates
    rt = t["returns"].copy()
    rt["return_date"] = rt["return_date"].astype(str)
    idx = pick(rt, 0.01)
    rt.loc[idx, "return_date"] = (pd.to_datetime(rt.loc[idx, "return_date"]) - pd.Timedelta(days=60)).dt.date.astype(str)
    rt.loc[pick(rt, 0.01), "return_reason"] = None
    rt.loc[pick(rt, 0.02), "return_reason"] = rt["return_reason"].map(lambda s: s.upper() if isinstance(s, str) else s)
    rt.loc[pick(rt, 0.003), "order_item_id"] = "OI9999999"
    rt = pd.concat([rt, rt.loc[pick(rt, 0.008)]], ignore_index=True)

    # support tickets
    s = t["support_tickets"].copy()
    s["created_at"] = s["created_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
    s["resolved_at"] = s["resolved_at"].dt.strftime("%Y-%m-%d %H:%M:%S")
    idx = pick(s, 0.006)  # resolved before created
    s.loc[idx, "resolved_at"] = (pd.to_datetime(s.loc[idx, "created_at"]) - pd.Timedelta(hours=5)).dt.strftime("%Y-%m-%d %H:%M:%S")
    s.loc[pick(s, 0.02), "priority"] = None
    s.loc[pick(s, 0.04), "ticket_category"] = s["ticket_category"].map(lambda x: x.lower())
    s.loc[pick(s, 0.004), "csat_score"] = rng.choice([0, 7, 10], int(len(s) * 0.004))
    s = pd.concat([s, s.loc[pick(s, 0.005)]], ignore_index=True)

    return {"regions": reg, "customers": c, "products": p, "orders": o, "order_items": oi,
            "payments": pay, "returns": rt, "support_tickets": s}


def generate(force: bool = False) -> None:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    if not force and all((RAW_DIR / f"{n}.csv").exists() for n in
                         ["regions", "customers", "products", "orders", "order_items", "payments", "returns", "support_tickets"]):
        log.info("Raw files already exist in %s - skipping generation (use --regenerate to rebuild)", RAW_DIR)
        return
    rng = np.random.default_rng(RANDOM_SEED)
    log.info("Simulating clean business process data (synthetic, seed=%s)...", RANDOM_SEED)
    clean = build_clean_tables(rng)
    log.info("Injecting realistic data-quality defects into RAW layer...")
    raw = inject_quality_issues(clean, rng)
    for name, df in raw.items():
        df.to_csv(RAW_DIR / f"{name}.csv", index=False)
        log.info("  wrote raw/%-20s %8d rows", f"{name}.csv", len(df))


if __name__ == "__main__":
    generate(force=True)
