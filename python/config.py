"""Central configuration: paths, constants and logging for the pipeline."""
from __future__ import annotations

import logging
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MART_DIR = PROCESSED_DIR / "mart"          # star-schema tables (Power BI / PostgreSQL)
TABLEAU_DIR = PROCESSED_DIR / "tableau"    # flat, denormalised extracts for Tableau
OUTPUT_DIR = DATA_DIR / "outputs"
CHART_DIR = OUTPUT_DIR / "charts"
DOCS_DIR = ROOT / "docs"
EXCEL_DIR = ROOT / "excel"
SQL_DIR = ROOT / "sql"

RANDOM_SEED = 42
START_DATE = "2023-01-01"
END_DATE = "2025-12-31"
# Snapshot date used for recency / churn calculations (day after the last order date)
ANALYSIS_DATE = "2026-01-01"

RAW_TABLES = [
    "regions", "customers", "products", "orders",
    "order_items", "payments", "returns", "support_tickets",
]

# PostgreSQL connection is read ONLY from environment variables (never hard-coded).
PG_SETTINGS = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": os.getenv("PGPORT", "5432"),
    "dbname": os.getenv("PGDATABASE", "enterprise_analytics"),
    "user": os.getenv("PGUSER", "postgres"),
}


def ensure_dirs() -> None:
    for d in (RAW_DIR, PROCESSED_DIR, MART_DIR, TABLEAU_DIR, OUTPUT_DIR, CHART_DIR, DOCS_DIR, EXCEL_DIR):
        d.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)-28s | %(message)s", "%H:%M:%S")
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        logger.addHandler(sh)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(OUTPUT_DIR / "pipeline.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        logger.propagate = False
    return logger
