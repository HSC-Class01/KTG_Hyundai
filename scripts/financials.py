"""재무제표 계정 매칭 · 기간 정리 · 재무비율 계산.

OpenDART 응답(JSON)과 공시 원문에서 뽑은 숫자를 같은 모양으로 맞춥니다.
네트워크를 쓰지 않는 순수 함수만 있어서 테스트하기 쉽습니다. (표준 라이브러리만 사용)

기간 모델
- 보고서 기간(report period): (연도, 월) 월은 3·6·9·12. 손익·현금흐름은 그 해 1월부터의 누적값,
  재무상태표는 그 달 말 잔액입니다. (1분기=3개월, 반기=6개월, 3분기=9개월, 사업보고서=12개월)
- 개별 분기: Q1=3개월, Q2=반기−1분기, Q3=3분기누적−반기, Q4=연간−3분기누적
- 반기: H1=반기보고서, H2=연간−반기
"""
from datetime import date

REPORT_CODES = {3: "11013", 6: "11012", 9: "11014", 12: "11011"}
CODE_MONTH = {v: k for k, v in REPORT_CODES.items()}
REPORT_NAMES = {3: "1분기보고서", 6: "반기보고서", 9: "3분기보고서", 12: "사업보고서"}

# (재무제표 구분, 표준계정코드 후보, 한글 계정명 후보)
# 표준코드를 먼저 찾고, 없으면 띄어쓰기를 무시한 한글 계정명으로 찾습니다.
# 재무상태표 일부 계정은 연도마다 코드가 바뀌거나 다른 계정에 재사용되어 이름으로만 찾습니다.
FIELDS = {
    "revenue": (("IS", "CIS"), ("ifrs-full_Revenue", "ifrs_Revenue", "ifrs-full_RevenueFromContractsWithCustomers",
                                "ifrs_RevenueFromContractsWithCustomers"), ("매출액", "수익(매출액)", "매출", "영업수익")),
    "cost_of_sales": (("IS", "CIS"), ("ifrs-full_CostOfSales", "ifrs_CostOfSales"), ("매출원가",)),
    "gross_profit": (("IS", "CIS"), ("ifrs-full_GrossProfit", "ifrs_GrossProfit"), ("매출총이익", "매출총이익(손실)")),
    "sga": (("IS", "CIS"), ("dart_TotalSellingGeneralAdministrativeExpenses", "ifrs-full_SellingGeneralAndAdministrativeExpense",
                            "ifrs_SellingGeneralAndAdministrativeExpense"), ("판매비와관리비",)),
    "operating_profit": (("IS", "CIS"), ("dart_OperatingIncomeLoss",), ("영업이익", "영업이익(손실)", "영업손익")),
    "net_income": (("IS", "CIS"), ("ifrs-full_ProfitLoss", "ifrs_ProfitLoss"), ("당기순이익", "당기순이익(손실)", "연결당기순이익",
                                                                                "분기순이익", "분기순이익(손실)", "반기순이익", "반기순이익(손실)")),
    "net_income_owners": (("IS", "CIS"), ("ifrs-full_ProfitLossAttributableToOwnersOfParent",
                                          "ifrs_ProfitLossAttributableToOwnersOfParent"), ()),
    "net_income_nci": (("IS", "CIS"), ("ifrs-full_ProfitLossAttributableToNoncontrollingInterests",
                                       "ifrs_ProfitLossAttributableToNoncontrollingInterests"), ()),
    "assets": (("BS",), ("ifrs-full_Assets", "ifrs_Assets"), ("자산총계",)),
    "liabilities": (("BS",), ("ifrs-full_Liabilities", "ifrs_Liabilities"), ("부채총계",)),
    "equity": (("BS",), ("ifrs-full_Equity", "ifrs_Equity"), ("자본총계",)),
    "current_assets": (("BS",), ("ifrs-full_CurrentAssets", "ifrs_CurrentAssets"), ("유동자산",)),
    "current_liabilities": (("BS",), ("ifrs-full_CurrentLiabilities", "ifrs_CurrentLiabilities"), ("유동부채",)),
    "cash": (("BS",), (), ("현금및현금성자산",)),
    "short_term_deposits": (("BS",), (), ("단기금융상품",)),
    "trade_receivables": (("BS",), (), ("매출채권",)),
    "contract_assets": (("BS",), (), ("미청구공사", "단기미청구공사")),
    "contract_liabilities": (("BS",), (), ("초과청구공사",)),
    "customer_advances": (("BS",), (), ("공사및분양선수금",)),
    "short_term_borrowings": (("BS",), (), ("단기차입금",)),
    "current_portion_ltd": (("BS",), (), ("유동성장기부채",)),
    "bonds": (("BS",), (), ("사채", "비유동성사채")),
    "long_term_borrowings": (("BS",), (), ("장기차입금",)),
    "operating_cashflow": (("CF",), ("ifrs-full_CashFlowsFromUsedInOperatingActivities", "ifrs_CashFlowsFromUsedInOperatingActivities"),
                           ("영업활동현금흐름", "영업활동으로인한현금흐름")),
    "investing_cashflow": (("CF",), ("ifrs-full_CashFlowsFromUsedInInvestingActivities", "ifrs_CashFlowsFromUsedInInvestingActivities"),
                           ("투자활동현금흐름", "투자활동으로인한현금흐름")),
    "financing_cashflow": (("CF",), ("ifrs-full_CashFlowsFromUsedInFinancingActivities", "ifrs_CashFlowsFromUsedInFinancingActivities"),
                           ("재무활동현금흐름", "재무활동으로인한현금흐름")),
}
LABELS = {
    "revenue": "매출액", "cost_of_sales": "매출원가", "gross_profit": "매출총이익", "sga": "판매비와관리비",
    "operating_profit": "영업이익", "net_income": "당기순이익", "net_income_owners": "지배주주 순이익",
    "net_income_nci": "비지배지분 순이익", "assets": "자산총계", "liabilities": "부채총계", "equity": "자본총계",
    "current_assets": "유동자산", "current_liabilities": "유동부채", "cash": "현금및현금성자산",
    "short_term_deposits": "단기금융상품", "trade_receivables": "매출채권", "contract_assets": "미청구공사",
    "contract_liabilities": "초과청구공사", "customer_advances": "공사및분양선수금", "short_term_borrowings": "단기차입금",
    "current_portion_ltd": "유동성장기부채", "bonds": "사채", "long_term_borrowings": "장기차입금",
    "operating_cashflow": "영업활동현금흐름", "investing_cashflow": "투자활동현금흐름", "financing_cashflow": "재무활동현금흐름",
}
IS_FIELDS = [k for k, v in FIELDS.items() if "IS" in v[0] or "CIS" in v[0]]
CF_FIELDS = [k for k, v in FIELDS.items() if v[0] == ("CF",)]
BS_FIELDS = [k for k, v in FIELDS.items() if v[0] == ("BS",)]
FLOW_FIELDS = IS_FIELDS + CF_FIELDS
# 여러 계정을 더해 만드는 값 (하나라도 없으면 비워 둡니다)
DERIVED = {
    "receivables_total": ("trade_receivables", "contract_assets"),
    "cash_and_deposits": ("cash", "short_term_deposits"),
    "borrowings_total": ("short_term_borrowings", "current_portion_ltd", "bonds", "long_term_borrowings"),
    "advances_total": ("contract_liabilities", "customer_advances"),
}
RATIO_LABELS = {
    "revenue_growth_pct": "매출증가율(%)", "qoq_growth_pct": "직전 분기 대비(%)",
    "gross_margin_pct": "매출총이익률(%)", "cost_ratio_pct": "원가율(%)", "sga_ratio_pct": "판관비율(%)",
    "operating_margin_pct": "영업이익률(%)", "net_margin_pct": "순이익률(%)",
    "debt_to_equity_pct": "부채비율(%)", "current_ratio_pct": "유동비율(%)", "equity_ratio_pct": "자기자본비율(%)",
    "roa_pct": "ROA(%)", "roe_pct": "ROE(%)", "receivables_to_revenue_pct": "받을 돈/매출(%)",
}


# ---------------------------------------------------------------------------
# 숫자·계정 매칭
# ---------------------------------------------------------------------------
def amount(value):
    """'1,234' '(1,234)' '-' 같은 표기를 정수(원)로 바꿉니다. 비어 있으면 None."""
    s = str(value if value is not None else "").replace(",", "").replace(" ", "").strip()
    if not s or s in ("-", "null", "None", "—"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return int(s)
    except ValueError:
        try:
            return int(round(float(s)))
        except ValueError:
            return None


def norm(name):
    return "".join(str(name or "").split())


def pick(records, field, column="thstrm_amount"):
    """계정 하나를 고릅니다. 반환: (금액, (계정코드, 계정명), 문제 설명)."""
    statements, account_ids, names = FIELDS[field]
    wanted = {norm(n) for n in names}
    choices = []
    for r in records:
        if r.get("sj_div") not in statements:
            continue
        if str(r.get("account_detail", "-")).strip() not in ("", "-"):
            continue
        if str(r.get("currency", "KRW")) not in ("", "KRW"):
            continue
        value = amount(r.get(column))
        if value is not None:
            choices.append((r, value))
    for account_id in account_ids:
        matches = [(r, v) for r, v in choices if r.get("account_id") == account_id]
        values = {v for _, v in matches}
        if len(values) == 1:
            r, v = matches[0]
            return v, (r.get("account_id", ""), r.get("account_nm", "")), ""
        if len(values) > 1:
            return None, ("", ""), f"{LABELS[field]}: 표준계정코드 후보 금액 충돌"
    matches = [(r, v) for r, v in choices if norm(r.get("account_nm")) in wanted]
    values = {v for _, v in matches}
    if len(values) == 1:
        r, v = matches[0]
        return v, (r.get("account_id", ""), r.get("account_nm", "")), ""
    if len(values) > 1:
        return None, ("", ""), f"{LABELS[field]}: 계정명 후보 금액 충돌"
    return None, ("", ""), f"{LABELS[field]}: 계정 미확인"


def _columns(field, month, which):
    """필드·보고서 종류·당기/비교기에 따라 읽을 금액 열 목록(앞에서부터 시도)."""
    is_flow = field in IS_FIELDS
    is_cf = field in CF_FIELDS
    if which == "current":
        if is_flow and month != 12:
            # 분·반기 손익: thstrm_amount는 3개월, thstrm_add_amount가 누적. 1분기는 둘이 같습니다.
            return ["thstrm_add_amount"] + (["thstrm_amount"] if month == 3 else [])
        return ["thstrm_amount"]
    if which == "prior":   # 전년 같은 기간 (손익·현금흐름). 재무상태표는 전기말이라 분·반기에서는 쓰지 않습니다.
        if month == 12:
            return ["frmtrm_amount"]
        if is_flow:
            return ["frmtrm_add_amount", "frmtrm_amount"] + (["frmtrm_q_amount"] if month == 3 else [])
        if is_cf:
            return ["frmtrm_q_amount", "frmtrm_amount"]
        return []
    if which == "prior2":  # 전전기 (사업보고서만)
        return ["bfefrmtrm_amount"] if month == 12 else []
    return []


def extract(records, month, which="current"):
    """API 응답 목록에서 모든 필드를 뽑습니다. 반환: {'values':{}, 'evidence':{}, 'issues':[]}"""
    out = {"values": {}, "evidence": {}, "issues": []}
    for field in FIELDS:
        value, evidence, issue = None, ("", ""), f"{LABELS[field]}: 계정 미확인"
        cols = _columns(field, month, which)
        used = ""
        for col in cols:
            value, evidence, issue = pick(records, field, col)
            if value is not None or "충돌" in issue:
                used = col
                break
        if not cols:
            continue
        out["values"][field] = value
        if value is not None:
            out["evidence"][field] = {"account_id": evidence[0], "account_name": evidence[1], "column": used}
        elif which == "current" and field not in ("net_income_owners", "net_income_nci"):
            out["issues"].append(issue)
    return out


# ---------------------------------------------------------------------------
# 기간 정리
# ---------------------------------------------------------------------------
def blank_period(year, month):
    return {"year": year, "month": month, "values": {}, "sources": {}, "receipt": "", "report_name": "",
            "filed": "", "warnings": []}


def merge(period, values, source, overwrite=False):
    """비어 있는 칸만 채웁니다(overwrite=True면 덮어씀). source: 'api' | 'api-prior' | 'document'."""
    for field, value in values.items():
        if value is None:
            continue
        if overwrite or period["values"].get(field) is None:
            period["values"][field] = value
            period["sources"][field] = source


def add_derived(values):
    out = dict(values)
    for name, parts in DERIVED.items():
        parts_v = [values.get(p) for p in parts]
        out[name] = None if any(v is None for v in parts_v) else sum(parts_v)
    if out.get("cash_and_deposits") is not None and out.get("borrowings_total") is not None:
        out["net_cash"] = out["cash_and_deposits"] - out["borrowings_total"]
    else:
        out["net_cash"] = None
    return out


def ratio(n, d):
    if n is None or d is None or d <= 0:
        return None
    return n / d * 100


def growth(now, before):
    if now is None or before is None or before <= 0:
        return None
    return (now - before) / before * 100


def balance_gap(values):
    a, l, e = values.get("assets"), values.get("liabilities"), values.get("equity")
    if None in (a, l, e):
        return None
    return a - l - e


def _sub(a, b):
    return None if a is None or b is None else a - b


def build_tables(periods):
    """보고서 기간 사전({(연,월): period})으로 연간·반기·분기 행을 만듭니다."""
    years = sorted({y for y, _ in periods})
    annual, halves, quarters = [], [], []

    def vals(y, m):
        p = periods.get((y, m))
        return p["values"] if p else {}

    def meta(y, m):
        p = periods.get((y, m))
        return p or blank_period(y, m)

    def amended_note(*keys):
        """차감 계산에 쓴 두 보고서 중 정정 공시가 있으면 알려 줍니다."""
        names = [meta(*k).get("report_name", "") for k in keys]
        if any("정정" in n for n in names):
            return ["차감에 쓴 보고서 중 정정 공시가 있어, 정정 효과가 이 기간 숫자에 섞였을 수 있음"]
        return []

    for y in years:
        fy, h1, m9, q1 = vals(y, 12), vals(y, 6), vals(y, 9), vals(y, 3)
        if fy:
            annual.append(_row(f"{y}", y, 12, "annual", fy, meta(y, 12), derived=False))
        if h1:
            halves.append(_row(f"{y} 상반기", y, 6, "H1", h1, meta(y, 6), derived=False))
        if fy and h1:
            h2 = {f: (_sub(fy.get(f), h1.get(f)) if f in FLOW_FIELDS else fy.get(f)) for f in FIELDS}
            if any(h2.get(f) is not None for f in FLOW_FIELDS):
                halves.append(_row(f"{y} 하반기", y, 12, "H2", h2, meta(y, 12), derived=True,
                                   notes=amended_note((y, 12), (y, 6))))
        steps = [(3, q1, None), (6, h1, q1), (9, m9, h1), (12, fy, m9)]
        for q, (m, cur, prev) in enumerate(steps, 1):
            if not cur:
                continue
            if q == 1:
                qv = dict(cur)
            elif prev:
                qv = {f: (_sub(cur.get(f), prev.get(f)) if f in FLOW_FIELDS else cur.get(f)) for f in FIELDS}
            else:
                continue   # 앞 누적 기간이 없으면 개별 분기 실적을 계산할 수 없습니다
            if not any(qv.get(f) is not None for f in FLOW_FIELDS):
                continue
            notes = amended_note((y, m), (y, m - 3)) if q > 1 else []
            quarters.append(_row(f"{y} {q}분기", y, m, f"Q{q}", qv, meta(y, m), derived=q > 1, notes=notes))
    _ratios(annual, "annual")
    _ratios(halves, "half")
    _ratios(quarters, "quarter")
    return annual, halves, quarters


def _row(label, year, month, kind, values, period, derived, notes=()):
    v = add_derived(values)
    sources = sorted({period["sources"].get(f) for f in values if period["sources"].get(f)})
    return {"label": label, "year": year, "month": month, "kind": kind, "values": v, "derived": derived,
            "receipt": period.get("receipt", ""), "report_name": period.get("report_name", ""),
            "filed": period.get("filed", ""), "sources": sources,
            "warnings": list(period.get("warnings", [])) + list(notes), "ratios": {}}


def _ratios(rows, kind):
    index = {(r["year"], r["kind"]): r for r in rows}
    prev_row = None
    for r in rows:
        v = r["values"]
        same_last_year = index.get((r["year"] - 1, r["kind"]))
        pv = same_last_year["values"] if same_last_year else {}
        rev = v.get("revenue")
        ratios = {
            "revenue_growth_pct": growth(rev, pv.get("revenue")),
            "gross_margin_pct": ratio(v.get("gross_profit"), rev),
            "cost_ratio_pct": ratio(v.get("cost_of_sales"), rev),
            "sga_ratio_pct": ratio(v.get("sga"), rev),
            "operating_margin_pct": ratio(v.get("operating_profit"), rev),
            "net_margin_pct": ratio(v.get("net_income"), rev),
            "debt_to_equity_pct": ratio(v.get("liabilities"), v.get("equity")),
            "current_ratio_pct": ratio(v.get("current_assets"), v.get("current_liabilities")),
            "equity_ratio_pct": ratio(v.get("equity"), v.get("assets")),
            "receivables_to_revenue_pct": ratio(v.get("receivables_total"), rev) if kind == "annual" else None,
            "roa_pct": None, "roe_pct": None, "qoq_growth_pct": None,
        }
        if kind == "annual" and same_last_year:
            avg_a = _avg(v.get("assets"), pv.get("assets"))
            avg_e = _avg(v.get("equity"), pv.get("equity"))
            ratios["roa_pct"] = ratio(v.get("net_income"), avg_a)
            ratios["roe_pct"] = ratio(v.get("net_income"), avg_e)
        if kind == "quarter" and prev_row is not None and _next_quarter(prev_row) == (r["year"], r["kind"]):
            ratios["qoq_growth_pct"] = growth(rev, prev_row["values"].get("revenue"))
        r["ratios"] = ratios
        prev_row = r


def _avg(a, b):
    return None if a is None or b is None else (a + b) / 2


def _next_quarter(row):
    q = int(row["kind"][1])
    return (row["year"], f"Q{q + 1}") if q < 4 else (row["year"] + 1, "Q1")


def ttm(quarters, field):
    """최근 4개 분기 합계(연속된 4개 분기가 모두 있을 때만)."""
    if len(quarters) < 4:
        return None, None
    last4 = quarters[-4:]
    for a, b in zip(last4, last4[1:]):
        if _next_quarter(a) != (b["year"], b["kind"]):
            return None, None
    vals = [q["values"].get(field) for q in last4]
    if any(v is None for v in vals):
        return None, last4
    return sum(vals), last4


def period_label(year, month):
    return {3: f"{year}년 1분기", 6: f"{year}년 상반기", 9: f"{year}년 3분기 누적", 12: f"{year}년"}[month]


def next_run_date(today):
    """다음 정기 실행일(매월 1일)."""
    y, m = (today.year + (today.month == 12), 1 if today.month == 12 else today.month + 1)
    return date(y, m, 1)
