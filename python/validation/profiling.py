"""Column-level data profiling for any DataFrame (used on the RAW layer)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from python.config import OUTPUT_DIR, get_logger

log = get_logger("validation.profiling")


def _numeric_share(s: pd.Series) -> float:
    nn = s.dropna()
    if nn.empty:
        return 0.0
    return float(pd.to_numeric(nn, errors="coerce").notna().mean())


def _date_share(s: pd.Series) -> float:
    nn = s.dropna()
    if nn.empty:
        return 0.0
    return float(pd.to_datetime(nn, errors="coerce", format="mixed").notna().mean())


def infer_semantic_type(s: pd.Series) -> str:
    name = s.name.lower()
    if name.endswith("_id"):
        return "identifier"
    if "date" in name or name.endswith("_at"):
        return "date"
    if _numeric_share(s) > 0.9:
        return "numeric"
    return "text"


def profile_table(df: pd.DataFrame, table: str) -> pd.DataFrame:
    rows = []
    n = len(df)
    for col in df.columns:
        s = df[col]
        stype = infer_semantic_type(s)
        nn = s.dropna()
        row = {
            "table": table, "column": col, "semantic_type": stype, "rows": n,
            "missing": int(s.isna().sum()), "missing_pct": round(100 * s.isna().mean(), 2),
            "distinct": int(nn.nunique()),
            "leading_trailing_space": int((nn.astype(str) != nn.astype(str).str.strip()).sum()),
            "sample_values": " | ".join(map(str, nn.drop_duplicates().head(4).tolist())),
        }
        if stype == "numeric":
            num = pd.to_numeric(nn, errors="coerce")
            row.update({"non_numeric_values": int(num.isna().sum()), "min": num.min(), "max": num.max(),
                        "mean": round(num.mean(), 2), "median": num.median()})
        elif stype == "date":
            parsed = pd.to_datetime(nn, errors="coerce", format="ISO8601")
            row.update({"unparseable_dates": int(parsed.isna().sum()),
                        "min": parsed.min(), "max": parsed.max()})
        rows.append(row)
    return pd.DataFrame(rows)


def profile_all(tables: dict[str, pd.DataFrame], tag: str = "raw") -> pd.DataFrame:
    prof = pd.concat([profile_table(df, name) for name, df in tables.items()], ignore_index=True)
    out = OUTPUT_DIR / "data_quality"
    out.mkdir(parents=True, exist_ok=True)
    prof.to_csv(out / f"profile_{tag}.csv", index=False)
    summary = prof.groupby("table").agg(columns=("column", "count"), rows=("rows", "max"),
                                        missing_cells=("missing", "sum"),
                                        whitespace_cells=("leading_trailing_space", "sum")).reset_index()
    summary["missing_cell_pct"] = np.round(100 * summary["missing_cells"] / (summary["rows"] * summary["columns"]), 2)
    summary.to_csv(out / f"profile_summary_{tag}.csv", index=False)
    for _, r in summary.iterrows():
        log.info("Profile[%s] %-16s rows=%6d missing_cells=%5d (%.2f%%) whitespace=%d",
                 tag, r["table"], r["rows"], r["missing_cells"], r["missing_cell_pct"], r["whitespace_cells"])
    return prof
