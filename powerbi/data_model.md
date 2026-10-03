# Power BI Data Model

> **Honest scope note:** a `.pbix` file cannot be generated outside Power BI Desktop (Windows). This folder contains
> everything needed to build the report in about an hour: the star-schema CSVs, the Power Query (M) script
> (`power_query.m`), the DAX measures (`dax_measures.md`) and the page-by-page design (`dashboard_design.md`).
> After you build it, save it as `powerbi/enterprise_analytics.pbix` and add real screenshots to the README.

## 1. Source
Run `python run_pipeline.py`, then load the 8 CSVs from `data/processed/mart/`:
`FactSales, FactReturns, FactSupport, DimDate, DimCustomer, DimProduct, DimRegion, DimChannel`.
(Alternative: connect Power BI to PostgreSQL schema `mart` after `python run_pipeline.py --with-postgres`.)

## 2. Relationships (all Many-to-One, single direction, dimension → fact)

| From (many) | To (one) | Active |
|---|---|---|
| FactSales[date_key] | DimDate[date_key] | Yes |
| FactSales[customer_key] | DimCustomer[customer_key] | Yes |
| FactSales[product_key] | DimProduct[product_key] | Yes |
| FactSales[region_key] | DimRegion[region_key] | Yes |
| FactSales[channel_key] | DimChannel[channel_key] | Yes |
| FactReturns[order_date_key] | DimDate[date_key] | Yes |
| FactReturns[return_date_key] | DimDate[date_key] | **No** (use `USERELATIONSHIP` for "returns by return date") |
| FactReturns[customer_key / product_key / region_key / channel_key] | matching Dim | Yes |
| FactSupport[created_date_key] | DimDate[date_key] | Yes |
| FactSupport[customer_key / region_key / channel_key] | matching Dim | Yes |

FactReturns is **not** related directly to FactSales (fact-to-fact joins create ambiguity). Return rate is computed
with measures that share the dimensions.

## 3. Model settings
* Mark `DimDate` as **Date table** (column `date`). It is continuous from 2022-07-01 to 2026-01-31.
* Sort `DimDate[month_name]` by `DimDate[month]`; sort `year_month` by `month_start`.
* Hide all key columns (`*_key`) and the fact tables' raw numeric columns from report view; expose measures only.
* Data types: keys = Whole number; amounts = Fixed decimal; `is_*` = True/False; dates = Date.
* Set `DimRegion[city]` data category = City and `DimRegion[state]` = State or Province (for map visuals).
* Create display folders: *Sales*, *Customers*, *Products*, *Returns & Ops*, *Data Quality*, *Time Intelligence*.

## 4. Data-quality tables (Page 6)
Also import from `data/outputs/data_quality/`:
`dq_scores.csv` (score per table and layer), `dq_checks_raw.csv`, `dq_checks_clean.csv`, `cleaning_issue_log.csv`.
These are standalone tables with no relationships.
