# Tableau Dashboard Specification

Tableau Public / Desktop can rebuild these dashboards from the flat extracts produced by `python run_pipeline.py`:

| File (`data/processed/tableau/`) | Grain | Use |
|---|---|---|
| `tableau_sales.csv` | order line (FactSales + all dimension attributes) | Executive & Sales dashboards |
| `tableau_customers.csv` | customer (DimCustomer incl. RFM) | Customer dashboard |
| `tableau_returns.csv` | returned line | Returns views |
| `tableau_support.csv` | ticket | Operations views |

Join `tableau_sales` to `tableau_customers` on `customer_key` only if you need customer attributes beyond those already
in the sales extract (segment, cohort_month, loyalty_member are included).

## Calculated fields
```
Revenue            = SUM([net_revenue])
Profit             = SUM([profit])
Profit Margin      = SUM([profit]) / SUM([net_revenue])
Orders             = COUNTD([order_id])
Customers          = COUNTD(IF [customer_key] <> -1 THEN [customer_key] END)
AOV                = SUM([net_revenue]) / COUNTD([order_id])
Return Rate        = SUM(INT([is_returned])) / COUNT([sales_key])
Discount Band      = IF [discount_pct] = 0 THEN "0%" ELSEIF [discount_pct] <= 0.1 THEN "1-10%"
                     ELSEIF [discount_pct] <= 0.2 THEN "11-20%" ELSE ">20%" END
Order Month        = DATETRUNC('month', [order_date])
YoY Growth         = (ZN(SUM([net_revenue])) - LOOKUP(ZN(SUM([net_revenue])), -12)) / ABS(LOOKUP(ZN(SUM([net_revenue])), -12))
                     -- table calc, compute along Order Month (monthly axis)
Running Revenue    = RUNNING_SUM(SUM([net_revenue]))
Rolling 3M Revenue = WINDOW_SUM(SUM([net_revenue]), -2, 0)
Revenue Rank       = RANK_DENSE(SUM([net_revenue]))
First Order Month  = { FIXED [customer_key] : MIN(DATETRUNC('month', [order_date])) }   -- LOD for cohorts
Months Since First = DATEDIFF('month', [First Order Month], [Order Month])
Customer Revenue   = { FIXED [customer_key] : SUM([net_revenue]) }
```

## Dashboard 1: Executive
* KPI BANs: Revenue, Profit, Profit Margin, Orders, Customers, AOV, Return Rate (each with YoY delta)
* Dual-axis line: Revenue and Profit by Order Month
* Filled map: Revenue by state (state field → geographic role *State/Province*, country India)
* Bar: Revenue by category (sorted), colour = Profit Margin (diverging)
* Bar: Revenue by channel_name
* Filters (apply to all worksheets): year, region_name, channel_name, category

## Dashboard 2: Sales
* Bar + line: monthly Revenue with YoY Growth (table calc) on secondary axis
* Highlight table: category × year Revenue
* Line: Running Revenue and Rolling 3M Revenue
* Scatter: Profit Margin vs avg discount_pct per product (detail = product_name, colour = category)
* Bar: Profit Margin by Discount Band
* Parameter **Top N** (integer, default 10) + set "Top N products by Revenue" → bar of top products

## Dashboard 3: Customer
* Bar: customers and revenue by `segment` (from `tableau_customers.csv`)
* Cohort heat map: rows First Order Month, columns Months Since First, measure = COUNTD(customer_key) / cohort size
  (cohort size = `{ FIXED [First Order Month] : COUNTD([customer_key]) }`)
* Pareto: bars = Customer Revenue sorted desc, line = RUNNING_SUM(SUM)/TOTAL(SUM) with 80% reference line
* Histogram: frequency (orders per customer)
* Box plot: monetary by segment

## Publishing
Tableau Public: *File → Save to Tableau Public*. Add the public link to the README only after it is published.
