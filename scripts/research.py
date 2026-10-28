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
BRIDGE_METHODS = (
    ("start", "앞 해 이익률 · 뒤 해 매출 기준", "규모 = ΔR × m₀ , 원가율 = −Δc × R₁"),
    ("end", "뒤 해 이익률 · 앞 해 매출 기준", "규모 = ΔR × m₁ , 원가율 = −Δc × R₀"),
    ("mid", "두 해 평균 기준(본문에 쓰는 값)", "규모 = ΔR × (m₀+m₁)/2 , 원가율 = −Δc × (R₀+R₁)/2"),
)


def _bridge(r0, r1, o0, o1, c0, c1, s0, s1, method="mid"):
    """영업이익 변화 = 규모 효과 + 원가율 효과 + 판관비율 효과 + 기타(영업이익 − 매출총이익 + 판관비의 비율 변화).
    네 칸의 합은 어느 방법이든 영업이익 변화와 정확히 같고, 칸끼리 나누는 몫만 방법에 따라 다릅니다(교차항을 어디에 붙이느냐의 차이)."""
    m0, m1 = o0 / r0, o1 / r1
    dc = c1 / r1 - c0 / r0
    ds = s1 / r1 - s0 / r0
    if method == "start":
        mv, rb = m0, r1
    elif method == "end":
        mv, rb = m1, r0
    else:                       # 중간값(평균) 방식: 계산 순서에 따라 결과가 달라지지 않습니다
        mv, rb = (m0 + m1) / 2, (r0 + r1) / 2
    volume = (r1 - r0) * mv
    cost = -dc * rb
    sga = -ds * rb
    other = (o1 - o0) - volume - cost - sga
    return volume, cost, sga, other


def op_bridge(v, start, end, method="mid"):
    """start년 → end년 영업이익 변화를 나눕니다(합이 정확히 맞는 회계 항등식 — 원인 판정이 아님).
    기본은 두 해 평균 이익률·평균 매출을 쓰는 중간값 방식이고, method='start'·'end'는 앞·뒤 해 기준(민감도 확인용)."""
    r0, r1 = v.a(start, "revenue"), v.a(end, "revenue")
    o0, o1 = v.a(start, "operating_profit"), v.a(end, "operating_profit")
    c0, c1 = v.a(start, "cost_of_sales"), v.a(end, "cost_of_sales")
    s0, s1 = v.a(start, "sga"), v.a(end, "sga")
    if None in (r0, r1, o0, o1, c0, c1, s0, s1) or not r0 or not r1:
        return None
    volume, cost, sga, other = _bridge(r0, r1, o0, o1, c0, c1, s0, s1, method)
    return {"start": start, "end": end, "method": method, "op0": o0, "op1": o1, "d_op": o1 - o0, "volume": volume, "cost": cost,
            "sga": sga, "other": other, "rev0": r0, "rev1": r1, "cost_ratio0": c0 / r0 * 100, "cost_ratio1": c1 / r1 * 100,
            "sga_ratio0": s0 / r0 * 100, "sga_ratio1": s1 / r1 * 100}


def abs_shares(rows):
    """연간 효과들의 절댓값 합계 중 각 효과의 몫(%). '변화의 크기를 누가 많이 만들었나'를 보는 값이지 방향(+/−)은 담지 않습니다."""
    keys = ("volume", "cost", "sga", "other")
    tot = sum(abs(r[k]) for r in rows for k in keys)
    return {k: (sum(abs(r[k]) for r in rows) / tot * 100 if tot else None) for k in keys}


def bridge_robustness(v, years):
    """본문 분해(중간값)가 계산 방법·기간을 바꿔도 같은 결론(원가율 효과 > 규모 효과)인지 확인합니다."""
    out = {"methods": [], "windows": []}
    a, b = years[0], years[-1]
    for method, label, formula in BRIDGE_METHODS:
        annual = [r for r in (op_bridge(v, x, y, method) for x, y in zip(years, years[1:])) if r]
        out["methods"].append({"method": method, "label": label, "formula": formula, "whole": op_bridge(v, a, b, method),
                               "annual_sum": {k: sum(r[k] for r in annual) for k in ("volume", "cost", "sga", "other")},
                               "abs_share": abs_shares(annual)})

    def avg(group, key):
        vals = [v.a(y, key) for y in group]
        return sum(vals) / len(vals) if vals and None not in vals else None

    groups = [(f"{years[0]}~{years[2]} 평균 → {years[-3]}~{years[-1]} 평균", years[:3], years[-3:]),
              (f"{years[1]} → {years[-1]}", [years[1]], [years[-1]]),
              (f"{years[0]} → {years[-3]} (2024·2025 제외)", [years[0]], [years[-3]]),
              (f"{years[3]} → {years[-1]}", [years[3]], [years[-1]])]
    for label, g0, g1 in groups:
        vals = [avg(g, k) for g in (g0, g1) for k in ("revenue", "operating_profit", "cost_of_sales", "sga")]
        r0, o0, c0, s0, r1, o1, c1, s1 = vals
        if None in vals or not r0 or not r1:
            continue
        volume, cost, sga, other = _bridge(r0, r1, o0, o1, c0, c1, s0, s1, "mid")
        out["windows"].append({"label": label, "d_op": o1 - o0, "volume": volume, "cost": cost, "sga": sga, "other": other,
                               "cost_ratio0": c0 / r0 * 100, "cost_ratio1": c1 / r1 * 100})
    return out


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
        # 공시 표의 항등식: 총계약수익 추정 변경 − 총계약원가 추정 변경 = 당기 손익 영향 + 미래 손익 영향 (공사 전체 기간의 이익 변화)
        row["lifetime"] = row["current"] + row["future"] if None not in (row["current"], row["future"]) else None
        row["identity_gap"] = ((row["rev_change"] - row["cost_change"]) - row["lifetime"]
                               if None not in (row["rev_change"], row["cost_change"], row["lifetime"]) else None)
        out.append(row)
    return out


# ---------------------------------------------------------------------------
# 4. 현금: 이익과 현금의 차이 · 운전자본 · 자본배분
# ---------------------------------------------------------------------------
CF_ADJ = (("dep_amort", "감가상각·상각"), ("provisions", "충당부채 전입−환입"), ("impairment", "대손·손상"),
          ("interest_tax", "이자·법인세·배당 손익 되돌림"), ("fx", "외화환산·파생"), ("employee", "퇴직급여 등"), ("other_adj", "기타 조정"))
CF_WC = (("receivables", "매출채권(공사미수금 등)"), ("contract_assets", "계약자산(미청구공사)"), ("other_receivables", "기타채권·장기채권"),
         ("inventories", "재고자산"), ("payables", "매입채무"), ("other_payables", "기타채무"),
         ("contract_liabilities", "계약부채(초과청구공사)"), ("advances", "공사·분양 선수금"), ("provisions_used", "충당부채·퇴직급여 사용"),
         ("other_wc", "기타 자산·부채"))


def cash_bridge(ctx, dr, years):
    """영업활동현금흐름 = 당기순이익 + 비현금 조정 + 운전자본 변동(= 영업으로부터 창출된 현금) + 이자·배당 수취 − 이자 지급 − 법인세 납부.
    앞 세 칸은 연결 현금흐름표 주석('영업으로부터 창출된 현금') 그대로이고, 뒤 칸은 현금흐름표 본문입니다.
    check = 계산한 영업활동현금흐름 − 재무제표의 영업활동현금흐름 (0이어야 맞음)."""
    v = an.View(ctx)
    out = []
    for y in years:
        g = _g(dr, "cash_generated", str(y))
        cf = _g(dr, "cashflow", str(y)) or {}
        if not g:
            continue
        row = {"year": y, "basis": g.get("basis"), "receipt": g.get("receipt"), "ni": g["net_income"], "adj": dict(g["adj"]),
               "wc": dict(g["wc"]), "adj_total": sum(g["adj"].values()), "wc_total": sum(g["wc"].values()),
               "generated": g["cash_generated"], "op": v.a(y, "operating_profit"), "ebitda": v.a(y, "ebitda"),
               "interest_received": cf.get("interest_received") or 0, "interest_paid": cf.get("interest_paid") or 0,
               "dividends_received": cf.get("dividends_received") or 0, "tax_paid": cf.get("tax_paid") or 0,
               "cfo": v.a(y, "operating_cashflow"), "ni_api": v.a(y, "net_income")}
        row["int_tax"] = row["interest_received"] + row["interest_paid"] + row["dividends_received"] + row["tax_paid"]
        row["cfo_calc"] = row["generated"] + row["int_tax"]
        row["check"] = row["cfo_calc"] - row["cfo"] if row["cfo"] is not None else None
        row["ni_check"] = row["ni"] - row["ni_api"] if row["ni_api"] is not None else None
        # 재무상태표로 본 변화(기말 − 기초)와 현금흐름표 주석의 같은 계정 줄 비교 — 손상·환산·대체·연결범위 변동 때문에 다를 수 있습니다
        bs = {}
        for key, wc_key in (("trade_receivables", "receivables"), ("contract_assets", "contract_assets"),
                            ("contract_liabilities", "contract_liabilities"), ("trade_payables", "payables")):
            a, b = v.a(y - 1, key), v.a(y, key)
            bs[wc_key] = b - a if None not in (a, b) else None
        row["bs_delta"] = bs
        out.append(row)
    return out


def cash_window(rows, start, end):
    """cash_bridge 행들을 start~end년으로 더한 값."""
    keep = [r for r in rows if start <= r["year"] <= end]
    if not keep:
        return None
    flat = ("ni", "adj_total", "wc_total", "generated", "interest_received", "interest_paid", "dividends_received", "tax_paid",
            "int_tax", "cfo", "cfo_calc")
    out = {"start": start, "end": end, "years": len(keep), **{k: sum(r[k] or 0 for r in keep) for k in flat}}
    out["adj"] = {k: sum(r["adj"].get(k, 0) for r in keep) for k, _ in CF_ADJ}
    out["wc"] = {k: sum(r["wc"].get(k, 0) for r in keep) for k, _ in CF_WC}
    return out


def _scale_ratio(stock0, stock1, rev0, rev1):
    """잔액 변화 = 매출 규모 효과 + (잔액 ÷ 매출) 비율 효과 — 두 해 평균을 쓰는 중간값 방식(합이 정확히 맞음)."""
    if None in (stock0, stock1, rev0, rev1) or not rev0 or not rev1:
        return None
    k0, k1 = stock0 / rev0, stock1 / rev1
    return {"s0": stock0, "s1": stock1, "d": stock1 - stock0, "k0": k0 * 100, "k1": k1 * 100,
            "scale": (rev1 - rev0) * (k0 + k1) / 2, "ratio": (k1 - k0) * (rev0 + rev1) / 2}


def receivables_view(ctx, dr, years, base=None):
    """받을 돈이 왜 늘었나: 매출채권 연령분석(연결) · 공사미수금/분양미수금 · 매출 대비 비율 · 규모/비율 분해(base년 말 → 마지막 해 말)."""
    v = an.View(ctx)
    rows = []
    for y in years:
        ag = _g(dr, "receivable_aging", str(y))
        mx = _g(dr, "receivable_mix", str(y))
        r = {"year": y, "revenue": v.a(y, "revenue"), "trade": v.a(y, "trade_receivables"), "contract_assets": v.a(y, "contract_assets"),
             "advances": v.a(y, "advances_total"), "receivables_total": v.a(y, "receivables_total")}
        r["net_contract"] = r["receivables_total"] - r["advances"] if None not in (r["receivables_total"], r["advances"]) else None
        if ag:
            b = ag["buckets"]
            r.update(aging=b, aging_labels=ag.get("labels") or [], allowance=ag["allowance"], aging_net=ag["net"],
                     gross=sum(b.values()), beyond_first=b["b1"] + b["b2"] + b["b3"], over_1y=b["b2"] + b["b3"],
                     aging_receipt=ag.get("receipt"), aging_basis=ag.get("basis"))
        if mx:
            r.update(construction=mx["construction"], construction_allowance=mx["construction_allowance"], sales=mx["sales"],
                     mix_receipt=mx.get("receipt"))
        rows.append(r)
    by = {r["year"]: r for r in rows}
    last = years[-1]
    split = {}
    if base is not None:
        r0 = by.get(base) or {"revenue": v.a(base, "revenue"), "trade": v.a(base, "trade_receivables"),
                               "receivables_total": v.a(base, "receivables_total"), "advances": v.a(base, "advances_total")}
        if r0.get("receivables_total") is not None and r0.get("advances") is not None:
            r0["net_contract"] = r0["receivables_total"] - r0["advances"]
        r1 = by.get(last, {})
        for key in ("trade", "receivables_total", "net_contract"):
            split[key] = _scale_ratio(r0.get(key), r1.get(key), r0.get("revenue"), r1.get("revenue"))
    return {"rows": rows, "base": base, "last": last, "split": split}


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
           "rate_measure": _g(last, "rate", "measure"), "fx_measure": _g(last, "fx", "measure"),
           "rate_scope": _g(last, "rate", "scope"), "fx_scope": _g(last, "fx", "scope"),
           "sens_receipt": last.get("receipt") if isinstance(last, dict) else None,
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
    R["bridge_robust"] = bridge_robustness(v, years)
    R["bridge_shares"] = abs_shares(R["bridges"])
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
    R["cash_windows"] = [w for w in (cash_window(R["cash"], first, (split or last + 1) - 1),
                                     cash_window(R["cash"], split, last) if split else None,
                                     cash_window(R["cash"], first, last)) if w]
    R["receivables"] = receivables_view(ctx, dr, years, base=(split - 1) if split else None)
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
    R["verification"] = verification(ctx, R)
    return R


# ---------------------------------------------------------------------------
# 10. 핵심 숫자 검증표: 숫자마다 출처 · 기준 · 원문 값 · 계산 방법
# ---------------------------------------------------------------------------
def _filings(ctx):
    """접수번호 → (보고서 이름, 접수일) — 표에 실린 연간·반기·분기 행에서 모읍니다."""
    out = {}
    for rows in (ctx.get("annual") or [], ctx.get("halves") or [], ctx.get("quarters") or []):
        for r in rows:
            if r.get("receipt"):
                out.setdefault(r["receipt"], (r.get("report_name") or "", r.get("filed") or ""))
    lf = ctx.get("latest_filing") or {}
    if lf.get("rcept_no"):
        out.setdefault(lf["rcept_no"], (lf.get("report_nm", "").strip(), lf.get("rcept_dt", "")))
    return out


def verification(ctx, R):
    """[{item, kind('공시'|'계산'), basis, receipts[], original, method, value, unit}] — 보고서의 핵심 숫자를 원문으로 되짚을 수 있게."""
    v = an.View(ctx)
    dr = ctx.get("drivers") or {}
    years = R["years"]
    y0, yl = years[0], years[-1]
    ann = {r["year"]: r for r in ctx.get("annual") or []}
    files = _filings(ctx)
    rows = []

    def mil(x):
        """원문 표기처럼: 백만원 단위, 음수는 괄호."""
        if x is None:
            return None
        m = round(x / 1e6)
        return f"({abs(m):,})백만원" if m < 0 else f"{m:,}백만원"

    def add(item, kind, basis, receipts, original, method, value, unit="원", fmt="jo"):
        """fmt: 보고서 본문과 같은 표기 방식(jo · sjo · seok · pct · won) — 검증표와 본문이 같은 글자로 보이게."""
        receipts = [r for r in receipts if r]
        rows.append({"item": item, "kind": kind, "basis": basis, "receipts": receipts,
                     "sources": [(r, *files.get(r, ("", ""))) for r in receipts], "original": original, "method": method,
                     "value": value, "unit": unit, "fmt": fmt})

    for y, key, name in ((y0, "revenue", "매출액"), (yl, "revenue", "매출액"), (2024, "operating_profit", "영업이익"), (yl, "operating_profit", "영업이익")):
        x = v.a(y, key)
        add(f"{y}년 {name}", "공시", "연결 손익계산서", [ann.get(y, {}).get("receipt")], mil(x), "재무제표 API(CFS) 값 그대로", x,
            fmt="jo1" if key == "revenue" else "jo")       # 매출은 표지·본문처럼 소수 한 자리
    b = R.get("bridge_10y")
    if b:
        add(f"{y0}→{yl}년 영업이익 변화 중 원가율 효과", "계산", "연결", [ann.get(y0, {}).get("receipt"), ann.get(yl, {}).get("receipt")],
            f"매출·매출원가·영업이익({y0}·{yl}년)", "−(원가율 변화) × 두 해 평균 매출 (6-1)", b["cost"], fmt="sjo")
        add(f"{y0}→{yl}년 영업이익 변화 중 매출 규모 효과", "계산", "연결", [ann.get(y0, {}).get("receipt"), ann.get(yl, {}).get("receipt")],
            "같은 입력", "매출 변화 × 두 해 평균 영업이익률 (6-1)", b["volume"], fmt="sjo")
    sh = R.get("bridge_shares") or {}
    if sh.get("cost") is not None:
        add("연간 영업이익 변화 크기 중 원가율 효과의 몫", "계산", "연결", [], f"{len(R['bridges'])}개 연도의 분해", "Σ|원가율 효과| ÷ Σ(|각 효과|)", sh["cost"], "%", fmt="pct")
    est = {r["year"]: r for r in R.get("estimates") or []}
    if 2024 in est:
        add("2024년 원가 추정 변경의 그해 세전손익 영향", "공시", "연결 주석(건설계약)", [est[2024]["receipt"]], mil(est[2024]["current"]),
            "‘당기 손익에 미치는 영향’ 합계 칸 그대로", est[2024]["current"])
    if est:
        add(f"{y0}~{yl}년 원가 추정 변경 그해 영향의 합", "계산", "연결 주석(건설계약)", [est[y]["receipt"] for y in years if y in est],
            "해마다의 ‘당기 손익에 미치는 영향’", "10개 연도 단순 합(누적 손실 아님 — 6-2)", sum(est[y]["current"] for y in years if y in est))
        add(f"{y0}~{yl}년 공사 전체 이익 변화의 합", "계산", "연결 주석(건설계약)", [], "‘당기’ + ‘미래’ 손익 영향",
            "= 총계약수익 변경 − 총계약원가 변경(해마다 차이 0)", sum(est[y]["lifetime"] or 0 for y in years if y in est))
    cw = next((w for w in R.get("cash_windows") or [] if w["start"] == R.get("alloc_split") and w["end"] == yl), None)
    if cw:
        rc_ = [r["receipt"] for r in R["cash"] if cw["start"] <= r["year"] <= yl]
        add(f"{cw['start']}~{yl}년 영업활동현금흐름 합계", "계산", "연결 현금흐름표", [ann.get(y, {}).get("receipt") for y in range(cw["start"], yl + 1)],
            " · ".join(mil(v.a(y, "operating_cashflow")) for y in range(cw["start"], yl + 1)), "연도별 공시 값의 합", cw["cfo"])
        add(f"{cw['start']}~{yl}년 운전자본 변동 합계", "계산", "연결 주석(현금흐름표)", rc_, "‘영업활동으로 인한 자산부채의 변동’ 소계",
            "연도별 소계의 합(구성 합 = 소계 확인)", cw["wc_total"], fmt="sjo")
        add(f"{cw['start']}~{yl}년 매출채권 변동(현금흐름표 주석)", "계산", "연결 주석(현금흐름표)", rc_, "‘매출채권의 감소(증가)’ 줄",
            "연도별 값의 합", cw["wc"]["receivables"], fmt="sjo")
    ag = _g(dr, "receivable_aging", str(yl))
    if ag:
        add(f"{yl}년 말 1년 넘은 매출채권", "공시", "연결 주석(매출채권 연령분석)", [ag.get("receipt")],
            f"{mil(ag['buckets']['b2'])}(1~3년) + {mil(ag['buckets']['b3'])}(3년 초과)", "두 구간의 합", ag["buckets"]["b2"] + ag["buckets"]["b3"])
    sens = R.get("sens") or {}
    if sens.get("rate_1pp") is not None:
        add("금리 1%p 상승 시 영향", "공시", f"연결 · {sens.get('rate_scope')} · {sens.get('rate_measure')}", [sens.get("sens_receipt")], mil(sens["rate_1pp"]),
            "위험관리 주석의 ‘1% 상승시’ 합계", sens["rate_1pp"], fmt="seok")
    if sens.get("fx_10pct") is not None:
        add("원화 환율 10% 상승 시 영향", "공시", f"연결 · {sens.get('fx_scope')} · {sens.get('fx_measure')}", [sens.get("sens_receipt")], mil(sens["fx_10pct"]),
            "위험관리 주석의 ‘10% 상승시’ 합계(세전이익이 아님)", sens["fx_10pct"], fmt="seok")
    sub = _g(dr, "subsidiary", "2024")
    if sub:
        add("2024년 현대엔지니어링 영업이익", "공시", "연결 주석(비지배지분 요약, 내부거래 제거 전)", [sub.get("receipt")], mil(sub.get("operating_profit")),
            "요약 재무정보 값 그대로", sub.get("operating_profit"))
    biz = ctx.get("business") or {}
    pf = biz.get("pf") or {}
    if pf:
        p_ = max(pf)
        add(f"PF 보증({p_})", "공시", "Ⅺ 우발부채(보증금액 기준)", [pf[p_].get("receipt")], mil(pf[p_].get("amount")), "신용보강 표의 합계", pf[p_].get("amount"), fmt="jo1")
    div = _g(dr, "dividends", str(yl))
    if div and div.get("dps"):
        add(f"{yl}년 보통주 주당 배당금", "공시", "배당에 관한 사항", [div.get("receipt")], f"{div['dps']:,}원", "값 그대로", div["dps"], "원/주", fmt="won")
    rt = _g(dr, "revenue_types", str(yl))
    if rt and rt.get("total"):
        add(f"{yl}년 매출 중 도급공사 비중", "계산", "연결 주석(수익의 구분)", [rt.get("receipt")], f"{mil(rt['contract'])} ÷ {mil(rt['total'])}",
            "도급공사수익 ÷ 매출", rt["contract"] / rt["total"] * 100, "%", fmt="pct")
    return rows


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
    out["estimate_changes"] = (["연도", "총계약수익 추정 변경", "총계약원가 추정 변경", "공사 전체 이익 변화(당기+미래)", "당기 손익 영향(연결, 세전)",
                                "건축/주택", "토목", "플랜트/전력", "현대건설 본사(별도)", "본사 외", "미래 손익 영향", "공사손실충당부채",
                                "매출 대비(%)", "항등식 차이(수익 변경 − 원가 변경 − 당기 − 미래)", "접수번호"],
                               [[r["year"], eok(r["rev_change"]), eok(r["cost_change"]), eok(r["lifetime"]), eok(r["current"]),
                                 eok(r["by_seg"].get("building")), eok(r["by_seg"].get("civil")), eok(r["by_seg"].get("plant")), eok(r["parent"]),
                                 eok(r["others"]), eok(r["future"]), eok(r["loss_prov"]), None if r["pct_rev"] is None else round(r["pct_rev"], 2),
                                 eok(r["identity_gap"]), r["receipt"]] for r in R["estimates"]])
    out["cash_bridge"] = (["연도", "당기순이익"] + [f"조정: {n}" for _, n in CF_ADJ] + [f"운전자본: {n}" for _, n in CF_WC]
                          + ["영업으로부터 창출된 현금", "이자·배당 수취", "이자 지급", "법인세 납부", "영업활동현금흐름(계산)",
                             "영업활동현금흐름(재무제표)", "기준", "접수번호"],
                          [[r["year"], eok(r["ni"])] + [eok(r["adj"].get(k)) for k, _ in CF_ADJ] + [eok(r["wc"].get(k)) for k, _ in CF_WC]
                           + [eok(r["generated"]), eok(r["interest_received"] + r["dividends_received"]), eok(r["interest_paid"]),
                              eok(r["tax_paid"]), eok(r["cfo_calc"]), eok(r["cfo"]), "그해 보고서" if r["basis"] == "own" else "다음 해 보고서 전기 숫자",
                              r["receipt"]] for r in R["cash"]])
    rv = R.get("receivables") or {}
    out["receivables"] = (["연도", "매출", "매출채권(재무상태표)", "계약자산(미청구공사)", "초과청구공사+선수금", "공사미수금 총액",
                           "분양미수금 총액", "연령 구간1", "연령 구간2", "1~3년", "3년 초과", "손상차손누계액", "1년 넘은 채권", "구간 이름"],
                          [[r["year"], eok(r["revenue"]), eok(r["trade"]), eok(r["contract_assets"]), eok(r["advances"]),
                            eok(r.get("construction")), eok(r.get("sales")),
                            *([eok(r["aging"][k]) for k in ("b0", "b1", "b2", "b3")] if r.get("aging") else [None] * 4),
                            eok(r.get("allowance")), eok(r.get("over_1y")), " / ".join(r.get("aging_labels") or [])]
                           for r in rv.get("rows", [])])
    out["op_bridge_methods"] = (["방법", "식", "규모 효과", "원가율 효과", "판관비율 효과", "기타", "연간 절댓값 몫: 규모(%)",
                                 "원가율(%)", "판관비율(%)"],
                                [[m["label"], m["formula"], eok(m["whole"]["volume"]), eok(m["whole"]["cost"]), eok(m["whole"]["sga"]),
                                  eok(m["whole"]["other"]), round(m["abs_share"]["volume"], 1), round(m["abs_share"]["cost"], 1),
                                  round(m["abs_share"]["sga"], 1)] for m in (R.get("bridge_robust") or {}).get("methods", []) if m["whole"]])
    out["capital_allocation"] = (["연도"] + [name for _, name in ALLOC] + ["현금 증감"],
                                 [[r["year"]] + [eok(r.get(k)) for k, _ in ALLOC] + [eok(r.get("cash_change"))] for r in R["alloc"]])
    out["verification"] = (["숫자", "공시/계산", "기준", "원문 값", "계산 방법", "값", "단위", "접수번호", "보고서", "접수일"],
                           [[r["item"], r["kind"], r["basis"], r["original"], r["method"],
                             (round(r["value"] / 1e8, 1) if r["unit"] == "원" and r["value"] is not None else
                              (round(r["value"], 2) if isinstance(r["value"], float) else r["value"])),
                             "억 원" if r["unit"] == "원" else r["unit"], " ".join(x[0] for x in r["sources"]),
                             " / ".join(x[1] for x in r["sources"] if x[1]), " / ".join(x[2] for x in r["sources"] if x[2])]
                            for r in R.get("verification") or []])
    return out
