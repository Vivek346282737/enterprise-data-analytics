# DAX Measures

Create a blank table **`_Measures`** (Enter data → one empty column → delete column) and add the measures below.
Format: currency measures `₹#,##0`; percentages `0.00%`. Tables and columns match `data_model.md`.
Every Python/SQL KPI has a DAX equivalent, so you can check the report against `data/outputs/kpis/headline_kpis.csv`.

## 1. Core sales
```DAX
Total Revenue = SUM ( FactSales[net_revenue] )
Total Cost    = SUM ( FactSales[cost_amount] )
Total Profit  = [Total Revenue] - [Total Cost]
Profit Margin % = DIVIDE ( [Total Profit], [Total Revenue] )
Gross Sales   = SUM ( FactSales[gross_amount] )
Total Discount = SUM ( FactSales[discount_amount] )
Avg Discount % = DIVIDE ( [Total Discount], [Gross Sales] )
Units Sold    = SUM ( FactSales[quantity] )
Total Orders  = DISTINCTCOUNT ( FactSales[order_id] )
Average Order Value = DIVIDE ( [Total Revenue], [Total Orders] )
```
*`DIVIDE` returns BLANK instead of an error when the denominator is 0. AOV uses distinct orders because one order has several lines.*

## 2. Customers
```DAX
Total Customers =
CALCULATE ( DISTINCTCOUNT ( FactSales[customer_key] ), DimCustomer[customer_key] <> -1 )

Orders per Customer = DIVIDE ( [Total Orders], [Total Customers] )

-- customers whose first order falls in the selected period
New Customers =
VAR _start = MIN ( DimDate[date] )
VAR _end   = MAX ( DimDate[date] )
RETURN
    CALCULATE (
        COUNTROWS ( DimCustomer ),
        DimCustomer[first_order_date] >= _start,
        DimCustomer[first_order_date] <= _end,
        REMOVEFILTERS ( DimDate )
    )

-- customers with 2+ orders in the selected context
Repeat Customers =
COUNTROWS (
    FILTER (
        VALUES ( FactSales[customer_key] ),
        FactSales[customer_key] <> -1 && CALCULATE ( DISTINCTCOUNT ( FactSales[order_id] ) ) >= 2
    )
)
Repeat Customer % = DIVIDE ( [Repeat Customers], [Total Customers] )

-- Retention: of customers who bought in the previous year, % who bought again in the current year
Customers Prior Year =
CALCULATE ( [Total Customers], SAMEPERIODLASTYEAR ( DimDate[date] ) )

Retained Customers =
VAR _current = CALCULATETABLE ( VALUES ( FactSales[customer_key] ) )
VAR _prior   = CALCULATETABLE ( VALUES ( FactSales[customer_key] ), SAMEPERIODLASTYEAR ( DimDate[date] ) )
RETURN COUNTROWS ( INTERSECT ( _current, _prior ) )

Customer Retention % = DIVIDE ( [Retained Customers], [Customers Prior Year] )

-- CLV proxy (same logic as SQL/Python): annualised revenue x margin x 3 years, averaged over customers
CLV Proxy (avg) =
VAR _margin = CALCULATE ( [Profit Margin %], ALL ( FactSales ) )
RETURN
AVERAGEX (
    FILTER ( VALUES ( DimCustomer[customer_key] ), DimCustomer[customer_key] <> -1 && NOT ISBLANK ( [Total Revenue] ) ),
    VAR _first  = CALCULATE ( MIN ( DimCustomer[first_order_date] ) )
    VAR _months = MAX ( 3, DATEDIFF ( _first, DATE ( 2026, 1, 1 ), DAY ) / 30.44 )
    RETURN [Total Revenue] / _months * 12 * _margin * 3
)

-- Customer concentration: share of revenue from the top 20% of customers
Top 20% Customer Revenue Share =
VAR _n   = ROUNDDOWN ( [Total Customers] * 0.2, 0 )
VAR _top = TOPN ( _n, FILTER ( VALUES ( DimCustomer[customer_key] ), DimCustomer[customer_key] <> -1 ), [Total Revenue], DESC )
RETURN DIVIDE ( CALCULATE ( [Total Revenue], _top ), [Total Revenue] )
```
*`Retained Customers` uses `INTERSECT` of the customer sets of two periods. This is the DAX form of the SQL self-join in `08_business_analysis.sql` (B3).*

## 3. Time intelligence (requires DimDate marked as Date table)
```DAX
Revenue PY   = CALCULATE ( [Total Revenue], SAMEPERIODLASTYEAR ( DimDate[date] ) )
Revenue YoY  = [Total Revenue] - [Revenue PY]
YoY Growth % = DIVIDE ( [Revenue YoY], [Revenue PY] )

Revenue PM   = CALCULATE ( [Total Revenue], DATEADD ( DimDate[date], -1, MONTH ) )
Revenue MoM  = [Total Revenue] - [Revenue PM]
MoM Growth % = DIVIDE ( [Revenue MoM], [Revenue PM] )

Revenue YTD  = TOTALYTD ( [Total Revenue], DimDate[date] )
Profit PY    = CALCULATE ( [Total Profit], SAMEPERIODLASTYEAR ( DimDate[date] ) )

Running Revenue =
CALCULATE (
    [Total Revenue],
    FILTER ( ALL ( DimDate ), DimDate[date] <= MAX ( DimDate[date] ) )
)

Rolling 3M Revenue =
CALCULATE ( [Total Revenue], DATESINPERIOD ( DimDate[date], MAX ( DimDate[date] ), -3, MONTH ) )

Rolling 12M Revenue =
CALCULATE ( [Total Revenue], DATESINPERIOD ( DimDate[date], MAX ( DimDate[date] ), -12, MONTH ) )
```
*`DATESINPERIOD` returns a window ending on the last visible date, so on a monthly axis Rolling 3M = current + 2 previous months. That matches the SQL `ROWS BETWEEN 2 PRECEDING AND CURRENT ROW`.*

## 4. Products & returns
```DAX
Product Revenue Rank =
IF ( HASONEVALUE ( DimProduct[product_name] ),
     RANKX ( ALL ( DimProduct[product_name] ), [Total Revenue], , DESC, DENSE ) )

Returned Lines = CALCULATE ( COUNTROWS ( FactSales ), FactSales[is_returned] = TRUE () )
Return Rate %  = DIVIDE ( [Returned Lines], COUNTROWS ( FactSales ) )
Total Returns  = COUNTROWS ( FactReturns )
Refund Value   = SUM ( FactReturns[refund_amount] )
Refund % of Revenue = DIVIDE ( [Refund Value], [Total Revenue] )

Returns by Return Date =
CALCULATE ( [Total Returns], USERELATIONSHIP ( FactReturns[return_date_key], DimDate[date_key] ) )

Category Revenue Share % =
DIVIDE ( [Total Revenue], CALCULATE ( [Total Revenue], ALL ( DimProduct[category] ) ) )
```

## 5. Operations & support
```DAX
Delivered Orders = CALCULATE ( DISTINCTCOUNT ( FactSales[order_id] ), NOT ISBLANK ( FactSales[is_on_time] ) )
On-Time Orders   = CALCULATE ( DISTINCTCOUNT ( FactSales[order_id] ), FactSales[is_on_time] = TRUE () )
On-Time Delivery % = DIVIDE ( [On-Time Orders], [Delivered Orders] )
Avg Delivery Days (Online) =
CALCULATE ( AVERAGE ( FactSales[delivery_days] ), DimChannel[channel_type] = "Online" )

Ticket Volume = COUNTROWS ( FactSupport )
Tickets per 100 Orders = DIVIDE ( [Ticket Volume], [Total Orders] ) * 100
Median Resolution Hours = MEDIAN ( FactSupport[resolution_hours] )
Avg Resolution Hours    = AVERAGE ( FactSupport[resolution_hours] )
SLA Met % = DIVIDE ( CALCULATE ( COUNTROWS ( FactSupport ), FactSupport[sla_met] = TRUE () ),
                     CALCULATE ( COUNTROWS ( FactSupport ), NOT ISBLANK ( FactSupport[sla_met] ) ) )
Avg CSAT = AVERAGE ( FactSupport[csat_score] )
Open Tickets = CALCULATE ( [Ticket Volume], FactSupport[ticket_status] = "Open" )
```

## 6. Data quality (tables from `data/outputs/data_quality/`)
```DAX
DQ Score Raw   = CALCULATE ( AVERAGE ( dq_scores[dq_score] ), dq_scores[layer] = "raw" )
DQ Score Clean = CALCULATE ( AVERAGE ( dq_scores[dq_score] ), dq_scores[layer] = "clean" )
DQ Improvement = [DQ Score Clean] - [DQ Score Raw]
Rows Fixed     = SUM ( cleaning_issue_log[rows_affected] )
Missing Records (raw)   = CALCULATE ( SUM ( dq_checks_raw[failed_rows] ), dq_checks_raw[dimension] = "Completeness" )
Duplicate Records (raw) = CALCULATE ( SUM ( dq_checks_raw[failed_rows] ), dq_checks_raw[dimension] = "Uniqueness" )
Invalid Records (raw)   = CALCULATE ( SUM ( dq_checks_raw[failed_rows] ), dq_checks_raw[dimension] IN { "Validity", "Consistency", "Integrity" },
                                      NOT CONTAINSSTRING ( dq_checks_raw[check], "info" ) )
Failed Checks (clean)   = CALCULATE ( COUNTROWS ( dq_checks_clean ), dq_checks_clean[failed_rows] > 0,
                                      NOT CONTAINSSTRING ( dq_checks_clean[check], "info" ) )
```

## 7. Conditional formatting helper
```DAX
YoY Colour = IF ( [YoY Growth %] >= 0, "#059669", "#DC2626" )   -- use as Font colour > Field value
```
