"""기업분석 보고서(PDF): 현대건설 종합 사업분석 — 건설사는 어떻게 돈을 벌고, 무엇이 현대건설의 10년을 움직였나.

순서: 표지 → 요약 → 1 문제의식과 방법 → 2 건설업이 돈을 버는 구조 → 3 그래서 사업보고서를 읽는다 → 4 현대건설은 어디서 버나
      → 5 성장에 중요한 재무항목 → 6 무엇이 실적을 움직였나 → 7 10년 연표 → 8 현재: 번 돈을 어디에 썼나
      → 9 미래: 성장사업과 시나리오 → 10 종합 평가 → 부록(방법·자료와 한계·용어·출처)

- 숫자·그래프·숫자로 쓴 문장은 매월 다시 계산합니다. 재료는 ctx(재무제표 표), ctx['business'](사업보고서 본문, business.py),
  ctx['drivers'](사업보고서 주석·현금흐름표 세부, drivers.py)이고, 원인 분해 계산은 research.py가 합니다.
- 사람이 조사한 내용(연도별 사건·정책·경쟁사 사건, 미래사업 단계, 사업 유형 설명)은 config/research.json에서 읽고,
  보고서에 조사 기준일을 적습니다. 조사하지 않은 새 사업연도는 '조사 전'으로 표시하고 경영진단 문장을 자동으로 옮깁니다.
- 문장마다 근거 종류를 표시합니다: [공시] 사업보고서·감사보고서, [계산] 공시 숫자로 계산, [가정] 가정을 둔 계산,
  [보도] 언론·통계·기관 자료, [해석] 분석자의 판단.
- 차트는 대시보드와 같은 부품(HTML·CSS·SVG)을 쓰고, 인쇄용 CSS를 덧씌운 HTML을 헤드리스 Chrome으로 A4 PDF로 인쇄합니다.
  에이전트는 파이썬 표준 라이브러리만 쓰므로 PDF 그리기는 GitHub Actions 러너에 기본으로 있는 Chrome에 맡깁니다.
- Chrome이나 한글 글꼴이 없는 환경에서는 PDF를 건너뛰고 경고만 남깁니다(이전 PDF는 그대로 둡니다).
- 내용이 같으면 다시 인쇄하지 않습니다. 인쇄한 HTML의 해시를 data/financials/report_pdf.json에 적어 두고 비교합니다
  (PDF는 만들 때마다 파일 안의 날짜가 바뀌어, 매번 새로 만들면 내용이 같아도 커밋이 생기기 때문입니다).
"""
import hashlib
import html
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
import report_charts as rc
import report_view as rv
import research as rs
import statements as st

T = an.T
EOK = 100_000_000
esc, rich = d.esc, d.rich
PDF_PATH = d.REPORT_PDF                       # reports/hyundai-company-report.pdf
STATE_PATH = "data/financials/report_pdf.json"
RESEARCH_PATH = Path(__file__).resolve().parents[1] / "config" / "research.json"
SEG = rs.SEG
SEG_KO = {"building": "건축/주택", "civil": "토목", "plant": "플랜트/전력", "other": "기타"}
SEG_COLOR = {"building": "--s1", "civil": "--s3", "plant": "--s2", "other": "--s4"}
REGION_KO = {"domestic": "국내", "asia": "아시아", "mideast": "중동·아프리카", "other": "기타(미주·유럽 등)"}
REGION_COLOR = {"domestic": "--s1", "asia": "--s3", "mideast": "--s2", "other": "--s4"}


# ---------------------------------------------------------------------------
# 공통 조각
# ---------------------------------------------------------------------------
def load_research(path=RESEARCH_PATH):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def edition(ctx):
    y, m = ctx["today"][:4], int(ctx["today"][5:7])
    return f"{y}년 {m}월판"


EV_CLASS = {"공시": "d", "계산": "c", "가정": "a", "추정": "a", "보도": "n", "통계": "n", "법령": "n", "WHO": "n",
            "한국은행": "n", "위키백과": "n", "해석": "h", "가설": "h"}


def ev(label):
    """근거 표시 배지. label 예: '공시', '공시: 대한건설협회 인용', '공시·보도'."""
    first = re.split(r"[:·\s]", label.strip())[0]
    return f'<span class="ev ev-{EV_CLASS.get(first, "n")}">{esc(label.strip())}</span>'


def tagify(text):
    """**굵게**와 [근거] 표시를 HTML로 바꿉니다."""
    out = rich(text or "")
    return re.sub(r"\[([^\[\]]{1,60})\]", lambda m: ev(html.unescape(m.group(1))), out)


def chapter(no, en, title, lead, body, cid):
    lead_html = "".join(f'<p class="r-lead">{tagify(x)}</p>' for x in ([lead] if isinstance(lead, str) else lead) if x)
    return (f'<section class="r-chap" id="{cid}"><header class="r-head"><span class="r-num">{no}</span>'
            f'<div class="r-tt"><p>{esc(en)}</p><h2>{esc(title)}</h2></div></header>{lead_html}{body}</section>')


def sub(no, title, body, note=None, keep=False):
    """번호 붙은 소제목 + 설명 + 내용. keep=True면 한 쪽 안에 통째로 둡니다(제목만 쪽 끝에 남지 않게)."""
    note_html = f'<p class="r-subnote">{tagify(note)}</p>' if note else ""
    num_html = f'<span class="k">{esc(no)}</span> ' if no else ""
    cls = "r-sec keep" if keep else "r-sec"
    return f'<div class="{cls}"><div class="r-hn"><h3>{num_html}{esc(title)}</h3>{note_html}</div>{body}</div>'


def box(title, body, cls=""):
    head = f'<p class="r-h">{esc(title)}</p>' if title else ""
    return f'<div class="r-box {cls}">{head}{body}</div>'


def bullets(items, cls="", raw=False):
    """글머리 목록. raw=True면 이미 HTML로 만든 줄(링크 등)을 그대로 넣습니다."""
    return f'<ul class="r-ul {cls}">{"".join(f"<li>{x if raw else tagify(x)}</li>" for x in items if x)}</ul>'


def para(text, cls="r-p"):
    return f'<p class="{cls}">{tagify(text)}</p>' if text else ""


def head_tags(h):
    """표 머리글 속 [계산]·[가정] 같은 근거 표시를 배지로 바꿉니다(머리글은 이미 HTML이라 tagify를 쓰지 않음)."""
    return re.sub(r"\[([^\[\]<>]{1,30})\]",
                  lambda m: ev(m.group(1)) if re.split(r"[:·\s]", m.group(1).strip())[0] in EV_CLASS else m.group(0), h)


def rtable(headers, rows, cls="", caption=None):
    """보고서용 표. 셀은 이미 HTML로 만든 문자열입니다(rich/esc 사용). 숫자 칸은 ('num', 문자열)로 넘깁니다."""
    th = "".join(f'<th scope="col">{head_tags(h)}</th>' for h in headers)
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


def src_links(F, keys, short=False):
    """출처 링크. short=True면 표 안에서 '매체, 날짜'까지만 적습니다(괄호 속 기사 설명은 부록 출처 목록에 그대로)."""
    srcs = (F["RC"].get("sources") or {})
    def name(n):
        return re.sub(r"\s*\([^()]*\)\s*$", "", n) if short and re.search(r",\s*20\d\d", n) else n
    return " · ".join(link(srcs[k][1], name(srcs[k][0])) for k in keys if k in srcs)


def won(x):
    return an.won(x) + " 원" if x is not None else "–"


def jo(x, digits=2):
    """원 → '1.26조' (부호 −)."""
    return "–" if x is None else an._m(f"{x / T:,.{digits}f}조")


def sjo(x, digits=2):
    return "–" if x is None else an._m(f"{x / T:+,.{digits}f}조")


def eok(x):
    return "–" if x is None else an._m(f"{round(x / EOK):,}억")


def seok(x):
    return "–" if x is None else an._m(f"{round(x / EOK):+,}억")


def pct(x, digits=1):
    return "–" if x is None else an._m(f"{x:,.{digits}f}%")


def fig(fid, title, subt, body, *, legend_html="", note=None, wide=False):
    """대시보드 figure와 같은 모양. 설명(note)의 [근거] 표시를 배지로 바꿉니다."""
    note_html = f'<p class="chart-note">{tagify(note)}</p>' if note else ""
    cls = "chart wide" if wide else "chart"
    return (f'<figure class="{cls}" id="{fid}"><figcaption class="chart-head"><h3>{esc(title)}</h3>'
            f'<p>{esc(subt)}</p></figcaption>{legend_html}{body}{note_html}</figure>')


def nd_text(nd, digits=2):
    """순차입금(+) 또는 순현금(−)을 말로."""
    if nd is None:
        return "–"
    return f"순현금 {jo(-nd, digits)}" if nd < 0 else f"순차입금 {jo(nd, digits)}"


def tiles_html(items):
    return ('<div class="vtiles">' + "".join(f'<div class="vt"><p class="vt-l">{esc(a)}</p><p class="vt-v">{esc(b)}<small>{esc(c)}</small></p>'
                                             f'<p class="vt-d">{esc(e)}</p></div>' for a, b, c, e in items) + "</div>")


def median(xs):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    k = len(xs)
    return xs[k // 2] if k % 2 else (xs[k // 2 - 1] + xs[k // 2]) / 2


FINAL_DIGIT = {"0": (True, False), "1": (True, True), "2": (False, False), "3": (True, False), "4": (False, False),
               "5": (False, False), "6": (True, False), "7": (True, True), "8": (True, True), "9": (False, False)}


def josa(word, kind):
    """받침에 맞는 조사를 붙입니다. kind: '이'(이/가) · '을'(을/를) · '은'(은/는) · '으로'(으로/로) · '과'(과/와) · '이었'(이었/였).
    숫자는 읽는 소리(일·이·삼…), %는 '퍼센트'로 봅니다."""
    ch = (word or " ").rstrip()[-1:] or " "
    code = ord(ch) - 0xAC00
    if 0 <= code < 11172:
        final, rieul = code % 28 != 0, code % 28 == 8
    else:
        final, rieul = FINAL_DIGIT.get(ch, (False, False))
    if kind == "으로":
        return word + ("로" if (not final or rieul) else "으로")
    if kind == "이었":
        return word + ("이었" if final else "였")
    a, b = {"이": ("이", "가"), "을": ("을", "를"), "은": ("은", "는"), "과": ("과", "와")}[kind]
    return word + (a if final else b)


def xlabels(years):
    return [d.year_label(t) for t in years]


# ---------------------------------------------------------------------------
# 여러 장에서 함께 쓰는 숫자
# ---------------------------------------------------------------------------
def facts(ctx):
    a = ctx["analysis"]
    v = an.View(ctx)
    R = rs.build(ctx)
    years = R["years"]
    biz = rv.biz_of(ctx)
    F = {"a": a, "v": v, "vd": a["verdicts"], "steps": {s["id"]: s for s in a.get("steps", [])}, "R": R, "RC": load_research(),
         "years": years, "years10": ln.window_years(ctx), "v10": st.ten_view(ctx, ln.window_years(ctx)), "L": ln.build(ctx),
         "biz": biz, "dr": ctx.get("drivers") or {}}
    y0, yl = years[0], years[-1]
    F.update(y0=y0, yl=yl, rev0=v.a(y0, "revenue"), revl=v.a(yl, "revenue"), op0=v.a(y0, "operating_profit"),
             opl=v.a(yl, "operating_profit"), m0=v.a(y0, "operating_margin_pct"), ml=v.a(yl, "operating_margin_pct"))
    lb = rv.latest_backlog(ctx)
    F["lb"] = lb
    F["yrs"] = rv.years_of_work(ctx, lb) if lb else None
    pf = rv.pf_rows(ctx)
    F["pf"] = pf
    F["pf_x"] = None
    if pf:
        p, r = pf[-1]
        b = rv.balance_at(ctx, int(p[:4]), int(p[5:]))
        F["pf_x"] = r["amount"] / b["values"]["equity"] if b else None
    F["bal"] = v.latest_balance()
    F["projects"] = (biz.get("projects") or {}).get("rows") or []
    F["orders"] = biz.get("orders") or {}
    # 원가 추정 변경: 10년 합계와 2016~2021 평균(평상시)
    est = {r["year"]: r for r in R["estimates"]}
    F["est"] = est
    calm = [est[y]["current"] for y in years if y <= 2021 and y in est and est[y]["current"] is not None]
    F["est_calm"] = sum(calm) / len(calm) if calm else None
    F["est_sum"] = sum(est[y]["current"] for y in years if y in est and est[y]["current"] is not None) if est else None
    F["est_worst"] = min(est.values(), key=lambda r: r["current"] if r["current"] is not None else 0) if est else None
    F["seg"] = {r["year"]: r for r in R["segments"]}
    F["ent"] = {r["year"]: r for r in R["entity"]}
    F["cash"] = {r["year"]: r for r in R["cash"]}
    F["cashw"] = {(w["start"], w["end"]): w for w in R.get("cash_windows") or []}
    F["recv"] = R.get("receivables") or {"rows": [], "split": {}}
    F["recv_by"] = {r["year"]: r for r in F["recv"]["rows"]}
    neg = [y for y in years if (v.a(y, "operating_cashflow") or 0) < 0]
    F["streak"] = F["vd"].get("streak") or 0
    F["neg_start"] = R.get("alloc_split")
    F["margin_med"] = median(v.a(y, "operating_margin_pct") for y in years)
    F["cfo_neg_years"] = neg
    F["est_life_sum"] = sum(est[y]["lifetime"] for y in years if y in est and est[y].get("lifetime") is not None) if est else None
    F["est_future_sum"] = sum(est[y]["future"] for y in years if y in est and est[y].get("future") is not None) if est else None
    rt = (F["dr"].get("revenue_types") or {})
    F["rev_types"] = {int(y): x for y, x in rt.items()}
    F["review"] = review_status(ctx, F["RC"])
    return F


def review_status(ctx, RC):
    """조사 기준일(research.json의 as_of) 뒤에 접수된 공시가 있으면 [(보고서 이름, 접수일)].
    숫자·그래프는 자동으로 새 공시를 반영하지만, 연표·해석 문장은 조사 기준일까지의 자료로 쓴 것이라 사람이 다시 봐야 합니다."""
    as_of = (RC.get("as_of") or "").replace("-", "")
    lf = ctx.get("latest_filing") or {}
    if not as_of or not lf.get("rcept_dt"):
        return []
    return [(lf.get("report_nm", "").strip(), lf["rcept_dt"])] if lf["rcept_dt"] > as_of else []


def window_sum(F, key, start, end):
    v = F["v"]
    vals = [v.a(y, key) for y in range(start, end + 1)]
    return sum(x for x in vals if x is not None) if any(x is not None for x in vals) else None


def bridge_shares(F):
    """연도별 영업이익 변화(두 해 평균 기준 분해)에서 효과별 절댓값 합의 비중(%) — research.abs_shares."""
    return F["R"].get("bridge_shares") or rs.abs_shares(F["R"]["bridges"])


def peer_gap_years(F):
    """현대건설 영업이익률이 동종사 중앙값보다 낮았던 해."""
    out = []
    for y, p in F["R"]["peers"].items():
        if p["own"] is not None and p["median"] is not None and p["n"] >= 2 and p["own"] < p["median"]:
            out.append(y)
    return out


# ---------------------------------------------------------------------------
# 표지
# ---------------------------------------------------------------------------
def cover_chart(F):
    """표지의 10년 매출 막대와 영업이익률."""
    v, years = F["v"], F["years"]
    rev = [v.a(y, "revenue") for y in years]
    top = max(x for x in rev if x)
    n = len(years)
    bars = "".join(f'<i class="{"last" if i == n - 1 else ""}" style="left:{i / n * 100:.3f}%;width:{100 / n:.3f}%;height:{x / top * 100:.2f}%"></i>'
                   for i, x in enumerate(rev) if x)
    margins = "".join(f'<span style="left:{(i + .5) / n * 100:.3f}%">{an.pct(v.a(y, "operating_margin_pct"))}%</span>'
                      for i, y in enumerate(years))
    return (f'<figure class="cv-chart" aria-label="연간 매출액 막대와 영업이익률"><div class="cv-bars">{bars}</div>'
            f'<div class="cv-m">{margins}</div>'
            f'<figcaption><span>{years[0]}년 {an.jo(rev[0])}조 원</span><span>연간 매출액(막대) · 영업이익률(숫자) · 연결</span>'
            f'<span>{years[-1]}년 {an.jo(rev[-1])}조 원</span></figcaption></figure>')


def cover_thesis(F):
    b = F["R"]["bridge_10y"]
    parts = []
    if b:
        parts.append(f"{b['start']}→{b['end']}년 매출은 **{b['rev1'] / b['rev0']:.2f}배**가 됐지만 영업이익은 "
                     f"**{an.won(abs(b['d_op']))} 원 {'늘었' if b['d_op'] >= 0 else '줄었'}습니다**. 매출이 커져 생긴 이익(" + sjo(b['volume'])
                     + f")보다 원가율이 올라 잃은 이익({sjo(b['cost'])})이 컸고, 계산 방법과 기간을 바꿔도 이 순서는 같습니다.")
    w = F["est_worst"]
    if w and w["current"] is not None:
        parts.append(f"원가율 상승은 진행 중인 공사의 **원가 추정 변경**으로 드러났고(최대 {w['year']}년, 그해 세전손익 영향 {jo(w['current'])} 원), "
                     "지금의 과제는 쌓인 공사미수금을 **현금으로 회수**하는 것입니다.")
    return " ".join(parts)


def cover(ctx, F):
    cfg = ctx["company"]
    v, R = F["v"], F["R"]
    b = R["bridge_10y"]
    kp = [("매출", f"{F['revl'] / F['rev0']:.2f}", "배", f"{F['y0']}→{F['yl']}년 · {an.jo(F['rev0'])}조 → {an.jo(F['revl'])}조 원"),
          ("영업이익률", an.pct(F["ml"]), "%", f"{F['yl']}년 · {F['y0']}년 {an.pct(F['m0'])}%")]
    w = F["est_worst"]
    if w and w["current"] is not None:
        kp.append(("원가 추정 변경", an.jo(w["current"], 2), "조 원", f"{w['year']}년 그해 세전손익 영향(회사 공시)"))
    if F["neg_start"]:
        s = window_sum(F, "operating_cashflow", F["neg_start"], F["yl"])
        cw = F["cashw"].get((F["neg_start"], F["yl"]))
        kp.append(("영업활동현금흐름", an.jo(s, 2), "조 원", f"{F['neg_start']}~{F['yl']}년 합계"
                   + (f" · 운전자본 {sjo(cw['wc_total'])}" if cw else " · 이익은 흑자")))
    kpis = "".join(f'<div class="cv-k"><p class="cv-l">{esc(a)}</p><p class="cv-v">{esc(b_)}<small>{esc(c)}</small></p>'
                   f'<p class="cv-s">{esc(e)}</p></div>' for a, b_, c, e in kp[:4])
    lf = ctx.get("latest_filing")
    meta = [("대상", f"{cfg['name']} ({cfg['stock_code']}) · 연결재무제표 · {cfg.get('business', '')}"),
            ("분석 기간", f"{F['y0']}~{F['yl']}년 사업보고서 10개 · 이후 반기·분기는 따로 표시"),
            ("기준 공시", (f"{lf['report_nm'].strip()} · {d.fmt_date(lf['rcept_dt'])} 접수" if lf else "–")),
            ("조사 기준일", f"연표·미래사업 조사 {F['RC'].get('as_of', '–')} · 숫자는 매월 1일 자동 갱신"
             + (" · 추가 검토 필요: 조사 기준일 뒤 새 공시(" + ", ".join(f"{n} {d.fmt_date(t)}" for n, t in F["review"])
                + ") — 숫자는 반영, 연표·해석 문장은 미검토" if F["review"] else "")),
            ("작성", "HSC-Class01 · OpenDART 재무분석 에이전트(GitHub Actions)"),
            ("재무제표 대시보드", cfg.get("dashboard_url", ""))]
    meta_html = "".join(f"<div><dt>{esc(k)}</dt><dd>{link(x, x) if x.startswith('http') else esc(x)}</dd></div>" for k, x in meta)
    rq = "".join(f"<li>{esc(q['q'])}</li>" for q in (F["RC"].get("questions") or []))
    return (f'<section class="cover"><div class="cv-top"><span>HSC-Class01 · KTG_Hyundai</span><span>{esc(edition(ctx))}</span></div>'
            f'<div class="cv-main"><p class="cv-eyebrow">Business analysis report · {F["y0"]}–{F["yl"]}</p>'
            f'<h1>{esc(cfg["name"])}&nbsp;<br><span>기업분석 보고서</span></h1>'
            f'<p class="cv-sub">10개년 종합 사업분석 — 건설사는 어떻게 돈을 벌고, 무엇이 현대건설의 10년을 움직였나</p></div>'
            f'<div class="cv-rq"><p>연구 질문</p><ol>{rq}</ol></div>'
            f'<p class="cv-thesis">{rich(cover_thesis(F))}</p>{cover_chart(F)}<div class="cv-kpis">{kpis}</div>'
            f'<dl class="cv-meta">{meta_html}</dl><p class="cv-note">{esc(DISCLAIMER)}</p></section>')


# ---------------------------------------------------------------------------
# 요약
# ---------------------------------------------------------------------------
def _share_last(F):
    seg_l = F["seg"].get(F["yl"])
    if seg_l and seg_l["rev"].get("total"):
        return {k: (seg_l["rev"].get(k) or 0) / seg_l["rev"]["total"] * 100 for k in SEG}
    return None


def key_messages(ctx, F):
    """요약의 핵심 메시지 네 개: ① 건설사가 돈을 버는 방식 ② 10년 실적을 움직인 것 ③ 지금 가장 중요한 재무 위험 ④ 장기 기회와 불확실성.
    숫자는 매월 다시 계산하고, 끝에 근거가 있는 절을 적습니다."""
    v, R = F["v"], F["R"]
    s = R["sens"]
    yl = F["yl"]
    out = []
    share = _share_last(F)
    rt = F["rev_types"].get(yl) or {}
    t1 = ("공사를 따내(수주) 몇 년에 걸쳐 **진행한 만큼 매출**로 잡고, **계약금액과 실제 원가의 차이**가 이익이 되며, **청구·회수 시점**이 현금을 정합니다. "
          f"현대건설의 10년 영업이익률 중앙값은 {pct(F['margin_med'])}라 원가율 1%p({s['year']}년 {eok(s['cost_1pp'])} 원)가 그해 영업이익의 "
          f"{s['cost_1pp'] / s['op'] * 100:.0f}%입니다 [계산]." if s.get("cost_1pp") and s.get("op") else "")
    if rt.get("total"):
        t1 += (f" {yl}년 매출의 {rt['contract'] / rt['total'] * 100:.0f}%가 남의 발주를 받아 짓는 **도급공사**이고, 직접 땅을 사서 파는 분양공사는 "
               f"{rt['sales'] / rt['total'] * 100:.0f}%입니다 [공시].")
    if share:
        t1 += f" 부문으로는 건축/주택 {share['building']:.0f}%, 플랜트/전력 {share['plant']:.0f}%, 토목 {share['civil']:.0f}% [공시]."
    out.append(("1", "건설사가 돈을 버는 방식", t1, "2-1 · 2-3 · 4-1"))
    b = R["bridge_10y"]
    w = F["est_worst"]
    t2 = ""
    if b:
        t2 = (f"{b['start']}→{b['end']}년 매출은 {b['rev1'] / b['rev0']:.2f}배인데 영업이익은 {sjo(b['d_op'])} 변했습니다. 회계식으로 나누면 매출 규모 효과 "
              f"{sjo(b['volume'])}보다 원가율 효과 {sjo(b['cost'])}가 컸고, 계산 방법 3가지·기간 4가지에서 모두 같은 순서입니다 [계산].")
    if w:
        ent = F["ent"].get(w["year"]) or {}
        t2 += (f" 원가율 상승은 진행 중인 공사의 원가 추정 변경으로 나타났습니다: {w['year']}년 그해 세전손익 영향 {jo(w['current'])} 원(연결) [공시]"
               + (f", 같은 해 현대엔지니어링 영업손실 {jo(ent['hec_op'])} 원 [공시]." if ent.get("hec_op") is not None else "."))
    out.append(("2", "10년 실적을 움직인 것", t2, "6-1 · 6-2 · 4-3"))
    cw = F["cashw"].get((F["neg_start"], yl)) if F["neg_start"] else None
    rv_last = F["recv_by"].get(yl) or {}
    rv_prev = F["recv_by"].get(yl - 2) or {}
    t3 = ""
    if cw:
        t3 = (f"이익을 현금으로 바꾸지 못하고 있습니다. {cw['start']}~{cw['end']}년 영업활동현금흐름은 {jo(cw['cfo'])}이고, 현금흐름표 주석으로 나누면 "
              f"순이익과 비현금 조정 {sjo(cw['ni'] + cw['adj_total'])}, 운전자본 {sjo(cw['wc_total'])}(그중 매출채권 {sjo(cw['wc']['receivables'])}), "
              f"이자·법인세 {sjo(cw['int_tax'])}입니다 [공시·계산].")
    elif F["neg_start"]:                   # 현금흐름표 주석을 읽지 못한 경우: 합계만
        t3 = (f"이익을 현금으로 바꾸지 못하고 있습니다. {F['neg_start']}~{yl}년 영업이익 합계 {jo(window_sum(F, 'operating_profit', F['neg_start'], yl))}에도 "
              f"영업활동현금흐름 합계는 {jo(window_sum(F, 'operating_cashflow', F['neg_start'], yl))}입니다 [공시·계산].")
    if rv_last.get("over_1y") is not None and rv_prev.get("over_1y") is not None:
        t3 += (f" 1년 넘게 못 받은 매출채권은 {yl - 2}년 말 {jo(rv_prev['over_1y'])} → {yl}년 말 {jo(rv_last['over_1y'])}, "
               f"손상차손누계액은 {jo(-rv_prev['allowance'])} → {jo(-rv_last['allowance'])}입니다 [공시].")
    bal = F["bal"]
    if bal and bal["values"].get("net_debt") is not None:
        t3 += f" {an.when_label(bal)} {nd_text(bal['values']['net_debt'])}"
        if F["pf"]:
            t3 += f", PF 보증 {jo(F['pf'][-1][1]['amount'], 1)}" + (f"(자본의 {F['pf_x']:.1f}배, 손실은 미확인)" if F["pf_x"] else "")
        t3 += " [공시·계산]."
    out.append(("3", "지금 가장 중요한 재무 위험", t3, "6-4 · 8-1 · 8-4"))
    lb, yrs = F["lb"], F["yrs"]
    best = max(F["years"], key=lambda y: v.a(y, "operating_margin_pct") or -99)
    t4 = ((f"일감은 충분합니다: 수주잔고 {jo(lb['total'], 1)}, 매출 {yrs:.1f}년 치 [공시·계산]. " if lb and yrs else "")
          + "원전·SMR 같은 미래사업은 대부분 설계·본계약 전 단계라 현대건설 몫의 계약금액·원가·현금흐름 일정이 없어 **NPV·IRR을 계산할 수 없습니다** [해석]. "
          + f"회사 목표 영업이익률 8%(2030년)는 지난 10년 최고치({best}년 {pct(v.a(best, 'operating_margin_pct'))})보다 높아, "
          + "계약 조건(원가 상승 분담)과 원가 추정 관리가 바뀌어야 닿는 숫자입니다 [계산·해석].")
    out.append(("4", "장기 기회와 불확실성", t4, "9-1 · 9-3 · 10-4"))
    return out


def rq_rows(ctx, F):
    """연구 질문 네 개의 한 줄 답과 근거 위치(절·표)."""
    R = F["R"]
    s = R["sens"]
    sh = bridge_shares(F)
    sums = R["alloc_sums"]
    rows = [("RQ1", "수주 → 진행률 매출 → 계약금액과 원가의 차이가 이익 → 청구·회수가 현금. 이익률이 낮아 원가 몇 %p가 이익을 좌우하고, "
             "현금은 회수 시점에 따라 이익과 따로 움직임", "2-1 흐름 · 2-3 진행기준 예시 · 4-1 부문 표")]
    if s.get("cost_1pp") and s.get("op"):
        rows.append(("RQ2", f"원가를 정확히 추정·관리하는 힘(원가율 1%p = {s['year']}년 영업이익의 {s['cost_1pp'] / s['op'] * 100:.0f}%)과 "
                     "공사대금을 제때 회수하는 힘", "5-1 항목 표 · 6-1 분해 · 6-4 현금 분해"))
    if sh.get("cost") is not None:
        rows.append(("RQ3", f"원가율(원가 추정 변경): 연간 영업이익 변화 크기의 {sh['cost']:.0f}% · 최대 {F['est_worst']['year']}년 {jo(F['est_worst']['current'])}. "
                     f"금리의 직접 영향은 1%p당 세전 {josa(seok(s.get('rate_1pp')), '으로')} 작음", "6-1 · 6-2 · 6-3 요인 표"))
    if len(sums) == 2:
        a1, a2 = sums
        rows.append(("RQ4", f"{a1['start']}~{a1['end']}년 영업 현금 {jo(a1['cfo'])}는 예금·대여금·배당·설비로, {a2['start']}~{a2['end']}년 {jo(a2['cfo'])}는 "
                     "예금 인출·차입으로 메움. 미래사업은 대부분 본계약 전이라 가치 계산(NPV·IRR) 불가", "8-1 원천과 사용 · 9-1 단계 표"))
    return rows


EVID = {"관측 자료와 일치": "good", "공시자료가 직접 뒷받침": "good", "일부 근거만 확보": "warn", "확인할 자료 부족": "info",
        "반대되는 근거 발견": "crit"}


def hypothesis_rows(ctx, F):
    """가설 H1~H5: (번호, 가설, 증거 판정, 증거, 반대 방향 자료, 분석자 평가, 절). 증거 판정은 자료가 가설을 얼마나 직접 보여 주는지이고,
    분석자 평가는 그 위에서 내린 판단입니다(부록 A의 규칙)."""
    v, R = F["v"], F["R"]
    hs = {h["id"]: h.get("short") or h["text"] for h in F["RC"].get("hypotheses", [])}
    rows = []
    b = R["bridge_10y"]
    rob = R.get("bridge_robust") or {}
    if b:
        alts = [m["whole"] for m in rob.get("methods", []) if m.get("whole")] + rob.get("windows", [])
        same = sum(1 for x in alts if x["cost"] < 0 and abs(x["cost"]) > abs(x["volume"]))
        both = [y for y in F["years"][1:] if (v.a(y, "revenue_growth_pct") or 0) > 0 and (v.a(y, "operating_profit") or 0) > (v.a(y - 1, "operating_profit") or 0)]
        verdict = "관측 자료와 일치" if b["volume"] > 0 and b["d_op"] < b["volume"] and same == len(alts) else "일부 근거만 확보"
        rows.append(("H1", hs.get("H1"), verdict,
                     f"매출 {b['rev1'] / b['rev0']:.2f}배, 영업이익 {sjo(b['d_op'])}; 규모 효과 {sjo(b['volume'])} < 원가율 효과 {sjo(b['cost'])}. "
                     f"방법·기간을 바꾼 {len(alts)}개 계산 중 {same}개에서 같은 순서 [계산]",
                     f"매출과 영업이익이 함께 늘어난 해도 있음({', '.join(map(str, both))}년)" if both else "없음",
                     "매출 증가만으로 성장을 판단할 수 없다는 주장은 이 회사 10년 자료에서 성립. 다만 분해는 회계 항등식이라 원인의 증명은 아님 [해석]", "6-1",
                     f"매출 {b['rev1'] / b['rev0']:.2f}배에도 영업이익 {sjo(b['d_op'])}; 원가율 효과 {sjo(b['cost'])}가 규모 효과 {sjo(b['volume'])}보다 큼"
                     f"({len(alts)}개 계산 중 {same}개) [계산]"))
    sh = bridge_shares(F)
    est = F["est"]
    neg_years = sum(1 for y in F["years"] if (est.get(y) or {}).get("current") is not None and est[y]["current"] < 0)
    if sh.get("cost") is not None:
        rows.append(("H2", hs.get("H2"), "공시자료가 직접 뒷받침",
                     f"원가 추정 변경의 그해 세전손익 영향이 {len(est)}년 중 {neg_years}년 마이너스, 최대 {F['est_worst']['year']}년 {jo(F['est_worst']['current'])} [공시]; "
                     f"연간 영업이익 변화 크기의 {sh['cost']:.0f}%가 원가율 효과 [계산]",
                     f"판관비율 효과 {sh['sga']:.0f}%, 매출 규모 효과 {sh['volume']:.0f}% — 원가 밖의 요인도 일부",
                     "원가 추정의 정확성이 이익을 좌우했다는 점은 확인. '관리 능력'의 좋고 나쁨은 공사별 자료가 없어 직접 재지 못함 [해석]", "6-1 · 6-2",
                     f"원가 추정 변경이 {len(est)}년 중 {neg_years}년 세전손익을 줄임(최대 {jo(F['est_worst']['current'])}) [공시]; 연간 변화 크기의 {sh['cost']:.0f}%가 원가율 효과 [계산]"))
    cw = F["cashw"].get((F["neg_start"], F["yl"])) if F["neg_start"] else None
    rl, r0 = F["recv_by"].get(F["yl"]) or {}, F["recv_by"].get(F["yl"] - 2) or {}
    if cw:
        c20 = F["cash"].get(2020) or {}
        rows.append(("H3", hs.get("H3"), "공시자료가 직접 뒷받침",
                     f"{cw['start']}~{cw['end']}년 영업활동현금흐름 {jo(cw['cfo'])} = 순이익·비현금 조정 {sjo(cw['ni'] + cw['adj_total'])} + 운전자본 {sjo(cw['wc_total'])}"
                     f"(매출채권 {sjo(cw['wc']['receivables'])}) + 이자·법인세 {sjo(cw['int_tax'])} [공시·계산]"
                     + (f"; 1년 넘은 매출채권 {jo(r0.get('over_1y'))} → {jo(rl.get('over_1y'))} [공시]" if rl.get("over_1y") is not None and r0.get("over_1y") is not None else ""),
                     (f"2020년처럼 운전자본이 회수돼({sjo(c20['wc_total'])}) 현금이 이익보다 많았던 해도 있음" if c20.get("wc_total", 0) > 0 else "없음"),
                     "현금 부족의 직접 원인은 공사미수금이 쌓인 것. 회수가 늦은 이유(분쟁·발주처 자금·계약 조건)는 공시로 나뉘지 않음 [해석]", "6-4",
                     f"{cw['start']}~{cw['end']}년 영업활동현금흐름 {jo(cw['cfo'])} 중 운전자본 {sjo(cw['wc_total'])}(매출채권 {sjo(cw['wc']['receivables'])}) [공시·계산]"
                     + (f"; 1년 넘은 매출채권 {jo(r0.get('over_1y'))} → {jo(rl.get('over_1y'))} [공시]" if rl.get("over_1y") is not None and r0.get("over_1y") is not None else "")))
    elif F["neg_start"]:                   # 현금흐름표 주석을 읽지 못한 경우: 합계 비교만
        s_op = window_sum(F, "operating_profit", F["neg_start"], F["yl"])
        s_cf = window_sum(F, "operating_cashflow", F["neg_start"], F["yl"])
        rows.append(("H3", hs.get("H3"), "일부 근거만 확보",
                     f"{F['neg_start']}~{F['yl']}년 영업이익 합계 {jo(s_op)}, 영업활동현금흐름 합계 {jo(s_cf)} [공시·계산]",
                     "–", "현금흐름표 주석을 읽지 못해 원인(운전자본 항목)을 나누지 못함 [해석]", "6-4",
                     f"영업이익 합계 {jo(s_op)}, 영업활동현금흐름 합계 {jo(s_cf)} [공시·계산]"))
    w = F["est_worst"]
    if w:
        pf_txt = (f"PF 보증 {jo(F['pf'][-1][1]['amount'], 1)}" + (f"(자본의 {F['pf_x']:.1f}배)" if F["pf_x"] else "") + "는 노출만 확인") if F["pf"] else "PF 자료 없음"
        rows.append(("H4", hs.get("H4"), "일부 근거만 확보",
                     f"대형 프로젝트 위험은 {w['year']}년 원가 추정 변경 {josa(jo(w['current']), '으로')} 현실화 [공시]. {pf_txt} [공시]",
                     "PF 보증에서 손실이 난 기록은 조사 기간에 없음",
                     "대형 손실 통제는 중요했음이 확인. PF는 위험의 크기(노출)만 알고 실제 영향은 모름 [해석]", "6-2 · 8-4",
                     f"대형 손실은 {w['year']}년 {josa(jo(w['current']), '으로')} 확인 [공시]; "
                     + (f"PF 보증 {jo(F['pf'][-1][1]['amount'], 1)}는 노출만 확인 [공시]" if F["pf"] else "PF 자료 없음")))
    pe = R["peers"]
    rows.append(("H5", hs.get("H5"), "확인할 자료 부족",
                 f"동종사 영업이익률 중앙값도 2021년 {pct(pe.get(2021, {}).get('median'))} → {F['yl']}년 {pct(pe.get(F['yl'], {}).get('median'))}로 낮아짐 [계산] — "
                 "건설업 안의 공통성만 확인", "다른 산업과 비교하지 않음",
                 "'다른 산업보다 더 중요하다'는 검증하지 않음(판정 보류) [해석]", "2-5",
                 "동종사도 같은 구조임은 확인 [계산] — 다른 산업과 비교하지 않아 판정 보류"))
    return rows


def hypothesis_table(ctx, F):
    """가설 다섯 개의 증거 판정 · 증거 · 반대 방향 자료 · 분석자 평가(10-1)."""
    hrows = [[f"<b>{esc(h)}</b>", esc(text or ""), f'<span class="r-chip {EVID.get(vd, "info")}">{esc(vd)}</span>', tagify(why), tagify(con),
              tagify(judge), esc(ref)] for h, text, vd, why, con, judge, ref, _ in hypothesis_rows(ctx, F)]
    return rtable(["가설", "내용", "증거 판정", "증거", "반대 방향 자료", "분석자 평가", "절"], hrows, "r-hyp")


def summary_page(ctx, F):
    cards = "".join(f'<article class="r-find"><p class="r-fno">{esc(no)}</p><p class="r-h">{esc(t)}</p><p>{tagify(b)}</p>'
                    f'<p class="r-fref">→ {esc(ref)}</p></article>' for no, t, b, ref in key_messages(ctx, F))
    rq = rtable(["질문", "답", "근거가 있는 곳"], [[f"<b>{esc(a)}</b>", tagify(b), esc(c)] for a, b, c in rq_rows(ctx, F)], "r-rqa")
    hrows = [[f"<b>{esc(h)}</b>", esc(text or ""), f'<span class="r-chip {EVID.get(vd, "info")}">{esc(vd)}</span>', tagify(brief), esc(ref)]
             for h, text, vd, _w, _c, _j, ref, brief in hypothesis_rows(ctx, F)]
    hyp = rtable(["가설", "내용", "증거 판정", "핵심 근거", "절"], hrows, "r-hyps")
    review = ""
    if F["review"]:
        review = box("추가 검토 필요", para("조사 기준일(" + F["RC"].get("as_of", "–") + ") 뒤에 새 공시가 접수됐습니다: "
                                       + ", ".join(f"{n} ({d.fmt_date(t)})" for n, t in F["review"])
                                       + ". 숫자·표·그래프는 자동으로 새 공시를 반영했지만, 분석자의 해석 문장과 연표는 그 전 자료로 쓴 것이라 다시 확인해야 합니다."), "warn")
    return (f'<section class="r-chap r-summary" id="summary"><header class="r-head"><span class="r-num">요약</span>'
            f'<div class="r-tt"><p>Executive summary</p><h2>핵심 메시지와 연구 질문의 답</h2></div></header>' + review
            + f'<div class="r-finds">{cards}</div>'
            + sub("", "연구 질문에 대한 답", rq, keep=True)
            + sub("", "가설 검증: 증거 판정", hyp,
                  "자료가 가설을 얼마나 직접 보여 주는지(관측 자료와 일치 · 공시자료가 직접 뒷받침 · 일부 근거만 확보 · 확인할 자료 부족 · 반대되는 근거 발견)입니다. "
                  "증거·반대 방향 자료·분석자 평가는 10-1, 판정 규칙은 부록 A.", keep=True)
            + '</section>')


# ---------------------------------------------------------------------------
# 1장 문제의식과 분석 방법
# ---------------------------------------------------------------------------
def ch1_method(ctx, F):
    RC = F["RC"]
    quote = f'<blockquote class="r-quote">{esc(RC.get("user_view", ""))}</blockquote>'
    hyps = rtable(["가설", "검증하는 내용"], [[f"<b>{esc(h['id'])}</b>", esc(h["text"])] for h in RC.get("hypotheses", [])], "r-h2")
    qs = rtable(["질문", "내용", "답하는 장"], [[f"<b>{esc(q['id'])}</b>", esc(q["q"]), esc(q["where"])] for q in RC.get("questions", [])], "r-q3")
    dr = F["dr"]
    n_docs = len({r.get("receipt") for r in (dr.get("segments") or {}).values() if r.get("receipt")})
    scope_items = [
        f"기본 기간은 **{F['y0']}~{F['yl']}년 10개 사업연도**(연결재무제표)입니다. 그 뒤의 반기·분기는 연간 결산 전이라 따로 표시합니다.",
        "숫자는 OpenDART 재무제표 API와 사업보고서 원문(주석·본문)에서 읽었습니다. 부문 손익·원가 추정 변경·현대엔지니어링 실적은 "
        f"연간 사업보고서 {n_docs}건의 주석을 직접 읽은 값이고, 부문 매출 합계가 연결 매출과 맞을 때만 씁니다 [공시].",
        "**연결과 별도**를 구분합니다. 연결 = 현대건설 + 종속회사(현대엔지니어링 등), 별도 = 현대건설 본사 단독입니다.",
        "**정정공시**는 가장 최근 정정본을 씁니다. 2013~2016년은 2017년 6월 재작성본(회계 추정 수정), 2024년은 2025년 10월 정정본"
        "(수주잔고 기재 추가, 숫자 재작성 없음)입니다 [공시].",
        "**잠정실적과 확정치**를 섞지 않습니다. 예: 2024년 영업손실은 잠정 1.22조 원(2025.1) → 감사 후 확정 1.26조 원(사업보고서) [공시·보도].",
        "**회계정책 변경**: 2026년 1분기부터 투자부동산 공정가치모형(2025년 말 자본 +0.32조 원 소급)과 토지 재평가모형(+0.36조 원)을 적용해 "
        "2026년 자본·부채비율은 그 전과 기준이 다릅니다 [공시].",
    ]
    methods = rtable(["방법", "알 수 있는 것", "한계"], [
        ["<b>회계 항등식 분해</b>", "영업이익 변화를 매출 규모·원가율·판관비율 효과로, 연결 이익을 본사·현대엔지니어링·기타로 정확히 나눔(나머지 0)", "왜 원가율이 올랐는지는 따로 찾아야 함"],
        ["<b>공시 주석 인용</b>", "회사가 직접 계산한 원가 추정 변경 효과, 부문 손익, 금리·환율 민감도", "회사가 정한 범위·방식 그대로(프로젝트별 손익은 비공개)"],
        ["<b>동종사 같은 기간 비교</b>", "같은 해 다른 건설사도 비슷했는지 → 업계 공통 요인과 회사 고유 요인 구분", "사업 구성·회계 처리가 회사마다 다름(삼성물산은 비건설 포함)"],
        ["<b>외부 지표 시계열</b>", "금리·자재값·수주 통계가 언제 어떻게 움직였는지와 실적의 시점 비교", "연간 10개 관측치로는 인과를 증명할 수 없어 상관계수를 내지 않음"],
        ["<b>민감도·시나리오</b>", "원가율·금리가 바뀌면 이익이 얼마나 변하는지, 이익률 가정별 3년 결과", "가정에 따라 결과가 달라짐 — 예측이 아님"],
    ], "r-method")
    legend_html = ('<p class="r-evleg">' + " ".join(f"{ev(k)} {esc(t)}" for k, t in (
        ("공시", "사업보고서·감사보고서에 적힌 사실"), ("계산", "공시 숫자로 이 보고서가 계산"), ("가정", "가정을 둔 계산"),
        ("보도", "언론·통계·기관 자료"), ("해석", "분석자의 판단"))) + "</p>")
    cmp_rows = [[f"<b>{esc(a)}</b>", esc(b), esc(c)] for a, b, c in RC.get("report_vs_analysis", [])]
    cmp_ = rtable(["", "법정 사업보고서", "이 사업분석 보고서"], cmp_rows, "r-vs")
    what = bullets(["상장회사가 **자본시장법 제159조**에 따라 1년 동안의 사업과 재무 상태를 투자자에게 알리는 공식 연간 보고서입니다.",
                    "사업연도가 끝나고 **90일 안에** 금융위원회와 한국거래소에 내고 전자공시시스템(DART)에 공개됩니다. 반기·분기보고서는 **45일 안에** 냅니다(제160조).",
                    "회계법인의 **감사보고서**가 붙어, 재무제표 숫자를 외부에서 한 번 확인받은 자료입니다. 장별 구성과 이 보고서가 읽는 곳은 부록 B."])
    what_box = box("사업보고서란?", what + f'<p class="r-src">출처: {rv.ref("law159")}</p>', "plain")
    body = (sub("1-1", "문제의식", quote + para("이 문장을 출발점 가설로 삼되, 결론은 자료가 말하는 대로 씁니다. 가설을 다섯 개로 나누면 다음과 같습니다.") + hyps, keep=True)
            + sub("1-2", "연구 질문", qs)
            + sub("1-3", "분석 범위와 자료 관리", bullets(scope_items, "small"))
            + sub("1-4", "분석 방법", methods + legend_html, keep=True)
            + sub("1-5", "법정 사업보고서와 이 보고서의 차이", what_box + cmp_, keep=True))
    return chapter("01", "Question & method", "문제의식과 분석 방법",
                   "숫자가 '얼마인가'보다 '왜 그렇게 됐는가'를 묻는 보고서입니다. 그래서 회계식으로 정확히 나눌 수 있는 것, 회사가 공시한 것, "
                   "분석자가 해석한 것을 구분해 적습니다.", body, "ch1")


# ---------------------------------------------------------------------------
# 2장 건설업이 돈을 버는 구조
# ---------------------------------------------------------------------------
TIMING_ROWS = [("수주·계약", "수주잔고가 늘어남(재무제표 밖)", "선수금이 들어오기도 함", "Ⅱ 수주상황"),
               ("공사 진행", "진행률만큼 매출과 원가를 인식", "자재·인건비·외주비가 먼저 나감", "Ⅲ 손익계산서"),
               ("기성 청구", "청구액 < 진행분 → 계약자산(미청구공사) · 청구액 > 진행분 → 계약부채(초과청구공사)", "청구 뒤 회수까지 몇 달", "Ⅲ 재무상태표·건설계약 주석"),
               ("원가 추정 변경", "남은 공사의 손실이 예상되면 그해 한꺼번에 비용(공사손실충당부채)", "현금은 공사 기간에 걸쳐 나감", "Ⅲ 건설계약 주석"),
               ("준공·정산", "하자보수충당부채, 공사 정산", "유보금 회수, 정산금 수령", "Ⅲ 충당부채 주석")]


def ch2_industry(ctx, F):
    RC, R = F["RC"], F["R"]
    steps = rv._flow_steps(ctx, F["v"])
    flow = rv.flow_html(steps)
    timing = rtable(["시점", "회계(손익·재무상태)", "현금", "사업보고서"],
                    [[f"<b>{esc(a)}</b>", esc(b), esc(c), esc(e)] for a, b, c, e in TIMING_ROWS], "r-timing")
    poc_rows = [["올해까지 쓴 원가", num("450억 원"), num("450억 원")],
                ["총예정원가(끝날 때까지 들 원가)", num("900억 원"), num("1,050억 원")],
                ["진행률 = 쓴 원가 ÷ 총예정원가", num("50.0%"), num("42.9%")],
                ["올해 매출 = 계약금액 1,000억 원 × 진행률", num("500.0억 원"), num("428.6억 원")],
                ["① 진행분 손익 = 매출 − 쓴 원가", num("50.0억 원"), num("−21.4억 원", -1)],
                ["② 남은 공사의 예상 손실을 미리 비용으로(공사손실충당부채)", num("–"), num("−28.6억 원", -1)],
                ["<b>올해 손익 = ① + ②</b>", num("50.0억 원"), num("−50.0억 원", -1)]]
    poc = (rtable(["계약금액 1,000억 원짜리 공사(공사 첫해)", "처음 예상", "원가 추정이 늘면"], poc_rows, "r-poc")
           + bullets(["원가 추정이 늘면 진행률이 낮아져 그해 매출이 줄고(500억 → 428.6억 원), 공사 전체가 손해로 예상되면 아직 짓지 않은 부분의 손실(28.6억 원)까지 "
                      "**그해에 한꺼번에** 공사손실충당부채로 잡습니다. 그래서 그해 손익(−50억 원)은 공사 전체의 예상 손실(계약금액 1,000억 − 총예정원가 1,050억)과 같아집니다.",
                      "교과서식 예시입니다. 실제로는 앞선 해에 이미 잡은 이익을 되돌리는 금액이 더해지고, 발주처와 협상 중인 공사비 증액(변동대가)을 얼마나 반영할지, "
                      "손실충당부채를 어떤 원가로 잴지에 회사의 판단이 들어갑니다 [해석].",
                      "이 효과를 회사가 직접 계산해 공시한 숫자가 6-2의 '원가 추정 변경 효과'입니다."], "small"))
    seg_rows = R["segments"]
    window_rows = [r for r in seg_rows if r["year"] in F["years"]]

    def seg_med(key):
        return median(r["margin"].get(key) for r in window_rows)

    cards = []
    for t in RC.get("business_types", []):
        m = seg_med(t["seg"]) if t.get("seg") in SEG else None
        hy = (f'현대건설 {SEG_KO[t["seg"]]} 부문 매출총이익률 10년 중앙값 <b>{pct(m)}</b> {ev("계산")}' if m is not None else "")
        rows = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(t.get(f, ''))}</dd></div>" for k, f in (
            ("매출", "revenue"), ("원가", "cost"), ("이익을 정하는 것", "driver"), ("주요 위험", "risk"), ("현금", "cash"), ("민감한 외부 변수", "sens")))
        cards.append(f'<article class="bt"><p class="r-h">{esc(t["type"])}<span> {esc(t.get("ex", ""))}</span></p><dl>{rows}</dl>'
                     + (f'<p class="bt-hy">{hy}</p>' if hy else "") + "</article>")
    types = f'<div class="bts">{"".join(cards)}</div>'
    # 동종사 비교: 10년 표(현대건설 · 동종사 중앙값 줄을 강조)
    pe = R["peers"]
    years = F["years"]
    own = [pe[y]["own"] for y in years]
    med = [pe[y]["median"] for y in years]
    names = sorted({n for y in years for n in pe[y]["peers"]})
    prow = []
    for n in names:
        prow.append([esc(n)] + [num(pct(pe[y]["peers"].get(n), 1) if pe[y]["peers"].get(n) is not None else "–", pe[y]["peers"].get(n)) for y in years])
    prow.append(["<b>동종사 중앙값</b>(삼성물산 제외)"] + [num(pct(x), x) for x in med])
    prow.append(["<b>현대건설</b>"] + [num(pct(x), x) for x in own])
    ptable = rtable(["영업이익률(연결)"] + [str(y) for y in years], prow, "r-peers10")
    lows = peer_gap_years(F)
    run = 0
    for y in reversed(years):
        if y in lows:
            run += 1
        else:
            break
    features = [
        f"**낮은 이익률, 큰 매출**: 매출 100원에서 남는 영업이익이 몇 원 수준(현대건설 10년 중앙값 {pct(F['margin_med'])})이라 원가 몇 %p가 이익 전체를 좌우합니다 [계산].",
        "**고정가격 장기 계약**: 계약할 때 정한 금액으로 몇 년씩 짓습니다. 그 사이 자재값·인건비가 오르면 대부분 건설사가 떠안고, "
        "계약 변경 협상이 늦어지면 손실이 됩니다(2024년 원가 추정 변경 사유 [공시]).",
        "**운전자본 집약**: 공사를 먼저 하고 나중에 받기 때문에 매출이 빨리 늘수록 받을 돈(매출채권·계약자산)이 쌓여 현금이 먼저 나갑니다.",
        "**재무제표 밖의 의무**: 시행사·조합의 PF 대출 보증, 책임준공 약정은 부채에 잡히지 않지만 분양이 막히면 건설사의 빚이 됩니다 [공시: Ⅺ장].",
        "**정책·금리 민감**: 주택은 금리·대출 규제, 공공은 SOC 예산, 해외는 유가와 지정학에 따라 일감과 대금 회수가 달라집니다.",
        "**업계 공통과 회사 고유의 구분**: 2022~2024년에는 동종사 대부분의 이익률이 함께 떨어졌지만(공통), 큰 손실은 회사마다 다른 해·다른 현장에서 "
        "났습니다(대우 2016·2025, GS 2023, 현대 2024 [보도·계산]).",
        (f"**현대건설의 위치**: 영업이익률이 최근 {run}년 연속 동종사 중앙값보다 낮았습니다(아래 표) [계산]." if run >= 2 else ""),
    ]
    body = (sub("2-1", "돈이 도는 여섯 단계", flow,
                "카드의 숫자는 가장 최근 공시 기준이며 매월 다시 계산합니다. 카드 맨 아래 작은 글씨는 그 숫자가 사업보고서의 어디에 있는지입니다.")
            + sub("2-2", "회계와 현금의 시간차", timing, "건설사의 이익과 현금이 같은 해에 같은 방향으로 움직이지 않는 이유입니다.", keep=True)
            + sub("2-3", "공사비가 매출이 되는 방법: 진행기준", poc,
                  "건설사는 공사가 끝날 때가 아니라 **진행한 만큼** 매출을 잡습니다(K-IFRS 1115호). 진행률은 보통 '지금까지 쓴 원가 ÷ 총예정원가'입니다.", keep=True)
            + sub("2-4", "사업 유형마다 돈 버는 방식이 다릅니다", types,
                  "일반적인 구조를 정리하고(분석자 정리), 현대건설에 해당하는 부문의 실제 이익률을 붙였습니다. 같은 회사 안에서도 사업 유형에 따라 "
                  "이익률이 몇 배씩 다릅니다.")
            + sub("2-5", "한국 대형 건설사의 구조적 특징", bullets(features) + ptable,
                  "삼성물산은 건설 외 상사·패션·리조트·바이오 등을 함께 연결해 중앙값에서 뺐고, DL이앤씨(2021년 분할)·IPARK현대산업개발(2018년 분할)은 "
                  "그 전 연도가 없습니다. 사업 구성이 달라 단순 비교에는 한계가 있습니다."))
    return chapter("02", "How builders make money", "건설업은 이렇게 돈을 법니다",
                   "건설사는 물건을 먼저 만들어 파는 회사가 아닙니다. **공사를 먼저 따내고(수주), 몇 년에 걸쳐 지으면서 진행한 만큼 매출로 잡고, "
                   "공사비를 청구해 현금을 회수하는 수주산업**입니다. 이익은 계약금액과 실제 원가의 차이에서, 현금은 청구와 회수의 시점에서 결정됩니다.",
                   body, "ch2")


# ---------------------------------------------------------------------------
# 3장 그래서 사업보고서를 읽는다
# ---------------------------------------------------------------------------
def ch3_report(ctx, F):
    RC, R, v = F["RC"], F["R"], F["v"]
    yl = F["yl"]
    bal = F["bal"]
    lb, yrs = F["lb"], F["yrs"]
    est = F["est"].get(yl) or {}
    rec = v.a(yl, "receivables_total")
    reg = (F["dr"].get("regions") or {}).get(str(yl), {}).get("revenue") or {}
    ovs = (1 - reg["domestic"] / (reg["total"] - (reg.get("adjust") or 0))) * 100 if reg.get("total") and reg.get("domestic") else None
    sens = R["sens"]
    big = max(F["projects"], key=lambda r: r["contract"], default=None)
    rows = [
        ("수주부터 완공까지 길다", "몇 년 뒤 매출이 될 일감이 얼마나 있는지가 미래를 정함", "Ⅱ 매출 및 수주상황",
         f"수주잔고 {jo(lb['total'], 1)} 원 · 매출 {yrs:.1f}년 치" if lb and yrs else "–"),
        ("대규모 자금이 묶인다", "공사를 먼저 하고 나중에 받아 운전자금이 필요", "Ⅲ 재무상태표 · 건설계약 주석",
         f"받을 돈 {jo(rec, 1)} 원(매출의 {rec / v.a(yl, 'revenue') * 100:.0f}%)" if rec and v.a(yl, "revenue") else "–"),
        ("공정과 대금 회수에 시차", "진행률 매출과 청구액의 차이가 계약자산·계약부채로 쌓임", "Ⅲ 건설계약 주석",
         f"계약자산 {jo(v.a(yl, 'contract_assets'), 1)} 원 · 미리 받은 돈 {jo(v.a(yl, 'advances_total'), 1)} 원"),
        ("이익과 현금이 다르다", "흑자여도 현금은 마이너스일 수 있음", "Ⅲ 현금흐름표",
         f"{yl}년 영업이익 {jo(v.a(yl, 'operating_profit'))} · 영업활동현금흐름 {jo(v.a(yl, 'operating_cashflow'))}"),
        ("원가·공기·계약 변경이 이익을 바꾼다", "원가 추정이 바뀌면 그해 이익이 한꺼번에 변함", "Ⅲ 건설계약 주석(추정 변경)",
         f"{yl}년 원가 추정 변경 효과 {jo(est.get('current'))}" + (f" · 공사손실충당부채 {jo(est.get('loss_prov'))}" if est.get("loss_prov") else "")),
        ("PF·보증 같은 우발채무", "재무제표 밖의 의무가 빚이 될 수 있음", "Ⅺ 우발부채 등(채무보증)",
         (f"PF 보증 {jo(F['pf'][-1][1]['amount'], 1)} 원" + (f" · 자본의 {F['pf_x']:.1f}배" if F["pf_x"] else "")) if F["pf"] else "–"),
        ("국내외 경제·정책에 노출", "환율·금리·지정학이 매출과 이익을 흔듦", "Ⅱ 위험관리 · Ⅲ 영업부문(지역별) 주석",
         (f"해외 매출 {ovs:.0f}%" if ovs is not None else "") + (f" · 환율 10% 상승 시 세전 {seok(sens.get('fx_10pct'))} 원" if sens.get("fx_10pct") else "")),
        ("현장 하나가 회사 전체를 흔든다", "대형 공사 한 건의 손실이 연간 이익을 넘을 수 있음", "Ⅲ 건설계약 주석(매출 5% 이상 공사)",
         f"가장 큰 진행 공사: {big['name']} {jo(big['contract'], 1)} 원" if big else "–"),
    ]
    feat = rtable(["건설업의 특성", "왜 중요한가", "사업보고서의 어디", f"현대건설 지금"],
                  [[f"<b>{esc(a)}</b>", esc(b), esc(c), f"<b>{esc(e)}</b>"] for a, b, c, e in rows], "r-feat")
    stake = rtable(["누가", "무엇을 위해 읽나", "주로 보는 곳"],
                   [[f"<b>{esc(s['who'])}</b>", esc(s["use"]), esc(s["where"])] for s in RC.get("stakeholders", [])], "r-stake")
    body = (sub("3-1", "건설업의 특성 여덟 가지와 사업보고서에서 확인하는 곳", feat,
                "2장의 특성 때문에 재무제표(Ⅲ장) 숫자 하나만 보면 오해하기 쉽습니다. 오른쪽 칸은 매월 자동으로 읽은 현대건설의 지금 숫자입니다.", keep=True)
            + sub("3-2", "이해관계자에게 주는 가치", stake, keep=True))
    return chapter("03", "Why the annual report", "그래서 사업보고서를 읽습니다",
                   "재무제표는 2장에서 본 순환의 **결과**만 보여 줍니다. 결과를 만든 **원인**, 즉 얼마나 따냈고 공사가 어디까지 왔고 원가 추정이 어떻게 바뀌었고 "
                   "어떤 보증을 섰는지는 Ⅱ장(사업의 내용)·Ⅲ장 주석·Ⅺ장(우발부채)에 흩어져 있습니다. 그래서 건설사는 사업보고서 전체를 함께 읽어야 합니다.",
                   body, "ch3")


# ---------------------------------------------------------------------------
# 4장 현대건설은 어디서 돈을 버나
# ---------------------------------------------------------------------------
def tick_pct(t):
    return an._m(f"{t:g}%")


def seg_legend(keys=SEG):
    return d.legend([(SEG_KO[k], SEG_COLOR[k], "box") for k in keys])


def seg_sum(F, key, k, years):
    vals = [(F["seg"].get(y) or {}).get(key, {}).get(k) for y in years]
    vals = [x for x in vals if x is not None]
    return sum(vals) if vals else None


def entity_table(F, a, b):
    """a년 → b년 연결 영업이익 변화를 회사별로, 그리고 연결 영업이익에서 지배주주 순이익까지(조 원)."""
    ra, rb = F["ent"].get(a) or {}, F["ent"].get(b) or {}
    if not ra or not rb:
        return ""
    def d(k):
        return rb[k] - ra[k] if ra.get(k) is not None and rb.get(k) is not None else None
    items = [("현대건설 본사(별도) 영업이익", "parent_op"), ("현대엔지니어링 영업이익(내부거래 제거 전)", "hec_op"),
             ("그 밖의 종속회사·연결조정(차이로 계산)", "rest_op"), ("<b>연결 영업이익</b>", "cons_op"),
             ("연결 당기순이익(영업외·법인세 반영 후)", "cons_ni"), ("그중 비지배지분 몫", "nci_ni"), ("<b>지배주주 순이익</b>", "owners_ni")]
    rows = [[name if name.startswith("<b>") else esc(name), num(sjo(ra.get(k)), ra.get(k)), num(sjo(rb.get(k)), rb.get(k)), num(sjo(d(k)), d(k))]
            for name, k in items]
    return rtable(["연결", f"{a}년", f"{b}년", "변화"], rows, "r-ent")


def ch4_business(ctx, F):
    R, v, years, seg = F["R"], F["v"], F["years"], F["seg"]
    yl = F["yl"]
    have = [y for y in years if y in seg]
    if not have:
        return chapter("04", "Where the money comes from", "현대건설은 어디서 돈을 버나", "사업보고서 주석(영업부문)을 읽지 못해 이 장을 비웠습니다.", "", "ch4")

    def rtips(i):
        y = have[i]
        r = seg[y]
        rows = [[SEG_KO[k], won(r["rev"].get(k)), f"var({SEG_COLOR[k]})"] for k in SEG]
        rows += [["연결조정(내부거래)", won(r["rev"].get("adjust")), None], ["연결 매출", won(r["rev"].get("total")), None]]
        return f"{y}년 부문별 매출", rows, None
    groups = [[{"values": [max((seg[y]["rev"].get(k) or 0), 0) / T for y in have], "color": SEG_COLOR[k]} for k in SEG]]
    fig_rev = fig("fig-seg-rev", "부문별 매출", "연결 · 막대 위 숫자 = 연결 매출(부문 간 거래 제외 후)",
                       d.stack_chart(xlabels(have), groups, ticks_fmt=d.tick_jo, tips=rtips, height=165,
                                     labels={(0, i): an.jo(seg[y]["rev"]["total"]) for i, y in enumerate(have)}),
                       legend_html=seg_legend())

    def mtips(i):
        y = have[i]
        r = seg[y]
        rows = [[SEG_KO[k], pct(r["margin"].get(k)), f"var({SEG_COLOR[k]})"] for k in ("building", "civil", "plant")]
        rows.append(["전체", pct(r["margin"].get("total")), None])
        return f"{y}년 매출총이익률", rows, "매출총이익 ÷ 매출"
    series = [{"name": SEG_KO[k], "values": [seg[y]["margin"].get(k) for y in have], "color": SEG_COLOR[k]} for k in ("building", "civil", "plant")]
    fig_m = fig("fig-seg-margin", "부문별 매출총이익률", "매출총이익 ÷ 매출 · 연결",
                     d.multi_line_chart(xlabels(have), series, ticks_fmt=tick_pct, tips=mtips, height=165, end_fmt=lambda x: pct(x)),
                     legend_html=seg_legend(("building", "civil", "plant")))
    early = [y for y in have if y <= 2021]
    late = [y for y in have if y >= 2022]
    tot_gp = seg_sum(F, "gp", "total", have) or 0
    seg_tot = sum(seg_sum(F, "gp", k, have) or 0 for k in SEG)          # 이익 비중의 분모: 네 부문 합(연결조정 전)
    adj_gp = seg_sum(F, "gp", "adjust", have)
    neg_gp = [(k, y, seg[y]["gp"].get(k)) for k in SEG for y in have if (seg[y]["gp"].get(k) or 0) < 0]
    est_by = {}
    for y in years:
        e = F["est"].get(y)
        if e:
            for k, x in e["by_seg"].items():
                if x is not None:
                    est_by[k] = est_by.get(k, 0) + x
    rows = []
    for k in SEG:
        gp = seg_sum(F, "gp", k, have)
        me = median(seg[y]["margin"].get(k) for y in early)
        ml_ = median(seg[y]["margin"].get(k) for y in late)
        rows.append([f'<b>{esc(SEG_KO[k])}</b>', num(jo(seg_sum(F, "rev", k, have), 1)), num(jo(gp, 2), gp),
                     num(pct(gp / seg_tot * 100, 0) if gp is not None and seg_tot else "–"), num(pct(me), me), num(pct(ml_), ml_),
                     num(jo(est_by.get(k), 2) if k in est_by else "–", est_by.get(k))])
    rows.append(["연결조정(부문 간 거래 제거)", num(jo(seg_sum(F, "rev", "adjust", have), 1), seg_sum(F, "rev", "adjust", have)),
                 num(jo(adj_gp, 2), adj_gp), num("–"), num("–"), num("–"), num("–")])
    rows.append(["<b>연결 합계</b>", num(jo(seg_sum(F, "rev", "total", have), 1)), num(jo(tot_gp, 2), tot_gp), num("–"), num("–"), num("–"),
                 num(jo(sum(est_by.values()), 2) if est_by else "–", sum(est_by.values()) if est_by else None)])
    tbl = rtable(["부문", f"매출 합계({have[0]}~{have[-1]})", "매출총이익 합계", "이익 비중(부문 합 대비)", f"이익률 중앙값 {early[0]}~{early[-1]}" if early else "이전",
                  f"이익률 중앙값 {late[0]}~{late[-1]}" if late else "이후", "원가 추정 변경 합계"], rows, "r-segsum")
    best = max(SEG, key=lambda k: seg_sum(F, "gp", k, have) or 0)
    worst_est = min(est_by, key=lambda k: est_by[k]) if est_by else None
    seg_points = [
        (f"10년 네 부문 매출총이익 합계({jo(seg_tot)} 원, 연결조정 전)의 **{(seg_sum(F, 'gp', best, have) or 0) / seg_tot * 100:.0f}%를 {josa(SEG_KO[best], '이')}** "
         f"벌었습니다. 연결조정 {jo(adj_gp)} 원을 더하면 연결 매출총이익 {jo(tot_gp)} 원입니다 [계산]." if seg_tot else ""),
        ("합계 속에는 매출총손실이 난 해가 들어 있습니다(" + ", ".join(f"{SEG_KO[k]} {y}년 {jo(x)}" for k, y, x in neg_gp)
         + "). 손실 해가 있는 부문은 그만큼 합계와 비중이 작아진 값이라, 해마다의 비중보다 10년 합계로만 비교했습니다 [계산]." if neg_gp else ""),
        (f"원가 추정 변경으로 줄어든 이익은 **{SEG_KO.get(worst_est, worst_est)}**에서 가장 컸습니다({jo(est_by[worst_est])} 원) [공시·계산]." if worst_est else ""),
        "건축/주택은 매출의 절반을 넘는 이익 창출원이지만, 2022년 이후 공사비 급등으로 이익률이 크게 낮아졌습니다. 플랜트/전력은 매출 규모에 비해 이익이 작고 "
        "손실이 한 해에 몰리는 부문입니다 [계산·해석].",
        "부문의 현금 창출력은 공시되지 않습니다(부문별 현금흐름·운전자본 비공개). 아래 4-4의 ‘현금’ 칸은 사업 구조에서 추론한 것입니다 [해석].",
    ]
    # 지역
    regs = F["dr"].get("regions") or {}
    ry = [y for y in years if str(y) in regs]
    fig_r = ""
    if ry:
        def gtips(i):
            y = ry[i]
            r = regs[str(y)]["revenue"]
            base = (r.get("total") or 0) - (r.get("adjust") or 0)
            rows = [[REGION_KO[k], f"{won(r.get(k))} · {(r.get(k) or 0) / base * 100:.0f}%" if base else won(r.get(k)), f"var({REGION_COLOR[k]})"]
                    for k in ("domestic", "asia", "mideast", "other")]
            return f"{y}년 지역별 매출", rows, None
        groups = [[{"values": [max(regs[str(y)]["revenue"].get(k) or 0, 0) / T for y in ry], "color": REGION_COLOR[k]}
                   for k in ("domestic", "asia", "mideast", "other")]]
        r_last = regs[str(ry[-1])]["revenue"]
        base = (r_last.get("total") or 0) - (r_last.get("adjust") or 0)
        r_first = regs[str(ry[0])]["revenue"]
        base0 = (r_first.get("total") or 0) - (r_first.get("adjust") or 0)
        note = (f"해외 매출 비중은 {ry[0]}년 {(1 - r_first['domestic'] / base0) * 100:.0f}% → {ry[-1]}년 {(1 - r_last['domestic'] / base) * 100:.0f}%입니다. "
                "2023~2024년 '기타'(미주 등)가 커진 것은 현대엔지니어링의 미국 그룹사 공장 공사 때문입니다 [공시]." if base and base0 else None)
        fig_r = fig("fig-region", "지역별 매출", "연결 · 영업부문 주석의 지역별 분석(내부거래 제거 전)",
                         d.stack_chart(xlabels(ry), groups, ticks_fmt=d.tick_jo, tips=gtips, height=150),
                         legend_html=d.legend([(REGION_KO[k], REGION_COLOR[k], "box") for k in ("domestic", "asia", "mideast", "other")]), note=note)
    # 본사 · 현대엔지니어링 · 기타
    ent = [F["ent"][y] for y in years if y in F["ent"]]
    ent = [r for r in ent if r.get("parent_op") is not None and r.get("hec_op") is not None]
    fig_e, ent_points = "", []
    if ent:
        ey = [r["year"] for r in ent]
        comps = [{"name": "현대건설 본사", "values": [r["parent_op"] / T for r in ent], "color": "--s1"},
                 {"name": "현대엔지니어링", "values": [r["hec_op"] / T for r in ent], "color": "--s2"},
                 {"name": "그 밖의 종속회사·조정", "values": [(r["rest_op"] or 0) / T for r in ent], "color": "--s3"}]

        def etips(i):
            r = ent[i]
            return (f"{r['year']}년 영업이익 나누기", [["현대건설 본사(별도)", won(r["parent_op"]), "var(--s1)"],
                                                    ["현대엔지니어링(내부거래 제거 전)", won(r["hec_op"]), "var(--s2)"],
                                                    ["그 밖의 종속회사·연결조정", won(r["rest_op"]), "var(--s3)"],
                                                    ["연결 영업이익", won(r["cons_op"]), None]], None)
        fig_e = fig("fig-entity", "연결 영업이익을 회사별로 나누면", "가로 막대 표시 = 연결 영업이익 · 막대 = 회사별 기여(조 원)",
                         rc.diverging_stack(xlabels(ey), comps, tips=etips, net=[r["cons_op"] / T for r in ent], height=170,
                                            net_labels={i: an.jo(r["cons_op"], 2) for i, r in enumerate(ent)}),
                         legend_html=d.legend([(c["name"], c["color"], "box") for c in comps]))
        w = min(ent, key=lambda r: r["cons_op"])
        last = ent[-1]
        ent_points = [
            f"현대엔지니어링은 현대건설의 유효지분이 40.47%인데도 '실질 지배'로 연결 대상입니다 [공시]. 그래서 매출·이익은 100% 합쳐지고, "
            "순이익 중 다른 주주 몫은 '비지배지분'으로 따로 나뉩니다.",
            (f"{w['year']}년 연결 영업손실 {jo(w['cons_op'])} 중 {josa(jo(w['hec_op']), '이')} 현대엔지니어링, {josa(jo(w['parent_op']), '이')} 본사였습니다 [공시]. "
             + (f"순손실 {jo(w['cons_ni'])} 가운데 {josa(jo(w['nci_ni']), '을')} 비지배지분이 나눠 가져 지배주주 몫은 {jo(w['owners_ni'])}였습니다 [계산]."
                if w.get("nci_ni") is not None else "")),
            (f"{last['year']}년 현대엔지니어링 영업활동현금흐름은 {jo(last['hec_cfo'])}(내부거래 제거 전)이고 연결은 {jo(last['cons_cfo'])}입니다 [공시]. "
             "단순 차이를 본사·기타의 몫으로 볼 수는 있지만, 회사 사이 거래가 지워지기 전 숫자라 정확한 회사별 현금은 아닙니다 [계산]."
             if last.get("hec_cfo") is not None else ""),
        ]
        ent_tbl = entity_table(F, w["year"], last["year"]) if w["year"] != last["year"] else ""
        fig_e += ent_tbl
    # 이익·현금·위험 매트릭스
    mat = []
    cash_txt = {"building": "기성·분양 대금으로 회수 — 정비사업은 조합의 분양 일정에 따라 늦어질 수 있음",
                "civil": "공공 발주처는 지급 능력 위험이 낮은 편(일반론) — 설계변경·물가변동 정산은 늦어질 수 있음",
                "plant": "선수금이 있지만 마일스톤 지연 시 계약자산이 쌓임", "other": "임대·개발 등 — 규모 작음"}
    risk_txt = {"building": "공사비 상승을 계약금액에 반영하기 어려움, PF·책임준공", "civil": "낮은 낙찰률, 공기 지연",
                "plant": "고정가격 EPC의 원가·공기 초과(2024년)", "other": "개발사업 분양"}
    for k in SEG:
        gp = seg_sum(F, "gp", k, have)
        mat.append([f"<b>{esc(SEG_KO[k])}</b>", esc(f"{gp / seg_tot * 100:.0f}%" if gp is not None and seg_tot else "–"),
                    esc(f"{pct(median(seg[y]['margin'].get(k) for y in early))} → {pct(median(seg[y]['margin'].get(k) for y in late))}"),
                    esc(cash_txt[k]), esc(jo(est_by.get(k), 2) if k in est_by else "–"), esc(risk_txt[k])])
    matrix = rtable(["부문", "이익을 버나(10년 매출총이익 비중, 부문 합 대비) [계산]", "이익률 변화 [계산]", "현금은 [해석]", "원가 추정 변경 합계(위험이 실제로 난 크기) [공시]",
                     "주요 위험 [해석]"], mat, "r-matrix")
    body = f'<div class="r-2">{fig_rev}{fig_m}</div>' + tbl + bullets(seg_points)
    body = sub("4-1", "부문별 매출과 이익", body, "영업부문 주석(연결)의 부문별 매출액·매출총이익입니다. 부문 합 + 연결조정 = 연결 매출이 맞는 해만 씁니다. "
               "부문별 영업이익은 공시되지 않아 매출총이익(매출 − 매출원가)까지만 나눕니다. 토목은 2021년까지 ‘인프라/환경’으로 공시됐고, 2022년 보고서의 "
               "2021년(전기) 숫자가 2021년 보고서와 같아 이름만 바뀐 것으로 확인했습니다 [공시].")
    if fig_r:
        body += sub("4-2", "국내와 해외", fig_r, keep=True)
    if fig_e:
        body += sub("4-3", "본사와 현대엔지니어링", fig_e + bullets(ent_points),
                    "연결 영업이익 = 현대건설 본사(별도 재무제표) + 현대엔지니어링(비지배지분 주석의 요약 재무정보, 회사 사이 거래를 지우기 전) + 나머지(다른 종속회사와 "
                    "연결조정, 차이로 계산). 그래서 ‘나머지’에는 다른 자회사의 이익과 내부거래 제거가 섞여 있습니다.")
    body += sub("4-4", "어떤 사업이 이익·현금·위험을 만드나", matrix, keep=True)
    body += sub("4-5", "일감: 수주잔고", rv.backlog_fig(ctx) + f'<div class="r-2">{rv.work_years_fig(ctx)}{rv.orders_fig(ctx)}</div>')
    share = {k: (seg[yl]["rev"].get(k) or 0) / seg[yl]["rev"]["total"] * 100 for k in SEG} if yl in seg else None
    lead = (f"{yl}년 매출의 {share['building']:.0f}%는 건축/주택, {share['plant']:.0f}%는 플랜트/전력, {share['civil']:.0f}%는 토목입니다 [공시]. "
            "어디서 매출을 올리는지보다 **어디서 이익이 남고, 어디서 손실 위험이 터지는지**를 나눠 봅니다." if share else "")
    return chapter("04", "Where the money comes from", "현대건설은 어디서 돈을 버나", lead, body, "ch4")


# ---------------------------------------------------------------------------
# 5장 성장에 중요한 재무항목
# ---------------------------------------------------------------------------
# 열세 개 항목: (이름, 목적, 건설업 일반의 이유[분석자 정리], 이 보고서에서의 쓰임)
# 쓰임 — 핵심: 이 보고서의 결론(RQ2·RQ3)을 직접 바꾸는 항목 · 보조: 핵심 항목의 원인·결과를 설명 · 참고: 건설업에서는 단독으로 쓰면 오해하기 쉬움
ITEMS = [
    ("영업이익·영업이익률(원가율)", "수익성·원가", "이익률이 낮아 원가 몇 %p가 이익 전체를 좌우함", "핵심"),
    ("영업활동현금흐름", "현금 전환", "진행률로 잡는 이익과 대금 회수 시점이 달라 흑자여도 현금이 빠질 수 있음", "핵심"),
    ("매출채권·계약자산(받을 돈)", "현금 전환", "공사를 먼저 하고 나중에 받는 구조에서 회수 지연을 가장 먼저 보여 줌", "핵심"),
    ("공사손실충당부채·우발채무(PF 보증)", "위험·생존", "남은 공사의 손실과 재무제표 밖 의무가 한꺼번에 빚이 될 수 있음", "핵심"),
    ("신규 수주·수주잔고", "성장·일감", "몇 년 뒤 매출의 양을 정하지만 이익은 보장하지 않음", "보조"),
    ("순차입금·이자 부담", "위험·생존", "영업 현금이 모자랄 때 무엇으로 메우는지", "보조"),
    ("ROIC·ROE(자본 효율)", "자본 효율", "투자한 돈이 자본비용보다 많이 버는지", "보조"),
    ("잉여현금흐름(FCF)", "현금 전환", "설비 투자 뒤 실제로 남는 현금", "보조"),
    ("매출총이익·매출총이익률", "수익성·원가", "원가 문제가 어느 부문에서 났는지", "보조"),
    ("매출액·매출 성장률", "성장·일감", "진행률 매출이라 단독으로는 이익·현금을 말해 주지 않음", "참고"),
    ("당기순이익", "수익성·원가", "환율 평가·비지배지분 몫 등 영업 밖 요인이 섞임", "참고"),
    ("현금 및 현금성자산", "위험·생존", "잔액은 결과일 뿐, 현금을 만드는 속도가 더 중요", "참고"),
    ("부채비율·유동비율", "위험·생존", "선수금·계약부채 같은 공사 관련 부채가 섞여 단독 해석이 어려움", "참고"),
]
ROLE_CHIP = {"핵심": "crit", "보조": "warn", "참고": "info"}


def item_evidence(ctx, F):
    v, R, years = F["v"], F["R"], F["years"]
    y0, yl = F["y0"], F["yl"]
    ev_ = {}
    b = R["bridge_10y"]
    ev_["영업이익·영업이익률(원가율)"] = f"{pct(F['m0'])} → {pct(F['ml'])}; 10년 영업이익 변화 {sjo(b['d_op']) if b else '–'} 중 원가율 효과 {sjo(b['cost']) if b else '–'}"
    s_cf = window_sum(F, "operating_cashflow", F["neg_start"], yl) if F["neg_start"] else None
    ev_["영업활동현금흐름"] = (f"{F['neg_start']}~{yl}년 {len(range(F['neg_start'], yl + 1))}년 연속 마이너스, 합계 {jo(s_cf)}" if F["neg_start"] else
                          f"{yl}년 {jo(v.a(yl, 'operating_cashflow'))}")
    r0, r1 = v.a(2021, "trade_receivables"), v.a(yl, "trade_receivables")
    rev0, rev1 = v.a(2021, "revenue"), v.a(yl, "revenue")
    ra, rl = F["recv_by"].get(yl - 2) or {}, F["recv_by"].get(yl) or {}
    ev_["매출채권·계약자산(받을 돈)"] = ((f"매출채권 2021→{yl}년 {jo(r0, 1)} → {jo(r1, 1)}({r1 / r0:.1f}배, 매출은 {rev1 / rev0:.1f}배)"
                                     if r0 and r1 and rev0 and rev1 else "–")
                                    + (f"; 1년 넘은 채권 {jo(ra['over_1y'])} → {jo(rl['over_1y'])}({yl - 2}→{yl})"
                                       if ra.get("over_1y") is not None and rl.get("over_1y") is not None else ""))
    lp = [(y, F["est"][y]["loss_prov"]) for y in years if y in F["est"] and F["est"][y].get("loss_prov") is not None]
    pf_txt = f"; PF 보증 {jo(F['pf'][-1][1]['amount'], 1)}(자본의 {F['pf_x']:.1f}배)" if F["pf"] and F["pf_x"] else ""
    ev_["공사손실충당부채·우발채무(PF 보증)"] = (f"공사손실충당부채 최대 {jo(max(lp, key=lambda x: x[1])[1])}({max(lp, key=lambda x: x[1])[0]}년)" if lp else "–") + pf_txt
    lb, yrs = F["lb"], F["yrs"]
    ev_["신규 수주·수주잔고"] = (f"잔고 {jo(lb['total'], 1)}(매출 {yrs:.1f}년 치) — 잔고가 커진 기간에도 이익률은 하락" if lb and yrs else "–")
    bal = F["bal"]
    cov = F["vd"].get("coverage")
    ev_["순차입금·이자 부담"] = (f"{nd_text(v.a(2022, 'net_debt'))}(2022년 말) → {nd_text(bal['values']['net_debt'])}({an.when_label(bal)}); "
                            f"이자보상배율 {cov:.1f}배" if bal and bal["values"].get("net_debt") is not None and v.a(2022, "net_debt") is not None and cov is not None else "–")
    ev_["ROIC·ROE(자본 효율)"] = f"ROIC {pct(v.a(y0, 'roic_pct'))}({y0}) → {pct(v.a(yl, 'roic_pct'))}({yl})"
    fcf = window_sum(F, "fcf", F["neg_start"], yl) if F["neg_start"] else None
    ev_["잉여현금흐름(FCF)"] = f"{F['neg_start']}~{yl}년 합계 {jo(fcf)}" if fcf is not None else "–"
    sb = [F["seg"][y]["margin"].get("building") for y in years if y in F["seg"]]
    ev_["매출총이익·매출총이익률"] = f"건축/주택 매출총이익률 최고 {pct(max(x for x in sb if x is not None))} → 최저 {pct(min(x for x in sb if x is not None))}" if sb else "–"
    ev_["매출액·매출 성장률"] = f"10년 {F['revl'] / F['rev0']:.2f}배 — 2024년 매출 +{v.a(2024, 'revenue_growth_pct'):.0f}%에 영업손실" if v.a(2024, "revenue_growth_pct") else "–"
    ev_["당기순이익"] = "환율 평가손익(2017·2018)·비지배지분 몫(2024) 때문에 영업이익과 다르게 움직임"
    ev_["현금 및 현금성자산"] = (f"{an.when_label(bal)} {jo(bal['values'].get('cash'), 1)} — 하지만 영업 현금 유출을 예금·차입으로 메운 결과" if bal else "–")
    ev_["부채비율·유동비율"] = (f"부채비율 {pct(bal['ratios'].get('debt_to_equity_pct'), 0)}이지만 차입금은 부채의 "
                         f"{bal['values']['borrowings_total'] / bal['values']['liabilities'] * 100:.0f}% — 나머지는 공사 관련 부채" if bal and bal["values"].get("borrowings_total") else "–")
    return ev_


def relation_cards(ctx, F):
    v, R, years = F["v"], F["R"], F["years"]
    yl = F["yl"]
    cards = []
    b24 = rs.op_bridge(v, 2023, 2024, "start")
    if b24:
        cards.append(("매출이 늘었는데 영업이익이 줄어드는 이유는?",
                      f"2024년 매출은 {(b24['rev1'] / b24['rev0'] - 1) * 100:.1f}% 늘어 전년 이익률이면 이익이 {sjo(b24['volume'])} 늘었겠지만, 원가율이 "
                      f"{b24['cost_ratio0']:.1f}% → {b24['cost_ratio1']:.1f}%로 올라 {sjo(b24['cost'])}를 잃었습니다(앞 해 기준 분해) [계산].",
                      "매출은 진행률로 늘어도, 원가 추정이 바뀌면 그해 이익이 한꺼번에 줄어듭니다."))
    c23 = F["cash"].get(2023)
    if c23 and c23.get("wc"):
        cards.append(("영업이익이 늘었는데 영업현금흐름이 나빠지는 이유는?",
                      f"2023년 영업이익은 {jo(c23['op'])}였지만 현금흐름표 주석의 운전자본 변동이 {sjo(c23['wc_total'])}(매출채권 {sjo(c23['wc']['receivables'])}, "
                      f"계약자산 {sjo(c23['wc']['contract_assets'])})이어서 영업활동현금흐름은 {jo(c23['cfo'])}였습니다 [공시·계산].",
                      "매출이 빨리 늘면 공사를 먼저 하고 나중에 받는 만큼 현금이 먼저 나갑니다. 청구한 뒤에도 회수가 늦으면 매출채권으로 쌓입니다."))
    lb = F["lb"]
    bk = [r for r in (F["biz"].get("backlog") or []) if r["month"] == 12 and not r.get("flag")]
    if len(bk) >= 2:
        first = next((r for r in bk if r["year"] >= F["y0"]), bk[0])
        last = bk[-1]
        cards.append(("수주잔고가 늘면 미래 이익도 늘까?",
                      f"수주잔고는 {first['year']}년 말 {jo(first['total'], 1)} → {last['year']}년 말 {jo(last['total'], 1)}로 늘었지만, "
                      f"같은 기간 영업이익률은 {pct(v.a(first['year'], 'operating_margin_pct'))} → {pct(v.a(last['year'], 'operating_margin_pct'))}로 낮아졌습니다 [공시·계산].",
                      "잔고는 매출의 양을 보장할 뿐 이익을 보장하지 않습니다. 잔고 속 공사의 예상 이익률과 원가 추정 변경을 함께 봐야 합니다."))
    bal = F["bal"]
    if bal:
        liab = bal["values"].get("liabilities")
        bor = bal["values"].get("borrowings_total")
        adv = bal["values"].get("advances_total")
        cards.append(("부채가 늘어도 성장에 유리한 경우가 있을까?",
                      f"{an.when_label(bal)} 부채 {jo(liab, 1)} 중 이자가 붙는 차입금은 {jo(bor, 1)}({bor / liab * 100:.0f}%)이고, "
                      f"발주처에게 미리 받은 돈(계약부채·선수금)이 {jo(adv, 1)}입니다 [공시·계산].",
                      "미리 받은 돈은 공사로 갚는 '좋은 부채'에 가깝습니다. 부채비율 하나보다 부채의 구성을 봐야 합니다."))
    if bal:
        nd0 = v.a(2022, "net_debt")
        cards.append(("현금이 많으면 재무가 건전하다고 할 수 있나?",
                      f"{an.when_label(bal)} 현금은 {jo(bal['values'].get('cash'), 1)}이지만 2022년 말 {nd_text(nd0)}에서 {nd_text(bal['values'].get('net_debt'))}로 바뀌었고, PF 보증"
                      + (f"({jo(F['pf'][-1][1]['amount'], 1)})" if F["pf"] else "") + "이 따로 있습니다 [공시·계산].",
                      "현금 잔액은 '얼마나 버는가'가 아니라 '얼마나 남았나'입니다. 현금을 만드는 속도와 재무제표 밖 의무를 함께 봐야 합니다."))
    return cards


def ch5_items(ctx, F):
    R = F["R"]
    evd = item_evidence(ctx, F)
    rows = []
    for name, goal, why, role in ITEMS:
        rows.append([f"<b>{esc(name)}</b>", esc(goal), esc(why), esc(evd.get(name, "")), f'<span class="r-chip {ROLE_CHIP[role]}">{esc(role)}</span>'])
    table = rtable(["재무항목", "목적", "건설업 일반: 왜 보나 [해석]", "현대건설 10년에서 확인된 것 [공시·계산]", "이 보고서에서의 쓰임 [해석]"], rows, "r-items")
    rule = ("‘쓰임’은 점수나 순위가 아니라 이 보고서의 질문에 비춘 분류입니다. **핵심** = 결론(RQ2·RQ3)을 직접 바꾸는 항목, **보조** = 핵심 항목의 원인·결과를 "
            "설명하는 항목, **참고** = 건설업에서는 단독으로 쓰면 오해하기 쉬운 항목. ‘건설업 일반’ 칸은 업종 공통의 이유(분석자 정리)이고, ‘현대건설’ 칸만 이 회사의 "
            "자료입니다. 다른 목적(예: 채권자의 상환 능력)이라면 분류가 달라집니다(5-2) [해석].")
    purpose = rtable(["누구의 목적", "먼저 볼 항목", "이유"], [
        ["<b>살아남기(채권자·신용평가)</b>", "현금·순차입금·우발채무·유동성", "당장 갚을 수 있는지, 재무제표 밖 의무가 빚이 될지"],
        ["<b>장기 가치(주주)</b>", "원가율·영업이익률, ROIC, 잉여현금흐름", "벌어들인 이익이 자본비용보다 높고 현금으로 남는지"],
        ["<b>끝까지 짓는 회사(발주처·조합)</b>", "부채비율·유동비율, 신용등급, 수주잔고", "공사 중에 회사가 흔들리지 않을지"],
        ["<b>손익 관리(경영진)</b>", "원가 추정 변경, 공사별 진행률·계약자산", "어느 현장에서 원가가 새는지 일찍 알기"],
    ], "r-purpose")
    rel = "".join(f'<article class="qa"><p class="r-h">Q. {esc(q)}</p><p>{tagify(a)}</p><p class="qa-a">→ {tagify(c)}</p></article>'
                  for q, a, c in relation_cards(ctx, F))
    icon = {"good": "✓", "warn": "!", "crit": "✕", "info": "i"}
    w = R["warning"]
    wrows = []
    for r in w["rows"]:
        fmt = (lambda x: pct(x, 1)) if "%" in r["name"] else (lambda x: "–" if x is None else an._m(f"{x:,.2f}"))
        mark = {True: '<span class="r-chip crit">✕ 미리 나빠짐</span>', False: '<span class="r-chip info">아님</span>',
                None: '<span class="r-chip info">방향 판단 없음</span>'}[r["warned"]]
        wrows.append([esc(r["name"]), num(fmt(r["base"]), r["base"]), num(fmt(r["pre2"]), r["pre2"]), num(fmt(r["pre1"]), r["pre1"]),
                      num(fmt(r["event"]), r["event"]), mark])
    ey = w["event_year"]
    warn = rtable(["지표", f"평상시({w['base'][0]}~{w['base'][1]} 평균)", f"{ey - 2}년", f"{ey - 1}년", f"{ey}년(손실)", "손실 2년 전부터 나빠졌나"], wrows, "r-warn")
    L, years10 = F["L"], F["years10"]
    lrows = []
    for lens in L:
        m = lens["head"] if lens["id"] != "price" else lens["metrics_data"][0]
        rank = f" ({m['rank']}위)" if m.get("rank") else ""
        lrows.append([f'<b>{lens["no"]} {esc(lens["ko"])}</b>', esc(m["label"]), num(ln.with_unit(m["latest"], m["unit"]), m["latest"]),
                      f'<span class="r-chip {m["tone"]}">{icon[m["tone"]]} {esc(m["word"])}{esc(rank)}</span>',
                      num(ln.with_unit(m["median"], m["unit"]), m["median"])])
    lens_tbl = rtable(["관점", "대표 지표", f"{years10[-1]}년", f"{len(years10)}년 중 위치(좋은 순)", "중앙값"], lrows, "r-lens")
    dupont = next((x for x in L if x["id"] == "dupont"), None)
    dp = ""
    if dupont:
        heads, drows = st.dupont_rows(dupont, years10)
        # 연도를 열로: 순이익률 × 총자산회전율 × 재무레버리지 = ROE (줄 4개)
        tr = [[esc(heads[j])] + [num(r[j][0], r[j][1]) for r in drows] for j in (1, 2, 3, 5)]
        dp = (rtable(["듀퐁 분해"] + [esc(r[0]) for r in drows], tr, "r-dupont")
              + f'<p class="r-src">{rich(st.dupont_note(dupont, years10))} 세 값을 곱한 값과 ROE가 해마다 같은지는 대시보드 ‘종합 분석’ 표에 있습니다.</p>')
    grows = []
    for s_ in F["a"].get("steps", []):
        tone, word = s_["verdict"]
        grows.append([esc(f"{s_['no']} {s_['ko']}"), f'<span class="r-chip {tone}">{icon[tone]} {esc(word)}</span>', rich(s_["answer"])])
    guide = rtable(["단계", "판정", "한 줄 답"], grows, "r-guide")
    body = (sub("5-1", "열세 개 재무항목: 무엇을 위해 보나", table + f'<p class="r-src">{tagify(rule)}</p>',
                "지시한 열세 개 항목을 목적별로 묶고, 건설업 일반의 이유와 현대건설 자료에서 확인된 것을 나눠 적었습니다. 모든 기업에 맞는 절대 순위는 없어서 "
                "점수를 매기지 않았습니다.", keep=True)
            + sub("5-2", "목적에 따라 달라지는 순위", purpose, "누가 무엇을 위해 보느냐에 따라 먼저 볼 항목이 달라집니다. 분석자의 정리입니다 [해석].", keep=True)
            + sub("5-3", "재무항목은 서로 연결되어 있습니다", f'<div class="qas">{rel}</div>')
            + sub("5-4", f"검증: {ey}년 손실 전에 먼저 나빠진 지표는?", warn,
                  f"{ey}년 손실 2년 전({ey - 2}·{ey - 1}년) 값이 평상시보다 나빴는지 봤습니다. 사례가 하나뿐이라 '이 지표가 경보다'라는 결론은 이 사건에 한정됩니다 [해석].",
                  keep=True)
            + sub("5-5", "교수님 가이드: 6단계 판정과 재무비율 10가지 관점", guide
                  + f'<p class="r-subnote r-g2">아래 표는 수익성·안정성·유동성·활동성·성장성·생산성·현금흐름·시장가치에 종합 분석(듀퐁)과 주가 반영을 더한 '
                  f'10가지 관점의 대표 지표가 최근 {len(years10)}년 안에서 어디쯤인지입니다. 관점별 그래프는 재무제표 대시보드에 있습니다.</p>'
                  + lens_tbl + dp,
                  "재무제표·재무비율 실무가이드의 분석 순서(매출 성장 → 이익률 → 현금흐름 → 차입 부담 → 투자수익률 → 주가 수준)와 정해진 판정 규칙(부록 A)을 "
                  "따릅니다. 대시보드의 같은 판정과 매월 함께 바뀝니다."))
    lead = ("매출·이익·현금·부채 지표는 따로 보면 서로 다른 말을 합니다. 현대건설 자료로 확인하면 **원가율(영업이익률)과 영업활동현금흐름, "
            "그리고 받을 돈과 재무제표 밖의 우발채무**가 이 회사의 결론을 직접 바꾼 항목이었습니다 [해석].")
    return chapter("05", "What matters for growth", "성장에 중요한 재무항목", lead, body, "ch5")


# ---------------------------------------------------------------------------
# 6장 무엇이 실적을 움직였나
# ---------------------------------------------------------------------------
def bridge_fig(F):
    R = F["R"]
    br = R["bridges"]
    ys = [b["end"] for b in br]
    comps = [{"name": "매출 규모 효과", "values": [b["volume"] / T for b in br], "color": "--s3"},
             {"name": "원가율 효과", "values": [b["cost"] / T for b in br], "color": "--s2"},
             {"name": "판관비율 효과", "values": [b["sga"] / T for b in br], "color": "--s4"}]

    def tips(i):
        b = br[i]
        return (f"{b['end']}년 영업이익 변화 {sjo(b['d_op'])}", [["매출 규모 효과", sjo(b["volume"]), "var(--s3)"],
                                                           ["원가율 효과", sjo(b["cost"]), "var(--s2)"], ["판관비율 효과", sjo(b["sga"]), "var(--s4)"]],
                f"원가율 {b['cost_ratio0']:.1f}% → {b['cost_ratio1']:.1f}% · 판관비율 {b['sga_ratio0']:.1f}% → {b['sga_ratio1']:.1f}% · 두 해 평균 기준")
    chart = rc.diverging_stack(xlabels(ys), comps, tips=tips, net=[b["d_op"] / T for b in br], height=180,
                               net_labels={i: an.signed(b["d_op"] / T, 2) for i, b in enumerate(br)})
    rows = [[str(b["end"]), num(sjo(b["d_op"]), b["d_op"]), num(sjo(b["volume"]), b["volume"]), num(sjo(b["cost"]), b["cost"]),
             num(sjo(b["sga"]), b["sga"]), num(f"{b['cost_ratio1']:.1f}%")] for b in br]
    b10 = R["bridge_10y"]
    if b10:
        rows.append([f"<b>{b10['start']}→{b10['end']}</b>", num(sjo(b10["d_op"]), b10["d_op"]), num(sjo(b10["volume"]), b10["volume"]),
                     num(sjo(b10["cost"]), b10["cost"]), num(sjo(b10["sga"]), b10["sga"]), num(f"{b10['cost_ratio1']:.1f}%")])
    tbl = rtable(["연도", "영업이익 변화", "매출 규모 효과", "원가율 효과", "판관비율 효과", "원가율"], rows, "r-bridge")
    out = fig("fig-bridge", "영업이익은 왜 변했나: 세 가지 효과", "전년 대비 · 두 해 평균 기준 · 가로 막대 표시와 숫자 = 영업이익 변화(조 원) · 세 효과의 합과 같음",
              chart, legend_html=d.legend([(c["name"], c["color"], "box") for c in comps]))
    return out, tbl


def bridge_robust_table(F):
    """계산 방법(앞 해·뒤 해·평균 기준)과 기간을 바꾼 분해."""
    rob = F["R"].get("bridge_robust") or {}
    rows = []
    for m in rob.get("methods", []):
        w = m.get("whole")
        if not w:
            continue
        rows.append([f"<b>{esc(m['label'])}</b><span class=\"r-q\">{esc(m['formula'])}</span>", esc(f"{w['start']}→{w['end']}"),
                     num(sjo(w["volume"]), w["volume"]), num(sjo(w["cost"]), w["cost"]), num(sjo(w["sga"]), w["sga"]),
                     num(pct(m["abs_share"]["cost"], 0))])
    for wd in rob.get("windows", []):
        rows.append(["두 해 평균 기준", esc(wd["label"]), num(sjo(wd["volume"]), wd["volume"]), num(sjo(wd["cost"]), wd["cost"]),
                     num(sjo(wd["sga"]), wd["sga"]), num("–")])
    return rtable(["계산 방법", "기간", "매출 규모 효과", "원가율 효과", "판관비율 효과", "연간 변화 크기 중 원가율 몫"], rows, "r-robust")


def estimate_fig(F):
    est = [F["est"][y] for y in F["years"] if y in F["est"]]
    ys = [r["year"] for r in est]
    comps = [{"name": SEG_KO[k], "values": [(r["by_seg"].get(k) or 0) / T for r in est], "color": SEG_COLOR[k]} for k in ("building", "civil", "plant")]

    def tips(i):
        r = est[i]
        rows = [[SEG_KO[k], won(r["by_seg"].get(k)), f"var({SEG_COLOR[k]})"] for k in ("building", "civil", "plant")]
        rows += [["합계(연결)", won(r["current"]), None], ["현대건설 본사(별도)", won(r["parent"]), None], ["미래 손익 영향", won(r["future"]), None]]
        return f"{r['year']}년 원가 추정 변경이 그해 세전손익에 준 영향", rows, f"매출 대비 {pct(r['pct_rev'], 1)}"
    chart = rc.diverging_stack(xlabels(ys), comps, tips=tips, net=[r["current"] / T for r in est], height=170,
                               net_labels={i: an.signed(r["current"] / T, 2) for i, r in enumerate(est)})
    note = None
    if F["est_calm"] is not None:
        note = (f"{ys[0]}~2021년 평균은 {josa(jo(F['est_calm']), '이었')}습니다. 원가 추정은 해마다 조금씩 나빠지는 것이 보통이고, "
                "문제는 그 크기가 평상시보다 커지는 해입니다 [계산].")
    return fig("fig-estimate", "진행 중인 공사의 원가 추정이 바뀌어 그해 세전손익에 준 영향", "회사 공시(건설계약 주석) · 연결 · 부문별 · 가로 표시 = 합계",
               chart, legend_html=seg_legend(("building", "civil", "plant")), note=note)


def estimate_table(F):
    """해마다 공시된 추정 변경표: 총계약수익 변경 − 총계약원가 변경 = 공사 전체 이익 변화 = 당기 영향 + 미래 영향(합이 정확히 맞음)."""
    rows = []
    keys = ("rev_change", "cost_change", "lifetime", "current", "future", "parent", "others", "loss_prov")
    tot = {k: 0 for k in keys}
    for y in F["years"]:
        r = F["est"].get(y)
        if not r:
            continue
        for k in keys:
            tot[k] += r.get(k) or 0
        rows.append([str(y)] + [num(sjo(r.get(k)), r.get(k)) for k in keys[:-1]] + [num(jo(r.get("loss_prov")))]
                    + [num(jo(r.get("op")), r.get("op"))])
    rows.append(["<b>10년 합</b>"] + [num(sjo(tot[k]), tot[k]) for k in keys[:-1]] + [num("–"), num("–")])
    return rtable(["연도", "총계약수익 추정 변경", "총계약원가 추정 변경", "공사 전체 이익 변화(①+②)", "① 그해 세전손익 영향", "② 미래 손익 영향",
                   "①의 본사(별도)", "①의 본사 외", "공사손실충당부채", "영업이익(참고)"], rows, "r-est")


def materials_fig(F):
    mats = F["dr"].get("materials") or {}
    keys = [k for k in ("봉강류(철근)", "강판류(후판)", "레미콘", "시멘트") if k in mats]
    years = F["years"]
    base_y = str(years[0])
    series = []
    colors = ["--s2", "--s3", "--s1", "--s4"]
    for k, c in zip(keys, colors):
        vals = mats[k]["values"]
        b = vals.get(base_y)
        series.append({"name": k.replace("봉강류", "").replace("강판류", "").strip("()") or k, "values":
                       [vals.get(str(y)) / b * 100 if b and vals.get(str(y)) else None for y in years], "color": c})
    if not series:
        return ""

    def tips(i):
        y = years[i]
        return f"{y}년 자재 가격({years[0]}년 = 100)", [[s["name"], "–" if s["values"][i] is None else f"{s['values'][i]:.0f}", f"var({s['color']})"] for s in series], \
            "사업보고서 '주요 원자재 가격변동추이'(회사 구매 기준가)"
    return fig("fig-materials", "주요 자재 가격", f"{years[0]}년 = 100 · 회사 사업보고서 원재료 가격표",
               d.multi_line_chart(xlabels(years), series, ticks_fmt=lambda t: an._m(f"{t:g}"), tips=tips, height=150,
                                  end_fmt=lambda x: f"{x:.0f}"),
               legend_html=d.legend([(s["name"], s["color"], "box") for s in series]))


def rate_fig(F):
    v, years = F["v"], F["years"]
    br = (F["RC"].get("macro") or {}).get("base_rate") or {}
    base = [br.get(str(y)) for y in years]
    imp = [v.a(y, "borrowing_rate_pct") for y in years]

    def tips(i):
        y = years[i]
        return f"{y}년", [["기준금리(연말)", pct(base[i], 2), "var(--s3)"], ["현대건설 평균 차입 이자율(계산)", pct(imp[i], 2), "var(--s2)"],
                          ["이자비용", won(v.a(y, "interest_expense")), None]], "차입 이자율 = 이자비용 ÷ 평균 차입금"
    return fig("fig-rate", "금리와 현대건설의 차입 이자율", "기준금리: 한국은행 · 차입 이자율: 이자비용 ÷ 평균 차입금(계산)",
               d.multi_line_chart(xlabels(years), [{"name": "기준금리", "values": base, "color": "--s3", "dash": True},
                                                   {"name": "차입 이자율", "values": imp, "color": "--s2"}],
                                  ticks_fmt=tick_pct, tips=tips, height=150, end_fmt=lambda x: pct(x, 1)),
               legend_html=d.legend([("기준금리(연말)", "--s3", "box"), ("평균 차입 이자율", "--s2", "box")]))


def cash_fig(F):
    v, years = F["v"], F["years"]
    op = [v.a(y, "operating_profit") for y in years]
    cf = [v.a(y, "operating_cashflow") for y in years]

    def tips(i):
        y = years[i]
        c = F["cash"].get(y) or {}
        return f"{y}년", [["영업이익", won(op[i]), "var(--s1)"], ["영업활동현금흐름", won(cf[i]), "var(--s2)"],
                          ["운전자본 변동(현금흐름표 주석)", won(c.get("wc_total")), None], ["그중 매출채권", won((c.get("wc") or {}).get("receivables")), None]], None
    return fig("fig-cash", "이익과 현금", "연결 · 조 원", d.column_chart(xlabels(years), [{"values": d.in_jo(op), "color": "--s1"},
                                                                                  {"values": d.in_jo(cf), "color": "--s2"}],
                                                                  ticks_fmt=d.tick_jo, tips=tips, height=160, neg_zone=True),
               legend_html=d.legend([("영업이익", "--s1", "box"), ("영업활동현금흐름", "--s2", "box")]))


def cash_year_table(F):
    """해마다: 순이익 + 비현금 조정 + 운전자본 = 영업으로부터 창출된 현금, + 이자·배당·법인세 = 영업활동현금흐름(합이 정확히 맞음)."""
    rows = []
    for y in F["years"]:
        c = F["cash"].get(y)
        if not c:
            continue
        wc = c["wc"]
        rows.append([str(y) + ("*" if c.get("basis") == "next" else ""), num(sjo(c["ni"]), c["ni"]), num(sjo(c["adj_total"]), c["adj_total"]),
                     num(sjo(c["wc_total"]), c["wc_total"]), num(sjo(wc["receivables"]), wc["receivables"]),
                     num(sjo(wc["contract_assets"]), wc["contract_assets"]), num(sjo(wc["payables"] + wc["other_payables"]), wc["payables"] + wc["other_payables"]),
                     num(sjo(c["generated"]), c["generated"]), num(sjo(c["int_tax"]), c["int_tax"]), num(sjo(c["cfo"]), c["cfo"])])
    return rtable(["연도", "당기순이익", "비현금 조정", "운전자본 변동", "그중 매출채권", "그중 계약자산", "그중 매입·기타채무",
                   "영업으로부터 창출된 현금", "이자·배당·법인세", "영업활동현금흐름"], rows, "r-cashy")


def cash_window_table(F):
    """두 기간(영업 현금이 플러스였던 시기 · 마이너스가 이어진 시기)과 10년 합계로 본 영업활동현금흐름의 구성."""
    ws = [w for w in F["R"].get("cash_windows") or []]
    if not ws:
        return ""
    lines = [("당기순이익", lambda w: w["ni"], True)]
    lines += [(f"　조정: {name}", (lambda k: lambda w: w["adj"][k])(k), False) for k, name in rs.CF_ADJ]
    lines.append(("비현금 조정 합계", lambda w: w["adj_total"], True))
    lines += [(f"　운전자본: {name}", (lambda k: lambda w: w["wc"][k])(k), False) for k, name in rs.CF_WC]
    lines.append(("운전자본 변동 합계", lambda w: w["wc_total"], True))
    lines.append(("영업으로부터 창출된 현금", lambda w: w["generated"], True))
    lines += [("　이자·배당 수취", lambda w: w["interest_received"] + w["dividends_received"], False),
              ("　이자 지급", lambda w: w["interest_paid"], False), ("　법인세 납부", lambda w: w["tax_paid"], False)]
    lines.append(("영업활동현금흐름", lambda w: w["cfo"], True))
    rows = []
    for name, fn, bold in lines:
        vals = [fn(w) for w in ws]
        label = f"<b>{esc(name.strip())}</b>" if bold else esc(name)
        rows.append([label] + [num(sjo(x), x) for x in vals])
    return rtable(["연결 · 조 원"] + [f"{w['start']}~{w['end']}년({w['years']}년)" for w in ws], rows, "r-cashw")


def receivables_table(F):
    """매출채권 연령분석(연결)과 공사미수금·분양미수금 — 1년 넘은 채권이 늘었는지가 회수 지연의 직접 증거입니다."""
    rows = []
    labels = None
    for r in F["recv"]["rows"]:
        if not r.get("aging"):
            continue
        a = r["aging"]
        labels = labels or r.get("aging_labels")
        gross = r["gross"]
        rows.append([str(r["year"]), num(jo(r.get("construction"))), num(jo(r.get("sales"))),
                     num(jo(a["b0"])), num(jo(a["b1"])), num(jo(a["b2"])), num(jo(a["b3"])),
                     num(jo(r["allowance"]), r["allowance"]), num(f"{jo(r['over_1y'])} · {r['over_1y'] / gross * 100:.0f}%" if gross else "–"),
                     num(f"{r['trade'] / r['revenue'] * 100:.1f}%" if r.get("trade") and r.get("revenue") else "–")])
    if not rows:
        return ""
    return rtable(["연말", "공사미수금 총액", "분양미수금 총액", "연체 없음·3개월 이내", "1년 이내(3개월 초과)", "1~3년", "3년 초과", "손상차손누계액",
                   "1년 넘은 채권 · 비중", "매출채권 ÷ 매출"], rows, "r-aging")


def receivables_split_table(F):
    rv = F["recv"]
    sp = rv.get("split") or {}
    names = (("trade", "매출채권(청구했지만 못 받은 돈)"), ("receivables_total", "매출채권 + 계약자산(아직 청구 전 포함)"),
             ("net_contract", "받을 돈 − 미리 받은 돈(계약부채·선수금)"))
    rows = []
    for k, name in names:
        x = sp.get(k)
        if not x:
            continue
        rows.append([esc(name), num(f"{jo(x['s0'])} → {jo(x['s1'])}"), num(f"{x['k0']:.1f}% → {x['k1']:.1f}%"), num(sjo(x["d"]), x["d"]),
                     num(sjo(x["scale"]), x["scale"]), num(sjo(x["ratio"]), x["ratio"])])
    if not rows:
        return ""
    return rtable([f"{rv['base']}년 말 → {rv['last']}년 말", "잔액", "매출 대비", "증가", "매출 규모 효과", "비율 효과(회수·청구 조건)"], rows, "r-split")


def bs_vs_cf_table(F):
    """같은 계정을 재무상태표 증감(기말 − 기초)으로 본 현금 효과와 현금흐름표 주석의 금액 비교."""
    c = F["cash"].get(F["yl"]) or {}
    if not c.get("bs_delta"):
        return ""
    items = (("receivables", "매출채권", -1), ("contract_assets", "계약자산(미청구공사)", -1), ("contract_liabilities", "계약부채(초과청구공사)", +1))
    rows = []
    for k, name, sign in items:
        bsd = c["bs_delta"].get(k)
        implied = sign * bsd if bsd is not None else None
        cf = c["wc"].get(k)
        rows.append([esc(name), num(sjo(implied), implied), num(sjo(cf), cf), num(sjo(cf - implied) if implied is not None else "–", (cf - implied) if implied is not None else None)])
    return rtable([f"{F['yl']}년", "재무상태표 증감으로 본 현금 효과", "현금흐름표 주석의 금액", "차이"], rows, "r-bscf")


def factor_rows(ctx, F):
    """외부·내부 요인을 '크기가 공시·회계식으로 확인된 것'과 '경로만 확인된 것'으로 나눕니다. 묶음 안의 순서는 중요도 순위가 아닙니다."""
    v, R, years = F["v"], F["R"], F["years"]
    mats = F["dr"].get("materials") or {}

    def chg(name, a, b):
        m = mats.get(name, {}).get("values", {})
        x, y = m.get(str(a)), m.get(str(b))
        return (y / x - 1) * 100 if x and y else None
    seg = F["seg"]
    bgm = lambda y: (seg.get(y) or {}).get("margin", {}).get("building")
    est = F["est"]
    sens = R["sens"]
    ib = rs.interest_bridge(v, 2021, F["yl"])
    pf0 = (F["biz"].get("pf") or {}).get("2022.12", {}).get("amount")
    w = F["est_worst"]
    hec24 = (F["ent"].get(2024) or {}).get("hec_op")
    cw = F["cashw"].get((F["neg_start"], F["yl"])) if F["neg_start"] else None
    known, path = [], []
    if w:
        known.append(("원가 추정 변경(공사비·현장 수행)", "고정가격 계약에서 원가가 오르거나 공기가 늘면 → 총예정원가 상향 → 그해 손익에 한꺼번에 반영",
                      f"{w['year']}년 그해 세전손익 {jo(w['current'])}, 10년 그해 영향의 합 {jo(F['est_sum'])} [공시]; 같은 해 현대엔지니어링 영업손실 {jo(hec24)} [공시]",
                      "회사 계산(전기말 진행 중 공사만). 원인별(자재·공기·설계변경) 금액은 나뉘지 않음", "회사 고유 + 업계 공통"))
    if cw:
        known.append(("운전자본(대금 회수)", "공사 진행 > 청구·회수 → 계약자산·매출채권 증가 → 영업 현금 유출",
                      f"{cw['start']}~{cw['end']}년 운전자본 {sjo(cw['wc_total'])}(매출채권 {sjo(cw['wc']['receivables'])}) [공시·계산]",
                      "계정별 금액만 공시 — 현장·발주처별 원인은 확인 불가", "구조적 + 이 기간의 회수 지연"))
    if sens.get("rate_1pp") is not None:
        known.append(("금리 — 직접(이자비용)", "변동금리 차입금의 이자 → 금융비용",
                      f"이자율 1%p 상승 시 세전이익 {seok(sens['rate_1pp'])}({sens.get('sens_year')}년 말 기준) [공시]"
                      + (f"; 이자비용 2021→{F['yl']}년 금리 효과 {seok(ib['rate_effect'])}, 차입 규모 효과 {seok(ib['volume_effect'])} [계산]" if ib else ""),
                      f"범위: {sens.get('rate_scope') or '변동이자율 차입금'}만, 기준: {sens.get('rate_measure') or '세전이익'}. 고정금리 차입·예금 이자·간접 효과는 빠짐",
                      "경기적"))
    if sens.get("fx_10pct") is not None:
        known.append(("환율 — 직접(외화 환산)", "외화 자산·부채의 원화 환산 → 영업외손익·자본",
                      f"원화 환율 10% 상승(원화 약세) 시 {seok(sens['fx_10pct'])}({sens.get('sens_year')}년 말 기준) [공시]",
                      f"범위: {sens.get('fx_scope') or '외화 화폐성 항목'}, 기준: {sens.get('fx_measure') or '순자산(세전)'} — 세전이익이 아님. 해외 공사 원가·수주에 주는 효과는 빠짐",
                      "변동성(일시적)"))
    path.append(("공사비(자재·인건비) 상승", "계약금액이 고정된 공사의 원가 상승 → 원가 추정 변경으로 나타남",
                 f"레미콘 {pct(chg('레미콘', 2020, 2024), 0)}, 시멘트 {pct(chg('시멘트', 2020, 2024), 0)}(2020→2024, 회사 구매가) [공시]; "
                 f"건축/주택 매출총이익률 {pct(bgm(2021))} → {pct(bgm(2024))} [계산]",
                 "원가 추정 변경 중 자재 몫은 공시되지 않음", "일시적(물가 급등기) + 구조적(계약 구조)"))
    path.append(("주택 경기·PF 환경", "미분양·PF 경색 → 조합·시행사의 대금 지연, 보증·책임준공 부담",
                 (f"PF 보증 {jo(pf0, 1)}(2022년 말) → {jo(F['pf'][-1][1]['amount'], 1)}({rv.period_label(F['pf'][-1][0])}) [공시]" if F["pf"] and pf0 else "–"),
                 "보증에서 생긴 손실은 확인되지 않음 — 노출 크기만 확인", "경기적"))
    path.append(("금리 — 간접(분양·PF·발주처 투자)", "금리 상승 → 분양 부진·PF 비용 → 대금 회수 지연, 발주 감소", "크기를 재는 공시 없음",
                 "연간 10개 값으로는 인과를 증명할 수 없어 상관계수를 내지 않음", "경기적"))
    mk = F["dr"].get("market") or {}
    mk_y = [y for y in years if (mk.get(str(y)) or {}).get("domestic_growth_pct") is not None][-4:]
    path.append(("건설 경기(국내 수주)", "국내 발주 → 몇 년 뒤 매출 · 경쟁 강도 → 수주 이익률",
                 ("국내 건설수주 증감률 " + ", ".join(f"{y}년 {an.signed(mk[str(y)]['domestic_growth_pct'], 1)}%" for y in mk_y)
                  + " [공시: 대한건설협회 인용]" if mk_y else "–"),
                 "현대건설 손익에 준 크기는 확인되지 않음(해마다 집계 기간이 11~12개월로 달라 금액 대신 회사가 인용한 증감률)", "경기적"))
    reg = F["dr"].get("regions") or {}
    me = [(y, (reg.get(str(y)) or {}).get("revenue", {}).get("mideast")) for y in years]
    path.append(("해외 발주·유가·지정학", "유가·발주처 투자 → 해외 수주·매출 구성; 전쟁 → 현장 안전·공기",
                 f"중동·아프리카 매출 {jo(me[0][1], 1)}({me[0][0]}) → {jo(me[-1][1], 1)}({me[-1][0]}) [공시]; 2026년 이란 전쟁 [보도]",
                 "손익 영향은 공시 전", "경기적·지정학"))
    path.append(("정책·규제·안전", "대출 규제·주택 공급 정책 → 분양; 중대재해처벌법·사고 → 공기·영업정지·수주 제한",
                 "서울-세종 고속도로 교량 붕괴(2025, 현대엔지니어링) [공시]; GTX-A 철근 누락(2026) [보도]; 중대재해처벌법(2022) [보도]",
                 "손실 금액 공시 없음", "규제 · 회사 고유"))
    path.append(("팬데믹(2020)", "현장 중단·착공 지연 → 매출 감소·비용 선반영", "2020년 해외 공사 중단·선제적 비용 반영 [공시]",
                 f"원가 추정 변경 2019 {jo((est.get(2019) or {}).get('current'))} → 2020 {jo((est.get(2020) or {}).get('current'))}; 코로나 몫은 미공시",
                 "일시적"))
    return known, path


def ch6_drivers(ctx, F):
    R, v, years = F["R"], F["v"], F["years"]
    fig_b, tbl_b = bridge_fig(F)
    sh = bridge_shares(F)
    b10 = R["bridge_10y"]
    rob = R.get("bridge_robust") or {}
    shares = [m["abs_share"]["cost"] for m in rob.get("methods", []) if m.get("abs_share", {}).get("cost") is not None]
    pts = []
    if b10:
        pts.append(f"{b10['start']}→{b10['end']}년 영업이익 {sjo(b10['d_op'])}: 매출이 {b10['rev1'] / b10['rev0']:.2f}배가 되며 생긴 규모 효과 {sjo(b10['volume'])}보다 "
                   f"원가율 상승({b10['cost_ratio0']:.1f}% → {b10['cost_ratio1']:.1f}%) 효과 {sjo(b10['cost'])}가 컸습니다 [계산].")
    if sh.get("cost") is not None:
        pts.append(f"해마다의 영업이익 변화를 크기(절댓값의 합)로 보면 **원가율 효과가 {sh['cost']:.0f}%**, 판관비율 {sh['sga']:.0f}%, 매출 규모 {sh['volume']:.0f}%입니다"
                   + (f" — 앞 해·뒤 해·평균 어느 기준으로 계산해도 {min(shares):.0f}~{max(shares):.0f}%" if len(shares) >= 2 else "") + " [계산].")
    odd = [b for b in R["bridges"] if b["rev1"] > b["rev0"] and b["volume"] < 0]
    if odd:
        a_ = rs.op_bridge(v, odd[0]["start"], odd[0]["end"], "start")
        pts.append(f"{', '.join(str(b['end']) for b in odd)}년처럼 영업이익률이 마이너스로 바뀐 해는 두 해 평균 이익률도 마이너스라, 매출이 늘었는데도 규모 효과가 "
                   f"마이너스로 계산됩니다(앞 해 이익률 기준이면 {odd[0]['end']}년 {sjo(a_['volume'])}) [계산].")
    if rob.get("windows"):
        pts.append("기간을 바꿔도(3년 평균끼리 비교, 2024·2025년을 뺀 기간 등) 원가율 효과가 규모 효과보다 큽니다(아래 표) [계산].")
    pts.append("이 분해는 숫자를 정확히 나누는 회계 항등식이지 원인의 증명이 아닙니다. 원가율이 ‘왜’ 올랐는지는 6-2(원가 추정 변경)와 6-3(외부 요인)에서 "
               "따로 확인합니다 [해석].")
    # 6-2 원가 추정 변경
    fig_e = estimate_fig(F)
    est_tbl = estimate_table(F)
    ev24 = (F["RC"].get("events") or {}).get("2024", {})
    reason = box("회사가 공시한 2024년 원가 추정 변경 사유", f'<p>{tagify(ev24.get("detail", ""))}</p>', "warn") if ev24.get("detail") else ""
    w = F["est_worst"]
    est_pts = []
    if w and F["est_calm"]:
        est_pts.append(f"{w['year']}년 그해 영향 {josa(jo(w['current']), '은')} 평상시({years[0]}~2021년 평균 {jo(F['est_calm'])})의 {w['current'] / F['est_calm']:.0f}배였고, "
                       f"매출의 {abs(w['pct_rev']):.1f}%에 해당합니다 [계산].")
        if w.get("rev_change") is not None and w.get("lifetime") is not None:
            est_pts.append(f"같은 해 총계약수익 추정도 {sjo(w['rev_change'])} 늘었지만 총계약원가 추정이 {sjo(w['cost_change'])} 늘어, 진행 중 공사 전체의 이익이 "
                           f"{sjo(w['lifetime'])} 바뀌었습니다. 그중 {sjo(w['current'])}가 그해, {sjo(w['future'])}가 앞으로의 손익에 들어갑니다 [공시·계산]. "
                           "수익·원가가 함께 커진 데에는 공사비 증액·설계변경과 환율 변동이 섞여 있을 수 있어(주석은 원인을 나누지 않음) 두 숫자의 차이만 해석합니다 [해석].")
        if w.get("others") is not None:
            est_pts.append(f"그해 영향 중 본사 외(현대엔지니어링 등)가 {jo(w['others'])}, 본사가 {jo(w['parent'])}였습니다 [공시·계산]. "
                           "본사는 다른 공사의 이익으로 상당 부분을 메웠지만, 현대엔지니어링은 그러지 못해 영업손실이 됐습니다.")
    est_pts.append(f"**영업이익과의 관계**: 이 숫자는 ‘추정이 바뀌지 않았다면’과 비교한 세전손익의 차이입니다. 그래서 영업이익의 구성 항목처럼 더하거나 빼지 않습니다. "
                   f"{w['year'] if w else ''}년 영업손실({jo(v.a(w['year'], 'operating_profit')) if w else '–'})은 이 효과에 다른 공사의 정상 이익과 판관비가 합쳐진 결과입니다 [해석].")
    if F["est_sum"] is not None and F["est_life_sum"] is not None:
        est_pts.append(f"**10년 합계를 읽는 법**: 해마다의 ‘그해 영향’을 더하면 {jo(F['est_sum'])}이지만 누적 손실이 아닙니다. 같은 해 추정 변경의 ‘미래 손익 영향’"
                       f"(10년 합 {sjo(F['est_future_sum'])})은 뒤 해의 손익에 나뉘어 들어가므로, 추정 변경으로 진행 중 공사의 전체 이익이 바뀐 크기는 "
                       f"{jo(F['est_life_sum'])}입니다 [계산].")
    e22, e23 = (F["est"].get(2022) or {}).get("current"), (F["est"].get(2023) or {}).get("current")
    if e22 and e23 and F["est_calm"]:
        est_pts.append(f"경고는 미리 있었습니다: 2022·2023년 그해 영향이 평상시의 {e22 / F['est_calm']:.1f}배·{e23 / F['est_calm']:.1f}배로 커졌고, "
                       "건축/주택에서도 마이너스가 커졌습니다(5-4 검증) [계산].")
    # 6-3 외부 요인
    known, path = factor_rows(ctx, F)
    krows = [[f"<b>{esc(a)}</b>", esc(b), tagify(c), esc(e), esc(g)] for a, b, c, e, g in known]
    prows = [[f"<b>{esc(a)}</b>", esc(b), tagify(c), esc(e), esc(g)] for a, b, c, e, g in path]
    ktbl = rtable(["크기가 확인된 요인", "영향 경로", "확인된 크기", "범위·한계", "성격 [해석]"], krows, "r-factor")
    ptbl = rtable(["경로만 확인된 요인", "영향 경로", "보이는 자료", "범위·한계", "성격 [해석]"], prows, "r-factor")
    fig_m, fig_r = materials_fig(F), rate_fig(F)
    # 6-4 현금
    fig_c = cash_fig(F)
    cw = F["cashw"].get((F["neg_start"], F["yl"])) if F["neg_start"] else None
    cash_pts = []
    if cw:
        cash_pts.append(f"{cw['start']}~{cw['end']}년 영업활동현금흐름 {jo(cw['cfo'])}: 순이익 {josa(sjo(cw['ni']), '과')} 비현금 조정 {josa(sjo(cw['adj_total']), '으로')} "
                        f"{sjo(cw['ni'] + cw['adj_total'])}의 현금이 생길 수 있었지만, 운전자본이 {sjo(cw['wc_total'])}, 이자·법인세가 {sjo(cw['int_tax'])}였습니다 [공시·계산].")
        pay = cw["wc"]["payables"] + cw["wc"]["other_payables"]
        cash_pts.append(f"운전자본 중 가장 큰 것은 **매출채권(청구했지만 못 받은 공사대금) {sjo(cw['wc']['receivables'])}**입니다. 계약자산 {sjo(cw['wc']['contract_assets'])}, "
                        f"기타채권 {sjo(cw['wc']['other_receivables'])}도 묶였고, 매입·기타채무가 {sjo(pay)} 늘어 일부를 메웠습니다 [공시·계산].")
    sp = F["recv"].get("split") or {}
    if sp.get("trade") and sp.get("net_contract"):
        t, n = sp["trade"], sp["net_contract"]
        cash_pts.append(f"**규모인가, 회수인가**: {F['recv']['base']}년 말 → {F['recv']['last']}년 말 매출채권 증가 {sjo(t['d'])} 중 매출이 커진 몫은 {sjo(t['scale'])}, "
                        f"매출 대비 비율이 {t['k0']:.1f}% → {t['k1']:.1f}%로 높아진 몫은 {sjo(t['ratio'])}입니다. 미리 받은 돈을 뺀 순액으로 보면 규모 {sjo(n['scale'])}, "
                        f"비율 {sjo(n['ratio'])}로 **비율(회수·청구 조건) 쪽이 더 큽니다** [계산].")
    ra, rl = F["recv_by"].get(F["yl"] - 2) or {}, F["recv_by"].get(F["yl"]) or {}
    if ra.get("over_1y") is not None and rl.get("over_1y") is not None:
        cash_pts.append(f"1년 넘게 못 받은 매출채권은 {F['yl'] - 2}년 말 {jo(ra['over_1y'])} → {F['yl']}년 말 {jo(rl['over_1y'])}, 손상차손누계액은 "
                        f"{jo(-ra['allowance'])} → {jo(-rl['allowance'])}입니다 [공시]. 늘어난 채권이 정상 결제 주기 안에만 있는 것이 아니라는 직접 증거입니다 [해석].")
    if rl.get("construction") is not None:
        cash_pts.append(f"매출채권의 대부분은 도급공사의 **공사미수금**({F['yl']}년 말 총액 {jo(rl['construction'])})이고 자체사업의 분양미수금은 {jo(rl.get('sales'))}입니다 [공시]. "
                        "어느 현장·발주처에서 쌓였는지는 일부 대형 계약만 공시돼 확인할 수 없습니다 [해석].")
    c24 = F["cash"].get(2024) or {}
    if c24:
        cash_pts.append(f"**2024년 손실과 현금**: 순손실 {jo(c24['ni'])}에도 영업활동현금흐름은 {jo(c24['cfo'])}였습니다. 손실의 상당 부분이 그해 현금이 나가지 않은 비용"
                        f"(비현금 조정 중 충당부채 전입−환입 {sjo(c24['adj']['provisions'])})이었고, 같은 해 계약부채가 {sjo(c24['wc']['contract_liabilities'])} 늘어 먼저 받은 돈이 "
                        "들어왔기 때문입니다 [공시·계산]. 손실 공사의 초과 원가는 남은 공사 기간에 현금으로 나갑니다 [해석].")
    cash_pts.append("공사미수금을 유동화 회사에 넘기는 이체약정(재매입 약정 포함)과 채권 팩토링 한도가 공시돼 있습니다 [공시: Ⅲ 약정사항 주석]. "
                    "처리 방식에 따라 영업활동현금흐름이 실제 회수보다 좋아 보일 수 있어 함께 봐야 합니다 [해석].")
    concl_cash = ""
    if cw:
        concl_cash = box("결론: 현금은 왜 나빠졌나", para(
            f"{cw['start']}~{cw['end']}년 현금 악화의 가장 큰 직접 요인은 **공사미수금이 쌓인 것**이고, 그 증가는 매출 규모보다 회수·청구 조건(비율) 쪽이 더 컸습니다 [계산]. "
            "프로젝트 손실은 아직 상당 부분 현금이 나가지 않은 비용 단계이고, 설비·지분 투자는 원인이 아닙니다(8-2) [해석]. "
            "한계: 현금흐름표 주석은 계정별 금액만 있어 현장·발주처별 원인(분쟁·조합 분양·계약 조건)은 공시로 나눌 수 없습니다."), "plain")
    bs_note = ("재무상태표 증감과 현금흐름표 금액이 다른 이유: ① 대손상각비(손상)는 비현금 조정에 더하고 운전자본에는 채권의 총액 변동을 적음 ② 외화 채권·채무의 환산 "
               "③ 계약자산 → 매출채권처럼 계정 사이 대체 ④ 연결 범위 변동. 그래서 원인 분석에는 현금흐름표 주석 숫자를 씁니다 [해석].")
    cl, cp = F["cash"].get(F["yl"]) or {}, F["recv_by"].get(F["yl"] - 1) or {}
    rl_ = F["recv_by"].get(F["yl"]) or {}
    if cl.get("bs_delta", {}).get("receivables") is not None and rl_.get("allowance") is not None and cp.get("allowance") is not None:
        gap = cl["wc"]["receivables"] + cl["bs_delta"]["receivables"]
        bs_note += (f" 예: {F['yl']}년 매출채권의 차이 {sjo(gap)}는 같은 해 손상차손누계액 증가 {sjo(cp['allowance'] - rl_['allowance'])}와 크기가 비슷합니다 [계산].")
    # 6-5 결론
    concl = rtable(["요인", "확인된 과거 영향", "수익성", "현금", "재무 건전성", "미래 성장", "성격"], conclusion_rows(ctx, F), "r-concl")
    body = (sub("6-1", "영업이익 변화 나누기: 규모 · 원가율 · 판관비율", fig_b + tbl_b + bullets(pts) + bridge_robust_table(F),
                "영업이익 = 매출 × 영업이익률이고 영업이익률 = 1 − 원가율 − 판관비율(+기타)이라 영업이익 변화는 규모 효과와 비율 효과로 정확히 나뉩니다(나머지 0, 부록 A). "
                "두 효과가 동시에 바뀐 몫(교차항)을 어디에 붙이느냐에 따라 숫자가 달라져, 본문은 두 해의 평균 이익률·평균 매출을 쓰는 방식(계산 순서에 따라 달라지지 "
                "않음)을 쓰고, 다른 방식과 다른 기간의 결과를 아래 표에 함께 보였습니다.")
            + sub("6-2", "원가는 어디서 새었나: 회사가 공시한 원가 추정 변경", fig_e + est_tbl + reason + bullets(est_pts),
                  "건설계약 주석의 원문: ‘전기말 현재 진행 중이었던 … 계약의 총계약금액 및 총계약원가에 대한 당기 중 추정의 변경과 그러한 추정의 변경이 당기와 "
                  "미래기간의 손익(법인세차감전) 및 미청구공사(초과청구공사)에 미치는 영향’ [공시]. 표의 ①+② = 총계약수익 변경 − 총계약원가 변경이 해마다 정확히 맞습니다. "
                  "연결은 연결재무제표 주석, 본사는 별도재무제표 주석의 같은 표이고 본사 외 = 연결 − 본사(차이)입니다.")
            + sub("6-3", "외부 요인: 크기가 확인된 것과 경로만 확인된 것", ktbl + ptbl + f'<div class="r-2">{fig_m}{fig_r}</div>',
                  "요인을 중요도 순으로 줄 세우지 않았습니다. 회사 공시나 회계식으로 크기가 확인된 것과, 영향 경로는 있지만 크기를 재는 공시가 없는 것을 나눴고, "
                  "두 표 안의 순서는 순위가 아닙니다. 연간 10개 값으로는 인과를 증명할 수 없어 상관계수를 내지 않았습니다 [해석].")
            + sub("6-4", "이익은 왜 현금이 되지 않았나", fig_c + cash_year_table(F) + cash_window_table(F) + bullets(cash_pts)
                  + receivables_table(F) + receivables_split_table(F) + bs_vs_cf_table(F) + para(bs_note, "r-src") + concl_cash,
                  "연결 현금흐름표 주석 ‘영업으로부터 창출된 현금’의 당기순이익 · 비현금 조정 · 영업활동으로 인한 자산·부채의 변동에 현금흐름표 본문의 이자·배당·법인세를 "
                  "더하면 영업활동현금흐름과 해마다 정확히 같습니다. *표시 연도(2016)는 다음 해 보고서의 전기 숫자입니다. 매출채권 연령 구간 이름은 보고서마다 다르지만"
                  "(같은 2023년 숫자를 ‘현재’·‘3개월 이내’로 표시) 1년 초과 구간은 이름이 같아 그 구간으로 비교합니다 [공시].")
            + sub("6-5", "결론: 어떤 요인이 얼마나 중요했나", concl,
                  "‘확인된 과거 영향’은 위의 공시·계산 숫자이고, 수익성·현금·재무 건전성·미래 성장 칸은 그 숫자를 바탕으로 한 분석자의 판단입니다. 크기가 공시되지 않은 "
                  "요인은 ‘미확인’으로 둡니다 [해석].", keep=True))
    lead = ("10년 실적의 변화를 회계식으로 나누면 **원가율**이 대부분을 설명합니다. 원가율 상승은 진행 중 공사의 원가 추정 변경으로 드러났고, "
            "그 뒤에는 자재값 급등(국내 주택)과 해외 플랜트 현장의 공기·설계 변경이 있었습니다. 2022년 이후 현금은 이익과 달리 **공사미수금이 쌓이며** 빠져나갔고, "
            "금리의 직접 영향은 작았습니다.")
    return chapter("06", "What moved the results", "무엇이 실적을 움직였나", lead, body, "ch6")


def conclusion_rows(ctx, F):
    R, years = F["R"], F["years"]
    b10 = R["bridge_10y"]
    w = F["est_worst"]
    s = R["sens"]
    cw = F["cashw"].get((F["neg_start"], F["yl"])) if F["neg_start"] else None
    hec = F["ent"].get(2024) or {}
    hec_l = F["ent"].get(F["yl"]) or {}
    rows = [
        ["<b>원가율(원가 추정 변경)</b>", esc(f"10년 영업이익 원가율 효과 {sjo(b10['cost'])} · 최대 {w['year']}년 그해 세전손익 {jo(w['current'])}" if b10 and w else "–"),
         "매우 큼", "간접(나중에 유출)", "자본 감소(손실)", "목표 이익률(8%)의 전제", "구조적"],
        ["<b>해외 플랜트·현대엔지니어링</b>", esc(f"2024년 현대엔지니어링 영업손실 {jo(hec.get('hec_op'))}" if hec.get("hec_op") is not None else "–"),
         "큼(한 해 집중)", esc(f"현금 유출({F['yl']}년 {jo(hec_l.get('hec_cfo'), 1)})" if (hec_l.get("hec_cfo") or 0) < 0 else "간접"),
         "비지배지분이 일부 흡수", "원전·에너지 EPC에도 같은 위험", "회사 고유·반복 가능"],
        ["<b>운전자본(대금 회수)</b>", esc(f"영업활동현금흐름 {cw['start']}~{cw['end']}년 {jo(cw['cfo'])} · 운전자본 {sjo(cw['wc_total'])}(매출채권 {sjo(cw['wc']['receivables'])})"
                                        if cw else "–"),
         "없음", "매우 큼", "순현금 감소·차입 증가", "투자 여력 제한", "구조적 + 이 기간의 회수 지연"],
        ["<b>공사비(자재·인건비)</b>", "건축/주택 이익률 하락(2022~2024) — 원가 추정 변경 중 자재 몫은 미공시", "큼", "간접", "간접", "신규 계약에 물가 반영 필요", "일시적+구조적"],
        ["<b>주택 경기·PF</b>", esc("손실 확인 없음 · 보증 노출 " + (jo(F['pf'][-1][1]['amount'], 1) if F["pf"] else "")), "미확인", "대금 지연 가능", "우발채무", "정비사업 수주 경쟁력", "경기적"],
        ["<b>금리</b>", esc(f"직접: 1%p당 세전 {seok(s.get('rate_1pp'))}(변동금리 차입금만, 회사 공시) · 간접 크기는 미확인"), "작음(직접)", "작음(직접)", "작음(직접)",
         "PF·분양 경로로 간접(미확인)", "경기적"],
        ["<b>환율</b>", esc(f"10%당 순자산(세전) {seok(s.get('fx_10pct'))}(외화 화폐성 항목 환산, 회사 공시)"), "순이익만", "작음", "작음", "해외 비중만큼(미확인)", "일시적"],
    ]
    return rows


# ---------------------------------------------------------------------------
# 7장 10년 연표: 실적과 사건을 나란히
# ---------------------------------------------------------------------------
AMOUNT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*조(?:\s*(\d[\d,]*)\s*억)?\s*원|(\d[\d,]*)\s*억\s*원")


def amounts_in(text):
    """문장 속 금액(원)과 '약'이 붙었는지. '1조 893억원' · '8,597억원' · '약 1.2조원'."""
    out = []
    for m in AMOUNT_RE.finditer(text or ""):
        if m.group(1):
            x = float(m.group(1)) * T + (float(m.group(2).replace(",", "")) * EOK if m.group(2) else 0)
        else:
            x = float(m.group(3).replace(",", "")) * EOK
        out.append((x, "약" in text[max(0, m.start() - 3):m.start()]))
    return out


def mdna_pick(F, y, limit=2):
    """그해 사업보고서 경영진단(Ⅳ장)에서 연결 실적을 설명하는 문장. 금액이 있는 문장은 그 금액이 연결 매출·영업이익·순이익과
    1% 안(‘약’이 붙은 어림수는 6% 안)에서 맞을 때만 씁니다(부문·별도 숫자나 고치기 전 숫자를 연결 실적으로 옮기지 않게)."""
    m = (F["dr"].get("mdna") or {}).get(str(y)) or {}
    v = F["v"]
    targets = [abs(x) for x in (v.a(y, "operating_profit"), v.a(y, "revenue"), v.a(y, "net_income")) if x]
    out = []
    for s in m.get("sentences") or []:
        amts = amounts_in(s)
        ok = (any(abs(a - t) / t <= (0.06 if rough else 0.01) for a, rough in amts for t in targets) if amts
              else bool(re.search(r"기인|영향|따라|반영", s)))
        if ok:
            out.append(s if len(s) <= 170 else s[:168].rstrip() + "…")
        if len(out) >= limit:
            break
    return out, m.get("receipt")


def change_kind(peers, y):
    """현대건설 영업이익률 변화가 동종사 중앙값과 같은 방향·비슷한 크기였는지(규칙은 부록 A)."""
    a, b = peers.get(y - 1), peers.get(y)
    if not a or not b or None in (a.get("own"), b.get("own"), a.get("median"), b.get("median")) or min(a["n"], b["n"]) < 2:
        return None
    d_own, d_med = round(b["own"] - a["own"], 1), round(b["median"] - a["median"], 1)    # 표에 적는 숫자(소수 1자리)로 판정
    way = "개선" if d_own > 0 else "하락"
    if abs(d_own) < 0.5:
        tone, word = "info", "큰 변화 없음"
    elif d_own * d_med > 0 and abs(d_med) >= abs(d_own) * 0.5:
        tone, word = ("good" if d_own > 0 else "warn"), f"업계 공통 {way}"
    else:
        tone, word = ("good" if d_own > 0 else "crit"), f"회사 고유 {way}"
    return {"d_own": d_own, "d_med": d_med, "tone": tone, "word": word}


def year_numbers(F, y):
    v = F["v"]
    e = (F["est"].get(y) or {}).get("current")
    pe = F["R"]["peers"].get(y) or {}
    return [("매출", jo(v.a(y, "revenue"), 1)), ("영업이익", jo(v.a(y, "operating_profit"))),
            ("영업이익률", pct(v.a(y, "operating_margin_pct"))), ("동종사 중앙값", pct(pe.get("median"))),
            ("영업활동현금흐름", jo(v.a(y, "operating_cashflow"))), ("원가 추정 변경", jo(e))]


def half_after(ctx, F):
    """마지막 사업연도 뒤에 나온 반기보고서(있으면)."""
    return next((r for r in reversed(ctx.get("halves") or []) if r["kind"] == "H1" and r["year"] > F["yl"]), None)


def year_card(F, label, numbers, ev_, kind=None, mdna=(), todo=None):
    nums = "".join(f"<div><dt>{esc(a)}</dt><dd>{esc(b)}</dd></div>" for a, b in numbers)
    chip_html = f'<span class="r-chip {kind["tone"]}">{esc(kind["word"])}</span>' if kind else ""
    def row(label, html_, cls=""):
        return f'<p class="yr {cls}"><span class="lab">{esc(label)}</span><span>{html_}</span></p>'
    lines = []
    if todo:
        lines.append(f'<p class="yc-todo">{tagify(todo)}</p>')
    if ev_.get("company"):
        lines.append(row("회사", tagify(ev_["company"])))
    ind = (ev_.get("industry") or []) + (ev_.get("policy") or [])
    if ind:
        lines.append(row("업계·정책", "<br>".join(tagify(x) for x in ind)))
    if ev_.get("peers"):
        lines.append(row("동종사", tagify(ev_["peers"])))
    if ev_.get("own"):
        lines.append(row("고유 요인", tagify(ev_["own"])))
    if mdna:
        lines.append(row("회사 설명", " ".join(f"“{esc(s)}”" for s in mdna) + f" {ev('공시: 경영진단')}", "yc-md"))
    if ev_.get("interp"):
        lines.append(row("해석", f'{tagify(ev_["interp"])} {ev("해석")}', "yc-in"))
    srcs = src_links(F, ev_.get("sources") or [])
    if srcs:
        lines.append(f'<p class="r-src">출처: {srcs}</p>')
    return (f'<article class="yc"><div class="yc-l"><p class="yc-y">{esc(label)}</p>{chip_html}<dl class="yc-n">{nums}</dl></div>'
            f'<div class="yc-r">{"".join(lines)}</div></article>')


def ch7_timeline(ctx, F):
    R, RC, v, years = F["R"], F["RC"], F["v"], F["years"]
    events = RC.get("events") or {}
    peers = dict(rs.peer_years(ctx, [years[0] - 1]))
    peers.update(R["peers"])
    rows, cards = [], []
    for y in years:
        ev_ = events.get(str(y))
        todo = None
        if not ev_ and events.get(f"{y}H1"):
            ev_, todo = events[f"{y}H1"], f"{y}년 사건은 상반기까지만 조사했습니다(조사 기준일 {RC.get('as_of', '–')})."
        if not ev_:
            ev_, todo = {}, (f"{y}년의 사건·정책·경쟁사 사건은 아직 조사하지 않았습니다(조사 전). 숫자와 회사 설명 문장만 자동으로 채웠습니다 — "
                             "조사 내용은 config/research.json의 events에 더합니다.")
        kind = change_kind(peers, y)
        md, _ = mdna_pick(F, y)
        est = (F["est"].get(y) or {}).get("current")
        chip_html = f'<span class="r-chip {kind["tone"]}">{esc(kind["word"])}</span>' if kind else '<span class="r-chip info">비교 불가</span>'
        delta = (" / ".join("0.0" if abs(x) < 0.05 else an.signed(x, 1) for x in (kind["d_own"], kind["d_med"])) if kind else "–")
        rows.append([f"<b>{y}</b>", num(pct(v.a(y, "operating_margin_pct")), v.a(y, "operating_margin_pct")), num(delta), chip_html,
                     num(jo(est), est), tagify(ev_.get("interp") or "조사 전")])
        cards.append(year_card(F, f"{y}", year_numbers(F, y), ev_, kind, md, todo))
    h = half_after(ctx, F)
    if h:
        key = f"{h['year']}H1"
        val = h["values"]
        rev, op = val.get("revenue"), val.get("operating_profit")
        nums = [("매출", jo(rev, 1)), ("영업이익", jo(op)), ("영업이익률", pct(op / rev * 100 if rev and op is not None else None)),
                ("영업활동현금흐름", jo(val.get("operating_cashflow")))]
        ev_ = events.get(key) or {}
        todo = None if ev_ else f"{h['year']}년 상반기 사건은 아직 조사하지 않았습니다(조사 전)."
        cards.append(year_card(F, f"{h['year']} 상반기", nums, ev_, None, (), todo))
        rows.append([f"<b>{h['year']} 상반기</b>", num(pct(op / rev * 100 if rev and op is not None else None)), num("–"),
                     '<span class="r-chip info">반기</span>', num("–"), tagify(ev_.get("interp") or "조사 전")])
    table = rtable(["연도", "영업이익률", "변화(현대 / 동종사, %p)", "변화의 성격 [계산]", "원가 추정 변경", "그해를 한 줄로 [해석]"], rows, "r-tl")
    counts = {}
    for y in years:
        k = change_kind(peers, y)
        if k:
            counts[k["word"]] = counts.get(k["word"], 0) + 1
    common = counts.get("업계 공통 하락", 0) + counts.get("업계 공통 개선", 0)
    own_ = counts.get("회사 고유 하락", 0) + counts.get("회사 고유 개선", 0)
    lead = (f"해마다 숫자(자동 계산)와 그해 회사·업계·정책 사건(조사)을 나란히 놓았습니다. 영업이익률이 동종사와 같은 방향으로 움직인 해(업계 공통)는 "
            f"{common}번, 다르게 움직인 해(회사 고유)는 {own_}번이었습니다 [계산]. 업계 공통이면 금리·자재값·정책 같은 외부 요인, 회사 고유면 "
            "특정 현장·자회사의 요인을 먼저 의심합니다.")
    body = (sub("7-1", "10년 연결표", table,
                "‘변화의 성격’은 영업이익률 변화가 동종사 중앙값 변화와 같은 방향이고 크기가 절반 이상이면 업계 공통, 아니면 회사 고유로 나눈 기계적 판정입니다(부록 A). "
                "인과를 증명하는 것이 아니라 어디부터 볼지 정하는 표입니다.", keep=True)
            + sub("7-2", "연도별 기록", "".join(cards),
                  f"왼쪽 숫자는 매월 다시 계산하고, 오른쪽 사건은 {RC.get('as_of', '–')}까지의 조사입니다. ‘회사 설명’은 그해 사업보고서 경영진단 문장을 자동으로 옮겼습니다."))
    return chapter("07", "Ten-year timeline", "10년 연표: 실적과 사건", lead, body, "ch7")


# ---------------------------------------------------------------------------
# 8장 현재: 번 돈을 어디에 썼나
# ---------------------------------------------------------------------------
ALLOC_GROUPS = [("영업활동현금흐름", ("cfo",), "--s1"),
                ("투자(설비·지분·금융자산, 순)", ("capex", "equity_net", "fin_net", "asset_sale"), "--s4"),
                ("예금·대여금(순)", ("deposits", "loans"), "--s3"),
                ("차입·사채(순)", ("borrow",), "--s2"),
                ("배당·리스·기타", ("dividends", "lease", "equity_tx", "other"), "--spark")]


def alloc_fig(F):
    rows = F["R"]["alloc"]
    if not rows:
        return ""
    ys = [r["year"] for r in rows]
    comps = [{"name": n, "values": [sum(r.get(k) or 0 for k in ks) / T for r in rows], "color": c} for n, ks, c in ALLOC_GROUPS]
    names = dict(rs.ALLOC)

    def tips(i):
        r = rows[i]
        tr = [[names[k], sjo(r.get(k)), None] for k, _ in rs.ALLOC if r.get(k)]
        tr.append(["현금및현금성자산 증감", sjo(r.get("cash_change")), None])
        return f"{r['year']}년 현금의 원천(+)과 사용(−)", tr, "연결 현금흐름표"
    net = [r["cash_change"] / T if r.get("cash_change") is not None else None for r in rows]
    chart = rc.diverging_stack(xlabels(ys), comps, tips=tips, net=net, height=190,
                               net_labels={i: an.signed(x, 2) for i, x in enumerate(net) if x is not None})
    return fig("fig-alloc", "현금은 어디서 와서 어디로 갔나", "연결 현금흐름표 · 0 위 = 들어온 돈, 0 아래 = 쓴 돈 · 가로 표시와 숫자 = 현금 증감(조 원)",
               chart, legend_html=d.legend([(n, c, "box") for n, _, c in ALLOC_GROUPS]),
               note="‘예금·대여금’이 0 위에 있으면 쌓아 둔 예금을 꺼내 쓰거나 빌려준 돈을 돌려받은 해, 0 아래면 예금을 쌓은 해입니다 [계산].")


def alloc_table(F):
    sums = F["R"]["alloc_sums"]
    if not sums:
        return ""
    heads = ["원천(+) · 사용(−)"] + [f"{s['start']}~{s['end']}년 합계({s['years']}년)" for s in sums]
    rows = [[esc(name)] + [num(sjo(s.get(k)), s.get(k)) for s in sums] for k, name in rs.ALLOC]
    rows.append(["<b>현금및현금성자산 증감</b>"] + [num(sjo(s.get("cash_change")), s.get("cash_change")) for s in sums])
    return rtable(heads, rows, "r-alloc")


def spend_table(F):
    sums = F["R"]["alloc_sums"]
    rnd = F["dr"].get("rnd") or {}

    def rnd_sum(s):
        vals = [(rnd.get(str(y)) or {}).get("total") for y in range(s["start"], s["end"] + 1)]
        vals = [x for x in vals if x is not None]
        return sum(vals) if vals else None
    items = [("연구개발비", "비용(매출원가·판관비에 포함)", "미래 경쟁력(투자활동 밖)", [rnd_sum(s) for s in sums]),
             ("설비·무형자산·투자부동산", "자산(투자활동)", "실물 투자(성장·유지)", [-s["capex"] for s in sums]),
             ("지분 투자(순)", "자산(투자활동)", "지분 투자(관계·공동기업 등)", [-s["equity_net"] for s in sums]),
             ("기타 금융자산(순)", "자산(투자활동)", "금융자산 운용 — 사업 투자 아님", [-s["fin_net"] for s in sums]),
             ("예금·단기금융상품(순)", "자산(투자활동)", "여유자금 운용 — 사업 투자 아님", [-s["deposits"] for s in sums]),
             ("대여금·보증금(순)", "자산(투자활동)", "사업 지원(조합·시행사 대여 등)", [-s["loans"] for s in sums]),
             ("배당금", "자본(재무활동)", "주주환원", [-s["dividends"] for s in sums]),
             ("리스부채 상환", "부채(재무활동)", "임차료 성격", [-s["lease"] for s in sums])]
    rows = []
    for name, acc, kind, vals in items:
        cells = []
        for s, x in zip(sums, vals):
            r = window_sum(F, "revenue", s["start"], s["end"])
            share = x / r * 100 if x is not None and r else None
            cells.append(num(f"{jo(x)} · 매출의 {an._m(f'{share:.1f}' if abs(share) >= 0.1 else f'{share:.2f}')}%" if share is not None else "–", x))
        rows.append([f"<b>{esc(name)}</b>", esc(acc), esc(kind)] + cells)
    return rtable(["어디에", "회계 처리", "성격"] + [f"{s['start']}~{s['end']}년 쓴 돈(−는 회수)" for s in sums], rows, "r-spend")


def dividend_table(F):
    div = F["dr"].get("dividends") or {}
    ys = [y for y in F["years"] if str(y) in div]
    if not ys:
        return ""
    g = lambda y, k: (div.get(str(y)) or {}).get(k)
    rows = [["주당 배당금(원)"] + [num(f"{g(y, 'dps'):,}" if g(y, "dps") else "–") for y in ys],
            ["배당 총액(억 원)"] + [num(eok(g(y, "total"))) for y in ys],
            ["배당성향(%)"] + [num(pct(g(y, "payout_pct"), 1) if g(y, "payout_pct") is not None else "손실") for y in ys]]
    return rtable(["사업연도"] + [str(y) for y in ys], rows, "r-div")


def interest_table(F):
    v, years = F["v"], F["years"]
    rows = [["이자비용(억 원)"] + [num(eok(v.a(y, "interest_expense"))) for y in years],
            ["평균 차입 이자율(%)"] + [num(pct(v.a(y, "borrowing_rate_pct"), 2)) for y in years],
            ["이자보상배율(배)"] + [num(an._m(f"{v.a(y, 'operating_profit') / v.a(y, 'interest_expense'):.1f}") if v.a(y, "interest_expense") else "–",
                                    v.a(y, "operating_profit")) for y in years],
            ["순차입금(조 원, −는 순현금)"] + [num(jo(v.a(y, "net_debt")), v.a(y, "net_debt")) for y in years]]
    return rtable(["연결"] + [str(y) for y in years], rows, "r-int")


def ch8_allocation(ctx, F):
    R, v, years = F["R"], F["v"], F["years"]
    sums = R["alloc_sums"]
    pts = []
    if len(sums) == 2:
        a1, a2 = sums
        pts.append(f"**{a1['start']}~{a1['end']}년**: 영업으로 {jo(a1['cfo'])}를 벌어 예금에 {jo(-a1['deposits'])}, 대여금에 {jo(-a1['loans'])}, "
                   f"설비 등에 {jo(-a1['capex'])}, 배당에 {jo(-a1['dividends'])}를 썼습니다 [계산].")
        pts.append(f"**{a2['start']}~{a2['end']}년**: 영업에서 {jo(-a2['cfo'])}가 빠져나가자 예금에서 {jo(a2['deposits'])}를 꺼내고, 대여금 {jo(a2['loans'])}를 "
                   f"돌려받고, {jo(a2['borrow'])}를 빌렸습니다. 그 와중에도 설비 등 투자({jo(-a2['capex'])})와 배당({jo(-a2['dividends'])})은 이어졌습니다 [계산].")
        cw = F["cashw"].get((a2["start"], a2["end"]))
        real = -(a2["capex"] + a2["equity_net"])
        if cw:
            pts.append(f"**현금이 줄어든 이유**: {a2['start']}~{a2['end']}년 실물·지분 투자는 {jo(real)}였지만 운전자본으로 묶인 돈은 {jo(-cw['wc_total'])}"
                       f"(그중 매출채권 {jo(-cw['wc']['receivables'])})였습니다(6-4) [계산]. 예금·대여금 회수는 투자가 아니라 쌓아 둔 돈을 꺼낸 것입니다. "
                       "현금 악화는 투자보다 회수 쪽에서 왔고, 손실 공사의 초과 원가는 앞으로 현금으로 나갑니다 [해석].")
        pts.append("앞 6년 동안 쌓은 예금이 뒤 4년의 영업 현금 유출을 버티는 완충이 됐습니다 [해석].")
    # 2024년 손실은 투자 때문이었나
    ey = R["warning"]["event_year"]
    a_e = next((r for r in R["alloc"] if r["year"] == ey), None)
    capex_avg = (sum(-r["capex"] for r in R["alloc"]) / len(R["alloc"])) if R["alloc"] else None
    rnd = (F["dr"].get("rnd") or {}).get(str(ey)) or {}
    e_e = F["est"].get(ey) or {}
    check = ""
    if a_e and e_e.get("current") is not None:
        check = box(f"검증: {ey}년 손실은 투자 때문이었나?", para(
            f"아닙니다. {ey}년 설비·무형자산 투자는 {jo(-a_e['capex'])}(10년 평균 {jo(capex_avg)}), 연구개발비는 {jo(rnd.get('total'))}로 평소 수준이었습니다 [공시·계산]. "
            f"같은 해 진행 중인 공사의 원가 추정 변경 효과가 {jo(e_e['current'])}였고 영업손실은 {jo(v.a(ey, 'operating_profit'))}였습니다. "
            "손실은 새 투자가 아니라 이미 수주한 공사의 원가 초과에서 나왔습니다 [해석]."), "warn")
    ib = R["interest_span"]
    ic = rs.interest_bridge(v, 2021, F["yl"]) if F["yl"] > 2021 else None
    int_pts = []
    if ib:
        txt = (f"이자비용은 {ib['start']}년 {eok(ib['int0'])} → {ib['end']}년 {josa(eok(ib['int1']), '으로')} {seok(ib['d_int'])} 늘었습니다. 10년 전체로는 차입 규모 효과가 "
               f"{seok(ib['volume_effect'])}, 금리 효과가 {seok(ib['rate_effect'])}입니다 [계산].")
        if ic:
            txt += (f" 금리가 오른 2021→{ic['end']}년만 보면 금리 효과 {seok(ic['rate_effect'])}, 차입 규모 효과 {josa(seok(ic['volume_effect']), '으로')} "
                    + ("금리 쪽이 조금 더 컸습니다" if ic["rate_effect"] > ic["volume_effect"] else "빌린 양 쪽이 더 컸습니다") + " [계산].")
        txt += (f" 다만 이자비용 자체가 {ib['end']}년 영업이익({jo(v.a(ib['end'], 'operating_profit'))})의 "
                f"{ib['int1'] / v.a(ib['end'], 'operating_profit') * 100:.0f}% 수준이라, 원가 추정 변경에 비하면 실적에 준 영향은 작았습니다 [계산·해석]."
                if v.a(ib["end"], "operating_profit") and v.a(ib["end"], "operating_profit") > 0 else "")
        int_pts.append(txt)
    cov = F["vd"].get("coverage")
    if cov is not None:
        int_pts.append(f"최근 4개 분기 이자보상배율은 {cov:.1f}배입니다. 1배를 넘어 영업이익으로 이자를 낼 수 있지만, 영업 현금이 마이너스인 동안에는 "
                       "이자를 현금으로 내기 위해 예금이나 차입이 필요합니다 [계산·해석].")
    if F["pf"]:
        p, r = F["pf"][-1]
        int_pts.append(f"PF 보증은 {rv.period_label(p)} {jo(r['amount'], 1)}" + (f"(자본의 {F['pf_x']:.1f}배)" if F["pf_x"] else "")
                       + "로 차입금보다 큽니다. 재무상태표에는 없지만 분양이 막히면 빚이 될 수 있는 금액입니다 [공시].")
    eval_pts = [
        "**예금 완충**: 2016~2021년의 보수적 현금 관리(예금 적립)는 이후 영업 현금 유출을 버티게 해 결과적으로 적절했습니다 [해석].",
        "**투자 규모**: 설비 투자와 연구개발비는 매출의 1% 안팎으로, 성장 투자가 재무를 압박한 상황은 아닙니다. 반대로 미래사업에 회사 돈을 크게 넣고 있지도 않습니다 [계산·해석].",
        "**주주환원**: 손실이 난 해에도 배당을 유지하고, 다음 해에는 밝힌 정책(최소 주당 800원)대로 늘렸습니다 [공시·보도]. 주주에게는 신호지만, "
        "영업 현금이 마이너스인 동안 배당은 예금 인출과 차입으로 낸 셈입니다 [계산·해석].",
        "**재무 부담**: 이자 부담은 아직 감당할 수준이지만 순현금이 순차입금으로 바뀌는 추세입니다. 영업 현금이 플러스로 돌아서야 부담이 멈춥니다 [해석].",
    ]
    body = (sub("8-1", "현금의 원천과 사용", alloc_fig(F) + alloc_table(F) + bullets(pts),
                "현금흐름표의 영업·투자·재무 칸을 성격별로 다시 묶었습니다. 모든 칸을 더하면 그해 현금 증감과 같습니다.")
            + sub("8-2", "어디에 썼나: 비용과 투자", spend_table(F) + check,
                  "연구개발비는 현금흐름표의 투자가 아니라 비용(손익계산서)으로 처리되므로 사업보고서 Ⅱ장 연구개발 활동에서 따로 읽었습니다 [공시].")
            + sub("8-3", "주주에게 돌려준 돈: 배당", dividend_table(F)
                  + para("회사는 2025년 3월 2025~2027년 총주주환원율 25% 이상과 최소 주당 배당금 800원(전년 600원)을 밝혔습니다 [보도]. "
                         "2025년 배당 증액은 이 정책에 따른 것입니다.")
                  + (f'<p class="r-src">출처: {src_links(F, ["etoday2025hroad"])}</p>' if src_links(F, ["etoday2025hroad"]) else ""),
                  "사업보고서 ‘배당에 관한 사항’ · 연결 지배주주 순이익 기준 배당성향 [공시].", keep=True)
            + sub("8-4", "재무 부담과 재무제표 밖의 의무", interest_table(F) + bullets(int_pts)
                  + f'<div class="r-2">{rv.pf_fig(ctx)}{st.bs_chart(F["v10"], F["years10"])}</div>')
            + sub("8-5", "평가: 자본배분은 적절했나", bullets(eval_pts), keep=True))
    lead = ("RQ4의 앞부분, **번 돈을 어디에 쓰고 있나**입니다. 10년 현금흐름표를 원천과 사용으로 나누면, 영업 현금이 플러스였던 시기와 마이너스로 바뀐 "
            "시기의 쓰임이 뚜렷하게 다릅니다.")
    return chapter("08", "Capital allocation", "현재: 번 돈을 어디에 썼나", lead, body, "ch8")


# ---------------------------------------------------------------------------
# 9장 미래: 성장사업과 시나리오
# ---------------------------------------------------------------------------
CHAIN = ("사업계획", "업무협약", "설계계약", "본계약", "공사", "매출", "이익", "현금")


def chain_states(g):
    """research.json의 단계(1~5)를 8칸 사슬(사업계획 → 업무협약 → 설계계약 → 본계약 → 공사 → 매출 → 이익 → 현금)로.
    done = 확인됨, now = 진행 중, todo = 아직, na = 해당 없음, unknown = 공시로 확인할 수 없음. g['chain']에 칸별 값을 적으면 그 값을 씁니다."""
    stage = g.get("stage") or 0
    n = len(CHAIN)
    if stage <= 3:
        states = ["done"] * stage + ["now"] + ["todo"] * (n - stage - 1)
    elif stage == 4:                       # 시공 중: 매출은 진행률로 인식 중, 현장 이익·대금 수령은 비공개
        states = ["done"] * 4 + ["now", "now", "unknown", "unknown"]
    else:                                  # 대금 회수·운영
        states = ["done"] * 6 + ["unknown", "now"]
    for name, val in (g.get("chain") or {}).items():
        if name in CHAIN:
            states[CHAIN.index(name)] = val
    return states


def chain_html(g):
    mark = {"done": ("●", "확인"), "now": ("◐", "진행 중"), "todo": ("○", "아직"), "na": ("–", "해당 없음"), "unknown": ("?", "공시 없음")}
    return ('<span class="chain">' + "".join(f'<i class="c-{s_}" title="{esc(n)}: {mark[s_][1]}">{mark[s_][0]}</i>' for n, s_ in zip(CHAIN, chain_states(g)))
            + "</span>")


def growth_table(F):
    revl = F["revl"]
    rows = []
    for g in F["RC"].get("growth") or []:
        amt = g.get("hd_amount")
        contrib = (f"확정 {jo(amt)} = {F['yl']}년 매출의 {amt / revl * 100:.0f}% [계산]" if amt and revl else "")
        rows.append([f'<b>{esc(g["name"])}</b><span class="r-q">{esc(g["area"])}</span>',
                     chain_html(g) + f'<span class="r-q">{tagify(g["status"])}</span>',
                     esc(g["form"]) + f'<span class="r-q">{tagify(g["amount"])}</span>',
                     tagify(g.get("invest", "–")),
                     esc(g["cash"]) + (f'<span class="r-q">회수: {tagify(g["recover"])}</span>' if g.get("recover") else ""),
                     esc(g["risk"]),
                     (tagify(contrib) + "<br>" if contrib else "") + tagify(g.get("value", "")),
                     src_links(F, g.get("src") or [], short=True)])
    legend = ('<p class="r-src">단계 사슬: ' + " → ".join(CHAIN) + " · ● 확인 ◐ 진행 중 ○ 아직 – 해당 없음 ? 공시로 확인할 수 없음"
              " (현장별 이익과 대금 수령은 공시되지 않아 시공 중인 사업도 ‘?’)</p>")
    return rtable(["사업", "어디까지 왔나", "현대건설 역할 · 확정 금액", "실제 투자와 성격", "매출·현금 시기 · 회수", "위험", "기여 판단 [해석]", "출처"],
                  rows, "r-grow") + legend


def roic_fig(F):
    v, years = F["v"], F["years"]
    roic = [v.a(y, "roic_pct") for y in years]
    br = [v.a(y, "borrowing_rate_pct") for y in years]

    def tips(i):
        y = years[i]
        return f"{y}년", [["ROIC", pct(roic[i]), "var(--s1)"], ["평균 차입 이자율", pct(br[i], 2), "var(--s2)"]], "ROIC = 세후 영업이익 ÷ 평균 투하자본"
    return fig("fig-roic", "투자한 돈으로 얼마나 버나: ROIC와 차입 이자율", "연결 · ROIC = 세후 영업이익 ÷ 평균(자본 + 순차입금) · 차입 이자율 = 이자비용 ÷ 평균 차입금",
               d.multi_line_chart(xlabels(years), [{"name": "ROIC", "values": roic, "color": "--s1"},
                                                   {"name": "차입 이자율", "values": br, "color": "--s2", "dash": True}],
                                  ticks_fmt=tick_pct, tips=tips, height=150, end_fmt=lambda x: pct(x)),
               legend_html=d.legend([("ROIC", "--s1", "box"), ("평균 차입 이자율", "--s2", "box")]))


def fcf_fig_r(F):
    v, years = F["v"], F["years"]
    fcf = [v.a(y, "fcf") for y in years]

    def tips(i):
        y = years[i]
        return f"{y}년", [["FCF", won(fcf[i]), "var(--s2)"], ["영업활동현금흐름", won(v.a(y, "operating_cashflow")), None],
                          ["설비투자", won(v.a(y, "capex")), None]], "FCF = 영업활동현금흐름 − 설비투자"
    return fig("fig-fcf-r", "잉여현금흐름(FCF)", "연결 · 영업활동현금흐름 − 설비투자 · 조 원",
               d.column_chart(xlabels(years), [{"values": d.in_jo(fcf), "color": "--s2"}], ticks_fmt=d.tick_jo, tips=tips, height=150, neg_zone=True))


def scenario_table(F):
    sc = F["R"]["scenarios"]
    rows = []
    for c in sc["cases"]:
        rows.append([f"<b>{esc(c['name'])}</b>", tagify(c["why"] + " [가정]"), num(" → ".join(an._m(f"{m:.1f}%") for m in c["margins"])),
                     num(jo(c["op_sum"]), c["op_sum"]), num(jo(c["ni_sum"]), c["ni_sum"]), num(jo(c["equity_end"], 1)), num(pct(c["de_end"], 0))])
    return rtable(["시나리오", "가정", "1~3년 차 영업이익률", "3년 누적 영업이익", f"세후(세율 {sc['tax'] * 100:.0f}% 가정)", "3년 뒤 자본", "3년 뒤 부채비율"],
                  rows, "r-scen")


def epc_grid(F):
    med = F["R"]["bases"]["base"]
    cols = [(-5.0, "−5%(손실 공사)"), (0.0, "0%(남는 것 없음)"), (med, f"{med:.1f}%(10년 중앙값)"), (8.0, "8%(회사 2030 목표)")]
    build_years = 8
    rows = []
    for size in (5, 10, 15):
        cells = []
        for m, _ in cols:
            tot = size * T * m / 100
            cells.append(num(f"{jo(tot)} · 연 {eok(tot / build_years)}", tot))
        rows.append([f"<b>{size}조 원</b>"] + cells)
    return rtable(["가상의 현대건설 몫 계약 [가정]"] + [esc(lab) for _, lab in cols], rows, "r-grid"), build_years


def stress_table(F):
    pj = [r for r in F["projects"] if r.get("region") == "해외" and r.get("remain")]
    bal = F["bal"]
    if not pj or not bal:
        return "", None
    rem = sum(r["remain"] for r in pj)
    eq = bal["values"]["equity"]
    opl = F["opl"]
    rows = []
    for rate in (3, 5, 10):
        loss = rem * rate / 100
        rows.append([f"<b>남은 공사의 원가가 {rate}% 더 들면</b>", num(jo(-loss), -loss), num(pct(loss / eq * 100)),
                     num(f"{loss / opl:.1f}배" if opl and opl > 0 else "–")])
    return rtable(["가정 [가정]", "추가 손실", f"자본({an.when_label(bal)}) 대비", f"{F['yl']}년 영업이익 대비"], rows, "r-stress"), (pj, rem)


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


def ch9_future(ctx, F):
    R, RC, v = F["R"], F["RC"], F["v"]
    growth = RC.get("growth") or []
    by_stage = {}
    for g in growth:
        by_stage[g["stage"]] = by_stage.get(g["stage"], 0) + 1
    early = sum(n for s, n in by_stage.items() if s <= 2)
    building = by_stage.get(4, 0)
    done = by_stage.get(5, 0)
    grow_pts = [
        f"조사한 미래사업 {len(growth)}건 중 **{early}건은 본계약 전(업무협약·설계계약 단계)**이고, 시공 중인 것은 {building}건입니다. "
        + (f"운영·회수 단계에 이른 사업은 {done}건입니다 [보도·공시]." if done else "운영·회수 단계에 이른 사업은 아직 없습니다 [보도·공시]."),
        "대형 원전(불가리아·미국 페르미)과 SMR(팰리세이즈)은 **EPC 본계약 전**이라 재무제표에 매출·이익으로 나타나지 않았고, 계약 금액도 확정되지 않았습니다. "
        "보도된 사업비는 사업 전체 금액이지 현대건설의 매출이 아닙니다 [보도·해석].",
        "사업 형태는 대부분 **지분을 넣지 않는 EPC(설계·조달·시공)**입니다. 자본 부담은 작지만, 고정가격 EPC는 2024년 손실과 같은 유형의 원가 초과 위험을 "
        "그대로 집니다 [해석].",
        "회사가 직접 돈을 넣는 사업은 작습니다: 수소 투자 계획 2033년까지 약 240억 원 [공시], 미국 태양광(LUCY) 지분 투자(지분율 비공개) [공시], "
        "2026년 5,000억 원 전환사채 발행 결정(원전·SMR 등 에너지 투자 재원) [보도].",
        "**NPV·IRR은 계산하지 않았습니다.** 어느 사업도 현대건설 몫의 계약금액·예상 원가율·대금 수령 일정이 함께 공개되지 않았고, 시공 중인 사업도 현장별 이익률이 "
        "비공개입니다. 계산하려면 ① 현대건설 몫 계약금액 ② 예상 원가율 ③ 기성·선수금 일정 ④ 할인율(자본비용)이 필요합니다 [해석].",
        "매출이 늘어나는 것이 곧 주주가치는 아닙니다. 이익률이 자본비용보다 높고 그 이익이 현금으로 회수될 때만 가치가 생깁니다(9-2 ROIC, 6-4 현금) [해석].",
    ]
    # ROIC · FCF
    years = F["years"]
    below = [y for y in years if v.a(y, "roic_pct") is not None and v.a(y, "borrowing_rate_pct") is not None and v.a(y, "roic_pct") < v.a(y, "borrowing_rate_pct")]
    fcf_s = window_sum(F, "fcf", F["neg_start"], F["yl"]) if F["neg_start"] else None
    roic_pts = [
        f"ROIC는 {years[0]}년 {pct(v.a(years[0], 'roic_pct'))}에서 {F['yl']}년 {pct(v.a(F['yl'], 'roic_pct'))}로 낮아졌습니다 [계산]."
        + (f" 차입 이자율보다 낮았던 해는 {', '.join(map(str, below))}년입니다." if below else ""),
        "차입 이자율은 투자에 드는 비용의 최소선입니다. 주주가 요구하는 수익률(자본비용)은 이보다 높으므로, ROIC가 차입 이자율 근처라면 가치를 거의 "
        "만들지 못하고 있다는 뜻입니다 [해석].",
        (f"FCF는 {F['neg_start']}~{F['yl']}년 합계 {jo(fcf_s)}입니다. 미래사업에 투자할 돈을 영업이 아니라 예금·차입·사채에서 마련해야 하는 상황입니다 [계산·해석]."
         if fcf_s is not None else ""),
    ]
    sc = R["scenarios"]
    scen_note = (f"매출은 최근 4개 분기 {jo(sc['revenue'], 1)}가 3년 동안 유지된다고 놓았습니다(수주잔고가 3년 치 넘게 있어 매출 규모의 근거가 됨). "
                 "영업이익률만 바꾸고, 영업외손익·배당·비지배지분 몫은 빼고, 부채는 지금 그대로라고 가정한 산수입니다. 예측이 아닙니다 [가정].")
    base = next((c for c in sc["cases"] if c["name"] == "기준"), None)
    bad = next((c for c in sc["cases"] if c["name"] == "비관"), None)
    scen_pts = []
    if base and bad:
        scen_pts.append(f"{sc['shock_year']}년 같은 해가 한 번 더 오면 3년 누적 영업이익은 기준({jo(base['op_sum'])})의 {bad['op_sum'] / base['op_sum'] * 100:.0f}% 수준으로 줄어듭니다. "
                        "같은 일감에서 이익률 몇 %p가 3년 결과를 몇 배로 가릅니다 [가정·계산].")
    grid, by = epc_grid(F)
    grid_note = (f"원전 EPC 계약 금액은 확정되지 않았으므로 가상의 계약 규모로 계산했습니다. 공사 기간 {by}년에 고르게 나눈다고 가정합니다 [가정]. "
                 f"비교: {F['yl']}년 연결 영업이익 {jo(F['opl'])} [공시].")
    stress, info = stress_table(F)
    stress_note = ""
    if info:
        pj, rem = info
        w = F["est_worst"]
        stress_note = (f"진행 중인 해외 큰 공사 {len(pj)}건(사업보고서 ‘수주상황’ 표의 상위 공사)의 남은 공사 금액 {jo(rem, 1)}에 원가 초과율을 곱한 근사치입니다 [가정]. "
                       + (f"비교: {w['year']}년 원가 추정 변경 효과는 그해 매출의 {abs(w['pct_rev']):.1f}%였습니다 [계산]." if w and w.get("pct_rev") else ""))
    price = next((x for x in F["L"] if x["id"] == "price"), None)
    direction = ""
    if price:
        _, _, same, total = st.price_direction(price, F["years10"])
        if total:
            direction = (f"계산할 수 있는 {total}년 중 **{same}년**은 연말 주가와 영업이익이 같은 방향으로 움직였습니다. 주가는 실적보다 기대를 먼저 반영하므로, "
                         "원전 기대처럼 실적에 아직 없는 이야기가 주가에 먼저 들어가 있을 수 있습니다 [계산·해석].")
    body = (sub("9-1", "미래사업은 어디까지 왔나", growth_table(F) + bullets(grow_pts),
                f"사업계획 → 업무협약 → 설계계약 → 본계약 → 공사 → 매출 → 이익 → 현금의 어느 칸까지 확인되는지입니다. 본계약부터 수주잔고, 공사부터 매출이 되고, "
                f"이익과 현금은 현장별로 공시되지 않습니다. 단계와 상태는 {RC.get('as_of', '–')}까지 공개된 공시·보도로 조사했습니다.")
            + sub("9-2", "투자의 가치: ROIC와 잉여현금흐름", f'<div class="r-2">{roic_fig(F)}{fcf_fig_r(F)}</div>' + bullets(roic_pts))
            + sub("9-3", "시나리오: 이익률이 바뀌면 3년 뒤는", scenario_table(F) + para(scen_note, "r-src") + bullets(scen_pts), keep=True)
            + sub("9-4", "원전 EPC를 따내면: 가상의 계산", grid + para(grid_note, "r-src")
                  + bullets(["같은 10조 원 계약이라도 이익률이 −5%면 0.5조 원 손실, 8%면 0.8조 원 이익입니다. 미래사업의 가치는 ‘따내는가’보다 ‘어떤 조건으로 따내는가’"
                             "(원가 상승을 누가 떠안는지)에 달려 있습니다 [해석]."]), keep=True)
            + sub("9-5", "실패하면: 진행 중인 해외 공사의 원가 스트레스", (stress + para(stress_note, "r-src")) if stress else "", keep=True)
            + sub("9-6", "시장의 평가와 경쟁사", d.valuation_tiles(ctx) + st.price_fig(ctx, F["years10"][0], fid="fig-price-report")
                  + para(direction) + peers_table(ctx)))
    lead = ("RQ4의 뒷부분, **지금의 투자는 어떤 가치와 위험을 갖는가**입니다. 확인된 사실(공시)과 계약 전의 기대(보도), 가정을 둔 계산을 나눠 적습니다.")
    return chapter("09", "Growth & scenarios", "미래: 성장사업과 시나리오", lead, body, "ch9")


# ---------------------------------------------------------------------------
# 10장 종합 평가
# ---------------------------------------------------------------------------
def strength_risk(ctx, F):
    v, vd, bal = F["v"], F["vd"], F["bal"]
    good, risk = [], []
    lb, yrs = F["lb"], F["yrs"]
    if lb and yrs and yrs >= 2.5:
        good.append(f"**일감**: 수주잔고 {jo(lb['total'], 1)}, 매출 {yrs:.1f}년 치 [공시·계산].")
    rank = ctx["company"].get("rank") or {}
    if rank.get("own") and rank["own"] <= 3:
        good.append(f"**체급**: {rank.get('year')}년 시공능력평가 {rank['own']}위 — 공공공사·정비사업 입찰과 보증에 유리 [보도].")
    sep_ok = [r for r in F["R"]["entity"] if r.get("parent_op") is not None and r["parent_op"] > 0]
    if sep_ok:
        good.append(f"**본사 체력**: 현대건설 본사(별도)는 {len(F['R']['entity'])}년 중 {len(sep_ok)}년 영업이익 흑자였습니다 [공시].")
    if bal and (bal["ratios"].get("current_ratio_pct") or 0) > 100:
        good.append(f"**유동성**: {an.when_label(bal)} 유동비율 {pct(bal['ratios']['current_ratio_pct'], 0)} [계산].")
    if vd.get("coverage") and vd["coverage"] > 3:
        good.append(f"**이자 감당**: 최근 4개 분기 이자보상배율 {vd['coverage']:.1f}배 [계산].")
    run = 0
    lows = peer_gap_years(F)
    for y in reversed(F["years"]):
        if y in lows:
            run += 1
        else:
            break
    if run >= 2:
        risk.append(f"**낮은 이익률**: 영업이익률이 {run}년 연속 동종사 중앙값보다 낮았습니다 [계산].")
    if (vd.get("streak") or 0) >= 2:
        risk.append(f"**현금 회수**: 영업활동현금흐름 {vd['streak']}년 연속 마이너스" + (f", 받을 돈 {jo(bal['values'].get('receivables_total'), 1)}" if bal else "") + " [공시].")
    big = [r for r in F["projects"] if r.get("region") == "해외" and r["contract"] >= T and r["done"] / r["contract"] < 0.10]
    if big:
        risk.append("**해외 고정가격 EPC**: " + ", ".join(r["name"] for r in big[:3]) + f" 등 {jo(sum(r['contract'] for r in big), 1)}가 진행률 10% 미만입니다 [공시].")
    if F["pf"]:
        risk.append(f"**PF 보증**: {jo(F['pf'][-1][1]['amount'], 1)}" + (f", 자본의 {F['pf_x']:.1f}배" if F["pf_x"] else "") + " [공시].")
    risk.append("**미래사업의 불확실성**: 원전·SMR은 본계약 전이며 계약 조건(위험 분담)이 정해지지 않았습니다 [보도].")
    return good, risk


def watch_rows(ctx, F):
    v, bal = F["v"], F["bal"]
    yl = F["yl"]
    rows = [["원가 추정 변경 효과", f"{yl}년 {jo((F['est'].get(yl) or {}).get('current'))}", "Ⅲ 건설계약 주석", "마이너스가 평상시(2016~2021 평균) 수준으로 줄어드는지"],
            ["현대엔지니어링 영업이익", f"{yl}년 {jo((F['ent'].get(yl) or {}).get('hec_op'))}", "Ⅲ 종속기업(비지배지분) 주석", "흑자가 이어지는지"],
            ["원가율", f"{yl}년 {pct(v.a(yl, 'cost_ratio_pct'))}", "Ⅲ 손익계산서 · 영업부문 주석", "낮아질수록 좋음(부문별 매출총이익률)"],
            ["영업활동현금흐름", f"{yl}년 {jo(v.a(yl, 'operating_cashflow'))}", "Ⅲ 현금흐름표", "플러스로 돌아서는지"]]
    if bal and bal["values"].get("receivables_total"):
        rows.append(["받을 돈(매출채권+계약자산)", f"{an.when_label(bal)} {jo(bal['values']['receivables_total'], 1)}", "Ⅲ 재무상태표", "매출보다 느리게 늘거나 줄어드는지"])
    rl = F["recv_by"].get(yl) or {}
    if rl.get("over_1y") is not None:
        rows.append(["1년 넘은 매출채권 · 손상차손누계액", f"{yl}년 말 {jo(rl['over_1y'])} · {jo(-rl['allowance'])}", "Ⅲ 매출채권 주석(연령분석)",
                     "줄어드는지(회수 진행) — 손상이 더 늘면 회수 가능성이 낮아지는 신호"])
    if F["pf"]:
        p, r = F["pf"][-1]
        rows.append(["PF 보증", f"{rv.period_label(p)} {jo(r['amount'], 1)}", "Ⅺ 우발부채 등", "자본 대비 배수가 줄어드는지"])
    rows.append(["원전·SMR 본계약", "미체결(조사 기준일)", "주요사항보고·Ⅱ 수주상황", "계약 금액과 위험 분담 조건"])
    return [[esc(a), f"<b>{esc(b)}</b>", esc(c), esc(e)] for a, b, c, e in rows]


def ch10_conclusion(ctx, F):
    RC, R, v = F["RC"], F["R"], F["v"]
    quote = f'<blockquote class="r-quote small">{esc(RC.get("user_view", ""))}</blockquote>'
    rewrite = ("**고쳐 쓴 문장**: 건설사의 성장은 매출이 아니라 ① 원가를 정확히 추정해 이익을 남기고 ② 그 이익을 제때 현금으로 회수하며 "
               "③ 재무제표 밖의 의무까지 통제할 때 이어진다. 현대건설의 지난 10년에서는 **①이 이익을 가장 크게 움직였고, 2022년 이후에는 ②가 가장 시급한 문제**가 "
               "됐다. ③은 노출은 크지만 아직 손실로 확인되지 않았다 [해석].")
    ppf_rows = []
    b = R["bridge_10y"]
    bal = F["bal"]
    if b:
        ppf_rows.append(["<b>과거</b>", "얼마나 벌었고 왜 변했나", '<span class="r-chip warn">매출 성장 · 이익률 하락</span>',
                         tagify(f"매출 {b['rev1'] / b['rev0']:.2f}배, 영업이익률 {pct(F['m0'])} → {pct(F['ml'])}; 원가율 효과 {sjo(b['cost'])} [계산]")])
    if bal:
        nd = bal["values"].get("net_debt")
        ppf_rows.append(["<b>현재</b>", "번 돈은 어디로, 부담은 적절한가", '<span class="r-chip warn">현금 부족을 예금·차입으로 메움</span>',
                         tagify(f"영업 현금 {F['streak']}년 연속 마이너스, {an.when_label(bal)} " + (f"순차입금 {jo(nd)}" if nd is not None and nd > 0 else f"순현금 {jo(-nd) if nd is not None else '–'}")
                                + f", 부채비율 {pct(bal['ratios'].get('debt_to_equity_pct'), 0)} [계산]")])
    ppf_rows.append(["<b>미래</b>", "지금의 투자는 가치를 만들까", '<span class="r-chip info">일감은 충분 · 전환 사업은 초기</span>',
                     tagify(f"잔고 {jo(F['lb']['total'], 1)}(매출 {F['yrs']:.1f}년 치) [공시·계산]; 원전·SMR은 본계약 전 [보도]; 목표 이익률 8%는 지난 10년 최고치("
                            f"{pct(max(v.a(y, 'operating_margin_pct') for y in F['years']))})보다 높음 [계산]" if F["lb"] and F["yrs"] else "–")])
    ppf = rtable(["시점", "질문", "평가", "핵심 근거"], ppf_rows, "r-ppf2")
    good, risk = strength_risk(ctx, F)
    cols = f'<div class="r-2">{box("강점", bullets(good), "good")}{box("약점과 위험", bullets(risk), "crit")}</div>'
    best = max(F["years"], key=lambda y: v.a(y, "operating_margin_pct") or -99)
    roe_best = max(F["years"], key=lambda y: v.a(y, "roe_pct") or -99)
    cagr = ((40 * T / F["revl"]) ** (1 / (2030 - F["yl"])) - 1) * 100 if F["revl"] and 2030 > F["yl"] else None
    strat = [
        "**회사가 밝힌 2030년 목표**: 수주·매출 각 40조 원 이상, 영업이익률 8% 이상, ROE 12% 이상(2025년 3월 CEO 인베스터데이) [보도].",
        (f"**매출 목표**는 {F['yl']}년 {jo(F['revl'], 1)}에서 해마다 {cagr:.1f}% 늘면 닿는 숫자로, 수주잔고({F['yrs']:.1f}년 치)를 보면 무리한 규모는 아닙니다 [계산·해석]."
         if cagr is not None and F["yrs"] else ""),
        f"**수익성 목표**: 지난 10년 영업이익률 최고치는 {best}년 {pct(v.a(best, 'operating_margin_pct'))}, ROE 최고치는 {roe_best}년 {pct(v.a(roe_best, 'roe_pct'))}였습니다. "
        "두 목표 모두 과거 어느 해보다 높아, 원가 추정·계약 조건 관리 방식이 바뀌어야 가능한 숫자입니다 [계산·해석].",
        "**에너지 전환(원전·SMR·신재생)**: 방향은 일감의 질을 바꿀 수 있지만, 지금은 대부분 설계·사전업무 단계입니다. 본계약에서 원가 상승을 발주처와 나누는 "
        "조건을 확보하는지가 2024년 같은 손실을 피하는 열쇠입니다 [해석].",
        "**자본 전략**: 회사 돈을 크게 넣지 않는 EPC 중심이라 재무 부담은 작지만, 영업 현금이 마이너스인 동안 투자 재원은 사채·전환사채에 기대게 됩니다 [보도·해석].",
    ]
    watch = rtable(["다음 공시에서 볼 숫자", "지금", "사업보고서의 어디", "좋아지는 신호"], watch_rows(ctx, F), "r-watch")
    body = (sub("10-1", "처음 생각은 맞았나: 가설 검증", quote + hypothesis_table(ctx, F) + box("", para(rewrite), "plain"),
                "‘증거 판정’은 자료의 상태이고 ‘분석자 평가’는 그 위의 판단입니다. 가설이 자료와 맞는다는 것과 그 원인이 증명됐다는 것은 다릅니다 [해석].")
            + sub("10-2", "과거 · 현재 · 미래 평가", ppf, keep=True)
            + sub("10-3", "강점과 위험", cols, "미리 정한 조건(일감 2.5년 치 이상, 동종사 중앙값과 비교 등)에 맞을 때만 자동으로 나타납니다.")
            + sub("10-4", "회사 전략에 대한 평가", bullets(strat), keep=True)
            + sub("10-5", "다음 공시에서 확인할 숫자", watch,
                  "숫자는 새 공시가 나오면 자동으로 다시 계산됩니다. 연표와 미래사업 단계는 사람이 조사해 고치는 부분이라 조사 기준일 뒤의 사건은 ‘조사 전’으로 표시됩니다.",
                  keep=True))
    lead = "1장의 문제의식으로 돌아가, 자료가 무엇을 확인했고 무엇을 확인하지 못했는지 정리합니다."
    return chapter("10", "Conclusion", "종합 평가", lead, body, "ch10")


# ---------------------------------------------------------------------------
# 부록
# ---------------------------------------------------------------------------
FORMULAS = [
    ("영업이익 변화 나누기(6-1)", "ΔOP = ΔR × (m₀+m₁)/2 + (−Δ원가율) × (R₀+R₁)/2 + (−Δ판관비율) × (R₀+R₁)/2 + 기타",
     "R = 매출, m = 영업이익률. 두 해 평균을 써서 계산 순서에 따라 달라지지 않음. 앞 해 기준(ΔR×m₀, 비율×R₁)·뒤 해 기준(ΔR×m₁, 비율×R₀)은 6-1 표. 기타는 현대건설에서 0"),
    ("원가율 효과의 몫(6-1)", "Σ|원가율 효과| ÷ Σ(|규모| + |원가율| + |판관비율| + |기타|) — 연도별 분해의 절댓값 합", "변화의 크기를 누가 만들었는지(방향은 담지 않음)"),
    ("원가 추정 변경(6-2)", "총계약수익 변경 − 총계약원가 변경 = 그해 손익 영향 + 미래 손익 영향(= 공사 전체 이익 변화)", "회사 공시 표의 항등식(해마다 차이 0). 그해 영향의 여러 해 합은 누적 손실이 아님"),
    ("영업활동현금흐름 나누기(6-4)", "CFO = 당기순이익 + 비현금 조정 + 운전자본 변동 + 이자·배당 수취 − 이자 지급 − 법인세 납부",
     "앞 세 항은 현금흐름표 주석 ‘영업으로부터 창출된 현금’, 뒤는 현금흐름표 본문. 해마다 재무제표의 CFO와 차이 0"),
    ("받을 돈의 규모·비율 분해(6-4)", "ΔS = ΔR × (k₀+k₁)/2 + Δk × (R₀+R₁)/2 , k = 잔액 ÷ 매출", "규모 효과 = 매출이 커진 몫, 비율 효과 = 매출 대비 잔액 비율이 바뀐 몫(회수·청구 조건)"),
    ("회사별 나누기(4-3)", "연결 영업이익 = 본사(별도) + 현대엔지니어링 + 나머지", "현대엔지니어링은 비지배지분 주석의 요약 재무정보(내부거래 제거 전), 나머지는 차이"),
    ("이자비용 나누기(8-4)", "ΔI = (r₁ − r₀) × D₁ + r₀ × (D₁ − D₀)", "r = 이자비용 ÷ 평균 차입금, D = 평균 차입금. 앞은 금리 효과, 뒤는 차입 규모 효과"),
    ("민감도(요약 RQ2)", "원가율 1%p = 매출 × 1% · 매출 10% = 매출 × 10% × 영업이익률",
     "금리 1%p·환율 10%는 회사가 위험관리 주석에 공시한 숫자(금리: 변동금리 차입금의 세전이익 영향, 환율: 외화 화폐성 항목 환산의 순자산(세전) 영향)"),
    ("시나리오(9-3)", "영업이익 = 최근 4개 분기 매출 × 가정 이익률 · 자본 = 지금 자본 + 영업이익 × (1 − 24%)", "영업외손익·배당·비지배지분은 빼고, 부채는 그대로"),
    ("조기 경보(5-4)", "사건 2년 전과 1년 전 값이 모두 평상시(2016~2020 평균)보다 나쁜 쪽이면 ‘미리 나빠짐’", "사례가 하나라 일반화하지 않음"),
    ("변화의 성격(7-1)", "|Δ현대| < 0.5%p → 큰 변화 없음 · 같은 방향이고 |Δ동종사| ≥ |Δ현대| × 0.5 → 업계 공통 · 그 밖 → 회사 고유", "영업이익률, 동종사는 삼성물산 제외 중앙값"),
    ("가설의 증거 판정(요약)", "H1: 규모 효과 > 0, 영업이익 변화 < 규모 효과, 다른 방법·기간도 같은 순서 → 관측 자료와 일치 · H2·H3: 회사 공시 주석이 직접 보여 줌 → 공시자료가 직접 뒷받침 · "
     "H4: 대형 손실은 확인, PF 손실은 미확인 → 일부 근거만 확보 · H5: 다른 산업 비교 없음 → 확인할 자료 부족",
     "증거 판정은 자료의 상태, ‘분석자 평가’는 그 위의 판단으로 따로 적음. 반대 방향 자료가 가설을 뒤집으면 ‘반대되는 근거 발견’"),
    ("재무항목의 쓰임(5-1)", "핵심 = 결론을 직접 바꾸는 항목 · 보조 = 핵심의 원인·결과를 설명 · 참고 = 단독으로 쓰면 오해하기 쉬운 항목", "분석자 판단 — 점수·순위가 아님"),
]
READ_ITEMS = [("재무제표(손익·재무상태·현금흐름)", "Ⅲ 재무에 관한 사항", "OpenDART 재무제표 API(연결) · 2010~2015년은 원문 표"),
              ("부문별 매출·매출총이익 · 지역별 매출", "Ⅲ 연결재무제표 주석 ‘영업부문’", "부문 합계가 연결 매출과 0.5% 안에서 맞을 때만 사용"),
              ("원가 추정 변경 효과 · 공사손실충당부채", "Ⅲ 주석 ‘건설계약’(추정총계약원가 변경)", "연결·별도 표를 장 제목으로 구분"),
              ("현대엔지니어링 요약 실적", "Ⅲ 주석 ‘종속기업’(비지배지분 요약 재무정보)", "매출·영업이익·순이익·영업활동현금흐름"),
              ("금리·환율 민감도", "Ⅲ 주석 ‘위험관리’", "금리: 세전이익, 환율: 순자산(세전) 영향 — 원문 문구와 범위를 함께 저장"),
              ("영업으로부터 창출된 현금(순이익·조정·운전자본)", "Ⅲ 연결 주석 ‘현금흐름표’", "구성 합 = 표의 합계 = 소계일 때만 사용(2017년 보고서부터)"),
              ("매출채권 연령분석 · 공사미수금/분양미수금", "Ⅲ 연결 주석 ‘매출채권’", "구간 합 + 손상차손 = 장부금액일 때만 사용"),
              ("수익의 구분(도급공사·분양공사)", "Ⅲ 연결 주석 ‘건설계약’", "칸 합 = 소계일 때만(2025년 보고서부터의 표)"),
              ("현금흐름 세부(예금·대여금·배당·차입)", "Ⅲ 연결 현금흐름표(API 세부 계정)", "부호 규칙을 해마다 확인"),
              ("수주잔고 · 공사별 진행 · 신규 수주", "Ⅱ 사업의 내용 > 매출 및 수주상황", "회사별 계약잔액 합계, 공사별 계약금액·완성·잔액"),
              ("자재 가격 · 국내 건설시장 · 연구개발비 · 배당", "Ⅱ 사업의 내용 · Ⅲ 배당에 관한 사항", "표와 문장"),
              ("경영진단 문장", "Ⅳ 이사의 경영진단 및 분석의견", "연결 실적과 금액이 맞는 문장만"),
              ("PF 보증", "Ⅺ 그 밖에 투자자 보호 > 우발부채 등", "보증금액 기준 신용보강 문장"),
              ("단독 매출·영업이익 · 직원 수", "Ⅲ 요약재무정보(별도) · Ⅷ 임원 및 직원", "본사 실적, 1인당 생산성")]
AUTO_ROWS = [("재무제표 숫자 · 비율 · 그래프 · 숫자로 쓴 문장", "매월 1일 자동", "새 공시가 없으면 같은 숫자"),
             ("주석에서 읽는 숫자(부문 · 원가 추정 변경 · 현대엔지니어링 · 민감도 · 현금흐름 주석 · 매출채권)", "새 사업보고서가 나오면 자동", "읽은 값은 data/financials/drivers.json에 쌓임"),
             ("가설 판정 · 변화의 성격 · 조기 경보 · 시나리오 · 강점과 위험", "매월 자동(규칙은 부록 A)", "숫자가 바뀌면 판정도 바뀜"),
             ("연도별 사건 · 정책 · 경쟁사 사건 · 미래사업 단계 · 사업 유형 설명", "사람이 config/research.json을 고침", "조사 기준일 뒤의 새 연도는 ‘조사 전’ 표시"),
             ("재무항목의 쓰임 · 증거 판정 기준 · 해석 문장", "사람이 판단(규칙은 부록 A)", "근거 숫자는 자동"),
             ("조사 기준일 뒤에 접수된 새 공시", "자동 표시", "표지·요약에 ‘추가 검토 필요’ — 숫자는 반영되지만 분석자의 해석 문장·연표는 사람이 다시 확인"),
             ("새로운 원인 주장·예측", "만들지 않음", "자동 갱신은 숫자와 정해진 규칙의 판정만 바꿈")]
GLOSSARY = [
    ("수주 · 수주잔고", "발주처와 공사 계약을 맺는 것, 그리고 계약했지만 아직 짓지 않은 금액(앞으로 매출이 될 일감)."),
    ("진행기준", "공사가 끝날 때가 아니라 진행한 만큼(보통 쓴 원가 ÷ 총예정원가) 매출을 잡는 방법(K-IFRS 1115호)."),
    ("원가 추정 변경", "진행 중인 공사의 총예정원가·계약금액 추정을 바꾼 것. 바뀐 만큼 그해 손익이 한꺼번에 변합니다."),
    ("공사손실충당부채", "끝까지 지으면 손실이 날 공사의 앞으로의 손실을 미리 비용으로 잡아 둔 부채."),
    ("원가율 · 판관비율", "매출원가 ÷ 매출, 판매비와관리비 ÷ 매출. 영업이익률 = 1 − 원가율 − 판관비율."),
    ("계약자산(미청구공사)", "공사는 했지만 아직 청구하지 못한 금액. 늘면 현금이 늦게 들어옵니다."),
    ("계약부채(초과청구) · 선수금", "공사보다 먼저 받은 돈. 돈 대신 공사로 갚는 부채입니다."),
    ("연결 · 별도", "연결 = 현대건설 + 종속회사(현대엔지니어링 등), 별도 = 현대건설 본사 단독."),
    ("비지배지분", "연결 종속회사의 다른 주주 몫. 현대엔지니어링 손익의 약 60%가 여기에 갑니다(유효지분 40.47%)."),
    ("PF 보증 · 책임준공", "시행사·조합의 프로젝트파이낸싱 대출에 선 보증, 그리고 끝까지 짓겠다는 약정. 재무제표 밖의 의무입니다."),
    ("EPC · ESC · EWA", "설계·조달·시공 일괄 계약, 그 전 단계의 설계(조기업무) 계약, 사전업무착수계약."),
    ("영업활동현금흐름 · FCF", "본업으로 실제 들어오고 나간 현금, 그리고 거기서 설비투자를 뺀 잉여현금흐름."),
    ("EBITDA", "영업이익 + 감가상각비. 설비가 적은 건설사는 영업이익과 차이가 작습니다."),
    ("ROE · ROIC", "순이익 ÷ 평균 자본, 세후 영업이익 ÷ 평균 투하자본(자본 + 순차입금)."),
    ("이자보상배율 · 순차입금", "영업이익 ÷ 이자비용, 이자가 붙는 차입금 − 현금(마이너스면 순현금)."),
    ("PER · PBR", "시가총액 ÷ 순이익, 시가총액 ÷ 순자산. 시장이 회사를 이익·장부가치의 몇 배로 보는지."),
    ("시공능력평가", "국토교통부가 해마다 실적·재무·기술·신인도로 매기는 건설사 체급."),
]
DISCLAIMER = ("대학 수업 과제로 공시 숫자를 자동 정리하고 사건을 조사한 교육용 자료이며, 특정 주식의 매수·매도를 권하는 투자 조언이 아닙니다. "
              "숫자는 공시 원문과 다를 수 있으니 중요한 판단에는 DART 원문을 확인하세요.")
LIMITS = [
    "재무 숫자는 연결재무제표 기준이고 당기순이익은 비지배지분 몫을 포함합니다. ‘본사’는 현대건설 별도재무제표입니다.",
    "부문별 영업이익은 공시되지 않아 매출총이익까지만 나눴습니다. 공사별 손익도 공시되지 않습니다.",
    "현대엔지니어링 숫자는 비지배지분 주석의 요약 재무정보(내부거래 제거 전)라 연결 숫자와 단순 합이 맞지 않으며, 그 차이는 ‘나머지’에 들어갑니다.",
    "연간 관측치가 10개뿐이라 외부 요인(금리·유가·정책)과 실적의 상관계수를 내지 않았습니다. 인과는 회계 항등식과 회사 공시로 확인되는 것만 ‘확인’이라 적었습니다.",
    "동종사 비교는 사업 구성이 달라 한계가 있습니다. 삼성물산은 비건설 사업을 함께 연결해 중앙값에서 뺐습니다.",
    "PF 보증은 2023년 사업보고서부터 정비사업 PF를 포함하는 기준이라 그 전과 비교하지 않습니다.",
    "2026년 1분기부터 투자부동산·토지 회계정책이 바뀌어 자본·부채비율은 그 전과 기준이 다릅니다.",
    "주가는 달마다 마지막 거래일 종가(네이버 금융, 실패하면 Yahoo Finance)이고 2021년 이전은 수정주가입니다.",
    "현금흐름표 주석은 계정별 금액만 있어, 회수가 늦은 현장·발주처와 그 이유(분쟁·조합 분양·계약 조건)는 나눌 수 없습니다. 매출채권 연령 구간 이름은 보고서마다 달라 1년 초과 구간으로 비교합니다.",
    "원가 추정 변경의 원인별(자재·공기·설계변경) 금액과 현장별 손익은 공시되지 않습니다.",
    "미래사업은 현대건설 몫의 계약금액·원가·대금 일정이 공개되지 않아 NPV·IRR을 계산하지 않았습니다.",
]


def shown_value(r):
    """검증표의 '보고서 표시' — 본문과 같은 함수로 적습니다(fmt: jo · jo1 · sjo · seok · pct · won)."""
    x = r["value"]
    if x is None:
        return "–"
    f = r.get("fmt") or "jo"
    if f == "pct":
        return pct(x, 0)
    if f == "won":
        return f"{x:,}원"
    if f == "seok":
        return seok(x)
    if f == "sjo":
        return sjo(x)
    if f == "jo1":
        return jo(x, 1)
    return jo(x)


def verification_table(F):
    rows = []
    for r in F["R"].get("verification") or []:
        src = r["sources"]
        links = [dart_link(rc_, f"{name or rc_} · {d.fmt_date(dt)}" if dt else (name or rc_)) for rc_, name, dt in src[:2]]
        more = f" 외 {len(src) - 2}건" if len(src) > 2 else ""
        rows.append([esc(r["item"]), num(shown_value(r), r["value"] if r["unit"] == "원" else None),
                     f'<span class="r-chip {"good" if r["kind"] == "공시" else "info"}">{esc(r["kind"])}</span>', esc(r["basis"]),
                     esc(r["original"] or "–"), (" · ".join(links) + esc(more)) if links else "–", esc(r["method"])])
    return rtable(["숫자", "보고서 표시", "구분", "기준", "원문 값(단위)", "출처(보고서 · 접수일)", "계산 방법"], rows, "r-verify")


def appendix(ctx, F):
    formulas = rtable(["계산", "공식 · 규칙", "설명"], [[f"<b>{esc(a)}</b>", esc(b), esc(c)] for a, b, c in FORMULAS], "r-formula")
    rules = bullets(F["a"].get("rules", []), "small")
    read = rtable(["자동으로 읽는 숫자", "사업보고서의 위치", "방법"], [[esc(a), esc(b), esc(c)] for a, b, c in READ_ITEMS], "r-read")
    chap = "".join(f'<li class="{"on" if on else ""}"><span class="cn">{esc(no)}</span><span><b>{esc(t)}</b> {esc(w)}</span></li>'
                   for no, t, w, on in rv.CHAPTERS)
    lf = ctx.get("latest_filing")
    chap_box = box("사업보고서 한 권의 구조", f'<ol class="r-chapters">{chap}</ol>'
                   f'<p class="r-src">진하게 표시한 장을 이 보고서가 자동으로 읽습니다'
                   + (f" · 최근 보고서: {dart_link(lf['rcept_no'], lf['report_nm'].strip())}" if lf else "") + "</p>", "r-chbox")
    auto = rtable(["내용", "갱신", "비고"], [[esc(a), f"<b>{esc(b)}</b>", esc(c)] for a, b, c in AUTO_ROWS], "r-auto")
    gl = "".join(f"<div><dt>{esc(a)}</dt><dd>{esc(b)}</dd></div>" for a, b in GLOSSARY)
    srcs = F["RC"].get("sources") or {}
    src_items = [link(u, n) for n, u in srcs.values()]
    refs = [link(url, name) for name, url in rv.REFS.values()] + [link(url, name) for name, url in an.SOURCES.values()]
    cfg = ctx["company"]
    body = (sub("A", "방법과 공식", formulas + '<p class="r-subnote r-rules-h"><b>교수님 가이드 6단계 판정 규칙</b></p>' + rules)
            + sub("B", "자료 · 한계 · 자동 갱신 범위", chap_box + read + auto + bullets(LIMITS + [DISCLAIMER], "small"),
                  "OpenDART에서 매월 새 보고서 원문(ZIP)을 받아 아래 위치의 표와 문장을 읽습니다. 형식이 낯선 보고서는 건너뛰고 지난번에 읽은 숫자를 씁니다.")
            + sub("C", "핵심 숫자 검증표", verification_table(F),
                  "본문·표지·요약에 쓴 핵심 숫자의 출처와 계산입니다. ‘공시’는 원문 값을 단위만 바꿔 옮긴 것, ‘계산’은 공시 숫자로 이 보고서가 계산한 것입니다. "
                  "같은 표가 data/financials/analysis/verification.csv에 있습니다.")
            + sub("D", "용어 풀이", f'<dl class="r-gloss">{gl}</dl>')
            + sub("E", "출처", bullets([("공시 원문: " + dart_link(lf["rcept_no"], f"{lf['report_nm'].strip()} ({d.fmt_date(lf['rcept_dt'])} 접수)")
                                         + " · OpenDART(opendart.fss.or.kr)") if lf else "",
                                        f"연표·미래사업 조사({F['RC'].get('as_of', '–')}): " + " · ".join(src_items),
                                        "제도·업계 설명: " + " · ".join(refs),
                                        f"코드와 데이터: {link(cfg.get('repo_url', ''), cfg.get('repo_url', ''))} · 재무제표 대시보드: "
                                        f"{link(cfg.get('dashboard_url', ''), cfg.get('dashboard_url', ''))}"], "small src", raw=True)))
    return chapter("부록", "Appendix", "방법 · 자료와 한계 · 검증표 · 용어 · 출처", "", body, "appendix")


# ---------------------------------------------------------------------------
# 인쇄용 CSS (이전 보고서의 PRINT_CSS 뒤에 덧붙임)
# ---------------------------------------------------------------------------
REPORT_CSS = """
/* 근거 표시 배지 */
.ev{display:inline-block;margin:0 .2mm 0 .6mm;padding:0 1.1mm;border-radius:.8mm;font-size:6.2pt;font-weight:700;line-height:1.55;vertical-align:.25mm;white-space:nowrap;letter-spacing:0}
.ev-d{background:#dceee8;color:#0b5d4f}
.ev-c{background:#e3e5f7;color:#3a439a}
.ev-a{background:#fbecc9;color:#7a4d06}
.ev-n{background:#ecebe6;color:#55584f}
.ev-h{background:#f6e1ec;color:#8a2f5f}
.r-evleg{margin:2.5mm 0 0;font-size:7.6pt;color:var(--ink-2);line-height:2.1}

/* 표지 (297mm 안에 들어가게) */
.cover{padding:16mm 18mm 12mm}
.cv-main{margin-top:12mm}
.cover h1{font-size:40pt}
.cover h1 span{font-size:26pt}
.cv-sub{margin-top:4mm;font-size:10.5pt;max-width:168mm}
.cv-rq{margin-top:6mm;max-width:170mm;padding:2.4mm 4mm;border:1px solid var(--forest-line);border-radius:1.5mm}
.cv-rq p{margin:0;font-size:6.8pt;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--forest-soft)}
.cv-rq ol{margin:1mm 0 0;padding-left:5mm;font-size:8.3pt;line-height:1.55}
.cv-thesis{margin-top:6mm;font-size:9.8pt;line-height:1.7}
.cv-chart{padding-top:5mm}
.cv-bars{height:20mm}
.cv-kpis{margin-top:4mm}
.cv-k{padding:3.5mm 3.5mm 3.5mm 0}
.cv-v{font-size:19pt}
.cv-meta{margin-top:4.5mm}
.cv-meta>div{padding:1.7mm 3mm}
.cv-meta dd{font-size:7.5pt}
.cv-m{position:relative;height:4.2mm;margin-top:1.2mm}
.cv-m span{position:absolute;top:0;transform:translateX(-50%);font-size:6.3pt;font-weight:600;color:var(--forest-soft);white-space:nowrap}

/* 요약 */
.r-summary .r-find p{font-size:7.55pt;line-height:1.45}
.r-summary .r-finds{gap:2.2mm}
.r-summary .r-find{padding-top:2.2mm;padding-bottom:2.2mm}
.r-summary .r-hyp td,.r-summary .r-hyp th{font-size:7.3pt;padding:.9mm 1.5mm;line-height:1.45}
.r-summary .r-sec{margin-top:3.6mm}
.r-summary .r-ppf{margin-top:4mm}
.r-summary .ppf{padding:2.2mm 3mm}
.r-summary .ppf p{font-size:7.5pt;line-height:1.5}
.r-ppf{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:3mm;margin-top:5mm;break-inside:avoid}
.ppf{padding:2.6mm 3.2mm;border-top:3px solid var(--forest);background:var(--tint)}
.ppf .r-h{margin:0;font-size:8.8pt;font-weight:700}
.ppf p{margin:.8mm 0 0;font-size:7.9pt;line-height:1.55}
.r-hyp{table-layout:fixed}
.r-hyp td,.r-hyp th{font-size:7pt;padding:1mm 1.4mm;line-height:1.42}
.r-hyp thead th:nth-child(1){width:5%}
.r-hyp thead th:nth-child(2){width:14%}
.r-hyp thead th:nth-child(3){width:13%}
.r-hyp thead th:nth-child(4){width:28%}
.r-hyp thead th:nth-child(5){width:14%}
.r-hyp thead th:nth-child(6){width:20%}
.r-hyp thead th:nth-child(7){width:6%}
.r-hyp .r-chip{white-space:normal;line-height:1.3}
.r-summary .r-hyp td,.r-summary .r-hyp th{font-size:6.9pt;padding:.9mm 1.3mm;line-height:1.42}
.r-hyps{table-layout:fixed}
.r-hyps td,.r-hyps th{font-size:7.2pt;padding:.9mm 1.4mm;line-height:1.42}
.r-hyps thead th:nth-child(1){width:6%}
.r-hyps thead th:nth-child(2){width:24%}
.r-hyps thead th:nth-child(3){width:14%}
.r-hyps thead th:nth-child(4){width:48%}
.r-hyps thead th:nth-child(5){width:8%}
.r-hyps .r-chip{white-space:normal;line-height:1.3}
.r-rqa{table-layout:fixed}
.r-rqa td,.r-rqa th{font-size:7.4pt;padding:1mm 1.6mm;line-height:1.45}
.r-rqa thead th:nth-child(1){width:7%}
.r-rqa thead th:nth-child(2){width:66%}
.r-rqa thead th:nth-child(3){width:27%}

/* 1장 */
.r-quote{margin:1mm 0 3mm;padding:3mm 4.5mm;border-left:3px solid var(--data);background:var(--tint-g);font-size:9.3pt;line-height:1.75;color:var(--ink)}
.r-quote.small{font-size:8.2pt;padding:2.4mm 4mm}
.r-h2 th,.r-q3 th{width:9%}
.r-q3 td:last-child{white-space:nowrap}
.r-method th{width:19%}
.r-method td,.r-method th{font-size:7.8pt}
.r-vs th{width:15%}
.r-vs td,.r-vs th{font-size:7.8pt}

/* 2장 */
.r-timing th{width:14%}
.r-timing td,.r-timing th{font-size:7.8pt}
.bts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3mm}
.bt{padding:2.4mm 3.2mm;border:1px solid var(--line);border-radius:2mm;break-inside:avoid;background:#fff}
.bt .r-h{margin:0 0 1.2mm;font-size:9pt;font-weight:700}
.bt .r-h span{font-size:7pt;font-weight:500;color:var(--muted)}
.bt dl{margin:0;display:grid;grid-template-columns:15mm minmax(0,1fr);gap:.5mm 2mm;font-size:7.2pt;line-height:1.45}
.bt dl>div{display:contents}
.bt dt{font-weight:600;color:var(--ink-2)}
.bt dd{margin:0}
.bt-hy{margin:1.4mm 0 0;padding-top:1.2mm;border-top:1px dashed var(--line);font-size:7.2pt;color:var(--data)}
.r-peers10 td,.r-peers10 th{font-size:7pt;padding:.9mm 1.2mm}
.r-peers10 tbody tr:last-child th,.r-peers10 tbody tr:last-child td{background:var(--self)}
.r-peers10 tbody tr:nth-last-child(2) th,.r-peers10 tbody tr:nth-last-child(2) td{background:var(--tint);font-weight:600}
.r-dupont td,.r-dupont th{font-size:7.1pt;padding:.9mm 1.2mm}
.r-dupont thead th{width:auto}
.r-dupont thead th:first-child{width:21%}
.r-dupont tbody th{white-space:nowrap}

/* 3장 */
.r-feat td,.r-feat th{font-size:7.6pt;padding:1.1mm 1.7mm}
.r-feat th{width:17%}
.r-feat td:last-child{width:27%}
.r-stake th{width:15%}
.r-stake td,.r-stake th{font-size:7.8pt}

/* 4장 */
.r-segsum td,.r-segsum th{font-size:7.5pt;padding:1mm 1.6mm}
.r-matrix td,.r-matrix th{font-size:7.4pt;padding:1.1mm 1.6mm}
.r-matrix th{width:11%}

/* 5장 */
.r-items{table-layout:fixed}
.r-items td,.r-items th{font-size:7.2pt;padding:.9mm 1.3mm;vertical-align:middle;line-height:1.4}
.r-items thead th{font-size:6.9pt;line-height:1.3;vertical-align:bottom}
.r-items thead th:nth-child(1){width:19%}
.r-items thead th:nth-child(2){width:9%}
.r-items thead th:nth-child(3){width:27%}
.r-items thead th:nth-child(4){width:35%}
.r-items thead th:nth-child(5){width:10%;text-align:center}
.r-items td:last-child{text-align:center}
.r-g2{margin-top:4mm}
.r-purpose th{width:24%}
.r-purpose td,.r-purpose th{font-size:7.8pt}
.qas{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3mm}
.qa{padding:2mm 3mm;border:1px solid var(--line);border-radius:2mm;break-inside:avoid}
.qa .r-h{margin:0;font-size:8.3pt;font-weight:700}
.qa p{margin:.7mm 0 0;font-size:7.5pt;line-height:1.5}
.qa .qa-a{color:var(--data);font-weight:600}
.r-warn td,.r-warn th{font-size:7.6pt}

/* 6장 */
.r-bridge td,.r-bridge th,.r-cash td,.r-cash th{font-size:7.4pt;padding:.9mm 1.5mm}
.r-bridge tbody tr:last-child th,.r-bridge tbody tr:last-child td{border-top:1.5px solid var(--axis);font-weight:700}
.r-robust td,.r-robust th{font-size:7.1pt;padding:.9mm 1.4mm;line-height:1.4}
.r-robust thead th:nth-child(1){width:30%}
.r-robust .r-q{display:block;font-size:6.3pt;font-weight:400;color:var(--muted)}
.r-est,.r-cashy,.r-aging{table-layout:fixed}
.r-est td,.r-est th,.r-cashy td,.r-cashy th,.r-aging td,.r-aging th{font-size:6.8pt;padding:.8mm 1mm;line-height:1.35}
.r-est thead th,.r-cashy thead th,.r-aging thead th{font-size:6.4pt;line-height:1.25;vertical-align:bottom}
.r-est thead th:first-child,.r-cashy thead th:first-child,.r-aging thead th:first-child{width:7%}
.r-est tbody tr:last-child th,.r-est tbody tr:last-child td{border-top:1.5px solid var(--axis);font-weight:700}
.r-cashw{table-layout:fixed}
.r-cashw td,.r-cashw th{font-size:6.9pt;padding:.55mm 1.6mm;line-height:1.3}
.r-cashw thead th:first-child{width:46%}
.r-split td,.r-split th,.r-bscf td,.r-bscf th,.r-ent td,.r-ent th{font-size:7.1pt;padding:.9mm 1.4mm}
.r-split thead th:first-child{width:34%}
.r-bscf thead th:first-child,.r-ent thead th:first-child{width:40%}
.r-factor{table-layout:fixed}
.r-factor td,.r-factor th{font-size:7pt;padding:1mm 1.3mm;line-height:1.42}
.r-factor thead th:nth-child(1){width:14%}
.r-factor thead th:nth-child(2){width:22%}
.r-factor thead th:nth-child(3){width:29%}
.r-factor thead th:nth-child(4){width:23%}
.r-factor thead th:nth-child(5){width:12%}
.r-concl td,.r-concl th{font-size:7.4pt;padding:1mm 1.5mm}
.r-concl th{width:16%}

/* 6장·8장: +와 −를 함께 쌓는 막대 */
.dv .bar.stk.neg{box-shadow:inset 0 -1px 0 var(--sheet)}
.dv .bar.stk.neg.bot{border-radius:0 0 4px 4px}
.netbar{position:absolute;left:calc(50% - var(--bw) / 2 - 3px);width:calc(var(--bw) + 6px);height:0;border-top:2px solid var(--ink);pointer-events:none}

/* 7장 연표 */
.r-tl td,.r-tl th{font-size:7.5pt;padding:1mm 1.5mm;vertical-align:middle}
.r-tl th{white-space:nowrap}
.r-tl td:nth-child(3),.r-tl td:nth-child(4){white-space:nowrap}
.yc{display:grid;grid-template-columns:30mm minmax(0,1fr);gap:4.5mm;padding:2.8mm 0 2.4mm;border-top:1px solid var(--line);break-inside:avoid}
.yc-y{margin:0;font-size:16pt;font-weight:700;letter-spacing:-.03em;line-height:1.1;color:var(--forest)}
.yc-l .r-chip{margin-top:1.2mm;font-size:6.7pt}
.yc-n{margin:1.6mm 0 0;display:grid;gap:.35mm}
.yc-n>div{display:flex;justify-content:space-between;gap:1.5mm;font-size:6.8pt;line-height:1.35}
.yc-n dt{color:var(--muted)}
.yc-n dd{margin:0;font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.yc-r p{margin:0 0 .9mm;font-size:7.8pt;line-height:1.55}
.yc-r .yr{display:grid;grid-template-columns:14mm minmax(0,1fr);gap:2mm}
.yc-r .lab{font-size:7pt;font-weight:700;color:var(--ink-2);padding-top:.25mm}
.yc-r .yc-in,.yc-r .yc-in .lab{color:var(--data)}
.yc-r .yc-md{color:var(--ink-2)}
.yc-todo{padding:1mm 2mm;border-radius:1mm;background:var(--warn-bg);font-size:7.5pt}

/* 8장 */
.r-alloc td,.r-alloc th{font-size:7.5pt;padding:.9mm 1.8mm}
.r-alloc tbody tr:last-child th,.r-alloc tbody tr:last-child td{border-top:1.5px solid var(--axis);font-weight:700}
.r-spend td,.r-spend th{font-size:7.5pt;padding:1mm 1.6mm}
.r-div td,.r-div th,.r-int td,.r-int th{font-size:7.1pt;padding:.9mm 1.1mm}
.r-div th,.r-int th{white-space:nowrap}

/* 9장: 미래사업 단계 */
table.ladder{width:100%;table-layout:fixed;border-collapse:collapse;margin-top:1mm;font-size:7.6pt;break-inside:avoid}
.ladder thead th:nth-child(n+2){width:13.4%}
.ladder th{white-space:normal;overflow-wrap:anywhere}
.ladder th,.ladder td{padding:.9mm 1.4mm;border-bottom:1px solid var(--grid);text-align:left;vertical-align:middle}
.ladder thead th{background:var(--thead);font-size:6.8pt;font-weight:600;color:var(--ink-2);text-align:center;line-height:1.3}
.ladder thead th:first-child{text-align:left;width:33%}
.ladder .sn{display:inline-grid;place-items:center;width:3.6mm;height:3.6mm;margin-right:1mm;border-radius:50%;background:var(--data);color:#fff;font-size:6.1pt;font-weight:700;vertical-align:.2mm}
.ladder tbody th b{display:block;font-size:7.6pt;font-weight:700;line-height:1.3}
.ladder tbody th span{display:block;font-size:6.5pt;color:var(--muted);line-height:1.3}
.ladder td{position:relative;height:6.2mm;padding:0}
.ladder td i{position:absolute;left:0;right:0;top:50%;height:1.8mm;margin-top:-.9mm}
.ladder td.done i{background:color-mix(in srgb,var(--s1) 42%,#fff)}
.ladder td.now i{right:50%;background:color-mix(in srgb,var(--s1) 42%,#fff)}
.ladder td.now:first-of-type i{display:none}
.ladder td.now::after{content:"";position:absolute;left:50%;top:50%;width:3.6mm;height:3.6mm;margin:-1.8mm 0 0 -1.8mm;border-radius:50%;background:var(--s1);box-shadow:0 0 0 1.2px #fff}
.ladder td.todo i{height:0;margin-top:0;border-top:1px dashed var(--axis)}
.r-grow{table-layout:fixed}
.r-grow td,.r-grow th{font-size:6.7pt;padding:.9mm 1.1mm;line-height:1.38;vertical-align:top}
.r-grow thead th{font-size:6.4pt;line-height:1.25;vertical-align:bottom}
.r-grow thead th:nth-child(1){width:14%}
.r-grow thead th:nth-child(2){width:16%}
.r-grow thead th:nth-child(3){width:14%}
.r-grow thead th:nth-child(4){width:13%}
.r-grow thead th:nth-child(5){width:14%}
.r-grow thead th:nth-child(6){width:10%}
.r-grow thead th:nth-child(7){width:12%}
.r-grow thead th:nth-child(8){width:7%}
.r-grow td:last-child{font-size:6pt;overflow-wrap:anywhere}
.r-grow .r-q{display:block;margin-top:.5mm;color:var(--muted);font-size:6.2pt}
.chain{display:flex;gap:.45mm;flex-wrap:nowrap}
.chain i{display:inline-grid;place-items:center;width:3.2mm;height:3.2mm;border-radius:.6mm;font-style:normal;font-size:5.6pt;line-height:1;font-weight:700}
.chain .c-done{background:var(--s1);color:#fff}
.chain .c-now{background:color-mix(in srgb,var(--s1) 35%,#fff);color:var(--ink)}
.chain .c-todo{background:#fff;color:var(--axis);box-shadow:inset 0 0 0 1px var(--axis)}
.chain .c-na{background:var(--hover);color:var(--muted)}
.chain .c-unknown{background:var(--warn-bg);color:var(--ink-2)}
.r-scen td,.r-scen th{font-size:7.4pt;padding:1mm 1.5mm}
.r-scen td:nth-child(2){width:33%}
.r-grid td,.r-grid th,.r-stress td,.r-stress th{font-size:7.5pt}
.r-peers td,.r-peers th{font-size:7.8pt}

/* 10장 */
.r-ppf2{table-layout:fixed}
.r-ppf2 td,.r-ppf2 th{font-size:7.7pt}
.r-ppf2 thead th:nth-child(1){width:8%}
.r-ppf2 thead th:nth-child(2){width:20%}
.r-ppf2 thead th:nth-child(3){width:24%}
.r-ppf2 thead th:nth-child(4){width:48%}
.r-ppf2 .r-chip{white-space:normal}

/* 쪽 나눔: 소제목과 설명을 한 덩어리로, 바로 뒤 내용과 같은 쪽에 */
.r-hn{break-inside:avoid;break-after:avoid}
.r-sec>.r-hn>h3{margin:0 0 2mm;font-size:11.5pt;letter-spacing:-.015em}
.r-sec>.r-hn>h3 .k{display:inline-block;min-width:9mm;margin-right:1.5mm;color:var(--data);font-weight:700}
.r-chbox{margin:0 0 3mm;padding:2.6mm 3.6mm}
.r-chbox .r-chapters{grid-template-columns:repeat(2,minmax(0,1fr));gap:.6mm 4mm}

/* 부록 */
.r-formula td,.r-formula th{font-size:7.3pt;padding:1mm 1.6mm}
.r-formula th{width:17%}
.r-formula td:nth-child(2){width:46%}
.r-auto td,.r-auto th{font-size:7.5pt}
.r-auto th{width:44%}
.r-verify{table-layout:fixed}
.r-verify td,.r-verify th{font-size:6.6pt;padding:.8mm 1.1mm;line-height:1.35;overflow-wrap:anywhere}
.r-verify thead th:nth-child(1){width:19%}
.r-verify thead th:nth-child(2){width:9%}
.r-verify thead th:nth-child(3){width:6%}
.r-verify thead th:nth-child(4){width:15%}
.r-verify thead th:nth-child(5){width:17%}
.r-verify thead th:nth-child(6){width:18%}
.r-verify thead th:nth-child(7){width:16%}
.r-verify .r-chip{font-size:6pt}
"""


# ---------------------------------------------------------------------------
# 문서 조립
# ---------------------------------------------------------------------------
# 한글 글꼴: 러너에서는 fonts-nanum(나눔고딕, TrueType)을 설치합니다. TrueType 글꼴은 PDF에 필요한 글자만 작게 들어가고,
# Noto Sans CJK 같은 CFF 글꼴은 Chrome이 글자마다 그림(Type 3)으로 넣어 파일이 몇 배 커집니다.
# 나눔고딕에 없는 글자(빼기 기호 −, Ⅺ 같은 로마 숫자)는 목록 끝의 DejaVu Sans로 채웁니다(없으면 세리프 글꼴로 빠짐).
# Windows·macOS에서 직접 실행하면 맑은 고딕·애플 SD 산돌고딕 Neo로 인쇄됩니다.
FONT_STACK = ('"NanumGothic","나눔고딕","Noto Sans CJK KR","Noto Sans KR","Malgun Gothic","Apple SD Gothic Neo",'
              '"DejaVu Sans",sans-serif')
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
.r-doc .vtiles{grid-template-columns:repeat(4,minmax(0,1fr));margin:3mm 0 4mm;border-radius:2mm;break-inside:avoid}
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
    for build in (ch1_method, ch2_industry, ch3_report, ch4_business, ch5_items, ch6_drivers, ch7_timeline, ch8_allocation,
                  ch9_future, ch10_conclusion, appendix):
        try:
            parts.append(build(ctx, F))
        except Exception as exc:     # 한 장이 실패해도 나머지 장으로 보고서를 만듭니다
            print(f"::warning::기업분석 보고서 {build.__name__} 생략: {type(exc).__name__}: {exc}")
    css = ((PRINT_CSS + REPORT_CSS).replace("__TITLE__", css_text(title)).replace("__EDITION__", css_text(edition(ctx)))
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
        found = sorted(base.glob("chromium-*/chrome-linux*/chrome")) if base.exists() else []
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
