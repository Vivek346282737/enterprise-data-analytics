-- =====================================================================
-- 09_advanced_sql.sql : window functions, ranking, Pareto, cohorts, optimisation
-- =====================================================================

-- A1. Product ranking within each category: ROW_NUMBER vs RANK vs DENSE_RANK
WITH p AS (
    SELECT category, product_name, SUM(quantity) AS units, ROUND(SUM(net_revenue), 2) AS revenue
    FROM mart.vw_sales WHERE category <> 'Unknown'
    GROUP BY category, product_name
)
SELECT * FROM (
    SELECT category, product_name, units, revenue,
           ROW_NUMBER() OVER (PARTITION BY category ORDER BY units DESC) AS row_num,
           RANK()       OVER (PARTITION BY category ORDER BY units DESC) AS rnk,
           DENSE_RANK() OVER (PARTITION BY category ORDER BY units DESC) AS dense_rnk
    FROM p
) x
WHERE row_num <= 3
ORDER BY category, row_num;

-- A2. Pareto (80/20) analysis of customers: cumulative revenue share
WITH c AS (
    SELECT customer_key, SUM(net_revenue) AS revenue FROM mart.fact_sales WHERE customer_key <> -1 GROUP BY customer_key
), r AS (
    SELECT customer_key, revenue,
           SUM(revenue) OVER (ORDER BY revenue DESC ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) / SUM(revenue) OVER () AS cum_share,
           ROW_NUMBER() OVER (ORDER BY revenue DESC)::numeric / COUNT(*) OVER () AS customer_pct
    FROM c
)
SELECT ROUND(100 * MIN(customer_pct) FILTER (WHERE cum_share >= 0.8), 2) AS pct_customers_for_80pct_revenue,
       ROUND(100 * MAX(cum_share) FILTER (WHERE customer_pct <= 0.2), 2) AS revenue_pct_from_top20pct_customers
FROM r;

-- A3. Pareto of products with NTILE deciles
WITH p AS (SELECT product_key, SUM(net_revenue) AS revenue FROM mart.fact_sales GROUP BY product_key),
d AS (SELECT revenue, NTILE(10) OVER (ORDER BY revenue DESC) AS decile FROM p)
SELECT decile, COUNT(*) AS products, ROUND(SUM(revenue), 2) AS revenue,
       ROUND(100 * SUM(revenue) / SUM(SUM(revenue)) OVER (), 2) AS share_pct,
       ROUND(100 * SUM(SUM(revenue)) OVER (ORDER BY decile) / SUM(SUM(revenue)) OVER (), 2) AS cumulative_share_pct
FROM d GROUP BY decile ORDER BY decile;

-- A4. Monthly cohort retention (customers active N months after first purchase)
WITH first_purchase AS (
    SELECT customer_key, MIN(month_start) AS cohort FROM mart.vw_sales WHERE customer_key <> -1 GROUP BY customer_key
), activity AS (
    SELECT DISTINCT s.customer_key, f.cohort,
           (EXTRACT(YEAR FROM age(s.month_start, f.cohort)) * 12 + EXTRACT(MONTH FROM age(s.month_start, f.cohort)))::int AS months_since
    FROM mart.vw_sales s JOIN first_purchase f USING (customer_key)
), cohort_size AS (
    SELECT cohort, COUNT(*) AS size FROM first_purchase GROUP BY cohort
)
SELECT to_char(a.cohort, 'YYYY-MM') AS cohort, cs.size,
       ROUND(100.0 * COUNT(*) FILTER (WHERE months_since = 1)  / cs.size, 1) AS m1,
       ROUND(100.0 * COUNT(*) FILTER (WHERE months_since = 2)  / cs.size, 1) AS m2,
       ROUND(100.0 * COUNT(*) FILTER (WHERE months_since = 3)  / cs.size, 1) AS m3,
       ROUND(100.0 * COUNT(*) FILTER (WHERE months_since = 6)  / cs.size, 1) AS m6,
       ROUND(100.0 * COUNT(*) FILTER (WHERE months_since = 12) / cs.size, 1) AS m12
FROM activity a JOIN cohort_size cs USING (cohort)
GROUP BY a.cohort, cs.size
ORDER BY a.cohort;

-- A5. Days between consecutive orders per customer (LAG) and next order gap (LEAD)
WITH o AS (SELECT DISTINCT customer_key, order_id, order_date FROM mart.vw_sales WHERE customer_key <> -1),
g AS (
    SELECT customer_key, order_date,
           order_date - LAG(order_date)  OVER (PARTITION BY customer_key ORDER BY order_date, order_id) AS days_since_prev,
           LEAD(order_date) OVER (PARTITION BY customer_key ORDER BY order_date, order_id) - order_date AS days_to_next
    FROM o
)
SELECT ROUND(AVG(days_since_prev), 1) AS avg_days_between_orders,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY days_since_prev) AS median_days_between_orders,
       COUNT(*) FILTER (WHERE days_to_next IS NULL) AS last_orders
FROM g;

-- A6. Each region's monthly revenue vs its own average (AVG OVER PARTITION) and share of month (SUM OVER)
WITH rm AS (SELECT region_name, year_month, SUM(net_revenue) AS revenue FROM mart.vw_sales GROUP BY region_name, year_month)
SELECT region_name, year_month, ROUND(revenue, 2) AS revenue,
       ROUND(AVG(revenue) OVER (PARTITION BY region_name), 2) AS region_avg_month,
       ROUND(100 * revenue / SUM(revenue) OVER (PARTITION BY year_month), 2) AS share_of_month_pct,
       ROUND(100 * (revenue / LAG(revenue, 12) OVER (PARTITION BY region_name ORDER BY year_month) - 1), 2) AS yoy_pct
FROM rm
WHERE year_month >= '2025-01'
ORDER BY region_name, year_month;

-- A7. Best month per year (ROW_NUMBER filter) using date functions
WITH m AS (
    SELECT EXTRACT(YEAR FROM month_start)::int AS yr, to_char(month_start, 'Mon') AS mon, SUM(net_revenue) AS revenue
    FROM mart.vw_sales GROUP BY 1, 2, month_start
)
SELECT yr, mon, ROUND(revenue, 2) AS revenue
FROM (SELECT m.*, ROW_NUMBER() OVER (PARTITION BY yr ORDER BY revenue DESC) AS rn FROM m) x
WHERE rn = 1 ORDER BY yr;

-- A8. Weekday vs weekend and festive season performance (date dimension attributes)
SELECT d.is_festive_season, d.is_weekend,
       COUNT(DISTINCT f.order_id) AS orders,
       ROUND(SUM(f.net_revenue) / COUNT(DISTINCT d.date), 2) AS revenue_per_day,
       ROUND(100 * SUM(f.discount_amount) / SUM(f.gross_amount), 2) AS avg_discount_pct
FROM mart.fact_sales f JOIN mart.dim_date d USING (date_key)
GROUP BY d.is_festive_season, d.is_weekend
ORDER BY 1, 2;

-- A9. RFM segment profile straight from SQL (recomputed with NTILE for comparison)
WITH c AS (
    SELECT customer_key, recency_days, orders AS frequency, revenue AS monetary FROM mart.vw_customer_summary
), s AS (
    SELECT c.*,
           6 - NTILE(5) OVER (ORDER BY recency_days) AS r,
           NTILE(5) OVER (ORDER BY frequency) AS f,
           NTILE(5) OVER (ORDER BY monetary) AS m
    FROM c
)
SELECT r, COUNT(*) AS customers, ROUND(AVG(frequency), 2) AS avg_orders, ROUND(AVG(monetary), 2) AS avg_revenue
FROM s GROUP BY r ORDER BY r DESC;

/* =====================================================================
   SQL QUERY OPTIMISATION NOTES (applied in this project)
   ---------------------------------------------------------------------
   1. Star schema: facts hold integer surrogate keys; joins on INT are cheaper than on VARCHAR.
   2. Indexes on every fact foreign key + composite (customer_key, date_key) for per-customer
      window queries (03_indexes.sql). Low-cardinality flags (is_returned) are NOT indexed.
   3. Filter early: WHERE on dimension attributes before aggregating; CTEs keep logic readable,
      and since PostgreSQL 12 non-recursive CTEs are inlined, so they do not block optimisation.
   4. Prefer COUNT(*) FILTER (WHERE ...) over several sub-queries: one table scan instead of N.
   5. Avoid SELECT * in views used by BI tools; select only needed columns.
   6. Use EXPLAIN (ANALYZE, BUFFERS) to check for sequential scans on large tables, e.g.: */
EXPLAIN (COSTS OFF)
SELECT SUM(net_revenue) FROM mart.fact_sales WHERE customer_key = 42;
/*  7. Sargable predicates: compare a column to a constant (date_key BETWEEN 20250101 AND 20251231)
       instead of wrapping the column in a function (EXTRACT(YEAR FROM date) = 2025) so indexes can be used.
    8. For dashboards, pre-aggregate (vw_monthly_kpis / materialized views) instead of scanning
       line-level facts on every refresh; REFRESH MATERIALIZED VIEW after each load.
    9. Run ANALYZE after bulk loads so the planner has fresh statistics (done by the loader).
   ===================================================================== */
