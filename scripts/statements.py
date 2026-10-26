"""대시보드의 재무제표 부분: 재무제표 10년(손익·재무상태·현금흐름)과 재무비율 10가지 관점.

- 최근 10개 사업연도(연결재무제표 연간 숫자)를 손익계산서 → 재무상태표 → 현금흐름표 순서로 그림으로 보여 주고,
  이어서 10가지 관점(수익성·안정성·유동성·활동성·성장성·생산성·현금흐름·시장가치·종합 분석·주가 반영)을 차트로 풉니다.
- 교수님 가이드 6단계(매출 성장 → 이익률 → 현금흐름 → 차입 부담 → 투자수익률 → 주가 수준)의 판정과 해설은
  짝이 되는 관점 섹션(성장성·수익성·현금흐름·안정성·종합 분석·시장가치)에 함께 넣습니다(lenses.GUIDE_STEP).
- 차트 부품과 지표 정의는 dashboard.py · lenses.py와 같습니다. 매월 에이전트가 대시보드와 함께 다시 만듭니다.
- 예전 주소(statements/)로 들어오면 대시보드의 같은 위치로 보내는 안내 페이지만 남깁니다(redirect_page).
"""
import analysis as an
import dashboard as d
import lenses as ln

esc, rich = d.esc, d.rich
T = an.T
COLORS = ["--s1", "--s3", "--s2", "--s4"]


def _vals(m):
    return [ln.display(x, m["unit"]) for x in m["values"]]


def _metric(lens, key):
    return next(m for m in lens["metrics_data"] if m["key"] == key)


def _xl(years):
    return [d.year_label(y) for y in years]


def _table_for(metrics, years):
    heads = ["연도"] + [f"{m['label']}({m['unit']})" for m in metrics]
    rows = []
    for i, y in enumerate(years):
        rows.append([str(y)] + [(ln.fmt(m["values"][i], m["unit"]), m["values"][i]) for m in metrics])
    return d.data_table(heads, rows)


def lines_fig(fid, title, sub, metrics, years, refs=(), note=None, wide=False):
    series = [{"name": m["label"], "values": _vals(m), "color": COLORS[i % 4]} for i, m in enumerate(metrics)]
    unit = metrics[0]["unit"]

    def tips(i):
        return f"{years[i]}년", [[m["label"], ln.with_unit(m["values"][i], m["unit"]), f"var({COLORS[j % 4]})"]
                                for j, m in enumerate(metrics)], None

    if len(metrics) == 1:
        vals = series[0]["values"]
        idx = [i for i, x in enumerate(vals) if x is not None]
        labels = {}
        if idx:
            hi = max(idx, key=lambda i: vals[i])
            lo = min(idx, key=lambda i: vals[i])
            labels = {i: ln.fmt(metrics[0]["values"][i], unit) for i in {idx[-1], hi, lo}}
        chart = d.line_chart(_xl(years), vals, color=COLORS[0], ticks_fmt=d.tick_plain, tips=tips, labels=labels, refs=refs)
        leg = ""
    else:
        chart = d.multi_line_chart(_xl(years), series, ticks_fmt=d.tick_plain, tips=tips, refs=refs,
                                   end_fmt=lambda x: ln.fmt(x * ln.SCALE.get(unit, 1), unit))
        leg = d.legend([(sr["name"], sr["color"], "line") for sr in series])
    return d.figure(fid, title, sub, chart, legend_html=leg, table_html=_table_for(metrics, years), note=note, wide=wide)


def cols_fig(fid, title, sub, metrics, years, refs=(), note=None, wide=False):
    series = [{"values": _vals(m), "color": COLORS[i % 4]} for i, m in enumerate(metrics[:2])]
    neg = any(x is not None and x < 0 for sr in series for x in sr["values"])

    def tips(i):
        return f"{years[i]}년", [[m["label"], ln.with_unit(m["values"][i], m["unit"]), f"var({COLORS[j % 4]})"]
                                for j, m in enumerate(metrics[:2])], None

    labels = {}
    for j, sr in enumerate(series):
        idx = [i for i, x in enumerate(sr["values"]) if x is not None]
        if idx:
            labels[(j, idx[-1])] = ln.fmt(metrics[j]["values"][idx[-1]], metrics[j]["unit"])
            if len(series) == 1:
                hi = max(idx, key=lambda i: sr["values"][i])
                lo = min(idx, key=lambda i: sr["values"][i])
                for i in (hi, lo):
                    labels[(0, i)] = ln.fmt(metrics[0]["values"][i], metrics[0]["unit"])
    chart = d.column_chart(_xl(years), series, ticks_fmt=d.tick_plain, tips=tips, labels=labels, neg_zone=neg,
                           include=[r[0] for r in refs])
    if refs:      # 막대 차트에도 기준선을 그립니다
        lo, hi, ticks = d.axis([x for sr in series for x in sr["values"]], include=[r[0] for r in refs])
        span = hi - lo
        ref_html = "".join(f'<i class="rl" style="bottom:{(val - lo) / span * 100:.3f}%"></i>'
                           f'<span class="rlab {side}" style="bottom:{(val - lo) / span * 100:.3f}%">{esc(text)}</span>'
                           for val, text, side in refs)
        chart = chart.replace('</div><div class="xa"', f'{ref_html}</div><div class="xa"', 1)   # 막대 위에 그려 글자가 가리지 않게
    leg = d.legend([(m["label"], COLORS[i % 4], "box") for i, m in enumerate(metrics[:2])]) if len(metrics) > 1 else ""
    return d.figure(fid, title, sub, chart, legend_html=leg, table_html=_table_for(metrics, years), note=note, wide=wide)


# ---------------------------------------------------------------------------
# 재무제표 세 가지
# ---------------------------------------------------------------------------
def ten_view(ctx, years):
    """최근 10개 사업연도만 담은 View (가이드 차트 함수에 그대로 넘깁니다)."""
    return an.View({**ctx, "annual": [r for r in ctx["annual"] if r["year"] in years]})


def revenue_note(v, years):
    rev = v.series("revenue")
    idx = range(len(years))
    peak = max(idx, key=lambda i: rev[i] or 0)
    growth = [(years[i], v.a(years[i], "revenue_growth_pct")) for i in idx if v.a(years[i], "revenue_growth_pct") is not None]
    text = (f"{years[0]}년 {an.jo(rev[0])}조 원 → {years[-1]}년 {an.jo(rev[-1])}조 원(**{rev[-1] / rev[0]:.2f}배**). "
            f"가장 많았던 해는 {years[peak]}년({an.jo(rev[peak])}조 원)")
    if growth:
        gy, g = max(growth, key=lambda x: x[1])
        if g > 0:
            text += f", 가장 크게 늘어난 해는 {gy}년({an.signed(g)}%)"
    return text + "입니다."


def is_section(ctx, v, years):
    rev, op, ni = (v.series(k) for k in ("revenue", "operating_profit", "net_income"))
    idx = range(len(years))
    hi = max(idx, key=lambda i: rev[i] or 0)
    labels = {(0, i): an.jo(rev[i]) for i in {0, hi, len(years) - 1}}

    def tips(i):
        t = years[i]
        return f"{t}년", [["매출액", an.won(rev[i]) + " 원", "var(--data)"],
                         ["매출원가", an.won(v.a(t, "cost_of_sales")) + " 원", None],
                         ["매출 증가율", f"{an.signed(v.a(t, 'revenue_growth_pct'))}%", None]], None

    f1 = d.figure("fig-revenue", "매출액", "연간 · 연결 · 단위: 조 원",
                  d.column_chart(_xl(years), [{"values": d.in_jo(rev), "color": "--data"}], ticks_fmt=d.tick_plain, tips=tips,
                                 labels=labels),
                  note=revenue_note(v, years))

    def tips2(i):
        t = years[i]
        return f"{t}년", [["영업이익", an.won(op[i]) + " 원", "var(--s1)"], ["당기순이익", an.won(ni[i]) + " 원", "var(--s2)"],
                         ["영업이익률", f"{an.pct(v.a(t, 'operating_margin_pct'))}%", None]], None

    lo_i = min(idx, key=lambda i: op[i] or 0)
    f2 = d.figure("fig-op-ni", "영업이익 · 당기순이익", "연간 · 연결 · 단위: 조 원 · 0 아래 붉은 바탕 = 손실",
                  d.column_chart(_xl(years), [{"values": d.in_jo(op), "color": "--s1"}, {"values": d.in_jo(ni), "color": "--s2"}],
                                 ticks_fmt=d.tick_plain, tips=tips2, labels={(0, lo_i): an.jo(op[lo_i], 2), (0, len(years) - 1): an.jo(op[-1], 2)},
                                 neg_zone=True),
                  legend_html=d.legend([("영업이익", "--s1", "box"), ("당기순이익", "--s2", "box")]))
    f3 = d.per100_fig(v, ctx["analysis"].get("notes") or {})
    keys = [("revenue", "매출액"), ("cost_of_sales", "매출원가"), ("gross_profit", "매출총이익"), ("sga", "판매비와관리비"),
            ("operating_profit", "영업이익"), ("pretax_income", "법인세차감전순이익"), ("net_income", "당기순이익"),
            ("net_income_owners", "지배주주 순이익")]
    table = d.data_table(["항목(억 원)"] + [str(y) for y in years],
                         [[name] + [(d.eok(v.a(y, k)), v.a(y, k)) for y in years] for k, name in keys])
    head = d.section_head("is", "Income statement", "손익계산서", "얼마나 팔고 얼마나 남겼나",
                          "손익계산서는 1년 동안의 **매출 → 원가 → 이익** 흐름입니다. 건설사는 공사 진행률만큼 매출을 잡기 때문에, "
                          "원가가 예상보다 늘면 그해 이익이 크게 흔들립니다.")
    return (f'<section id="is" aria-labelledby="h-is">{head}<div class="stack"><div class="grid-2">{f1}{f2}</div>{f3}'
            f'<details class="tv"><summary>손익계산서 요약 표</summary>{table}</details></div></section>')


def bs_chart(v, years):
    """재무상태표 두 막대(자산 | 부채 + 자본). 대시보드와 기업분석 보고서가 함께 씁니다."""
    def g(t, k):
        return v.a(t, k) or 0

    cur = [g(t, "current_assets") / T for t in years]
    non = [(g(t, "assets") - g(t, "current_assets")) / T for t in years]
    bor = [g(t, "borrowings_total") / T for t in years]
    adv = [g(t, "advances_total") / T for t in years]
    oth = [(g(t, "liabilities") - g(t, "borrowings_total") - g(t, "advances_total")) / T for t in years]
    eq = [g(t, "equity") / T for t in years]

    def tips(i):
        t = years[i]
        return f"{t}년 말", [["자산총계", f"{an.jo(v.a(t, 'assets'), 2)}조 원", None],
                            ["유동자산", f"{cur[i]:.2f}조 원", "var(--s3)"], ["비유동자산", f"{non[i]:.2f}조 원", "var(--sga)"],
                            ["이자부차입금", f"{bor[i]:.2f}조 원", "var(--s4)"], ["미리 받은 돈", f"{adv[i]:.2f}조 원", "var(--s2)"],
                            ["기타 부채", f"{oth[i]:.2f}조 원", "var(--cost)"], ["자본총계", f"{eq[i]:.2f}조 원", "var(--s1)"]], \
            f"부채비율 {an.pct(v.a(t, 'debt_to_equity_pct'), 0)}% · 차입금의존도 {an.pct(v.a(t, 'borrowing_dependency_pct'))}%"

    chart = d.stack_chart(_xl(years), [[{"values": cur, "color": "--s3"}, {"values": non, "color": "--sga"}],
                                       [{"values": bor, "color": "--s4"}, {"values": adv, "color": "--s2"},
                                        {"values": oth, "color": "--cost"}, {"values": eq, "color": "--s1"}]],
                          ticks_fmt=d.tick_plain, tips=tips, height=240, wide_bars=True)
    last = years[-1]
    share = g(last, "borrowings_total") / g(last, "liabilities") * 100 if g(last, "liabilities") else None
    return d.figure("fig-bs", "가진 것(자산)과 그 돈의 출처(부채 + 자본)", "연말 · 연결 · 왼쪽 막대 = 자산, 오른쪽 막대 = 부채 + 자본 · 단위: 조 원",
                    chart, legend_html=d.legend([("유동자산", "--s3", "box"), ("비유동자산", "--sga", "box"), ("이자부차입금", "--s4", "box"),
                                                 ("미리 받은 돈(선수금·초과청구)", "--s2", "box"), ("기타 부채", "--cost", "box"), ("자본", "--s1", "box")]),
                    note=(f"두 막대 높이는 늘 같습니다(자산 = 부채 + 자본). {last}년 말 부채 {an.jo(v.a(last, 'liabilities'))}조 원 중 이자가 붙는 차입금은 "
                          f"**{an.pct(share, 0)}%**뿐이고, 상당 부분은 공사로 갚는 ‘미리 받은 돈’과 매입채무 같은 영업 부채입니다." if share else None),
                    wide=True)


def bs_section(ctx, v, years):
    fig = bs_chart(v, years)
    keys = [("assets", "자산총계"), ("current_assets", "유동자산"), ("cash", "현금및현금성자산"), ("receivables_total", "받을 돈(매출채권+미청구공사)"),
            ("liabilities", "부채총계"), ("borrowings_total", "이자부차입금"), ("advances_total", "미리 받은 돈"), ("equity", "자본총계"),
            ("equity_owners", "지배주주 자본")]
    table = d.data_table(["항목(억 원)"] + [str(y) for y in years],
                         [[name] + [(d.eok(v.a(y, k)), v.a(y, k)) for y in years] for k, name in keys])
    head = d.section_head("bs", "Balance sheet", "재무상태표", "무엇을 가졌고, 그 돈은 어디서 왔나",
                          "재무상태표는 연말 하루의 사진입니다. 왼쪽(자산)은 가진 것, 오른쪽(부채 + 자본)은 그 돈을 누가 댔는지입니다.")
    return (f'<section id="bs" aria-labelledby="h-bs">{head}<div class="stack">{fig}'
            f'<details class="tv"><summary>재무상태표 요약 표</summary>{table}</details></div></section>')


def cf_chart(v, years):
    cfo, cfi, cff = (v.series(k) for k in ("operating_cashflow", "investing_cashflow", "financing_cashflow"))

    def tips(i):
        t = years[i]
        return f"{t}년", [["영업활동", an.won(cfo[i]) + " 원", "var(--s1)"], ["투자활동", an.won(cfi[i]) + " 원", "var(--s3)"],
                         ["재무활동", an.won(cff[i]) + " 원", "var(--s2)"]], f"연말 현금 {an.won(v.a(t, 'cash'))} 원"

    chart = d.column_chart(_xl(years), [{"values": d.in_jo(cfo), "color": "--s1"}, {"values": d.in_jo(cfi), "color": "--s3"},
                                        {"values": d.in_jo(cff), "color": "--s2"}], ticks_fmt=d.tick_plain, tips=tips, neg_zone=True)
    chart = chart.replace('class="plot cc k3"', 'class="plot cc k3 wb"', 1)
    return d.figure("fig-cf3", "현금흐름표 세 칸", "연간 · 연결 · 플러스 = 들어온 돈, 마이너스 = 나간 돈 · 단위: 조 원", chart,
                    legend_html=d.legend([("영업활동", "--s1", "box"), ("투자활동", "--s3", "box"), ("재무활동", "--s2", "box")]), wide=True,
                    note="영업활동은 본업(공사)으로 번 현금, 투자활동은 설비·예금 등에 쓴 돈, 재무활동은 빌리거나 갚은 돈입니다.")


def cf_section(ctx, v, years):
    sig = [s for s in ctx["analysis"].get("signals", []) if s["year"] in years]
    head = d.section_head("cf", "Cash flow", "현금흐름표", "돈은 실제로 어디서 들어와 어디로 나갔나",
                          "손익계산서의 이익은 ‘장부상’ 숫자입니다. 현금흐름표는 실제로 통장에 들어오고 나간 돈입니다. "
                          "건설사는 공사를 해도 대금을 늦게 받으면 이익과 현금이 크게 벌어집니다.")
    return (f'<section id="cf" aria-labelledby="h-cf">{head}<div class="stack">{cf_chart(v, years)}'
            f'{d.signal_table(sig) if sig else ""}</div></section>')


# ---------------------------------------------------------------------------
# 10가지 관점
# ---------------------------------------------------------------------------
HEAT_PICKS = [("profitability", "operating_margin_pct"), ("profitability", "roe_pct"), ("stability", "debt_to_equity_pct"),
              ("stability", "interest_coverage_x"), ("liquidity", "current_ratio_pct"), ("activity", "receivables_days"),
              ("growth", "revenue_growth_pct"), ("productivity", "rev_per_emp"), ("cashflow", "operating_cashflow"),
              ("cashflow", "cfo_to_ni_x")]


def heat_color(x, m):
    """같은 지표의 10년 값 안에서 좋은 쪽은 초록, 나쁜 쪽은 빨강 (가운데는 흰 바탕)."""
    vals = [y for y in m["values"] if y is not None]
    lo, hi = (min(vals), max(vals)) if vals else (0, 1)
    t = 0.5 if hi == lo else (x - lo) / (hi - lo)
    if m["dir"] < 0:
        t = 1 - t
    if t >= 0.5:
        return f"color-mix(in srgb,var(--good) {(t - 0.5) * 2 * 34:.0f}%,var(--sheet))"
    return f"color-mix(in srgb,var(--crit) {(0.5 - t) * 2 * 34:.0f}%,var(--sheet))"


def heatmap(L, years):
    by = {x["id"]: x for x in L}
    head = "".join(f'<th scope="col">{y}</th>' for y in years)
    body = []
    for lid, key in HEAT_PICKS:
        lens = by[lid]
        m = _metric(lens, key)
        cells = []
        for x in m["values"]:
            if x is None:
                cells.append('<td class="na">–</td>')
                continue
            cells.append(f'<td style="background:{heat_color(x, m)}">{esc(ln.fmt(x, m["unit"]))}</td>')
        body.append(f'<tr><th scope="row">{esc(lens["ko"])} · {esc(m["label"])}<small>{esc(m["unit"])}</small></th>{"".join(cells)}</tr>')
    return (f'<div class="table-scroll heat" tabindex="0"><table><caption>10년 위치표 · 같은 줄 안에서 가장 좋은 해는 초록, 가장 나쁜 해는 빨강 '
            f'(부채비율·회수기간은 낮을수록 좋음)</caption><thead><tr><th scope="col">지표</th>{head}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def dupont_rows(lens, years):
    roe, nm, at, lev = (_metric(lens, k) for k in ("roe_pct", "net_margin_pct", "asset_turnover_x", "leverage_x"))
    rows = []
    for i, y in enumerate(years):
        a, b, c, r = nm["values"][i], at["values"][i], lev["values"][i], roe["values"][i]
        prod = None if None in (a, b, c) else a * b * c
        rows.append([str(y), (ln.fmt(a, "%"), a), (ln.fmt(b, "회"), b), (ln.fmt(c, "배"), c), (ln.fmt(prod, "%"), prod), (ln.fmt(r, "%"), r)])
    return ["연도", "순이익률(%)", "× 총자산회전율(회)", "× 재무레버리지(배)", "= ROE 계산(%)", "ROE(%)"], rows


def dupont_note(lens, years):
    roe, nm, lev = (_metric(lens, k) for k in ("roe_pct", "net_margin_pct", "leverage_x"))
    i_hi = max(range(len(years)), key=lambda i: roe["values"][i] if roe["values"][i] is not None else -1e9)
    msg = []
    if roe["values"][-1] is not None and roe["values"][i_hi] is not None:
        msg.append(f"ROE가 가장 높았던 해는 {years[i_hi]}년({ln.fmt(roe['values'][i_hi], '%')}%)이고, {years[-1]}년은 {ln.fmt(roe['values'][-1], '%')}%입니다.")
        if None not in (nm["values"][i_hi], nm["values"][-1], lev["values"][i_hi], lev["values"][-1]):
            msg.append(f"그사이 순이익률은 {ln.fmt(nm['values'][i_hi], '%')}% → {ln.fmt(nm['values'][-1], '%')}%로, "
                       f"재무레버리지는 {ln.fmt(lev['values'][i_hi], '배')}배 → {ln.fmt(lev['values'][-1], '배')}배로 바뀌었습니다. "
                       "레버리지가 올라 ROE를 받친 만큼은 ‘빚으로 만든 수익률’입니다.")
    return " ".join(msg)


def dupont_body(lens, years, L, v, vd):
    nm, at, lev = (_metric(lens, k) for k in ("net_margin_pct", "asset_turnover_x", "leverage_x"))
    main = d.returns_fig(v, vd)
    minis = "".join(lines_fig(f"fig-dp-{m['key']}", m["label"], f"{m['how']} · 단위: {m['unit']}", [m], years)
                    for m in (nm, at, lev))
    heads, rows = dupont_rows(lens, years)
    return (f'<div class="stack">{main}<div class="grid-3">{minis}</div>'
            f'<figure class="chart"><figcaption class="chart-head"><h3>듀퐁 분해 검산</h3><p>세 값을 곱하면 ROE가 됩니다</p></figcaption>'
            f'{d.data_table(heads, rows)}<p class="chart-note">{rich(dupont_note(lens, years))}</p></figure>'
            f'<div class="sub-head"><h3>종합 분석: 10년 위치표</h3><p>여러 관점의 대표 지표를 한 표에 놓고, 같은 줄 안에서 상대적으로 좋은 해와 나쁜 해를 색으로 표시했습니다. '
            f'한 해의 색이 대부분 빨갛다면 여러 관점에서 동시에 나빠진 해입니다.</p></div>{heatmap(L, years)}</div>')


def price_fig(ctx, first_year, fid="fig-price10"):
    """월별 주가 꺾은선 (first_year 1월부터). 대시보드와 기업분석 보고서가 함께 씁니다."""
    monthly = ctx.get("prices") or {}
    months = [m for m in sorted(monthly) if int(m[:4]) >= first_year]
    if len(months) < 12:
        return ""
    xl = [f'<span>{"’" + m[2:4] if m[4:] == "01" else "&nbsp;"}</span>' for m in months]
    vals = [monthly[m] / 1000 for m in months]
    hi_i = max(range(len(vals)), key=lambda i: vals[i])
    lo_i = min(range(len(vals)), key=lambda i: vals[i])

    def ptips(i):
        m = months[i]
        return f"{m[:4]}년 {int(m[4:])}월 말", [["종가", f"{monthly[m]:,.0f}원", "var(--data)"]], None

    return d.figure(fid, "월별 주가", f"{months[0][:4]}.{months[0][4:]}~{months[-1][:4]}.{months[-1][4:]} · 달마다 마지막 거래일의 보통주 종가 · 단위: 천 원",
                    d.line_chart(xl, vals, color="--data", ticks_fmt=d.tick_plain, tips=ptips,
                                 labels={hi_i: f"{vals[hi_i]:.1f}", lo_i: f"{vals[lo_i]:.1f}", len(vals) - 1: f"{vals[-1]:.1f}"},
                                 height=200, dots=False), wide=True,
                    note="2021년 이전 숫자는 네이버 금융의 수정주가(액면분할·증자 등을 반영해 다시 계산한 가격)입니다.")


def price_direction(lens, years):
    """주가 연간 상승률과 영업이익 증가율이 같은 방향이었던 해 → (표 머리, 행, 같은 방향 해 수, 비교 가능한 해 수)."""
    pr, og = _metric(lens, "price_return_pct"), _metric(lens, "op_growth_pct")
    rows, same, total = [], 0, 0
    for i, y in enumerate(years):
        a, b = pr["values"][i], og["values"][i]
        mark = "–"
        if a is not None and b is not None:
            total += 1
            ok = (a >= 0) == (b >= 0)
            same += ok
            mark = "✓ 같은 방향" if ok else "✕ 반대"
        rows.append([str(y), (ln.fmt(a, "%", True), a), (ln.fmt(b, "%", True), b), mark])
    return ["연도", "주가 연간 상승률(%)", "영업이익 증가율(%)", "방향"], rows, same, total


def price_body(ctx, lens, years):
    figs = [price_fig(ctx, years[0])]
    heads, rows, same, total = price_direction(lens, years)
    note = (f"계산할 수 있는 {total}년 중 **{same}년**은 주가와 영업이익이 같은 방향으로 움직였습니다. "
            "주가는 실적이 나오기 전에 기대를 먼저 반영하기 때문에, 방향이 반대인 해는 시장이 다음 해 실적(수주·원전·해외 사업 등)을 미리 본 경우가 많습니다."
            if total else "")
    figs.append(f'<figure class="chart"><figcaption class="chart-head"><h3>주가는 실적을 따라갔나</h3>'
                f'<p>연말 주가 상승률 vs 같은 해 영업이익 증가율 (작년이 적자면 증가율 계산 안 함)</p></figcaption>{d.data_table(heads, rows)}'
                f'<p class="chart-note">{rich(note)}</p></figure>')
    cap = _metric(lens, "market_cap")
    figs.append(cols_fig("fig-mcap", "연말 시가총액", "보통주 + 우선주 · 단위: 조 원", [cap], years))
    return f'<div class="stack">{figs[0]}<div class="grid-2">{"".join(figs[1:])}</div></div>'


# 관점별 차트: ('line'|'col', 지표 키, 제목, 부제, 기준선) 또는 ('guide', 이름) = 가이드 단계 차트(dashboard.py)
CHARTS = {
    "profitability": [("guide", "margins")],
    "stability": [("line", ["debt_to_equity_pct", "equity_ratio_pct", "borrowing_dependency_pct"], "부채비율 · 자기자본비율 · 차입금의존도", "연말 · 단위: %", [(100, "100%", "left")]),
                  ("guide", "coverage"), ("guide", "netdebt")],
    "liquidity": [("line", ["current_ratio_pct", "quick_ratio_pct", "cash_ratio_pct"], "유동비율 · 당좌비율 · 현금비율", "연말 · 단위: %", [(100, "100%", "left")])],
    "activity": [("line", ["receivables_days", "dso_days", "dpo_days", "ccc_days"], "회수·지급 기간", "단위: 일", []),
                 ("line", ["asset_turnover_x"], "총자산회전율", "매출액 ÷ 평균 자산총계 · 단위: 회", [(1, "1회", "left")]),
                 ("guide", "receivables")],
    "growth": [("col", ["revenue_growth_pct"], "매출증가율", "전년 대비 · 단위: %", []),
               ("line", ["equity_growth_pct", "asset_growth_pct"], "자기자본 · 총자산 증가율", "전년 말 대비 · 단위: %", [(0, "", "left")])],
    "productivity": [("col", ["rev_per_emp"], "직원 1인당 매출액", "현대건설 단독 · 단위: 억 원", []),
                     ("col", ["employees"], "직원 수", "현대건설 단독 · 연말 · 단위: 명", []),
                     ("line", ["avg_salary", "op_per_emp"], "1인 평균 급여 · 1인당 영업이익", "현대건설 단독 · 단위: 백만 원", [(0, "", "left")])],
    "cashflow": [("guide", "cash"), ("guide", "fcf"),
                 ("col", ["cfo_to_ni_x"], "CFO/순이익", "1배 이상이면 이익만큼 현금이 들어옴 · 단위: 배", [(1, "1배", "left")])],
    "market": [("line", ["pbr_x"], "PBR", "연말 주가 기준 · 단위: 배", [(1, "1배", "right")]),
               ("line", ["per_x", "ev_ebitda_x"], "PER · EV/EBITDA", "연말 주가 기준 · 적자 해는 비움 · 단위: 배", []),
               ("col", ["fcf_yield_pct"], "FCF 수익률", "FCF ÷ 시가총액 · 단위: %", [])],
}


def guide_fig(name, v, ctx):
    a = ctx["analysis"]
    if name == "margins":
        return d.margins_fig(v)
    if name in ("coverage", "netdebt"):
        f_cov, f_nd, _, _ = d.debt_figs(v)
        return f_cov if name == "coverage" else f_nd
    if name in ("cash", "receivables"):
        f_cash, f_rec = d.cash_figs(v, a["verdicts"], a.get("notes") or {})
        return f_cash if name == "cash" else f_rec
    if name == "fcf":
        return d.fcf_fig(v)
    raise KeyError(name)


def lens_body(ctx, lens, years, L, v):
    lid = lens["id"]
    if lid == "dupont":
        return dupont_body(lens, years, L, v, ctx["analysis"]["verdicts"])
    if lid == "price":
        return price_body(ctx, lens, years)
    figs = []
    for n, spec in enumerate(CHARTS.get(lid, [])):
        if spec[0] == "guide":
            figs.append(guide_fig(spec[1], v, ctx))
            continue
        kind, keys, title, sub, refs = spec
        ms = [_metric(lens, k) for k in keys]
        fid = f"fig-{lid}-{n}"
        figs.append(lines_fig(fid, title, sub, ms, years, refs=refs) if kind == "line" else cols_fig(fid, title, sub, ms, years, refs=refs))
    top = d.valuation_tiles(ctx) if lid == "market" else ""
    if len(figs) == 1:
        return top + figs[0]
    cls = "grid-3" if len(figs) == 3 else "grid-2"
    return f'{top}<div class="{cls}" style="margin-top:0">{"".join(figs)}</div>'


def lens_section(ctx, lens, years, L, v, step=None):
    head_m = lens["head"]
    chips = d.chip((head_m["tone"], head_m["word"]))
    if step and step.get("verdict"):
        tone, word = step["verdict"]
        lens_chip = chips if head_m["tone"] != "info" else ""      # 둘 다 '참고'면 하나만
        chips = d.chip((tone, f"가이드 판정 · {word}")) + lens_chip
    answer = f'<p class="answer">{rich(step["answer"])}</p>' if step else ""
    lead = f'<p>{rich(step["lead"])}</p>' if step and step.get("lead") else ""
    top = (f'<div class="sec-head"><div class="sec-top"><span class="step-no">관점 {lens["no"]}</span>{d.eyebrow(lens["en"], lens["ko"])}'
           f'{chips}</div><h2 id="h-{lens["id"]}">{esc(lens["ko"])}: {esc(lens["q"])}</h2>{answer}<p>{rich(lens["read"])}</p>{lead}</div>')
    sentences = "".join(f"<li>{rich(ln.sentence(m))}</li>" for m in lens["metrics_data"])
    now = f'<div class="card lens-now"><h3>지금은 · 최근 {len(years)}년 중 위치</h3><ul class="plain">{sentences}</ul></div>'
    more = "".join(f"<p>{rich(p)}</p>" for p in (step or {}).get("more", []))
    explain = f'<div class="explain"><p class="mini-h">가이드 순서로 본 해설</p>{more}</div>' if more else ""
    return (f'<section id="{lens["id"]}" aria-labelledby="h-{lens["id"]}">{top}<div class="stack">{now}'
            f'{lens_body(ctx, lens, years, L, v)}</div>{explain}</section>')


def lens_tile(lens):
    m = lens["head"]
    if lens["id"] == "price":
        m = lens["metrics_data"][0]
    vals = [ln.display(x, m["unit"]) for x in m["values"]]
    spark = d.sparkline(vals, zero=any(x is not None and x < 0 for x in vals))
    others = [x for x in lens["metrics_data"] if x is not m][:2]
    extra = " · ".join(f"{x['label']} {ln.with_unit(x['latest'], x['unit'])}" for x in others if x["latest"] is not None)
    return (f'<article class="kpi lens"><div class="kpi-top"><h3 class="kpi-label"><a href="#{lens["id"]}">'
            f'<span class="no">{lens["no"]}</span>{esc(lens["ko"])}</a></h3>{d.chip((m["tone"], m["word"]))}</div>'
            f'<p class="kpi-basis">{esc(m["latest_year"])}년 {esc(m["label"])}</p>'
            f'<p class="kpi-value">{esc(ln.fmt(m["latest"], m["unit"]))}<small>{esc(m["unit"])}</small></p>'
            f'<p class="kpi-delta">{esc(extra)}</p>{spark}<p class="kpi-term">{esc(lens["q"])}</p></article>')


def lenses_overview(L, years):
    span = f"{years[0]}~{years[-1]}" if years else ""
    head = d.section_head("lenses", "10 lenses", "10가지 관점", "재무비율 10가지 관점으로 본 현대건설",
                          f"수익성·안정성·유동성·활동성·성장성·생산성·현금흐름·시장가치에 종합 분석(듀퐁)과 주가 반영을 더했습니다. "
                          f"카드의 판정은 절대 기준이 아니라 **최근 10년({span}) 안에서 지금이 어디쯤인지**입니다(높을수록 좋은 지표와 낮을수록 좋은 지표를 구분). "
                          f"PER처럼 해석이 갈리는 지표는 ‘참고’로 둡니다.",
                          "교수님 가이드 6단계의 판정(절대 규칙)과 해설은 짝이 되는 관점(성장성·수익성·현금흐름·안정성·종합 분석·시장가치) 섹션에 함께 있습니다. "
                          "카드를 누르면 그 관점의 차트로 갑니다.")
    tiles = "".join(lens_tile(x) for x in L)
    return f'<section id="lenses" aria-labelledby="h-lenses">{head}<div class="kpis ten">{tiles}</div></section>'


def sections(ctx):
    """대시보드에 넣을 재무제표 10년 · 10가지 관점 섹션. 반환: (목차 [(id, 이름) | None], HTML)."""
    years = ln.window_years(ctx)
    if len(years) < 3:
        return [], ""
    v = ten_view(ctx, years)
    L = ln.build(ctx)
    steps = {s["id"]: s for s in ctx["analysis"].get("steps", [])}
    parts = ['<p class="band-label" aria-hidden="true">Financial statements · 재무제표 10년</p>']
    for build in (is_section, bs_section, cf_section):
        try:
            parts.append(build(ctx, v, years))
        except Exception as exc:    # 한 표의 숫자가 이상해도 나머지 화면은 만듭니다
            print(f"::warning::{build.__name__} 생략: {type(exc).__name__}: {exc}")
    parts.append('<p class="band-label" aria-hidden="true">10 lenses · 재무비율 10가지 관점</p>')
    parts.append(lenses_overview(L, years))
    for lens in L:
        try:
            parts.append(lens_section(ctx, lens, years, L, v, steps.get(ln.GUIDE_STEP.get(lens["id"]))))
        except Exception as exc:    # 한 관점의 숫자가 이상해도 나머지 화면은 만듭니다
            print(f"::warning::관점 {lens['ko']} 생략: {type(exc).__name__}: {exc}")
    toc = [("is", "손익계산서"), ("bs", "재무상태표"), ("cf", "현금흐름표"), None, ("lenses", "10가지 관점")]
    toc += [(x["id"], f"{x['no']} {x['ko']}") for x in L]
    return toc, "".join(parts)


def redirect_page(ctx):
    """예전 주소(statements/)로 들어오면 대시보드의 같은 위치로 보냅니다."""
    name = esc(ctx["company"]["name"])
    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} 재무제표 대시보드로 이동</title>
<meta http-equiv="refresh" content="0; url=../dashboard/#is">
<link rel="canonical" href="../dashboard/">
<script>var h=location.hash||"#is";if(h==="#all"){{h="#annual";}}location.replace("../dashboard/"+h);</script>
<style>
:root{{--bg:#f3f0e8;--ink:#141716;--link:#1a6252}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1312;--ink:#ecede8;--link:#7cc4b3}}}}
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:var(--bg);color:var(--ink);
  font:16px/1.6 "Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",system-ui,sans-serif;padding:16px}}
a{{color:var(--link)}}
</style></head>
<body><p>재무제표 10년 시각화는 <a href="../dashboard/#is">{name} 재무제표 대시보드</a>로 합쳤습니다.</p></body></html>
"""
