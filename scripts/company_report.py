"""기업분석 보고서(PDF): 사업보고서로 읽는 현대건설.

순서: 표지 → 요약 → 1 돈 버는 구조 → 2 사업보고서 → 3 일감(수주) → 4 이익의 질 → 5 현금·재무 체력
      → 6 재무비율 10가지 관점 → 7 시장의 평가 → 8 종합 의견 → 부록(용어 · 자료와 한계 · 출처)

- 숫자와 문장은 모두 ctx(재무제표 표)와 ctx['business'](사업보고서 본문, business.py)에서 매월 다시 계산합니다.
  제도 설명(입찰 방식 · 진행기준 회계 등)만 고정 문장이고, 출처를 함께 적습니다.
- 차트는 대시보드와 같은 부품(HTML·CSS·SVG)을 쓰고, 인쇄용 CSS를 덧씌운 HTML을 헤드리스 Chrome으로 A4 PDF로 인쇄합니다.
  에이전트는 파이썬 표준 라이브러리만 쓰므로 PDF 그리기는 GitHub Actions 러너에 기본으로 있는 Chrome에 맡깁니다.
- Chrome이나 한글 글꼴이 없는 환경에서는 PDF를 건너뛰고 경고만 남깁니다(이전 PDF는 그대로 둡니다).
- 내용이 같으면 다시 인쇄하지 않습니다. 인쇄한 HTML의 해시를 data/financials/report_pdf.json에 적어 두고 비교합니다
  (PDF는 만들 때마다 파일 안의 날짜가 바뀌어, 매번 새로 만들면 내용이 같아도 커밋이 생기기 때문입니다).
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import analysis as an
import dashboard as d
import lenses as ln
import report_view as rv
import statements as st

T = an.T
esc, rich = d.esc, d.rich
PDF_PATH = d.REPORT_PDF                       # reports/hyundai-company-report.pdf
STATE_PATH = "data/financials/report_pdf.json"


# ---------------------------------------------------------------------------
# 공통 조각
# ---------------------------------------------------------------------------
def edition(ctx):
    y, m = ctx["today"][:4], int(ctx["today"][5:7])
    return f"{y}년 {m}월판"


def chapter(no, en, title, lead, body, cid):
    lead_html = "".join(f'<p class="r-lead">{rich(x)}</p>' for x in ([lead] if isinstance(lead, str) else lead) if x)
    return (f'<section class="r-chap" id="{cid}"><header class="r-head"><span class="r-num">{no}</span>'
            f'<div class="r-tt"><p>{esc(en)}</p><h2>{esc(title)}</h2></div></header>{lead_html}{body}</section>')


def sub(no, title, body, note=None, keep=False):
    """번호 붙은 소제목 + 설명 + 내용. keep=True면 한 쪽 안에 통째로 둡니다(제목만 쪽 끝에 남지 않게)."""
    note_html = f'<p class="r-subnote">{rich(note)}</p>' if note else ""
    num_html = f'<span class="k">{esc(no)}</span> ' if no else ""
    cls = "r-sec keep" if keep else "r-sec"
    return f'<div class="{cls}"><h3>{num_html}{esc(title)}</h3>{note_html}{body}</div>'


def box(title, body, cls=""):
    head = f'<p class="r-h">{esc(title)}</p>' if title else ""
    return f'<div class="r-box {cls}">{head}{body}</div>'


def bullets(items, cls="", raw=False):
    """글머리 목록. raw=True면 이미 HTML로 만든 줄(링크 등)을 그대로 넣습니다."""
    return f'<ul class="r-ul {cls}">{"".join(f"<li>{x if raw else rich(x)}</li>" for x in items if x)}</ul>'


def rtable(headers, rows, cls="", caption=None):
    """보고서용 표. 셀은 이미 HTML로 만든 문자열입니다(rich/esc 사용). 숫자 칸은 ('num', 문자열)로 넘깁니다."""
    th = "".join(f'<th scope="col">{h}</th>' for h in headers)
    body = []
    for row in rows:
        cells = []
        for i, c in enumerate(row):
            kind, text = c if isinstance(c, tuple) else ("", c)
            tag = "th" if i == 0 else "td"
            scope = ' scope="row"' if tag == "th" else ""
            cl = f' class="{kind}"' if kind else ""
            cells.append(f"<{tag}{scope}{cl}>{text}</{tag}>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return f'<table class="r-table {cls}">{cap}<thead><tr>{th}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def num(text, value=None):
    return ("num neg" if isinstance(value, (int, float)) and value < 0 else "num", esc(text))


def link(url, text):
    return f'<a href="{esc(url)}">{esc(text)}</a>'


def dart_link(receipt, text):
    return link(f"{d.DART_VIEW}{receipt}", text)


def ratio_word(r, unit="배"):
    """1.48 → '1.5배로 늘었습니다' · 0.8 → '20% 줄었습니다'."""
    if r >= 1.05:
        return f"{r:.1f}{unit}로 늘었습니다"
    if r <= 0.95:
        return f"{(1 - r) * 100:.0f}% 줄었습니다"
    return "비슷합니다"


# ---------------------------------------------------------------------------
# 여러 장에서 함께 쓰는 숫자
# ---------------------------------------------------------------------------
def facts(ctx):
    a = ctx["analysis"]
    v = an.View(ctx)
    years10 = ln.window_years(ctx)
    biz = rv.biz_of(ctx)
    F = {"a": a, "v": v, "vd": a["verdicts"], "steps": {s["id"]: s for s in a.get("steps", [])},
         "years10": years10, "v10": st.ten_view(ctx, years10), "L": ln.build(ctx), "biz": biz}
    first, last = v.annual[0], v.annual[-1]
    F.update(y0=first["year"], yl=last["year"], rev0=first["values"]["revenue"], revl=last["values"]["revenue"],
             m0=first["ratios"].get("operating_margin_pct"), ml=last["ratios"].get("operating_margin_pct"))
    lb = rv.latest_backlog(ctx)
    F["lb"] = lb
    F["yrs"] = rv.years_of_work(ctx, lb) if lb else None
    F["lb_prev"] = None
    if lb:
        for r in biz.get("backlog") or []:
            if r["year"] == lb["year"] - 1 and r["month"] == lb["month"] and not r.get("flag"):
                F["lb_prev"] = r
    orders = biz.get("orders") or {}
    F["orders"] = orders
    F["oy"] = max(orders) if orders else None
    pf = rv.pf_rows(ctx)
    F["pf"] = pf
    F["pf_x"] = None
    if pf:
        p, r = pf[-1]
        b = rv.balance_at(ctx, int(p[:4]), int(p[5:]))
        F["pf_x"] = r["amount"] / b["values"]["equity"] if b else None
    costs = [(t, v.a(t, "cost_ratio_pct")) for t in v.years if v.a(t, "cost_ratio_pct") is not None]
    F["worst_cost"] = max(costs, key=lambda x: x[1]) if costs else None
    F["bal"] = v.latest_balance()
    F["projects"] = (biz.get("projects") or {}).get("rows") or []
    return F


def thesis(F):
    parts = []
    lb, yrs = F["lb"], F["yrs"]
    if lb and yrs:
        lead = "일감은 넉넉합니다" if yrs >= 2.5 else ("일감은 보통 수준입니다" if yrs >= 1.5 else "일감이 많지 않습니다")
        parts.append(f"{lead}. 수주잔고 **{an.jo(lb['total'])}조 원**은 최근 1년 매출의 **{yrs:.1f}년 치**입니다.")
    weak_margin = F["ml"] is not None and F["m0"] and F["ml"] < F["m0"] / 2
    streak = F["vd"].get("streak") or 0
    issues = []
    if weak_margin:
        issues.append(f"매출 100원당 영업이익은 {F['y0']}년 {an.pct(F['m0'])}원에서 {F['yl']}년 **{an.pct(F['ml'])}원**으로 줄었")
    if streak >= 2:
        issues.append(f"본업에서 들어오는 현금(영업활동현금흐름)은 **{streak}년 연속 마이너스**입니다.")
    if weak_margin and streak >= 2:
        parts.append(f"숙제는 남기는 돈과 받는 돈입니다. {issues[0]}고, {issues[1]}")
    elif weak_margin:
        parts.append(f"숙제는 남기는 돈입니다. {issues[0]}습니다.")
    elif streak >= 2:
        parts.append(f"숙제는 받는 돈입니다. {issues[0]}")
    else:
        parts.append("이익률과 현금흐름도 큰 문제 없이 유지되고 있습니다.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# 표지
# ---------------------------------------------------------------------------
def cover_chart(F):
    """표지의 연간 매출 막대 (첫해 → 마지막 해)."""
    v = F["v"]
    years, rev = v.years, v.series("revenue")
    top = max(x for x in rev if x)
    n = len(years)
    bars = "".join(f'<i class="{"last" if i == n - 1 else ""}" style="left:{i / n * 100:.3f}%;width:{100 / n:.3f}%;height:{x / top * 100:.2f}%"></i>'
                   for i, x in enumerate(rev) if x)
    return (f'<figure class="cv-chart" aria-label="연간 매출액 막대"><div class="cv-bars">{bars}</div>'
            f'<figcaption><span>{years[0]}년 {an.jo(rev[0])}조 원</span><span>연간 매출액 · 연결</span>'
            f'<span>{years[-1]}년 {an.jo(rev[-1])}조 원</span></figcaption></figure>')


def cover(ctx, F):
    cfg = ctx["company"]
    v = F["v"]
    kp = []
    if F["lb"]:
        kp.append(("수주잔고", an.jo(F["lb"]["total"]), "조 원",
                   rv.period_label(F["lb"]["period"]) + (f" · 매출 {F['yrs']:.1f}년 치" if F["yrs"] else "")))
    kp.append(("매출액", an.jo(F["revl"]), "조 원", f"{F['yl']}년 · {F['y0']}년의 {F['revl'] / F['rev0']:.2f}배"))
    kp.append(("영업이익률", an.pct(F["ml"]), "%", f"{F['yl']}년 · {F['y0']}년 {an.pct(F['m0'])}%"))
    if F["pf"]:
        p, r = F["pf"][-1]
        kp.append(("PF 보증", an.jo(r["amount"]), "조 원", rv.period_label(p) + (f" · 자본의 {F['pf_x']:.1f}배" if F["pf_x"] else "")))
    else:
        cfo = v.a(F["yl"], "operating_cashflow")
        kp.append(("영업활동현금흐름", an.jo(cfo, 2), "조 원", f"{F['yl']}년"))
    kpis = "".join(f'<div class="cv-k"><p class="cv-l">{esc(a)}</p><p class="cv-v">{esc(b)}<small>{esc(c)}</small></p>'
                   f'<p class="cv-s">{esc(e)}</p></div>' for a, b, c, e in kp[:4])
    lf = ctx.get("latest_filing")
    val = ctx.get("valuation") or {}
    seg = F["biz"].get("segments") or {}
    meta = [("대상", f"{cfg['name']} ({cfg['stock_code']}) · 연결재무제표 · {cfg.get('business', '')}"),
            ("기준 공시", (f"{lf['report_nm'].strip()} · {d.fmt_date(lf['rcept_dt'])} 접수" if lf else "–")
             + (f" / {seg['report']}" if seg.get("report") else "")),
            ("주가", f"{val['as_of']} 월말 종가 ({val.get('source', '')})" if val.get("as_of") else "–"),
            ("자료", "OpenDART 전자공시 · 사업·반기·분기보고서 " + f"{F['y0']}년~"),
            ("작성", "HSC-Class01 · OpenDART 재무분석 에이전트 (GitHub Actions가 매월 1일 다시 만듦)"),
            ("대시보드", cfg.get("dashboard_url", ""))]
    meta_html = "".join(f"<div><dt>{esc(k)}</dt><dd>{link(x, x) if x.startswith('http') else esc(x)}</dd></div>" for k, x in meta)
    return (f'<section class="cover"><div class="cv-top"><span>HSC-Class01 · KTG_Hyundai</span><span>{esc(edition(ctx))}</span></div>'
            f'<div class="cv-main"><p class="cv-eyebrow">Company analysis report</p>'
            f'<h1>{esc(cfg["name"])}&nbsp;<br><span>기업분석 보고서</span></h1>'
            f'<p class="cv-sub">사업보고서로 읽는 돈 버는 구조 · 일감 · 재무 체력</p></div>'
            f'<p class="cv-thesis">{rich(thesis(F))}</p>{cover_chart(F)}<div class="cv-kpis">{kpis}</div>'
            f'<dl class="cv-meta">{meta_html}</dl><p class="cv-note">{esc(DISCLAIMER)}</p></section>')


# ---------------------------------------------------------------------------
# 요약
# ---------------------------------------------------------------------------
def findings(ctx, F):
    v, vd, out = F["v"], F["vd"], []
    lb, yrs = F["lb"], F["yrs"]
    if lb and yrs:
        body = f"수주잔고는 {rv.period_label(lb['period'])} **{an.jo(lb['total'])}조 원**으로 최근 1년 매출의 {yrs:.1f}년 치입니다."
        if F["lb_prev"]:
            diff = lb["total"] - F["lb_prev"]["total"]
            body += f" 1년 전보다 {an.jo(abs(diff))}조 원 {'늘었' if diff >= 0 else '줄었'}습니다."
        oy = F["oy"]
        if oy:
            o = F["orders"][oy]["total"]
            if o >= max(x["total"] for x in F["orders"].values()):
                body += f" {oy}년 신규 수주(현대건설 단독) {an.jo(o)}조 원은 {min(F['orders'])}년 이후 가장 많습니다."
            else:
                prev = F["orders"].get(str(int(oy) - 1))
                if prev:
                    body += f" {oy}년 신규 수주(현대건설 단독)는 {an.jo(o)}조 원으로 전년보다 {an.signed((o / prev['total'] - 1) * 100, 0)}%입니다."
        title = "일감은 넉넉합니다" if yrs >= 2.5 else ("일감은 보통 수준입니다" if yrs >= 1.5 else "일감이 줄었습니다")
        out.append((title, body, "3장"))
    mult = F["revl"] / F["rev0"]
    body = (f"매출은 {F['y0']}년의 {mult:.2f}배({an.jo(F['revl'])}조 원)가 됐지만, 영업이익률은 "
            f"{an.pct(F['m0'])}% → **{an.pct(F['ml'])}%**입니다.")
    if F["worst_cost"]:
        wy, wc = F["worst_cost"]
        wop = v.a(wy, "operating_profit")
        if wc >= 100 and wop is not None and wop < 0:
            body += f" 원가율이 가장 높았던 {wy}년({an.pct(wc)}%)에는 원가가 매출보다 커서 영업손실 {an.jo(-wop, 2)}조 원을 냈고,"
        elif wop is not None and wop < 0:
            body += f" 원가율이 가장 높았던 {wy}년({an.pct(wc)}%)에는 영업손실 {an.jo(-wop, 2)}조 원을 냈고,"
        else:
            body += f" 원가율이 가장 높았던 해는 {wy}년({an.pct(wc)}%)이고,"
        body += f" {F['yl']}년 원가율은 {an.pct(v.a(F['yl'], 'cost_ratio_pct'))}%입니다."
    out.append(("매출은 커졌지만 남는 돈은 줄었습니다" if F["ml"] is not None and F["m0"] and F["ml"] < F["m0"]
                else "매출과 함께 이익률도 지켰습니다", body, "4장"))
    streak = vd.get("streak") or 0
    if streak >= 2:
        start = F["yl"] - streak + 1
        total = sum(v.a(t, "operating_cashflow") or 0 for t in range(start, F["yl"] + 1))
        body = f"영업활동현금흐름은 {start}년부터 **{streak}년 연속 마이너스**(합계 {an.jo(total, 2)}조 원)입니다."
        ra, rb = v.a(start - 1, "receivables_total"), v.a(F["yl"], "receivables_total")
        if ra and rb:
            body += (f" 공사는 했지만 아직 받지 못한 돈(매출채권+미청구공사)이 {start - 1}년 말 {an.jo(ra)}조 원에서 "
                     f"{F['yl']}년 말 {an.jo(rb)}조 원으로 {rb / ra:.1f}배가 됐습니다.")
        out.append(("이익이 현금으로 들어오지 않습니다", body, "5장"))
    else:
        cfo = v.a(F["yl"], "operating_cashflow")
        out.append(("현금은 들어오고 있습니다" if cfo and cfo > 0 else "현금흐름이 마이너스로 돌아섰습니다",
                    f"{F['yl']}년 영업활동현금흐름은 {an.jo(cfo, 2)}조 원입니다.", "5장"))
    if F["pf"]:
        p, r = F["pf"][-1]
        p0, r0 = F["pf"][0]
        body = (f"시행사·재건축 조합이 빌린 PF 대출에 선 보증이 {rv.period_label(p)} **{an.jo(r['amount'])}조 원**"
                + (f"으로 자본총계의 {F['pf_x']:.1f}배입니다." if F["pf_x"] else "입니다."))
        if p0 != p:
            body += f" 같은 기준으로 볼 수 있는 {rv.period_label(p0)}({an.jo(r0['amount'])}조 원)보다 {ratio_word(r['amount'] / r0['amount'])}."
        body += " 재무제표 본문에는 빚으로 잡히지 않지만, 사업장이 잘못되면 건설사가 대신 갚아야 합니다."
        out.append(("재무제표 밖의 위험, PF 보증", body, "5장"))
    step = F["steps"].get("debt")
    if step:
        tone = step["verdict"][0]
        title = {"good": "당장 갚을 힘은 있습니다", "warn": "빚 부담을 지켜봐야 합니다", "crit": "빚 부담이 큽니다"}.get(tone, "빚 부담")
        nums = []
        if vd.get("coverage") is not None:
            nums.append(f"이자보상배율 {an.pct(vd['coverage'])}배")
        if vd.get("net_debt") is not None:
            nums.append(f"순차입금 {an.jo(vd['net_debt'], 2)}조 원" + (f"(EBITDA의 {vd['nd_ebitda']:.1f}배)" if vd.get("nd_ebitda") else ""))
        out.append((title, step["answer"] + (" 최근 4개 분기 " + ", ".join(nums) + "입니다." if nums else ""), "5장"))
    val = ctx.get("valuation") or {}
    if val.get("market_cap"):
        body = (f"주가 {val['price']:,.0f}원({val['as_of']} 기준), 시가총액 {an.jo(val['market_cap'], 2)}조 원입니다. "
                + (f"PBR {val['pbr_x']:.2f}배" if val.get("pbr_x") else "")
                + (f", PER {val['per_x']:.1f}배(최근 4개 분기 이익 기준)" if val.get("per_x") else "") + ". "
                + "배수는 좋고 나쁨이 아니라 시장의 기대를 보여 주는 참고 값입니다.")
        out.append(("시장의 평가", body, "7장"))
    return out


def summary_page(ctx, F):
    cards = "".join(f'<article class="r-find"><p class="r-fno">{i:02d}</p><p class="r-h">{esc(t)}</p><p>{rich(b)}</p>'
                    f'<p class="r-fref">→ {esc(ref)}</p></article>' for i, (t, b, ref) in enumerate(findings(ctx, F), 1))
    icon = {"good": "✓", "warn": "!", "crit": "✕", "info": "i"}
    rows = []
    for s in F["a"].get("steps", []):
        tone, word = s["verdict"]
        rows.append([esc(f"{s['no']} {s['ko']}"), f'<span class="r-chip {tone}">{icon[tone]} {esc(word)}</span>', rich(s["answer"])])
    guide = rtable(["단계", "판정", "한 줄 답"], rows, "r-guide")
    return (f'<section class="r-chap r-summary" id="summary"><header class="r-head"><span class="r-num">요약</span>'
            f'<div class="r-tt"><p>Executive summary</p><h2>한 장으로 보는 {esc(ctx["company"]["name"])}</h2></div></header>'
            f'<p class="r-lead">{rich(thesis(F))}</p><div class="r-finds">{cards}</div>'
            + sub("", "교수님 가이드 6단계 판정", guide,
                  "재무제표·재무비율 실무가이드의 분석 순서(매출 성장 → 이익률 → 현금흐름 → 차입 부담 → 투자수익률 → 주가 수준)와 "
                  "정해진 판정 규칙(부록 B)을 따릅니다. 대시보드의 같은 판정과 매월 함께 바뀝니다.")
            + '</section>')


# ---------------------------------------------------------------------------
# 1장 돈 버는 구조
# ---------------------------------------------------------------------------
def segment_headline(F):
    seg = F["biz"].get("segments") or {}
    rows = seg.get("rows") or []
    if not rows:
        return "사업부문별 매출"
    tot = sum((r["domestic"] or [0])[0] + (r["overseas"] or [0])[0] for r in rows)
    top = max(rows, key=lambda r: (r["domestic"] or [0])[0] + (r["overseas"] or [0])[0])
    share = ((top["domestic"] or [0])[0] + (top["overseas"] or [0])[0]) / tot * 100 if tot else 0
    return f"매출의 {share:.0f}%는 {top['segment'].replace('/', '·')}"


def ch1_structure(ctx, F):
    steps = rv._flow_steps(ctx, F["v"])
    flow = rv.flow_html(steps)
    poc_rows = [["올해까지 쓴 원가", num("450억 원"), num("450억 원")],
                ["총예정원가(끝날 때까지 들 원가)", num("900억 원"), num("1,050억 원")],
                ["진행률 = 쓴 원가 ÷ 총예정원가", num("50.0%"), num("42.9%")],
                ["올해 매출 = 계약금액 1,000억 원 × 진행률", num("500억 원"), num("429억 원")],
                ["올해 이익", num("50억 원"), num("−50억 원", -1)]]
    poc = (rtable(["계약금액 1,000억 원짜리 공사", "처음 예상", "원가 추정이 늘면"], poc_rows, "r-poc")
           + bullets(["공사 전체가 손해로 예상되면 앞으로 생길 손실(이 예에서 50억 원)까지 **그해에 한꺼번에** 비용으로 잡습니다. "
                      "2024년 현대건설의 적자가 이렇게 생겼습니다(4장).",
                      "진행률로 잡은 매출보다 청구한 돈이 적으면 **미청구공사**(받을 돈), 많으면 **초과청구공사**(미리 받은 돈)가 생깁니다(5장)."], "small"))
    body = (sub("1-1", "돈이 도는 여섯 단계", flow,
                "카드의 숫자는 가장 최근 공시 기준이며 매월 다시 계산합니다. 카드 맨 아래 작은 글씨는 그 숫자가 사업보고서의 어디에 있는지입니다.")
            + sub("1-2", "공사비가 매출이 되는 방법: 진행기준", poc,
                  "건설사는 공사가 끝날 때가 아니라 **진행한 만큼** 매출을 잡습니다(K-IFRS 1115호). 진행률은 보통 ‘지금까지 쓴 원가 ÷ 총예정원가’로 잽니다.")
            + sub("1-3", "누가, 어떻게 공사를 맡기나", rv.buyers_html(ctx) + rv.market_html(ctx),
                  "공사를 따내는 기준은 발주처마다 다릅니다. 공공은 점수, 재건축은 조합원 투표, 민간·해외는 실적과 신뢰로 정해집니다.")
            + sub("1-4", segment_headline(F), rv.segments_fig(ctx)))
    return chapter("01", "Business model", "건설사는 이렇게 돈을 법니다",
                   "건설사는 물건을 먼저 만들어 파는 회사가 아닙니다. **공사를 먼저 따내고(수주), 몇 년에 걸쳐 지으면서 진행한 만큼 매출로 잡고, "
                   "공사비를 청구해 현금을 회수하는 수주산업**입니다. 그래서 돈이 들어오는 길은 여섯 단계가 한 바퀴로 이어지고, "
                   "단계마다 사업보고서에서 확인할 숫자가 있습니다.", body, "ch1")


# ---------------------------------------------------------------------------
# 2장 사업보고서
# ---------------------------------------------------------------------------
READ_ITEMS = [("수주잔고 · 공사별 진행", "Ⅱ 사업의 내용 > 매출 및 수주상황", "회사별 국내·해외 계약잔액, 공사별 계약금액·완성·잔액"),
              ("신규 수주", "Ⅱ 사업의 내용 > 사업의 개요(지배회사 현황)", "현대건설 단독 한 해 수주실적 문장"),
              ("사업부문별 매출 · 국내 건설시장 · 원자재 가격", "Ⅱ 사업의 내용", "가장 최근 사업보고서의 표"),
              ("재무제표(손익·재무상태·현금흐름)", "Ⅲ 재무에 관한 사항", "OpenDART 재무제표 API + 2010~2015년 원문 표"),
              ("단독 매출·영업이익", "Ⅲ 재무에 관한 사항 > 요약재무정보(별도)", "직원 1인당 생산성 계산용"),
              ("직원 수 · 평균 급여", "Ⅷ 임원 및 직원 등에 관한 사항", "직원 현황 합계"),
              ("PF 보증", "Ⅺ 그 밖에 투자자 보호 > 우발부채 등(채무보증현황)", "보증금액 기준 신용보강 문장")]


def ch2_report(ctx, F):
    what = bullets(["상장회사가 **자본시장법 제159조**에 따라 1년 동안의 사업과 재무 상태를 투자자에게 알리는 공식 연간 보고서입니다.",
                    "사업연도가 끝나고 **90일 안에** 금융위원회와 한국거래소에 내고, 전자공시시스템(DART)에 공개됩니다. "
                    "6개월 치는 반기보고서, 3·9개월 치는 분기보고서로 **45일 안에** 냅니다(제160조).",
                    "회계법인의 **감사보고서**가 함께 붙어, 재무제표 숫자를 외부에서 한 번 확인받은 자료입니다.",
                    "건설업만의 정의가 따로 있지는 않지만, 건설사 보고서는 **수주잔고·공사별 진행률·미청구공사·PF 보증**이 핵심입니다."])
    what_box = box("사업보고서란?", what + f'<p class="r-src">출처: {rv.ref("law159")}</p>')
    chap = "".join(f'<li class="{"on" if on else ""}"><span class="cn">{esc(no)}</span><span><b>{esc(t)}</b> {esc(w)}</span></li>'
                   for no, t, w, on in rv.CHAPTERS)
    lf = ctx.get("latest_filing")
    chap_box = box("사업보고서 한 권의 구조", f'<ol class="r-chapters">{chap}</ol>'
                   f'<p class="r-src">진하게 표시한 장을 이 보고서가 자동으로 읽습니다'
                   + (f" · 최근 보고서: {dart_link(lf['rcept_no'], lf['report_nm'].strip())}" if lf else "") + "</p>")
    rows = [[f'<b>{i}</b> {esc(a)}', esc(b), f"<b>{esc(c)}</b>", esc(e)] for i, (a, b, c, e) in enumerate(rv.why_rows(ctx, F["v"]), 1)]
    why = rtable(["돈 버는 단계", "사업보고서의 어디", "현대건설 지금", "이렇게 읽습니다"], rows, "r-why")
    body = (f'<div class="r-2 r-ch2">{what_box}{chap_box}</div>'
            + sub("2-1", "돈 버는 단계별로 사업보고서에서 볼 곳", why,
                  "1장의 단계마다 보고서의 어느 장을 봐야 하는지와, 그 자리에서 매월 자동으로 읽어 온 현대건설의 지금 숫자입니다.")
            + f'<p class="r-src">특히 볼 곳: Ⅱ장 수주상황 표, Ⅲ장 주석 ‘건설계약’(2016년부터 매출 5% 이상 공사는 공사별 진행률·미청구공사 공개, '
              f'{rv.ref("crowe")}), Ⅺ장 PF 보증. 자동으로 읽는 위치는 부록 B.</p>')
    return chapter("02", "Why the annual report", "그래서 사업보고서를 읽습니다",
                   "재무제표(사업보고서 Ⅲ장)는 1장에서 본 순환의 **결과**만 보여 줍니다. 결과를 만든 **원인**, 즉 얼마나 따냈고 공사가 어디까지 왔고 "
                   "어떤 보증을 섰는지는 Ⅱ장(사업의 내용)과 Ⅺ장(우발부채 등)에 있습니다. 그래서 건설사를 분석할 때는 재무제표 숫자 하나를 보더라도 "
                   "사업보고서 전체에서 그 원인을 함께 찾아야 합니다.", body, "ch2")


# ---------------------------------------------------------------------------
# 3장 일감
# ---------------------------------------------------------------------------
def tiles_html(items):
    return ('<div class="vtiles">' + "".join(f'<div class="vt"><p class="vt-l">{esc(a)}</p><p class="vt-v">{esc(b)}<small>{esc(c)}</small></p>'
                                             f'<p class="vt-d">{esc(e)}</p></div>' for a, b, c, e in items) + "</div>")


def orders_points(ctx, F):
    pts = []
    lb, prev = F["lb"], F["lb_prev"]
    if lb and prev:
        diff = lb["total"] - prev["total"]
        share_now = lb["overseas"] / lb["total"] * 100 if lb.get("overseas") and lb["total"] else None
        share_prev = prev["overseas"] / prev["total"] * 100 if prev.get("overseas") and prev["total"] else None
        text = (f"{rv.period_label(lb['period'])} 수주잔고는 1년 전({an.jo(prev['total'])}조 원)보다 **{an.jo(abs(diff))}조 원 "
                f"{'늘었' if diff >= 0 else '줄었'}습니다**.")
        if share_now is not None and share_prev is not None:
            text += (f" 해외 비중은 {share_prev:.0f}% → {share_now:.0f}%"
                     f"(해외 잔고 {an.jo(prev['overseas'])}조 → {an.jo(lb['overseas'])}조 원)입니다.")
        pts.append(text)
    big_new = [r for r in F["projects"] if r["contract"] >= T and r["done"] / r["contract"] < 0.15]
    if big_new:
        names = ", ".join(f"{r['name']}({an.jo(r['contract'], 2)}조 원, 진행률 {r['done'] / r['contract'] * 100:.0f}%)" for r in big_new[:4])
        pts.append(f"아직 대부분 남은 큰 공사(진행률 15% 미만): {names}. 앞으로 몇 년 동안 매출이 될 일감입니다.")
    ending = [r for r in F["projects"] if r["contract"] and r["done"] / r["contract"] >= 0.55]
    if ending:
        names = ", ".join(f"{r['name']} {r['done'] / r['contract'] * 100:.0f}%" for r in ending[:4])
        pts.append(f"끝나 가는 공사(진행률 55% 이상): {names}. 이 공사들의 매출은 줄어들고, 새 공사가 그 자리를 채워야 합니다.")
    pts.append("잔고가 이익을 보장하지는 않습니다. 같은 잔고라도 원가가 예상보다 늘면 손실이 됩니다(4장의 원가율). "
               "그래서 수주잔고는 공사별 진행률·원가율과 함께 봐야 합니다.")
    return pts


def ch3_orders(ctx, F):
    body = (tiles_html(rv.orders_tiles(ctx))
            + sub("3-1", "일감은 얼마나 쌓였나", rv.backlog_fig(ctx))
            + f'<div class="r-2">{rv.work_years_fig(ctx)}{rv.orders_fig(ctx)}</div>'
            + sub("3-2", "어떤 공사가 남았나", rv.projects_fig(ctx))
            + sub("3-3", "일감을 읽는 법", bullets(orders_points(ctx, F))))
    return chapter("03", "Orders & backlog", "일감: 수주와 수주잔고",
                   "수주잔고는 계약은 했지만 아직 짓지 않은 공사 금액, 곧 **앞으로 매출이 될 일감**입니다. 사업보고서 Ⅱ장 ‘수주상황’ 표에 "
                   "회사별·공사별로 나옵니다. 신규 수주는 한 해 동안 새로 따낸 공사입니다.", body, "ch3")


# ---------------------------------------------------------------------------
# 4장 이익의 질
# ---------------------------------------------------------------------------
def materials_table(ctx):
    mt = (rv.biz_of(ctx).get("materials") or {})
    items = mt.get("items") or []
    if not items:
        return ""
    year = mt.get("year")
    labels = [f"{year - i}년" for i in range(len(mt.get("periods") or []))][::-1]
    rows = []
    for it in items:
        vals = list(reversed(it["values"]))
        chg = (vals[-1] / vals[0] - 1) * 100 if vals and vals[0] and vals[-1] is not None else None
        rows.append([esc(it["name"])] + [num(f"{x:,.0f}" if x is not None else "–") for x in vals]
                    + [num(f"{an.signed(chg, 1)}%" if chg is not None else "–", chg), esc(it.get("unit", ""))])
    note = (f"출처: {rv.dart(mt['receipt'], mt['report'])} Ⅱ장 ‘주요 원재료 가격변동추이’. 고정된 계약금액으로 몇 년씩 짓는 공사에서는 "
            "자재값이 오르면 원가율이 바로 오릅니다.")
    return rtable(["원자재"] + labels + [f"{labels[0][:4]}→{labels[-1][:4]}", "단위"], rows, "r-mat") + f'<p class="r-src">{note}</p>'


def acts_table(F):
    rows = []
    for act in F["a"].get("acts", []):
        why_text, srcs = act["why"]
        links = " · ".join(link(an.SOURCES[s][1], an.SOURCES[s][0]) for s in srcs if s in an.SOURCES)
        facts_line = " · ".join(esc(f) for f in act["facts"])
        rows.append([f'<b>{esc(act["years"])}</b>', f'<b>{esc(act["title"])}</b><span class="r-facts">{facts_line}</span>',
                     esc(why_text) + (f'<span class="r-src">출처: {links}</span>' if links else "")])
    return rtable(["시기", "장면과 숫자", "배경"], rows, "r-acts") if rows else ""


def ch4_profit(ctx, F):
    v10 = F["v10"]
    step = F["steps"].get("profit") or {}
    notes = F["a"].get("notes") or {}
    body = (sub("4-1", "원가가 이익을 정합니다", d.per100_fig(v10, notes))
            + sub("4-2", "네 가지 이익률로 본 10년", d.margins_fig(v10))
            + box("가이드 순서로 본 이익률", bullets(step.get("more", [])), "cols")
            + sub("4-3", "원가를 흔드는 자재값", materials_table(ctx))
            + sub("4-4", f"{F['y0']}년부터의 흐름, 다섯 장면", acts_table(F),
                  "숫자는 재무제표에서 자동으로 계산하고, 배경 설명은 언론 보도에서 가져왔습니다."))
    lead = [step.get("answer", ""), step.get("lead", "")]
    return chapter("04", "Quality of earnings", "이익의 질: 원가율과 수익성", lead, body, "ch4")


# ---------------------------------------------------------------------------
# 5장 현금과 재무 체력
# ---------------------------------------------------------------------------
def ch5_cash(ctx, F):
    v10, years = F["v10"], F["years10"]
    a = F["a"]
    cash_step, debt_step = F["steps"].get("cash") or {}, F["steps"].get("debt") or {}
    f_cash, f_rec = d.cash_figs(v10, F["vd"], a.get("notes") or {})
    f_cov, f_nd, _, _ = d.debt_figs(v10)
    sig = [s for s in a.get("signals", []) if s["year"] in years]
    pf_box = box("PF 보증이란?", bullets(["아파트·오피스를 짓는 시행사나 재건축 조합은 땅을 사고 공사비를 대려고 은행에서 큰돈을 빌립니다(PF 대출).",
                                          "건설사는 공사를 따내는 조건으로 ‘사업이 잘못되면 대신 갚거나 책임지고 완공하겠다’는 약속(보증·책임준공)을 섭니다.",
                                          "지금은 빚이 아니어서 재무상태표의 부채에는 없지만, 분양이 안 되면 건설사의 빚이 됩니다. 그래서 사업보고서 Ⅺ장의 "
                                          "‘채무보증현황’을 따로 봐야 합니다."]))
    body = (f'<div class="r-2">{f_cash}{f_rec}</div>'
            + sub("5-1", "현금흐름 신호등", d.signal_table(sig) if sig else "",
                  "현금흐름표의 세 칸(영업·투자·재무)이 들어왔는지(▲) 나갔는지(▼)만 봐도 회사의 상태가 보입니다.")
            + box("가이드 순서로 본 현금흐름", bullets(cash_step.get("more", [])))
            + sub("5-2", "부채는 무엇으로 이뤄졌나", st.bs_chart(v10, years))
            + sub("5-3", "재무제표 밖의 위험: PF 보증", f'<div class="r-2 r-pf">{rv.pf_fig(ctx)}{pf_box}</div>')
            + sub("5-4", "빚을 감당할 힘", f'<div class="r-2">{f_cov}{f_nd}</div>'
                  + box("가이드 순서로 본 차입 부담", f'<p><b>{rich(debt_step.get("answer", ""))}</b></p>'
                        + bullets([debt_step.get("lead", "")] + debt_step.get("more", [])))))
    lead = [cash_step.get("answer", ""), cash_step.get("lead", "")]
    return chapter("05", "Cash & financial strength", "현금과 재무 체력", lead, body, "ch5")


# ---------------------------------------------------------------------------
# 6장 재무비율 10가지 관점
# ---------------------------------------------------------------------------
def ch6_lenses(ctx, F):
    L, years = F["L"], F["years10"]
    icon = {"good": "✓", "warn": "!", "crit": "✕", "info": "i"}
    rows = []
    for lens in L:
        m = lens["head"] if lens["id"] != "price" else lens["metrics_data"][0]
        others = [x for x in lens["metrics_data"] if x is not m][:2]
        extra = " · ".join(f"{x['label']} {ln.with_unit(x['latest'], x['unit'])}" for x in others if x["latest"] is not None)
        rank = f" ({m['rank']}위)" if m.get("rank") else ""
        rows.append([f'<b>{lens["no"]} {esc(lens["ko"])}</b><span class="r-q">{esc(lens["q"])}</span>',
                     f'{esc(m["label"])}<span class="r-q">{esc(extra)}</span>',
                     num(ln.with_unit(m["latest"], m["unit"]), m["latest"]),
                     f'<span class="r-chip {m["tone"]}">{icon[m["tone"]]} {esc(m["word"])}{esc(rank)}</span>',
                     num(ln.with_unit(m["median"], m["unit"]), m["median"])])
    table = rtable(["관점 · 질문", "대표 지표 · 함께 본 지표", f"{years[-1]}년", f"{len(years)}년 중 위치(좋은 순)", "중앙값"], rows, "r-lens")
    dupont = next((x for x in L if x["id"] == "dupont"), None)
    dp = ""
    if dupont:
        heads, drows = st.dupont_rows(dupont, years)
        dp = rtable(heads, [[esc(r[0])] + [num(c[0], c[1]) for c in r[1:]] for r in drows], "r-dupont") + \
            f'<p class="r-src">{rich(st.dupont_note(dupont, years))}</p>'
    body = (table
            + sub("6-1", "10년 위치표", st.heatmap(L, years),
                  "여러 관점의 대표 지표를 한 표에 놓고, 같은 줄 안에서 상대적으로 좋은 해는 초록, 나쁜 해는 빨강으로 칠했습니다. "
                  "한 해의 색이 대부분 빨갛다면 여러 관점에서 동시에 나빠진 해입니다.", keep=True)
            + sub("6-2", "종합 분석: ROE를 셋으로 나누면 (듀퐁 분해)", dp,
                  "ROE = 순이익률(얼마나 남기나) × 총자산회전율(얼마나 빨리 돌리나) × 재무레버리지(빚을 얼마나 쓰나).", keep=True))
    return chapter("06", "10 lenses", "재무비율 10가지 관점",
                   f"재무비율은 하나만 보면 오해하기 쉽습니다. 수익성·안정성·유동성·활동성·성장성·생산성·현금흐름·시장가치에 종합 분석(듀퐁)과 "
                   f"주가 반영을 더한 10가지 관점으로 나눠, **최근 {len(years)}년({years[0]}~{years[-1]}) 안에서 지금이 어디쯤인지** 봤습니다. "
                   "높을수록 좋은 지표와 낮을수록 좋은 지표를 구분하고, PER처럼 해석이 갈리는 지표는 ‘참고’로 둡니다. "
                   "관점별 차트는 대시보드에 있습니다.", body, "ch6")


# ---------------------------------------------------------------------------
# 7장 시장의 평가
# ---------------------------------------------------------------------------
def peers_table(ctx):
    rows_, year = d.peer_table_rows(ctx)
    rows = []
    for p, own in rows_:
        name = f"<b>{esc(p['name'])}</b>" if own else esc(p["name"])
        vals = []
        for key, unit in (("revenue", "amt"), ("operating_margin_pct", "pct"), ("debt_to_equity_pct", "pct"),
                          ("roe_pct", "pct"), ("pbr_x", "x2")):
            col = next(c for c in d.PEER_COLS if c[0] == key)
            x = d.peer_value(p, key, col[3])
            if x is None:
                vals.append(num("–"))
            elif unit == "amt":
                vals.append(num(an.jo(x, 1), x))
            elif unit == "pct":
                vals.append(num(an.pct(x, 1), x))
            else:
                vals.append(num(f"{x:.2f}", x))
        rows.append([esc(f"{p['rank']}위" if p.get("rank") else "–"), name] + vals)
    table = rtable(["시평 순위", "회사", "매출액(조 원)", "영업이익률(%)", "부채비율(%)", "ROE(%)", "PBR(배)"], rows, "r-peers")
    summary = d.peer_summary(rows_, ctx["company"]["name"])
    rank = ctx["company"].get("rank") or {}
    notes = " · ".join(f"{p['name']}: {p['note']}" for p, own in rows_ if not own and p.get("note"))
    src = (f"순위: {rank.get('year')}년 {rank.get('basis')} ({link(rank.get('source_url', ''), rank.get('source_name', ''))}) · "
           f"재무: 각 회사의 가장 최근 사업보고서 연결재무제표 · PBR은 현재 주가 ÷ 사업보고서 지배주주지분" if rank else "")
    foot = " · ".join(x for x in (esc(notes) if notes else "", src) if x)
    return (f'<p class="r-p">{rich(summary)}</p>' if summary else "") + table + (f'<p class="r-src">{foot}</p>' if foot else "")


def ch7_market(ctx, F):
    step = F["steps"].get("valuation") or {}
    price = next((x for x in F["L"] if x["id"] == "price"), None)
    direction = ""
    if price:
        _, _, same, total = st.price_direction(price, F["years10"])
        if total:
            direction = (f"계산할 수 있는 {total}년 중 **{same}년**은 연말 주가와 영업이익이 같은 방향으로 움직였습니다. "
                         "주가는 실적이 나오기 전에 기대를 먼저 반영하기 때문에, 방향이 반대인 해는 시장이 다음 해 실적을 미리 본 경우가 많습니다.")
    body = (d.valuation_tiles(ctx)
            + st.price_fig(ctx, F["years10"][0], fid="fig-price-report")
            + (f'<p class="r-p">{rich(direction)}</p>' if direction else "")
            + sub("7-1", "경쟁사와 비교", peers_table(ctx)))
    more = step.get("more", [])
    lead = [step.get("answer", "") + (" " + more[0] if more else "")]
    return chapter("07", "Market view", "시장의 평가와 경쟁사", lead, body, "ch7")


# ---------------------------------------------------------------------------
# 8장 종합 의견
# ---------------------------------------------------------------------------
def opinion_lists(ctx, F):
    v, vd = F["v"], F["vd"]
    lb, yrs = F["lb"], F["yrs"]
    good, risk = [], []
    if lb and yrs and yrs >= 2.5:
        good.append(f"**일감**: 수주잔고 {an.jo(lb['total'])}조 원으로 매출 {yrs:.1f}년 치를 확보했습니다.")
    oy = F["oy"]
    if oy and F["orders"][oy]["total"] >= max(x["total"] for x in F["orders"].values()):
        good.append(f"**수주력**: {oy}년 신규 수주 {an.jo(F['orders'][oy]['total'])}조 원(현대건설 단독)은 {min(F['orders'])}년 이후 가장 많습니다.")
    rank = ctx["company"].get("rank") or {}
    if rank.get("own") and rank["own"] <= 3:
        good.append(f"**체급**: {rank.get('year')}년 시공능력평가 {rank['own']}위로, 공공공사·정비사업 입찰에서 실적과 신인도가 유리하게 작용합니다.")
    if F["steps"].get("debt", {}).get("verdict", ("",))[0] == "good":
        good.append(f"**상환능력**: 최근 4개 분기 이자보상배율 {an.pct(vd.get('coverage'))}배"
                    + (f", 순차입금/EBITDA {vd['nd_ebitda']:.1f}배" if vd.get("nd_ebitda") else "") + "로 이자 부담은 감당할 수 있습니다.")
    bal = F["bal"]
    if bal and (bal["ratios"].get("current_ratio_pct") or 0) > 100:
        good.append(f"**유동성**: {an.when_label(bal)} 유동비율 {an.pct(bal['ratios']['current_ratio_pct'], 0)}%로, 1년 안에 갚을 빚보다 1년 안에 돈이 될 자산이 많습니다.")
    seg = F["biz"].get("segments") or {}
    if seg.get("rows"):
        tot = sum((r["domestic"] or [0])[0] + (r["overseas"] or [0])[0] for r in seg["rows"])
        ovs = sum((r["overseas"] or [0])[0] for r in seg["rows"])
        parts = sorted(((r["segment"], ((r["domestic"] or [0])[0] + (r["overseas"] or [0])[0]) / tot * 100) for r in seg["rows"]), key=lambda x: -x[1])
        good.append(f"**사업 구성**: {seg['year']}년 매출은 " + ", ".join(f"{n} {s:.0f}%" for n, s in parts[:3])
                    + f"이고 해외가 {ovs / tot * 100:.0f}%입니다. 주택 경기 하나에만 기대지 않습니다.")
    margin_lens = next((x for x in F["L"] if x["id"] == "profitability"), None)
    if margin_lens:
        m = margin_lens["head"]
        if m["latest"] is not None and m["median"] is not None and m["latest"] < m["median"]:
            risk.append(f"**낮은 이익률**: {m['latest_year']}년 영업이익률 {ln.with_unit(m['latest'], '%')}로 최근 10년 중앙값({ln.with_unit(m['median'], '%')})보다 낮습니다.")
    streak = vd.get("streak") or 0
    if streak >= 2:
        rec = bal["values"].get("receivables_total") if bal else None
        risk.append(f"**현금 회수**: 영업활동현금흐름이 {streak}년 연속 마이너스이고"
                    + (f", {an.when_label(bal)} 받을 돈(매출채권+미청구공사)이 {an.jo(rec)}조 원입니다." if rec else "입니다."))
    if F["pf"]:
        p, r = F["pf"][-1]
        risk.append(f"**PF 보증**: {rv.period_label(p)} {an.jo(r['amount'])}조 원" + (f"으로 자본총계의 {F['pf_x']:.1f}배" if F["pf_x"] else "")
                    + "입니다. 부동산 경기가 꺾이면 우발채무가 빚이 될 수 있습니다.")
    early = [r for r in F["projects"] if r["region"] == "해외" and r["contract"] >= T and r["done"] / r["contract"] < 0.10]
    if early:
        risk.append(f"**해외 대형 공사의 원가**: " + ", ".join(f"{r['name']}" for r in early[:3])
                    + f" 등 {an.jo(sum(r['contract'] for r in early), 1)}조 원이 진행률 10% 미만입니다. 2024년처럼 원가 추정이 바뀌면 손실이 한꺼번에 반영됩니다.")
    debt_now = bal["ratios"].get("debt_to_equity_pct") if bal else None
    lows = [(t, v.a(t, "debt_to_equity_pct")) for t in v.years if v.a(t, "debt_to_equity_pct") is not None]
    if debt_now and lows:
        lt, lowv = min(lows, key=lambda x: x[1])
        if debt_now > lowv * 1.25:
            risk.append(f"**늘어난 빚**: 부채비율이 {lt}년 말 {an.pct(lowv, 0)}%에서 {an.when_label(bal)} {an.pct(debt_now, 0)}%로 올랐습니다. "
                        "모자란 현금을 빌려서 메우고 있기 때문입니다.")
    return good, risk


def watch_rows(ctx, F):
    v, bal = F["v"], F["bal"]
    rows = []
    if F["lb"]:
        lb = F["lb"]
        share = lb["overseas"] / lb["total"] * 100 if lb.get("overseas") else None
        rows.append(["수주잔고와 해외 비중", f"{an.jo(lb['total'])}조 원" + (f" · 해외 {share:.0f}%" if share is not None else ""),
                     "Ⅱ 매출 및 수주상황", "잔고가 유지되면서 새 공사의 원가율이 낮게 유지되는지"])
    rows.append(["원가율", f"{F['yl']}년 {an.pct(v.a(F['yl'], 'cost_ratio_pct'))}%", "Ⅲ 손익계산서 · 주석 ‘건설계약’",
                 "낮아질수록 좋음. 원가 추정 변경(손실 반영)이 있는지"])
    cfo_h = None
    h1 = next((h for h in reversed(ctx["halves"]) if h["kind"] == "H1"), None)
    if h1 and h1["year"] > F["yl"]:
        cfo_h = h1["values"].get("operating_cashflow")
    rows.append(["영업활동현금흐름", f"{F['yl']}년 {an.jo(v.a(F['yl'], 'operating_cashflow'), 2)}조 원"
                 + (f" · {h1['year']}년 상반기 {an.jo(cfo_h, 2)}조 원" if cfo_h is not None else ""),
                 "Ⅲ 현금흐름표", "플러스로 돌아서는지"])
    if bal and bal["values"].get("receivables_total"):
        rows.append(["받을 돈(매출채권+미청구공사)", f"{an.when_label(bal)} {an.jo(bal['values']['receivables_total'])}조 원",
                     "Ⅲ 재무상태표 · 주석 ‘건설계약’", "매출보다 느리게 늘거나 줄어드는지"])
    if F["pf"]:
        p, r = F["pf"][-1]
        rows.append(["PF 보증", f"{rv.period_label(p)} {an.jo(r['amount'])}조 원", "Ⅺ 우발부채 등(채무보증현황)", "자본 대비 배수가 줄어드는지"])
    return [[esc(a), f"<b>{esc(b)}</b>", esc(c), esc(e)] for a, b, c, e in rows]


def ch8_opinion(ctx, F):
    good, risk = opinion_lists(ctx, F)
    cols = (f'<div class="r-2">{box("강점", bullets(good), "good")}{box("약점과 위험", bullets(risk), "crit")}</div>')
    watch = rtable(["다음 공시에서 볼 숫자", "지금", "사업보고서의 어디", "좋아지는 신호"], watch_rows(ctx, F), "r-watch")
    closing = (f"{ctx['company']['name']}의 지금을 한 문장으로 줄이면 ‘일감은 충분하지만, 그 일감을 이익과 현금으로 바꾸는 힘을 다시 증명해야 하는 회사’입니다. "
               if F["yrs"] and F["yrs"] >= 2.5 and (F["vd"].get("streak") or 0) >= 2 else "")
    closing += ("이 보고서의 숫자와 문장은 새 공시가 나올 때마다 자동으로 다시 계산되므로, 다음 분기에 위 다섯 숫자가 어느 쪽으로 움직였는지 "
                "확인하는 것이 가장 좋은 다음 단계입니다.")
    body = (cols + sub("8-1", "다음 공시에서 확인할 숫자", watch)
            + f'<p class="r-lead r-close">{rich(closing)}</p>')
    return chapter("08", "Conclusion", "종합 의견",
                   "1~7장에서 본 숫자를 강점과 위험으로 나누고, 다음 공시에서 확인할 숫자를 정리했습니다. "
                   "강점과 위험은 미리 정한 조건(일감 2.5년 치 이상, 10년 중앙값과 비교 등)에 맞을 때만 자동으로 나타납니다.", body, "ch8")


# ---------------------------------------------------------------------------
# 부록
# ---------------------------------------------------------------------------
GLOSSARY = [
    ("수주 · 신규 수주", "발주처와 공사 계약을 맺는 것. 신규 수주는 한 해 동안 새로 맺은 계약 금액입니다."),
    ("수주잔고", "계약은 했지만 아직 짓지 않은 공사 금액. 앞으로 매출이 될 일감입니다."),
    ("진행기준", "공사가 끝날 때가 아니라 진행한 만큼(보통 쓴 원가 ÷ 총예정원가) 매출을 잡는 회계 방법입니다."),
    ("원가율", "매출원가 ÷ 매출액. 100%를 넘으면 원가만으로 매출보다 많이 쓴 것입니다."),
    ("미청구공사", "공사는 했지만 아직 청구하지 못한 금액(계약자산). 늘어나면 현금이 늦게 들어옵니다."),
    ("초과청구공사 · 선수금", "공사보다 먼저 받은 돈(계약부채). 돈 대신 공사로 갚는 부채입니다."),
    ("PF 보증", "시행사·조합의 프로젝트파이낸싱 대출에 건설사가 선 보증이나 신용보강. 재무상태표 밖의 우발채무입니다."),
    ("영업활동현금흐름(CFO)", "본업으로 실제 들어오고 나간 현금. 이익과 달리 회계상 추정이 들어가지 않습니다."),
    ("FCF(잉여현금흐름)", "영업활동현금흐름 − 설비투자(CAPEX). 투자를 하고도 남는 현금입니다."),
    ("이자보상배율", "영업이익 ÷ 이자비용. 1배 미만이면 영업이익으로 이자도 못 냅니다."),
    ("순차입금", "이자가 붙는 차입금 − 현금. 마이너스면 빚보다 현금이 많은 순현금 상태입니다."),
    ("EBITDA", "영업이익 + 감가상각비. 설비가 적은 건설사는 영업이익과 큰 차이가 없습니다."),
    ("ROE · ROIC", "ROE = 순이익 ÷ 평균 자본, ROIC = 세후 영업이익 ÷ 평균 투하자본(자본 + 순차입금)."),
    ("PER · PBR", "PER = 시가총액 ÷ 순이익, PBR = 시가총액 ÷ 순자산. 시장이 회사를 이익·장부가치의 몇 배로 보는지입니다."),
    ("시공능력평가", "국토교통부가 매년 실적·재무·기술·신인도로 매기는 건설사 체급. 입찰 자격과 보증에 쓰입니다."),
    ("종합심사낙찰제", "300억 원 이상 공공공사에서 공사수행능력과 입찰금액을 합산해 낙찰자를 정하는 방식입니다."),
]

DISCLAIMER = ("대학 교양 수업 과제로 공시 숫자를 자동 정리한 교육용 자료이며, 특정 주식의 매수·매도를 권하는 투자 조언이 아닙니다. "
              "숫자는 공시 원문과 다를 수 있으니 중요한 판단에는 DART 원문을 확인하세요.")
LIMITS = [
    "모든 재무 숫자는 연결재무제표 기준이고, 당기순이익은 비지배지분 몫을 포함합니다. 생산성(직원 1인당)만 현대건설 단독 숫자입니다.",
    "2015년 이후 연간·2016년 이후 분기는 OpenDART 재무제표 API, 2010~2015년은 공시 원문(XBRL) 표에서 읽었습니다.",
    "수주잔고는 2014년부터 사업보고서 ‘수주상황’ 표의 회사별 계약잔액 합계입니다(연결기준 숫자는 문장에 있는 해만). "
    "앞뒤 보고서와 15% 넘게 어긋나는 보고서(표에 넣은 공사 범위가 다른 경우)는 그래프에서 뺐습니다.",
    "신규 수주는 현대건설 단독 수주실적이라 현대엔지니어링 등 자회사 수주가 빠져 있고, 보고서에 같은 문장이 없는 해는 비웠습니다.",
    "PF 보증은 정비사업 PF까지 포함하도록 바뀐 공시 기준(2023년 사업보고서부터)이라 그 전 숫자와 비교하지 않습니다.",
    "10가지 관점의 판정은 절대 기준이 아니라 최근 10년 안에서의 상대 위치이고, 가이드 6단계 판정은 아래의 단순 규칙을 따릅니다.",
    "주가는 월말 종가(네이버 금융, 실패하면 Yahoo Finance)이고 2021년 이전은 수정주가입니다.",
]


def appendix(ctx, F):
    gl = "".join(f"<div><dt>{esc(a)}</dt><dd>{esc(b)}</dd></div>" for a, b in GLOSSARY)
    rules = bullets(F["a"].get("rules", []), "small")
    refs = [link(url, name) for name, url in rv.REFS.values()] + [link(url, name) for name, url in an.SOURCES.values()]
    reports = []
    lf = ctx.get("latest_filing")
    if lf:
        reports.append(dart_link(lf["rcept_no"], f"{lf['report_nm'].strip()} ({d.fmt_date(lf['rcept_dt'])} 접수)"))
    seg = F["biz"].get("segments") or {}
    if seg.get("receipt") and (not lf or seg["receipt"] != lf["rcept_no"]):
        reports.append(dart_link(seg["receipt"], seg["report"]))
    cfg = ctx["company"]
    read = rtable(["자동으로 읽는 숫자", "사업보고서의 위치", "방법"], [[esc(a), esc(b), esc(c)] for a, b, c in READ_ITEMS], "r-read")
    body = (sub("A", "용어 풀이", f'<dl class="r-gloss">{gl}</dl>')
            + sub("B", "자료와 한계", '<p class="r-subnote">OpenDART에서 매월 새 보고서 원문(ZIP)을 받아 아래 위치의 표와 문장을 읽습니다. '
                  '형식이 낯선 보고서는 건너뛰고 지난번에 읽은 숫자를 씁니다.</p>' + read + bullets(LIMITS + [DISCLAIMER], "small")
                  + '<p class="r-subnote r-rules-h"><b>가이드 6단계 판정 규칙</b></p>' + rules)
            + sub("C", "출처", bullets(["공시: " + " · ".join(reports) + " · OpenDART(opendart.fss.or.kr)" if reports else "",
                                        "제도·업계 설명과 시기별 배경: " + " · ".join(refs),
                                        f"이 보고서를 만드는 코드와 데이터: {link(cfg.get('repo_url', ''), cfg.get('repo_url', ''))} · "
                                        f"재무제표 대시보드: {link(cfg.get('dashboard_url', ''), cfg.get('dashboard_url', ''))}"], "small src", raw=True)))
    return chapter("부록", "Appendix", "용어 · 자료와 한계 · 출처", "", body, "appendix")


# ---------------------------------------------------------------------------
# 문서 조립
# ---------------------------------------------------------------------------
# 한글 글꼴: 러너에서는 fonts-nanum(나눔고딕, TrueType)을 설치합니다. TrueType 글꼴은 PDF에 필요한 글자만 작게 들어가고,
# Noto Sans CJK 같은 CFF 글꼴은 Chrome이 글자마다 그림(Type 3)으로 넣어 파일이 몇 배 커집니다.
FONT_STACK = '"NanumGothic","나눔고딕",__FONTS__'
PRINT_CSS = """
@page{size:A4;margin:17mm 15mm 15mm 15mm;
  @top-left{content:"__TITLE__";font:500 7pt __FONTS__;color:#7a7d78;vertical-align:bottom;padding-bottom:4.5mm}
  @top-right{content:"__EDITION__";font:500 7pt __FONTS__;color:#7a7d78;vertical-align:bottom;padding-bottom:4.5mm}
  @bottom-left{content:"HSC-Class01 · OpenDART 공시로 매월 자동 생성";font:500 7pt __FONTS__;color:#7a7d78;vertical-align:top;padding-top:4mm}
  @bottom-right{content:counter(page) " / " counter(pages);font:600 7pt __FONTS__;color:#4a4f4c;vertical-align:top;padding-top:4mm}}
@page:first{margin:0;@top-left{content:none}@top-right{content:none}@bottom-left{content:none}@bottom-right{content:none}}
:root{--paper:#fff;--sheet:#fff;--zebra:#f7f6f2;--thead:#e8efec;--thead-2:#eff4f1;--tint:#f4f1ea;--tint-g:#ecf4f1;
  --font-sans:__FONTS__;--font-mono:var(--font-sans)}
html{font-size:12.4px;-webkit-print-color-adjust:exact;print-color-adjust:exact}
body{background:#fff;color:var(--ink);font:400 9.3pt/1.62 var(--font-sans);margin:0}
a{color:var(--link);text-decoration:none}
b{font-weight:700}

/* 표지 */
.cover{height:297mm;padding:20mm 19mm 16mm;background:var(--forest);color:var(--forest-ink);display:flex;flex-direction:column;overflow:hidden;break-after:page;position:relative}
.cover::before{content:"";position:absolute;inset:0;background-image:linear-gradient(var(--forest-line) 1px,transparent 1px),linear-gradient(90deg,var(--forest-line) 1px,transparent 1px);
  background-size:10mm 10mm;opacity:.35}
.cover>*{position:relative}
.cv-top{display:flex;justify-content:space-between;font-size:7.5pt;font-weight:600;letter-spacing:.14em;text-transform:uppercase;color:var(--forest-soft)}
.cv-main{margin-top:30mm}
.cv-eyebrow{margin:0;font-size:8pt;font-weight:600;letter-spacing:.2em;text-transform:uppercase;color:var(--forest-soft)}
.cover h1{margin:4mm 0 0;font-size:50pt;line-height:1.05;letter-spacing:-.04em;font-weight:700}
.cover h1 span{display:inline-block;margin-top:2mm;font-size:30pt;font-weight:500;letter-spacing:-.03em;color:var(--forest-soft)}
.cv-sub{margin:6mm 0 0;font-size:12.5pt;font-weight:500}
.cv-thesis{margin:13mm 0 0;max-width:150mm;padding-left:5mm;border-left:3px solid var(--forest-soft);font-size:11pt;line-height:1.8}
.cv-thesis b{color:#fff}
.cv-chart{margin:auto 0 0;padding-top:8mm}
.cv-bars{position:relative;height:26mm;border-bottom:1px solid var(--forest-soft)}
.cv-bars i{position:absolute;bottom:0;box-sizing:border-box;border-inline:1.1mm solid transparent;background:rgba(180,211,205,.32);background-clip:padding-box}
.cv-bars i.last{background:rgba(180,211,205,.85);background-clip:padding-box}
.cv-chart figcaption{display:flex;justify-content:space-between;margin-top:1.5mm;font-size:7pt;color:var(--forest-soft)}
.cv-kpis{margin-top:6mm;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));border-top:1px solid var(--forest-soft);border-bottom:1px solid var(--forest-line)}
.cv-k{padding:5mm 4mm 5mm 0;min-width:0}
.cv-k+.cv-k{padding-left:4mm;border-left:1px solid var(--forest-line)}
.cv-l{margin:0;font-size:8pt;font-weight:600;color:var(--forest-soft)}
.cv-v{margin:1mm 0 0;font-size:21pt;font-weight:700;letter-spacing:-.03em;line-height:1.15}
.cv-v small{margin-left:1mm;font-size:9pt;font-weight:500}
.cv-s{margin:1mm 0 0;font-size:7.3pt;line-height:1.45;color:var(--forest-soft)}
.cv-meta{margin:6mm 0 0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:0;border:1px solid var(--forest-line)}
.cv-meta>div{padding:2.2mm 3mm;border-bottom:1px solid var(--forest-line);min-width:0}
.cv-meta>div:nth-child(odd){border-right:1px solid var(--forest-line)}
.cv-meta>div:nth-last-child(-n+2){border-bottom:0}
.cv-meta dt{font-size:6.5pt;font-weight:600;letter-spacing:.12em;color:var(--forest-soft)}
.cv-meta dd{margin:.5mm 0 0;font-size:7.8pt;line-height:1.45;overflow-wrap:anywhere}
.cv-meta a{color:var(--forest-ink)}
.cv-note{margin:3mm 0 0;font-size:6.8pt;line-height:1.5;color:var(--forest-soft)}

/* 장 머리 */
.r-chap{break-before:page}
.r-head{display:flex;align-items:flex-end;gap:5mm;margin:0 0 4.5mm;padding-bottom:3mm;border-bottom:2px solid var(--forest)}
.r-num{font-size:30pt;font-weight:700;line-height:.95;letter-spacing:-.04em;color:var(--forest)}
.r-tt p{margin:0;font-size:7.5pt;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--data)}
.r-tt h2{margin:.8mm 0 0;font-size:17pt;line-height:1.25;letter-spacing:-.03em}
.r-lead{margin:0 0 3mm;font-size:10.2pt;line-height:1.75}
.r-sec{margin:6.5mm 0 0}
.r-sec>h3{margin:0 0 2mm;font-size:11.5pt;letter-spacing:-.015em;break-after:avoid}
.r-sec.keep{break-inside:avoid}
.r-sec>h3 .k{display:inline-block;min-width:9mm;margin-right:1.5mm;color:var(--data);font-weight:700}
.r-subnote{margin:0 0 2.5mm;font-size:8.6pt;color:var(--ink-2)}
.r-p{margin:3mm 0;font-size:9.2pt}
.r-src{margin:1.5mm 0 0;font-size:7.4pt;line-height:1.55;color:var(--muted)}
.r-src a{color:var(--link)}
span.r-src{display:block}
.r-2{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:5mm;align-items:start;margin-top:4mm}
.r-box{margin-top:4mm;padding:3.5mm 4.5mm;border-radius:2mm;background:var(--tint);break-inside:avoid}
.r-2>.r-box{margin-top:0}
.r-box .r-h{margin:0 0 1.5mm;font-size:9.8pt;font-weight:700;letter-spacing:-.01em}
.r-box p{margin:0 0 1.5mm;font-size:8.8pt}
.r-box.good{background:var(--tint-g);border-top:3px solid var(--good)}
.r-box.crit{background:#f8eeec;border-top:3px solid var(--crit)}
.r-box.warn{background:#fbf3e2;border-top:3px solid var(--warn)}
.r-box.plain{background:none;border:1px solid var(--line)}
.r-box.cols .r-ul{columns:2;column-gap:7mm}
.r-box.cols .r-ul li{break-inside:avoid}
.r-ul{margin:0;padding-left:4.2mm;font-size:8.8pt}
.r-ul li{margin:.9mm 0}
.r-ul.small{font-size:8.2pt}
.r-ul.tight{margin-top:1mm;font-size:8pt}
.r-ul.tight li{margin:.3mm 0}
.r-ul.src{font-size:7.6pt;color:var(--ink-2)}

/* 요약 */
.r-finds{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3.2mm;margin-top:3mm}
.r-find{position:relative;padding:2.6mm 3.5mm 2.2mm 12mm;border:1px solid var(--line);border-radius:2mm;break-inside:avoid}
.r-fno{position:absolute;left:3.5mm;top:2.6mm;margin:0;font-size:12pt;font-weight:700;color:var(--data)}
.r-find .r-h{margin:0;font-size:10pt;font-weight:700;letter-spacing:-.01em}
.r-find p{margin:.8mm 0 0;font-size:8.2pt;line-height:1.55}
.r-find .r-fref{margin-top:1mm;font-size:7.4pt;font-weight:600;color:var(--data)}
.r-order{margin:5mm 0 0;padding-top:3mm;border-top:1px solid var(--line);font-size:8pt;color:var(--ink-2)}
.r-order b{margin-right:2mm;color:var(--ink)}
.r-chip{display:inline-block;padding:.3mm 2.2mm;border-radius:9mm;font-size:7.6pt;font-weight:700;white-space:nowrap}
.r-chip.good{background:var(--good-bg)}
.r-chip.warn{background:var(--warn-bg)}
.r-chip.crit{background:var(--crit-bg)}
.r-chip.info{background:var(--hover)}

/* 표 */
.r-table{width:100%;border-collapse:collapse;margin-top:2mm;font-size:8.1pt;line-height:1.5;break-inside:auto}
.r-table caption{caption-side:top;text-align:left;padding:0 0 1mm;font-size:8pt;font-weight:600;color:var(--ink-2)}
.r-table th,.r-table td{padding:1.4mm 2mm;border-bottom:1px solid var(--grid);text-align:left;vertical-align:top;white-space:normal}
.r-table thead th{background:var(--thead);font-weight:600;font-size:7.6pt;color:var(--ink-2);border-bottom:1px solid var(--line)}
.r-table tbody th{font-weight:500}
.r-table tr{break-inside:avoid}
.r-table td.num,.r-table th.num{text-align:right;white-space:nowrap;font-variant-numeric:tabular-nums}
.r-table td.neg{color:var(--neg-text)}
.r-table .r-q{display:block;font-size:7.2pt;font-weight:400;color:var(--muted)}
.r-guide td:nth-child(2){white-space:nowrap}
.r-guide td,.r-guide th{padding:1.1mm 2mm;font-size:7.9pt}
.r-why td,.r-why th{font-size:7.6pt;padding:.9mm 1.8mm;line-height:1.45}
.r-ch2 .r-box{padding:2.6mm 3.6mm}
.r-ch2 .r-box .r-ul{font-size:8pt}
.r-ch2 .r-box .r-ul li{margin:.6mm 0}
.r-guide th{white-space:nowrap}
.r-why th{width:22%}.r-why td:nth-child(2){width:24%}.r-why td:nth-child(3){width:22%}
.r-read th{width:30%}
.r-poc{max-width:150mm}
.r-poc td{width:22%}
.r-acts{table-layout:fixed}.r-acts thead th:nth-child(1){width:11%}.r-acts thead th:nth-child(2){width:37%}.r-acts tbody th{white-space:nowrap}
.r-acts td,.r-acts th{font-size:7.7pt;padding:1.2mm 1.8mm}
.r-acts .r-facts{display:block;margin-top:.6mm;color:var(--ink-2)}
.r-mat td,.r-mat th{padding:1mm 2mm}
.r-lens td:nth-child(4){white-space:nowrap}
.r-lens td,.r-lens th{padding:1mm 1.8mm;font-size:7.8pt;line-height:1.4}
.r-lens .r-chip{font-size:7.2pt}
.r-doc .heat{break-inside:avoid}
.r-watch th{width:22%}.r-watch td:nth-child(2){width:24%}
.r-mat td:last-child{font-size:7.2pt;color:var(--muted)}
.r-dupont th{width:12%}

/* 대시보드 부품을 인쇄에 맞게 */
.r-doc .chart{margin:0;padding:0;border:0;border-radius:0;background:none;break-inside:avoid}
.r-doc .stack,.r-doc .r-sec>.chart{margin-top:0}
.r-doc .chart-head .ft,.r-doc .buyer .ft{margin:0;font-size:9.4pt;font-weight:700;letter-spacing:-.01em}
.r-doc .fig-no{margin-right:2.2mm;color:var(--data)}
.r-doc .chart-head p{font-size:7.4pt}
.r-doc .chart-note{margin-top:1.8mm;font-size:7.8pt;line-height:1.55}
.r-doc .legend{margin-top:1.5mm;font-size:7.3pt;gap:1mm 3.5mm}
.r-doc .plot{margin-top:2mm}
.r-doc .chart .plot{--h:150px!important}
.r-doc .chart.wide .plot{--h:165px!important}
.r-doc details.tv{display:none}
.r-doc .table-scroll{overflow:visible;margin-top:2mm;border:0;border-radius:0;background:none}
.r-doc .table-scroll table{font-size:7.6pt}
.r-doc .table-scroll th,.r-doc .table-scroll td{padding:1.1mm 1.6mm}
.r-doc .table-scroll tbody th,.r-doc .table-scroll thead th:first-child{position:static}
.r-doc .table-scroll caption{padding:0 0 1mm;font-size:7.6pt}
.r-doc .heat td{font-size:7.2pt;padding:1mm .8mm}
.r-doc .heat th small{margin-left:1mm;font-size:6.4pt}
.r-doc .sig td.lab{min-width:0}
.r-doc .vtiles{grid-template-columns:repeat(4,minmax(0,1fr));margin:3mm 0 4mm;border-radius:2mm}
.r-doc .vtiles:has(.vt:nth-child(6)){grid-template-columns:repeat(3,minmax(0,1fr))}
.r-doc .vt{padding:2mm 3mm}
.r-doc .vt-l{font-size:7.4pt}
.r-doc .vt-v{font-size:14pt}
.r-doc .vt-d{font-size:6.9pt;line-height:1.4}
.r-doc .r-2>.chart{margin-top:0}
.r-doc .plot.lc{margin-right:6mm}
.r-doc #fig-price-report .plot{--h:118px!important}
.r-doc .grid-2,.r-doc .grid-3{display:grid;gap:5mm}
.r-doc .card{padding:3mm 3.5mm;border-radius:2mm;break-inside:avoid}
.r-doc ul.plain{font-size:8.2pt;padding-left:4mm}
.r-doc ul.plain li{margin:.8mm 0}
.r-doc .card-foot{margin-top:2mm;padding-top:1.5mm;font-size:7pt}

/* 1장: 돈이 도는 여섯 단계 · 발주처 · 시장 */
.r-doc .flow{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4mm 7mm}
.r-doc .fl{position:relative;display:flex;flex-direction:column;padding:3mm 3.5mm 2.5mm;border:1px solid var(--line);border-radius:2mm;background:#fff;break-inside:avoid}
.r-doc .fl:not(:nth-child(3n))::after{content:"";position:absolute;right:-5.2mm;top:8mm;width:2.4mm;height:2.4mm;border-top:1.6px solid var(--axis);border-right:1.6px solid var(--axis);transform:rotate(45deg)}
.r-doc .fl-top{display:flex;align-items:center;gap:2mm;margin:0;font-size:9.6pt}
.r-doc .fl-no{display:inline-grid;place-items:center;width:5mm;height:5mm;border-radius:50%;background:var(--data);color:#fff;font-size:7pt;font-weight:700}
.r-doc .fl-what{margin:.5mm 0 0;font-size:7.4pt;color:var(--muted)}
.r-doc .fl-v{margin:2mm 0 0;font-size:15pt;font-weight:700;letter-spacing:-.02em;line-height:1.15}
.r-doc .fl-basis{margin:.5mm 0 0;font-size:7.2pt;color:var(--muted)}
.r-doc .fl-sub{margin:1.2mm 0 0;font-size:7.8pt;color:var(--ink-2)}
.r-doc .fl-gap{flex:1 0 2mm}
.r-doc .fl-where{margin:0;padding-top:1.5mm;border-top:1px dashed var(--line);font-size:7pt;font-weight:600;color:var(--data)}
.r-doc .flow-loop{margin:2mm 0 0;font-size:7.8pt;color:var(--muted)}
.r-doc .buyers{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:4mm;margin:0}
.r-doc .buyer .ft{font-size:9.8pt}
.r-doc .buyer-who{margin:.5mm 0 1.5mm;font-size:7.6pt;font-weight:600;color:var(--data)}
.r-doc .r-sec>.chart.mk{margin-top:5mm}
.r-doc .mk-bars{margin-top:2mm;display:grid;gap:1.6mm}
.r-doc .mk-row{display:grid;grid-template-columns:12mm minmax(0,1fr);gap:3mm;align-items:center}
.r-doc .mk-l{font-size:7.6pt;color:var(--muted)}
.r-doc .mk-t{position:relative;height:6.5mm}
.r-doc .mk-seg{position:absolute;top:0;bottom:0;display:flex;align-items:center;padding-left:2.5mm;font-style:normal;font-size:7.8pt;font-weight:700;color:var(--ink);
  background:color-mix(in srgb,var(--c) 26%,#fff);border-left:3px solid var(--c);white-space:nowrap;overflow:hidden}
.r-doc .mk-seg+.mk-seg{box-shadow:inset 2px 0 0 #fff}
.r-doc .hs{margin-top:2mm;gap:.4mm}
.r-doc .hs-row{grid-template-columns:minmax(0,62mm) minmax(0,1fr) auto;gap:1mm 3mm;padding:.8mm 0}
.r-doc .hs-l b{font-size:8pt}
.r-doc .hs-meta{font-size:6.6pt}
.r-doc .hs-t{height:3.2mm}
.r-doc .hs-v{font-size:7.6pt}
.r-doc .hs-unit{margin-top:1.5mm;font-size:7pt}

/* 2장: 목차 */
.r-chapters{list-style:none;margin:0;padding:0;display:grid;gap:.6mm}
.r-chapters li{display:grid;grid-template-columns:8mm minmax(0,1fr);gap:1.5mm;padding:.5mm 1.8mm;border-radius:1.2mm;font-size:7.3pt;line-height:1.4;color:var(--muted)}
.r-chapters li b{font-weight:600}
.r-chapters li.on{background:#fff;color:var(--ink-2)}
.r-chapters li.on b{color:var(--ink)}
.r-chapters .cn{font-weight:700}
.r-chapters li.on .cn{color:var(--data)}

/* 부록 */
.r-gloss{margin:0;display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1.4mm 6mm}
.r-gloss>div{break-inside:avoid}
.r-gloss dt{font-size:8.6pt;font-weight:700}
.r-gloss dd{margin:.2mm 0 0;font-size:7.7pt;color:var(--ink-2);line-height:1.5}
.r-read td,.r-read th{font-size:7.6pt;padding:1mm 1.8mm}
.r-rules-h{margin-top:3mm}
.r-close{margin-top:6mm;padding:4mm 5mm;border-left:3px solid var(--forest);background:var(--tint-g)}
"""


def build_html(ctx):
    """인쇄용 HTML 전체(문자열). 같은 자료면 언제나 같은 글자가 나옵니다(해시 비교용)."""
    cfg = ctx["company"]
    F = facts(ctx)
    title = f"{cfg['name']} 기업분석 보고서"
    parts = [cover(ctx, F), summary_page(ctx, F)]
    for build in (ch1_structure, ch2_report, ch3_orders, ch4_profit, ch5_cash, ch6_lenses, ch7_market, ch8_opinion, appendix):
        try:
            parts.append(build(ctx, F))
        except Exception as exc:     # 한 장이 실패해도 나머지 장으로 보고서를 만듭니다
            print(f"::warning::기업분석 보고서 {build.__name__} 생략: {type(exc).__name__}: {exc}")
    css = (PRINT_CSS.replace("__TITLE__", css_text(title)).replace("__EDITION__", css_text(edition(ctx)))
           .replace("__FONTS__", FONT_STACK))
    body = number_figures("".join(parts))
    return ("<!doctype html>\n<html lang=\"ko\" data-theme=\"light\"><head><meta charset=\"utf-8\">"
            f"<title>{esc(title)} ({esc(edition(ctx))})</title>"
            f"<meta name=\"author\" content=\"HSC-Class01 · OpenDART 재무분석 에이전트\">"
            f"<style>{d.CSS}{css}</style></head>"
            f"<body><main class=\"r-doc\">{body}</main></body></html>\n")


def number_figures(html_text):
    """그림 제목 앞에 '그림 1'부터 차례로 번호를 붙이고, 그림·카드 제목은 PDF 책갈피에 들어가지 않게 문단으로 바꿉니다.
    (책갈피에는 장과 번호 붙은 소제목만 남깁니다.)"""
    count = [0]

    def add(m):
        count[0] += 1
        return f'<figcaption class="chart-head"><p class="ft"><span class="fig-no">그림 {count[0]}</span> {m.group(1)}</p>'
    html_text = re.sub(r'<figcaption class="chart-head"><h3>(.*?)</h3>', add, html_text)
    return re.sub(r'<article class="card buyer"><h3>(.*?)</h3>', r'<article class="card buyer"><p class="ft">\1</p>', html_text)


def css_text(text):
    """CSS content 문자열 안에 넣을 수 있게 따옴표·역슬래시를 막습니다."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# PDF 인쇄 (헤드리스 Chrome)
# ---------------------------------------------------------------------------
CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")
CHROME_PATHS = ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")


def find_chrome():
    """PDF를 인쇄할 Chrome(또는 Chromium·Edge) 실행 파일. 없으면 None."""
    for env in ("CHROME_PATH", "CHROME_BIN"):
        path = os.environ.get(env)
        if path and Path(path).exists():
            return path
    for name in CHROME_NAMES:
        path = shutil.which(name)
        if path:
            return path
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    for base in (Path.home() / ".cache" / "ms-playwright", Path("/opt/pw-browsers")):     # Playwright가 받아 둔 Chromium
        found = sorted(base.glob("chromium-*/chrome-linux/chrome")) if base.exists() else []
        if found:
            return str(found[-1])
    return None


def korean_font_ok():
    """한글 글꼴이 있는지(fontconfig가 있는 리눅스에서만 확인). 없으면 PDF 글자가 네모로 나옵니다."""
    if not shutil.which("fc-list"):
        return True        # Windows·macOS는 기본 한글 글꼴이 있습니다
    try:
        out = subprocess.run(["fc-list", ":lang=ko", "family"], capture_output=True, text=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return True
    return bool(out.strip())


def print_pdf(chrome, html_text, out_pdf, timeout=180):
    """HTML 문자열을 A4 PDF로 인쇄합니다. 성공하면 쪽수를 돌려줍니다."""
    out_pdf = Path(out_pdf)
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "report.html"
        src.write_text(html_text, encoding="utf-8")
        target = Path(tmp) / "report.pdf"
        cmd = [chrome, "--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage", "--hide-scrollbars",
               "--no-first-run", "--no-default-browser-check", f"--user-data-dir={Path(tmp) / 'profile'}",
               "--no-pdf-header-footer", "--generate-pdf-document-outline", "--run-all-compositor-stages-before-draw",
               "--virtual-time-budget=8000",
               f"--print-to-pdf={target}", src.resolve().as_uri()]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        data = target.read_bytes() if target.exists() else b""
        if not data.startswith(b"%PDF") or len(data) < 20_000:
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            raise RuntimeError(f"Chrome이 PDF를 만들지 못했습니다(종료 코드 {proc.returncode}): {' / '.join(tail)}")
        out_pdf.parent.mkdir(parents=True, exist_ok=True)
        out_pdf.write_bytes(data)
    return len(re.findall(rb"/Type\s*/Page[^s]", data))


def write(ctx, root):
    """기업분석 보고서 PDF를 (내용이 바뀐 경우에만) 다시 인쇄합니다. 반환: 한 줄 결과."""
    root = Path(root)
    pdf, state_path = root / PDF_PATH, root / STATE_PATH
    html_text = build_html(ctx)
    digest = hashlib.sha256(html_text.encode("utf-8")).hexdigest()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if pdf.exists() and state.get("source_sha256") == digest:
        msg = f"기업분석 보고서 PDF: 내용이 같아 그대로 둠 ({state.get('pages', '?')}쪽)"
        print(msg)
        return msg
    chrome = find_chrome()
    if not chrome:
        msg = "기업분석 보고서 PDF 건너뜀: Chrome(Chromium)을 찾지 못했습니다. 설치 후 다시 실행하거나 CHROME_PATH를 지정하세요."
        print(f"::warning::{msg}")
        return msg
    if not korean_font_ok():
        msg = "기업분석 보고서 PDF 건너뜀: 한글 글꼴이 없습니다(예: sudo apt-get install fonts-noto-cjk)."
        print(f"::warning::{msg}")
        return msg
    pages = print_pdf(chrome, html_text, pdf)
    state = {"pdf": PDF_PATH, "source_sha256": digest, "pages": pages, "bytes": pdf.stat().st_size,
             "edition": edition(ctx), "printed_with": Path(chrome).name}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    msg = f"기업분석 보고서 PDF: 새로 인쇄 ({pages}쪽, {pdf.stat().st_size / 1024:,.0f}KB) → {PDF_PATH}"
    print(msg)
    return msg
