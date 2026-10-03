"""Build excel/analytics_dashboard.xlsx: a formula-driven analytics workbook.

Data sheets hold pipeline outputs; analysis sheets calculate everything with live Excel
formulas (SUMIFS, COUNTIFS, AVERAGEIFS, XLOOKUP, INDEX/MATCH, IF/IFS/IFERROR, date functions),
plus conditional formatting, data validation and native Excel charts.
"""
from __future__ import annotations

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, PieChart, Reference
from openpyxl.formatting.rule import CellIsRule, ColorScaleRule, DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

from python.config import EXCEL_DIR, RAW_DIR, get_logger

log = get_logger("reporting.excel")
HDR = PatternFill("solid", fgColor="1F3A5F")
HFONT = Font(color="FFFFFF", bold=True)
INPUT = PatternFill("solid", fgColor="FFF4CC")
CARD = PatternFill("solid", fgColor="EAF1FB")
THIN = Border(*(Side(style="thin", color="BFBFBF"),) * 4)
INR = '[>=10000000]"₹"#,##0.00,,,," Cr";[>=100000]"₹"#,##0.00,," L";"₹"#,##0'
INR_PLAIN = '"₹"#,##0'
PCT = "0.00%"


def _title(ws, text, sub=None):
    ws["A1"] = text
    ws["A1"].font = Font(size=15, bold=True, color="1F3A5F")
    if sub:
        ws["A2"] = sub
        ws["A2"].font = Font(italic=True, color="666666")


def _write_df(ws, df: pd.DataFrame, r0: int = 4, c0: int = 1, table: str | None = None, widths=True):
    for j, col in enumerate(df.columns):
        c = ws.cell(r0, c0 + j, col)
        c.fill, c.font = HDR, HFONT
    for i, row in enumerate(df.itertuples(index=False), start=1):
        for j, v in enumerate(row):
            ws.cell(r0 + i, c0 + j, None if pd.isna(v) else (v.item() if hasattr(v, "item") else v))
    if table:
        ref = f"{get_column_letter(c0)}{r0}:{get_column_letter(c0 + len(df.columns) - 1)}{r0 + len(df)}"
        t = Table(displayName=table, ref=ref)
        t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
        ws.add_table(t)
    if widths:
        for j, col in enumerate(df.columns):
            ws.column_dimensions[get_column_letter(c0 + j)].width = max(11, min(28, len(str(col)) + 3))
    return r0 + len(df)


def _hdr(ws, row, col, labels):
    for j, l in enumerate(labels):
        c = ws.cell(row, col + j, l)
        c.fill, c.font = HDR, HFONT
        c.alignment = Alignment(horizontal="center", wrap_text=True)


def build_workbook(mart: dict[str, pd.DataFrame], k: dict, issues: pd.DataFrame, scores: pd.DataFrame,
                   clean_checks: pd.DataFrame, raw_checks: pd.DataFrame) -> str:
    EXCEL_DIR.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    wb.calculation.fullCalcOnLoad = True

    # ---------------- Raw_Data ----------------
    ws = wb.active
    ws.title = "Raw_Data"
    raw_p = pd.read_csv(RAW_DIR / "products.csv", dtype=str)
    _title(ws, "Raw Data: products.csv as received (synthetic)",
           "Unmodified source rows. Note the inconsistent categories, '₹1,299.00' text prices, blanks and duplicates (highlighted).")
    end = _write_df(ws, raw_p, table="tblRawProducts")
    ws.conditional_formatting.add(f"A5:I{end}", CellIsRule(operator="equal", formula=['""'], fill=PatternFill("solid", fgColor="FDE2E2")))
    ws["K4"], ws["K5"], ws["K6"] = "Check", "Blank unit_cost", "Text prices (contain ₹)"
    ws["L4"], ws["L5"], ws["L6"] = "Count", f"=COUNTBLANK(G5:G{end})", f'=COUNTIF(F5:F{end},"₹*")'
    ws["K7"], ws["L7"] = "Distinct category spellings", f"=SUMPRODUCT(1/COUNTIF(C5:C{end},C5:C{end}))"
    for c in ("K4", "L4"):
        ws[c].fill, ws[c].font = HDR, HFONT
    ws.column_dimensions["K"].width = 28

    # ---------------- Cleaned_Data: monthly aggregate (month x region x channel x category) ----------------
    s = (mart["FactSales"].merge(mart["DimDate"][["date_key", "month_start"]], on="date_key")
         .merge(mart["DimRegion"][["region_key", "region_name"]], on="region_key", how="left")
         .merge(mart["DimChannel"][["channel_key", "channel_name"]], on="channel_key")
         .merge(mart["DimProduct"][["product_key", "category"]], on="product_key"))
    agg = s.groupby(["month_start", "region_name", "channel_name", "category"], dropna=False).agg(
        revenue=("net_revenue", "sum"), cost=("cost_amount", "sum"), gross=("gross_amount", "sum"),
        units=("quantity", "sum"), lines=("sales_key", "count"), returned_lines=("is_returned", "sum")).reset_index()
    agg["region_name"] = agg["region_name"].fillna("Unknown")
    agg["month_start"] = pd.to_datetime(agg["month_start"]).dt.date
    agg[["revenue", "cost", "gross"]] = agg[["revenue", "cost", "gross"]].round(2)
    agg["returned_lines"] = agg["returned_lines"].astype(int)
    ws = wb.create_sheet("Cleaned_Data")
    _title(ws, "Cleaned Data: monthly sales cube from the star schema",
           "Grain: month x region x channel x category. Columns K-O are Excel formulas (profit, margin, year, quarter, month).")
    end = _write_df(ws, agg, table=None)
    # columns: A month B region C channel D category E revenue F cost G gross H units I lines J returned_lines
    _hdr(ws, 4, 11, ["profit", "margin", "year", "quarter", "month_name"])
    for r in range(5, end + 1):
        ws.cell(r, 1).number_format = "yyyy-mm"
        ws.cell(r, 11, f"=E{r}-F{r}")
        ws.cell(r, 12, f"=IFERROR(K{r}/E{r},0)").number_format = PCT
        ws.cell(r, 13, f"=YEAR(A{r})")
        ws.cell(r, 14, f'="Q"&ROUNDUP(MONTH(A{r})/3,0)')
        ws.cell(r, 15, f'=TEXT(A{r},"mmm")')
    t = Table(displayName="tblSales", ref=f"A4:O{end}")
    t.tableStyleInfo = TableStyleInfo(name="TableStyleLight9", showRowStripes=True)
    ws.add_table(t)
    CD = f"Cleaned_Data!$%s$5:$%s${end}"

    def col(letter):
        return CD % (letter, letter)
    MONTH, REG, CHN, CAT, REV, COST, GROSS, UNITS, LINES, RET, PROF, YEAR = (col(x) for x in "ABCDEFGHIJKM")
    ws.freeze_panes = "A5"

    # ---------------- Customer_Analysis (data used by KPI sheet) ----------------
    dc = mart["DimCustomer"]
    cs = (mart["FactSales"][mart["FactSales"]["customer_key"] != -1].merge(mart["DimDate"][["date_key", "date"]], on="date_key")
          .groupby("customer_key").agg(orders=("order_id", "nunique"), revenue=("net_revenue", "sum"), profit=("profit", "sum"),
                                       first_order=("date", "min"), last_order=("date", "max")).reset_index())
    cs = cs.merge(dc[["customer_key", "customer_id", "full_name", "region_name", "city", "loyalty_member", "segment",
                      "r_score", "f_score", "m_score"]], on="customer_key")
    cs = cs[["customer_id", "full_name", "region_name", "city", "loyalty_member", "segment", "orders", "revenue", "profit",
             "first_order", "last_order", "r_score", "f_score", "m_score"]].sort_values("revenue", ascending=False)
    cs["first_order"] = pd.to_datetime(cs["first_order"]).dt.date
    cs["last_order"] = pd.to_datetime(cs["last_order"]).dt.date
    cs[["revenue", "profit"]] = cs[["revenue", "profit"]].round(2)
    cs["loyalty_member"] = cs["loyalty_member"].map({True: "Yes", False: "No"})
    ws = wb.create_sheet("Customer_Analysis")
    _title(ws, "Customer Analysis: RFM segments, lookups and customer KPIs",
           "Type a customer_id in the yellow cell. XLOOKUP and INDEX/MATCH return the details. Segment table uses COUNTIFS/SUMIFS/AVERAGEIFS.")
    cend = _write_df(ws, cs, r0=4, c0=1, table="tblCustomers")
    _hdr(ws, 4, 15, ["days_since_last_order", "repeat_flag"])
    for r in range(5, cend + 1):
        ws.cell(r, 15, f"=DATE(2026,1,1)-K{r}")
        ws.cell(r, 16, f'=IF(G{r}>=2,"Repeat","One-time")')
        for cc in (8, 9):
            ws.cell(r, cc).number_format = INR_PLAIN
    CA = lambda L: f"Customer_Analysis!${L}$5:${L}${cend}"  # noqa: E731
    ws["R4"], ws["S4"] = "Customer lookup", "Value"
    ws["R5"], ws["S5"] = "customer_id (input)", cs.iloc[0]["customer_id"]
    ws["S5"].fill = INPUT
    look = [("Name (XLOOKUP)", f'=_xlfn.XLOOKUP(S5,{CA("A")},{CA("B")},"Not found")'),
            ("Segment (XLOOKUP)", f'=_xlfn.XLOOKUP(S5,{CA("A")},{CA("F")},"Not found")'),
            ("Name (INDEX/MATCH)", f'=IFERROR(INDEX({CA("B")},MATCH(S5,{CA("A")},0)),"Not found")'),
            ("Revenue (INDEX/MATCH)", f'=IFERROR(INDEX({CA("H")},MATCH(S5,{CA("A")},0)),0)'),
            ("Orders (INDEX/MATCH)", f'=IFERROR(INDEX({CA("G")},MATCH(S5,{CA("A")},0)),0)'),
            ("Revenue rank", f'=IFERROR(_xlfn.RANK.EQ(S9,{CA("H")},0),"-")')]
    for i, (lab, f) in enumerate(look, start=6):
        ws.cell(i, 18, lab)
        ws.cell(i, 19, f)
    ws["S9"].number_format = INR_PLAIN
    for c in ("R4", "S4"):
        ws[c].fill, ws[c].font = HDR, HFONT
    segs = ["High Value", "Loyal", "New", "Occasional", "At Risk", "Hibernating"]
    _hdr(ws, 14, 18, ["Segment", "Customers", "Revenue", "Avg orders", "Revenue share", "Avg revenue/customer"])
    for i, sg in enumerate(segs, start=15):
        ws.cell(i, 18, sg)
        ws.cell(i, 19, f'=COUNTIFS({CA("F")},R{i})')
        ws.cell(i, 20, f'=SUMIFS({CA("H")},{CA("F")},R{i})').number_format = INR
        ws.cell(i, 21, f'=IFERROR(AVERAGEIFS({CA("G")},{CA("F")},R{i}),0)').number_format = "0.00"
        ws.cell(i, 22, f"=IFERROR(T{i}/SUM($T$15:$T$20),0)").number_format = PCT
        ws.cell(i, 23, f"=IFERROR(T{i}/S{i},0)").number_format = INR_PLAIN
    ws.conditional_formatting.add("V15:V20", DataBarRule(start_type="num", start_value=0, end_type="max", color="2563EB"))
    ws["R23"], ws["S23"] = "Repeat customer %", f'=COUNTIFS({CA("P")},"Repeat")/COUNTA({CA("A")})'
    ws["S23"].number_format = PCT
    ws["R24"], ws["S24"] = "Loyalty filter (select)", "Yes"
    ws["S24"].fill = INPUT
    dv = DataValidation(type="list", formula1='"Yes,No"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add("S24")
    ws["R25"], ws["S25"] = "Avg orders for selection", f'=AVERAGEIFS({CA("G")},{CA("E")},S24)'
    ws["S25"].number_format = "0.00"
    ws.column_dimensions["R"].width = 24
    ws.column_dimensions["S"].width = 20
    pie = PieChart()
    pie.title = "Revenue by RFM segment"
    pie.add_data(Reference(ws, min_col=20, min_row=14, max_row=20), titles_from_data=True)
    pie.set_categories(Reference(ws, min_col=18, min_row=15, max_row=20))
    pie.height, pie.width = 7, 11
    ws.add_chart(pie, "R27")
    ws.freeze_panes = "A5"

    # ---------------- KPI_Summary ----------------
    ws = wb.create_sheet("KPI_Summary", 2)
    _title(ws, "KPI Summary: all values are live formulas over Cleaned_Data and Customer_Analysis")
    ws["A4"], ws["B4"], ws["C4"] = "KPI", "All years", "Selected year"
    ws["E4"], ws["F4"] = "Select year", 2025
    ws["F4"].fill = INPUT
    dv = DataValidation(type="list", formula1='"2023,2024,2025"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add("F4")
    for c in ("A4", "B4", "C4", "E4"):
        ws[c].fill, ws[c].font = HDR, HFONT
    kpis = [
        ("Total Revenue", f"=SUM({REV})", f"=SUMIFS({REV},{YEAR},$F$4)", INR),
        ("Total Cost", f"=SUM({COST})", f"=SUMIFS({COST},{YEAR},$F$4)", INR),
        ("Total Profit", "=B5-B6", "=C5-C6", INR),
        ("Profit Margin", "=IFERROR(B7/B5,0)", "=IFERROR(C7/C5,0)", PCT),
        ("Units Sold", f"=SUM({UNITS})", f"=SUMIFS({UNITS},{YEAR},$F$4)", "#,##0"),
        ("Orders (identified customers)", f'=SUM({CA("G")})', None, "#,##0"),
        ("Customers (purchasing)", f'=COUNTA({CA("A")})', None, "#,##0"),
        ("Average Order Value (identified)", f'=IFERROR(SUM({CA("H")})/B10,0)', None, INR_PLAIN),
        ("Orders per Customer", "=IFERROR(B10/B11,0)", None, "0.00"),
        ("Average Discount %", f"=IFERROR(1-SUM({REV})/SUM({GROSS}),0)", f"=IFERROR(1-C5/SUMIFS({GROSS},{YEAR},$F$4),0)", PCT),
        ("Return Rate (lines)", f"=IFERROR(SUM({RET})/SUM({LINES}),0)", f"=IFERROR(SUMIFS({RET},{YEAR},$F$4)/SUMIFS({LINES},{YEAR},$F$4),0)", PCT),
        ("Revenue YoY growth", None, f"=IFERROR(C5/SUMIFS({REV},{YEAR},$F$4-1)-1,\"n/a\")", PCT),
        ("Margin health", '=_xlfn.IFS(B8>=0.2,"Strong",B8>=0.15,"Healthy",B8>=0.1,"Watch",TRUE,"Weak")',
         '=_xlfn.IFS(C8>=0.2,"Strong",C8>=0.15,"Healthy",C8>=0.1,"Watch",TRUE,"Weak")', None),
    ]
    for i, (lab, fa, fs, nf) in enumerate(kpis, start=5):
        ws.cell(i, 1, lab).border = THIN
        for cidx, f in ((2, fa), (3, fs)):
            c = ws.cell(i, cidx, f if f else "-")
            c.border = THIN
            if nf:
                c.number_format = nf
    ws["A20"] = "Python cross-check (from pipeline headline_kpis.csv)"
    ws["A20"].font = Font(bold=True)
    checks = [("Total Revenue", k["headline"]["total_revenue"], "B5"), ("Orders (identified customers)", mart["FactSales"].loc[mart["FactSales"]["customer_key"] != -1, "order_id"].nunique(), "B10"),
              ("Customers", k["headline"]["total_customers"], "B11")]
    _hdr(ws, 21, 1, ["KPI", "Python value", "Excel value", "Match?"])
    for i, (lab, v, ref) in enumerate(checks, start=22):
        ws.cell(i, 1, lab)
        ws.cell(i, 2, float(v)).number_format = "#,##0.00"
        ws.cell(i, 3, f"={ref}").number_format = "#,##0.00"
        ws.cell(i, 4, f'=IF(ABS(B{i}-C{i})<1,"✔ Match","✖ Check")')
    ws.conditional_formatting.add("D22:D24", CellIsRule(operator="equal", formula=['"✔ Match"'], fill=PatternFill("solid", fgColor="D1FAE5")))
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 18
    ws.column_dimensions["C"].width = 18

    # ---------------- Data_Quality ----------------
    ws = wb.create_sheet("Data_Quality", 2)
    _title(ws, "Data Quality: scores, checks and cleaning log", "Status uses IFS; colours via conditional formatting.")
    sc = scores.pivot_table(index="table", columns="layer", values="dq_score").reset_index()[["table", "raw", "clean"]]
    e = _write_df(ws, sc, r0=4)
    _hdr(ws, 4, 4, ["improvement", "status"])
    for r in range(5, e + 1):
        ws.cell(r, 4, f"=C{r}-B{r}").number_format = "0.00"
        ws.cell(r, 5, f'=_xlfn.IFS(C{r}>=99.5,"Good",C{r}>=98,"Watch",TRUE,"Poor")')
    ws.cell(e + 1, 1, "Overall")
    ws.cell(e + 1, 2, f"=AVERAGE(B5:B{e})").number_format = "0.00"
    ws.cell(e + 1, 3, f"=AVERAGE(C5:C{e})").number_format = "0.00"
    ws.conditional_formatting.add(f"E5:E{e}", CellIsRule(operator="equal", formula=['"Good"'], fill=PatternFill("solid", fgColor="D1FAE5")))
    ws.conditional_formatting.add(f"E5:E{e}", CellIsRule(operator="equal", formula=['"Watch"'], fill=PatternFill("solid", fgColor="FEF3C7")))
    ws.conditional_formatting.add(f"B5:C{e}", ColorScaleRule(start_type="num", start_value=95, start_color="F87171",
                                                              mid_type="num", mid_value=99, mid_color="FDE68A", end_type="num", end_value=100, end_color="34D399"))
    iss = issues[issues["rows_affected"] > 0][["table", "issue", "how_detected", "how_fixed", "rows_affected"]]
    r0 = e + 4
    ws.cell(r0 - 1, 1, "Cleaning issue log").font = Font(bold=True)
    e2 = _write_df(ws, iss, r0=r0, widths=False)
    ws.cell(e2 + 1, 4, "Total rows fixed")
    ws.cell(e2 + 1, 5, f"=SUM(E{r0 + 1}:E{e2})")
    ws.cell(e2 + 2, 4, "Issues affecting >500 rows")
    ws.cell(e2 + 2, 5, f'=COUNTIFS(E{r0 + 1}:E{e2},">500")')
    ws.conditional_formatting.add(f"E{r0 + 1}:E{e2}", DataBarRule(start_type="num", start_value=0, end_type="max", color="F59E0B"))
    for L, w in zip("ABCDE", [18, 48, 36, 60, 14]):
        ws.column_dimensions[L].width = w
    bc = BarChart()
    bc.title = "DQ score raw vs clean"
    bc.add_data(Reference(ws, min_col=2, max_col=3, min_row=4, max_row=e), titles_from_data=True)
    bc.set_categories(Reference(ws, min_col=1, min_row=5, max_row=e))
    bc.y_axis.scaling.min = 90
    bc.height, bc.width = 7, 14
    ws.add_chart(bc, "G4")

    # ---------------- Sales_Analysis ----------------
    ws = wb.create_sheet("Sales_Analysis")
    _title(ws, "Sales Analysis: monthly trend (SUMIFS), MoM, YoY, running and rolling totals")
    _hdr(ws, 4, 1, ["Month", "Revenue", "Profit", "Margin", "MoM %", "YoY %", "Running revenue", "Rolling 3M", "Rolling 12M", "Month name", "Quarter"])
    months = sorted(agg["month_start"].unique())
    for i, mth in enumerate(months, start=5):
        ws.cell(i, 1, f"=DATE({mth.year},{mth.month},1)").number_format = "mmm-yy"
        ws.cell(i, 2, f"=SUMIFS({REV},{MONTH},A{i})").number_format = INR
        ws.cell(i, 3, f"=SUMIFS({PROF},{MONTH},A{i})").number_format = INR
        ws.cell(i, 4, f"=IFERROR(C{i}/B{i},0)").number_format = PCT
        ws.cell(i, 5, f'=IFERROR(B{i}/B{i - 1}-1,"")' if i > 5 else "").number_format = PCT
        ws.cell(i, 6, f'=IFERROR(B{i}/B{i - 12}-1,"")' if i > 16 else "").number_format = PCT
        ws.cell(i, 7, f"=SUM($B$5:B{i})").number_format = INR
        ws.cell(i, 8, f"=SUM(B{i - 2}:B{i})" if i >= 7 else "").number_format = INR
        ws.cell(i, 9, f"=SUM(B{i - 11}:B{i})" if i >= 16 else "").number_format = INR
        ws.cell(i, 10, f'=TEXT(A{i},"mmmm")')
        ws.cell(i, 11, f'="Q"&ROUNDUP(MONTH(A{i})/3,0)&"-"&YEAR(A{i})')
    last = 4 + len(months)
    ws.conditional_formatting.add(f"E6:F{last}", CellIsRule(operator="lessThan", formula=["0"], font=Font(color="DC2626")))
    ws.conditional_formatting.add(f"E6:F{last}", CellIsRule(operator="greaterThan", formula=["0"], font=Font(color="059669")))
    lc = LineChart()
    lc.title = "Monthly revenue & profit"
    lc.add_data(Reference(ws, min_col=2, max_col=3, min_row=4, max_row=last), titles_from_data=True)
    lc.set_categories(Reference(ws, min_col=1, min_row=5, max_row=last))
    lc.height, lc.width = 8, 22
    ws.add_chart(lc, "M4")
    _hdr(ws, last + 3, 1, ["Year", "Revenue", "Profit", "Margin", "YoY %"])
    for j, yv in enumerate([2023, 2024, 2025]):
        r = last + 4 + j
        ws.cell(r, 1, yv)
        ws.cell(r, 2, f"=SUMIFS({REV},{YEAR},A{r})").number_format = INR
        ws.cell(r, 3, f"=SUMIFS({PROF},{YEAR},A{r})").number_format = INR
        ws.cell(r, 4, f"=IFERROR(C{r}/B{r},0)").number_format = PCT
        ws.cell(r, 5, f'=IFERROR(B{r}/B{r - 1}-1,"")' if j else "").number_format = PCT
    for L in "ABCDEFGHIJK":
        ws.column_dimensions[L].width = 15

    # ---------------- Product_Analysis ----------------
    p = k["product"][["product_id", "product_name", "category", "revenue", "profit", "units", "lines", "returned_lines"]]
    p = p[p["product_id"] != "P_UNKNOWN"]
    ws = wb.create_sheet("Product_Analysis")
    _title(ws, "Product Analysis: margin, return rate, rank and tier (formulas)")
    pend = _write_df(ws, p, table="tblProducts")
    _hdr(ws, 4, 9, ["margin", "return_rate", "revenue_rank", "tier", "cum_share"])
    for r in range(5, pend + 1):
        ws.cell(r, 4).number_format = INR_PLAIN
        ws.cell(r, 5).number_format = INR_PLAIN
        ws.cell(r, 9, f"=IFERROR(E{r}/D{r},0)").number_format = PCT
        ws.cell(r, 10, f"=IFERROR(H{r}/G{r},0)").number_format = PCT
        ws.cell(r, 11, f"=_xlfn.RANK.EQ(D{r},$D$5:$D${pend},0)")
        ws.cell(r, 12, f'=_xlfn.IFS(K{r}<=20,"Top 20",K{r}>{pend - 4 - 20},"Bottom 20",TRUE,"Core")')
        ws.cell(r, 13, f"=SUM($D$5:D{r})/SUM($D$5:$D${pend})").number_format = PCT
    ws.conditional_formatting.add(f"I5:I{pend}", ColorScaleRule(start_type="min", start_color="F87171", mid_type="percentile",
                                                                  mid_value=50, mid_color="FDE68A", end_type="max", end_color="34D399"))
    ws.conditional_formatting.add(f"D5:D{pend}", DataBarRule(start_type="num", start_value=0, end_type="max", color="2563EB"))
    ws.conditional_formatting.add(f"J5:J{pend}", CellIsRule(operator="greaterThan", formula=["0.12"], fill=PatternFill("solid", fgColor="FDE2E2")))
    ws["O4"], ws["P4"] = "Pareto check", "Value"
    ws["O5"], ws["P5"] = "Products for 80% of revenue", f'=COUNTIFS(M5:M{pend},"<=0.8")'
    ws["O6"], ws["P6"] = "Share of catalogue", f"=P5/COUNTA(A5:A{pend})"
    ws["P6"].number_format = PCT
    ws["O7"], ws["P7"] = "Loss-making products", f'=COUNTIFS(E5:E{pend},"<0")'
    for c in ("O4", "P4"):
        ws[c].fill, ws[c].font = HDR, HFONT
    ws.column_dimensions["O"].width = 28
    ws.freeze_panes = "A5"

    # ---------------- Regional_Analysis ----------------
    ws = wb.create_sheet("Regional_Analysis")
    _title(ws, "Regional & Channel Analysis (SUMIFS over Cleaned_Data)")
    zones = ["North", "South", "East", "West", "Central"]
    _hdr(ws, 4, 1, ["Region", "Revenue", "Profit", "Margin", "Revenue share", "Return rate", "Performance"])
    for i, z in enumerate(zones, start=5):
        ws.cell(i, 1, z)
        ws.cell(i, 2, f"=SUMIFS({REV},{REG},A{i})").number_format = INR
        ws.cell(i, 3, f"=SUMIFS({PROF},{REG},A{i})").number_format = INR
        ws.cell(i, 4, f"=IFERROR(C{i}/B{i},0)").number_format = PCT
        ws.cell(i, 5, f"=IFERROR(B{i}/SUM($B$5:$B$9),0)").number_format = PCT
        ws.cell(i, 6, f"=IFERROR(SUMIFS({RET},{REG},A{i})/SUMIFS({LINES},{REG},A{i}),0)").number_format = PCT
        ws.cell(i, 7, f'=IF(E{i}>=0.25,"Leader",IF(E{i}>=0.15,"Core","Growth market"))')
    chs = ["Website", "Mobile App", "Marketplace", "Retail Store", "Unknown"]
    _hdr(ws, 12, 1, ["Channel", "Revenue", "Profit", "Margin", "Revenue share", "Return rate", "Avg discount"])
    for i, c_ in enumerate(chs, start=13):
        ws.cell(i, 1, c_)
        ws.cell(i, 2, f"=SUMIFS({REV},{CHN},A{i})").number_format = INR
        ws.cell(i, 3, f"=SUMIFS({PROF},{CHN},A{i})").number_format = INR
        ws.cell(i, 4, f"=IFERROR(C{i}/B{i},0)").number_format = PCT
        ws.cell(i, 5, f"=IFERROR(B{i}/SUM($B$13:$B$17),0)").number_format = PCT
        ws.cell(i, 6, f"=IFERROR(SUMIFS({RET},{CHN},A{i})/SUMIFS({LINES},{CHN},A{i}),0)").number_format = PCT
        ws.cell(i, 7, f"=IFERROR(1-B{i}/SUMIFS({GROSS},{CHN},A{i}),0)").number_format = PCT
    ws.conditional_formatting.add("F5:F9", ColorScaleRule(start_type="min", start_color="34D399", end_type="max", end_color="F87171"))
    ws.conditional_formatting.add("F13:F17", ColorScaleRule(start_type="min", start_color="34D399", end_type="max", end_color="F87171"))
    bc = BarChart()
    bc.title = "Revenue by region"
    bc.add_data(Reference(ws, min_col=2, min_row=4, max_row=9), titles_from_data=True)
    bc.set_categories(Reference(ws, min_col=1, min_row=5, max_row=9))
    bc.height, bc.width = 7, 13
    ws.add_chart(bc, "I4")
    for L in "ABCDEFG":
        ws.column_dimensions[L].width = 16

    # ---------------- Returns_Analysis ----------------
    fr = (mart["FactReturns"].merge(mart["DimProduct"][["product_key", "category"]], on="product_key")
          .merge(mart["DimRegion"][["region_key", "region_name"]], on="region_key", how="left")
          .merge(mart["DimChannel"][["channel_key", "channel_name"]], on="channel_key")
          .merge(mart["DimDate"][["date_key", "date"]], left_on="order_date_key", right_on="date_key"))
    fr = fr[["return_id", "order_id", "date", "category", "region_name", "channel_name", "return_reason", "return_qty", "refund_amount"]]
    fr = fr.rename(columns={"date": "order_date"})
    fr["order_date"] = pd.to_datetime(fr["order_date"]).dt.date
    ws = wb.create_sheet("Returns_Analysis")
    _title(ws, "Returns Analysis: COUNTIFS / SUMIFS over the returns register")
    rend = _write_df(ws, fr, table="tblReturns")
    RR = lambda L: f"Returns_Analysis!${L}$5:${L}${rend}"  # noqa: E731
    reasons = k["return_reasons"]["return_reason"].tolist()
    _hdr(ws, 4, 11, ["Return reason", "Returns", "Refund value", "Share"])
    for i, rs in enumerate(reasons, start=5):
        ws.cell(i, 11, rs)
        ws.cell(i, 12, f'=COUNTIFS({RR("G")},K{i})')
        ws.cell(i, 13, f'=SUMIFS({RR("I")},{RR("G")},K{i})').number_format = INR
        ws.cell(i, 14, f"=IFERROR(L{i}/SUM($L$5:$L${4 + len(reasons)}),0)").number_format = PCT
    cats = [c for c in k["category"]["category"] if c != "Unknown"]
    r0 = 7 + len(reasons)
    _hdr(ws, r0, 11, ["Category", "Returns", "Sold lines", "Return rate", "Flag"])
    for i, ct in enumerate(cats, start=r0 + 1):
        ws.cell(i, 11, ct)
        ws.cell(i, 12, f'=COUNTIFS({RR("D")},K{i})')
        ws.cell(i, 13, f"=SUMIFS({LINES},{CAT},K{i})")
        ws.cell(i, 14, f"=IFERROR(L{i}/M{i},0)").number_format = PCT
        ws.cell(i, 15, f'=IF(N{i}>0.1,"High - investigate","OK")')
    ws.conditional_formatting.add(f"O{r0 + 1}:O{r0 + len(cats)}", CellIsRule(operator="equal", formula=['"High - investigate"'],
                                                                               fill=PatternFill("solid", fgColor="FDE2E2")))
    bc = BarChart()
    bc.type = "bar"
    bc.title = "Returns by reason"
    bc.add_data(Reference(ws, min_col=12, min_row=4, max_row=4 + len(reasons)), titles_from_data=True)
    bc.set_categories(Reference(ws, min_col=11, min_row=5, max_row=4 + len(reasons)))
    bc.height, bc.width = 7, 13
    ws.add_chart(bc, "Q4")
    ws.column_dimensions["K"].width = 24

    # ---------------- Pivot_Analysis ----------------
    ws = wb.create_sheet("Pivot_Analysis")
    _title(ws, "Pivot Analysis: formula cross-tabs + pivot-style chart",
           "Native PivotTable: Insert > PivotTable > Table 'tblSales' (Cleaned_Data). Rows=category, Columns=year, Values=Sum of revenue. See excel/README.md")
    years = [2023, 2024, 2025]
    _hdr(ws, 4, 1, ["Category"] + [str(y) for y in years] + ["Total", "CAGR 23-25"])
    for i, ct in enumerate(cats, start=5):
        ws.cell(i, 1, ct)
        for j, yv in enumerate(years, start=2):
            ws.cell(i, j, f"=SUMIFS({REV},{CAT},$A{i},{YEAR},{yv})").number_format = INR
        ws.cell(i, 5, f"=SUM(B{i}:D{i})").number_format = INR
        ws.cell(i, 6, f'=IFERROR((D{i}/B{i})^(1/2)-1,"")').number_format = PCT
    pl = 4 + len(cats)
    ws.cell(pl + 1, 1, "Grand Total").font = Font(bold=True)
    for j in range(2, 6):
        L = get_column_letter(j)
        ws.cell(pl + 1, j, f"=SUM({L}5:{L}{pl})").number_format = INR
    ws.conditional_formatting.add(f"B5:D{pl}", ColorScaleRule(start_type="min", start_color="FFFFFF", end_type="max", end_color="60A5FA"))
    r0 = pl + 4
    _hdr(ws, r0, 1, ["Region \\ Channel"] + chs[:4])
    for i, z in enumerate(zones, start=r0 + 1):
        ws.cell(i, 1, z)
        for j, c_ in enumerate(chs[:4], start=2):
            ws.cell(i, j, f'=SUMIFS({REV},{REG},$A{i},{CHN},"{c_}")').number_format = INR
    ws.conditional_formatting.add(f"B{r0 + 1}:E{r0 + 5}", ColorScaleRule(start_type="min", start_color="FFFFFF", end_type="max", end_color="F59E0B"))
    bc = BarChart()
    bc.title = "Revenue by category and year"
    bc.add_data(Reference(ws, min_col=2, max_col=4, min_row=4, max_row=pl), titles_from_data=True)
    bc.set_categories(Reference(ws, min_col=1, min_row=5, max_row=pl))
    bc.height, bc.width = 8, 16
    ws.add_chart(bc, "H4")
    ws.column_dimensions["A"].width = 18
    for L in "BCDEF":
        ws.column_dimensions[L].width = 15

    # ---------------- Executive_Report ----------------
    ws = wb.create_sheet("Executive_Report", 0)
    _title(ws, "UrbanCart Retail: Executive Report (SYNTHETIC DATA)",
           "All numbers are formulas linked to the analysis sheets. Change the year on KPI_Summary!F4 to refresh the year column.")
    cards = [("Total Revenue", "=KPI_Summary!B5", INR), ("Total Profit", "=KPI_Summary!B7", INR),
             ("Profit Margin", "=KPI_Summary!B8", PCT), ("Orders", "=KPI_Summary!B10", "#,##0"),
             ("Customers", "=KPI_Summary!B11", "#,##0"), ("Avg Order Value", "=KPI_Summary!B12", INR_PLAIN),
             ("Return Rate", "=KPI_Summary!B15", PCT), ("Repeat Customers", "=Customer_Analysis!S23", PCT)]
    for i, (lab, f, nf) in enumerate(cards):
        col_ = 1 + (i % 4) * 2
        row = 4 + (i // 4) * 3
        a = ws.cell(row, col_, lab)
        a.font, a.fill = Font(bold=True, color="1F3A5F"), CARD
        v = ws.cell(row + 1, col_, f)
        v.font, v.fill, v.number_format = Font(size=16, bold=True), CARD, nf
    ws["A11"] = "Selected-year view"
    ws["A11"].font = Font(bold=True)
    ws["A12"], ws["B12"] = "Year", "=KPI_Summary!F4"
    ws["A13"], ws["B13"] = "Revenue", "=KPI_Summary!C5"
    ws["A14"], ws["B14"] = "YoY growth", "=KPI_Summary!C16"
    ws["A15"], ws["B15"] = "Margin health", "=KPI_Summary!C17"
    ws["B13"].number_format = INR
    ws["B14"].number_format = PCT
    ws["A17"] = "Top region"
    ws["B17"] = "=INDEX(Regional_Analysis!A5:A9,MATCH(MAX(Regional_Analysis!B5:B9),Regional_Analysis!B5:B9,0))"
    ws["A18"] = "Top category"
    ws["B18"] = f"=INDEX(Pivot_Analysis!A5:A{pl},MATCH(MAX(Pivot_Analysis!E5:E{pl}),Pivot_Analysis!E5:E{pl},0))"
    ws["A19"] = "Top return reason"
    ws["B19"] = f"=INDEX(Returns_Analysis!K5:K{4 + len(reasons)},MATCH(MAX(Returns_Analysis!L5:L{4 + len(reasons)}),Returns_Analysis!L5:L{4 + len(reasons)},0))"
    for L in "ABCDEFGH":
        ws.column_dimensions[L].width = 18
    sa = wb["Sales_Analysis"]
    lc = LineChart()
    lc.title = "Monthly revenue trend"
    lc.add_data(Reference(sa, min_col=2, min_row=4, max_row=last), titles_from_data=True)
    lc.set_categories(Reference(sa, min_col=1, min_row=5, max_row=last))
    lc.height, lc.width = 7.5, 18
    ws.add_chart(lc, "A22")
    pa = wb["Pivot_Analysis"]
    bc = BarChart()
    bc.type = "bar"
    bc.title = "Revenue by category (3 years)"
    bc.add_data(Reference(pa, min_col=5, min_row=4, max_row=pl), titles_from_data=True)
    bc.set_categories(Reference(pa, min_col=1, min_row=5, max_row=pl))
    bc.height, bc.width = 7.5, 14
    ws.add_chart(bc, "J4")

    order = ["Executive_Report", "Raw_Data", "Cleaned_Data", "Data_Quality", "KPI_Summary", "Sales_Analysis",
             "Customer_Analysis", "Product_Analysis", "Regional_Analysis", "Returns_Analysis", "Pivot_Analysis"]
    wb._sheets = [wb[n] for n in order]
    path = EXCEL_DIR / "analytics_dashboard.xlsx"
    wb.save(path)
    log.info("Wrote Excel workbook %s (%d sheets)", path, len(order))
    return str(path)
