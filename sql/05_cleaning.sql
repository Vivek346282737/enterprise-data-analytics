-- =====================================================================
-- 05_cleaning.sql : SQL implementation of the core cleaning rules (raw -> clean)
-- Python (python/cleaning/cleaner.py) is the production cleaner that feeds the mart;
-- this file shows the same logic in SQL and ends with a reconciliation against the mart.
-- Requires helper functions from 04_data_quality.sql.
-- =====================================================================
SET client_min_messages = warning;
DROP TABLE IF EXISTS clean.regions, clean.products, clean.customers, clean.customer_id_map, clean.orders, clean.order_items;

-- Regions: trim + map zone variants with CASE
CREATE TABLE clean.regions AS
SELECT region_id,
       initcap(trim(regexp_replace(city, '\s+', ' ', 'g'))) AS city,
       state,
       CASE lower(trim(region_name))
            WHEN 'north' THEN 'North' WHEN 'n. region' THEN 'North'
            WHEN 'south' THEN 'South' WHEN 'south zone' THEN 'South'
            WHEN 'east'  THEN 'East'
            WHEN 'west'  THEN 'West'  WHEN 'western' THEN 'West'
            WHEN 'central' THEN 'Central' WHEN 'centre' THEN 'Central'
       END AS region_name
FROM raw.regions;

-- Products: de-duplicate, standardise category, parse '₹1,299.00', impute cost by sub-category ratio
CREATE TABLE clean.products AS
WITH d AS (SELECT DISTINCT * FROM raw.products),
std AS (
    SELECT product_id, trim(product_name) AS product_name,
           CASE
               WHEN lower(trim(category)) IN ('electronics', 'electronic') THEN 'Electronics'
               WHEN lower(trim(category)) = 'fashion' THEN 'Fashion'
               WHEN lower(replace(trim(category), ' ', '')) IN ('home&kitchen', 'homeandkitchen') THEN 'Home & Kitchen'
               WHEN lower(trim(category)) IN ('beauty', 'beauty & personal care') THEN 'Beauty'
               WHEN lower(trim(category)) IN ('sports', 'sport') THEN 'Sports'
               WHEN lower(trim(category)) = 'books' THEN 'Books'
               WHEN lower(trim(category)) IN ('grocery', 'groceries') THEN 'Grocery'
           END AS category,
           sub_category, COALESCE(brand, 'Unbranded') AS brand,
           regexp_replace(unit_price, '[₹,]', '', 'g')::numeric AS unit_price,
           raw.try_num(unit_cost) AS unit_cost
    FROM d
)
SELECT s.product_id, s.product_name, s.category, s.sub_category, s.brand, s.unit_price,
       COALESCE(s.unit_cost, round(s.unit_price * r.cost_ratio, 2)) AS unit_cost,
       (s.unit_cost IS NULL) AS cost_imputed
FROM std s
JOIN (SELECT sub_category, percentile_cont(0.5) WITHIN GROUP (ORDER BY unit_cost / unit_price)::numeric AS cost_ratio
      FROM std WHERE unit_cost IS NOT NULL GROUP BY sub_category) r USING (sub_category);

-- Customers: exact de-dupe, then keep earliest record per normalised e-mail (ROW_NUMBER)
CREATE TABLE clean.customers AS
WITH d AS (SELECT DISTINCT * FROM raw.customers),
typed AS (
    SELECT customer_id,
           initcap(trim(first_name)) AS first_name,
           initcap(trim(last_name))  AS last_name,
           lower(trim(email))        AS email,
           CASE lower(trim(gender)) WHEN 'male' THEN 'Male' WHEN 'm' THEN 'Male'
                                    WHEN 'female' THEN 'Female' WHEN 'f' THEN 'Female' ELSE 'Not Specified' END AS gender,
           CASE WHEN raw.try_num(age) BETWEEN 18 AND 100 THEN raw.try_num(age)::int END AS age,
           region_id,
           CASE WHEN raw.try_date(signup_date) <= DATE '2025-12-31' THEN raw.try_date(signup_date) END AS signup_date,
           lower(trim(loyalty_member)) IN ('yes', 'y', 'true') AS loyalty_member
    FROM d
),
ranked AS (
    SELECT t.*,
           ROW_NUMBER() OVER (PARTITION BY COALESCE(email, customer_id) ORDER BY signup_date NULLS LAST, customer_id) AS rn,
           FIRST_VALUE(customer_id) OVER (PARTITION BY COALESCE(email, customer_id) ORDER BY signup_date NULLS LAST, customer_id) AS master_id
    FROM typed t
)
SELECT * FROM ranked;

CREATE TABLE clean.customer_id_map AS
SELECT customer_id AS duplicate_id, master_id FROM clean.customers WHERE rn > 1;
DELETE FROM clean.customers WHERE rn > 1;
ALTER TABLE clean.customers DROP COLUMN rn, DROP COLUMN master_id;
ALTER TABLE clean.customers ADD PRIMARY KEY (customer_id);

-- Orders: de-dupe, re-point duplicate customers, recover bad dates from payment_date, map channels
CREATE TABLE clean.orders AS
WITH d AS (SELECT DISTINCT * FROM raw.orders),
pay AS (SELECT DISTINCT ON (order_id) order_id, payment_date FROM raw.payments ORDER BY order_id)
SELECT d.order_id,
       CASE WHEN c.customer_id IS NOT NULL THEN c.customer_id ELSE 'C_UNKNOWN' END AS customer_id,
       COALESCE(CASE WHEN raw.try_date(d.order_date) <= DATE '2025-12-31' THEN raw.try_date(d.order_date) END,
                raw.try_date(p.payment_date)) AS order_date,
       d.region_id,
       initcap(trim(d.order_status)) AS order_status,
       CASE
           WHEN lower(trim(d.channel)) IN ('website', 'web') THEN 'CH01'
           WHEN lower(trim(d.channel)) IN ('mobile app', 'app', 'mobileapp') THEN 'CH02'
           WHEN lower(trim(d.channel)) IN ('marketplace', '3p marketplace') THEN 'CH03'
           WHEN lower(trim(d.channel)) IN ('retail store', 'store', 'offline store') THEN 'CH04'
           WHEN d.channel IS NULL AND d.promised_days = '0' THEN 'CH04'
           ELSE 'CH00'
       END AS channel_id,
       d.promised_days::int AS promised_days,
       raw.try_date(d.delivery_date) AS delivery_date
FROM d
LEFT JOIN clean.customer_id_map m ON m.duplicate_id = d.customer_id
LEFT JOIN clean.customers c ON c.customer_id = COALESCE(m.master_id, d.customer_id)
LEFT JOIN pay p ON p.order_id = d.order_id;
ALTER TABLE clean.orders ADD PRIMARY KEY (order_id);

-- Order items: de-dupe, cast types, re-derive invalid quantity / discount / missing amounts
CREATE TABLE clean.order_items AS
WITH d AS (SELECT DISTINCT * FROM raw.order_items),
t AS (
    SELECT order_item_id, order_id, product_id,
           raw.try_num(quantity) AS qty, regexp_replace(unit_price, ',', '', 'g')::numeric AS unit_price,
           raw.try_num(unit_cost) AS unit_cost, raw.try_num(discount_pct) AS disc, raw.try_num(line_amount) AS amt
    FROM d
),
q AS (
    SELECT t.*,
           CASE WHEN qty BETWEEN 1 AND 50 THEN qty
                ELSE round(amt / NULLIF(unit_price * (1 - LEAST(GREATEST(disc, 0), 0.6)), 0)) END AS qty_fixed
    FROM t
)
SELECT q.order_item_id, q.order_id,
       CASE WHEN p.product_id IS NULL THEN 'P_UNKNOWN' ELSE q.product_id END AS product_id,
       q.qty_fixed::int AS quantity, q.unit_price, q.unit_cost,
       CASE WHEN q.disc BETWEEN 0 AND 0.6 THEN q.disc ELSE round(1 - q.amt / NULLIF(q.qty_fixed * q.unit_price, 0), 2) END AS discount_pct,
       COALESCE(q.amt, round(q.qty_fixed * q.unit_price * (1 - q.disc), 2)) AS line_amount
FROM q LEFT JOIN clean.products p ON p.product_id = q.product_id
WHERE q.qty_fixed BETWEEN 1 AND 50 AND COALESCE(q.amt, q.qty_fixed * q.unit_price * (1 - q.disc)) IS NOT NULL;

-- Reconciliation: SQL cleaning vs Python mart (should match or differ only by documented rules)
SELECT 'customers' AS entity, (SELECT COUNT(*) FROM clean.customers) AS sql_clean,
       (SELECT COUNT(*) FROM mart.dim_customer WHERE customer_key <> -1) AS python_mart
UNION ALL
SELECT 'orders (non-cancelled)', (SELECT COUNT(*) FROM clean.orders WHERE order_status <> 'Cancelled'),
       (SELECT COUNT(DISTINCT order_id) FROM mart.fact_sales)
UNION ALL
SELECT 'revenue (non-cancelled, INR)',
       (SELECT round(SUM(oi.line_amount)) FROM clean.order_items oi JOIN clean.orders o USING (order_id) WHERE o.order_status <> 'Cancelled'),
       (SELECT round(SUM(net_revenue)) FROM mart.fact_sales);
