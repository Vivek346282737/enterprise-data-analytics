-- =====================================================================
-- 01_schema.sql : database layers
-- raw   : source CSVs loaded as TEXT (nothing coerced, defects preserved)
-- clean : typed & de-duplicated tables produced by SQL cleaning (05_cleaning.sql)
-- mart  : star schema (facts + dimensions) loaded from the Python pipeline
-- Run with: psql -d enterprise_analytics -f sql/01_schema.sql
-- =====================================================================
DROP SCHEMA IF EXISTS mart CASCADE;
DROP SCHEMA IF EXISTS clean CASCADE;
DROP SCHEMA IF EXISTS raw CASCADE;
CREATE SCHEMA raw;
CREATE SCHEMA clean;
CREATE SCHEMA mart;
COMMENT ON SCHEMA raw   IS 'Landing zone: synthetic source extracts stored as text';
COMMENT ON SCHEMA clean IS 'Typed, standardised, de-duplicated tables (SQL cleaning layer)';
COMMENT ON SCHEMA mart  IS 'Analytical star schema consumed by Power BI / Tableau';
