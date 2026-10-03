-- =====================================================================
-- 06_views.sql : reusable analytical views on the star schema
-- =====================================================================

-- Flat sales view: one row per order line with all dimension attributes
CREATE OR REPLACE VIEW mart.vw_sales AS
SELECT f.sales_key, f.order_item_id, f.order_id, d.date AS order_date, d.year, d.month, d.year_month, d.month_start,
       c.customer_key, c.customer_id, c.segment, c.loyalty_member, c.cohort_month,
       p.product_id, p.product_name, p.category, p.sub_category, p.brand,
       r.city, r.state, r.region_name, ch.channel_name, ch.channel_type,
       f.quantity, f.unit_price, f.discount_pct, f.gross_amount, f.discount_amount, f.net_revenue,
       f.cost_amount, f.profit, f.payment_method, f.delivery_days, f.is_on_time, f.is_returned
FROM mart.fact_sales f
JOIN mart.dim_date d      ON d.date_key = f.date_key
JOIN mart.dim_customer c  ON c.customer_key = f.customer_key
JOIN mart.dim_product p   ON p.product_key = f.product_key
JOIN mart.dim_region r    ON r.region_key = f.region_key
JOIN mart.dim_channel ch  ON ch.channel_key = f.channel_key;

-- Order-level view (AOV, basket size, delivery)
CREATE OR REPLACE VIEW mart.vw_orders AS
SELECT order_id, MIN(order_date) AS order_date, MIN(year_month) AS year_month, MIN(customer_key) AS customer_key,
       MIN(region_name) AS region_name, MIN(channel_name) AS channel_name,
       SUM(net_revenue) AS order_value, SUM(profit) AS order_profit, SUM(quantity) AS units,
       COUNT(*) AS lines, BOOL_OR(is_returned) AS has_return, MIN(delivery_days) AS delivery_days
FROM mart.vw_sales
GROUP BY order_id;

-- Monthly KPI view
CREATE OR REPLACE VIEW mart.vw_monthly_kpis AS
SELECT year_month,
       SUM(net_revenue)                                   AS revenue,
       SUM(profit)                                        AS profit,
       COUNT(DISTINCT order_id)                           AS orders,
       COUNT(DISTINCT customer_key)                       AS customers,
       ROUND(SUM(net_revenue) / COUNT(DISTINCT order_id), 2) AS aov,
       ROUND(100 * SUM(profit) / SUM(net_revenue), 2)     AS profit_margin_pct,
       ROUND(100 * AVG(is_returned::int), 2)              AS return_rate_pct
FROM mart.vw_sales
GROUP BY year_month;

-- Customer summary view (basis for RFM / CLV)
CREATE OR REPLACE VIEW mart.vw_customer_summary AS
SELECT customer_key, customer_id, segment,
       MIN(order_date) AS first_order_date, MAX(order_date) AS last_order_date,
       COUNT(DISTINCT order_id) AS orders, SUM(net_revenue) AS revenue, SUM(profit) AS profit,
       DATE '2026-01-01' - MAX(order_date) AS recency_days
FROM mart.vw_sales
WHERE customer_key <> -1
GROUP BY customer_key, customer_id, segment;
