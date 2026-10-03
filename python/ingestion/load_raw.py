"""Load the RAW CSV layer exactly as delivered (everything as text, no silent type coercion)."""
from __future__ import annotations

import pandas as pd

from python.config import RAW_DIR, RAW_TABLES, get_logger

log = get_logger("ingestion.load_raw")


def load_raw(tables: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """Read raw CSVs with dtype=str so that type problems stay visible for profiling."""
    out: dict[str, pd.DataFrame] = {}
    for name in tables or RAW_TABLES:
        path = RAW_DIR / f"{name}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing raw file {path}. Run `python run_pipeline.py --regenerate`.")
        df = pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""])
        out[name] = df
        log.info("Loaded raw %-16s rows=%7d cols=%2d", name, len(df), df.shape[1])
    return out
