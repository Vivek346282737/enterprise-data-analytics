"""Build the 5 analysis notebooks (nbformat v4 JSON) and execute them with outputs embedded.

A tiny built-in executor runs each code cell, captures printed text, the last expression
(DataFrames rendered as HTML tables) and matplotlib figures (PNG). This keeps the
notebooks reproducible without requiring a Jupyter kernel. You can also open and re-run them in
Jupyter normally:   python -m python.reporting.build_notebooks
"""
from __future__ import annotations

import ast
import base64
import contextlib
import io
import json
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from python.config import ROOT, get_logger

log = get_logger("reporting.notebooks")

SETUP = """import os, sys
from pathlib import Path
ROOT = Path.cwd().parent if Path.cwd().name == "notebooks" else Path.cwd()
os.chdir(ROOT); sys.path.insert(0, str(ROOT))
import pandas as pd, numpy as np, matplotlib.pyplot as plt
pd.set_option("display.max_columns", 30); pd.set_option("display.width", 160)
MART = "data/processed/mart/"
"""

NOTEBOOKS = {
    "01_data_profiling.ipynb": [
        ("md", "# 01 · Data Profiling (RAW layer)\n**Dataset:** synthetic UrbanCart Retail data (fictional). Raw files are loaded **as text** so type problems stay visible.\n\nGoal: understand structure, completeness, distinct values and obvious defects **before** cleaning."),
        ("code", SETUP),
        ("code", "from python.ingestion.load_raw import load_raw\nraw = load_raw()\n{k: v.shape for k, v in raw.items()}"),
        ("md", "## Column profile\nMissing %, distinct counts, leading/trailing whitespace and unparseable numbers/dates per column."),
        ("code", "from python.validation.profiling import profile_all\nprof = profile_all(raw, 'raw')\nprof.sort_values('missing_pct', ascending=False).head(15)[['table','column','semantic_type','missing','missing_pct','distinct','leading_trailing_space']]"),
        ("code", "prof[prof.semantic_type.isin(['numeric','date'])][['table','column','non_numeric_values','unparseable_dates','min','max']].dropna(how='all', subset=['non_numeric_values','unparseable_dates'])"),
        ("md", "## Label consistency\nThe same category / zone / channel is spelt several ways, so a GROUP BY would split totals."),
        ("code", "print(raw['products']['category'].value_counts().to_string())\nprint()\nprint(raw['orders']['channel'].value_counts(dropna=False).to_string())"),
        ("md", "## Rule-based quality checks & score (raw)"),
        ("code", "from python.validation import quality_checks as q\nraw_checks = q.run_checks(raw, 'raw')\nprint('Overall DQ score (raw):', q.summarize(raw_checks))\nraw_checks[raw_checks.failed_rows > 0].sort_values('failed_rows', ascending=False).head(20)"),
        ("code", "sc = q.quality_score(raw_checks)\nax = sc.set_index('table')['dq_score'].sort_values().plot.barh(color='#94A3B8', figsize=(7,3.5), title='Raw DQ score by table')\nax.set_xlim(90, 100); plt.show()"),
        ("md", "**Takeaways:** duplicates (rows and customers), inconsistent labels, text-typed prices, invalid dates, out-of-range quantities and orphan keys must be fixed before any KPI can be trusted."),
    ],
    "02_data_cleaning.ipynb": [
        ("md", "# 02 · Data Cleaning & Validation\nEvery fix is logged: **what** was wrong, **why**, **how detected**, **how fixed** and **rows affected**. Unrepairable rows are quarantined, not silently deleted."),
        ("code", SETUP),
        ("code", "from python.ingestion.load_raw import load_raw\nfrom python.cleaning.cleaner import clean_all\nfrom python.validation import quality_checks as q\nraw = load_raw()\nclean, issues = clean_all(raw)"),
        ("code", "issues[issues.rows_affected > 0][['table','issue','how_fixed','rows_affected']]"),
        ("md", "## Validation: re-run the same checks on the clean layer"),
        ("code", "r_raw, r_clean = q.run_checks(raw, 'raw'), q.run_checks(clean, 'clean')\nscores = pd.concat([q.quality_score(r_raw), q.quality_score(r_clean)])\npiv = scores.pivot_table(index='table', columns='layer', values='dq_score')[['raw','clean']]\npiv['improvement'] = piv['clean'] - piv['raw']\npiv.round(2)"),
        ("code", "ax = piv[['raw','clean']].plot.bar(figsize=(8,3.5), color=['#94A3B8','#10B981'], title='Data quality score: raw vs clean')\nax.set_ylim(90, 100.5); plt.xticks(rotation=25); plt.show()"),
        ("md", "## Remaining exceptions (accepted by design)\nExplicit *Unknown* members and nulls where the true value cannot be known. See `docs/data_quality.md`."),
        ("code", "r_clean[(r_clean.failed_rows > 0) & ~r_clean.check.str.contains('info')][['table','check','column','failed_rows','pass_rate']]"),
        ("code", "print('Row counts raw -> clean')\nfor t in raw: print(f'{t:16s} {len(raw[t]):>7,} -> {len(clean[t]):>7,}')"),
    ],
    "03_eda.ipynb": [
        ("md", "# 03 · Exploratory Data Analysis\nBuilt on the star schema (`data/processed/mart`). All data is synthetic."),
        ("code", SETUP + "from python.analysis.kpis import sales_view\nmart = {n: pd.read_csv(MART + f'{n}.csv') for n in ['FactSales','FactReturns','FactSupport','DimDate','DimCustomer','DimProduct','DimRegion','DimChannel']}\nmart['DimDate']['date'] = pd.to_datetime(mart['DimDate']['date'])\ns = sales_view(mart)\ns.shape"),
        ("code", "kpi = pd.read_csv('data/outputs/kpis/headline_kpis.csv').set_index('kpi')['value']\nkpi"),
        ("md", "## Trend & seasonality"),
        ("code", "mo = s.groupby('year_month').agg(revenue=('net_revenue','sum'), profit=('profit','sum'), orders=('order_id','nunique'))\nmo['yoy_%'] = mo.revenue.pct_change(12)*100\nax = (mo[['revenue','profit']]/1e5).plot(figsize=(10,3.8), title='Monthly revenue & profit (₹ lakh)')\nplt.show()\nmo.tail(12).round(1)"),
        ("code", "season = s.groupby(['year','month'])['net_revenue'].sum().unstack(0)/1e5\nseason.plot(figsize=(9,3.5), marker='o', title='Revenue by calendar month (₹ lakh): Oct-Nov festive peak'); plt.show()"),
        ("md", "## Category, region and channel mix"),
        ("code", "cat = s.groupby('category').agg(revenue=('net_revenue','sum'), profit=('profit','sum'), returned=('is_returned','mean'))\ncat['margin_%'] = 100*cat.profit/cat.revenue; cat['return_rate_%'] = 100*cat.returned\ncat.sort_values('revenue', ascending=False).round(2)"),
        ("code", "fig, ax = plt.subplots(1, 2, figsize=(11,3.6))\n(s.groupby('region_name').net_revenue.sum().sort_values()/1e7).plot.barh(ax=ax[0], title='Revenue by zone (₹ Cr)', color='#F59E0B')\n(s.groupby('channel_name').net_revenue.sum().sort_values()/1e7).plot.barh(ax=ax[1], title='Revenue by channel (₹ Cr)', color='#8B5CF6')\nplt.tight_layout(); plt.show()"),
        ("md", "## Discounts vs profitability"),
        ("code", "b = pd.cut(s.discount_pct, [-0.01, 0, .10, .20, .6], labels=['0%','1-10%','11-20%','>20%'])\ng = s.groupby(b, observed=True).agg(revenue=('net_revenue','sum'), profit=('profit','sum'), lines=('sales_key','count'))\ng['margin_%'] = 100*g.profit/g.revenue\ng.round(2)"),
        ("md", "## Order value distribution"),
        ("code", "ov = s.groupby('order_id').net_revenue.sum()\nprint(ov.describe(percentiles=[.25,.5,.75,.9,.99]).round(0))\nfig, ax = plt.subplots(1,2, figsize=(11,3.5))\nov.clip(upper=ov.quantile(.99)).plot.hist(bins=60, ax=ax[0], title='Order value (clipped P99)')\nnp.log10(ov).plot.hist(bins=60, ax=ax[1], color='#F59E0B', title='log10(order value)')\nplt.show()"),
        ("md", "## Operations: returns, delivery, support"),
        ("code", "print(mart['FactReturns'].return_reason.value_counts().to_string())\nsup = mart['FactSupport'].groupby('ticket_category').agg(tickets=('ticket_id','count'), median_h=('resolution_hours','median'), csat=('csat_score','mean'))\nsup.sort_values('tickets', ascending=False).round(2)"),
    ],
    "04_customer_segmentation.ipynb": [
        ("md", "# 04 · Customer Segmentation (RFM)\n**Recency** = days since last order (snapshot 2026-01-01), **Frequency** = distinct orders, **Monetary** = net revenue.\nEach is scored 1-5 by quintile (5 = best).\n\n| Segment | Rule (first match wins) |\n|---|---|\n| New | first order in last 90 days |\n| High Value | R≥3, F≥4, M≥4 |\n| Loyal | R≥3, F≥3 |\n| At Risk | R≤2 and (F≥3 or M≥4) |\n| Hibernating | R=1 |\n| Occasional | everyone else |"),
        ("code", SETUP + "rfm = pd.read_csv('data/outputs/segmentation/customer_rfm.csv')\nrfm.head()"),
        ("code", "rfm[['recency_days','frequency','monetary']].describe(percentiles=[.2,.4,.6,.8]).round(1)"),
        ("code", "seg = pd.read_csv('data/outputs/segmentation/segment_summary.csv')\nseg"),
        ("code", "fig, ax = plt.subplots(1,2, figsize=(11,3.8))\nseg.set_index('segment')['customer_share_pct'].sort_values().plot.barh(ax=ax[0], color='#94A3B8', title='% of customers')\nseg.set_index('segment')['revenue_share_pct'].sort_values().plot.barh(ax=ax[1], color='#2563EB', title='% of revenue')\nplt.tight_layout(); plt.show()"),
        ("code", "heat = rfm.pivot_table(index='r_score', columns='f_score', values='monetary', aggfunc='mean')/1e3\nfig, ax = plt.subplots(figsize=(6,4)); im = ax.imshow(heat.values, cmap='Blues')\nax.set_xticks(range(5), heat.columns); ax.set_yticks(range(5), heat.index); ax.set_xlabel('F score'); ax.set_ylabel('R score')\nax.set_title('Avg revenue (₹ thousand) by R x F'); fig.colorbar(im); plt.show()"),
        ("md", "**How to use the segments:** protect *High Value* (service priority), grow *Loyal*, run win-back for *At Risk* (largest recoverable revenue), onboard *New*, and keep *Hibernating* on low-cost channels. Every campaign should be measured against a random hold-out group."),
    ],
    "05_statistical_analysis.ipynb": [
        ("md", "# 05 · Statistical Analysis\nDescriptive statistics, distributions, correlation, outliers and five pre-defined hypothesis tests (α = 0.05). Results are reported **as computed**. All tests are on observational (synthetic) data, so they show association, not causation."),
        ("code", SETUP + "import json\nst = json.load(open('data/outputs/statistics/statistics_summary.json'))\npd.read_csv('data/outputs/statistics/descriptive_statistics.csv', index_col=0)"),
        ("code", "print(st['distribution']['interpretation'])\nprint('Skew:', round(st['distribution']['order_value_skew'],2), '| log skew:', round(st['distribution']['log_order_value_skew'],2))\nprint('IQR outliers (order value):', {k: round(v,1) for k,v in st['outliers_order_value'].items()})"),
        ("code", "corr = pd.read_csv('data/outputs/statistics/correlation_spearman.csv', index_col=0)\nfig, ax = plt.subplots(figsize=(5.5,4.5)); im = ax.imshow(corr, cmap='RdBu_r', vmin=-1, vmax=1)\nax.set_xticks(range(len(corr)), corr.columns, rotation=45, ha='right'); ax.set_yticks(range(len(corr)), corr.index)\n[ax.text(j, i, f'{corr.iloc[i,j]:.2f}', ha='center', va='center', fontsize=8) for i in range(len(corr)) for j in range(len(corr))]\nax.set_title('Spearman correlation (order level)'); fig.colorbar(im); plt.show()"),
        ("md", "## Hypothesis tests\nFor each: hypothesis, H0/H1, metric, method, result, interpretation, limitation."),
        ("code", "for t in st['tests']:\n    p = t.get('p_value', t.get('p_value_mannwhitney'))\n    print('='*90); print(t['name']); print('  H0:', t['h0']); print('  H1:', t['h1']); print('  Metric:', t['metric'], '| Method:', t['method'])\n    extra = {k: round(float(v), 3) for k, v in t.items() if k.startswith(('group_a_m','group_b_m','group_a_r','group_b_r','rho','z','h_stat')) and v is not None}\n    print('  Result:', extra, '| p =', f'{float(p):.3g}', '->', 'reject H0' if t['significant'] else 'fail to reject H0')"),
        ("md", "### Interpretation & limitations\n* **Discount vs order value:** deep-discount orders are *smaller*. This can come from product mix (cheap items are discounted more), so it is not proof that discounts shrink baskets.\n* **Marketplace vs Website returns:** a significant, sizeable gap, which justifies a seller/listing-quality review.\n* **Loyalty members:** order more, but self-selection bias means membership may not *cause* the extra orders. A randomised invite test would be needed.\n* **Resolution time vs CSAT:** a strong negative association that supports SLA investment.\n* **Channel AOV:** with about 55k orders even tiny differences become 'significant'. Check the effect size (₹ gap) before acting.\n* Data is synthetic, and no multiple-testing correction is applied (5 tests, so read borderline p-values with caution)."),
    ],
}


def _execute(cells):
    ns: dict = {}
    out_cells = []
    count = 0
    cwd = os.getcwd()
    os.chdir(ROOT / "notebooks")
    try:
        for kind, src in cells:
            if kind == "md":
                out_cells.append({"cell_type": "markdown", "metadata": {}, "source": src.splitlines(keepends=True)})
                continue
            count += 1
            outputs = []
            buf = io.StringIO()
            tree = ast.parse(src)
            last = tree.body.pop() if tree.body and isinstance(tree.body[-1], ast.Expr) else None
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
                exec(compile(tree, "<cell>", "exec"), ns)
                val = eval(compile(ast.Expression(last.value), "<cell>", "eval"), ns) if last else None
            if buf.getvalue():
                outputs.append({"output_type": "stream", "name": "stdout", "text": buf.getvalue().splitlines(keepends=True)})
            for num in plt.get_fignums():
                fig = plt.figure(num)
                b = io.BytesIO()
                fig.savefig(b, format="png", bbox_inches="tight", dpi=90)
                outputs.append({"output_type": "display_data", "metadata": {},
                                "data": {"image/png": base64.b64encode(b.getvalue()).decode(), "text/plain": ["<Figure>"]}})
            plt.close("all")
            if val is not None and not hasattr(val, "figure") and not (isinstance(val, list) and val and hasattr(val[0], "figure")):
                data = {"text/plain": repr(val).splitlines(keepends=True)}
                if isinstance(val, (pd.DataFrame, pd.Series)):
                    df = val.to_frame() if isinstance(val, pd.Series) else val
                    data["text/html"] = df.head(40).to_html(float_format=lambda x: f"{x:,.2f}").splitlines(keepends=True)
                outputs.append({"output_type": "execute_result", "execution_count": count, "metadata": {}, "data": data})
            out_cells.append({"cell_type": "code", "execution_count": count, "metadata": {},
                              "source": src.splitlines(keepends=True), "outputs": outputs})
    finally:
        os.chdir(cwd)
    return out_cells


def build_all() -> None:
    for name, cells in NOTEBOOKS.items():
        nb = {"cells": _execute(cells), "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
                                                      "language_info": {"name": "python", "version": sys.version.split()[0]}},
              "nbformat": 4, "nbformat_minor": 5}
        (ROOT / "notebooks" / name).write_text(json.dumps(nb, indent=1), encoding="utf-8")
        log.info("Built & executed notebooks/%s", name)


if __name__ == "__main__":
    build_all()
