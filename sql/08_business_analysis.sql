-- =====================================================================
-- 08_business_analysis.sql : answers to management's business questions
-- =====================================================================

-- B1. Top 10 customers by revenue (with share of total)
SELECT customer_id, segment, orders, ROUND(revenue, 2) AS revenue,
       ROUND(100 * revenue / SUM(revenue) OVER (), 3) AS revenue_share_pct
FROM mart.vw_customer_summary
ORDER BY revenue DESC
LIMIT 10;

-- B2. Repeat vs one-time customers
SELECT CASE WHEN orders >= 2 THEN 'Repeat' ELSE 'One-time' END AS customer_type,
       COUNT(*) AS customers, ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS share_pct,
       ROUND(SUM(revenue), 2) AS revenue
FROM mart.vw_customer_summary
GROUP BY 1;

-- B3. Customer retention by year: % of last year's customers who bought again this year
WITH cy AS (SELECT DISTINCT customer_key, year FROM mart.vw_sales WHERE customer_key <> -1)
SELECT a.year, COUNT(*) AS customers_prev_year_base,
       COUNT(b.customer_key) AS retained,
       ROUND(100.0 * COUNT(b.customer_key) / COUNT(*), 2) AS retention_pct
FROM cy a
LEFT JOIN cy b ON b.customer_key = a.customer_key AND b.year = a.year + 1
WHERE a.year < 2025
GROUP BY a.year ORDER BY a.year;

-- B4. Churn proxy: customers with no order in the last 180 days of the data
SELECT COUNT(*) FILTER (WHERE recency_days > 180) AS churned_customers,
       COUNT(*) AS customers,
       ROUND(100.0 * COUNT(*) FILTER (WHERE recency_days > 180) / COUNT(*), 2) AS churn_proxy_pct,
       ROUND(SUM(revenue) FILTER (WHERE recency_days > 180), 2) AS historical_revenue_of_churned
FROM mart.vw_customer_summary;

-- B5. Top 10 and bottom 10 products by revenue (UNION ALL)
(SELECT 'Top' AS bucket, product_id, product_name, category, ROUND(SUM(net_revenue), 2) AS revenue, SUM(quantity) AS units
 FROM mart.vw_sales WHERE product_id <> 'P_UNKNOWN' GROUP BY product_id, product_name, category ORDER BY revenue DESC LIMIT 10)
UNION ALL
(SELECT 'Bottom', product_id, product_name, category, ROUND(SUM(net_revenue), 2), SUM(quantity)
 FROM mart.vw_sales WHERE product_id <> 'P_UNKNOWN' GROUP BY product_id, product_name, category ORDER BY 5 ASC LIMIT 10);

-- B6. Category performance
SELECT category, ROUND(SUM(net_revenue), 2) AS revenue, ROUND(SUM(profit), 2) AS profit,
       ROUND(100 * SUM(profit) / SUM(net_revenue), 2) AS margin_pct,
       ROUND(100 * SUM(net_revenue) / SUM(SUM(net_revenue)) OVER (), 2) AS revenue_share_pct,
       ROUND(100 * AVG(is_returned::int), 2) AS return_rate_pct
FROM mart.vw_sales
GROUP BY category
ORDER BY revenue DESC;

-- B7. Regional performance (zone and top city per zone)
SELECT region_name, ROUND(SUM(net_revenue), 2) AS revenue, COUNT(DISTINCT customer_key) AS customers,
       ROUND(SUM(net_revenue) / COUNT(DISTINCT order_id), 2) AS aov,
       ROUND(100 * SUM(profit) / SUM(net_revenue), 2) AS margin_pct
FROM mart.vw_sales GROUP BY region_name ORDER BY revenue DESC;

-- B8. Channel performance
SELECT channel_name, COUNT(DISTINCT order_id) AS orders, ROUND(SUM(net_revenue), 2) AS revenue,
       ROUND(SUM(net_revenue) / COUNT(DISTINCT order_id), 2) AS aov,
       ROUND(100 * SUM(discount_amount) / SUM(gross_amount), 2) AS avg_discount_pct,
       ROUND(100 * AVG(is_returned::int), 2) AS return_rate_pct
FROM mart.vw_sales GROUP BY channel_name ORDER BY revenue DESC;

-- B9. Return rate by category and channel (conditional aggregation pivot)
SELECT category,
       ROUND(100 * AVG(is_returned::int) FILTER (WHERE channel_name = 'Website'), 2)      AS website_pct,
       ROUND(100 * AVG(is_returned::int) FILTER (WHERE channel_name = 'Mobile App'), 2)   AS app_pct,
       ROUND(100 * AVG(is_returned::int) FILTER (WHERE channel_name = 'Marketplace'), 2)  AS marketplace_pct,
       ROUND(100 * AVG(is_returned::int) FILTER (WHERE channel_name = 'Retail Store'), 2) AS store_pct
FROM mart.vw_sales GROUP BY category ORDER BY category;

-- B10. Return reasons
SELECT return_reason, COUNT(*) AS returns, ROUND(SUM(refund_amount), 2) AS refund_value,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS share_pct
FROM mart.fact_returns GROUP BY return_reason ORDER BY returns DESC;

-- B11. Discount analysis: margin by discount band (CASE bucketing)
SELECT CASE WHEN discount_pct = 0 THEN '0%'
            WHEN discount_pct <= 0.10 THEN '1-10%'
            WHEN discount_pct <= 0.20 THEN '11-20%'
            ELSE '>20%' END AS discount_band,
       COUNT(*) AS lines, ROUND(SUM(net_revenue), 2) AS revenue,
       ROUND(100 * SUM(profit) / SUM(net_revenue), 2) AS margin_pct,
       ROUND(100 * AVG(is_returned::int), 2) AS return_rate_pct
FROM mart.vw_sales GROUP BY 1 ORDER BY 1;

-- B12. Customer Lifetime Value proxy by segment
--      CLV proxy = annualised revenue (revenue / tenure months * 12) x overall margin x 3-year horizon
WITH m AS (SELECT SUM(profit) / SUM(net_revenue) AS margin FROM mart.fact_sales)
SELECT segment, COUNT(*) AS customers,
       ROUND(AVG(revenue), 2) AS avg_revenue,
       ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY
            revenue / GREATEST((DATE '2026-01-01' - first_order_date) / 30.44, 3) * 12 * (SELECT margin FROM m) * 3)::numeric, 2) AS median_clv_proxy
FROM mart.vw_customer_summary GROUP BY segment ORDER BY median_clv_proxy DESC;

-- B13. Customers with above-average lifetime revenue in their own region (correlated subquery)
SELECT cs.customer_id, dc.region_name, ROUND(cs.revenue, 2) AS revenue
FROM mart.vw_customer_summary cs
JOIN mart.dim_customer dc USING (customer_key)
WHERE cs.revenue > (SELECT AVG(cs2.revenue) * 5 FROM mart.vw_customer_summary cs2
                    JOIN mart.dim_customer d2 USING (customer_key) WHERE d2.region_name = dc.region_name)
ORDER BY revenue DESC
LIMIT 15;

-- B14. Categories whose margin is below the company margin (HAVING with subquery)
SELECT category, ROUND(100 * SUM(profit) / SUM(net_revenue), 2) AS margin_pct
FROM mart.vw_sales
GROUP BY category
HAVING SUM(profit) / SUM(net_revenue) < (SELECT SUM(profit) / SUM(net_revenue) FROM mart.fact_sales)
ORDER BY margin_pct;

-- B15. Support: ticket volume, resolution time and SLA by category
SELECT ticket_category, COUNT(*) AS tickets,
       ROUND(AVG(resolution_hours), 1) AS avg_resolution_h,
       ROUND(100 * AVG(sla_met::int), 2) AS sla_met_pct,
       ROUND(AVG(csat_score), 2) AS avg_csat
FROM mart.fact_support GROUP BY ticket_category ORDER BY tickets DESC;

-- B16. Delivery performance by zone (online orders)
SELECT region_name, ROUND(AVG(delivery_days), 2) AS avg_delivery_days, ROUND(100 * AVG(is_on_time::int), 2) AS on_time_pct
FROM mart.vw_orders o
JOIN (SELECT DISTINCT order_id, is_on_time FROM mart.fact_sales) f USING (order_id)
WHERE channel_name <> 'Retail Store'
GROUP BY region_name ORDER BY on_time_pct;
