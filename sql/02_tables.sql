-- =====================================================================
-- 02_tables.sql : RAW landing tables + MART star schema with PK / FK
-- =====================================================================

-- ---------- RAW (all TEXT on purpose: data types are validated later) ----------
CREATE TABLE raw.regions        (region_id TEXT, city TEXT, state TEXT, region_name TEXT, country TEXT);
CREATE TABLE raw.customers      (customer_id TEXT, first_name TEXT, last_name TEXT, email TEXT, phone TEXT, gender TEXT,
                                 age TEXT, region_id TEXT, signup_date TEXT, preferred_channel TEXT, loyalty_member TEXT);
CREATE TABLE raw.products       (product_id TEXT, product_name TEXT, category TEXT, sub_category TEXT, brand TEXT,
                                 unit_price TEXT, unit_cost TEXT, launch_date TEXT);
CREATE TABLE raw.orders         (order_id TEXT, customer_id TEXT, order_date TEXT, region_id TEXT, order_status TEXT,
                                 promised_days TEXT, delivery_date TEXT, channel TEXT);
CREATE TABLE raw.order_items    (order_item_id TEXT, order_id TEXT, product_id TEXT, quantity TEXT, unit_price TEXT,
                                 unit_cost TEXT, discount_pct TEXT, line_amount TEXT);
CREATE TABLE raw.payments       (payment_id TEXT, order_id TEXT, payment_date TEXT, payment_method TEXT, amount TEXT, payment_status TEXT);
CREATE TABLE raw.returns        (return_id TEXT, order_item_id TEXT, order_id TEXT, product_id TEXT, return_date TEXT,
                                 return_qty TEXT, return_reason TEXT, refund_amount TEXT, return_status TEXT);
CREATE TABLE raw.support_tickets(ticket_id TEXT, order_id TEXT, customer_id TEXT, created_at TEXT, resolved_at TEXT,
                                 ticket_category TEXT, priority TEXT, ticket_status TEXT, agent_channel TEXT, csat_score TEXT);

-- ---------- MART : dimensions ----------
CREATE TABLE mart.dim_date (
    date_key          INT PRIMARY KEY,            -- YYYYMMDD
    date              DATE NOT NULL UNIQUE,
    year              SMALLINT NOT NULL,
    quarter           VARCHAR(2) NOT NULL,
    month             SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    month_name        VARCHAR(3) NOT NULL,
    year_month        CHAR(7) NOT NULL,
    month_start       DATE NOT NULL,
    week_of_year      SMALLINT,
    day_of_week       SMALLINT,
    day_name          VARCHAR(3),
    is_weekend        BOOLEAN,
    is_festive_season BOOLEAN,
    fiscal_year       VARCHAR(4)
);

CREATE TABLE mart.dim_region (
    region_key  INT PRIMARY KEY,
    region_id   VARCHAR(5) NOT NULL UNIQUE,
    city        VARCHAR(40) NOT NULL,
    state       VARCHAR(40),
    region_name VARCHAR(10) NOT NULL,             -- zone: North/South/East/West/Central
    country     VARCHAR(20)
);

CREATE TABLE mart.dim_channel (
    channel_key  INT PRIMARY KEY,
    channel_id   VARCHAR(5) NOT NULL UNIQUE,
    channel_name VARCHAR(20) NOT NULL,
    channel_type VARCHAR(10) NOT NULL
);

CREATE TABLE mart.dim_product (
    product_key  INT PRIMARY KEY,                 -- -1 = Unknown product
    product_id   VARCHAR(12) NOT NULL UNIQUE,
    product_name VARCHAR(80),
    category     VARCHAR(30),
    sub_category VARCHAR(30),
    brand        VARCHAR(30),
    unit_price   NUMERIC(12,2),
    unit_cost    NUMERIC(12,2),
    price_band   VARCHAR(20),
    cost_imputed BOOLEAN
);

CREATE TABLE mart.dim_customer (
    customer_key        INT PRIMARY KEY,          -- -1 = Unknown customer
    customer_id         VARCHAR(12) NOT NULL UNIQUE,
    full_name           VARCHAR(80),
    gender              VARCHAR(15),
    age                 SMALLINT,
    age_band            VARCHAR(10),
    region_id           VARCHAR(5),
    city                VARCHAR(40),
    state               VARCHAR(40),
    region_name         VARCHAR(10),
    signup_date         DATE,
    loyalty_member      BOOLEAN,
    preferred_channel   VARCHAR(20),
    first_order_date    DATE,
    cohort_month        CHAR(7),
    signup_date_imputed BOOLEAN,
    recency_days        INT,
    frequency           INT,
    monetary            NUMERIC(14,2),
    r_score             SMALLINT,
    f_score             SMALLINT,
    m_score             SMALLINT,
    rfm_score           CHAR(3),
    segment             VARCHAR(20)
);

-- ---------- MART : facts ----------
CREATE TABLE mart.fact_sales (
    sales_key       BIGINT PRIMARY KEY,
    order_item_id   VARCHAR(12) NOT NULL UNIQUE,
    order_id        VARCHAR(10) NOT NULL,
    date_key        INT NOT NULL REFERENCES mart.dim_date(date_key),
    customer_key    INT NOT NULL REFERENCES mart.dim_customer(customer_key),
    product_key     INT NOT NULL REFERENCES mart.dim_product(product_key),
    region_key      INT NOT NULL REFERENCES mart.dim_region(region_key),
    channel_key     INT NOT NULL REFERENCES mart.dim_channel(channel_key),
    quantity        INT NOT NULL CHECK (quantity > 0),
    unit_price      NUMERIC(12,2) NOT NULL,
    discount_pct    NUMERIC(6,4) CHECK (discount_pct BETWEEN 0 AND 0.6),
    gross_amount    NUMERIC(14,2) NOT NULL,
    discount_amount NUMERIC(14,2) NOT NULL,
    net_revenue     NUMERIC(14,2) NOT NULL,
    cost_amount     NUMERIC(14,2),
    profit          NUMERIC(14,2),
    payment_method  VARCHAR(20),
    order_status    VARCHAR(12),
    delivery_days   INT,
    is_on_time      BOOLEAN,
    is_returned     BOOLEAN NOT NULL
);

CREATE TABLE mart.fact_returns (
    return_key          BIGINT PRIMARY KEY,
    return_id           VARCHAR(12) NOT NULL UNIQUE,
    order_item_id       VARCHAR(12) NOT NULL REFERENCES mart.fact_sales(order_item_id),
    order_id            VARCHAR(10) NOT NULL,
    order_date_key      INT NOT NULL REFERENCES mart.dim_date(date_key),
    return_date_key     INT REFERENCES mart.dim_date(date_key),
    customer_key        INT NOT NULL REFERENCES mart.dim_customer(customer_key),
    product_key         INT NOT NULL REFERENCES mart.dim_product(product_key),
    region_key          INT NOT NULL REFERENCES mart.dim_region(region_key),
    channel_key         INT NOT NULL REFERENCES mart.dim_channel(channel_key),
    return_qty          INT NOT NULL,
    refund_amount       NUMERIC(14,2) NOT NULL,
    return_reason       VARCHAR(30),
    return_status       VARCHAR(12),
    return_date_invalid BOOLEAN
);

CREATE TABLE mart.fact_support (
    ticket_key        BIGINT PRIMARY KEY,
    ticket_id         VARCHAR(10) NOT NULL UNIQUE,
    order_id          VARCHAR(10) NOT NULL,
    created_date_key  INT NOT NULL REFERENCES mart.dim_date(date_key),
    customer_key      INT NOT NULL REFERENCES mart.dim_customer(customer_key),
    region_key        INT NOT NULL REFERENCES mart.dim_region(region_key),
    channel_key       INT NOT NULL REFERENCES mart.dim_channel(channel_key),
    created_at        TIMESTAMP NOT NULL,
    resolved_at       TIMESTAMP,
    resolution_hours  NUMERIC(8,2),
    ticket_category   VARCHAR(20),
    priority          VARCHAR(12),
    ticket_status     VARCHAR(10),
    agent_channel     VARCHAR(10),
    csat_score        NUMERIC(3,1) CHECK (csat_score BETWEEN 1 AND 5),
    sla_target_hours  INT,
    sla_met           BOOLEAN,
    timestamp_invalid BOOLEAN
);
