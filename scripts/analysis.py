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

    def ttm_quarters(self):
        return fin.ttm(self.quarters, "revenue")[1] or []

    def latest_balance(self):
        """가장 최근 분기말 재무상태표가 있는 행."""
        for q in reversed(self.ctx["quarters"]):
            if q["values"].get("assets") is not None:
                return q
        return self.annual[-1] if self.annual else None


def neg_streak(values):
    n = 0
    for v in reversed(values):
        if v is None or v >= 0:
            break
        n += 1
    return n


def verdicts(v):
    first, last = v.annual[0], v.annual[-1]
    span = last["year"] - first["year"]
    cagr = None
    if span > 0 and first["values"]["revenue"] > 0 and last["values"]["revenue"] > 0:
        cagr = ((last["values"]["revenue"] / first["values"]["revenue"]) ** (1 / span) - 1) * 100
    growth = ("warn", "확인 필요") if cagr is None else ("good", "성장") if cagr >= 3 else ("warn", "정체") if cagr >= 0 else ("crit", "축소")
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
    streak = neg_streak(v.series("operating_cashflow"))
    cash = ("crit", "경고") if streak >= 2 else ("warn", "주의") if streak == 1 else ("good", "양호")
    bal = v.latest_balance()
    debt = bal["ratios"]["debt_to_equity_pct"] if bal else None
    cur = bal["ratios"]["current_ratio_pct"] if bal else None
    if debt is None or cur is None:
        stab = ("warn", "확인 필요")
    elif debt > 200 or cur < 100:
        stab = ("crit", "위험")
    elif debt > 150 or cur < 120:
        stab = ("warn", "주의")
    else:
        stab = ("good", "양호")
    return {"growth": growth, "profit": profit, "cash": cash, "stability": stab, "cagr": cagr,
            "margin_now": m_now, "margin_first": m0, "streak": streak, "balance_row": bal}


VERDICT_RULES = [
    "성장성: 연간 매출의 연평균 성장률(CAGR)이 3% 이상이면 ‘성장’, 0~3%면 ‘정체’, 0% 미만이면 ‘축소’.",
    "수익성: 최근 4개 분기 영업이익률이 0% 미만이면 ‘적자’, 첫해 영업이익률의 절반에 못 미치면 ‘약해짐’, 그 밖에는 ‘유지’.",
    "현금흐름: 연간 영업활동현금흐름이 최근까지 2년 이상 연속 마이너스면 ‘경고’, 1년만 마이너스면 ‘주의’, 그 밖에는 ‘양호’.",
    "안정성: 최근 분기말 부채비율 200% 초과 또는 유동비율 100% 미만이면 ‘위험’, 부채비율 150% 초과 또는 유동비율 120% 미만이면 ‘주의’, 그 밖에는 ‘양호’.",
]


# ---------------------------------------------------------------------------
# 문장 만들기
# ---------------------------------------------------------------------------
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
    # 같은 해 누적
    cum = next((h for h in reversed(v.halves) if h["year"] == q["year"] and h["kind"] == "H1"), None) if q["kind"] == "Q2" else None
    cf = (cum or q)["values"].get("operating_cashflow")
    if cum and cf is not None:
        lines.append(f"상반기 누적 영업활동현금흐름은 **{won(cf)} 원**입니다." + (" 이익은 흑자인데 현금은 빠져나갔습니다."
                                                                       if cf < 0 and (cum['values'].get('operating_profit') or 0) > 0 else ""))
    elif cf is not None:
        lines.append(f"이 분기 영업활동현금흐름은 {won(cf)} 원입니다.")
    if qv.get("assets") is not None:
        lines.append(f"{q['month']}월 말 부채비율 **{pct(r.get('debt_to_equity_pct'), 0)}%**, 유동비율 {pct(r.get('current_ratio_pct'), 0)}%, "
                     f"받을 돈(매출채권+미청구공사) {jo(qv.get('receivables_total'), 2)}조 원입니다.")
    return {"title": f"가장 최근 분기: {qname(q)}", "lines": lines, "row": q}


def questions(v, vd):
    out = []
    first, last = v.annual[0], v.annual[-1]
    y0, yl = first["year"], last["year"]
    revs = v.series("revenue")

    # 성장성
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
    ttm_rev = v.ttm("revenue")
    tq = v.ttm_quarters()
    if ttm_rev and tq:
        more.append(f"가장 최근 4개 분기({tq[0]['year']}년 {tq[0]['kind'][1]}분기~{tq[-1]['year']}년 {tq[-1]['kind'][1]}분기) 매출 합계는 "
                    f"**{jo(ttm_rev)}조 원**으로, {yl}년 연간 매출보다 {pct(abs(fin.growth(ttm_rev, last['values']['revenue']) or 0))}% "
                    f"{'많습니다' if ttm_rev >= last['values']['revenue'] else '적습니다'}.")
    out.append({"id": "growth", "en": "Growth", "ko": "성장성", "q": "얼마나 컸나?",
                "answer": f"{y0}년 이후 매출이 {mult:.2f}배가 됐습니다. 연평균 {pct(vd['cagr'])}% 성장입니다.",
                "lead": f"{y0}년 {won(first['values']['revenue'])} 원에서 {yl}년 {won(last['values']['revenue'])} 원이 됐습니다.",
                "more": more})

    # 수익성
    m0, ml = first["ratios"]["operating_margin_pct"], last["ratios"]["operating_margin_pct"]
    loss_years = [t for t in v.years if (v.a(t, "operating_margin_pct") or 0) < 0]
    answer = f"{y0}년엔 {pct(m0)}원, {yl}년엔 {pct(ml)}원이 남았습니다." + "".join(
        f" {t}년엔 {pct(abs(v.a(t, 'operating_margin_pct')))}원 손해였습니다." for t in loss_years)
    more = []
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
    if vd["margin_now"] is not None:
        tq = v.ttm_quarters()
        more.append(f"최근 4개 분기({tq[0]['year']}.{tq[0]['kind'][1]}Q~{tq[-1]['year']}.{tq[-1]['kind'][1]}Q) 영업이익률은 "
                    f"**{pct(vd['margin_now'])}%**입니다." if tq else f"최근 영업이익률은 {pct(vd['margin_now'])}%입니다.")
    roe = [(t, v.a(t, "roe_pct")) for t in v.years if v.a(t, "roe_pct") is not None]
    if roe:
        best = max(roe, key=lambda x: x[1])
        worst = min(roe, key=lambda x: x[1])
        more.append(f"주주 돈 100원으로 1년에 번 순이익(ROE)은 가장 좋았던 {best[0]}년 {pct(best[1])}원, "
                    f"가장 나빴던 {worst[0]}년 {pct(worst[1])}원, {yl}년 {pct(v.a(yl, 'roe_pct'))}원입니다.")
    out.append({"id": "profit", "en": "Profitability", "ko": "수익성", "q": "100원어치 팔아 얼마 남겼나?",
                "answer": answer,
                "lead": "건설업은 매출의 90% 안팎이 공사 원가(자재비·인건비·외주비)입니다. 원가율이 몇 %p만 올라도 남는 돈이 크게 줄어듭니다.",
                "more": more})

    # 현금흐름
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
    base_year = 2021 if v.has(2021) else y0
    r0, rl = v.a(base_year, "receivables_total"), last["values"].get("receivables_total")
    if r0 and rl:
        more.append(f"이유는 ‘받을 돈’입니다. 공사는 했지만 아직 현금으로 받지 못한 금액(매출채권+미청구공사)이 "
                    f"{base_year}년 말 **{jo(r0)}조 원**에서 {yl}년 말 **{jo(rl)}조 원**으로 {rl / r0:.1f}배가 됐습니다.")
    h1 = next((h for h in reversed(v.halves) if h["kind"] == "H1"), None)
    if h1 and h1["year"] > yl and h1["values"].get("operating_cashflow") is not None:
        cf = h1["values"]["operating_cashflow"]
        more.append(f"{h1['year']}년 상반기에도 영업활동현금흐름은 **{won(cf)} 원**이고, 6월 말 받을 돈은 "
                    f"{jo(h1['values'].get('receivables_total'))}조 원입니다.")
    out.append({"id": "cash", "en": "Cash flow", "ko": "현금흐름", "q": "번 돈이 통장에 들어왔나?",
                "answer": answer, "lead": lead, "more": more})

    # 안정성
    debts = [(t, v.a(t, "debt_to_equity_pct")) for t in v.years if v.a(t, "debt_to_equity_pct") is not None]
    lowest = min(debts, key=lambda x: x[1])
    bal = vd["balance_row"]
    br = bal["ratios"]
    answer = {"good": "빚 부담이 크지 않고, 버틸 여력도 충분합니다.",
              "warn": "빚 부담은 커졌지만, 아직 버틸 여력은 남아 있습니다.",
              "crit": "빚 부담이 커져 주의 깊게 봐야 하는 수준입니다."}[vd["stability"][0]]
    when = f"{bal['year']}년 {bal['month']}월" if bal["kind"] != "annual" else f"{bal['year']}년"
    lead = (f"부채비율은 {lowest[0]}년 말 **{pct(lowest[1], 0)}%**(가장 낮았던 해)에서 {when} 말 **{pct(br['debt_to_equity_pct'], 0)}%**가 "
            f"됐습니다. 자기 돈 100원당 남의 돈이 {pct(lowest[1], 0)}원에서 {pct(br['debt_to_equity_pct'], 0)}원으로 늘었다는 뜻입니다.")
    more = []
    bv = bal["values"]
    if br.get("current_ratio_pct") is not None:
        more.append(f"유동비율은 **{pct(br['current_ratio_pct'], 0)}%**입니다. " +
                    ("1년 안에 갚을 돈보다 1년 안에 현금으로 바꿀 수 있는 자산이 더 많습니다." if br["current_ratio_pct"] >= 100
                     else "1년 안에 갚을 돈이 1년 안에 현금으로 바꿀 수 있는 자산보다 많습니다."))
    if bv.get("net_cash") is not None:
        borrows = [v.a(t, "borrowings_total") for t in v.years if v.a(t, "borrowings_total") is not None]
        text = (f"현금성자산 {jo(bv['cash_and_deposits'], 2)}조 원, 차입금 {jo(bv['borrowings_total'], 2)}조 원으로 "
                + (f"**순현금 {jo(bv['net_cash'], 2)}조 원**입니다." if bv["net_cash"] >= 0 else f"**순차입금 {jo(-bv['net_cash'], 2)}조 원**입니다."))
        if borrows and bv["borrowings_total"] >= max(borrows):
            text += " 차입금은 연말 기준 어느 해보다 많습니다."
        more.append(text)
    if bv.get("advances_total") and bv.get("liabilities") and bv.get("borrowings_total"):
        more.append(f"건설사 부채에는 공사보다 먼저 받은 돈(초과청구공사·선수금)처럼 이자가 붙지 않는 부채가 많습니다. "
                    f"부채 {jo(bv['liabilities'], 2)}조 원 중 {jo(bv['advances_total'], 2)}조 원({bv['advances_total'] / bv['liabilities'] * 100:.0f}%)이 "
                    f"이런 돈이고, 이자가 붙는 차입금은 {jo(bv['borrowings_total'], 2)}조 원({bv['borrowings_total'] / bv['liabilities'] * 100:.0f}%)입니다.")
    out.append({"id": "stability", "en": "Stability", "ko": "안정성", "q": "버틸 체력은 있나?",
                "answer": answer, "lead": lead, "more": more})
    return out


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


def analyze(ctx):
    v = View(ctx)
    if not v.annual:
        return {"verdicts": {}, "headline": "아직 수집된 숫자가 없습니다.", "update": update_box(ctx), "latest": None,
                "questions": [], "acts": [], "signals": [], "notes": {}, "rules": VERDICT_RULES, "sources": SOURCES,
                "plain": {}}
    vd = verdicts(v)
    out = {
        "verdicts": vd, "headline": headline(v, vd), "update": update_box(ctx), "latest": latest_quarter(v),
        "questions": questions(v, vd), "acts": acts(v), "signals": cash_signals(v), "notes": figure_notes(v, vd),
        "rules": VERDICT_RULES, "sources": SOURCES,
    }
    out["plain"] = to_plain({"headline": out["headline"], "latest": out["latest"], "questions": out["questions"],
                             "verdicts": {k: vd[k] for k in ("growth", "profit", "cash", "stability")}})
    return out
