-- =====================================================================
-- 04_data_quality.sql : data-quality checks on the RAW layer
-- Each query returns the number (and examples) of rows breaking a rule.
-- =====================================================================

-- Helper: safe casts (PostgreSQL has no TRY_CAST)
CREATE OR REPLACE FUNCTION raw.try_date(t TEXT) RETURNS DATE LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    IF t ~ '^\d{4}-\d{2}-\d{2}$' THEN RETURN t::date; END IF;
    IF t ~ '^\d{2}/\d{2}/\d{4}$' THEN RETURN to_date(t, 'DD/MM/YYYY'); END IF;
    RETURN NULL;
EXCEPTION WHEN others THEN RETURN NULL;          -- e.g. 2024-02-31
END $$;

CREATE OR REPLACE FUNCTION raw.try_num(t TEXT) RETURNS NUMERIC LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN t::numeric;
EXCEPTION WHEN others THEN RETURN NULL;
END $$;

-- 1. Completeness: missing values per critical column (UNION ALL into one result)
SELECT 'customers' AS table_name, 'email' AS column_name, COUNT(*) FILTER (WHERE email IS NULL OR trim(email) = '') AS missing, COUNT(*) AS total FROM raw.customers
UNION ALL SELECT 'customers', 'gender', COUNT(*) FILTER (WHERE gender IS NULL), COUNT(*) FROM raw.customers
UNION ALL SELECT 'products', 'unit_cost', COUNT(*) FILTER (WHERE unit_cost IS NULL), COUNT(*) FROM raw.products
UNION ALL SELECT 'orders', 'channel', COUNT(*) FILTER (WHERE channel IS NULL), COUNT(*) FROM raw.orders
UNION ALL SELECT 'order_items', 'line_amount', COUNT(*) FILTER (WHERE line_amount IS NULL), COUNT(*) FROM raw.order_items
UNION ALL SELECT 'payments', 'payment_method', COUNT(*) FILTER (WHERE payment_method IS NULL), COUNT(*) FROM raw.payments
UNION ALL SELECT 'support_tickets', 'priority', COUNT(*) FILTER (WHERE priority IS NULL), COUNT(*) FROM raw.support_tickets
ORDER BY missing DESC;

-- 2. Uniqueness: exact duplicate rows and duplicate primary keys
SELECT 'orders' AS table_name, COUNT(*) - COUNT(DISTINCT o.*) AS exact_duplicates,
       COUNT(*) - COUNT(DISTINCT order_id) AS duplicate_keys FROM raw.orders o
UNION ALL
SELECT 'order_items', COUNT(*) - COUNT(DISTINCT oi.*), COUNT(*) - COUNT(DISTINCT order_item_id) FROM raw.order_items oi
UNION ALL
SELECT 'customers', COUNT(*) - COUNT(DISTINCT c.*), COUNT(*) - COUNT(DISTINCT customer_id) FROM raw.customers c;

-- 3. Duplicate customers: same normalised e-mail under several customer_ids
SELECT lower(trim(email)) AS email_key, COUNT(DISTINCT customer_id) AS ids, string_agg(DISTINCT customer_id, ', ') AS customer_ids
FROM raw.customers
WHERE email IS NOT NULL
GROUP BY lower(trim(email))
HAVING COUNT(DISTINCT customer_id) > 1
ORDER BY ids DESC
LIMIT 20;

-- 4. Validity: data types (text in numeric columns)
SELECT 'products.unit_price' AS col, COUNT(*) AS non_numeric, MIN(unit_price) AS example
FROM raw.products WHERE raw.try_num(unit_price) IS NULL AND unit_price IS NOT NULL
UNION ALL
SELECT 'order_items.unit_price', COUNT(*), MIN(unit_price) FROM raw.order_items WHERE raw.try_num(unit_price) IS NULL
UNION ALL
SELECT 'customers.age', COUNT(*), MIN(age) FROM raw.customers WHERE raw.try_num(age) IS NULL AND age IS NOT NULL;

-- 5. Validity: invalid / out-of-window dates
SELECT 'orders.order_date' AS col,
       COUNT(*) FILTER (WHERE raw.try_date(order_date) IS NULL) AS unparseable,
       COUNT(*) FILTER (WHERE raw.try_date(order_date) > DATE '2025-12-31') AS future_dates,
       COUNT(*) FILTER (WHERE order_date ~ '^\d{2}/') AS non_iso_format
FROM raw.orders
UNION ALL
SELECT 'customers.signup_date', COUNT(*) FILTER (WHERE raw.try_date(signup_date) IS NULL),
       COUNT(*) FILTER (WHERE raw.try_date(signup_date) > DATE '2025-12-31'), COUNT(*) FILTER (WHERE signup_date ~ '^\d{2}/')
FROM raw.customers;

-- 6. Validity: business ranges and outliers
SELECT COUNT(*) FILTER (WHERE raw.try_num(quantity) <= 0)              AS non_positive_qty,
       COUNT(*) FILTER (WHERE raw.try_num(quantity) > 50)              AS qty_over_50,
       COUNT(*) FILTER (WHERE raw.try_num(discount_pct) NOT BETWEEN 0 AND 0.6) AS invalid_discount,
       MAX(raw.try_num(quantity))                                      AS max_qty
FROM raw.order_items;

SELECT COUNT(*) FILTER (WHERE raw.try_num(age) NOT BETWEEN 18 AND 100) AS invalid_age FROM raw.customers;
SELECT COUNT(*) FILTER (WHERE raw.try_num(amount) < 0) AS negative_payments FROM raw.payments;

-- IQR outlier fence for line amounts (PERCENTILE_CONT)
WITH q AS (
    SELECT percentile_cont(0.25) WITHIN GROUP (ORDER BY raw.try_num(line_amount)) AS q1,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY raw.try_num(line_amount)) AS q3
    FROM raw.order_items
)
SELECT q1, q3, q3 + 3 * (q3 - q1) AS extreme_fence,
       (SELECT COUNT(*) FROM raw.order_items WHERE raw.try_num(line_amount) > q3 + 3 * (q3 - q1)) AS extreme_outliers
FROM q;

-- 7. Consistency: label variants (category, region, channel, status)
SELECT category, COUNT(*) AS products FROM raw.products GROUP BY category ORDER BY lower(trim(category)), category;
SELECT region_name, COUNT(*) FROM raw.regions GROUP BY region_name ORDER BY 1;
SELECT channel, COUNT(*) FROM raw.orders GROUP BY channel ORDER BY 2 DESC;
SELECT COUNT(*) AS names_with_extra_spaces FROM raw.customers WHERE first_name <> trim(first_name) OR last_name <> trim(last_name);

-- 8. Referential integrity (LEFT JOIN anti-joins)
SELECT 'orders -> customers' AS relationship, COUNT(*) AS orphans
FROM raw.orders o LEFT JOIN raw.customers c ON c.customer_id = o.customer_id WHERE c.customer_id IS NULL
UNION ALL
SELECT 'order_items -> products', COUNT(*)
FROM raw.order_items oi LEFT JOIN raw.products p ON p.product_id = oi.product_id WHERE p.product_id IS NULL
UNION ALL
SELECT 'returns -> order_items', COUNT(*)
FROM raw.returns r LEFT JOIN (SELECT DISTINCT order_item_id FROM raw.order_items) oi ON oi.order_item_id = r.order_item_id
WHERE oi.order_item_id IS NULL;

-- 9. Cross-field rule: ticket resolved before it was created
SELECT COUNT(*) AS resolved_before_created
FROM raw.support_tickets
WHERE resolved_at IS NOT NULL AND resolved_at::timestamp < created_at::timestamp;

-- 10. Payment reconciliation: payment amount vs sum of order lines
WITH lines AS (
    SELECT order_id, SUM(raw.try_num(line_amount)) AS line_total
    FROM (SELECT DISTINCT * FROM raw.order_items) d GROUP BY order_id
), pay AS (
    SELECT order_id, MAX(raw.try_num(amount)) AS paid FROM raw.payments GROUP BY order_id
)
SELECT COUNT(*) AS orders_compared,
       COUNT(*) FILTER (WHERE abs(abs(p.paid) - l.line_total) > 1) AS mismatched_orders
FROM lines l JOIN pay p USING (order_id);
