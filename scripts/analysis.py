"""자동 해설: 매달 새 숫자로 문장을 다시 씁니다.

문장은 정해진 규칙으로 만들고, 안에 들어가는 숫자는 모두 표에서 계산합니다. (AI·외부 서비스 사용 없음)
'**'로 감싼 부분은 화면에서 굵게 표시됩니다.
기사로 확인한 배경 설명(CONTEXT)만 출처와 함께 직접 적어 두었습니다.
"""
import financials as fin

T = 1_000_000_000_000
MINUS = "−"


# ---------------------------------------------------------------------------
# 숫자 표기
# ---------------------------------------------------------------------------
def _m(s):
    return s.replace("-", MINUS)


def won(v):
    """31062912000000 → '31조 629억' (뉴스에서 쓰는 표기)."""
    if v is None:
        return "자료 없음"
    eok = round(abs(v) / 100_000_000)
    jo, rest = divmod(eok, 10_000)
    text = f"{jo}조 {rest:,}억" if jo and rest else (f"{jo}조" if jo else f"{rest:,}억")
    return (MINUS if v < 0 else "") + text


def jo(v, d=1):
    return "–" if v is None else _m(f"{v / T:,.{d}f}")


def pct(v, d=1):
    return "–" if v is None else _m(f"{v:,.{d}f}")


def signed(v, d=1):
    return "–" if v is None else _m(f"{v:+,.{d}f}")


def change_word(v, up="늘었", down="줄었"):
    return up if v >= 0 else down


QUARTER_MONTHS = {"Q1": "1~3월", "Q2": "4~6월", "Q3": "7~9월", "Q4": "10~12월"}


def qname(row):
    return f"{row['year']}년 {row['kind'][1]}분기({QUARTER_MONTHS[row['kind']]})"


# ---------------------------------------------------------------------------
# 언론 보도로 확인한 배경 (요약은 직접 작성, 출처 링크 포함)
# ---------------------------------------------------------------------------
SOURCES = {
    "mt2011": ("머니투데이, 2011.05.17", "https://www.mt.co.kr/estate/2011/05/17/2011051308183626824"),
    "sat2014": ("토요경제, 2014.01.20", "https://sateconomy.co.kr/news/view/179590192894798"),
    "inews24": ("아이뉴스24, 2021.03.24", "https://www.inews24.com/view/1352243"),
    "tomato": ("뉴스토마토, 2024.01.29", "https://newstomato.com/ReadNews.aspx?no=1217505"),
    "hankyung": ("한경비즈니스, 2024.01.24", "https://magazine.hankyung.com/business/article/202401247040b"),
    "newsis": ("뉴시스, 2025.01.23", "https://www.newsis.com/view/NISX20250122_0003042645"),
    "ceoscore": ("CEO스코어데일리, 2026.03.03", "https://ceoscoredaily.com/page/view/2026022715452685651"),
}


# ---------------------------------------------------------------------------
# 도우미
# ---------------------------------------------------------------------------
class View:
    def __init__(self, ctx):
        self.ctx = ctx
        self.annual = [r for r in ctx["annual"] if r["values"].get("revenue") is not None]
        self.halves = ctx["halves"]
        self.quarters = [q for q in ctx["quarters"] if q["values"].get("revenue") is not None]
        self.by_year = {r["year"]: r for r in self.annual}
        self.years = [r["year"] for r in self.annual]

    def a(self, year, key):
        r = self.by_year.get(year)
        if not r:
            return None
        return r["values"].get(key) if key in r["values"] else r["ratios"].get(key)

    def series(self, key):
        return [self.a(y, key) for y in self.years]

    def per100(self, year, key):
        v, rev = self.a(year, key), self.a(year, "revenue")
        return None if v is None or not rev else v / rev * 100

    def has(self, *years):
        return all(y in self.by_year for y in years)

    def ttm(self, key):
        return fin.ttm(self.quarters, key)[0]

    def ttm_prev(self, key):
        """최근 4개 분기 바로 앞의 4개 분기 합계 (1년 전 같은 기준)."""
        return fin.ttm(self.quarters[:-4], key)[0] if len(self.quarters) >= 8 else None

    def ttm_quarters(self):
        return fin.ttm(self.quarters, "revenue")[1] or []

    def latest_balance(self):
        """가장 최근 분기말 재무상태표가 있는 행."""
        for q in reversed(self.ctx["quarters"]):
            if q["values"].get("assets") is not None:
                return q
        return self.annual[-1] if self.annual else None

    def last_with(self, key):
        """그 비율·값이 있는 가장 최근 연도."""
        for t in reversed(self.years):
            if self.a(t, key) is not None:
                return t
        return None


def neg_streak(values):
    n = 0
    for v in reversed(values):
        if v is None or v >= 0:
            break
        n += 1
    return n


def ttm_span(v):
    tq = v.ttm_quarters()
    return f"{tq[0]['year']}.{tq[0]['kind'][1]}Q~{tq[-1]['year']}.{tq[-1]['kind'][1]}Q" if tq else ""


def when_label(row):
    return f"{row['year']}년 {row['month']}월 말" if row["kind"] != "annual" else f"{row['year']}년 말"


HURDLE_ROIC = 8.0   # 투자수익률 단순 기준(%) — 흔히 쓰는 주주 기대수익률 수준


# ---------------------------------------------------------------------------
# 판정 (교수님 가이드의 6단계 분석 순서)
# ---------------------------------------------------------------------------
def verdicts(v):
    first, last = v.annual[0], v.annual[-1]
    span = last["year"] - first["year"]
    cagr = None
    if span > 0 and first["values"]["revenue"] > 0 and last["values"]["revenue"] > 0:
        cagr = ((last["values"]["revenue"] / first["values"]["revenue"]) ** (1 / span) - 1) * 100
    growth = ("warn", "확인 필요") if cagr is None else ("good", "성장") if cagr >= 3 else ("warn", "정체") if cagr >= 0 else ("crit", "축소")

    # 2 이익률
    m0 = first["ratios"]["operating_margin_pct"]
    rev_ttm, op_ttm = v.ttm("revenue"), v.ttm("operating_profit")
    m_now = fin.ratio(op_ttm, rev_ttm) if rev_ttm else last["ratios"]["operating_margin_pct"]
    if m_now is None or m0 is None:
        profit = ("warn", "확인 필요")
    elif m_now < 0:
        profit = ("crit", "적자")
    elif m_now < m0 * 0.5:
        profit = ("warn", "약해짐")
    else:
        profit = ("good", "유지")

    # 3 현금흐름
    streak = neg_streak(v.series("operating_cashflow"))
    cash = ("crit", "경고") if streak >= 2 else ("warn", "주의") if streak == 1 else ("good", "양호")

    # 4 차입 부담 (가이드: 차입비율보다 상환능력 우선 → 이자보상배율·순차입금/EBITDA)
    bal = v.latest_balance()
    int_ttm = v.ttm("interest_expense")
    coverage = op_ttm / int_ttm if op_ttm is not None and int_ttm and int_ttm > 0 else None
    ebitda_ttm = v.ttm("ebitda")
    net_debt = bal["values"].get("net_debt") if bal else None
    nd_ebitda = None
    if net_debt is not None and ebitda_ttm is not None and ebitda_ttm > 0:
        nd_ebitda = net_debt / ebitda_ttm
    heavy = net_debt is not None and net_debt > 0 and (ebitda_ttm is None or ebitda_ttm <= 0 or (nd_ebitda or 0) > 5)
    if coverage is None:
        debt = ("warn", "확인 필요")
    elif coverage < 1 or heavy:
        debt = ("crit", "위험")
    elif coverage < 3 or (net_debt is not None and net_debt > 0 and (nd_ebitda or 0) > 3):
        debt = ("warn", "주의")
    else:
        debt = ("good", "양호")

    # 5 투자수익률: ROIC를 세후 차입 이자율, 단순 기준 8%와 비교
    roic_year = v.last_with("roic_pct")
    roic = v.a(roic_year, "roic_pct") if roic_year else None
    rate_year = v.last_with("borrowing_rate_pct")
    rate = v.a(rate_year, "borrowing_rate_pct") if rate_year else None
    tax = fin.effective_tax_rate(v.by_year[roic_year]["values"]) if roic_year else None
    after_tax_rate = rate * (1 - (tax if tax is not None else fin.DEFAULT_TAX_RATE)) if rate is not None else None
    if roic is None:
        returns = ("warn", "확인 필요")
    elif after_tax_rate is not None and roic < after_tax_rate:
        returns = ("crit", "경고")
    elif roic < HURDLE_ROIC:
        returns = ("warn", "주의")
    else:
        returns = ("good", "양호")

    # 6 주가 수준: 좋고 나쁨을 판정하지 않고 참고 값만 보여 줍니다(가이드: 배수는 결과).
    valuation = ("info", "참고")

    return {"growth": growth, "profit": profit, "cash": cash, "debt": debt, "returns": returns, "valuation": valuation,
            "cagr": cagr, "margin_now": m_now, "margin_first": m0, "streak": streak, "balance_row": bal,
            "coverage": coverage, "nd_ebitda": nd_ebitda, "net_debt": net_debt, "ebitda_ttm": ebitda_ttm,
            "roic": roic, "roic_year": roic_year, "borrow_rate": rate, "after_tax_rate": after_tax_rate}


VERDICT_RULES = [
    "1 매출 성장: 연간 매출의 연평균 성장률(CAGR)이 3% 이상이면 ‘성장’, 0~3%면 ‘정체’, 0% 미만이면 ‘축소’.",
    "2 이익률: 최근 4개 분기 영업이익률이 0% 미만이면 ‘적자’, 첫해 영업이익률의 절반에 못 미치면 ‘약해짐’, 그 밖에는 ‘유지’.",
    "3 현금흐름: 연간 영업활동현금흐름이 최근까지 2년 이상 연속 마이너스면 ‘경고’, 1년만 마이너스면 ‘주의’, 그 밖에는 ‘양호’.",
    "4 차입 부담: 최근 4개 분기 이자보상배율이 1배 미만이거나 순차입금이 EBITDA의 5배를 넘으면 ‘위험’, "
    "이자보상배율 3배 미만이거나 순차입금/EBITDA 3배 초과면 ‘주의’, 그 밖에는 ‘양호’ (순현금이면 순차입금 조건은 통과).",
    f"5 투자수익률: 최근 연간 ROIC가 세후 차입 이자율보다 낮으면 ‘경고’, {HURDLE_ROIC:.0f}% 미만이면 ‘주의’, 그 이상이면 ‘양호’. "
    f"(가이드는 ROIC를 자본비용(WACC)과 비교하라고 하지만 WACC는 공시 숫자가 아니어서, 흔히 쓰는 주주 기대수익률 수준인 "
    f"{HURDLE_ROIC:.0f}%를 단순 기준으로 삼았습니다.)",
    "6 주가 수준: 판정하지 않습니다. 가이드처럼 배수는 결과이므로 성장·수익성·위험과 함께 참고 값으로만 보여 줍니다.",
]


# ---------------------------------------------------------------------------
# 문장 만들기
# ---------------------------------------------------------------------------
def price_when(val):
    """주가 기준 시점. 지난달까지는 '2026.09 월말', 아직 끝나지 않은 이번 달이면 받은 날 '2026.10.26'."""
    as_of, fetched = val.get("as_of", ""), str(val.get("fetched") or "")
    if fetched[:7].replace("-", ".") == as_of:
        return fetched.replace("-", ".")
    return f"{as_of} 월말"


def update_box(ctx):
    status = ctx["status"]
    lines = []
    new = [f for f in status.get("new_filings", []) if "보고서" in f.get("report_nm", "")]
    checked = status.get("checked_at", "")[:10]
    if status.get("mode") == "online":
        if new:
            names = ", ".join(f"{f['report_nm'].strip()}({f['rcept_dt'][:4]}.{f['rcept_dt'][4:6]}.{f['rcept_dt'][6:]} 접수)" for f in new[-4:])
            more = f" 외 {len(new) - 4}건" if len(new) > 4 else ""
            lines.append(f"**{checked} 확인** · 새로 반영한 보고서: {names}{more}")
        else:
            lines.append(f"**{checked} 확인** · 새로 나온 정기보고서가 없어 숫자는 그대로입니다.")
    else:
        lines.append(f"**{checked} 기준** · 저장된 자료로 화면을 다시 만들었습니다.")
    lf = ctx.get("latest_filing")
    if lf:
        lines.append(f"가장 최근 반영 보고서: **{lf['report_nm'].strip()}** ({lf['rcept_dt'][:4]}.{lf['rcept_dt'][4:6]}.{lf['rcept_dt'][6:]} 접수)")
    val = ctx.get("valuation") or {}
    if val.get("as_of"):
        lines.append(f"주가: {price_when(val)} 종가 기준 ({val.get('source', '')}, {val.get('fetched', '')} 받음)")
    lines.append(f"다음 자동 확인: **{ctx['next_run'].replace('-', '.')} 09:17** (매월 1일)")
    return {"lines": lines, "errors": status.get("errors", []), "notes": status.get("notes", [])}


def headline(v, vd):
    first, last = v.annual[0], v.annual[-1]
    mult = last["values"]["revenue"] / first["values"]["revenue"]
    m0, ml = first["ratios"]["operating_margin_pct"], last["ratios"]["operating_margin_pct"]
    text = (f"연간 매출은 {first['year']}년 {jo(first['values']['revenue'])}조 원에서 {last['year']}년 "
            f"{jo(last['values']['revenue'])}조 원으로 **{mult:.2f}배**가 됐습니다. 하지만 100원어치 공사를 해서 남기는 돈은 "
            f"**{pct(m0)}원에서 {pct(ml)}원**으로 {change_word(ml - m0, '늘었', '줄었')}고, ")
    streak = vd["streak"]
    if streak:
        text += f"본업에서 들어오는 현금은 **{streak}년 연속 마이너스**입니다."
    else:
        text += "본업에서 들어오는 현금은 플러스를 유지하고 있습니다."
    return text


def latest_quarter(v):
    if not v.quarters:
        return None
    q = v.quarters[-1]
    idx = {(r["year"], r["kind"]): r for r in v.quarters}
    ly = idx.get((q["year"] - 1, q["kind"]))
    qv, r = q["values"], q["ratios"]
    lines = []
    s = f"{qname(q)} 매출은 **{jo(qv['revenue'], 2)}조 원**"
    parts = []
    if r.get("revenue_growth_pct") is not None:
        parts.append(f"1년 전보다 {pct(abs(r['revenue_growth_pct']))}% {change_word(r['revenue_growth_pct'])}고")
    if r.get("qoq_growth_pct") is not None:
        parts.append(f"직전 분기보다 {pct(abs(r['qoq_growth_pct']))}% {change_word(r['qoq_growth_pct'])}습니다")
    s += ("으로 " + ", ".join(parts) + ".") if parts else "입니다."
    lines.append(s)
    op = qv.get("operating_profit")
    if op is not None:
        s = f"영업{'이익' if op >= 0 else '손실'}은 **{won(abs(op))} 원**(영업이익률 {pct(r.get('operating_margin_pct'))}%)"
        if ly and ly["values"].get("operating_profit") is not None:
            lop = ly["values"]["operating_profit"]
            s += f"으로 1년 전 같은 분기({won(lop)} 원)보다 {'많습니다' if op > lop else '적습니다' if op < lop else '같습니다'}."
        else:
            s += "입니다."
        lines.append(s)
    if r.get("interest_coverage_x") is not None:
        lines.append(f"이 분기 영업이익은 이자비용의 **{pct(r['interest_coverage_x'])}배**입니다(이자보상배율).")
    cum = next((h for h in reversed(v.halves) if h["year"] == q["year"] and h["kind"] == "H1"), None) if q["kind"] == "Q2" else None
    cf = (cum or q)["values"].get("operating_cashflow")
    if cum and cf is not None:
        lines.append(f"상반기 누적 영업활동현금흐름은 **{won(cf)} 원**입니다." + (" 이익은 흑자인데 현금은 빠져나갔습니다."
                                                                       if cf < 0 and (cum['values'].get('operating_profit') or 0) > 0 else ""))
    elif cf is not None:
        lines.append(f"이 분기 영업활동현금흐름은 {won(cf)} 원입니다.")
    if qv.get("assets") is not None:
        nd = qv.get("net_debt")
        nd_text = "" if nd is None else (f", 순차입금 {jo(nd, 2)}조 원" if nd >= 0 else f", 순현금 {jo(-nd, 2)}조 원")
        lines.append(f"{q['month']}월 말 부채비율 **{pct(r.get('debt_to_equity_pct'), 0)}%**, 유동비율 {pct(r.get('current_ratio_pct'), 0)}%"
                     f"{nd_text}, 받을 돈(매출채권+미청구공사) {jo(qv.get('receivables_total'), 2)}조 원입니다.")
    return {"title": f"가장 최근 분기: {qname(q)}", "lines": lines, "row": q}


def _growth_step(v, vd):
    first, last = v.annual[0], v.annual[-1]
    y0, yl = first["year"], last["year"]
    revs = v.series("revenue")
    mult = last["values"]["revenue"] / first["values"]["revenue"]
    peak_i = max(range(len(revs)), key=lambda i: revs[i] or 0)
    more = []
    if v.has(2021, 2024):
        early = [v.a(t, "revenue") for t in v.years if t <= 2021]
        more.append(f"{y0}~2021년 매출은 **{jo(min(early))}~{jo(max(early))}조 원**이었습니다. 큰 도약은 2022~2024년 3년에 몰려 있어서, "
                    f"이 기간에만 **{jo(v.a(2024, 'revenue') - v.a(2021, 'revenue'))}조 원**이 늘었습니다.")
    g_last = last["ratios"]["revenue_growth_pct"]
    more.append(f"정점은 {v.years[peak_i]}년({jo(revs[peak_i])}조 원)입니다."
                + (f" {yl}년 매출은 전년보다 {pct(abs(g_last))}% {change_word(g_last)}습니다." if g_last is not None else ""))
    ttm_rev, prev = v.ttm("revenue"), v.ttm_prev("revenue")
    if ttm_rev:
        text = f"가장 최근 4개 분기({ttm_span(v)}) 매출 합계는 **{jo(ttm_rev)}조 원**"
        if prev:
            g = fin.growth(ttm_rev, prev)
            text += f"으로, 그 전 4개 분기보다 {pct(abs(g))}% {change_word(g)}습니다."
        else:
            text += "입니다."
        more.append(text)
    base = 2021 if v.has(2021) else y0
    r0, rl = v.a(base, "receivables_total"), last["values"].get("receivables_total")
    s0, sl = v.a(base, "revenue"), last["values"].get("revenue")
    if r0 and rl and s0 and sl:
        more.append(f"가이드는 ‘매출이 늘어도 채권이 더 빨리 늘면 현금이 묶일 수 있다’고 봅니다. {base}→{yl}년 매출은 {sl / s0:.1f}배, "
                    f"받을 돈(매출채권+미청구공사)은 **{rl / r0:.1f}배**가 됐습니다"
                    + (". 채권이 매출보다 빨리 늘었습니다." if rl / r0 > sl / s0 else "."))
    return {"id": "growth", "no": 1, "en": "Revenue growth", "ko": "매출 성장", "q": "외형이 실제 사업 성장으로 커지고 있나?",
            "answer": f"{y0}년 이후 매출이 {mult:.2f}배가 됐습니다. 연평균 {pct(vd['cagr'])}% 성장입니다.",
            "lead": f"{y0}년 {won(first['values']['revenue'])} 원에서 {yl}년 {won(last['values']['revenue'])} 원이 됐습니다.",
            "more": more}


def _profit_step(v, vd):
    first, last = v.annual[0], v.annual[-1]
    y0, yl = first["year"], last["year"]
    m0, ml = first["ratios"]["operating_margin_pct"], last["ratios"]["operating_margin_pct"]
    loss_years = [t for t in v.years if (v.a(t, "operating_margin_pct") or 0) < 0]
    answer = f"{y0}년엔 {pct(m0)}원, {yl}년엔 {pct(ml)}원이 남았습니다." + "".join(
        f" {t}년엔 {pct(abs(v.a(t, 'operating_margin_pct')))}원 손해였습니다." for t in loss_years)
    more = []
    # 가이드: 총이익률이 함께 떨어지면 가격·원가, 총이익률은 그대로인데 영업이익률만 떨어지면 판관비
    base = yl - 4 if v.has(yl - 4) else y0
    g0, g1 = v.a(base, "gross_margin_pct"), v.a(yl, "gross_margin_pct")
    o0, o1 = v.a(base, "operating_margin_pct"), v.a(yl, "operating_margin_pct")
    if None not in (g0, g1, o0, o1):
        text = (f"{base}→{yl}년 매출총이익률은 {pct(g0)}% → {pct(g1)}%({signed(g1 - g0)}%p), "
                f"영업이익률은 {pct(o0)}% → {pct(o1)}%({signed(o1 - o0)}%p)입니다. ")
        if g1 - g0 <= -1:
            text += "총이익률이 함께 떨어졌으므로, 가이드 기준으로는 판관비보다 **공사 원가·가격** 쪽 원인을 먼저 봐야 합니다."
        elif o1 - o0 <= -1:
            text += "총이익률은 버텼는데 영업이익률이 떨어졌으므로 **판관비**가 늘어난 영향을 봐야 합니다."
        else:
            text += "두 이익률이 크게 달라지지 않았습니다."
        more.append(text)
    costs = [(t, v.per100(t, "cost_of_sales")) for t in v.years if v.per100(t, "cost_of_sales") is not None]
    if costs:
        lo = min(costs, key=lambda x: x[1])
        hi = max(costs, key=lambda x: x[1])
        text = f"원가율이 가장 낮았던 해는 {lo[0]}년({pct(lo[1])}%), 가장 높았던 해는 **{hi[0]}년({pct(hi[1])}%)**입니다."
        gp = v.a(hi[0], "gross_profit")
        if hi[1] > 100 and gp is not None:
            text += f" 이 해에는 원가만으로 매출을 넘어서, 판관비를 쓰기 전에 이미 {won(abs(gp))} 원 적자(매출총손실)였습니다."
        more.append(text)
    if v.has(2024):
        r24 = v.by_year[2024]["values"]
        ni, nci, owners = r24.get("net_income"), r24.get("net_income_nci"), r24.get("net_income_owners")
        if None not in (ni, nci, owners) and ni < 0 and nci < 0 and abs(nci) > abs(owners):
            more.append(f"2024년 순손실 {won(abs(ni))} 원 가운데 **{won(abs(nci))} 원**은 비지배지분 몫이었습니다. "
                        f"손실의 큰 부분이 연결 자회사 쪽에서 났다는 신호입니다.")
    em = last["ratios"].get("ebitda_margin_pct")
    if vd["margin_now"] is not None:
        text = f"최근 4개 분기({ttm_span(v)}) 영업이익률은 **{pct(vd['margin_now'])}%**입니다."
        if em is not None:
            text += f" 감가상각비를 더한 EBITDA 마진은 {yl}년 {pct(em)}%로, 건설업은 설비가 적어 영업이익률과 차이가 작습니다."
        more.append(text)
    return {"id": "profit", "no": 2, "en": "Margins", "ko": "이익률", "q": "성장이 이익으로 남고 있나?",
            "answer": answer,
            "lead": "건설업은 매출의 90% 안팎이 공사 원가(자재비·인건비·외주비)입니다. 원가율이 몇 %p만 올라도 남는 돈이 크게 줄어듭니다.",
            "more": more}


def _cash_step(v, vd):
    last = v.annual[-1]
    yl = last["year"]
    streak = vd["streak"]
    more = []
    if streak:
        a = yl - streak + 1
        sum_op = sum(v.a(t, "operating_profit") or 0 for t in range(a, yl + 1))
        sum_cf = sum(v.a(t, "operating_cashflow") or 0 for t in range(a, yl + 1))
        answer = f"장부상 이익은 흑자인데, 현금은 {streak}년 연속 빠져나갔습니다." if sum_op > 0 else f"현금이 {streak}년 연속 빠져나갔습니다."
        lead = (f"{a}~{yl}년 {streak}년 동안 영업이익은 합계 **{won(sum_op)} 원**이었지만, "
                f"영업활동현금흐름은 합계 **{won(sum_cf)} 원**이었습니다.")
    else:
        answer = "본업에서 번 돈이 현금으로도 들어오고 있습니다."
        lead = f"{yl}년 영업활동현금흐름은 {won(last['values'].get('operating_cashflow'))} 원입니다."
    # 가이드: 한 해보다 3~5년 누적 CFO와 누적 순이익을 비교
    span = [t for t in v.years if t > yl - 5]
    cfo = [v.a(t, "operating_cashflow") for t in span]
    ni = [v.a(t, "net_income") for t in span]
    if len(span) == 5 and None not in cfo and None not in ni:
        sc, sn = sum(cfo), sum(ni)
        text = f"가이드처럼 5년을 묶어 보면({span[0]}~{yl}년) 누적 영업현금흐름 **{jo(sc, 2)}조 원**, 누적 순이익 {jo(sn, 2)}조 원입니다."
        if sn > 0:
            text += f" CFO/순이익은 **{pct(sc / sn, 2)}배**로, 1배보다 작을수록 이익이 현금으로 덜 들어왔다는 뜻입니다."
        more.append(text)
    base = 2021 if v.has(2021) else v.years[0]
    r0, rl = v.a(base, "receivables_total"), last["values"].get("receivables_total")
    if r0 and rl:
        more.append(f"이유는 ‘받을 돈’입니다. 공사는 했지만 아직 현금으로 받지 못한 금액(매출채권+미청구공사)이 "
                    f"{base}년 말 **{jo(r0)}조 원**에서 {yl}년 말 **{jo(rl)}조 원**으로 {rl / r0:.1f}배가 됐습니다.")
    c0, c1 = v.a(base, "ccc_days"), last["ratios"].get("ccc_days")
    d0, d1 = v.a(base, "dso_days"), last["ratios"].get("dso_days")
    if None not in (c0, c1, d0, d1):
        more.append(f"운전자본에 현금이 묶이는 기간(CCC)은 {base}년 {c0:.0f}일 → {yl}년 **{c1:.0f}일**입니다. "
                    f"매출채권 회수일수(DSO)가 {d0:.0f}일에서 {d1:.0f}일로 늘어난 영향이 큽니다.")
    capex, fcf = last["values"].get("capex"), last["values"].get("fcf")
    if capex is not None and fcf is not None:
        more.append(f"{yl}년 설비투자(CAPEX)는 {won(capex)} 원으로 크지 않아, 투자 후 남는 현금(FCF = 영업현금흐름 − CAPEX)은 "
                    f"**{won(fcf)} 원**입니다. 건설사의 FCF는 사실상 공사대금 회수가 결정합니다.")
    h1 = next((h for h in reversed(v.halves) if h["kind"] == "H1"), None)
    if h1 and h1["year"] > yl and h1["values"].get("operating_cashflow") is not None:
        cf = h1["values"]["operating_cashflow"]
        more.append(f"{h1['year']}년 상반기에도 영업활동현금흐름은 **{won(cf)} 원**이고, 6월 말 받을 돈은 "
                    f"{jo(h1['values'].get('receivables_total'))}조 원입니다.")
    return {"id": "cash", "no": 3, "en": "Cash flow", "ko": "현금흐름", "q": "이익이 현금으로 들어오고 있나?",
            "answer": answer, "lead": lead, "more": more}


def _debt_step(v, vd):
    bal = vd["balance_row"]
    br, bv = bal["ratios"], bal["values"]
    cov, nd, nde = vd["coverage"], vd["net_debt"], vd["nd_ebitda"]
    answer = {"good": "영업이익으로 보면 이자를 갚을 여력은 충분합니다.",
              "warn": "이자는 감당하지만 여유가 줄었습니다.",
              "crit": "이자와 빚을 감당하기 어려운 수준입니다."}.get(vd["debt"][0], "자료가 부족해 판단을 미룹니다.")
    if vd["debt"][0] in ("good", "warn") and vd["streak"] >= 2:
        answer += " 다만 영업현금흐름이 마이너스라 모자란 현금을 빌려서 메우고 있어, 빚은 늘고 있습니다."
    lead = ""
    if cov is not None:
        lead = f"최근 4개 분기({ttm_span(v)}) 영업이익은 이자비용의 **{pct(cov)}배**입니다(이자보상배율, 1배 미만이면 이익으로 이자도 못 냄). "
    if nd is not None:
        if nd > 0:
            lead += f"{when_label(bal)} 순차입금(이자부차입금 − 현금)은 **{jo(nd, 2)}조 원**"
            lead += f"으로 1년 EBITDA의 {nde:.1f}배입니다." if nde is not None else "입니다."
        else:
            lead += f"{when_label(bal)} 현금이 이자부차입금보다 {jo(-nd, 2)}조 원 많은 **순현금** 상태입니다."
    more = []
    debts = [(t, v.a(t, "debt_to_equity_pct")) for t in v.years if v.a(t, "debt_to_equity_pct") is not None]
    if debts:
        lowest = min(debts, key=lambda x: x[1])
        more.append(f"부채비율은 {lowest[0]}년 말 {pct(lowest[1], 0)}%(가장 낮았던 해)에서 {when_label(bal)} **{pct(br.get('debt_to_equity_pct'), 0)}%**가 "
                    f"됐습니다. 자기 돈 100원당 남의 돈이 {pct(lowest[1], 0)}원에서 {pct(br.get('debt_to_equity_pct'), 0)}원으로 늘었다는 뜻입니다.")
    if br.get("current_ratio_pct") is not None:
        text = f"유동비율은 **{pct(br['current_ratio_pct'], 0)}%**"
        if br.get("quick_ratio_pct") is not None:
            text += f", 재고를 뺀 당좌비율은 {pct(br['quick_ratio_pct'], 0)}%"
        text += "입니다. " + ("1년 안에 갚을 돈보다 1년 안에 현금으로 바꿀 수 있는 자산이 더 많습니다." if br["current_ratio_pct"] >= 100
                            else "1년 안에 갚을 돈이 1년 안에 현금으로 바꿀 수 있는 자산보다 많습니다.")
        more.append(text)
    if bv.get("borrowings_total") is not None:
        borrows = [v.a(t, "borrowings_total") for t in v.years if v.a(t, "borrowings_total") is not None]
        text = (f"이자부차입금 {jo(bv['borrowings_total'], 2)}조 원, 현금및현금성자산 {jo(bv.get('cash'), 2)}조 원"
                + (f", 차입금의존도 {pct(br.get('borrowing_dependency_pct'))}%" if br.get("borrowing_dependency_pct") is not None else "") + "입니다.")
        if borrows and bv["borrowings_total"] >= max(borrows):
            text += " 차입금은 연말 기준 어느 해보다 많습니다."
        more.append(text)
    rate_year = v.last_with("borrowing_rate_pct")
    if rate_year:
        more.append(f"{rate_year}년 이자비용을 평균 차입금으로 나눈 차입 이자율은 약 {pct(v.a(rate_year, 'borrowing_rate_pct'))}%입니다.")
    if bv.get("advances_total") and bv.get("liabilities") and bv.get("borrowings_total"):
        more.append(f"건설사 부채에는 공사보다 먼저 받은 돈(초과청구공사·선수금)처럼 이자가 붙지 않는 부채가 많습니다. "
                    f"부채 {jo(bv['liabilities'], 2)}조 원 중 {jo(bv['advances_total'], 2)}조 원({bv['advances_total'] / bv['liabilities'] * 100:.0f}%)이 "
                    f"이런 돈이고, 이자가 붙는 차입금은 {jo(bv['borrowings_total'], 2)}조 원({bv['borrowings_total'] / bv['liabilities'] * 100:.0f}%)입니다. "
                    f"그래서 가이드도 부채비율보다 상환능력(이자보상배율·순차입금/EBITDA)을 먼저 보라고 합니다.")
    return {"id": "debt", "no": 4, "en": "Debt burden", "ko": "차입 부담", "q": "번 돈으로 이자와 빚을 감당할 수 있나?",
            "answer": answer, "lead": lead, "more": more}


def _returns_step(v, vd):
    ry, roic = vd["roic_year"], vd["roic"]
    if roic is None:
        return {"id": "returns", "no": 5, "en": "Returns", "ko": "투자수익률", "q": "투입한 자본으로 충분히 벌고 있나?",
                "answer": "ROIC를 계산할 자료가 부족합니다.", "lead": "", "more": []}
    atr = vd["after_tax_rate"]
    if vd["returns"][0] == "crit":
        answer = f"{ry}년 ROIC {pct(roic)}%로, 빌린 돈의 세후 이자율({pct(atr)}%)도 벌지 못했습니다."
    elif vd["returns"][0] == "warn":
        answer = (f"{ry}년 ROIC {pct(roic)}%로 빌린 돈의 세후 이자율({pct(atr)}%)보다는 높지만, "
                  f"단순 기준 {HURDLE_ROIC:.0f}%에는 못 미칩니다." if atr is not None else
                  f"{ry}년 ROIC {pct(roic)}%로 단순 기준 {HURDLE_ROIC:.0f}%에 못 미칩니다.")
    else:
        answer = f"{ry}년 ROIC {pct(roic)}%로 단순 기준 {HURDLE_ROIC:.0f}%를 넘었습니다."
    ys = [t for t in v.years if v.a(t, "roic_pct") is not None]
    best = max(ys, key=lambda t: v.a(t, "roic_pct"))
    worst = min(ys, key=lambda t: v.a(t, "roic_pct"))
    lead = (f"ROIC(세후 영업이익 ÷ 평균 투하자본)는 가장 좋았던 {best}년 {pct(v.a(best, 'roic_pct'))}%, "
            f"가장 나빴던 {worst}년 {pct(v.a(worst, 'roic_pct'))}%였습니다. 투하자본은 자본총계 + 순차입금입니다.")
    more = []
    roe, roa = v.a(ry, "roe_pct"), v.a(ry, "roa_pct")
    if roe is not None and roa is not None:
        text = f"{ry}년 ROE는 {pct(roe)}%, ROA는 {pct(roa)}%입니다."
        if roa > 0:
            text += (f" ROE가 ROA의 {roe / roa:.1f}배인 것은 빚의 지렛대 효과(부채비율 {pct(v.a(ry, 'debt_to_equity_pct'), 0)}%) 때문입니다. "
                     "가이드는 ROE가 부채로 부풀 수 있으니 ROIC를 중심에 두라고 합니다.")
        more.append(text)
    owners = v.a(ry, "roe_owners_pct")
    if owners is not None:
        more.append(f"비지배지분을 뺀 지배주주 기준 ROE(지배주주 순이익 ÷ 평균 지배주주지분)는 {pct(owners)}%입니다.")
    roes = [(t, v.a(t, "roe_pct")) for t in v.years if v.a(t, "roe_pct") is not None]
    if roes:
        b = max(roes, key=lambda x: x[1])
        more.append(f"주주 돈 100원으로 1년에 번 순이익(ROE)이 가장 많았던 해는 {b[0]}년({pct(b[1])}원)입니다.")
    return {"id": "returns", "no": 5, "en": "Returns", "ko": "투자수익률", "q": "투입한 자본으로 충분히 벌고 있나?",
            "answer": answer, "lead": lead, "more": more}


def _valuation_step(v, vd, ctx):
    val = ctx.get("valuation") or {}
    base = {"id": "valuation", "no": 6, "en": "Valuation", "ko": "주가 수준", "q": "지금 주가는 이 실적을 어떻게 평가하나?"}
    if not val.get("market_cap"):
        return {**base, "answer": "주가 자료를 아직 받지 못했습니다.",
                "lead": "다음 자동 실행(매월 1일) 때 주가를 받아 PER·PBR·EV/EBITDA·FCF 수익률을 계산합니다.", "more": []}
    pbr, per = val.get("pbr_x"), val.get("per_x")
    if pbr is not None:
        answer = (f"PBR {pbr:.2f}배: 주가가 장부상 순자산(지배주주지분)보다 낮게 거래됩니다." if pbr < 1 else
                  f"PBR {pbr:.2f}배: 주가가 장부상 순자산보다 높게 거래됩니다.")
    else:
        answer = "자본이 0 이하라 PBR을 계산할 수 없습니다."
    lead = (f"{price_when(val)} 주가 {val['price']:,.0f}원 × 발행주식 {val['shares']:,}주 = 시가총액 **{jo(val['market_cap'], 2)}조 원**. "
            + (f"최근 4개 분기 지배주주 순이익 기준 PER **{per:.1f}배**" if per is not None else "최근 4개 분기 지배주주 순이익이 0 이하라 PER은 계산하지 않습니다")
            + (f", EV/EBITDA {val['ev_ebitda_x']:.1f}배" if val.get("ev_ebitda_x") is not None else "")
            + (f", FCF 수익률 {pct(val['fcf_yield_pct'])}%" if val.get("fcf_yield_pct") is not None else "") + ".")
    more = []
    hist = [(t, v.a(t, "pbr_x")) for t in v.years if v.a(t, "pbr_x") is not None]
    if len(hist) >= 2:
        lo, hi = min(hist, key=lambda x: x[1]), max(hist, key=lambda x: x[1])
        more.append(f"연말 주가 기준 PBR은 {hist[0][0]}년 {hist[0][1]:.2f}배 → {hist[-1][0]}년 {hist[-1][1]:.2f}배였고, "
                    f"가장 높았던 해는 {hi[0]}년({hi[1]:.2f}배), 가장 낮았던 해는 {lo[0]}년({lo[1]:.2f}배)입니다.")
    roe = vd["roic"]
    if pbr is not None and pbr < 1:
        more.append("가이드는 ‘낮은 배수를 저평가로 단정하지 말라’고 합니다. ROE·ROIC가 자본비용보다 낮으면 PBR 1배 미만이 오히려 자연스러울 수 있습니다"
                    + (f"(최근 ROIC {pct(roe)}%)." if roe is not None else "."))
    if val.get("fcf_yield_pct") is not None and val["fcf_yield_pct"] < 0:
        more.append("FCF 수익률이 마이너스인 것은 최근 1년 영업현금흐름이 설비투자보다 적었기 때문입니다(투자 후 남는 현금이 없음).")
    peers = [p for p in ctx.get("peers", []) if (p.get("market") or {}).get("pbr_x")]
    own = (ctx.get("own_market") or {}).get("pbr_x")
    if peers and own:
        lower = sum(1 for p in peers if p["market"]["pbr_x"] < own)
        py = max(p.get("year") or 0 for p in peers)
        more.append(f"같은 기준(현재 주가 ÷ {py}년 사업보고서 지배주주지분)으로 동종기업 {len(peers)}곳과 비교하면, "
                    f"현대건설 PBR {own:.2f}배보다 낮은 곳이 {lower}곳입니다(동종기업 표).")
    return {**base, "answer": answer, "lead": lead, "more": more}


def steps(v, vd, ctx):
    """교수님 가이드 4장 '실무 필수 분석 흐름' 순서의 6단계 해설."""
    out = [_growth_step(v, vd), _profit_step(v, vd), _cash_step(v, vd), _debt_step(v, vd), _returns_step(v, vd),
           _valuation_step(v, vd, ctx)]
    keys = ["growth", "profit", "cash", "debt", "returns", "valuation"]
    for s, k in zip(out, keys):
        s["verdict"] = vd[k]
    return out


# 가이드 5장 '지표 조합으로 읽는 실무 신호' (가능한 해석 · 우선 확인할 내용은 가이드 표를 따름)
COMBOS = [
    ("rev_up_margin_down", "매출 증가 + 영업이익률 하락", "가격 인하·원가 상승·저마진 제품 확대 가능성", "판매량과 단가, 제품 믹스, 원재료비"),
    ("ni_up_cfo_down", "순이익 증가 + CFO 감소", "이익의 현금 전환이 약해졌을 가능성", "매출채권·재고·계약자산, 일회성 이익"),
    ("roe_up_debt_up", "ROE 상승 + 부채비율 상승", "레버리지가 ROE를 끌어올렸을 가능성", "ROA, ROIC, 이자보상배율"),
    ("cr_up_qr_flat", "유동비율 상승 + 당좌비율 정체", "유동자산 증가가 재고 중심일 가능성", "DIO, 재고평가손실, 판매 전망"),
    ("fcf_neg_capex_up", "FCF 적자 + CAPEX 급증", "성장투자 단계일 수 있으나 조달 부담 증가", "투자 목적, 가동 시점, 예상 ROIC, 자금계획"),
    ("div_up_profit_down", "배당수익률 상승 + 이익·FCF 감소", "주가 하락과 배당 유지 우려가 함께 반영될 가능성", "배당성향, 순차입금, 차입을 통한 배당 여부"),
    ("rev_up_ccc_up", "매출 증가 + CCC 장기화", "성장 과정에서 운전자본 부담 확대", "DSO·DIO·DPO와 고객·공급업체 조건"),
    ("per_down_roic_down", "PER 하락 + ROIC 하락", "낮은 가격이 사업의 가치 창출력 약화를 반영할 가능성", "정상화 이익, 투자회수, 산업 구조 변화"),
]


def _combo(key, cur, prev):
    """(해당 여부 True/False/None, 숫자 설명)."""
    c, p = cur["values"], prev["values"]
    cr, pr = cur["ratios"], prev["ratios"]

    def need(*vals):
        return all(x is not None for x in vals)

    if key == "rev_up_margin_down":
        g, m1, m0 = cr.get("revenue_growth_pct"), cr.get("operating_margin_pct"), pr.get("operating_margin_pct")
        if not need(g, m1, m0):
            return None, ""
        return g > 0 and m1 < m0, f"매출 {signed(g)}%, 영업이익률 {pct(m0)}% → {pct(m1)}%"
    if key == "ni_up_cfo_down":
        n1, n0, f1, f0 = c.get("net_income"), p.get("net_income"), c.get("operating_cashflow"), p.get("operating_cashflow")
        if not need(n1, n0, f1, f0):
            return None, ""
        return n1 > n0 and f1 < f0, f"순이익 {jo(n0, 2)} → {jo(n1, 2)}조, 영업현금흐름 {jo(f0, 2)} → {jo(f1, 2)}조 원"
    if key == "roe_up_debt_up":
        r1, r0, d1, d0 = cr.get("roe_pct"), pr.get("roe_pct"), cr.get("debt_to_equity_pct"), pr.get("debt_to_equity_pct")
        if not need(r1, r0, d1, d0):
            return None, ""
        return r1 > r0 and d1 > d0, f"ROE {pct(r0)} → {pct(r1)}%, 부채비율 {pct(d0, 0)} → {pct(d1, 0)}%"
    if key == "cr_up_qr_flat":
        c1, c0, q1, q0 = cr.get("current_ratio_pct"), pr.get("current_ratio_pct"), cr.get("quick_ratio_pct"), pr.get("quick_ratio_pct")
        if not need(c1, c0, q1, q0):
            return None, ""
        return (c1 - c0) > 1 and (q1 - q0) < (c1 - c0) / 2, f"유동비율 {pct(c0, 0)} → {pct(c1, 0)}%, 당좌비율 {pct(q0, 0)} → {pct(q1, 0)}%"
    if key == "fcf_neg_capex_up":
        f1, k1, k0 = c.get("fcf"), c.get("capex"), p.get("capex")
        if not need(f1, k1, k0) or k0 <= 0:
            return None, ""
        g = (k1 - k0) / k0 * 100
        return f1 < 0 and g >= 30, f"FCF {jo(f1, 2)}조 원, CAPEX {signed(g, 0)}%"
    if key == "div_up_profit_down":
        return None, "배당 자료를 받지 않아 판단하지 않음"
    if key == "rev_up_ccc_up":
        g, a1, a0 = cr.get("revenue_growth_pct"), cr.get("ccc_days"), pr.get("ccc_days")
        if not need(g, a1, a0):
            return None, ""
        return g > 0 and a1 > a0 + 3, f"매출 {signed(g)}%, CCC {a0:.0f} → {a1:.0f}일"
    if key == "per_down_roic_down":
        e1, e0, r1, r0 = cr.get("per_x"), pr.get("per_x"), cr.get("roic_pct"), pr.get("roic_pct")
        if not need(r1, r0):
            return None, ""
        if not need(e1, e0):
            return None, "PER을 계산할 수 없는 해(적자 또는 주가 없음)"
        return e1 < e0 and r1 < r0, f"PER {e0:.1f} → {e1:.1f}배, ROIC {pct(r0)} → {pct(r1)}%"
    return None, ""


def combos(v):
    if len(v.annual) < 2:
        return []
    pairs = list(zip(v.annual, v.annual[1:]))
    cur, prev = v.annual[-1], v.annual[-2]
    out = []
    for key, name, meaning, check in COMBOS:
        hit, detail = _combo(key, cur, prev)
        years = [b["year"] for a, b in pairs if _combo(key, b, a)[0]]
        out.append({"key": key, "name": name, "hit": hit, "detail": detail, "meaning": meaning, "check": check,
                    "years": years, "basis": f"{prev['year']}→{cur['year']}년"})
    return out


def checklist(ctx, vd):
    """가이드 6장 '실무 검토 체크리스트'를 이 대시보드가 어디까지 반영했는지."""
    lg = ctx.get("legacy") or {}
    val = ctx.get("valuation") or {}
    years = [r["year"] for r in ctx["annual"]]
    span = f"{years[0]}~{years[-1]}년 {len(years)}개 연도, 분기 {len(ctx['quarters'])}개" if years else "자료 없음"
    items = [
        ("기준 통일", "ok", "모두 연결재무제표 · 연간/반기/분기를 따로 표시 · 원자료는 원 단위(표는 억 원)"),
        ("추세 확보", "ok", span),
        ("성장 분해", "part", "판매량·가격·환율 분해는 재무제표 숫자만으로는 불가. 건설업에서 그 역할을 하는 수주잔고·신규 수주·공사별 진행률은 "
                             "사업보고서 본문에서 읽어 기업분석 보고서(PDF) 3장에 반영"),
        ("마진 원인", "ok", "매출 100원 분해(원가·판관비·영업이익), 매출총이익률과 영업이익률 변화 비교"),
        ("이익의 질", "ok", "5년 누적 CFO vs 누적 순이익, 받을 돈, CCC(DSO·DIO·DPO)"),
        ("투자 구분", "part", "CAPEX(유형·무형자산 취득)는 계산하지만 유지·성장 투자 구분은 공시 숫자로 불가"),
        ("부채 상환능력", "part", "이자보상배율, 순차입금/EBITDA, 차입 이자율. 만기 구조·변동금리 비중은 반영하지 않음"),
        ("자본 효율", "part", f"ROIC 계산. WACC 대신 세후 차입 이자율과 단순 기준 {HURDLE_ROIC:.0f}%로 비교, ROE의 레버리지 영향 설명"),
        ("가치평가", "ok" if val.get("market_cap") else "part",
         "PER·PBR·EV/EBITDA·FCF 수익률, 동종기업 PER·PBR" if val.get("market_cap") else "주가를 받은 뒤 PER·PBR 등을 계산(다음 자동 실행)"),
        ("공시 검증", "ok", "모든 기간에 DART 원문 링크" + (f", 원문 추출값과 API 대조 {lg['matched']}/{lg['checked']} 일치"
                                                   if lg.get("checked") else "")),
    ]
    return [{"item": a, "status": b, "how": c} for a, b, c in items]


def acts(v):
    """시기별 흐름. 연도 구간과 배경은 기사로 확인한 해석이고, 숫자는 표에서 계산합니다."""
    items = []
    A = v.a

    def rng(years, key, d=1, fmt=jo):
        vals = [A(t, key) for t in years if A(t, key) is not None]
        return (fmt(min(vals), d), fmt(max(vals), d)) if vals else ("–", "–")

    if v.has(2010, 2015):
        span = range(2010, 2016)
        lo, hi = rng(span, "operating_margin_pct", fmt=pct)
        items.append({"years": "2010–2015", "title": "1막 · 그룹 편입과 몸집 키우기",
                      "facts": [f"매출 {jo(A(2010, 'revenue'))}조 → {jo(A(2015, 'revenue'))}조 원 ({A(2015, 'revenue') / A(2010, 'revenue'):.2f}배)",
                                f"2014년 매출 {signed(A(2014, 'revenue_growth_pct'))}%",
                                f"영업이익률 {lo}~{hi}%",
                                f"부채비율 {pct(A(2010, 'debt_to_equity_pct'), 0)}% → {pct(A(2015, 'debt_to_equity_pct'), 0)}%"],
                      "why": ("2011년 현대차그룹 계열사가 됐습니다. 2014년 4월에는 연결 자회사 현대엔지니어링이 현대엠코를 흡수합병해, "
                              "그해 연결 매출이 크게 늘었습니다.", ["mt2011", "sat2014"])})
    if v.has(*range(2016, 2022)):
        span = range(2016, 2022)
        lo, hi = rng(span, "revenue")
        mlo, mhi = rng(span, "operating_margin_pct", fmt=pct)
        cfs = [A(t, "operating_cashflow") for t in span]
        pos = sum(1 for c in cfs if c is not None and c > 0)
        drop = fin.growth(A(2020, "operating_profit"), A(2019, "operating_profit"))
        items.append({"years": "2016–2021", "title": "2막 · 조용한 안정기",
                      "facts": [f"매출 {lo}~{hi}조 원에서 제자리", f"영업이익률 {mlo}~{mhi}%",
                                (f"영업현금흐름 6년 모두 플러스 (합계 {jo(sum(cfs))}조 원)" if pos == 6 else f"영업현금흐름 {pos}/6년 플러스"),
                                f"부채비율 {pct(A(2016, 'debt_to_equity_pct'), 0)}% → {pct(A(2021, 'debt_to_equity_pct'), 0)}%"],
                      "why": (f"2020년 영업이익이 {pct(abs(drop or 0), 0)}% 줄었습니다. 코로나19로 멈추거나 늦어진 해외 현장의 비용을 미리 "
                              "손실로 잡았기 때문입니다.", ["inews24"])})
    if v.has(2021, 2022, 2023):
        c22, c23 = A(2022, "operating_cashflow"), A(2023, "operating_cashflow")
        items.append({"years": "2022–2023", "title": "3막 · 해외 대형 현장으로 급성장",
                      "facts": [f"매출 {jo(A(2022, 'revenue'))}조 → {jo(A(2023, 'revenue'))}조 원 (2023년 {signed(A(2023, 'revenue_growth_pct'))}%)",
                                f"원가율 {pct(v.per100(2021, 'cost_of_sales'))}% → {pct(v.per100(2023, 'cost_of_sales'))}%",
                                (f"영업현금흐름 마이너스로 돌아섬 ({jo(c22, 2)}조, {jo(c23, 2)}조 원)" if c22 < 0 and c23 < 0
                                 else f"영업현금흐름 {jo(c22, 2)}조, {jo(c23, 2)}조 원"),
                                f"받을 돈 {jo(A(2021, 'receivables_total'))}조 → {jo(A(2023, 'receivables_total'))}조 원"],
                      "why": ("2022년엔 자재값과 환율이 급등해 이익이 줄었습니다. 2023년엔 사우디 자푸라 가스전, 네옴 러닝터널, 이라크 바스라 "
                              "정유공장 같은 해외 대형 현장과 국내 샤힌 프로젝트 공사가 본격화되며 매출이 급증했습니다.", ["tomato", "hankyung"])})
    if v.has(2023, 2024):
        c24 = v.per100(2024, "cost_of_sales")
        revs = [x for x in v.series("revenue") if x is not None]
        items.append({"years": "2024", "title": "4막 · 적자 충격",
                      "facts": [f"매출 {jo(A(2024, 'revenue'))}조 원" + (" (사상 최대)" if A(2024, "revenue") >= max(revs) else ""),
                                f"원가율 {pct(c24)}%" + (" (원가가 매출보다 큼)" if c24 and c24 > 100 else ""),
                                f"영업손실 {won(abs(A(2024, 'operating_profit')))} 원",
                                f"부채비율 {pct(A(2023, 'debt_to_equity_pct'), 0)}% → {pct(A(2024, 'debt_to_equity_pct'), 0)}%"],
                      "why": ("연결 자회사 현대엔지니어링이 인도네시아 발릭파판 정유공장, 사우디 자푸라 가스전 현장에서 앞으로 들 비용까지 "
                              "한꺼번에 손실로 반영했습니다. 언론은 23년 만의 연간 적자로 보도했습니다.", ["newsis"])})
    if v.has(2024, 2025):
        facts = [f"2025년 영업이익 {won(A(2025, 'operating_profit'))} 원으로 흑자 전환",
                 f"원가율 {pct(v.per100(2025, 'cost_of_sales'))}%로 개선",
                 f"2025년 영업현금흐름 {jo(A(2025, 'operating_cashflow'), 2)}조 원"]
        h1 = next((h for h in reversed(v.halves) if h["kind"] == "H1" and h["year"] > 2025), None)
        title_years = "2025–"
        if h1:
            hv = h1["values"]
            prev = next((h for h in v.halves if h["kind"] == "H1" and h["year"] == h1["year"] - 1), None)
            g = fin.growth(hv.get("revenue"), prev["values"].get("revenue")) if prev else None
            facts.append(f"{h1['year']}년 상반기 매출 {jo(hv.get('revenue'))}조 원" + (f" ({signed(g)}%)" if g is not None else "")
                         + f", 영업현금흐름 {jo(hv.get('operating_cashflow'), 2)}조 원")
            title_years = f"2025–{h1['year']}"
        items.append({"years": title_years, "title": "5막 · 흑자 회복, 현금은 숙제",
                      "facts": facts,
                      "why": ("전년의 일회성 비용이 빠지고 공정 관리와 선별 수주로 흑자로 돌아섰습니다. 반면 샤힌 프로젝트, 사우디 아미랄 같은 "
                              "대형 현장이 진행되면서 매출채권이 늘어 현금흐름은 나빠졌습니다.", ["ceoscore"])})
    return items


def cash_signals(v):
    meaning = {
        (1, -1, -1): "벌어서 투자·상환", (1, 0, -1): "벌어서 상환·배당", (1, -1, 0): "벌어서 투자",
        (1, -1, 1): "벌고 빌려서 투자", (1, 1, -1): "벌고 회수해서 상환", (1, 0, 0): "벌어서 현금 쌓기", (1, 1, 0): "벌어서 현금 쌓기",
        (1, 0, 1): "벌고 빌려서 현금 쌓기",
        (-1, 1, -1): "모아둔 돈 꺼내 버팀", (-1, 1, 0): "모아둔 돈 꺼내 버팀",
        (-1, 1, 1): "꺼내고 빌려서 버팀", (-1, 0, 1): "빌려서 버팀", (-1, -1, 1): "빌려서 버팀",
        (0, -1, 1): "빌려서 투자", (0, -1, 0): "모아둔 돈으로 투자", (0, -1, -1): "모아둔 돈으로 투자·상환",
        (0, 1, -1): "회수해서 상환", (0, 0, 1): "빌려서 현금 쌓기", (0, 0, -1): "모아둔 돈으로 상환",
    }
    small = 0.05 * T

    def sign(x):
        if x is None:
            return None
        return 0 if abs(x) < small else (1 if x > 0 else -1)

    rows = []
    for t in v.years:
        vals = [v.a(t, k) for k in ("operating_cashflow", "investing_cashflow", "financing_cashflow")]
        key = tuple(sign(x) for x in vals)
        if None in key:
            label = "자료 부족"
        elif key in meaning:
            label = meaning[key]
        elif key[0] == -1:
            label = "현금 잔고로 버팀"
        else:
            label = "현금이 늘어남" if sum(vals) > 0 else "현금이 줄어듦"
        rows.append({"year": t, "values": vals, "signs": key, "label": label})
    return rows


def figure_notes(v, vd):
    notes = {}
    first, last = v.annual[0], v.annual[-1]
    notes["revenue"] = (f"막대 하나가 1년 매출입니다. {first['year']}년 {jo(first['values']['revenue'])}조 원에서 "
                        f"{last['year']}년 {jo(last['values']['revenue'])}조 원이 됐습니다.")
    loss = [str(t) for t in v.years if (v.per100(t, "operating_profit") or 0) < 0]
    notes["per100"] = "막대 끝 초록 부분이 남는 돈입니다." + (
        f" {'·'.join(loss)}년 막대는 점선(매출 100원)을 넘어갔습니다. 넘어간 만큼이 손실입니다." if loss else "")
    streak = vd["streak"]
    if streak:
        a = last["year"] - streak + 1
        notes["cash"] = f"{a}년부터 현금 막대(주황)가 0 아래에 머뭅니다. 이익(초록)과 현금이 갈라지는 지점을 보세요."
    else:
        notes["cash"] = "두 막대가 함께 위에 있으면 이익이 현금으로도 들어온 해입니다."
    q = v.quarters[-12:]
    if q:
        notes["quarters"] = f"최근 12개 분기({q[0]['year']}년 {q[0]['kind'][1]}분기~{q[-1]['year']}년 {q[-1]['kind'][1]}분기)의 분기별 실적입니다."
    return notes


def to_plain(obj):
    if isinstance(obj, str):
        return obj.replace("**", "")
    if isinstance(obj, list):
        return [to_plain(x) for x in obj]
    if isinstance(obj, dict):
        return {k: to_plain(x) for k, x in obj.items() if k != "row"}
    return obj


STEP_KEYS = ("growth", "profit", "cash", "debt", "returns", "valuation")


def analyze(ctx):
    v = View(ctx)
    if not v.annual:
        return {"verdicts": {}, "headline": "아직 수집된 숫자가 없습니다.", "update": update_box(ctx), "latest": None,
                "steps": [], "acts": [], "signals": [], "combos": [], "checklist": [], "notes": {}, "rules": VERDICT_RULES,
                "sources": SOURCES, "plain": {}}
    vd = verdicts(v)
    out = {
        "verdicts": vd, "headline": headline(v, vd), "update": update_box(ctx), "latest": latest_quarter(v),
        "steps": steps(v, vd, ctx), "acts": acts(v), "signals": cash_signals(v), "combos": combos(v),
        "checklist": checklist(ctx, vd), "notes": figure_notes(v, vd), "rules": VERDICT_RULES, "sources": SOURCES,
    }
    out["plain"] = to_plain({"headline": out["headline"], "latest": out["latest"], "steps": out["steps"],
                             "combos": out["combos"], "verdicts": {k: vd[k] for k in STEP_KEYS}})
    return out
