"""대시보드(사업보고서 시각화)의 앞부분: 건설사가 돈을 버는 구조 → 사업보고서가 중요한 이유 → 수주·PF → 10가지 관점.

숫자는 모두 ctx(재무제표 표)와 ctx['business'](사업보고서 본문에서 읽은 숫자, business.py)에서 계산합니다.
제도 설명(입찰 방식 등)은 문장으로 고정해 두고, 출처를 함께 적습니다.
"""
import analysis as an
import dashboard as d
import lenses as ln

T = an.T
esc, rich = d.esc, d.rich

# 제도·업계 설명의 출처 (문장은 직접 요약)
REFS = {
    "law159": ("자본시장법 제159조(사업보고서)", "https://korea.legal/wiki/%ec%9e%90%eb%b3%b8%ec%8b%9c%ec%9e%a5%ea%b3%bc-%ea%b8%88%ec%9c%b5%ed%88%ac%ec%9e%90%ec%97%85%ec%97%90-%ea%b4%80%ed%95%9c-%eb%b2%95%eb%a5%a0-%ec%a0%9c159%ec%a1%b0/"),
    "easylaw": ("찾기쉬운 생활법령정보: 종합심사낙찰제", "https://www.easylaw.go.kr/CSP/CnpClsMain.laf?csmSeq=519&ccfNo=2&cciNo=5&cnpClsNo=3"),
    "pps": ("조달청 낙찰자 결정제도", "https://pps.go.kr/kor/sub.do?key=00005"),
    "sbs2026": ("SBS Biz, 2026.7.1 (간이형 종심제 개편)", "https://biz.sbs.co.kr/amp/article/20000320067"),
    "jungbi": ("스마트투데이, 2025.12.1 (도시정비 수주)", "https://www.smarttoday.co.kr/ko-kr/articles/97725"),
    "rank": ("이데일리, 2026.7.30 (시공능력평가)", "https://v.daum.net/v/20260730110336152"),
    "crowe": ("Crowe, 2016.1.29 (건설계약 공시 강화)", "https://www.crowe.com/kr/news/news20160129_kr"),
}


def ref(key):
    name, url = REFS[key]
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(name)} ↗</a>'


def dart(receipt, text):
    return f'<a href="{d.DART_VIEW}{esc(receipt)}" target="_blank" rel="noopener">{esc(text)} ↗</a>'


def period_label(p):
    """'2026.06' → '2026년 6월 말'"""
    y, m = p.split(".")
    return f"{y}년 {int(m)}월 말"


def short_period(p):
    y, m = p.split(".")
    return f"’{y[2:]}.{int(m)}" if m != "12" else y


# ---------------------------------------------------------------------------
# 계산 도우미
# ---------------------------------------------------------------------------
def biz_of(ctx):
    return ctx.get("business") or {}


def backlog_rows(ctx):
    """연말 값(2014~) + 가장 최근 분기 값(연말보다 새 것이면). 표기 기준이 다른 값(flag)은 그대로 두고 그래프에서 비웁니다."""
    rows = biz_of(ctx).get("backlog") or []
    out = [r for r in rows if r["month"] == 12]
    if rows and rows[-1]["month"] != 12:
        out.append(rows[-1])
    return out


def latest_backlog(ctx):
    rows = [r for r in (biz_of(ctx).get("backlog") or []) if not r.get("flag")]
    return rows[-1] if rows else None


def balance_at(ctx, year, month):
    for r in list(ctx["quarters"]) + list(ctx["annual"]):
        if r["year"] == year and r.get("month") == month and r["values"].get("equity") is not None:
            return r
    return None


def ttm_revenue_at(ctx, year, month):
    """그 분기말까지 4개 분기 매출 합계. 연말이면 연간 매출."""
    if month == 12:
        row = next((r for r in ctx["annual"] if r["year"] == year), None)
        if row and row["values"].get("revenue"):
            return row["values"]["revenue"]
    qs = [q for q in ctx["quarters"] if q["values"].get("revenue") is not None]
    ttm = d.rolling_ttm(qs, "revenue")
    for q, s in zip(qs, ttm):
        if q["year"] == year and q.get("month") == month:
            return s
    return None


def pf_rows(ctx):
    pf = biz_of(ctx).get("pf") or {}
    return [(p, pf[p]) for p in sorted(pf)]


def years_of_work(ctx, r):
    rev = ttm_revenue_at(ctx, r["year"], r["month"])
    return None if not rev or not r.get("total") else r["total"] / rev


# ---------------------------------------------------------------------------
# 차트 부품: 누적 세로 막대, 가로 누적 막대
# ---------------------------------------------------------------------------
def stack_chart(xlabels, groups, *, ticks_fmt, tips, height=220, labels=None, wide_bars=False):
    """누적 세로 막대. groups: 묶음 1~2개, 묶음마다 [{'values': [...], 'color': '--s1'}, …]를 아래부터 쌓습니다(양수만).
    labels: {(묶음, 위치): 글자} 막대 위 글자."""
    n, k = len(xlabels), len(groups)
    tops = [sum(seg["values"][i] or 0 for seg in g) for g in groups for i in range(n)]
    lo, hi, ticks = d.axis(tops)
    span = hi - lo
    slots = []
    for i in range(n):
        marks = []
        for j, g in enumerate(groups):
            base = 0.0
            segs = [seg for seg in g if seg["values"][i]]
            for s_i, seg in enumerate(segs):
                v = seg["values"][i]
                h = v / span * 100
                top = " top" if s_i == len(segs) - 1 else ""
                marks.append(f'<i class="bar stk j{j}{top}" style="bottom:{base / span * 100:.3f}%;height:{h:.3f}%;--c:var({seg["color"]})"></i>')
                base += v
            text = (labels or {}).get((j, i))
            if text and base:
                marks.append(f'<b class="vl j{j}" style="bottom:calc({base / span * 100:.3f}% + 4px)">{esc(text)}</b>')
        title, rows, note = tips(i)
        slots.append(f'<div class="slot" style="left:{i / n * 100:.4f}%;width:{100 / n:.4f}%"'
                     f'{d.tip_attr(title, rows, note)}>{"".join(marks)}</div>')
    wb = " wb" if wide_bars else ""
    return (f'<div class="plot cc k{k}{wb}" style="--h:{height}px;--n:{n}">{d._y_axis(lo, hi, ticks, ticks_fmt)}'
            f'<div class="pa">{d._grid(lo, hi, ticks)}{"".join(slots)}</div>{d._xa(xlabels)}</div>')


def hstack(rows, *, scale_max, value_fmt, unit_label=""):
    """가로 누적 막대 목록. rows: [{'label', 'meta', 'segs': [(값, 색, 이름)], 'value', 'tip': (제목, 줄, 메모)}]"""
    out = []
    for r in rows:
        left = 0.0
        segs = []
        for val, color, cls in r["segs"]:
            if not val or val <= 0:
                continue
            w = val / scale_max * 100
            segs.append(f'<i class="hs-seg {cls}" style="left:{left:.3f}%;width:{w:.3f}%;--c:var({color})"></i>')
            left += w
        title, tip_rows, note = r["tip"]
        meta = f'<span class="hs-meta">{esc(r["meta"])}</span>' if r.get("meta") else ""
        out.append(f'<div class="hs-row"{d.tip_attr(title, tip_rows, note)}><span class="hs-l"><b>{esc(r["label"])}</b>{meta}</span>'
                   f'<span class="hs-t">{"".join(segs)}</span><span class="hs-v">{esc(value_fmt(r))}</span></div>')
    unit = f'<p class="hs-unit">{esc(unit_label)}</p>' if unit_label else ""
    return f'<div class="hs">{"".join(out)}</div>{unit}'


# ---------------------------------------------------------------------------
# 1. 건설사가 돈을 버는 구조
# ---------------------------------------------------------------------------
def _flow_steps(ctx, v):
    biz = biz_of(ctx)
    lb = latest_backlog(ctx)
    orders = biz.get("orders") or {}
    oy = max(orders) if orders else None
    ttm_rev, ttm_op, ttm_cos = v.ttm("revenue"), v.ttm("operating_profit"), v.ttm("cost_of_sales")
    ttm_cf = v.ttm("operating_cashflow")
    bal = v.latest_balance()
    pf = pf_rows(ctx)
    lp, lpv = (pf[-1] if pf else (None, None))
    eq_row = balance_at(ctx, int(lp[:4]), int(lp[5:])) if lp else None
    pf_x = (lpv["amount"] / eq_row["values"]["equity"]) if lp and eq_row else None
    rank = ctx["company"].get("rank") or {}
    span = an.ttm_span(v)
    steps = []
    yrs = years_of_work(ctx, lb) if lb else None
    steps.append(("수주", "발주처와 공사 계약", "Ⅱ-4 수주상황",
                  f"{an.jo(lb['total'])}조 원" if lb else "–", f"수주잔고 · {period_label(lb['period'])}" if lb else "수주잔고",
                  (f"{oy}년 새로 딴 공사 {an.jo(orders[oy]['total'])}조 원(현대건설 단독)" if oy else "")))
    steps.append(("공사·매출", "진행한 만큼 매출로 잡음", "Ⅲ 손익계산서",
                  f"{an.jo(ttm_rev)}조 원" if ttm_rev else "–", f"최근 4개 분기 매출 ({span})",
                  f"수주잔고 = 매출 **{yrs:.1f}년 치** 일감" if yrs else ""))
    margin = None if not ttm_rev or ttm_op is None else ttm_op / ttm_rev * 100
    cost = None if not ttm_rev or ttm_cos is None else ttm_cos / ttm_rev * 100
    steps.append(("이익", "매출 − 공사원가 − 판관비", "Ⅲ 주석 '건설계약'",
                  f"{an.pct(margin)}%" if margin is not None else "–", "최근 4개 분기 영업이익률",
                  f"원가율 {an.pct(cost)}% (매출 100원 중 공사원가)" if cost is not None else ""))
    ca = bal["values"].get("contract_assets") if bal else None
    steps.append(("현금", "기성 청구 → 대금 회수", "Ⅲ 현금흐름표·재무상태표",
                  f"{an.jo(ttm_cf, 2)}조 원" if ttm_cf is not None else "–", "최근 4개 분기 영업활동현금흐름",
                  f"미청구공사 {an.jo(ca, 1)}조 원 (공사는 했지만 청구 전)" if ca is not None else ""))
    steps.append(("재무 체력", "빚·보증·신용", "Ⅺ 우발부채(PF 보증)",
                  f"{an.jo(lpv['amount'])}조 원" if lp else "–", f"PF 보증 · {period_label(lp)}" if lp else "PF 보증",
                  (f"자본의 **{pf_x:.1f}배** · 부채비율 {an.pct(bal['ratios'].get('debt_to_equity_pct'), 0)}%"
                   if pf_x and bal else "")))
    steps.append(("다음 수주 자격", "시공능력평가·신용등급", "국토교통부 시공능력평가",
                  f"{rank.get('own')}위" if rank.get("own") else "–", f"{rank.get('year', '')}년 시공능력평가",
                  "실적·재무·기술·신인도로 매긴 체급이 입찰 자격과 보증에 쓰입니다"))
    return steps


def flow_html(steps):
    items = []
    for i, (name, what, where, value, basis, sub) in enumerate(steps, 1):
        sub_html = f'<p class="fl-sub">{rich(sub)}</p>' if sub else ""
        items.append(f'<li class="fl"><p class="fl-top"><span class="fl-no">{i}</span><b>{esc(name)}</b></p>'
                     f'<p class="fl-what">{esc(what)}</p><p class="fl-v">{esc(value)}</p><p class="fl-basis">{esc(basis)}</p>'
                     f'{sub_html}<span class="fl-gap" aria-hidden="true"></span><p class="fl-where">{esc(where)}</p></li>')
    return (f'<ol class="flow" aria-label="건설사가 돈을 버는 순서">{"".join(items)}</ol>'
            '<p class="flow-loop" aria-hidden="true">↺ 재무 체력이 좋아야 다음 공사를 딸 자격이 생기고, 다시 1번(수주)으로 돌아갑니다</p>')


def buyers_html(ctx):
    cards = [
        ("공공공사", "정부·LH·도로공사 등이 점수로 정함",
         ["300억 원 이상은 **종합심사낙찰제**: 공사수행능력(같은 공사 실적·배치 기술자·시공평가) 50점 + 입찰금액 50점, 사회적 책임 가점, 계약 위반 감점",
          "100억~300억 원은 간이형 종심제(가격 60점), 2027년부터 ‘기술형 적격심사’로 바뀔 예정 · 100억 원 미만은 적격심사",
          "설계까지 맡기는 기술형 입찰(턴키 등)은 설계·기술 제안 점수가 큼"],
         f"{ref('easylaw')} · {ref('sbs2026')}"),
        ("재건축·재개발", "조합원 투표로 정함",
         ["아파트 **브랜드**(디에이치·힐스테이트)가 집값에 영향을 준다고 봄",
          "공사비와 계약 조건, 이주비·사업비를 얼마나 싸게 빌려주는지(신용이 좋을수록 유리)",
          "현대건설은 2019~2025년 7년 연속 정비사업 수주 1위, 2025년 10조 원 이상(보도)"],
         ref("jungbi")),
        ("민간·해외", "발주처가 실적·관계·금융을 봄",
         ["공장·데이터센터 같은 민간 공사는 비슷한 시설을 지어 본 실적과 신뢰",
          "해외 플랜트는 흔히 기술평가를 통과한 회사끼리 가격으로 겨룸",
          "자금 조달 능력, 기술 보유사(라이선서)·정부와의 협력(UAE 원전은 한국전력이 발주처)"],
         ""),
    ]
    out = []
    for title, who, bullets, src in cards:
        lis = "".join(f"<li>{rich(b)}</li>" for b in bullets)
        src_html = f'<p class="card-foot">출처: {src}</p>' if src else ""
        out.append(f'<article class="card buyer"><h3>{esc(title)}</h3><p class="buyer-who">{esc(who)}</p><ul class="plain">{lis}</ul>{src_html}</article>')
    return f'<div class="grid-3 buyers">{"".join(out)}</div>'


def market_html(ctx):
    mk = biz_of(ctx).get("market")
    if not mk or not mk.get("total"):
        return ""
    rows = []
    if mk.get("public") and mk.get("private"):
        rows.append(("발주자", [(mk["public"], "--s3", "공공"), (mk["private"], "--s2", "민간")]))
    if mk.get("civil") and mk.get("building"):
        rows.append(("공종", [(mk["civil"], "--s1", "토목"), (mk["building"], "--s4", "건축")]))
    if not rows:
        return ""
    total = mk["total"]
    bars = []
    for name, segs in rows:
        s_total = sum(x[0] for x in segs)
        left = 0.0
        parts = []
        for val, color, lab in segs:
            w = val / s_total * 100
            parts.append(f'<i class="mk-seg" style="left:{left:.3f}%;width:{w:.3f}%;--c:var({color})"><span>{esc(lab)} {w:.0f}%</span></i>')
            left += w
        tip = d.tip_attr(f"{mk['year']}년 국내 건설 수주 · {name}",
                         [[lab, f"{an.jo(val)}조 원 ({val / s_total * 100:.1f}%)", f"var({color})"] for val, color, lab in segs],
                         "대한건설협회 집계를 현대건설 사업보고서가 인용" + (" · 잠정치" if mk.get("provisional") else ""))
        bars.append(f'<div class="mk-row"{tip}><span class="mk-l">{esc(name)}</span><span class="mk-t">{"".join(parts)}</span></div>')
    head = (f"{mk['year']}년 국내 건설 수주 **{an.jo(total)}조 원**" + (" (잠정치)" if mk.get("provisional") else "")
            + (f" · 해외 수주 {mk['overseas_usd_100m']:,}억 달러" if mk.get("overseas_usd_100m") else ""))
    return (f'<figure class="chart mk" id="fig-market"><figcaption class="chart-head"><h3>국내 건설 시장은 누가 발주하나</h3>'
            f'<p>{rich(head)} · 출처: 현대건설 사업보고서(대한건설협회 자료) {dart(mk["receipt"], mk["report"])}</p></figcaption>'
            f'<div class="mk-bars">{"".join(bars)}</div>'
            f'<p class="chart-note">공공 발주는 국내 시장의 3분의 1이 안 됩니다. 그래서 종합심사낙찰제 점수만큼이나 재건축 조합원 투표, 민간·해외 발주처의 선택이 중요합니다.</p></figure>')


def segments_fig(ctx):
    seg = biz_of(ctx).get("segments")
    if not seg or not seg.get("rows"):
        return ""
    year = seg["year"]
    labels = [f"{year - i}년" for i in range(len(seg["periods"]))]
    rows = []
    for r in seg["rows"]:
        dom, ovs = (r["domestic"] or [None])[0], (r["overseas"] or [None])[0]
        rows.append((r, dom or 0, ovs or 0))
    rows.sort(key=lambda x: -(x[1] + x[2]))
    sub = sum(x[1] + x[2] for x in rows)
    scale = max(x[1] + x[2] for x in rows) or 1
    items = []
    for r, dom, ovs in rows:
        tot = dom + ovs
        items.append({"label": r["segment"], "meta": r["products"][:40],
                      "segs": [(dom, "--s1", "dom"), (ovs, "--s3", "ovs")], "value": tot,
                      "tip": (f"{year}년 {r['segment']}", [["국내", f"{an.jo(dom, 2)}조 원", "var(--s1)"],
                                                         ["해외", f"{an.jo(ovs, 2)}조 원", "var(--s3)"],
                                                         ["합계", f"{an.jo(tot, 2)}조 원 (매출의 {tot / sub * 100:.1f}%)", None]],
                              r["products"])})
    body = hstack(items, scale_max=scale, value_fmt=lambda r: f"{an.jo(r['value'])}조 · {r['value'] / sub * 100:.0f}%",
                  unit_label="단위: 조 원 · 부문 사이 내부거래를 빼기 전 금액")
    dom_all = sum(x[1] for x in rows)
    table_rows = []
    for r, _, _ in rows:
        cells = [r["segment"]]
        for i in range(len(labels)):
            dv = (r["domestic"] or [None] * 3)[i]
            ov = (r["overseas"] or [None] * 3)[i]
            cells += [(d.eok(dv), dv), (d.eok(ov), ov)]
        table_rows.append(cells)
    heads = ["사업부문"] + [f"{lab} {k}(억 원)" for lab in labels for k in ("국내", "해외")]
    note = (f"{year}년 매출의 **{(sub - dom_all) / sub * 100:.0f}%**가 해외입니다. 이름은 ‘건설’이지만 토목은 매출의 일부이고, "
            "가장 큰 몫은 건축·주택(아파트·데이터센터)과 플랜트·원전입니다.")
    return d.figure("fig-segments", f"현대건설은 어디서 매출을 내나 ({year}년)",
                    f"사업부문별 매출 · 국내·해외 · 출처: {seg['report']}", body,
                    legend_html=d.legend([("국내", "--s1", "box"), ("해외", "--s3", "box")]),
                    table_html=d.data_table(heads, table_rows), note=note, wide=True)


def structure_section(ctx, v):
    steps = _flow_steps(ctx, v)
    head = d.section_head("structure", "Business model", "돈 버는 구조", "건설사는 이렇게 돈을 법니다",
                          "건설사는 물건을 먼저 만들어 파는 회사가 아닙니다. **공사를 먼저 따내고(수주), 몇 년에 걸쳐 지으면서 진행한 만큼 매출로 잡고, "
                          "공사비를 받아 현금을 회수하는** 수주산업입니다. 그래서 돈이 들어오는 길이 아래처럼 한 바퀴로 이어집니다.",
                          "카드의 숫자는 현대건설의 가장 최근 공시에서 매월 자동으로 다시 계산합니다. 맨 아래 작은 글씨는 그 숫자가 사업보고서의 어디에 있는지입니다.")
    buyers = ('<div class="sub-head"><h3>누가 어떻게 공사를 맡기나</h3><p>공사를 따내는 기준은 발주처마다 다릅니다. '
              '공공은 점수, 재건축은 조합원 투표, 민간·해외는 실적과 신뢰로 정해집니다.</p></div>')
    return (f'<section id="structure" aria-labelledby="h-structure">{head}{flow_html(steps)}{buyers}{buyers_html(ctx)}'
            f'<div class="stack" style="margin-top:14px">{market_html(ctx)}{segments_fig(ctx)}</div></section>')


# ---------------------------------------------------------------------------
# 2. 그래서 사업보고서가 중요하다
# ---------------------------------------------------------------------------
CHAPTERS = [
    ("Ⅰ", "회사의 개요", "연혁, 주식 수", False),
    ("Ⅱ", "사업의 내용", "사업부문, 수주상황(수주잔고·공사별 진행), 원자재 가격, 국내 건설시장", True),
    ("Ⅲ", "재무에 관한 사항", "재무제표와 주석: 원가 추정 변경, 미청구공사, 차입금", True),
    ("Ⅳ", "이사의 경영진단 및 분석의견", "경영진이 직접 설명하는 실적 원인", False),
    ("Ⅴ", "회계감사인의 감사의견 등", "감사의견(적정 여부), 핵심감사사항", False),
    ("Ⅵ~Ⅶ", "이사회·주주", "지배구조, 최대주주(현대자동차)", False),
    ("Ⅷ", "임원 및 직원 등", "직원 수·급여 → 생산성", True),
    ("Ⅸ~Ⅹ", "계열회사, 대주주와의 거래", "그룹 내 공사(GBC 등)", False),
    ("Ⅺ", "그 밖에 투자자 보호를 위하여 필요한 사항", "우발부채: PF 보증·책임준공 약정, 소송", True),
    ("Ⅻ", "상세표", "종속회사 목록", False),
]


def why_rows(ctx, v):
    lb = latest_backlog(ctx)
    yrs = years_of_work(ctx, lb) if lb else None
    cost_now = v.a(v.years[-1], "cost_ratio_pct") if v.years else None
    worst = None
    for t in v.years:
        c = v.a(t, "cost_ratio_pct")
        if c is not None and (worst is None or c > worst[1]):
            worst = (t, c)
    bal = v.latest_balance()
    vd = ctx["analysis"]["verdicts"]
    pf = pf_rows(ctx)
    rank = ctx["company"].get("rank") or {}
    rows = [
        ("수주", "Ⅱ. 사업의 내용 > 매출 및 수주상황",
         f"수주잔고 {an.jo(lb['total'])}조 원 · 매출 {yrs:.1f}년 치" if lb and yrs else "–",
         "잔고가 줄면 2~3년 뒤 매출이 줄어듭니다. 국내·해외, 공사별 진행률까지 나옵니다."),
        ("수주의 질", "Ⅲ. 손익계산서 원가율 · 주석 ‘건설계약’(원가 추정 변경)",
         (f"원가율 {v.years[-1]}년 {an.pct(cost_now)}%" + (f" (최고 {worst[0]}년 {an.pct(worst[1])}%)" if worst else "")) if cost_now else "–",
         "원가율이 오르면 싸게 따낸 공사거나 공사비가 예상보다 늘어난 것입니다. 손실이 예상되면 미리 반영합니다."),
        ("공사 진행·현금", "Ⅲ. 재무상태표 미청구공사·매출채권 · 현금흐름표",
         (f"미청구공사 {an.jo(bal['values'].get('contract_assets'))}조 원 · 영업현금흐름 "
          + (f"{vd['streak']}년 연속 마이너스" if vd.get("streak") else "플러스")) if bal else "–",
         "이익은 났는데 현금이 안 들어오면, 공사비를 못 받고 있거나 미리 쓴 돈이 많다는 뜻입니다."),
        ("재무 체력", "Ⅺ. 우발부채(PF 보증·책임준공) · Ⅲ. 차입금",
         (f"PF 보증 {an.jo(pf[-1][1]['amount'])}조 원 ({period_label(pf[-1][0])})" if pf else "–"),
         "보증은 지금은 빚이 아니지만, 사업장이 잘못되면 건설사 빚이 됩니다. 재무제표 본문에는 안 나옵니다."),
        ("다음 수주 자격", "Ⅲ. 재무제표 → 신용등급·시공능력평가(경영평가)",
         f"{rank.get('year', '')}년 시공능력평가 {rank.get('own', '–')}위" if rank else "–",
         "재무제표가 나빠지면 신용등급이 내려가고, 입찰 자격·보증·재건축 금융 조건이 모두 불리해집니다."),
    ]
    return rows


def why_section(ctx, v):
    head = d.section_head("why", "Why the report", "사업보고서가 중요한 이유", "그래서 사업보고서를 봅니다",
                          "재무제표(Ⅲ장)는 위 순환의 **결과**만 보여 줍니다. 결과를 만든 **원인**, 즉 얼마나 따냈고(수주) 공사가 어디까지 왔고 "
                          "어떤 보증을 섰는지는 Ⅱ장(사업의 내용)과 Ⅺ장(우발부채)에 있습니다. 그래서 숫자 하나를 보더라도 "
                          "사업보고서 전체에서 그 원인을 같이 찾아야 합니다.",
                          "아래 다섯 장의 카드는 돈 버는 단계마다 보고서의 어디를 봐야 하는지와, 그 자리에서 이 화면이 매월 자동으로 읽어 온 현대건설의 지금 숫자입니다.")
    rows = why_rows(ctx, v)
    cards = "".join(f'<article class="card why-card"><p class="why-no">{i}</p><h3>{esc(a)}</h3><p class="why-where">{esc(b)}</p>'
                    f'<p class="why-now">{esc(c)}</p><p class="why-read">{esc(e)}</p></article>'
                    for i, (a, b, c, e) in enumerate(rows, 1))
    table = f'<div class="why-cards" role="list" aria-label="돈 버는 단계별로 사업보고서에서 볼 곳">{cards}</div>'
    lf = ctx.get("latest_filing")
    chap = "".join(f'<li class="{"on" if on else ""}"><span class="ch-no">{esc(no)}</span><span class="ch-t"><b>{esc(t)}</b>'
                   f'<span>{esc(what)}</span></span></li>' for no, t, what, on in CHAPTERS)
    link = f' · 최근 보고서: {dart(lf["rcept_no"], lf["report_nm"].strip())}' if lf else ""
    chapters = (f'<figure class="chart" id="fig-chapters"><figcaption class="chart-head"><h3>사업보고서 한 권의 구조</h3>'
                f'<p>금융감독원 작성기준의 목차 · 진하게 표시한 장을 이 대시보드가 읽습니다{link}</p></figcaption>'
                f'<ol class="chapters">{chap}</ol>'
                f'<p class="chart-note">건설사 보고서에서 특히 볼 곳: Ⅱ장의 수주상황 표, Ⅲ장 주석의 ‘건설계약’(2016년부터 매출 5% 이상 공사는 공사별 진행률·미청구공사 공개), '
                f'Ⅺ장의 PF 보증. 출처: {ref("law159")} · {ref("crowe")}</p></figure>')
    what = ('<article class="card report-what"><h3>사업보고서란?</h3><ul class="plain">'
            '<li>상장회사가 <b>자본시장법 제159조</b>에 따라 1년 동안의 사업과 재무 상태를 투자자에게 알리는 공식 연간 보고서입니다.</li>'
            '<li>사업연도가 끝나고 <b>90일 안에</b> 금융위원회와 한국거래소에 내고, 전자공시시스템(DART)에 공개됩니다. '
            '6개월 치는 반기보고서, 3·9개월 치는 분기보고서로 <b>45일 안에</b> 냅니다(제160조).</li>'
            '<li>회계법인의 <b>감사보고서</b>가 함께 붙어, 재무제표 숫자를 외부에서 한 번 확인받은 자료입니다.</li>'
            '<li>건설업만의 정의가 따로 있지는 않지만, 건설사 보고서는 <b>수주잔고·공사별 진행률·미청구공사·PF 보증</b>이 핵심입니다.</li>'
            f'</ul><p class="card-foot">출처: {ref("law159")}</p></article>')
    return (f'<section id="why" aria-labelledby="h-why">{head}{table}'
            f'<div class="grid-2 why-grid" style="margin-top:14px">{what}{chapters}</div></section>')


# ---------------------------------------------------------------------------
# 3. 수주·PF
# ---------------------------------------------------------------------------
def backlog_fig(ctx):
    rows = backlog_rows(ctx)
    if not rows:
        return ""
    xl = [d.year_label(r["year"]) if r["month"] == 12 else f'<span>{esc(short_period(r["period"]))}</span>' for r in rows]
    dom = [None if r.get("flag") else (r["domestic"] or 0) / T for r in rows]
    ovs = [None if r.get("flag") else (r["overseas"] or 0) / T for r in rows]
    labels = {(0, i): an.jo(r["total"]) for i, r in enumerate(rows) if not r.get("flag") and (i in (0, len(rows) - 1) or r["total"] == max(x["total"] for x in rows if not x.get("flag")))}

    def tips(i):
        r = rows[i]
        tr = [["국내", f"{an.jo(r['domestic'], 2)}조 원", "var(--s1)"], ["해외", f"{an.jo(r['overseas'], 2)}조 원", "var(--s3)"],
              ["합계", f"{an.jo(r['total'], 2)}조 원", None]]
        if r.get("consolidated"):
            tr.append(["연결기준(내부거래 제외)", f"{an.jo(r['consolidated'], 2)}조 원", None])
        note = r.get("flag") or f"{r['report']} · 회사별 계약잔액 합계"
        return period_label(r["period"]), tr, note

    chart = stack_chart(xl, [[{"values": dom, "color": "--s1"}, {"values": ovs, "color": "--s3"}]],
                        ticks_fmt=d.tick_plain, tips=tips, labels=labels)
    table = d.data_table(["기간", "국내(억 원)", "해외(억 원)", "합계(억 원)", "연결기준(억 원)", "비고"],
                         [[period_label(r["period"]), (d.eok(r["domestic"]), None), (d.eok(r["overseas"]), None),
                           (d.eok(r["total"]), None), (d.eok(r.get("consolidated")), None),
                           "표 범위가 달라 그래프 제외" if r.get("flag") else ""] for r in rows])
    flagged = [r for r in rows if r.get("flag")]
    note = ("수주잔고 = 계약은 했지만 아직 짓지 않은 공사 금액. 사업보고서 ‘수주상황’ 표의 회사별(현대건설·현대엔지니어링 등) 국내·해외 계약잔액 합계입니다."
            + (f" {', '.join(period_label(r['period']) for r in flagged)} 값은 앞뒤 보고서와 크게 달라(표에 넣은 공사 범위가 다름) 그래프에서 뺐습니다." if flagged else ""))
    return d.figure("fig-backlog", "수주잔고 (쌓여 있는 일감)", "연말 · 마지막 막대는 가장 최근 분기말 · 단위: 조 원", chart,
                    legend_html=d.legend([("국내", "--s1", "box"), ("해외", "--s3", "box")]), table_html=table, note=note)


def work_years_fig(ctx):
    rows = [r for r in backlog_rows(ctx) if not r.get("flag")]
    vals = [years_of_work(ctx, r) for r in rows]
    if sum(1 for x in vals if x) < 3:
        return ""
    xl = [d.year_label(r["year"]) if r["month"] == 12 else f'<span>{esc(short_period(r["period"]))}</span>' for r in rows]

    def tips(i):
        r = rows[i]
        rev = ttm_revenue_at(ctx, r["year"], r["month"])
        return period_label(r["period"]), [["일감", "–" if vals[i] is None else f"{vals[i]:.1f}년 치", "var(--s2)"],
                                           ["수주잔고", f"{an.jo(r['total'], 1)}조 원", None],
                                           ["최근 1년 매출", f"{an.jo(rev, 1)}조 원" if rev else "–", None]], None

    idx = [i for i, x in enumerate(vals) if x is not None]
    labels = {i: f"{vals[i]:.1f}" for i in {idx[-1], max(idx, key=lambda i: vals[i]), min(idx, key=lambda i: vals[i])}}
    chart = d.line_chart(xl, vals, color="--s2", ticks_fmt=d.tick_plain, tips=tips, labels=labels, refs=[(3, "3년", "left")])
    return d.figure("fig-workyears", "몇 년 치 일감인가", "수주잔고 ÷ 최근 1년 매출 · 단위: 년", chart,
                    note="3년 치 안팎이면 앞으로 2~3년 매출은 이미 확보된 셈입니다. 다만 잔고가 이익을 보장하지는 않습니다(공사별 원가가 관건).")


def orders_fig(ctx):
    orders = biz_of(ctx).get("orders") or {}
    if len(orders) < 3:
        return ""
    years = list(range(int(min(orders)), int(max(orders)) + 1))
    get = lambda y, k: (orders.get(str(y)) or {}).get(k)
    dom = [get(y, "domestic") / T if get(y, "domestic") else None for y in years]
    ovs = [get(y, "overseas") / T if get(y, "overseas") else None for y in years]
    tot_only = [get(y, "total") / T if get(y, "total") and not get(y, "domestic") else None for y in years]

    def tips(i):
        y = years[i]
        o = orders.get(str(y))
        if not o:
            return f"{y}년", [["신규 수주", "보고서에 문장이 없음", None]], None
        rows = [["합계", f"{an.jo(o['total'], 2)}조 원", None]]
        if o.get("domestic"):
            rows = [["국내", f"{an.jo(o['domestic'], 2)}조 원", "var(--s1)"], ["해외", f"{an.jo(o['overseas'], 2)}조 원", "var(--s3)"]] + rows
        return f"{y}년 (현대건설 단독)", rows, "사업보고서 ‘지배회사 현황’ 문단"

    labels = {(0, i): an.jo(orders[str(y)]["total"]) for i, y in enumerate(years)
              if str(y) in orders and (i == len(years) - 1 or orders[str(y)]["total"] == max(o["total"] for o in orders.values()))}
    chart = stack_chart([d.year_label(y) for y in years],
                        [[{"values": dom, "color": "--s1"}, {"values": ovs, "color": "--s3"}, {"values": tot_only, "color": "--spark"}]],
                        ticks_fmt=d.tick_plain, tips=tips, labels=labels)
    missing = [str(y) for y in years if str(y) not in orders]
    note = ("현대건설 단독(별도) 기준입니다. 현대엔지니어링 등 자회사 수주는 빠져 있습니다. 회색 막대는 국내·해외 구분 없이 합계만 적힌 해입니다."
            + (f" {'·'.join(missing)}년은 보고서에 같은 문장이 없어 비웠습니다." if missing else ""))
    return d.figure("fig-orders", "한 해 동안 새로 따낸 공사 (신규 수주)", "현대건설 단독 · 연간 · 단위: 조 원", chart,
                    legend_html=d.legend([("국내", "--s1", "box"), ("해외", "--s3", "box"), ("구분 없음", "--spark", "box")]), note=note)


def pf_fig(ctx):
    every = pf_rows(ctx)
    rows = [x for x in every if x[0].endswith(".12")]
    if every and not every[-1][0].endswith(".12"):
        rows.append(every[-1])          # 연말 값 + 가장 최근 분기 (분기 숫자는 표에서)
    if len(rows) < 2:
        return ""
    xl = [f'<span>{esc(short_period(p) if not p.endswith(".12") else p[:4])}</span>' for p, _ in rows]
    vals = [r["amount"] / T for _, r in rows]
    mult = []
    for p, r in rows:
        b = balance_at(ctx, int(p[:4]), int(p[5:]))
        mult.append(r["amount"] / b["values"]["equity"] if b else None)
    labels = {(0, i): (f"{mult[i]:.1f}배" if mult[i] else an.jo(rows[i][1]["amount"])) for i in {0, len(rows) - 1}}

    def tips(i):
        p, r = rows[i]
        b = balance_at(ctx, int(p[:4]), int(p[5:]))
        tr = [["PF 보증", f"{an.jo(r['amount'], 2)}조 원", "var(--s4)"]]
        if b:
            tr += [["자본총계", f"{an.jo(b['values']['equity'], 2)}조 원", None], ["자본 대비", f"{mult[i]:.2f}배", None]]
        return period_label(p), tr, ("다음 해 보고서의 ‘전기말’ 숫자" if r.get("basis") == "next" else None)

    chart = d.column_chart(xl, [{"values": vals, "color": "--s4"}], ticks_fmt=d.tick_plain, tips=tips, labels=labels)
    def mult_at(p, r):
        b = balance_at(ctx, int(p[:4]), int(p[5:]))
        return r["amount"] / b["values"]["equity"] if b else None

    table = d.data_table(["기간", "PF 보증(억 원)", "자본 대비(배)"],
                         [[period_label(p), (d.eok(r["amount"]), None),
                           ("–" if mult_at(p, r) is None else f"{mult_at(p, r):.2f}", None)] for p, r in every])
    return d.figure("fig-pf", "PF 대출 보증 (책임지고 있는 남의 빚)", "보증금액 기준 · 연결 · 단위: 조 원 · 막대 위 = 자본총계의 몇 배", chart,
                    table_html=table,
                    note=("시행사·재건축 조합이 빌린 돈(PF)에 현대건설이 보증(신용보강)을 선 금액입니다. 지금은 빚이 아니지만 사업장이 잘못되면 빚이 됩니다. "
                          "2023년 사업보고서부터 정비사업 PF까지 포함하는 새 공시 기준이라, 그 전 숫자와는 비교하지 않습니다."))


def projects_fig(ctx):
    pj = biz_of(ctx).get("projects")
    if not pj or not pj.get("rows"):
        return ""
    rows = pj["rows"]
    scale = max(r["contract"] for r in rows)
    items = []
    for r in rows:
        prog = r["done"] / r["contract"] * 100 if r["contract"] else 0
        end = r["end"].replace("-", ".")[:7]
        meta = " · ".join(x for x in (r["company"], r["region"], r["client"][:22], f"~{end}" if end else "") if x)
        items.append({"label": r["name"], "meta": meta, "segs": [(r["done"], "--s1", "done"), (r["remain"], "--s1", "left")],
                      "value": r["remain"], "prog": prog,
                      "tip": (r["name"], [["계약(기본도급액)", f"{an.jo(r['contract'], 2)}조 원", None],
                                          ["완성", f"{an.jo(r['done'], 2)}조 원 ({prog:.0f}%)", "var(--s1)"],
                                          ["남은 공사", f"{an.jo(r['remain'], 2)}조 원", None]],
                              f"{r['client']} · {r['start'].replace('-', '.')} ~ {r['end'].replace('-', '.')}")})
    body = hstack(items, scale_max=scale, value_fmt=lambda r: f"{an.jo(r['value'], 2)}조 남음 · {r['prog']:.0f}%",
                  unit_label="막대 길이 = 계약금액 · 진한 부분 = 이미 지은 만큼 · 연한 부분 = 남은 공사")
    note = (f"남은 공사 금액이 큰 순서 {len(rows)}건 (전체 {pj['count']}건 중). 출처: {pj['report']} ‘수주상황’ 표. "
            "같은 공사를 현대건설과 현대엔지니어링이 나눠 맡으면 회사별로 따로 나옵니다.")
    return d.figure("fig-projects", f"지금 짓고 있는 큰 공사 ({period_label(pj['period'])})", "공사별 계약금액 · 완성 · 남은 금액", body,
                    legend_html=d.legend([("완성", "--s1", "box"), ("남은 공사", "--s1", "tint")]), note=note, wide=True)


def orders_section(ctx, v):
    biz = biz_of(ctx)
    lb = latest_backlog(ctx)
    orders = biz.get("orders") or {}
    oy = max(orders) if orders else None
    pf = pf_rows(ctx)
    tiles = []
    if lb:
        yrs = years_of_work(ctx, lb)
        tiles.append(("수주잔고", an.jo(lb["total"]), "조 원", period_label(lb["period"]) + (f" · 연결기준 {an.jo(lb['consolidated'])}조" if lb.get("consolidated") else "")))
        if yrs:
            tiles.append(("일감", f"{yrs:.1f}", "년 치", "수주잔고 ÷ 최근 1년 매출"))
    if oy:
        prev = orders.get(str(int(oy) - 1))
        chg = f" · 전년 {an.signed((orders[oy]['total'] / prev['total'] - 1) * 100, 0)}%" if prev else ""
        tiles.append(("신규 수주", an.jo(orders[oy]["total"]), "조 원", f"{oy}년 · 현대건설 단독{chg}"))
    if pf:
        p, r = pf[-1]
        b = balance_at(ctx, int(p[:4]), int(p[5:]))
        tiles.append(("PF 보증", an.jo(r["amount"]), "조 원", period_label(p) + (f" · 자본의 {r['amount'] / b['values']['equity']:.1f}배" if b else "")))
    cells = "".join(f'<div class="vt"><p class="vt-l">{esc(a)}</p><p class="vt-v">{esc(b)}<small>{esc(c)}</small></p>'
                    f'<p class="vt-d">{esc(e)}</p></div>' for a, b, c, e in tiles)
    head = d.section_head("orders", "Orders & PF", "수주·PF", "일감은 얼마나 쌓였고, 위험은 얼마나 지고 있나",
                          "재무제표에는 나오지 않는 두 숫자입니다. **수주잔고**는 앞으로 매출이 될 일감이고, **PF 보증**은 남의 빚을 대신 책임지기로 한 금액입니다. "
                          "둘 다 사업보고서 본문(Ⅱ장 수주상황, Ⅺ장 우발부채)에서 매월 자동으로 읽습니다.")
    errs = biz.get("errors") or []
    err = (f'<div class="callout warn" role="note"><p class="mini-h">읽지 못한 부분</p><ul>{"".join(f"<li>{esc(e)}</li>" for e in errs[:5])}</ul></div>'
           if errs else "")
    grid1 = f'<div class="grid-2">{backlog_fig(ctx)}{work_years_fig(ctx)}</div>'
    grid2 = f'<div class="grid-2">{orders_fig(ctx)}{pf_fig(ctx)}</div>'
    return (f'<section id="orders" aria-labelledby="h-orders">{head}<div class="vtiles">{cells}</div>'
            f'<div class="stack">{grid1}{projects_fig(ctx)}{grid2}</div>{err}</section>')


# ---------------------------------------------------------------------------
# 4. 10가지 관점 (요약 카드 · 자세한 차트는 재무제표 10년 화면)
# ---------------------------------------------------------------------------
def lens_tile(lens, href):
    m = lens["head"]
    if lens["id"] == "price":
        m = lens["metrics_data"][0]
    value = ln.fmt(m["latest"], m["unit"])
    unit = m["unit"]
    vals = [ln.display(x, m["unit"]) for x in m["values"]]
    spark = d.sparkline(vals, zero=any(x is not None and x < 0 for x in vals))
    verdict = (m["tone"], m["word"])
    extra = ""
    others = [x for x in lens["metrics_data"] if x is not m][:2]
    if others:
        extra = " · ".join(f"{x['label']} {ln.with_unit(x['latest'], x['unit'])}" for x in others if x["latest"] is not None)
    return (f'<article class="kpi lens"><div class="kpi-top"><h3 class="kpi-label"><a href="{esc(href)}#{lens["id"]}">'
            f'<span class="no">{lens["no"]}</span>{esc(lens["ko"])}</a></h3>{d.chip(verdict)}</div>'
            f'<p class="kpi-basis">{esc(m["latest_year"])}년 {esc(m["label"])}</p>'
            f'<p class="kpi-value">{esc(value)}<small>{esc(unit)}</small></p>'
            f'<p class="kpi-delta">{esc(extra)}</p>{spark}<p class="kpi-term">{esc(lens["q"])}</p></article>')


def lenses_section(ctx, href="../statements/"):
    L = ln.build(ctx)
    years = L[0]["years"] if L else []
    span = f"{years[0]}~{years[-1]}" if years else ""
    head = d.section_head("lenses", "10 lenses", "10가지 관점", "재무비율 10가지 관점으로 본 현대건설",
                          f"수익성·안정성·유동성·활동성·성장성·생산성·현금흐름·시장가치에 종합 분석(듀퐁)과 주가 반영을 더했습니다. "
                          f"판정은 절대 기준이 아니라 **최근 10년({span}) 안에서 지금이 어디쯤인지**입니다(높을수록 좋은 지표와 낮을수록 좋은 지표를 구분). "
                          f"PER처럼 해석이 갈리는 지표는 ‘참고’로 둡니다.")
    tiles = "".join(lens_tile(x, href) for x in L)
    more = (f'<p class="more-link"><a href="{esc(href)}">재무제표 10년 시각화에서 관점별 차트 자세히 보기 →</a></p>')
    return f'<section id="lenses" aria-labelledby="h-lenses">{head}<div class="kpis ten">{tiles}</div>{more}</section>'
