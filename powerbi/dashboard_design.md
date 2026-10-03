# Power BI Dashboard Design (6 pages)

**Canvas:** 16:9, 1280×720. **Theme:** navy `#1F3A5F` headers, blue `#2563EB` = revenue, green `#10B981` = profit/good,
red `#EF4444` = returns/bad, amber `#F59E0B` = highlight. **Global slicers (synced on all pages):** Year, Quarter,
Region (zone), Channel, Category. Every page footer: *"Synthetic data, for portfolio demonstration only."*

## Page 1: Executive Overview
| Area | Visual | Fields / measures |
|---|---|---|
| Top row | 7 KPI cards | Total Revenue, Total Profit, Total Orders, Total Customers, Average Order Value, Profit Margin %, Return Rate % (each card subtitle: YoY Growth % with YoY Colour) |
| Middle left | Line chart | Axis DimDate[month_start]; Total Revenue, Rolling 3M Revenue |
| Middle right | Line chart | Axis DimDate[month_start]; Total Profit, Profit Margin % (secondary axis) |
| Bottom 1 | Filled map or bar | DimRegion[region_name] / [state]; Total Revenue |
| Bottom 2 | Bar chart | DimProduct[category]; Total Revenue (sorted) |
| Bottom 3 | Table | Top 10 products: product_name, Total Revenue, Profit Margin %, Product Revenue Rank ≤ 10 (filter) |
| Bottom 4 | Clustered column | DimChannel[channel_name]; Total Revenue, Average Order Value |

## Page 2: Sales Analytics
* Column + line combo: Total Revenue by month, line = MoM Growth %
* Matrix: rows Year > Month; values Total Revenue, Revenue PY, YoY Growth %, MoM Growth % (conditional font colour)
* Line: Running Revenue and Rolling 12M Revenue
* Stacked bar: Revenue by Category × Region; 100% stacked column: Revenue by Channel per Year
* Scatter (discount analysis): X = Avg Discount %, Y = Profit Margin %, size = Total Revenue, details = product_name, legend = category
* Column: Profit Margin % by discount band (create the band as a calculated column: `Discount Band = SWITCH(TRUE(), FactSales[discount_pct]=0,"0%", FactSales[discount_pct]<=0.1,"1-10%", FactSales[discount_pct]<=0.2,"11-20%", ">20%")`)

## Page 3: Customer Analytics
* Cards: Total Customers, New Customers, Repeat Customer %, Customer Retention %, Average Order Value, CLV Proxy (avg), Top 20% Customer Revenue Share
* Donut: Total Customers by DimCustomer[segment]; bar: Total Revenue by segment
* Line: New Customers by month
* Matrix (cohort): rows DimCustomer[cohort_month], columns DimDate[year_month], values Total Customers (heat-map formatting)
* Table: top 20 customers (customer_id, segment, Total Orders, Total Revenue)
* Pareto: bar Total Revenue by customer_id (top N), line = cumulative share (`Cumulative % = DIVIDE(CALCULATE([Total Revenue], FILTER(ALLSELECTED(DimCustomer[customer_id]), [Total Revenue] >= MAXX(VALUES(DimCustomer[customer_id]), [Total Revenue]))), CALCULATE([Total Revenue], ALLSELECTED(DimCustomer[customer_id])))`)

## Page 4: Product Analytics
* Cards: Units Sold, Total Revenue, Total Profit, Return Rate %
* Bar: Top 10 products (Top N filter on Total Revenue); Bar: Bottom 10 products
* Matrix: Category > Sub-category with Total Revenue, Total Profit, Profit Margin %, Units Sold, Return Rate %, Category Revenue Share % (data bars + colour scale)
* Scatter: Return Rate % vs Profit Margin % by product (size = revenue)
* Treemap: revenue by category > brand

## Page 5: Operations & Returns
* Cards: Return Rate %, Refund Value, On-Time Delivery %, Ticket Volume, Median Resolution Hours, SLA Met %, Avg CSAT
* Bar: Total Returns by return_reason; stacked bar: returns by category × reason
* Column: Return Rate % by channel
* Line: Ticket Volume by month (FactSupport via DimDate)
* Bar: Median Resolution Hours by ticket_category with SLA Met % as tooltip
* Bar: On-Time Delivery % by region_name (target line 90%)

## Page 6: Data Quality
* Cards: DQ Score Raw, DQ Score Clean, DQ Improvement, Rows Fixed, Missing Records (raw), Duplicate Records (raw), Invalid Records (raw)
* Clustered bar: dq_scores by table (raw vs clean)
* Matrix: dq_scores table × dimension (colour scale 95 → 100)
* Table: cleaning_issue_log (table, issue, how_detected, how_fixed, rows_affected)
* Table: dq_checks_clean filtered to failed_rows > 0 (remaining accepted exceptions)

## Interactivity
* Drill-through page *Customer Detail* (drill on customer_id): orders over time, segment, RFM scores.
* Tooltips page: mini line of revenue trend for any category/region.
* Bookmarks: "Festive season" (Oct-Nov filter) vs "All year".
* Row-level security example: role *Zone Manager* with filter `DimRegion[region_name] = "South"`.
