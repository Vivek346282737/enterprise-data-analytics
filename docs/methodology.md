# Methodology

## 1. Why synthetic data?
No public dataset contains all eight related tables needed here (customers, orders, items, products, payments,
returns, regions **and** support tickets) with a consistent key structure. A realistic synthetic dataset was therefore
generated and **clearly labelled as synthetic** everywhere. It simulates a fictional Indian omni-channel retailer:

| Behaviour | How it is simulated |
|---|---|
| Growth & seasonality | daily demand index = ~22 %/yr trend × weekday pattern × monthly seasonality (Oct-Nov festive peak) × sale-event spikes |
| Customer heterogeneity | log-normal activity weights (heavy-tailed, Pareto-like spend); loyalty members more active |
| Churn | every customer has an exponential active lifetime; no orders after it ends |
| Product long tail | Pareto popularity; category-specific price (log-normal), margin and return-rate profiles |
| Channels | preferred channel per customer (70 %); channel-specific discount and payment mix |
| Operations | zone-specific delivery times, returns driven by category / channel / discount, tickets driven by returns, delays and cancellations; resolution time by priority; CSAT falls with slow resolution |

Defects are then injected into the RAW copy only (see `docs/data_quality.md`).

## 2. Pipeline
`run_pipeline.py` orchestrates modular steps (each in its own package):
1. **Ingestion**: generate (first run) and load raw CSVs as text (`python/ingestion`)
2. **Profiling**: column statistics (`python/validation/profiling.py`)
3. **Quality checks**: 100+ rule checks in 5 dimensions, plus scoring (`python/validation/quality_checks.py`)
4. **Cleaning**: logged, rule-based fixes, quarantine for unrepairable rows (`python/cleaning/cleaner.py`)
5. **Validation**: the same checks re-run on clean data; the pipeline stops if quality decreases
6. **Transformation**: star schema with surrogate keys and Unknown members (`python/transformation/star_schema.py`)
7. **Segmentation**: RFM (`python/analysis/segmentation.py`)
8. **KPIs**: headline, trend, mix, Pareto, cohort, operations (`python/analysis/kpis.py`)
9. **Statistics**: descriptive, correlation, outliers, hypothesis tests (`python/analysis/statistics.py`)
10. **Outputs**: charts, Excel workbook, Markdown reports, executed notebooks, optional PostgreSQL load and SQL run

## 3. Cleaning principles
* **Never guess silently.** If a value can be re-derived from other fields (quantity from line amount, order date from
  payment date), re-derive it and log it. Otherwise set it NULL or use an explicit "Unknown" label.
* **Keep revenue.** Orphan foreign keys map to an Unknown dimension member instead of dropping sales.
* **Quarantine, don't delete.** Rows that cannot be repaired are written to `data/processed/quarantine/`.
* **Measure.** A data-quality score before and after cleaning proves the effect.

## 4. RFM segmentation
| Metric | Definition | Scoring |
|---|---|---|
| Recency | days from last order to snapshot (2026-01-01) | quintiles, 5 = most recent |
| Frequency | distinct non-cancelled orders | quintiles on rank (ties broken), 5 = most |
| Monetary | total net revenue | quintiles, 5 = highest |

Segment rules (first match wins): **New** (first order ≤ 90 days ago) → **High Value** (R≥3, F≥4, M≥4) →
**Loyal** (R≥3, F≥3) → **At Risk** (R≤2 and (F≥3 or M≥4)) → **Hibernating** (R=1) → **Occasional** (rest).
Rule-based segments are explainable to business users, unlike black-box clustering.

## 5. Statistical testing
* Tests and thresholds fixed in advance, α = 0.05; results reported as computed (no cherry-picking).
* Non-parametric tests (Mann-Whitney U, Kruskal-Wallis, Spearman) because order values are strongly right-skewed.
  A Welch t-test on log values is shown as a robustness check. A two-proportion z-test is used for return rates.
* All tests are observational, so they show association, not causation. With ~55k orders, tiny effects become
  significant, so effect sizes are reported alongside p-values.

## 6. CLV proxy
`CLV proxy = (customer revenue / tenure months × 12) × company profit margin × 3 years`, with tenure measured from the first order to the snapshot
(minimum 3 months to avoid inflating brand-new customers). It is a ranking aid, not a predictive model.

## 7. Limitations
Synthetic data; contribution margin only (no shipping/marketing cost); single currency; no
returns of cancelled orders; RFM thresholds are relative (quintiles), so segment sizes are partly by construction.
