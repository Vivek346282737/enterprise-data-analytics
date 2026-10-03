-- =====================================================================
-- 03_indexes.sql : indexes for the analytical access paths
-- Facts are filtered/joined by date and dimension keys -> index every FK.
-- =====================================================================
CREATE INDEX ix_fs_date      ON mart.fact_sales (date_key);
CREATE INDEX ix_fs_customer  ON mart.fact_sales (customer_key);
CREATE INDEX ix_fs_product   ON mart.fact_sales (product_key);
CREATE INDEX ix_fs_region    ON mart.fact_sales (region_key);
CREATE INDEX ix_fs_channel   ON mart.fact_sales (channel_key);
CREATE INDEX ix_fs_order     ON mart.fact_sales (order_id);
-- composite index for the very common "customer history in date order" pattern (cohorts, LAG on orders)
CREATE INDEX ix_fs_cust_date ON mart.fact_sales (customer_key, date_key);
CREATE INDEX ix_fr_product   ON mart.fact_returns (product_key);
CREATE INDEX ix_fr_odate     ON mart.fact_returns (order_date_key);
CREATE INDEX ix_fsup_created ON mart.fact_support (created_date_key);
CREATE INDEX ix_fsup_cat     ON mart.fact_support (ticket_category, priority);
CREATE INDEX ix_dc_segment   ON mart.dim_customer (segment);
CREATE INDEX ix_dp_category  ON mart.dim_product (category);
CREATE INDEX ix_dd_ym        ON mart.dim_date (year_month);
-- raw layer: support the profiling / duplicate checks
CREATE INDEX ix_raw_cust_email ON raw.customers (lower(trim(email)));
CREATE INDEX ix_raw_orders_id  ON raw.orders (order_id);
