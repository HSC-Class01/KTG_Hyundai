"""재무비율 10가지 관점(수익성·안정성·유동성·활동성·성장성·생산성·현금흐름·시장가치·종합 분석·주가 반영).

대시보드(요약 카드)와 '재무제표 10년' 화면(자세한 차트)이 같은 정의를 씁니다.
- 기본은 연결재무제표 연간 숫자입니다. 생산성만 사업보고서 직원 현황과 별도(현대건설 단독) 실적을 씁니다
  (직원 수가 현대건설 단독 기준이라 분자도 단독 숫자로 맞춥니다).
- 판정은 절대 기준이 아니라 '최근 10년 안에서 지금이 어디쯤인가'입니다. 방향(높을수록 좋음/낮을수록 좋음)이
  정해진 지표만 판정하고, 나머지(PER처럼 해석이 갈리는 지표)는 '참고'로 둡니다.
"""
import financials as fin

WINDOW = 10
T = 1_000_000_000_000
EOK = 100_000_000
MIL = 1_000_000

# (키, 이름, 단위, 방향 +1 높을수록 좋음 / -1 낮을수록 좋음 / 0 판정 안 함, 설명)
LENSES = [
    {"id": "profitability", "no": 1, "ko": "수익성", "en": "Profitability", "q": "판 만큼 남기는가",
     "read": "건설사는 매출원가가 매출의 90% 안팎이라 영업이익률 1%p 차이가 큰 차이입니다. 원가율이 오르면 저가 수주나 공사비 상승을 의심합니다.",
     "metrics": [("operating_margin_pct", "영업이익률", "%", 1, "영업이익 ÷ 매출액"),
                 ("gross_margin_pct", "매출총이익률", "%", 1, "(매출액 − 매출원가) ÷ 매출액"),
                 ("net_margin_pct", "순이익률", "%", 1, "당기순이익 ÷ 매출액"),
                 ("roe_pct", "ROE", "%", 1, "당기순이익 ÷ 평균 자본총계"),
                 ("roa_pct", "ROA", "%", 1, "당기순이익 ÷ 평균 자산총계")]},
    {"id": "stability", "no": 2, "ko": "안정성", "en": "Stability", "q": "빚을 감당할 수 있는가",
     "read": "건설사 부채에는 선수금·초과청구공사처럼 돈 대신 공사로 갚는 부채가 많아 부채비율만 보면 부풀려 보입니다. 이자가 붙는 차입금과 이자보상배율을 같이 봅니다.",
     "metrics": [("debt_to_equity_pct", "부채비율", "%", -1, "부채총계 ÷ 자본총계"),
                 ("borrowing_dependency_pct", "차입금의존도", "%", -1, "이자부차입금 ÷ 자산총계"),
                 ("equity_ratio_pct", "자기자본비율", "%", 1, "자본총계 ÷ 자산총계"),
                 ("interest_coverage_x", "이자보상배율", "배", 1, "영업이익 ÷ 이자비용"),
                 ("net_debt_to_ebitda_x", "순차입금/EBITDA", "배", -1, "(차입금 − 현금) ÷ EBITDA · 마이너스면 차입금보다 현금이 많음(순현금)")]},
    {"id": "liquidity", "no": 3, "ko": "유동성", "en": "Liquidity", "q": "1년 안에 갚을 돈을 낼 수 있는가",
     "read": "유동비율이 100%를 넘으면 1년 안에 갚을 빚보다 1년 안에 돈이 될 자산이 많다는 뜻입니다. 건설사 유동자산에는 미청구공사가 많아 현금비율도 함께 봅니다.",
     "metrics": [("current_ratio_pct", "유동비율", "%", 1, "유동자산 ÷ 유동부채"),
                 ("quick_ratio_pct", "당좌비율", "%", 1, "(유동자산 − 재고자산) ÷ 유동부채"),
                 ("cash_ratio_pct", "현금비율", "%", 1, "(현금 + 단기금융상품) ÷ 유동부채")]},
    {"id": "activity", "no": 4, "ko": "활동성", "en": "Activity", "q": "자산을 얼마나 빨리 돌리고 돈을 받는가",
     "read": "건설사는 공사를 하고도 청구 전이거나(미청구공사) 대금을 늦게 받는 경우가 많습니다. 받을 돈 회수기간이 길어지면 이익이 현금으로 늦게 들어옵니다.",
     "metrics": [("receivables_days", "받을 돈 회수기간", "일", -1, "평균(매출채권 + 미청구공사) ÷ 매출액 × 365"),
                 ("asset_turnover_x", "총자산회전율", "회", 1, "매출액 ÷ 평균 자산총계"),
                 ("dso_days", "매출채권 회수기간", "일", -1, "평균 매출채권 ÷ 매출액 × 365"),
                 ("dpo_days", "매입채무 지급기간", "일", 0, "평균 매입채무 ÷ 매출원가 × 365"),
                 ("ccc_days", "현금전환주기", "일", -1, "매출채권 회수기간 + 재고 보유기간 − 매입채무 지급기간")]},
    {"id": "growth", "no": 5, "ko": "성장성", "en": "Growth", "q": "회사가 커지고 있는가",
     "read": "건설사 매출은 2~3년 전에 따낸 수주잔고에서 나옵니다. 매출 증가와 자기자본 증가를 함께 보면 커지는 만큼 남기고 있는지 알 수 있습니다.",
     "metrics": [("revenue_growth_pct", "매출증가율", "%", 1, "(올해 매출 ÷ 작년 매출) − 1"),
                 ("op_growth_pct", "영업이익증가율", "%", 1, "작년 영업이익이 적자면 계산하지 않음"),
                 ("asset_growth_pct", "총자산증가율", "%", 0, "(올해 말 자산 ÷ 작년 말 자산) − 1"),
                 ("equity_growth_pct", "자기자본증가율", "%", 1, "(올해 말 자본 ÷ 작년 말 자본) − 1")]},
    {"id": "productivity", "no": 6, "ko": "생산성", "en": "Productivity", "q": "직원 한 명이 얼마나 벌어 오는가",
     "read": "사업보고서 '직원 현황'은 현대건설 단독(자회사 제외) 기준이라, 매출·영업이익도 단독 숫자로 나눴습니다. 1인당 값은 기초·기말 평균 직원 수로 나눈 값입니다.",
     "metrics": [("rev_per_emp", "1인당 매출액", "억 원", 1, "단독 매출액 ÷ 평균 직원 수"),
                 ("op_per_emp", "1인당 영업이익", "백만 원", 1, "단독 영업이익 ÷ 평균 직원 수"),
                 ("avg_salary", "1인 평균 급여", "백만 원", 0, "사업보고서 직원 현황의 1인 평균 급여액"),
                 ("employees", "직원 수", "명", 0, "사업보고서 직원 현황 합계(기말)")]},
    {"id": "cashflow", "no": 7, "ko": "현금흐름", "en": "Cash flow", "q": "이익이 현금으로 들어오는가",
     "read": "영업활동현금흐름이 순이익보다 적은 해가 이어지면 공사비를 늦게 받거나 미리 쓴 돈이 많다는 뜻입니다. 투자까지 뺀 잉여현금흐름(FCF)이 진짜 남는 돈입니다.",
     "metrics": [("operating_cashflow", "영업활동현금흐름", "조 원", 1, "현금흐름표"),
                 ("fcf", "잉여현금흐름(FCF)", "조 원", 1, "영업활동현금흐름 − 유형·무형자산 취득"),
                 ("cfo_to_ni_x", "CFO/순이익", "배", 1, "영업활동현금흐름 ÷ 당기순이익 (1배 이상이면 이익만큼 현금이 들어옴)")]},
    {"id": "market", "no": 8, "ko": "시장가치", "en": "Market value", "q": "시장은 이 회사를 얼마로 보는가",
     "read": "PBR이 1배보다 낮으면 시장이 회사를 장부상 자본보다 싸게 보고 있다는 뜻입니다. 배수는 결과이므로 성장·수익성·위험과 함께 읽습니다(연말 주가 기준).",
     "metrics": [("pbr_x", "PBR", "배", 0, "시가총액 ÷ 지배주주 자본"),
                 ("per_x", "PER", "배", 0, "시가총액 ÷ 지배주주 순이익 (적자면 계산 안 함)"),
                 ("ev_ebitda_x", "EV/EBITDA", "배", 0, "(시가총액 + 순차입금 + 비지배지분) ÷ EBITDA"),
                 ("fcf_yield_pct", "FCF 수익률", "%", 1, "FCF ÷ 시가총액")]},
    {"id": "dupont", "no": 9, "ko": "종합 분석", "en": "DuPont", "q": "ROE는 무엇으로 만들어졌나",
     "read": "듀퐁 분석은 ROE를 순이익률(얼마나 남기나) × 총자산회전율(얼마나 빨리 돌리나) × 재무레버리지(빚을 얼마나 쓰나)로 나눠, ROE가 바뀐 원인을 찾는 종합 분석 도구입니다.",
     "metrics": [("roe_pct", "ROE", "%", 1, "= 순이익률 × 총자산회전율 × 재무레버리지"),
                 ("net_margin_pct", "순이익률", "%", 1, "당기순이익 ÷ 매출액"),
                 ("asset_turnover_x", "총자산회전율", "회", 1, "매출액 ÷ 평균 자산총계"),
                 ("leverage_x", "재무레버리지", "배", 0, "평균 자산총계 ÷ 평균 자본총계")]},
    {"id": "price", "no": 10, "ko": "주가 반영", "en": "Share price", "q": "주가는 실적을 따라갔나",
     "read": "연말 주가가 1년 동안 오른 비율과 같은 해 영업이익 증가율을 나란히 놓으면, 주가가 실적을 반영했는지(또는 앞서갔는지) 볼 수 있습니다.",
     "metrics": [("price_return_pct", "주가 연간 상승률", "%", 0, "연말 종가 ÷ 전년 말 종가 − 1 (2021년 이전은 수정주가)"),
                 ("op_growth_pct", "영업이익 증가율", "%", 1, "작년 영업이익이 적자면 계산하지 않음"),
                 ("market_cap", "연말 시가총액", "조 원", 0, "연말 종가 × (보통주 + 우선주)"),
                 ("price_close", "연말 주가", "원", 0, "12월 말 보통주 종가")]},
]
SCALE = {"조 원": T, "억 원": EOK, "백만 원": MIL}


def _avg(a, b):
    return None if a is None or b is None else (a + b) / 2


def _growth(cur, prev):
    if cur is None or prev is None or prev <= 0:
        return None
    return (cur / prev - 1) * 100


def window_years(ctx, n=WINDOW):
    years = [r["year"] for r in ctx["annual"] if r["values"].get("revenue") is not None]
    return years[-n:]


def table(ctx):
    """{연도: {지표 키: 값(표시 단위)}} — 연결 연간 + 사업보고서(생산성)."""
    rows = {r["year"]: r for r in ctx["annual"]}
    biz = ctx.get("business") or {}
    emp = biz.get("employees") or {}
    sep = biz.get("separate") or {}
    out = {}
    for y, r in rows.items():
        v, ra = r["values"], r["ratios"]
        pv = (rows.get(y - 1) or {}).get("values") or {}
        d = {k: ra.get(k) for k in ra}
        d.update({k: v.get(k) for k in ("operating_cashflow", "fcf", "market_cap", "price_close")})
        d["op_growth_pct"] = _growth(v.get("operating_profit"), pv.get("operating_profit"))
        d["asset_growth_pct"] = _growth(v.get("assets"), pv.get("assets"))
        d["equity_growth_pct"] = _growth(v.get("equity"), pv.get("equity"))
        d["price_return_pct"] = _growth(v.get("price_close"), pv.get("price_close"))
        cl = v.get("current_liabilities")
        cash = (v.get("cash") or 0) + (v.get("short_term_deposits") or 0) if v.get("cash") is not None else None
        d["cash_ratio_pct"] = fin.ratio(cash, cl)
        avg_assets, avg_equity = _avg(v.get("assets"), pv.get("assets")), _avg(v.get("equity"), pv.get("equity"))
        d["leverage_x"] = None if not avg_assets or not avg_equity or avg_equity <= 0 else avg_assets / avg_equity
        avg_rec = _avg(v.get("receivables_total"), pv.get("receivables_total"))
        d["receivables_days"] = None if avg_rec is None or not v.get("revenue") else avg_rec / v["revenue"] * 365
        e, pe = emp.get(str(y)), emp.get(str(y - 1))
        s = sep.get(str(y))
        heads = _avg(e["count"], pe["count"]) if e and pe else (e["count"] if e else None)
        d["employees"] = e["count"] if e else None
        d["avg_salary"] = e["avg_salary"] if e else None
        d["rev_per_emp"] = s["revenue"] / heads if s and heads and s.get("revenue") is not None else None
        d["op_per_emp"] = s["operating_profit"] / heads if s and heads and s.get("operating_profit") is not None else None
        out[y] = d
    return out


def display(value, unit):
    """원 단위 값을 표시 단위 숫자로 (조 원·억 원·백만 원)."""
    if value is None:
        return None
    return value / SCALE[unit] if unit in SCALE else value


def fmt(value, unit, signed=False):
    if value is None:
        return "–"
    v = display(value, unit)
    if unit in ("%", "조 원"):
        d = 1 if unit == "%" or abs(v) < 100 else 0
        s = f"{v:+,.{d}f}" if signed else f"{v:,.{d}f}"
    elif unit in ("배", "회"):
        s = f"{v:,.2f}" if abs(v) < 10 else f"{v:,.1f}"
    elif unit == "억 원":
        s = f"{v:,.1f}"
    else:
        s = f"{v:,.0f}"
    return s.replace("-", "−")


def judge(values, latest, direction):
    """10년 안에서 지금 위치 → (tone, word, rank). rank: 1 = 가장 좋음."""
    vals = [x for x in values if x is not None]
    if latest is None or len(vals) < 4 or direction == 0:
        return "info", "참고", None
    better = sum(1 for x in vals if (x > latest if direction > 0 else x < latest))
    rank = better + 1
    share = better / (len(vals) - 1)
    if share <= 0.3:
        return "good", "10년 중 상위", rank
    if share >= 0.7:
        return "crit", "10년 중 하위", rank
    return "warn", "10년 중 중간", rank


def median(vals):
    vals = sorted(x for x in vals if x is not None)
    if not vals:
        return None
    m = len(vals) // 2
    return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2


def build(ctx, n=WINDOW):
    """관점별 계산 결과 목록."""
    years = window_years(ctx, n)
    tab = table(ctx)
    out = []
    for lens in LENSES:
        metrics = []
        for key, label, unit, direction, how in lens["metrics"]:
            values = [tab.get(y, {}).get(key) for y in years]
            latest = values[-1] if values else None          # 가장 최근 연도 값만 씁니다(없으면 판정하지 않음)
            tone, word, rank = judge(values, latest, direction)
            if latest is None:
                tone, word = "info", "숫자 없음"
            metrics.append({"key": key, "label": label, "unit": unit, "dir": direction, "how": how, "values": values,
                            "latest": latest, "latest_year": years[-1] if years else None,
                            "median": median(values), "tone": tone, "word": word, "rank": rank,
                            "count": sum(1 for x in values if x is not None)})
        out.append({**lens, "years": years, "metrics_data": metrics, "head": metrics[0]})
    return out


def with_unit(value, unit, signed=False):
    """2.1 → '2.1%', 0.75조 → '0.75조 원', 6900 → '6,900명'."""
    text = fmt(value, unit, signed)
    if text == "–":
        return text
    return text + unit


def sentence(m):
    """'2025년 영업이익률 2.1% · 10년 중 9번째 (중앙값 4.1%)' 같은 한 줄 (**굵게** 표시 포함)."""
    if m["latest"] is None:
        return f"{m['latest_year']}년 {m['label']}: 계산할 수 없음 ({m['how']})"
    head = f"{m['latest_year']}년 {m['label']} **{with_unit(m['latest'], m['unit'])}**"
    med = with_unit(m["median"], m["unit"])
    if m["rank"] is None:
        return f"{head} · {m['count']}년 중앙값 {med}"
    return f"{head} · {m['count']}년 중 **{m['rank']}위**(좋은 순) · 중앙값 {med}"
