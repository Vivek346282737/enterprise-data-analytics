-- =====================================================================
-- 07_kpi_queries.sql : headline & trend KPIs
-- =====================================================================

-- K1. Headline KPIs
SELECT ROUND(SUM(net_revenue), 2)                                   AS total_revenue,
       ROUND(SUM(cost_amount), 2)                                   AS total_cost,
       ROUND(SUM(profit), 2)                                        AS total_profit,
       ROUND(100 * SUM(profit) / SUM(net_revenue), 2)               AS profit_margin_pct,
       COUNT(DISTINCT order_id)                                     AS total_orders,
       COUNT(DISTINCT customer_key) FILTER (WHERE customer_key <> -1) AS total_customers,
       ROUND(SUM(net_revenue) / COUNT(DISTINCT order_id), 2)        AS avg_order_value,
       ROUND(100 * SUM(discount_amount) / SUM(gross_amount), 2)     AS avg_discount_pct,
       ROUND(100 * AVG(is_returned::int), 2)                        AS return_rate_pct
FROM mart.vw_sales;

-- K2. Monthly revenue, profit, orders with MoM growth (LAG)
SELECT year_month, revenue, profit, orders, aov,
       ROUND(100 * (revenue - LAG(revenue) OVER (ORDER BY year_month)) / LAG(revenue) OVER (ORDER BY year_month), 2) AS mom_growth_pct
FROM mart.vw_monthly_kpis
ORDER BY year_month;

-- K3. YoY growth: same month previous year (LAG 12) and annual totals
SELECT year_month, revenue,
       LAG(revenue, 12) OVER (ORDER BY year_month) AS revenue_same_month_last_year,
       ROUND(100 * (revenue / NULLIF(LAG(revenue, 12) OVER (ORDER BY year_month), 0) - 1), 2) AS yoy_growth_pct
FROM mart.vw_monthly_kpis
ORDER BY year_month;

SELECT year, ROUND(SUM(net_revenue), 2) AS revenue, ROUND(SUM(profit), 2) AS profit,
       ROUND(100 * (SUM(net_revenue) / LAG(SUM(net_revenue)) OVER (ORDER BY year) - 1), 2) AS yoy_growth_pct
FROM mart.vw_sales GROUP BY year ORDER BY year;

-- K4. Average order value & orders per customer by year
SELECT year, ROUND(SUM(net_revenue) / COUNT(DISTINCT order_id), 2) AS aov,
       ROUND(COUNT(DISTINCT order_id)::numeric / COUNT(DISTINCT customer_key), 2) AS orders_per_customer
FROM mart.vw_sales WHERE customer_key <> -1
GROUP BY year ORDER BY year;

-- K5. Running revenue, rolling 3-month and rolling 12-month revenue (window frames)
SELECT year_month, revenue,
       SUM(revenue) OVER (ORDER BY year_month ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS running_revenue,
       SUM(revenue) OVER (ORDER BY year_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW)  AS rolling_3m_revenue,
       CASE WHEN ROW_NUMBER() OVER (ORDER BY year_month) >= 12
            THEN SUM(revenue) OVER (ORDER BY year_month ROWS BETWEEN 11 PRECEDING AND CURRENT ROW) END AS rolling_12m_revenue,
       ROUND(AVG(revenue) OVER (ORDER BY year_month ROWS BETWEEN 2 PRECEDING AND CURRENT ROW), 2) AS moving_avg_3m
FROM mart.vw_monthly_kpis
ORDER BY year_month;

-- K6. Return rate & refund value
SELECT ROUND(100 * COUNT(*)::numeric / (SELECT COUNT(*) FROM mart.fact_sales), 2) AS return_rate_lines_pct,
       ROUND(SUM(refund_amount), 2) AS refund_value,
       ROUND(100 * SUM(refund_amount) / (SELECT SUM(net_revenue) FROM mart.fact_sales), 2) AS refund_pct_of_revenue
FROM mart.fact_returns;

-- K7. Operational KPIs: on-time delivery, support SLA, CSAT
SELECT ROUND(100 * AVG(is_on_time::int), 2) AS on_time_delivery_pct,
       ROUND(AVG(delivery_days) FILTER (WHERE channel_name <> 'Retail Store'), 2) AS avg_delivery_days_online
FROM (SELECT DISTINCT ON (order_id) order_id, is_on_time, delivery_days, channel_name FROM mart.vw_sales) o;

SELECT COUNT(*) AS tickets,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_hours)::numeric, 1) AS median_resolution_hours,
       ROUND(100 * AVG(sla_met::int), 2) AS sla_met_pct,
       ROUND(AVG(csat_score), 2) AS avg_csat
FROM mart.fact_support;
