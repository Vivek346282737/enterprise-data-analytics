"""Load RAW and MART layers into PostgreSQL and execute every SQL script.

Uses the `psql` client (no Python DB driver needed). Connection settings come ONLY from the
standard environment variables PGHOST / PGPORT / PGDATABASE / PGUSER / PGPASSWORD (or ~/.pgpass);
no credentials are stored in the repository.

    python -m python.database.load_postgres          # or: python run_pipeline.py --with-postgres
"""
from __future__ import annotations

import os
import shutil
import subprocess

from python.config import MART_DIR, OUTPUT_DIR, PG_SETTINGS, RAW_DIR, RAW_TABLES, SQL_DIR, get_logger

log = get_logger("database.load_postgres")

MART_TABLES = {"DimDate": "dim_date", "DimRegion": "dim_region", "DimChannel": "dim_channel", "DimProduct": "dim_product",
               "DimCustomer": "dim_customer", "FactSales": "fact_sales", "FactReturns": "fact_returns", "FactSupport": "fact_support"}
SQL_FILES = ["01_schema.sql", "02_tables.sql", "03_indexes.sql", "04_data_quality.sql", "05_cleaning.sql",
             "06_views.sql", "07_kpi_queries.sql", "08_business_analysis.sql", "09_advanced_sql.sql"]


def _env() -> dict:
    env = os.environ.copy()
    env.setdefault("PGHOST", PG_SETTINGS["host"])
    env.setdefault("PGPORT", PG_SETTINGS["port"])
    env.setdefault("PGUSER", PG_SETTINGS["user"])
    return env


def psql(args: list[str], db: str | None = None, capture: bool = True) -> str:
    cmd = ["psql", "-X", "-v", "ON_ERROR_STOP=1", "-d", db or PG_SETTINGS["dbname"]] + args
    res = subprocess.run(cmd, env=_env(), capture_output=capture, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"psql failed ({' '.join(args[:2])}):\n{res.stderr[-2000:]}")
    return res.stdout


def ensure_database() -> None:
    db = PG_SETTINGS["dbname"]
    exists = psql(["-tAc", f"SELECT 1 FROM pg_database WHERE datname = '{db}'"], db="postgres").strip()
    if not exists:
        psql(["-c", f'CREATE DATABASE "{db}"'], db="postgres")
        log.info("Created database %s", db)


def copy_csv(table: str, path) -> None:
    header = path.open(encoding="utf-8").readline().strip()
    psql(["-c", f"\\copy {table} ({header}) FROM '{path.as_posix()}' WITH (FORMAT csv, HEADER true, NULL '')"])


def load_all() -> None:
    if shutil.which("psql") is None:
        raise RuntimeError("psql client not found. Install PostgreSQL client tools and set PG* env variables.")
    ensure_database()
    out = OUTPUT_DIR / "sql_results"
    out.mkdir(parents=True, exist_ok=True)
    for f in SQL_FILES[:3]:
        psql(["-q", "-f", str(SQL_DIR / f)])
        log.info("Executed %s", f)
    for t in RAW_TABLES:
        copy_csv(f"raw.{t}", RAW_DIR / f"{t}.csv")
    for csv_name, table in MART_TABLES.items():
        copy_csv(f"mart.{table}", MART_DIR / f"{csv_name}.csv")
    psql(["-q", "-c", "ANALYZE"])
    counts = psql(["-tAc", " UNION ALL ".join(f"SELECT '{t}', COUNT(*) FROM mart.{t}" for t in MART_TABLES.values())])
    for line in counts.strip().splitlines():
        log.info("  mart.%-14s rows=%s", *line.split("|"))
    for f in SQL_FILES[3:]:
        result = psql(["-P", "pager=off", "-f", str(SQL_DIR / f)])
        (out / f.replace(".sql", ".txt")).write_text(result, encoding="utf-8")
        log.info("Executed %s -> data/outputs/sql_results/%s", f, f.replace(".sql", ".txt"))


if __name__ == "__main__":
    load_all()
