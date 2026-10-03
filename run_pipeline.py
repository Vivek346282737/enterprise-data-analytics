"""End-to-end pipeline for the Enterprise Sales, Customer & Operations Analytics Platform.

    python run_pipeline.py                  # full pipeline (generates raw data on first run)
    python run_pipeline.py --regenerate     # rebuild the synthetic raw data first
    python run_pipeline.py --with-postgres  # also load PostgreSQL and run all SQL scripts

Steps: generate/load raw -> profile -> DQ checks (raw) -> clean -> DQ checks (clean)
       -> star schema -> RFM segmentation -> KPIs -> statistics -> charts
       -> Excel workbook -> reports (docs) -> notebooks -> [PostgreSQL]
"""
from __future__ import annotations

import argparse
import sys
import time

import pandas as pd

from python.analysis import kpis, segmentation, statistics
from python.cleaning.cleaner import clean_all
from python.config import ensure_dirs, get_logger
from python.ingestion.generate_synthetic_data import generate
from python.ingestion.load_raw import load_raw
from python.reporting import excel_builder, report_writer
from python.transformation import star_schema
from python.validation import profiling, quality_checks
from python.visualization import charts

log = get_logger("pipeline")


def step(n: int, name: str):
    log.info("=" * 70)
    log.info("STEP %02d | %s", n, name)
    return time.perf_counter()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--regenerate", action="store_true", help="rebuild synthetic raw data")
    ap.add_argument("--with-postgres", action="store_true", help="load PostgreSQL and run sql/*.sql")
    args = ap.parse_args()
    t0 = time.perf_counter()
    ensure_dirs()

    step(1, "Generate synthetic raw data (if missing)")
    generate(force=args.regenerate)
    step(2, "Load raw data")
    raw = load_raw()
    step(3, "Profile raw data")
    profiling.profile_all(raw, "raw")
    step(4, "Data-quality checks on RAW")
    raw_checks = quality_checks.run_checks(raw, "raw")
    raw_score = quality_checks.summarize(raw_checks)
    step(5, "Clean data")
    clean, issues = clean_all(raw)
    step(6, "Data-quality checks on CLEAN (validation)")
    clean_checks = quality_checks.run_checks(clean, "clean")
    clean_score = quality_checks.summarize(clean_checks)
    if clean_score < raw_score:
        log.error("Cleaning made data quality worse - stopping")
        return 1
    scores = pd.concat([quality_checks.quality_score(raw_checks), quality_checks.quality_score(clean_checks)])
    scores.to_csv("data/outputs/data_quality/dq_scores.csv", index=False)
    step(7, "Transform to star schema")
    mart = star_schema.build_mart(clean)
    step(8, "RFM customer segmentation")
    rfm = segmentation.rfm(mart["FactSales"], mart["DimDate"])
    star_schema.add_segments(mart, rfm)
    star_schema.write_mart(mart)
    step(9, "KPI generation")
    k = kpis.compute_kpis(mart, clean)
    sales = kpis.sales_view(mart)
    step(10, "Statistical analysis")
    stats_out = statistics.run_statistics(sales, mart)
    step(11, "Charts (EDA)")
    charts.make_eda_charts(k, sales, rfm, scores)
    step(12, "Excel analytics workbook")
    excel_builder.build_workbook(mart, k, issues, scores, clean_checks, raw_checks)
    step(13, "Reports (docs/business_insights.md, docs/data_quality.md)")
    seg = pd.read_csv("data/outputs/segmentation/segment_summary.csv")
    report_writer.write_business_insights(k, stats_out, seg, (raw_score, clean_score))
    report_writer.write_data_quality(issues, raw_checks, clean_checks, scores, (raw_score, clean_score))
    step(14, "Build & execute analysis notebooks")
    from python.reporting.build_notebooks import build_all
    build_all()
    if args.with_postgres:
        step(15, "Load PostgreSQL + run SQL scripts")
        from python.database.load_postgres import load_all
        load_all()
    log.info("=" * 70)
    log.info("Pipeline finished in %.1f s | DQ score %.2f -> %.2f", time.perf_counter() - t0, raw_score, clean_score)
    return 0


if __name__ == "__main__":
    sys.exit(main())
