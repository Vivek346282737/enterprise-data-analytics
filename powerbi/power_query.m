// =====================================================================
// Power Query (M): load the star schema from the pipeline output folder.
// 1. In Power BI: Home > Transform data > Manage Parameters > New parameter
//      Name: ProjectFolder   Type: Text   Value: C:\path\to\enterprise-data-analytics\
// 2. Create one Blank Query per table and paste the matching block (Advanced Editor).
// =====================================================================

// ---------- helper: fnLoadCsv (Blank Query named fnLoadCsv) ----------
(fileName as text) as table =>
let
    Source   = Csv.Document(File.Contents(ProjectFolder & "data\processed\mart\" & fileName & ".csv"),
                            [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true])
in
    Promoted

// ---------- FactSales ----------
let
    Source = fnLoadCsv("FactSales"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"sales_key", Int64.Type}, {"date_key", Int64.Type}, {"customer_key", Int64.Type}, {"product_key", Int64.Type},
        {"region_key", Int64.Type}, {"channel_key", Int64.Type}, {"quantity", Int64.Type},
        {"unit_price", Currency.Type}, {"discount_pct", type number}, {"gross_amount", Currency.Type},
        {"discount_amount", Currency.Type}, {"net_revenue", Currency.Type}, {"cost_amount", Currency.Type},
        {"profit", Currency.Type}, {"delivery_days", Int64.Type}, {"is_on_time", type logical}, {"is_returned", type logical}},
        "en-US")
in
    Typed

// ---------- FactReturns ----------
let
    Source = fnLoadCsv("FactReturns"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"return_key", Int64.Type}, {"order_date_key", Int64.Type}, {"return_date_key", Int64.Type},
        {"customer_key", Int64.Type}, {"product_key", Int64.Type}, {"region_key", Int64.Type}, {"channel_key", Int64.Type},
        {"return_qty", Int64.Type}, {"refund_amount", Currency.Type}, {"return_date_invalid", type logical}}, "en-US")
in
    Typed

// ---------- FactSupport ----------
let
    Source = fnLoadCsv("FactSupport"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"ticket_key", Int64.Type}, {"created_date_key", Int64.Type}, {"customer_key", Int64.Type},
        {"region_key", Int64.Type}, {"channel_key", Int64.Type}, {"created_at", type datetime}, {"resolved_at", type datetime},
        {"resolution_hours", type number}, {"csat_score", type number}, {"sla_target_hours", Int64.Type},
        {"sla_met", type logical}, {"timestamp_invalid", type logical}}, "en-US")
in
    Typed

// ---------- DimDate ----------
let
    Source = fnLoadCsv("DimDate"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"date_key", Int64.Type}, {"date", type date}, {"year", Int64.Type}, {"month", Int64.Type},
        {"month_start", type date}, {"week_of_year", Int64.Type}, {"day_of_week", Int64.Type},
        {"is_weekend", type logical}, {"is_festive_season", type logical}}, "en-US")
in
    Typed

// ---------- DimCustomer ----------
let
    Source = fnLoadCsv("DimCustomer"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"customer_key", Int64.Type}, {"age", Int64.Type}, {"signup_date", type date}, {"loyalty_member", type logical},
        {"first_order_date", type date}, {"signup_date_imputed", type logical}, {"recency_days", Int64.Type},
        {"frequency", Int64.Type}, {"monetary", Currency.Type}, {"r_score", Int64.Type}, {"f_score", Int64.Type},
        {"m_score", Int64.Type}}, "en-US"),
    // Power Query cleaning example: replace blanks with explicit labels
    Filled = Table.ReplaceValue(Typed, "", "Unknown", Replacer.ReplaceValue, {"age_band", "cohort_month"})
in
    Filled

// ---------- DimProduct ----------
let
    Source = fnLoadCsv("DimProduct"),
    Typed  = Table.TransformColumnTypes(Source, {
        {"product_key", Int64.Type}, {"unit_price", Currency.Type}, {"unit_cost", Currency.Type}, {"cost_imputed", type logical}}, "en-US"),
    Trimmed = Table.TransformColumns(Typed, {{"product_name", Text.Trim, type text}, {"category", Text.Proper, type text}})
in
    Trimmed

// ---------- DimRegion ----------
let
    Source = fnLoadCsv("DimRegion"),
    Typed  = Table.TransformColumnTypes(Source, {{"region_key", Int64.Type}})
in
    Typed

// ---------- DimChannel ----------
let
    Source = fnLoadCsv("DimChannel"),
    Typed  = Table.TransformColumnTypes(Source, {{"channel_key", Int64.Type}})
in
    Typed

// ---------- DQ_Scores (Page 6) ----------
let
    Source   = Csv.Document(File.Contents(ProjectFolder & "data\outputs\data_quality\dq_scores.csv"), [Delimiter = ",", Encoding = 65001]),
    Promoted = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),
    Unpivot  = Table.UnpivotOtherColumns(Promoted, {"layer", "table"}, "dimension", "score"),
    Typed    = Table.TransformColumnTypes(Unpivot, {{"score", type number}}, "en-US")
in
    Typed
