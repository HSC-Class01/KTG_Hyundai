"""기업분석 보고서의 원인 분석 계산 — 공시 숫자를 회계식으로 나누고, 민감도와 시나리오를 계산합니다.

원칙
- '확인된 기여도'는 회계 항등식으로 정확히 나눠지는 것만 씁니다(나머지가 0이 되는 분해).
  예) 영업이익 증감 = 매출 규모 효과 + 원가율 효과 + 판관비율 효과 (+ 기타 영업손익)
- 공시 주석에 회사가 직접 계산해 적은 숫자(원가 추정 변경 효과, 이자율·환율 민감도)는 그대로 인용합니다.
- 가정이 들어간 계산(시나리오, 원가율 1%p 같은 민감도)은 결과마다 가정을 함께 돌려줍니다.
- 외부 요인(금리·정책·유가)과 실적의 관계는 연간 관측치가 10개뿐이라 인과로 판정하지 않습니다(상관계수도 계산하지 않음).

입력은 dart_agent.make_context가 만든 ctx(재무제표 표 + business + drivers)이고, 출력은 JSON으로 저장할 수 있는 dict/list입니다.
"""
import analysis as an

T = an.T                        # 1조 원
SEG = ("building", "civil", "plant", "other")
SEG_KO = {"building": "건축/주택", "civil": "토목", "plant": "플랜트/전력", "other": "기타", "adjust": "연결조정·기타"}
TAX_ASSUMED = 0.24              # 시나리오에서 영업이익 → 순이익 환산에 쓰는 법인세율(가정, 한국 최고 법인세율 수준)


def window(ctx, n=10):
    """보고서의 기본 분석 기간: 사업보고서가 나온 마지막 n개 사업연도 (예: 2016~2025)."""
    years = [r["year"] for r in ctx["annual"] if r["values"].get("revenue") is not None]
    return years[-n:]


def _g(dct, *keys):
    for k in keys:
        if dct is None:
            return None
        dct = dct.get(k) if isinstance(dct, dict) else None
    return dct


# ---------------------------------------------------------------------------
# 1. 영업이익 증감 분해: 매출 규모 효과 · 원가율 효과 · 판관비율 효과
# ---------------------------------------------------------------------------
def op_bridge(v, start, end):
    """start년 → end년 영업이익 변화를 나눕니다(정확한 항등식).
    규모 효과 = (매출 변화) × start년 영업이익률, 원가율 효과 = −(원가율 변화) × end년 매출, 판관비율 효과도 같은 방식,
    기타 = 영업이익 − (매출총이익 − 판관비)의 변화(현대건설은 거의 0)."""
    r0, r1 = v.a(start, "revenue"), v.a(end, "revenue")
    o0, o1 = v.a(start, "operating_profit"), v.a(end, "operating_profit")
    c0, c1 = v.a(start, "cost_of_sales"), v.a(end, "cost_of_sales")
    s0, s1 = v.a(start, "sga"), v.a(end, "sga")
    if None in (r0, r1, o0, o1, c0, c1, s0, s1) or not r0 or not r1:
        return None
    m0 = o0 / r0
    volume = (r1 - r0) * m0
    cost = -(c1 / r1 - c0 / r0) * r1
    sga = -(s1 / r1 - s0 / r0) * r1
    other = (o1 - o0) - volume - cost - sga
    return {"start": start, "end": end, "op0": o0, "op1": o1, "d_op": o1 - o0, "volume": volume, "cost": cost, "sga": sga,
            "other": other, "rev0": r0, "rev1": r1, "cost_ratio0": c0 / r0 * 100, "cost_ratio1": c1 / r1 * 100,
            "sga_ratio0": s0 / r0 * 100, "sga_ratio1": s1 / r1 * 100}


def op_bridges(v, years):
    rows = [op_bridge(v, a, b) for a, b in zip(years, years[1:])]
    return [r for r in rows if r]


# ---------------------------------------------------------------------------
# 2. 사업부문 · 본사/자회사
# ---------------------------------------------------------------------------
def segments(dr, years):
    """연도별 부문 매출·매출총이익·매출총이익률(연결)과, 같은 부문의 본사(별도)·본사 외(연결 − 별도) 매출총이익."""
    out = []
    for y in years:
        c = _g(dr, "segments", str(y))
        if not c:
            continue
        s = _g(dr, "segments_separate", str(y))
        row = {"year": y, "basis": c.get("basis"), "receipt": c.get("receipt"), "rev": {}, "gp": {}, "margin": {},
               "gp_parent": {}, "gp_others": {}, "rev_parent": {}}
        for k in SEG + ("adjust", "total"):
            rv, gp = c["revenue"].get(k), c["gross_profit"].get(k)
            row["rev"][k], row["gp"][k] = rv, gp
            row["margin"][k] = gp / rv * 100 if rv and gp is not None and rv > 0 and k != "adjust" else None
            if s:
                sp, sr = s["gross_profit"].get(k), s["revenue"].get(k)
                row["gp_parent"][k], row["rev_parent"][k] = sp, sr
                row["gp_others"][k] = gp - sp if gp is not None and sp is not None else None
        out.append(row)
    return out


def segment_change(seg_rows, a, b):
    """a년 → b년 부문별 매출총이익 변화(연결). 합계 변화 = 부문 변화의 합 + 연결조정 변화."""
    ra = next((r for r in seg_rows if r["year"] == a), None)
    rb = next((r for r in seg_rows if r["year"] == b), None)
    if not ra or not rb:
        return None
    d = {k: (rb["gp"].get(k) or 0) - (ra["gp"].get(k) or 0) for k in SEG + ("adjust", "total")}
    return {"start": a, "end": b, "d": d}


def entity_split(ctx, dr, years):
    """연결 영업이익 = 현대건설 본사(별도) + 현대엔지니어링(종속회사 연결, 내부거래 제거 전) + 그 밖의 종속회사·연결조정.
    마지막 칸은 차이로 계산한 값이라 다른 자회사 이익과 내부거래 제거가 섞여 있습니다."""
    v = an.View(ctx)
    sep = (ctx.get("business") or {}).get("separate") or {}
    out = []
    for y in years:
        cons_op, cons_rev = v.a(y, "operating_profit"), v.a(y, "revenue")
        parent = sep.get(str(y)) or {}
        sub = _g(dr, "subsidiary", str(y)) or {}
        p_op, h_op = parent.get("operating_profit"), sub.get("operating_profit")
        row = {"year": y, "cons_op": cons_op, "cons_rev": cons_rev, "parent_op": p_op, "parent_rev": parent.get("revenue"),
               "hec_op": h_op, "hec_rev": sub.get("revenue"), "hec_ni": sub.get("net_income"), "hec_cfo": sub.get("cfo"),
               "cons_ni": v.a(y, "net_income"), "owners_ni": v.a(y, "net_income_owners"), "cons_cfo": v.a(y, "operating_cashflow")}
        row["rest_op"] = cons_op - p_op - h_op if None not in (cons_op, p_op, h_op) else None
        row["nci_ni"] = row["cons_ni"] - row["owners_ni"] if None not in (row["cons_ni"], row["owners_ni"]) else None
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 3. 원가 추정 변경 (건설계약 주석)
# ---------------------------------------------------------------------------
def estimate_effects(ctx, dr, years):
    """연도별 '진행 중 공사의 총계약수익·원가 추정 변경이 그해 세전이익에 준 영향'(회사 공시)과 매출 대비 크기."""
    v = an.View(ctx)
    out = []
    for y in years:
        e = _g(dr, "estimates", str(y))
        if not e:
            continue
        by = e["by"]
        sep = _g(dr, "estimates_separate", str(y), "by") or {}
        tot = by.get("total", {})
        rev = v.a(y, "revenue")
        row = {"year": y, "receipt": e.get("receipt"), "basis": e.get("basis"),
               "current": tot.get("pl_current"), "future": tot.get("pl_future"), "loss_prov": tot.get("loss_prov"),
               "cost_change": tot.get("cost_change"), "rev_change": tot.get("rev_change"),
               "by_seg": {k: (by.get(k) or {}).get("pl_current") for k in SEG if k in by},
               "parent": (sep.get("total") or {}).get("pl_current"),
               "op": v.a(y, "operating_profit"), "revenue": rev}
        row["pct_rev"] = row["current"] / rev * 100 if row["current"] is not None and rev else None
        row["others"] = row["current"] - row["parent"] if None not in (row["current"], row["parent"]) else None
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 4. 현금: 이익과 현금의 차이 · 운전자본 · 자본배분
# ---------------------------------------------------------------------------
def cash_bridge(ctx, dr, years):
    """EBITDA(영업이익+감가상각) → 영업에서 창출된 현금(이자·세금 전) → 영업활동현금흐름.
    둘의 차이는 운전자본 변화 등입니다. 재무상태표 변화로 본 운전자본(받을 돈·미리 받은 돈·매입채무)도 함께 돌려줍니다."""
    v = an.View(ctx)
    out = []
    for y in years:
        cf = _g(dr, "cashflow", str(y)) or {}
        ebitda = v.a(y, "ebitda")
        row = {"year": y, "op": v.a(y, "operating_profit"), "ebitda": ebitda, "generated": cf.get("cash_generated"),
               "cfo": v.a(y, "operating_cashflow"), "interest_paid": cf.get("interest_paid"),
               "interest_received": cf.get("interest_received"), "tax_paid": cf.get("tax_paid")}
        row["wc_gap"] = row["generated"] - ebitda if None not in (row["generated"], ebitda) else None
        for key, name in (("receivables_total", "d_receivables"), ("advances_total", "d_advances"), ("trade_payables", "d_payables")):
            a, b = v.a(y - 1, key), v.a(y, key)
            row[name] = b - a if None not in (a, b) else None
        out.append(row)
    return out


ALLOC = (  # (키, 보고서 이름, 원천(+)·사용(−) 방향은 금액 부호 그대로)
    ("cfo", "영업활동현금흐름"), ("capex", "설비·무형자산·투자부동산 투자"), ("equity_net", "지분 투자(순)"),
    ("fin_net", "기타 금융자산 투자(순)"), ("loans", "대여금·보증금(순)"), ("asset_sale", "유형자산 등 처분"),
    ("dividends", "배당금 지급"), ("lease", "리스부채 상환"), ("borrow", "차입·사채(순)"), ("equity_tx", "증자·비지배지분 거래"),
    ("deposits", "예금·단기금융상품(순)"), ("other", "기타(환율 효과 포함)"))


def capital_allocation(ctx, dr, years):
    """연도별 현금의 원천과 사용(재무제표 API 현금흐름표, 연결). 모든 칸을 더하면 현금및현금성자산 증감과 같습니다."""
    v = an.View(ctx)
    rows = []
    for y in years:
        cf = _g(dr, "cashflow", str(y))
        if not cf or cf.get("cfo") is None:
            continue
        r = {"year": y, "cfo": cf["cfo"], "capex": cf.get("capex", 0), "equity_net": cf.get("equity_invest", 0) + cf.get("equity_sale", 0),
             "fin_net": cf.get("fin_invest", 0) + cf.get("fin_sale", 0), "loans": cf.get("loans", 0), "asset_sale": cf.get("asset_sale", 0),
             "dividends": cf.get("dividends", 0), "lease": cf.get("lease", 0), "borrow": cf.get("borrow", 0),
             "equity_tx": cf.get("equity_tx", 0), "deposits": cf.get("deposits", 0)}
        cash_now, cash_before = v.a(y, "cash"), v.a(y - 1, "cash")
        flows = sum(r[k] for k in r if k != "year")
        r["cash_change"] = cash_now - cash_before if None not in (cash_now, cash_before) else None
        r["other"] = (r["cash_change"] - flows) if r["cash_change"] is not None else (cf.get("other_invest") or 0) + (cf.get("other_fin") or 0)
        rows.append(r)
    return rows


def allocation_sum(rows, start, end):
    keep = [r for r in rows if start <= r["year"] <= end]
    if not keep:
        return None
    return {"start": start, "end": end, "years": len(keep), **{k: sum(r.get(k) or 0 for r in keep) for k, _ in ALLOC},
            "cash_change": sum(r.get("cash_change") or 0 for r in keep)}


# ---------------------------------------------------------------------------
# 5. 금융비용: 이자비용 = 금리 효과 + 차입 규모 효과
# ---------------------------------------------------------------------------
def interest_bridge(v, start, end):
    """이자비용 ÷ 평균 차입금 = 평균 차입 이자율(계산값). 이자비용 변화 = (이자율 변화 × 올해 평균 차입금) + (작년 이자율 × 평균 차입금 변화)."""
    def avg_debt(y):
        a, b = v.a(y, "borrowings_total"), v.a(y - 1, "borrowings_total")
        return (a + b) / 2 if None not in (a, b) else None
    i0, i1 = v.a(start, "interest_expense"), v.a(end, "interest_expense")
    d0, d1 = avg_debt(start), avg_debt(end)
    if None in (i0, i1, d0, d1) or not d0 or not d1:
        return None
    r0, r1 = i0 / d0, i1 / d1
    return {"start": start, "end": end, "int0": i0, "int1": i1, "rate0": r0 * 100, "rate1": r1 * 100, "debt0": d0, "debt1": d1,
            "rate_effect": (r1 - r0) * d1, "volume_effect": r0 * (d1 - d0), "d_int": i1 - i0}


# ---------------------------------------------------------------------------
# 6. 민감도 (가정이 분명한 산수)
# ---------------------------------------------------------------------------
def sensitivities(ctx, dr):
    """원가율 1%p, 매출 10%, 이자율 1%p(회사 공시), 환율 10%(회사 공시)가 영업이익·세전이익에 주는 크기."""
    v = an.View(ctx)
    y = v.years[-1]
    rev, op = v.a(y, "revenue"), v.a(y, "operating_profit")
    m = op / rev if rev else None
    sens = (dr.get("sensitivity") or {})
    last = sens.get(str(y)) or (sens[max(sens)] if sens else {})
    out = {"year": y, "revenue": rev, "op": op, "margin_pct": m * 100 if m is not None else None,
           "cost_1pp": rev * 0.01 if rev else None,
           "revenue_10pct": rev * 0.10 * m if rev and m is not None else None,
           "rate_1pp": _g(last, "rate", "impact"), "fx_10pct": _g(last, "fx", "impact"),
           "sens_year": next((k for k, val in sens.items() if val is last), None)}
    out["cost_vs_op"] = out["cost_1pp"] / op if out["cost_1pp"] and op and op > 0 else None
    return out


# ---------------------------------------------------------------------------
# 7. 조기 경보: 2024년 손실 전에 먼저 나빠진 지표
# ---------------------------------------------------------------------------
def early_warning(ctx, dr, event_year=2024, base=(2016, 2020)):
    """사건 전 2년(event−2, event−1)의 값이 기준 기간 평균보다 나빴는지. 사례가 하나라 '경보였다'는 판정은 이 사건에 한정됩니다."""
    v = an.View(ctx)
    est = {r["year"]: r for r in estimate_effects(ctx, dr, v.years)}
    seg = {r["year"]: r for r in segments(dr, v.years)}
    ent = {r["year"]: r for r in entity_split(ctx, dr, v.years)}

    def plant_margin(y):
        return _g(seg.get(y), "margin", "plant")

    def hec_margin(y):
        r = ent.get(y)
        return r["hec_op"] / r["hec_rev"] * 100 if r and r.get("hec_op") is not None and r.get("hec_rev") else None

    items = [
        ("원가 추정 변경 효과(매출 대비, %)", lambda y: _g(est.get(y), "pct_rev"), "high"),
        ("매출원가율(%)", lambda y: v.a(y, "cost_ratio_pct"), "low"),
        ("플랜트/전력 매출총이익률(%)", plant_margin, "high"),
        ("현대엔지니어링 영업이익률(%)", hec_margin, "high"),
        ("영업활동현금흐름(조 원)", lambda y: (v.a(y, "operating_cashflow") or 0) / T if v.a(y, "operating_cashflow") is not None else None, "high"),
        ("받을 돈 ÷ 매출(%)", lambda y: v.a(y, "receivables_to_revenue_pct"), "low"),
        ("매출증가율(%)", lambda y: v.a(y, "revenue_growth_pct"), "neutral"),
    ]
    rows = []
    for name, fn, good in items:
        basev = [fn(y) for y in range(base[0], base[1] + 1)]
        basev = [x for x in basev if x is not None]
        b = sum(basev) / len(basev) if basev else None
        pre = [fn(event_year - 2), fn(event_year - 1)]
        ev = fn(event_year)
        worse = None
        if b is not None and None not in pre and good != "neutral":
            worse = all((x > b) if good == "low" else (x < b) for x in pre)
        rows.append({"name": name, "base": b, "pre2": pre[0], "pre1": pre[1], "event": ev, "warned": worse, "good": good})
    return {"event_year": event_year, "base": base, "rows": rows}


# ---------------------------------------------------------------------------
# 8. 동종사 같은 해 비교
# ---------------------------------------------------------------------------
def peer_years(ctx, years):
    """{연도: {'own': 영업이익률, 'peers': {회사: 영업이익률}, 'median': 동종사 중앙값, 'cost': {...}}} — 삼성물산은 상사·바이오 등을 함께
    연결해 건설업만의 숫자가 아니어서 중앙값에서 뺍니다(표에는 참고로 둡니다)."""
    v = an.View(ctx)
    hist = ctx.get("peer_history") or {}
    names = {p["stock_code"]: p["name"] for p in ctx["company"].get("peers", [])}
    out = {}
    for y in years:
        peers, cost = {}, {}
        for code, ys in hist.items():
            row = ys.get(y) or ys.get(str(y))
            if row and row.get("operating_margin_pct") is not None:
                peers[names.get(code, code)] = row["operating_margin_pct"]
                cost[names.get(code, code)] = row.get("cost_ratio_pct")
        comparable = sorted(x for n, x in peers.items() if "삼성물산" not in n)
        med = None
        if comparable:
            k = len(comparable)
            med = comparable[k // 2] if k % 2 else (comparable[k // 2 - 1] + comparable[k // 2]) / 2
        out[y] = {"own": v.a(y, "operating_margin_pct"), "own_cost": v.a(y, "cost_ratio_pct"), "peers": peers, "cost": cost,
                  "median": med, "n": len(comparable)}
    return out


# ---------------------------------------------------------------------------
# 9. 시나리오: 수주잔고가 매출이 되는 3년 동안의 이익과 자본
# ---------------------------------------------------------------------------
def scenarios(ctx, base_margin_pct, years_ahead=3, shock=None):
    """최근 4개 분기 매출이 앞으로 3년 유지된다고 놓고(수주잔고가 3년 치 넘게 있어 매출 규모의 근거가 됨),
    영업이익률만 바꿔 누적 영업이익·세후 이익·자본 변화를 셉니다. 예측이 아니라 '이익률이 이 정도면 결과가 이렇다'는 산수입니다.
    shock: (연도, 영업이익률) — 비관 시나리오에서 3년 중 한 해에 다시 오는 '10년 중 가장 나빴던 해'."""
    v = an.View(ctx)
    rev = v.ttm("revenue")
    bal = v.latest_balance()
    equity = bal["values"].get("equity") if bal else None
    d_e = bal["ratios"].get("debt_to_equity_pct") if bal else None
    liab = bal["values"].get("liabilities") if bal else None
    cases = []
    shock_year, shock_m = shock if shock and shock[1] is not None else (None, -3.9)
    shock_word = f"{shock_year}년" if shock_year else "가장 나빴던 해"
    now = base_margin_pct["pessimistic"]
    target = base_margin_pct["optimistic"]
    ramp = [now + (target - now) * (i + 1) / years_ahead for i in range(years_ahead)]
    mapping = [("낙관", f"최근 4개 분기 이익률({now:.1f}%)에서 회사의 2030년 목표({target:.0f}% 이상)까지 3년 동안 고르게 올라간다고 가정", ramp),
               ("기준", "최근 10년 영업이익률 중앙값이 이어진다고 가정", [base_margin_pct["base"]] * years_ahead),
               ("비관", f"최근 4개 분기 이익률이 이어지다가 3년 중 한 해에 {shock_word}(10년 중 가장 나빴던 해) 같은 해가 다시 온다고 가정"
                f"(그해 영업이익률 {an._m(f'{shock_m:.1f}')}%)",
                [base_margin_pct["pessimistic"], shock_m, base_margin_pct["pessimistic"]])]
    for name, why, margins in mapping:
        ops = [rev * m / 100 for m in margins] if rev else []
        op_sum = sum(ops)
        ni_sum = op_sum * (1 - TAX_ASSUMED) if op_sum > 0 else op_sum * (1 - TAX_ASSUMED)
        eq_end = equity + ni_sum if equity is not None else None
        de_end = liab / eq_end * 100 if liab and eq_end else None
        cases.append({"name": name, "why": why, "margins": margins, "op_sum": op_sum, "ni_sum": ni_sum, "equity_end": eq_end,
                      "de_end": de_end})
    return {"revenue": rev, "equity": equity, "de_now": d_e, "liabilities": liab, "years": years_ahead, "cases": cases,
            "tax": TAX_ASSUMED, "shock_year": shock_year, "shock_margin": shock_m}


def margin_bases(v, years):
    ms = sorted(x for x in (v.a(y, "operating_margin_pct") for y in years) if x is not None)
    med = ms[len(ms) // 2] if len(ms) % 2 else (ms[len(ms) // 2 - 1] + ms[len(ms) // 2]) / 2
    ttm = v.ttm("operating_profit")
    ttm_rev = v.ttm("revenue")
    ttm_m = ttm / ttm_rev * 100 if ttm is not None and ttm_rev else ms[-1]
    return {"optimistic": 8.0, "base": med, "pessimistic": ttm_m}


# ---------------------------------------------------------------------------
# 묶음: 보고서와 CSV에 쓰는 값 전체
# ---------------------------------------------------------------------------
def build(ctx):
    dr = ctx.get("drivers") or {}
    v = an.View(ctx)
    years = window(ctx)
    all_years = v.years
    R = {"years": years}
    R["bridges"] = op_bridges(v, years)
    R["bridge_10y"] = op_bridge(v, years[0], years[-1])
    R["segments"] = segments(dr, all_years)
    R["entity"] = entity_split(ctx, dr, years)
    R["estimates"] = estimate_effects(ctx, dr, years)
    R["cash"] = cash_bridge(ctx, dr, years)
    R["alloc"] = capital_allocation(ctx, dr, years)
    first, last = years[0], years[-1]
    worst = min((r for r in R["cash"] if r.get("cfo") is not None), key=lambda r: r["cfo"], default=None)
    split = next((y for y in years if (v.a(y, "operating_cashflow") or 0) < 0 and all((v.a(t, "operating_cashflow") or 0) < 0
                                                                                      for t in range(y, last + 1))), None)
    R["alloc_split"] = split
    R["alloc_sums"] = [s for s in (allocation_sum(R["alloc"], first, (split or last + 1) - 1),
                                   allocation_sum(R["alloc"], split, last) if split else None) if s]
    R["interest"] = [b for b in (interest_bridge(v, a, b) for a, b in zip(years, years[1:])) if b]
    R["interest_span"] = interest_bridge(v, min((y for y in years if v.a(y, "interest_expense")), default=first), last)
    R["sens"] = sensitivities(ctx, dr)
    R["warning"] = early_warning(ctx, dr)
    R["peers"] = peer_years(ctx, years)
    R["bases"] = margin_bases(v, years)
    margins = [(y, v.a(y, "operating_margin_pct")) for y in years if v.a(y, "operating_margin_pct") is not None]
    worst_m = min(margins, key=lambda t: t[1]) if margins else None
    R["scenarios"] = scenarios(ctx, R["bases"], shock=worst_m)
    R["worst_cfo"] = worst
    return R


def csv_tables(R):
    """data/financials/analysis/*.csv 로 저장할 표: {파일 이름: (머리글, 행 목록)} — 금액은 억 원(소수 1자리)."""
    def eok(x):
        return None if x is None else round(x / 1e8, 1)
    out = {}
    out["op_bridge"] = (["연도", "영업이익 변화", "매출 규모 효과", "원가율 효과", "판관비율 효과", "기타", "원가율(%)", "판관비율(%)"],
                        [[b["end"], eok(b["d_op"]), eok(b["volume"]), eok(b["cost"]), eok(b["sga"]), eok(b["other"]),
                          round(b["cost_ratio1"], 2), round(b["sga_ratio1"], 2)] for b in R["bridges"]])
    seg_rows = []
    for r in R["segments"]:
        for k in SEG + ("adjust",):
            seg_rows.append([r["year"], SEG_KO[k], eok(r["rev"].get(k)), eok(r["gp"].get(k)),
                             None if r["margin"].get(k) is None else round(r["margin"][k], 2),
                             eok(r["gp_parent"].get(k)) if r["gp_parent"] else None, eok(r["gp_others"].get(k)) if r["gp_others"] else None,
                             r["receipt"]])
    out["segments"] = (["연도", "부문", "매출", "매출총이익", "매출총이익률(%)", "본사(별도) 매출총이익", "본사 외(연결−별도)", "접수번호"], seg_rows)
    out["entity_split"] = (["연도", "연결 영업이익", "현대건설 본사(별도)", "현대엔지니어링", "그 밖의 종속회사·조정", "연결 순이익",
                            "지배주주 순이익", "비지배지분 몫", "현대엔지니어링 영업활동현금흐름"],
                           [[r["year"], eok(r["cons_op"]), eok(r["parent_op"]), eok(r["hec_op"]), eok(r["rest_op"]), eok(r["cons_ni"]),
                             eok(r["owners_ni"]), eok(r["nci_ni"]), eok(r["hec_cfo"])] for r in R["entity"]])
    out["estimate_changes"] = (["연도", "당기 손익 영향(연결)", "건축/주택", "토목", "플랜트/전력", "현대건설 본사(별도)", "본사 외",
                                "미래 손익 영향", "공사손실충당부채", "매출 대비(%)", "접수번호"],
                               [[r["year"], eok(r["current"]), eok(r["by_seg"].get("building")), eok(r["by_seg"].get("civil")),
                                 eok(r["by_seg"].get("plant")), eok(r["parent"]), eok(r["others"]), eok(r["future"]), eok(r["loss_prov"]),
                                 None if r["pct_rev"] is None else round(r["pct_rev"], 2), r["receipt"]] for r in R["estimates"]])
    out["cash_bridge"] = (["연도", "영업이익", "EBITDA", "영업에서 창출된 현금", "차이(운전자본 등)", "영업활동현금흐름",
                           "받을 돈 증감", "미리 받은 돈 증감", "매입채무 증감"],
                          [[r["year"], eok(r["op"]), eok(r["ebitda"]), eok(r["generated"]), eok(r["wc_gap"]), eok(r["cfo"]),
                            eok(r["d_receivables"]), eok(r["d_advances"]), eok(r["d_payables"])] for r in R["cash"]])
    out["capital_allocation"] = (["연도"] + [name for _, name in ALLOC] + ["현금 증감"],
                                 [[r["year"]] + [eok(r.get(k)) for k, _ in ALLOC] + [eok(r.get("cash_change"))] for r in R["alloc"]])
    return out
