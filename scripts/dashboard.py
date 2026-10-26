"""재무제표 대시보드(dashboard/index.html)와 README 자동 구역을 만듭니다.

- 파이썬 표준 라이브러리만 씁니다. 차트는 HTML/CSS와 SVG로 직접 그려서 자바스크립트가 꺼져 있어도 보입니다.
  스크립트는 마우스를 올리거나 누르면 나오는 설명 상자만 담당합니다.
- 화면 위쪽(그래프): 가이드 6단계 판정 카드 → 이번 달(최근 분기) → 재무제표 10년(손익·재무상태·현금흐름)
  → 재무비율 10가지 관점(statements.py) → 조합 신호 → 시기별 흐름
- 화면 아래쪽(표): Annual · Half-year · Quarterly 표 → 자료·검증 → 동종업계(Peer firms) 표
- 사업보고서 본문(수주·PF 등)을 읽은 내용은 기업분석 보고서 PDF(company_report.py)로 따로 만듭니다.
- 화면의 숫자와 문장은 모두 ctx(dart_agent.build가 만든 표)에서 계산합니다. 차트 부품은 기업분석 보고서도 함께 씁니다.
"""
import html
import json
import math
import re
from pathlib import Path

import analysis as an
import financials as fin
import lenses as ln

EOK = 100_000_000          # 1억 원
T = an.T                   # 1조 원
SMALL_FLOW = 0.05 * T      # 현금흐름 신호등에서 '거의 없음'으로 보는 기준 (±500억 원)
DART_VIEW = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


# ---------------------------------------------------------------------------
# 1. 표기
# ---------------------------------------------------------------------------
def esc(value):
    return html.escape(str(value), quote=True)


def rich(text):
    """**굵게** 표시를 <b>로 바꾸고 나머지는 이스케이프합니다."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(text))


def eok(v):
    """원 → 억 원 (정수, 천 단위 쉼표)."""
    return "–" if v is None else an._m(f"{round(v / EOK):,}")


def tick_jo(t):
    return "0" if abs(t) < 1e-9 else an._m(f"{t:g}조")


def tick_plain(t):
    return an._m(f"{t:g}")


def in_jo(values):
    return [None if v is None else v / T for v in values]


def fmt_date(yyyymmdd):
    s = str(yyyymmdd or "")
    return f"{s[:4]}.{s[4:6]}.{s[6:8]}" if len(s) == 8 else s


def short_q(row):
    return f"{row['year']}년 {row['kind'][1]}분기"


# ---------------------------------------------------------------------------
# 2. 차트 부품 (HTML/CSS + SVG)
# ---------------------------------------------------------------------------
def axis(values, include=(), max_ticks=5, head=0.1):
    """값 범위로 축 범위(lo, hi)와 눈금(1·2·5 간격)을 정합니다."""
    vals = [v for v in values if v is not None] + list(include) + [0]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1
    lo2 = lo - span * head if lo < 0 else 0
    hi2 = hi + span * head if hi > 0 else 0
    exponent = math.floor(math.log10(span)) - 2
    for k in range(exponent, exponent + 4):
        for m in (1, 2, 5):
            step = m * 10 ** k
            first, last = math.ceil(lo2 / step - 1e-9), math.floor(hi2 / step + 1e-9)
            if 2 <= last - first + 1 <= max_ticks:
                return lo2, hi2, [round(i * step, 10) for i in range(first, last + 1)]
    return lo2, hi2, [lo2, hi2]


def year_label(y):
    return f'<span><span class="y4">{y}</span><span class="y2">’{str(y)[2:]}</span></span>'


def quarter_label(row, show_year):
    year = f"’{str(row['year'])[2:]}" if show_year else "&nbsp;"
    return f'<span><span class="qq">{row["kind"][1]}Q</span><span class="qy">{year}</span></span>'


def tip_attr(title, rows, note=None):
    """툴팁 데이터(JSON)와 화면낭독기용 설명을 함께 만듭니다. rows: [[이름, 값, 색 또는 None]]"""
    data = {"t": title, "r": rows}
    if note:
        data["n"] = note
    label = title + ": " + ", ".join(f"{r[0]} {r[1]}" for r in rows) + (f". {note}" if note else "")
    return (f' tabindex="0" role="img" aria-label="{esc(label)}"'
            f' data-tip="{esc(json.dumps(data, ensure_ascii=False))}"')


def legend(items):
    """items: [(이름, CSS 변수명, 모양)] 모양은 'box' | 'outline'."""
    keys = "".join(f'<span class="key"><i class="sw {shape}" style="--c:var({color})"></i>{esc(name)}</span>'
                   for name, color, shape in items)
    return f'<div class="legend">{keys}</div>'


def _y_axis(lo, hi, ticks, fmt):
    span = hi - lo
    labels = "".join(f'<span style="bottom:{(t - lo) / span * 100:.3f}%">{esc(fmt(t))}</span>' for t in ticks)
    sizer = max((fmt(t) for t in ticks), key=len)
    return f'<div class="ya" aria-hidden="true"><span class="sizer">{esc(sizer)}</span>{labels}</div>'


def _grid(lo, hi, ticks, neg_zone=False):
    span = hi - lo
    out = "".join(f'<i class="gl" style="bottom:{(t - lo) / span * 100:.3f}%"></i>' for t in ticks if abs(t) > 1e-12)
    zero = (0 - lo) / span * 100
    if neg_zone and zero > 0.5:
        out = f'<i class="below" style="height:{zero:.3f}%"></i>' + out
    return out + f'<i class="zl" style="bottom:{zero:.3f}%"></i>'


def _xa(xlabels):
    return f'<div class="xa" aria-hidden="true">{"".join(xlabels)}</div>'


def column_chart(xlabels, series, *, ticks_fmt, tips, labels=None, include=(), height=220, neg_zone=False):
    """세로 막대 차트. series: [{'values': [...], 'color': '--s1'}] (1~2개). labels: {(시리즈, 위치): 글자}"""
    n, k = len(xlabels), len(series)
    lo, hi, ticks = axis([v for s in series for v in s["values"]], include=include)
    span = hi - lo
    zero = (0 - lo) / span * 100
    slots = []
    for i in range(n):
        marks = []
        for j, s in enumerate(series):
            v = s["values"][i]
            if v is None:
                continue
            h = abs(v) / span * 100
            pos = f"bottom:{zero:.3f}%" if v >= 0 else f"top:{100 - zero:.3f}%"
            sign = "pos" if v >= 0 else "neg"
            marks.append(f'<i class="bar {sign} j{j}" style="{pos};height:{h:.3f}%;--c:var({s["color"]})"></i>')
            text = (labels or {}).get((j, i))
            if text:
                lpos = f"bottom:calc({zero + h:.3f}% + 4px)" if v >= 0 else f"top:calc({100 - zero + h:.3f}% + 4px)"
                marks.append(f'<b class="vl j{j}" style="{lpos}">{esc(text)}</b>')
        title, rows, note = tips(i)
        slots.append(f'<div class="slot" style="left:{i / n * 100:.4f}%;width:{100 / n:.4f}%"'
                     f'{tip_attr(title, rows, note)}>{"".join(marks)}</div>')
    return (f'<div class="plot cc k{k}" style="--h:{height}px;--n:{n}">{_y_axis(lo, hi, ticks, ticks_fmt)}'
            f'<div class="pa">{_grid(lo, hi, ticks, neg_zone)}{"".join(slots)}</div>{_xa(xlabels)}</div>')


def line_chart(xlabels, values, *, color, ticks_fmt, tips, labels=None, refs=(), height=200, dots=True):
    """꺾은선 차트(시리즈 1개). refs: [(값, 설명, 'left'|'right')] 참고선."""
    n = len(xlabels)
    lo, hi, ticks = axis(values, include=[r[0] for r in refs])
    span = hi - lo

    def yp(v):
        return (v - lo) / span * 100

    pts = " ".join(f"{(i + 0.5) / n * 1000:.1f},{(1 - (v - lo) / span) * 1000:.1f}"
                   for i, v in enumerate(values) if v is not None)
    marks = [f'<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">'
             f'<polyline points="{pts}" style="stroke:var({color})"/></svg>']
    for value, text, side in refs:
        marks.append(f'<i class="rl" style="bottom:{yp(value):.3f}%"></i>')
        if text:
            marks.append(f'<span class="rlab {side}" style="bottom:{yp(value):.3f}%">{esc(text)}</span>')
    labels = labels or {}
    for i, v in enumerate(values):
        if v is None:
            continue
        x, y = (i + 0.5) / n * 100, yp(v)
        if dots or i in labels:
            marks.append(f'<i class="dt" style="left:{x:.3f}%;bottom:{y:.3f}%;--c:var({color})"></i>')
        text = labels.get(i)
        if text:
            # 바로 옆 점에도 숫자가 붙으면, 둘 중 낮은 점의 숫자는 점 아래로 내립니다.
            neighbors = [values[j] for j in (i - 1, i + 1) if j in labels and 0 <= j < n and values[j] is not None]
            below = y > 78 or any(v < other for other in neighbors)
            spot = f"top:calc({100 - y:.3f}% + 9px)" if below else f"bottom:calc({y:.3f}% + 9px)"
            marks.append(f'<b class="ll" style="left:{x:.3f}%;{spot}">{esc(text)}</b>')
    slots = []
    for i in range(n):
        title, rows, note = tips(i)
        slots.append(f'<div class="slot" style="left:{i / n * 100:.4f}%;width:{100 / n:.4f}%"'
                     f'{tip_attr(title, rows, note)}></div>')
    return (f'<div class="plot lc" style="--h:{height}px;--n:{n}">{_y_axis(lo, hi, ticks, ticks_fmt)}'
            f'<div class="pa">{_grid(lo, hi, ticks)}{"".join(marks)}{"".join(slots)}</div>{_xa(xlabels)}</div>')


def multi_line_chart(xlabels, series, *, ticks_fmt, tips, refs=(), height=210, end_fmt=None):
    """같은 단위의 꺾은선 여러 개. series: [{'name', 'values', 'color', 'dash'}]. 끝점 오른쪽에 값을 적습니다."""
    n = len(xlabels)
    vals = [x for sr in series for x in sr["values"] if x is not None]
    if not vals:
        return '<p class="chart-note">표시할 숫자가 없습니다.</p>'
    lo, hi, ticks = axis(vals, include=[r[0] for r in refs])
    span = hi - lo

    def yp(v):
        return (v - lo) / span * 100

    lines, marks = [], []
    for sr in series:
        segs, cur = [], []
        for i, v in enumerate(sr["values"]):
            if v is None:
                if cur:
                    segs.append(cur)
                cur = []
                continue
            cur.append((i, v))
        if cur:
            segs.append(cur)
        dash = ' stroke-dasharray="5 4"' if sr.get("dash") else ""
        for seg in segs:
            if len(seg) == 1:
                i, v = seg[0]
                marks.append(f'<i class="dt" style="left:{(i + 0.5) / n * 100:.3f}%;bottom:{yp(v):.3f}%;--c:var({sr["color"]})"></i>')
                continue
            pts = " ".join(f"{(i + 0.5) / n * 1000:.1f},{(1 - (v - lo) / span) * 1000:.1f}" for i, v in seg)
            lines.append(f'<polyline points="{pts}" style="stroke:var({sr["color"]})"{dash}/>')
    out = [f'<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">{"".join(lines)}</svg>']
    for value, text, side in refs:
        out.append(f'<i class="rl" style="bottom:{yp(value):.3f}%"></i>')
        if text:
            out.append(f'<span class="rlab {side}" style="bottom:{yp(value):.3f}%">{esc(text)}</span>')
    ends = []
    for sr in series:
        idx = [i for i, v in enumerate(sr["values"]) if v is not None]
        if idx:
            i = idx[-1]
            ends.append([yp(sr["values"][i]) / 100 * height, i, sr["values"][i], sr])
    ends.sort(key=lambda e: e[0])
    for k in range(1, len(ends)):     # 끝 값 글자가 겹치지 않게 14px 이상 띄웁니다
        ends[k][0] = max(ends[k][0], ends[k - 1][0] + 14)
    for ypx, i, v, sr in ends:
        out.append(f'<i class="dt" style="left:{(i + 0.5) / n * 100:.3f}%;bottom:{yp(v):.3f}%;--c:var({sr["color"]})"></i>')
        out.append(f'<b class="el" style="bottom:{ypx:.1f}px;--c:var({sr["color"]})">{esc((end_fmt or ticks_fmt)(v))}</b>')
    slots = []
    for i in range(n):
        title, rows, note = tips(i)
        slots.append(f'<div class="slot" style="left:{i / n * 100:.4f}%;width:{100 / n:.4f}%"'
                     f'{tip_attr(title, rows, note)}></div>')
    return (f'<div class="plot lc ml" style="--h:{height}px;--n:{n}">{_y_axis(lo, hi, ticks, ticks_fmt)}'
            f'<div class="pa">{_grid(lo, hi, ticks)}{"".join(marks)}{"".join(out)}{"".join(slots)}</div>{_xa(xlabels)}</div>')


def sparkline(values, color="--data", zero=False):
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals + ([0] if zero else [])), max(vals + ([0] if zero else []))
    span = (hi - lo) or 1
    lo, hi = lo - span * 0.08, hi + span * 0.08
    n = len(values)

    def pt(i, v):
        return i / (n - 1) * 1000, (1 - (v - lo) / (hi - lo)) * 1000

    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, v) for i, v in enumerate(values) if v is not None))
    zl = ""
    if zero and lo < 0 < hi:
        zy = (1 - (0 - lo) / (hi - lo)) * 1000
        zl = f'<line class="z" x1="0" x2="1000" y1="{zy:.1f}" y2="{zy:.1f}"/>'
    end = ""
    if values[-1] is not None:
        end = (f'<i class="end" style="left:100%;bottom:{(values[-1] - lo) / (hi - lo) * 100:.2f}%;'
               f'--c:var({color})"></i>')
    return (f'<div class="spark" aria-hidden="true"><svg viewBox="0 0 1000 1000" preserveAspectRatio="none">'
            f'{zl}<polyline points="{pts}"/></svg>{end}</div>')


def stack_chart(xlabels, groups, *, ticks_fmt, tips, height=220, labels=None, wide_bars=False):
    """누적 세로 막대. groups: 묶음 1~2개, 묶음마다 [{'values': [...], 'color': '--s1'}, …]를 아래부터 쌓습니다(양수만).
    labels: {(묶음, 위치): 글자} 막대 위 글자."""
    n, k = len(xlabels), len(groups)
    tops = [sum(seg["values"][i] or 0 for seg in g) for g in groups for i in range(n)]
    lo, hi, ticks = axis(tops)
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
                     f'{tip_attr(title, rows, note)}>{"".join(marks)}</div>')
    wb = " wb" if wide_bars else ""
    return (f'<div class="plot cc k{k}{wb}" style="--h:{height}px;--n:{n}">{_y_axis(lo, hi, ticks, ticks_fmt)}'
            f'<div class="pa">{_grid(lo, hi, ticks)}{"".join(slots)}</div>{_xa(xlabels)}</div>')


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
        out.append(f'<div class="hs-row"{tip_attr(title, tip_rows, note)}><span class="hs-l"><b>{esc(r["label"])}</b>{meta}</span>'
                   f'<span class="hs-t">{"".join(segs)}</span><span class="hs-v">{esc(value_fmt(r))}</span></div>')
    unit = f'<p class="hs-unit">{esc(unit_label)}</p>' if unit_label else ""
    return f'<div class="hs">{"".join(out)}</div>{unit}'


def data_table(headers, rows, caption=None):
    """작은 표. rows: [[셀, ...]] 셀은 (표시 문자열, 원값) 또는 문자열. 첫 칸은 행 제목."""
    th = "".join(f'<th scope="col">{esc(h)}</th>' for h in headers)
    body = []
    for row in rows:
        cells = []
        for idx, cell in enumerate(row):
            text, raw = cell if isinstance(cell, tuple) else (cell, None)
            cls = ""
            if raw is None and text in ("–", "자료 없음") and idx:
                cls = ' class="na"'
            elif isinstance(raw, (int, float)) and raw < 0:
                cls = ' class="neg"'
            tag = "th" if idx == 0 else "td"
            scope = ' scope="row"' if tag == "th" else ""
            cells.append(f"<{tag}{scope}{cls}>{esc(text)}</{tag}>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    cap = f"<caption>{esc(caption)}</caption>" if caption else ""
    return (f'<div class="table-scroll" tabindex="0"><table>{cap}<thead><tr>{th}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def figure(fid, title, sub, body, *, legend_html="", note=None, table_html=None, wide=False):
    note_html = f'<p class="chart-note">{rich(note)}</p>' if note else ""
    tv = f'<details class="tv"><summary>표로 보기</summary>{table_html}</details>' if table_html else ""
    cls = "chart wide" if wide else "chart"
    return (f'<figure class="{cls}" id="{fid}"><figcaption class="chart-head"><h3>{esc(title)}</h3>'
            f'<p>{esc(sub)}</p></figcaption>{legend_html}{body}{note_html}{tv}</figure>')


def chip(verdict):
    tone, word = verdict
    icon = {"good": "✓", "warn": "!", "crit": "✕", "info": "i"}[tone]
    return f'<span class="chip {tone}"><i class="ic" aria-hidden="true">{icon}</i>{esc(word)}</span>'


def eyebrow(en, ko):
    return f'<p class="eyebrow">{esc(en)}<span class="ko"> · {esc(ko)}</span></p>'


def section_head(sid, en, ko, title, *paras):
    body = "".join(f"<p>{rich(p)}</p>" for p in paras if p)
    return f'<div class="sec-head">{eyebrow(en, ko)}<h2 id="h-{sid}">{esc(title)}</h2>{body}</div>'


def src_link(key):
    name, url = an.SOURCES[key]
    return f'<a href="{esc(url)}" target="_blank" rel="noopener">{esc(name)} ↗</a>'


# ---------------------------------------------------------------------------
# 3. 계산 도우미
# ---------------------------------------------------------------------------
def rolling_ttm(quarters, num, den=None):
    """연속된 4개 분기 합계(또는 비율) 목록. 분기가 끊기면 None."""
    out = []
    for i in range(len(quarters)):
        if i < 3:
            out.append(None)
            continue
        last4 = quarters[i - 3:i + 1]
        ok = all(fin._next_quarter(a) == (b["year"], b["kind"]) for a, b in zip(last4, last4[1:]))
        nums = [q["values"].get(num) for q in last4]
        if not ok or None in nums:
            out.append(None)
            continue
        if den is None:
            out.append(sum(nums))
            continue
        dens = [q["values"].get(den) for q in last4]
        out.append(None if None in dens else fin.ratio(sum(nums), sum(dens)))
    return out


def balance_rows(v):
    return [q for q in v.ctx["quarters"] if q["values"].get("assets") is not None]


# ---------------------------------------------------------------------------
# 4. 화면 위쪽: 판정 카드
# ---------------------------------------------------------------------------
def kpis(v, vd, ctx):
    """가이드 6단계마다 카드 하나: 판정 · 대표 숫자 · 비교 · 추세선."""
    first, last = v.annual[0], v.annual[-1]
    y0, yl = first["year"], last["year"]
    tiles = []

    # 1 매출 성장
    rev0, revl = first["values"]["revenue"], last["values"]["revenue"]
    ttm_rev, prev_rev = v.ttm("revenue"), v.ttm_prev("revenue")
    now = ""
    if ttm_rev:
        now = f"최근 4개 분기 {an.jo(ttm_rev)}조 원" + (f" ({an.signed(fin.growth(ttm_rev, prev_rev))}%)" if prev_rev else "")
    tiles.append((1, "매출 성장", "growth", vd["growth"], an.jo(revl), "조 원", f"{yl}년 연간 매출액",
                  f"{y0}년의 **{revl / rev0:.2f}배** · 연평균 {an.pct(vd['cagr'])}%", now,
                  sparkline(v.series("revenue")), "외형이 실제 사업 성장으로 커지고 있는가"))

    # 2 이익률
    m0, ml = first["ratios"]["operating_margin_pct"], last["ratios"]["operating_margin_pct"]
    gm = fin.ratio(v.ttm("gross_profit"), v.ttm("revenue"))
    nm = fin.ratio(v.ttm("net_income"), v.ttm("revenue"))
    tiles.append((2, "이익률", "profit", vd["profit"], an.pct(vd["margin_now"]), "%", "최근 4개 분기 영업이익률",
                  f"{y0}년 {an.pct(m0)}% → {yl}년 {an.pct(ml)}%",
                  f"매출총이익률 {an.pct(gm)}% · 순이익률 {an.pct(nm)}%" if gm is not None else "",
                  sparkline(rolling_ttm(v.quarters, "operating_profit", "revenue"), zero=True),
                  "성장이 영업이익과 순이익으로 남고 있는가"))

    # 3 현금흐름
    cfl = last["values"].get("operating_cashflow")
    span = [t for t in v.years if t > yl - 5]
    sc = [v.a(t, "operating_cashflow") for t in span]
    sn = [v.a(t, "net_income") for t in span]
    now = ""
    if len(span) == 5 and None not in sc and None not in sn and sum(sn) > 0:
        now = f"5년 누적 CFO/순이익 {an.pct(sum(sc) / sum(sn), 2)}배"
    fcf = last["values"].get("fcf")
    if fcf is not None:
        now += (" · " if now else "") + f"FCF {an.jo(fcf, 2)}조 원"
    tiles.append((3, "현금흐름", "cash", vd["cash"], an.jo(cfl, 2), "조 원", f"{yl}년 영업활동현금흐름",
                  f"**{vd['streak']}년 연속 마이너스**" if vd["streak"] else "플러스 유지", now,
                  sparkline(v.series("operating_cashflow"), zero=True), "회계상 이익이 현금으로 회수되고 있는가"))

    # 4 차입 부담
    cov, nde, nd = vd["coverage"], vd["nd_ebitda"], vd["net_debt"]
    bal = vd["balance_row"]
    if nd is None:
        delta = ""
    elif nd > 0:
        delta = f"순차입금 {an.jo(nd, 2)}조 원" + (f" · EBITDA의 **{nde:.1f}배**" if nde is not None else "")
    else:
        delta = f"**순현금 {an.jo(-nd, 2)}조 원**"
    tiles.append((4, "차입 부담", "debt", vd["debt"], an.pct(cov), "배", "최근 4개 분기 이자보상배율",
                  delta, f"{an.when_label(bal)} 부채비율 {an.pct(bal['ratios'].get('debt_to_equity_pct'), 0)}%",
                  sparkline(v.series("interest_coverage_x"), zero=True), "현금창출력으로 이자와 원금을 감당할 수 있는가"))

    # 5 투자수익률
    roic, ry = vd["roic"], vd["roic_year"]
    tiles.append((5, "투자수익률", "returns", vd["returns"], an.pct(roic), "%", f"{ry}년 ROIC" if ry else "ROIC",
                  (f"ROE {an.pct(v.a(ry, 'roe_pct'))}% · ROA {an.pct(v.a(ry, 'roa_pct'))}%" if ry else ""),
                  (f"세후 차입 이자율 {an.pct(vd['after_tax_rate'])}% · 단순 기준 {an.HURDLE_ROIC:.0f}%"
                   if vd["after_tax_rate"] is not None else f"단순 기준 {an.HURDLE_ROIC:.0f}%"),
                  sparkline(v.series("roic_pct"), zero=True), "투입한 자본이 자본비용보다 높은 수익을 만드는가"))

    # 6 주가 수준
    val = ctx.get("valuation") or {}
    if val.get("market_cap"):
        delta = " · ".join(x for x in (f"PER **{val['per_x']:.1f}배**" if val.get("per_x") else "",
                                       f"EV/EBITDA {val['ev_ebitda_x']:.1f}배" if val.get("ev_ebitda_x") else "") if x)
        tiles.append((6, "주가 수준", "valuation", vd["valuation"], f"{val['pbr_x']:.2f}" if val.get("pbr_x") else "–", "배",
                      f"PBR · {an.price_when(val)} 주가 기준", delta,
                      f"주가 {val['price']:,.0f}원 · 시가총액 {an.jo(val['market_cap'], 2)}조 원",
                      sparkline(v.series("pbr_x")), "현재 가격이 성장과 위험을 어느 정도 반영하고 있는가"))
    else:
        tiles.append((6, "주가 수준", "valuation", vd["valuation"], "–", "", "PBR · PER · EV/EBITDA",
                      "주가를 받으면 계산합니다", "다음 자동 실행(매월 1일) 때 채워집니다", "",
                      "현재 가격이 성장과 위험을 어느 정도 반영하고 있는가"))

    out = []
    for no, label, sid, verdict, value, unit, basis, delta, now, spark, question_text in tiles:
        now_html = f'<p class="kpi-now">{rich(now)}</p>' if now else ""
        out.append(f'<article class="kpi"><div class="kpi-top"><h3 class="kpi-label"><a href="#{ln.LENS_OF_STEP.get(sid, sid)}"><span class="no">{no}</span>{esc(label)}</a></h3>'
                   f'{chip(verdict)}</div><p class="kpi-basis">{esc(basis)}</p>'
                   f'<p class="kpi-value">{esc(value)}<small>{esc(unit)}</small></p>'
                   f'<p class="kpi-delta">{rich(delta)}</p>{now_html}{spark}<p class="kpi-term">{esc(question_text)}</p></article>')
    return f'<div class="kpis six">{"".join(out)}</div>'


# ---------------------------------------------------------------------------
# 5. 화면 위쪽: 이번 달(최근 분기)
# ---------------------------------------------------------------------------
def update_card(ctx, a):
    up = a["update"]
    lines = "".join(f"<li>{rich(x)}</li>" for x in up["lines"])
    new = [f for f in ctx["status"].get("new_filings", []) if "보고서" in f.get("report_nm", "")]
    new_html = ""
    if new:
        items = "".join(f'<li><a href="{DART_VIEW}{esc(f["rcept_no"])}" target="_blank" rel="noopener">'
                        f'{esc(f["report_nm"].strip())} ↗</a> <span class="muted">{fmt_date(f["rcept_dt"])} 접수</span></li>'
                        for f in new[-6:])
        new_html = f'<p class="mini-h">이번에 새로 반영한 보고서</p><ul class="plain">{items}</ul>'
    alert = ""
    if up["errors"]:
        items = "".join(f"<li>{esc(e)}</li>" for e in up["errors"][:8])
        more = f"<li>외 {len(up['errors']) - 8}건 (data/financials/status.json)</li>" if len(up["errors"]) > 8 else ""
        alert = (f'<div class="callout warn" role="note"><p class="mini-h">확인이 필요한 점</p><ul>{items}{more}</ul>'
                 f'<p class="callout-foot">문제가 있어도 저장된 숫자로 화면은 계속 갱신됩니다. 다음 실행에서 다시 시도합니다.</p></div>')
    notes = "".join(f"<li>{esc(n)}</li>" for n in up["notes"])
    notes_html = f'<ul class="plain small">{notes}</ul>' if notes else ""
    log_html = ""
    log = ctx.get("log") or []
    if log:
        rows = "".join(f'<tr><th scope="row">{esc(x["checked_at"][:16].replace("T", " "))}</th>'
                       f'<td>{len(x.get("new_filings", []))}건</td><td>{x.get("errors", 0)}건</td></tr>' for x in log[:6])
        log_html = (f'<details class="tv"><summary>최근 자동 실행 기록</summary><div class="table-scroll"><table>'
                    f'<thead><tr><th scope="col">확인 시각</th><th scope="col">새 공시</th><th scope="col">문제</th></tr></thead>'
                    f'<tbody>{rows}</tbody></table></div></details>')
    return (f'<article class="card"><h3>업데이트 상태</h3><ul class="plain">{lines}</ul>{new_html}{alert}{notes_html}'
            f'{log_html}</article>')


def latest_card(a):
    lq = a.get("latest")
    if not lq:
        return '<article class="card"><h3>가장 최근 분기</h3><p>분기 자료가 아직 없습니다.</p></article>'
    row = lq["row"]
    link = ""
    if row.get("receipt"):
        link = (f'<p class="card-foot">출처: <a href="{DART_VIEW}{esc(row["receipt"])}" target="_blank" rel="noopener">'
                f'{esc(row["report_name"].strip())} ↗</a> · {fmt_date(row["filed"])} 접수'
                + (" · 2분기 이후 숫자는 누적 보고서끼리 빼서 계산" if row["derived"] else "") + "</p>")
    items = "".join(f"<li>{rich(x)}</li>" for x in lq["lines"])
    return f'<article class="card latest"><h3>{esc(lq["title"])}</h3><ul class="plain">{items}</ul>{link}</article>'


def quarter_figs(v, notes):
    qs = v.quarters[-12:]
    if len(qs) < 2:
        return ""
    xl = [quarter_label(q, i == 0 or q["kind"] == "Q1") for i, q in enumerate(qs)]
    n = len(qs)
    rev = [q["values"].get("revenue") for q in qs]
    peak = max(range(n), key=lambda i: rev[i] or 0)
    labels = {(0, n - 1): an.jo(rev[-1], 1), (0, peak): an.jo(rev[peak], 1)}

    def rtips(i):
        q = qs[i]
        rows = [["매출", an.won(rev[i]) + " 원", "var(--data)"]]
        g, qq = q["ratios"].get("revenue_growth_pct"), q["ratios"].get("qoq_growth_pct")
        if g is not None:
            rows.append(["1년 전 같은 분기 대비", an.signed(g) + "%", None])
        if qq is not None:
            rows.append(["직전 분기 대비", an.signed(qq) + "%", None])
        return an.qname(q), rows, ("누적 보고서끼리 빼서 계산한 분기" if q["derived"] else None)

    f1 = figure("fig-q-revenue", "분기 매출", "최근 12개 분기 · 각 분기 3개월 실적 · 단위: 조 원",
                column_chart(xl, [{"values": in_jo(rev), "color": "--data"}], ticks_fmt=tick_jo, tips=rtips,
                             labels=labels, height=190),
                table_html=data_table(["분기", "매출(억 원)", "1년 전 대비(%)", "직전 분기 대비(%)"],
                                      [[short_q(q), (eok(rev[i]), rev[i]),
                                        (an.signed(q["ratios"].get("revenue_growth_pct")), q["ratios"].get("revenue_growth_pct")),
                                        (an.signed(q["ratios"].get("qoq_growth_pct")), q["ratios"].get("qoq_growth_pct"))]
                                       for i, q in enumerate(qs)]))

    op = [q["values"].get("operating_profit") for q in qs]
    cf = [q["values"].get("operating_cashflow") for q in qs]
    labels = {(0, n - 1): an.jo(op[-1], 2), (1, n - 1): an.jo(cf[-1], 2)}
    lo_i = min(range(n), key=lambda i: op[i] if op[i] is not None else 0)
    if op[lo_i] is not None and op[lo_i] < 0 and lo_i != n - 1:
        labels[(0, lo_i)] = an.jo(op[lo_i], 2)

    def ctips(i):
        rows = [["영업이익", an.won(op[i]) + " 원", "var(--s1)"], ["영업활동현금흐름", an.won(cf[i]) + " 원", "var(--s2)"]]
        gap = None if None in (op[i], cf[i]) else cf[i] - op[i]
        return an.qname(qs[i]), rows, (f"현금 − 이익 = {an.won(gap)} 원" if gap is not None else None)

    f2 = figure("fig-q-cash", "분기 영업이익 vs 영업현금흐름", "최근 12개 분기 · 단위: 조 원 · 붉은 바탕 = 손실·유출",
                column_chart(xl, [{"values": in_jo(op), "color": "--s1"}, {"values": in_jo(cf), "color": "--s2"}],
                             ticks_fmt=tick_jo, tips=ctips, labels=labels, neg_zone=True, height=190),
                legend_html=legend([("영업이익", "--s1", "box"), ("영업활동현금흐름", "--s2", "box")]),
                table_html=data_table(["분기", "영업이익(억 원)", "영업활동현금흐름(억 원)"],
                                      [[short_q(q), (eok(op[i]), op[i]), (eok(cf[i]), cf[i])] for i, q in enumerate(qs)]))

    bq = [q for q in balance_rows(v)][-12:]
    f3 = ""
    if len(bq) >= 2:
        xb = [quarter_label(q, i == 0 or q["kind"] == "Q1") for i, q in enumerate(bq)]
        debt = [q["ratios"].get("debt_to_equity_pct") for q in bq]
        hi_i = max(range(len(bq)), key=lambda i: debt[i] or 0)
        dl = {len(bq) - 1: f"{an.pct(debt[-1], 0)}%", hi_i: f"{an.pct(debt[hi_i], 0)}%", 0: f"{an.pct(debt[0], 0)}%"}

        def dtips(i):
            q = bq[i]
            qv = q["values"]
            rows = [["부채비율", an.pct(debt[i]) + "%", "var(--data)"],
                    ["유동비율", an.pct(q["ratios"].get("current_ratio_pct")) + "%", None],
                    ["부채", an.won(qv.get("liabilities")) + " 원", None], ["자본", an.won(qv.get("equity")) + " 원", None]]
            return f"{q['year']}년 {q['month']}월 말", rows, None

        f3 = figure("fig-q-debt", "분기말 부채비율", "최근 12개 분기말 · 부채 ÷ 자본 × 100 · 점선 = 100%·200%",
                    line_chart(xb, debt, color="--data", ticks_fmt=tick_plain, tips=dtips, labels=dl,
                               refs=[(100, "", "left"), (200, "", "left")], height=190),
                    table_html=data_table(["분기말", "부채비율(%)", "유동비율(%)"],
                                          [[f"{q['year']}.{q['month']:02d}", (an.pct(debt[i]), debt[i]),
                                            (an.pct(q["ratios"].get("current_ratio_pct")), q["ratios"].get("current_ratio_pct"))]
                                           for i, q in enumerate(bq)]))
    return f'<div class="grid-3">{f1}{f2}{f3}</div>'


# ---------------------------------------------------------------------------
# 6. 화면 위쪽: 질문별 차트 (연간)
# ---------------------------------------------------------------------------
def per100_fig(v, notes):
    years = v.years
    totals = [v.per100(t, "cost_of_sales") + v.per100(t, "sga") for t in years
              if v.per100(t, "cost_of_sales") is not None and v.per100(t, "sga") is not None]
    scale_max = max(105, math.ceil((max(totals) + 1) / 5) * 5) if totals else 105

    def x(val):
        return val / scale_max * 100

    rows_html, table_rows = [], []
    for t in years:
        c, s, o = v.per100(t, "cost_of_sales"), v.per100(t, "sga"), v.per100(t, "operating_profit")
        if None in (c, s, o):
            continue
        segs = [f'<i class="seg" style="left:0;width:calc({x(c):.3f}% - 2px);--c:var(--cost)"></i>']
        if o >= 0:
            segs.append(f'<i class="seg" style="left:{x(c):.3f}%;width:calc({x(s):.3f}% - 2px);--c:var(--sga)"></i>')
            segs.append(f'<i class="seg end" style="left:{x(c + s):.3f}%;width:{x(o):.3f}%;--c:var(--s1)"></i>')
        else:
            segs.append(f'<i class="seg end" style="left:{x(c):.3f}%;width:{x(s):.3f}%;--c:var(--sga)"></i>')
            segs.append(f'<i class="over" style="left:{x(100):.3f}%;width:{x(-o):.3f}%"></i>')
        tip_rows = [["원가", f"{an.pct(c)}원", "var(--cost)"], ["판관비", f"{an.pct(s)}원", "var(--sga)"],
                    ["영업이익" if o >= 0 else "영업손실", f"{an.signed(o)}원", "var(--s1)" if o >= 0 else "var(--neg)"]]
        note = f"원가율 {an.pct(c)}% · 영업이익 {an.won(v.a(t, 'operating_profit'))} 원"
        rows_html.append(f'<div class="hb-row"{tip_attr(f"{t}년 매출 100원당", tip_rows, note)}>'
                         f'<span class="hb-y">{t}</span><span class="hb-t">{"".join(segs)}</span>'
                         f'<span class="hb-v{" neg" if o < 0 else ""}">{an.signed(o)}원</span></div>')
        table_rows.append([str(t), (an.pct(c), c), (an.pct(s), s), (an.signed(o), o)])
    ticks = "".join(f'<span style="left:{x(val):.3f}%">{val}</span>' for val in (0, 25, 50, 75, 100))
    body = (f'<div class="hb" style="--x100:{x(100):.3f}%">{"".join(rows_html)}'
            f'<div class="hb-scale" aria-hidden="true"><span></span><span class="ticks">{ticks}</span>'
            f'<span class="hb-unit">남는 돈</span></div></div>')
    leg = legend([("원가", "--cost", "box"), ("판관비", "--sga", "box"), ("영업이익", "--s1", "box"),
                  ("손실(비용이 매출 100원을 넘은 만큼)", "--neg", "outline")])
    table = data_table(["연도", "원가(원)", "판관비(원)", "영업이익(원)"], table_rows)
    note = notes.get("per100") or ""
    odd = [str(t) for t in years if None not in (v.per100(t, "cost_of_sales"), v.per100(t, "sga"), v.per100(t, "operating_profit"))
           and abs(v.per100(t, "cost_of_sales") + v.per100(t, "sga") + v.per100(t, "operating_profit") - 100) > 0.3]
    if odd:
        note += (f" {'·'.join(odd)}년은 당시 회계기준에 따라 영업이익에 기타 영업손익이 들어 있어, 세 칸을 더하면 100원과 조금 다릅니다.")
    return figure("fig-per100", "매출 100원은 어디로 갔나", "매출 100원을 원가·판관비·영업이익으로 나눈 값 · 점선 = 매출 100원",
                  body, legend_html=leg, table_html=table, wide=True, note=note.strip())


def cash_figs(v, vd, notes):
    years = v.years
    xl = [year_label(t) for t in years]
    op, cf = v.series("operating_profit"), v.series("operating_cashflow")
    labels = {(1, len(years) - 1): an.jo(cf[-1], 2)}
    lo_i = min(range(len(op)), key=lambda i: op[i] if op[i] is not None else 0)
    if op[lo_i] is not None and op[lo_i] < 0:
        labels[(0, lo_i)] = an.jo(op[lo_i], 2)

    def tips(i):
        rows = [["영업이익", an.won(op[i]) + " 원", "var(--s1)"], ["영업활동현금흐름", an.won(cf[i]) + " 원", "var(--s2)"]]
        gap = None if None in (op[i], cf[i]) else cf[i] - op[i]
        return f"{years[i]}년", rows, (f"현금 − 이익 = {an.won(gap)} 원" if gap is not None else None)

    chart1 = column_chart(xl, [{"values": in_jo(op), "color": "--s1"}, {"values": in_jo(cf), "color": "--s2"}],
                          ticks_fmt=tick_jo, tips=tips, labels=labels, neg_zone=True)
    t1 = data_table(["연도", "영업이익(억 원)", "영업활동현금흐름(억 원)"],
                    [[str(t), (eok(op[i]), op[i]), (eok(cf[i]), cf[i])] for i, t in enumerate(years)])
    fig1 = figure("fig-cash", "장부상 이익 vs 실제 현금", "연간 · 단위: 조 원 · 0 아래 붉은 바탕 = 손실 또는 현금 유출",
                  chart1, legend_html=legend([("영업이익", "--s1", "box"), ("영업활동현금흐름", "--s2", "box")]),
                  table_html=t1, note=notes.get("cash"))

    rec = v.series("receivables_total")
    idx = [i for i, r in enumerate(rec) if r is not None]
    rlabels = {}
    if idx:
        rlabels = {(0, idx[0]): an.jo(rec[idx[0]]), (0, idx[-1]): an.jo(rec[idx[-1]])}
        if 2021 in years and rec[years.index(2021)] is not None:
            rlabels[(0, years.index(2021))] = an.jo(rec[years.index(2021)])

    def rtips(i):
        t = years[i]
        rows = [["받을 돈 합계", an.won(rec[i]) + " 원", "var(--data)"],
                ["매출채권", an.won(v.a(t, "trade_receivables")) + " 원", None],
                ["미청구공사", an.won(v.a(t, "contract_assets")) + " 원", None]]
        return f"{t}년 말", rows, f"매출의 {an.pct(v.a(t, 'receivables_to_revenue_pct'))}%"

    chart2 = column_chart(xl, [{"values": in_jo(rec), "color": "--data"}], ticks_fmt=tick_jo, tips=rtips, labels=rlabels)
    t2 = data_table(["연도", "매출채권(억 원)", "미청구공사(억 원)", "합계(억 원)", "매출 대비(%)"],
                    [[str(t), (eok(v.a(t, "trade_receivables")), v.a(t, "trade_receivables")),
                      (eok(v.a(t, "contract_assets")), v.a(t, "contract_assets")),
                      (eok(v.a(t, "receivables_total")), v.a(t, "receivables_total")),
                      (an.pct(v.a(t, "receivables_to_revenue_pct")), v.a(t, "receivables_to_revenue_pct"))] for t in years])
    fig2 = figure("fig-receivables", "아직 못 받은 공사비", "매출채권 + 미청구공사 · 연말 잔액 · 단위: 조 원", chart2,
                  table_html=t2, note="**매출채권**은 청구했지만 못 받은 돈, **미청구공사**는 공사는 했지만 아직 청구하지 못한 돈입니다.")
    return fig1, fig2


def signal_table(signals):
    head = ('<tr><th scope="col">연도</th><th scope="col">영업<small>본업 현금</small></th>'
            '<th scope="col">투자<small>예금·자산</small></th><th scope="col">재무<small>차입·상환</small></th>'
            '<th scope="col">한 줄 해석</th></tr>')
    rows = []
    for s in signals:
        cells = []
        for val, sg in zip(s["values"], s["signs"]):
            if sg is None:
                cells.append('<td class="na">–</td>')
                continue
            cls, arrow, word = {1: ("in", "▲", "유입"), -1: ("out", "▼", "유출"), 0: ("flat", "≈", "거의 없음")}[sg]
            cells.append(f'<td class="{cls}"><span class="ar" aria-hidden="true">{arrow}</span>'
                         f'{esc(an.jo(abs(val), 2))}<span class="sr">조 원 {word}</span></td>')
        minus = " minus" if s["signs"][0] == -1 else ""
        rows.append(f'<tr class="row{minus}"><th scope="row">{s["year"]}</th>{"".join(cells)}<td class="lab">{esc(s["label"])}</td></tr>')
    return (f'<div class="table-scroll sig" tabindex="0"><table><caption>현금흐름 신호등 · 단위: 조 원 · ▲ 들어옴 · ▼ 나감 · '
            f'≈ 거의 없음(±500억 원 미만)</caption><thead>{head}</thead><tbody>{"".join(rows)}</tbody></table></div>')


def _tips_multi(v, years, series, unit, title_fmt="{t}년"):
    def tips(i):
        t = years[i]
        rows = [[sr["name"], ("–" if sr["values"][i] is None else f"{an.pct(sr['values'][i])}{unit}"), f"var({sr['color']})"]
                for sr in series]
        return title_fmt.format(t=t), rows, None
    return tips


def margins_fig(v):
    years = v.years
    series = [{"name": "매출총이익률", "values": v.series("gross_margin_pct"), "color": "--s3"},
              {"name": "영업이익률", "values": v.series("operating_margin_pct"), "color": "--s1"},
              {"name": "EBITDA 마진", "values": v.series("ebitda_margin_pct"), "color": "--s4"},
              {"name": "순이익률", "values": v.series("net_margin_pct"), "color": "--s2"}]
    chart = multi_line_chart([year_label(t) for t in years], series, ticks_fmt=tick_plain, tips=_tips_multi(v, years, series, "%"),
                             refs=[(0, "", "left")], end_fmt=lambda x: f"{an.pct(x)}%")
    table = data_table(["연도"] + [sr["name"] + "(%)" for sr in series],
                       [[str(t)] + [(an.pct(sr["values"][i]), sr["values"][i]) for sr in series] for i, t in enumerate(years)])
    return figure("fig-margins", "이익률 네 가지", "매출 대비 % · 매출총이익률 = (매출 − 원가) ÷ 매출 · EBITDA = 영업이익 + 감가상각비",
                  chart, legend_html=legend([(sr["name"], sr["color"], "line") for sr in series]), table_html=table, wide=True,
                  note="가이드: 매출총이익률이 함께 떨어지면 가격·원가, 총이익률은 그대로인데 영업이익률만 떨어지면 판관비를 먼저 봅니다.")


def fcf_fig(v):
    years = v.years
    fcf, cfo, capex = v.series("fcf"), v.series("operating_cashflow"), v.series("capex")
    labels = {}
    idx = [i for i, x in enumerate(fcf) if x is not None]
    if idx:
        labels[(0, idx[-1])] = an.jo(fcf[idx[-1]], 2)

    def tips(i):
        rows = [["FCF", an.won(fcf[i]) + " 원", "var(--s2)"], ["영업활동현금흐름", an.won(cfo[i]) + " 원", None],
                ["CAPEX(유형·무형자산 취득)", an.won(capex[i]) + " 원", None]]
        return f"{years[i]}년", rows, "FCF = 영업활동현금흐름 − CAPEX"

    chart = column_chart([year_label(t) for t in years], [{"values": in_jo(fcf), "color": "--s2"}], ticks_fmt=tick_jo, tips=tips,
                         labels=labels, neg_zone=True)
    table = data_table(["연도", "영업활동현금흐름(억 원)", "CAPEX(억 원)", "FCF(억 원)"],
                       [[str(t), (eok(cfo[i]), cfo[i]), (eok(capex[i]), capex[i]), (eok(fcf[i]), fcf[i])] for i, t in enumerate(years)])
    return figure("fig-fcf", "투자 후 남는 현금 (FCF)", "연간 · FCF = 영업활동현금흐름 − CAPEX · 단위: 조 원", chart, table_html=table,
                  note="건설사는 설비투자가 작아서 FCF는 대부분 공사대금이 얼마나 들어왔는지(영업현금흐름)로 정해집니다.")


def debt_figs(v):
    years = v.years
    xl = [year_label(t) for t in years]
    cov = v.series("interest_coverage_x")

    def ctips(i):
        t = years[i]
        rows = [["이자보상배율", "–" if cov[i] is None else f"{an.pct(cov[i])}배", "var(--data)"],
                ["영업이익", an.won(v.a(t, "operating_profit")) + " 원", None], ["이자비용", an.won(v.a(t, "interest_expense")) + " 원", None]]
        return f"{t}년", rows, None

    idx = [i for i, x in enumerate(cov) if x is not None]
    labels = {i: f"{an.pct(cov[i])}배" for i in {idx[0], idx[-1], min(idx, key=lambda i: cov[i])}} if idx else {}
    f1 = figure("fig-coverage", "이자보상배율", "영업이익 ÷ 이자비용 · 단위: 배 · 1배 미만이면 이익으로 이자도 못 냄",
                line_chart(xl, cov, color="--data", ticks_fmt=tick_plain, tips=ctips, labels=labels,
                           refs=[(1, "1배", "left"), (3, "3배", "left")]),
                table_html=data_table(["연도", "이자보상배율(배)", "영업이익(억 원)", "이자비용(억 원)"],
                                      [[str(t), (an.pct(cov[i]), cov[i]),
                                        (eok(v.a(t, "operating_profit")), v.a(t, "operating_profit")),
                                        (eok(v.a(t, "interest_expense")), None)] for i, t in enumerate(years)]),
                note="이자비용은 공시 주석(현금흐름표 조정 항목)에서 읽었습니다.")
    nd = v.series("net_debt")
    nlabels = {}
    idx = [i for i, x in enumerate(nd) if x is not None]
    if idx:
        nlabels[(0, idx[-1])] = an.jo(nd[idx[-1]], 2)

    def ntips(i):
        t = years[i]
        nde = v.a(t, "net_debt_to_ebitda_x")
        rows = [["순차입금", an.won(nd[i]) + " 원", "var(--s3)"], ["이자부차입금", an.won(v.a(t, "borrowings_total")) + " 원", None],
                ["현금및현금성자산", an.won(v.a(t, "cash")) + " 원", None]]
        return f"{t}년 말", rows, (f"순차입금/EBITDA {an.pct(nde)}배" if nde is not None else None)

    f2 = figure("fig-netdebt", "순차입금", "연말 · 이자부차입금 − 현금및현금성자산 · 0 아래 = 순현금 · 단위: 조 원",
                column_chart(xl, [{"values": in_jo(nd), "color": "--s3"}], ticks_fmt=tick_jo, tips=ntips, labels=nlabels),
                table_html=data_table(["연도", "이자부차입금(억 원)", "현금및현금성자산(억 원)", "순차입금(억 원)", "순차입금/EBITDA(배)"],
                                      [[str(t), (eok(v.a(t, "borrowings_total")), None), (eok(v.a(t, "cash")), None),
                                        (eok(nd[i]), nd[i]),
                                        (an.pct(v.a(t, "net_debt_to_ebitda_x")),
                                         v.a(t, "net_debt_to_ebitda_x"))] for i, t in enumerate(years)]),
                note="이자부차입금 = 단기차입금 + 유동성장기부채 + 사채 + 장기차입금 (리스부채 제외).")
    debt = v.series("debt_to_equity_pct")

    def pick_labels(vals):
        idx = [i for i, x in enumerate(vals) if x is not None]
        if not idx:
            return {}
        hi_i = max(idx, key=lambda i: vals[i])
        lo_i = min(idx, key=lambda i: vals[i])
        return {i: f"{an.pct(vals[i], 0)}%" for i in {idx[0], hi_i, lo_i, idx[-1]}}

    def dtips(i):
        t = years[i]
        return f"{t}년 말", [["부채비율", f"{an.pct(debt[i])}%", "var(--data)"], ["부채", an.won(v.a(t, "liabilities")) + " 원", None],
                            ["자본", an.won(v.a(t, "equity")) + " 원", None]], None

    f3 = figure("fig-debt", "부채비율", "연말 · 부채 ÷ 자본 × 100 · 단위: %",
                line_chart(xl, debt, color="--data", ticks_fmt=tick_plain, tips=dtips, labels=pick_labels(debt),
                           refs=[(100, "100%", "left"), (200, "200%", "left")]),
                table_html=data_table(["연도", "부채비율(%)", "부채(억 원)", "자본(억 원)"],
                                      [[str(t), (an.pct(debt[i]), debt[i]), (eok(v.a(t, "liabilities")), None),
                                        (eok(v.a(t, "equity")), None)] for i, t in enumerate(years)]))
    series = [{"name": "유동비율", "values": v.series("current_ratio_pct"), "color": "--s3"},
              {"name": "당좌비율", "values": v.series("quick_ratio_pct"), "color": "--s1"}]
    f4 = figure("fig-liquidity", "유동비율 · 당좌비율", "연말 · 단위: % · 당좌비율은 재고자산을 뺀 보수적인 지급능력",
                multi_line_chart(xl, series, ticks_fmt=tick_plain, tips=_tips_multi(v, years, series, "%", "{t}년 말"),
                                 refs=[(100, "100%", "left")], end_fmt=lambda x: f"{an.pct(x, 0)}%"),
                legend_html=legend([(sr["name"], sr["color"], "line") for sr in series]),
                table_html=data_table(["연도", "유동비율(%)", "당좌비율(%)"],
                                      [[str(t)] + [(an.pct(sr["values"][i]), sr["values"][i]) for sr in series] for i, t in enumerate(years)]))
    return f1, f2, f3, f4


def returns_fig(v, vd):
    years = v.years
    rate = v.series("borrowing_rate_pct")
    tax = [fin.effective_tax_rate(v.by_year[t]["values"]) for t in years]
    after = [None if r is None else r * (1 - (tx if tx is not None else fin.DEFAULT_TAX_RATE)) for r, tx in zip(rate, tax)]
    series = [{"name": "ROIC", "values": v.series("roic_pct"), "color": "--s3"},
              {"name": "ROE", "values": v.series("roe_pct"), "color": "--s1"},
              {"name": "ROA", "values": v.series("roa_pct"), "color": "--s2"},
              {"name": "세후 차입 이자율", "values": after, "color": "--ref", "dash": True}]
    chart = multi_line_chart([year_label(t) for t in years], series, ticks_fmt=tick_plain, tips=_tips_multi(v, years, series, "%"),
                             refs=[(0, "", "left"), (an.HURDLE_ROIC, f"단순 기준 {an.HURDLE_ROIC:.0f}%", "left")],
                             end_fmt=lambda x: f"{an.pct(x)}%")
    table = data_table(["연도"] + [sr["name"] + "(%)" for sr in series] + ["지배주주 ROE(%)"],
                       [[str(t)] + [(an.pct(sr["values"][i]), sr["values"][i]) for sr in series]
                        + [(an.pct(v.a(t, "roe_owners_pct")), v.a(t, "roe_owners_pct"))] for i, t in enumerate(years)])
    leg = legend([(sr["name"], sr["color"], "dash" if sr.get("dash") else "line") for sr in series])
    return figure("fig-returns", "ROIC · ROE · ROA", "연간 · 단위: % · ROIC = 영업이익 × (1 − 실효세율) ÷ 평균 투하자본(자본총계 + 순차입금)",
                  chart, legend_html=leg, table_html=table, wide=True,
                  note="ROE·ROA는 연결 당기순이익 ÷ 평균 자본·자산. 첫해는 평균을 구할 수 없어 비어 있습니다.")


def valuation_tiles(ctx):
    """현재 주가 기준 시장가치 숫자 6칸 (대시보드 ‘시장가치’ 관점과 기업분석 보고서 7장이 함께 씀)."""
    val = ctx.get("valuation") or {}
    if not val.get("market_cap"):
        return ('<div class="card empty"><h3>주가 자료 대기 중</h3><p>주가는 GitHub Actions가 매월 실행될 때 네이버 금융(실패하면 Yahoo Finance)에서 '
                '달마다 마지막 거래일 종가를 받아 옵니다. 받는 즉시 PER·PBR·EV/EBITDA·FCF 수익률이 이 자리에 채워집니다.</p></div>')
    tiles = [("주가", f"{val['price']:,.0f}", "원", f"{an.price_when(val)} 종가"),
             ("시가총액", an.jo(val["market_cap"], 2), "조 원", f"발행주식 {val['shares']:,}주 (보통주+우선주)"),
             ("PER", "–" if val.get("per_x") is None else f"{val['per_x']:.1f}", "배", "시가총액 ÷ 최근 4개 분기 지배주주 순이익"),
             ("PBR", "–" if val.get("pbr_x") is None else f"{val['pbr_x']:.2f}", "배", f"시가총액 ÷ {val.get('balance_label', '')} 지배주주지분"),
             ("EV/EBITDA", "–" if val.get("ev_ebitda_x") is None else f"{val['ev_ebitda_x']:.1f}", "배",
              "(시가총액 + 순차입금 + 비지배지분) ÷ 최근 4개 분기 EBITDA"),
             ("FCF 수익률", "–" if val.get("fcf_yield_pct") is None else an.pct(val["fcf_yield_pct"]), "%",
              "최근 4개 분기 FCF ÷ 시가총액")]
    cells = "".join(f'<div class="vt"><p class="vt-l">{esc(a)}</p><p class="vt-v">{esc(b)}<small>{esc(c)}</small></p>'
                    f'<p class="vt-d">{esc(d)}</p></div>' for a, b, c, d in tiles)
    return f'<div class="vtiles">{cells}</div>'


def combos_section(a):
    rows = []
    for c in a.get("combos", []):
        if c["hit"] is True:
            res = '<span class="chip warn"><i class="ic" aria-hidden="true">!</i>해당</span>'
        elif c["hit"] is False:
            res = '<span class="res no">해당 없음</span>'
        else:
            res = '<span class="res na">판단 불가</span>'
        years = ", ".join(str(y) for y in c["years"][-6:]) or "–"
        tr = '<tr class="hit">' if c["hit"] else "<tr>"
        rows.append(f'{tr}<th scope="row">{esc(c["name"])}</th><td class="left">{res}'
                    f'<span class="det">{esc(c["detail"])}</span></td><td class="left wrap">{esc(c["meaning"])}</td>'
                    f'<td class="left wrap">{esc(c["check"])}</td><td class="left">{esc(years)}</td></tr>')
    basis = a["combos"][0]["basis"] if a.get("combos") else ""
    head = ('<tr><th scope="col" class="corner">지표 조합</th><th scope="col" class="left">' + esc(basis) + ' 결과</th>'
            '<th scope="col" class="left">가능한 해석 (가이드)</th><th scope="col" class="left">우선 확인할 내용 (가이드)</th>'
            '<th scope="col" class="left">해당했던 해</th></tr>')
    hits = [c for c in a.get("combos", []) if c["hit"]]
    lead = (f"가이드 5장의 여덟 가지 조합을 최근 두 해({basis})로 자동 점검했습니다. 이번에 해당하는 조합은 "
            + (", ".join(f"**{c['name']}**" for c in hits) if hits else "없습니다") + ("입니다." if hits else "."))
    return (f'<section id="combos" aria-labelledby="h-combos">'
            + section_head("combos", "Signals", "지표 조합 점검", "숫자 두 개를 같이 보면 보이는 신호", lead,
                           "‘해당했던 해’는 2010년 이후 연도별로 같은 조합이 나타난 해입니다. 해당한다고 바로 문제라는 뜻은 아니고, 오른쪽 내용을 확인하라는 신호입니다.")
            + f'<div class="table-scroll combo" tabindex="0"><table><caption class="sr">지표 조합 점검</caption><thead>{head}</thead>'
              f'<tbody>{"".join(rows)}</tbody></table></div></section>')


def acts_html(items):
    out = []
    for item in items:
        facts = "".join(f"<li>{esc(f)}</li>" for f in item["facts"])
        why_text, srcs = item["why"]
        links = " · ".join(src_link(s) for s in srcs)
        out.append(f'<li class="act"><p class="act-years">{esc(item["years"])}</p><h3>{esc(item["title"])}</h3>'
                   f'<ul>{facts}</ul><p class="act-why"><span class="tag">배경</span>{esc(why_text)} '
                   f'<span class="src">출처: {links}</span></p></li>')
    return f'<ol class="acts">{"".join(out)}</ol>'


# ---------------------------------------------------------------------------
# 7. 화면 아래쪽: Annual · Half-year · Quarterly 표
# ---------------------------------------------------------------------------
# (그룹 이름, 단위 설명, [(키, 표시 이름, 형식)]) · 형식: amt=억 원, won=원, pct=%, x=배, x2=배(소수 둘째 자리), d=일
# 교수님 가이드의 분류(손익·재무상태·현금흐름 / 수익성·유동성·안정성·활동성·성장성·시장가치)를 따릅니다.
TABLE_GROUPS = [
    ("손익", "억 원", [("revenue", "매출액", "amt"), ("cost_of_sales", "매출원가", "amt"), ("gross_profit", "매출총이익", "amt"),
                     ("sga", "판관비", "amt"), ("operating_profit", "영업이익", "amt"), ("ebitda", "EBITDA", "amt"),
                     ("pretax_income", "세전이익", "amt"), ("net_income", "당기순이익", "amt"),
                     ("net_income_owners", "지배주주 순이익", "amt")]),
    ("재무상태 · 기말", "억 원", [("assets", "자산총계", "amt"), ("current_assets", "유동자산", "amt"),
                           ("cash", "현금및현금성자산", "amt"), ("trade_receivables", "매출채권", "amt"),
                           ("contract_assets", "미청구공사", "amt"), ("inventories", "재고자산", "amt"), ("ppe", "유형자산", "amt"),
                           ("liabilities", "부채총계", "amt"), ("current_liabilities", "유동부채", "amt"),
                           ("borrowings_total", "이자부차입금", "amt"), ("net_debt", "순차입금", "amt"),
                           ("equity", "자본총계", "amt"), ("equity_owners", "지배주주지분", "amt")]),
    ("현금흐름", "억 원", [("operating_cashflow", "영업활동", "amt"), ("investing_cashflow", "투자활동", "amt"),
                       ("financing_cashflow", "재무활동", "amt"), ("capex", "CAPEX", "amt"), ("fcf", "FCF", "amt")]),
    ("수익성", "%", [("gross_margin_pct", "매출총이익률", "pct"), ("operating_margin_pct", "영업이익률", "pct"),
                    ("net_margin_pct", "순이익률", "pct"), ("ebitda_margin_pct", "EBITDA 마진", "pct"), ("roa_pct", "ROA", "pct"),
                    ("roe_pct", "ROE", "pct"), ("roe_owners_pct", "지배주주 ROE", "pct"), ("roic_pct", "ROIC", "pct")]),
    ("유동성·안정성", "", [("current_ratio_pct", "유동비율|%", "pct"), ("quick_ratio_pct", "당좌비율|%", "pct"),
                       ("debt_to_equity_pct", "부채비율|%", "pct"), ("equity_ratio_pct", "자기자본비율|%", "pct"),
                       ("borrowing_dependency_pct", "차입금의존도|%", "pct"), ("interest_coverage_x", "이자보상배율|배", "x"),
                       ("net_debt_to_ebitda_x", "순차입금/EBITDA|배", "x")]),
    ("활동성·성장성", "", [("revenue_growth_pct", "매출증가율|%", "pct"), ("qoq_growth_pct", "직전 분기 대비|%", "pct"),
                       ("asset_turnover_x", "총자산회전율|회", "x2"), ("dso_days", "DSO|일", "d"), ("dio_days", "DIO|일", "d"),
                       ("dpo_days", "DPO|일", "d"), ("ccc_days", "CCC|일", "d"), ("cfo_to_ni_x", "CFO/순이익|배", "x")]),
    ("시장가치 · 연말 주가", "", [("price_close", "연말 주가|원", "won"), ("market_cap", "시가총액|억 원", "amt"),
                            ("per_x", "PER|배", "x"), ("pbr_x", "PBR|배", "x2"), ("ev_ebitda_x", "EV/EBITDA|배", "x"),
                            ("fcf_yield_pct", "FCF 수익률|%", "pct")]),
    ("건설업 참고", "%", [("cost_ratio_pct", "원가율", "pct"), ("sga_ratio_pct", "판관비율", "pct"),
                       ("receivables_to_revenue_pct", "받을 돈/매출", "pct"), ("borrowing_rate_pct", "차입 이자율", "pct")]),
]
GROWTH_NAMES = {"annual": "매출증가율|% · 전년 대비", "half": "매출증가율|% · 전년 같은 반기 대비",
                "quarter": "매출증가율|% · 전년 같은 분기 대비"}
SOURCE_BADGES = {"document": ("원문", "공시 원문 표(XBRL)에서 읽은 숫자"),
                 "document-prior": ("원문", "다음 보고서 원문의 비교 열에서 읽은 숫자"),
                 "api-prior": ("비교", "다음 해 보고서(API)의 비교 열 숫자")}
CELL_HINTS = {"net_income_owners": "비지배지분 몫을 뺀 순이익", "contract_assets": "공사는 했지만 아직 청구하지 못한 금액",
              "borrowings_total": "단기차입금 + 유동성장기부채 + 사채 + 장기차입금", "net_debt": "이자부차입금 − 현금및현금성자산",
              "ebitda": "영업이익 + 감가상각비(유형·사용권·투자부동산) + 무형자산상각비", "capex": "유형자산 취득 + 무형자산 취득",
              "fcf": "영업활동현금흐름 − CAPEX", "roic_pct": "영업이익 × (1 − 실효세율) ÷ 평균(자본총계 + 순차입금)",
              "quick_ratio_pct": "(유동자산 − 재고자산) ÷ 유동부채", "borrowing_dependency_pct": "이자부차입금 ÷ 자산총계",
              "interest_coverage_x": "영업이익 ÷ 이자비용", "net_debt_to_ebitda_x": "순차입금 ÷ EBITDA",
              "asset_turnover_x": "매출액 ÷ 평균 자산총계", "dso_days": "평균 매출채권 ÷ 매출액 × 365",
              "dio_days": "평균 재고자산 ÷ 매출원가 × 365", "dpo_days": "평균 매입채무 ÷ 매출원가 × 365",
              "ccc_days": "DSO + DIO − DPO", "cfo_to_ni_x": "영업활동현금흐름 ÷ 당기순이익 (순이익이 0 이하이면 계산 안 함)",
              "per_x": "연말 시가총액 ÷ 지배주주 순이익", "pbr_x": "연말 시가총액 ÷ 지배주주지분",
              "ev_ebitda_x": "(시가총액 + 순차입금 + 비지배지분) ÷ EBITDA", "fcf_yield_pct": "FCF ÷ 시가총액",
              "borrowing_rate_pct": "이자비용 ÷ 평균 이자부차입금", "roe_owners_pct": "지배주주 순이익 ÷ 평균 지배주주지분"}
SOURCE_NOTE_TEXTS = {"일부 숫자는 다음 해 보고서(API)의 비교 열", "공시 원문 표에서 읽은 숫자",
                     "일부 숫자는 다음 보고서 원문의 비교 열"}


def row_badges(r):
    out = []
    if r["derived"]:
        out.append('<span class="bd" title="누적 보고서끼리 빼서 계산한 기간">계산</span>')
    seen = set()
    for src in r["sources"]:
        if src in SOURCE_BADGES and SOURCE_BADGES[src][0] not in seen:
            seen.add(SOURCE_BADGES[src][0])
            out.append(f'<span class="bd" title="{esc(SOURCE_BADGES[src][1])}">{SOURCE_BADGES[src][0]}</span>')
    notes = [w for w in r["warnings"] if w not in SOURCE_NOTE_TEXTS]
    if notes:
        out.append(f'<span class="bd warn" title="{esc(" / ".join(notes))}">주의</span>')
    return "".join(out)


def fmt_cell(val, typ):
    if val is None:
        return "–"
    if typ == "amt":
        return eok(val)
    if typ == "won":
        return an._m(f"{val:,.0f}")
    if typ == "pct":
        return an.pct(val)
    if typ == "x":
        return an._m(f"{val:,.1f}")
    if typ == "x2":
        return an._m(f"{val:,.2f}")
    if typ == "d":
        return an._m(f"{val:,.0f}")
    return str(val)


def big_table(tid, rows, kind, caption):
    """기간 하나가 한 줄. 최신 기간이 맨 위. 비어 있는 열은 빼고, 열 묶음별로 골라 볼 수 있습니다."""
    rows = list(reversed(rows))

    def get(r, k):
        return r["values"].get(k) if k in r["values"] else r["ratios"].get(k)

    groups = []
    for gi, (name, unit, cols) in enumerate(TABLE_GROUPS):
        cols = [(k, GROWTH_NAMES[kind] if k == "revenue_growth_pct" else lab, typ) for k, lab, typ in cols
                if any(get(r, k) is not None for r in rows)]
        if cols:
            groups.append((gi, name + (f" · {unit}" if unit else ""), cols))
    head1 = ['<th scope="col" rowspan="2" class="corner">기간</th>']
    head2 = []
    for gi, gname, cols in groups:
        head1.append(f'<th scope="colgroup" colspan="{len(cols)}" class="gs" data-g="{gi}">{esc(gname)}</th>')
        for j, (k, lab, _) in enumerate(cols):
            hint = CELL_HINTS.get(k)
            title = f' title="{esc(hint)}"' if hint else ""
            gs = " gs" if j == 0 else ""
            name, _, unit = lab.partition("|")
            label = f"{esc(name)}<small>{esc(unit)}</small>" if unit else esc(name)
            head2.append(f'<th scope="col"{title} class="c{gs}" data-g="{gi}">{label}</th>')
    body = []
    for r in rows:
        link = (f'<a href="{DART_VIEW}{esc(r["receipt"])}" target="_blank" rel="noopener" '
                f'title="{esc((r["report_name"] or "").strip())} 원문 보기">{esc(r["label"])}</a>'
                if r.get("receipt") else esc(r["label"]))
        cells = [f'<th scope="row"><span class="pl">{link}</span>{row_badges(r)}</th>']
        for gi, _, cols in groups:
            for j, (k, _, typ) in enumerate(cols):
                val = get(r, k)
                cls = ["gs"] if j == 0 else []
                if val is None:
                    cls.append("na")
                elif val < 0:
                    cls.append("neg")
                c = f' class="{" ".join(cls)}"' if cls else ""
                cells.append(f'<td{c} data-g="{gi}">{fmt_cell(val, typ)}</td>')
        body.append("<tr>" + "".join(cells) + "</tr>")
    chips = "".join(f'<button type="button" data-g="{gi}" aria-pressed="false">{esc(TABLE_GROUPS[gi][0])}</button>'
                    for gi, _, _ in groups)
    toggles = (f'<div class="gtoggle" role="group" aria-label="열 묶음 고르기" hidden>'
               f'<button type="button" data-g="" aria-pressed="true">전체</button>{chips}</div>')
    return (f'{toggles}<div class="table-scroll big tall" tabindex="0" id="{tid}-table"><table><caption class="sr">{esc(caption)}</caption>'
            f'<thead><tr class="g">{"".join(head1)}</tr><tr class="c">{"".join(head2)}</tr></thead>'
            f'<tbody>{"".join(body)}</tbody></table></div>')


def table_section(sid, en, ko, title, desc, rows, kind, csv_name):
    if not rows:
        return ""
    first, last = rows[0]["label"], rows[-1]["label"]
    files = (f'<a href="../data/financials/{csv_name}" download>CSV 내려받기 ↓</a>'
             f'<a href="../data/financials/dashboard.json">JSON ↗</a>')
    return (f'<section id="{sid}" aria-labelledby="h-{sid}" class="tbl-sec"><div class="tbl-head">'
            f'<div>{eyebrow(en, ko)}<h2 id="h-{sid}">{esc(title)}</h2><p>{rich(desc)}</p></div>'
            f'<div class="tbl-meta"><span class="count">{len(rows)}개 기간 · {esc(first)} ~ {esc(last)}</span>{files}</div></div>'
            f'{big_table(sid, rows, kind, title)}</section>')


# ---------------------------------------------------------------------------
# 8. 화면 아래쪽: 자료·검증, 동종업계
# ---------------------------------------------------------------------------
CAVEATS = [
    "모든 숫자는 연결재무제표(현대건설 + 현대엔지니어링 등 자회사) 기준입니다. 당기순이익은 비지배지분 몫을 포함합니다.",
    "2분기·3분기·4분기와 하반기 실적은 공시된 누적 숫자끼리 빼서 계산했습니다(예: 4분기 = 연간 − 3분기 누적). "
    "누적 보고서 중 하나가 정정됐으면 정정 효과가 그 분기에 섞일 수 있어 표에 ‘주의’로 표시했습니다.",
    "2010~2014년(분·반기는 2015년까지)은 OpenDART 재무제표 API가 없어 공시 원문의 XBRL 재무제표 표에서 읽었습니다. "
    "2010년 숫자는 K-IFRS를 처음 적용한 2011년 보고서의 비교 열이고, 2010년 분·반기말 재무상태표는 공시에 없습니다.",
    "감가상각비·이자비용은 재무제표 본문에 없어 연결재무제표 주석(현금흐름표 조정 항목)에서 읽었습니다. "
    "2010~2013년 분·반기 주석에는 이 표가 없어 그 기간의 EBITDA·이자보상배율은 비어 있습니다.",
    "지배주주 순이익은 원문 표에서 같은 이름의 줄이 여러 번 나와 2010~2014년은 비워 두었습니다.",
    "주가는 네이버 금융(실패하면 Yahoo Finance)의 달마다 마지막 거래일 종가(아직 끝나지 않은 달은 받은 날까지), 주식수는 OpenDART ‘주식의 총수 현황’(2015년부터)입니다. "
    "네이버 금융의 과거 주가는 권리 변동을 반영한 수정주가라 그때 실제 거래 가격과 조금 다를 수 있고, "
    "우선주도 보통주 주가로 계산해 시가총액이 조금 다를 수 있습니다.",
    "판정(성장·주의 등)은 화면 아래 판정 기준의 단순 규칙입니다. 투자 판단의 근거로 쓰기에는 정보가 부족합니다.",
    "동종기업은 사업 구성이 달라(삼성물산의 상사·바이오 등) 연결 전체 숫자를 그대로 비교하면 차이가 과장될 수 있습니다.",
]
METHOD = [
    "정의는 교수님 자료 ‘재무제표·재무비율 실무가이드’를 따랐습니다. ROA·ROE·ROIC·회전율처럼 손익과 잔액을 함께 쓰는 지표는 "
    "전년 말과 올해 말의 평균 잔액을 쓰고, 그래서 연간 표에만 표시합니다.",
    "수익성: 매출총이익률·영업이익률·순이익률·EBITDA 마진 = 각 이익 ÷ 매출 · ROA = 순이익 ÷ 평균 자산 · ROE = 순이익 ÷ 평균 자본 · "
    "ROIC = 영업이익 × (1 − 실효세율) ÷ 평균 투하자본(자본총계 + 순차입금)",
    "유동성·안정성: 유동비율 = 유동자산 ÷ 유동부채 · 당좌비율 = (유동자산 − 재고자산) ÷ 유동부채 · 부채비율 = 부채 ÷ 자본 · "
    "자기자본비율 = 자본 ÷ 자산 · 차입금의존도 = 이자부차입금 ÷ 자산 · 이자보상배율 = 영업이익 ÷ 이자비용 · 순차입금/EBITDA",
    "활동성·성장성: 총자산회전율 = 매출 ÷ 평균 자산 · DSO = 평균 매출채권 ÷ 매출 × 365 · DIO = 평균 재고자산 ÷ 매출원가 × 365 · "
    "DPO = 평균 매입채무 ÷ 매출원가 × 365(외상매입액 대신 매출원가) · CCC = DSO + DIO − DPO · 매출증가율 · CFO/순이익",
    "현금흐름: CAPEX = 유형자산 취득 + 무형자산 취득 · FCF = 영업활동현금흐름 − CAPEX · "
    "순차입금 = 이자부차입금(단기차입금 + 유동성장기부채 + 사채 + 장기차입금) − 현금및현금성자산",
    "EBITDA = 영업이익 + 감가상각비(유형자산·사용권자산·투자부동산·운휴자산) + 무형자산상각비",
    "시장가치: 시가총액 = 월말 보통주 종가 × 발행주식수(보통주+우선주) · PER = 시가총액 ÷ 지배주주 순이익 · PBR = 시가총액 ÷ 지배주주지분 · "
    "EV/EBITDA = (시가총액 + 순차입금 + 비지배지분) ÷ EBITDA · FCF 수익률 = FCF ÷ 시가총액",
    "건설업 참고: 받을 돈 = 매출채권 + 미청구공사 · 미리 받은 돈 = 초과청구공사 + 공사및분양선수금 · 차입 이자율 = 이자비용 ÷ 평균 이자부차입금",
    "금액은 표에서 억 원(반올림), CSV에서는 원 단위 그대로입니다. 분모가 0 이하이거나 숫자가 없으면 ‘–’입니다.",
]
STATUS_ICON = {"ok": ("✓", "반영"), "part": ("△", "일부")}


def notes_section(ctx, a):
    lg = ctx.get("legacy") or {}
    q, h, y = ctx["quarters"], ctx["halves"], ctx["annual"]
    coverage = []
    if y:
        coverage.append(f"연간 {len(y)}개 ({y[0]['year']}~{y[-1]['year']}년)")
    if h:
        coverage.append(f"반기 {len(h)}개")
    if q:
        coverage.append(f"분기 {len(q)}개 ({short_q(q[0])}~{short_q(q[-1])})")
    check = [f"정기보고서 {ctx['filing_count']}건(정정 포함 최신본) 목록 확인, 원문 ZIP {ctx['archives']}건 저장소에 보관",
             "표에 실린 기간: " + ", ".join(coverage)]
    if lg.get("checked"):
        check.append(f"원문 추출 정확도: 2015~2016년 보고서에서 원문 표로 읽은 숫자와 API 숫자를 {lg['checked']}개 비교해 "
                     f"{lg['matched']}개 일치 ({lg['matched'] / lg['checked'] * 100:.0f}%)")
    if lg.get("filled_periods"):
        check.append(f"원문으로 채운 기간 {len(lg['filled_periods'])}개 ({lg['filled_periods'][0]}~{lg['filled_periods'][-1]})")
    check.append("모든 기간에서 자산 = 부채 + 자본이 맞는지 확인했습니다. 맞지 않으면 그 기간 표에 ‘주의’가 붙습니다.")
    for m in (lg.get("mismatches") or [])[:5]:
        check.append(f"불일치: {m}")
    rules = "".join(f"<li>{esc(r)}</li>" for r in a.get("rules", an.VERDICT_RULES))
    method = "".join(f"<li>{esc(m)}</li>" for m in METHOD)
    caveats = "".join(f"<li>{esc(c)}</li>" for c in CAVEATS)
    lf = ctx.get("latest_filing")
    dart_links = [("OpenDART 재무제표 API 설명", "https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020"),
                  ("OpenDART 공시검색 API 설명", "https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001"),
                  ("OpenDART 공시서류 원본 API 설명", "https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003"),
                  ("OpenDART 주식의 총수 현황 API 설명", "https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS002&apiId=2020002"),
                  ("네이버 금융 현대건설 시세", f"https://finance.naver.com/item/sise.naver?code={ctx['company']['stock_code']}")]
    if lf:
        dart_links.insert(0, (f"가장 최근 반영 보고서: {lf['report_nm'].strip()}", DART_VIEW + lf["rcept_no"]))
    links = "".join(f'<li><a href="{esc(u)}" target="_blank" rel="noopener">{esc(n)} ↗</a></li>' for n, u in dart_links)
    news = "".join(f"<li>{src_link(k)}</li>" for k in an.SOURCES)
    rank = ctx["company"].get("rank", {})
    if rank.get("source_url"):
        news += (f'<li><a href="{esc(rank["source_url"])}" target="_blank" rel="noopener">'
                 f'{esc(rank["source_name"])} (시공능력평가 순위) ↗</a></li>')
    nr = ctx.get("notes") or {}
    if nr.get("found"):
        check.append(f"감가상각비·이자비용: 보고서 {nr['parsed']}건 중 {nr['found']}건의 연결 주석에서 읽음"
                     + (f", {len(nr['from_prior'])}개 기간은 다음 보고서의 비교 열로 보충" if nr.get("from_prior") else ""))
    val = ctx.get("valuation") or {}
    if val.get("as_of"):
        check.append(f"주가: {val.get('source', '')}에서 {val.get('fetched', '')}에 받은 달마다 마지막 거래일 종가 (최근 {val['as_of']})")
    rows = "".join(f'<tr><th scope="row">{esc(c["item"])}</th><td class="st {c["status"]}"><span aria-hidden="true">{STATUS_ICON[c["status"]][0]}</span>'
                   f'{STATUS_ICON[c["status"]][1]}</td><td class="left wrap">{esc(c["how"])}</td></tr>' for c in a.get("checklist", []))
    checklist = (f'<div class="table-scroll ck"><table><caption>교수님 가이드 6장 ‘실무 검토 체크리스트’에 대한 이 대시보드의 반영 정도</caption>'
                 f'<thead><tr><th scope="col">검토 항목</th><th scope="col">반영</th><th scope="col" class="left">어떻게</th></tr></thead>'
                 f'<tbody>{rows}</tbody></table></div>') if rows else ""
    return (f'<section id="notes" aria-labelledby="h-notes">'
            f'{section_head("notes", "Notes", "자료와 검증", "숫자는 어디서 왔고, 어떻게 계산했나")}{checklist}'
            f'<div class="notes"><div class="note-card"><h3>자료 검증</h3><ul>{"".join(f"<li>{esc(c)}</li>" for c in check)}</ul></div>'
            f'<div class="note-card"><h3>계산 방법</h3><ul>{method}</ul></div>'
            f'<div class="note-card"><h3>판정 기준</h3><ul>{rules}</ul></div>'
            f'<div class="note-card"><h3>해석할 때 주의할 점</h3><ul>{caveats}</ul></div>'
            f'<div class="note-card"><h3>출처</h3><ul>{links}</ul><h3 class="mt">배경 설명에 쓴 기사</h3><ul>{news}</ul></div>'
            f'</div></section>')


def peer_table_rows(ctx):
    """[(행, 자기회사 여부)] 시공능력평가 순위 순."""
    cfg = ctx["company"]
    peers = ctx.get("peers") or []
    years = [p["year"] for p in peers if p.get("year")]
    year = max(years) if years else None
    own = None
    if ctx["annual"]:
        cands = [r for r in ctx["annual"] if r["year"] == year] if year else []
        base = cands[0] if cands else ctx["annual"][-1]
        v = base["values"]
        own = {"name": cfg["name"], "stock_code": cfg["stock_code"], "rank": cfg.get("rank", {}).get("own"),
               "business": cfg.get("business", ""), "note": "", "year": base["year"],
               "values": v, "receipt": base.get("receipt", ""),
               "ratios": {"operating_margin_pct": base["ratios"].get("operating_margin_pct"),
                          "net_margin_pct": base["ratios"].get("net_margin_pct"),
                          "debt_to_equity_pct": base["ratios"].get("debt_to_equity_pct"),
                          "current_ratio_pct": base["ratios"].get("current_ratio_pct"),
                          "roe_pct": fin.ratio(v.get("net_income"), v.get("equity"))},
               "market": ctx.get("own_market") or {}}
    rows = [(p, False) for p in peers] + ([(own, True)] if own else [])
    rows.sort(key=lambda x: (x[0].get("rank") or 99))
    return rows, year


def peer_summary(rows, name):
    """자기 회사가 동종기업 가운데 몇 번째인지 한 문장으로 만듭니다."""
    have = [(p, own) for p, own in rows if p.get("year") and p["values"].get("revenue")]
    me = next((p for p, own in have if own), None)
    if not me or len(have) < 3:
        return ""

    def place(key, src, reverse):
        vals = [(p[src].get(key), own) for p, own in have if p[src].get(key) is not None]
        order = sorted(vals, key=lambda x: x[0], reverse=reverse)
        return next((i for i, (_, own) in enumerate(order, 1) if own), None), len(order)

    rev, n1 = place("revenue", "values", True)
    om, n2 = place("operating_margin_pct", "ratios", True)
    debt, n3 = place("debt_to_equity_pct", "ratios", False)
    parts = []
    if rev:
        parts.append(f"매출은 {n1}개사 중 **{rev}위**")
    if om:
        parts.append(f"영업이익률은 **{om}위**")
    if debt:
        parts.append(f"부채비율은 낮은 순서로 **{debt}위**")
    return f"{me['year']}년 사업보고서 기준으로 {name}의 " + ", ".join(parts) + "입니다." if parts else ""


# (키, 이름, 형식, 어디서) · 어디서: values=재무제표 금액, ratios=비율, market=주가 기준
PEER_COLS = [("revenue", "매출액", "amt", "values"), ("operating_profit", "영업이익", "amt", "values"),
             ("net_income", "당기순이익", "amt", "values"), ("operating_margin_pct", "영업이익률", "pct", "ratios"),
             ("net_margin_pct", "순이익률", "pct", "ratios"), ("roe_pct", "ROE", "pct", "ratios"),
             ("debt_to_equity_pct", "부채비율", "pct", "ratios"), ("current_ratio_pct", "유동비율", "pct", "ratios"),
             ("per_x", "PER", "x", "market"), ("pbr_x", "PBR", "x2", "market")]
PEER_UNITS = {"amt": "억 원", "pct": "%", "x": "배", "x2": "배"}


def peer_value(p, key, where):
    return (p.get(where) or {}).get(key)


def peers_section(ctx):
    rows, year = peer_table_rows(ctx)
    rank = ctx["company"].get("rank", {})
    head = ('<tr><th scope="col" class="corner">회사 · 주요 사업</th><th scope="col">시평 순위</th><th scope="col">기준</th>'
            + "".join(f'<th scope="col">{esc(lab)}<small>{PEER_UNITS[t]}</small></th>' for _, lab, t, _ in PEER_COLS)
            + "</tr>")
    body = []
    for p, own in rows:
        name = esc(p["name"])
        if p.get("receipt"):
            name = f'<a href="{DART_VIEW}{esc(p["receipt"])}" target="_blank" rel="noopener">{name}</a>'
        cells = [f'<th scope="row"><span class="pn">{name}<span class="code">{esc(p["stock_code"])}</span></span>'
                 f'<span class="biz">{esc(p.get("business", ""))}</span></th>',
                 f'<td>{esc(p["rank"]) + "위" if p.get("rank") else "–"}</td>',
                 f'<td>{esc(p["year"]) + "년" if p.get("year") else "수집 전"}</td>']
        for k, _, t, where in PEER_COLS:
            val = peer_value(p, k, where)
            text = fmt_cell(val, t)
            cls = "na" if val is None else ("neg" if val < 0 else "")
            cells.append(f'<td class="{cls}">{text}</td>' if cls else f"<td>{text}</td>")
        body.append(('<tr class="self">' if own else "<tr>") + "".join(cells) + "</tr>")
    cautions = "".join(f"<li><b>{esc(p['name'])}</b> · {esc(p['note'])}</li>" for p, own in rows if not own and p.get("note"))
    missing = [p["name"] for p, own in rows if not own and not p.get("year")]
    foot = f'<ul class="plain small peer-notes">{cautions}</ul>' if cautions else ""
    if missing:
        foot += (f'<p class="chart-note">{esc(", ".join(missing))}의 숫자는 다음 자동 실행 때 OpenDART에서 받아 채웁니다. '
                 f'(동종기업은 가장 최근 사업보고서 1개만 받습니다)</p>')
    basis = (f"순위는 {rank.get('year', '')}년 {rank.get('basis', '시공능력평가')} 기준"
             f"({rank.get('source_name', '')}). " if rank else "")
    as_of = next((p["market"].get("as_of") for p, _ in rows if (p.get("market") or {}).get("as_of")), None)
    desc = (f"{basis}재무 숫자는 각 회사의 {str(year) + '년 ' if year else ''}사업보고서 연결재무제표를 OpenDART에서 자동으로 받아 "
            f"현대건설과 같은 방식으로 계산합니다. ROE는 기말 자본 기준"
            + (f", PER·PBR은 {as_of} 주가 × 발행주식수(시가총액) ÷ 사업보고서의 지배주주 순이익·지배주주지분입니다. "
               if as_of else ", PER·PBR은 주가를 받은 뒤 채워집니다. ")
            + "회사 이름을 누르면 원문 공시가 열립니다.")
    summary = peer_summary(rows, ctx["company"]["name"])
    return (f'<section id="peers" aria-labelledby="h-peers" class="tbl-sec">'
            f'{section_head("peers", "Peer firms", "국내 동종업계", "국내 대형 건설사와 비교", summary, desc)}'
            f'<div class="table-scroll pe" tabindex="0"><table><caption class="sr">국내 동종업계 비교</caption>'
            f'<thead>{head}</thead><tbody>{"".join(body)}</tbody></table></div>'
            f'<p class="mini-h">비교할 때 주의</p>{foot}</section>')


# ---------------------------------------------------------------------------
# 9. 조립
# ---------------------------------------------------------------------------
CSS = """
:root{
  --paper:#f3f0e8; --paper-glass:rgba(243,240,232,.92); --sheet:#fbfaf6; --thead:#e7efeb; --thead-2:#eef3f0; --zebra:#f6f4ee;
  --ink:#141716; --ink-2:#4a4f4c; --muted:#5f625e; --line:#d4d0c6; --grid:#e5e1d8; --axis:#b3ad9f; --ref:#8d877b;
  --hover:rgba(24,61,61,.07); --below:rgba(196,72,59,.05); --self:#e8f1ed;
  --forest:#183d3d; --forest-ink:#f3f0e8; --forest-soft:#b4d3cd; --forest-line:rgba(180,211,205,.3);
  --data:#245553; --s1:#008f7a; --s2:#b9770e; --s3:#5965c9; --s4:#b5487f; --neg:#c4483b; --neg-wash:rgba(196,72,59,.14); --neg-text:#a8382c;
  --cost:#cfc8ba; --sga:#9c9588; --spark:#aaa496;
  --good:#0ca30c; --warn:#fab219; --crit:#d03b3b; --good-bg:rgba(12,163,12,.12); --warn-bg:rgba(250,178,25,.22); --crit-bg:rgba(208,59,59,.13);
  --tip-bg:#141716; --tip-fg:#f3f0e8; --tip-muted:#b9bcb6; --link:#1a6252; --focus:#1a6252;
  --font-sans:"IBM Plex Sans KR","Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR","Noto Sans CJK KR",system-ui,sans-serif;
  --font-mono:"IBM Plex Mono",ui-monospace,"SFMono-Regular",Menlo,Consolas,monospace;
}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){
  --paper:#0f1312; --paper-glass:rgba(15,19,18,.9); --sheet:#171c1b; --thead:#1f2826; --thead-2:#1b2321; --zebra:#1a201f;
  --ink:#ecede8; --ink-2:#c2c7c3; --muted:#9aa09c; --line:#2c3331; --grid:#252b29; --axis:#4a514d; --ref:#7d8480;
  --hover:rgba(180,211,205,.08); --below:rgba(224,106,92,.08); --self:#1d2a27;
  --forest:#10201f; --forest-ink:#ecede8; --forest-soft:#9fbdb6; --forest-line:rgba(159,189,182,.22);
  --data:#8fc7ba; --s1:#24a58f; --s2:#c4862a; --s3:#7480dc; --s4:#d16a9f; --neg:#e06a5c; --neg-wash:rgba(224,106,92,.18); --neg-text:#f08a7c;
  --cost:#3a403d; --sga:#6b726e; --spark:#5d6461;
  --good-bg:rgba(12,163,12,.2); --warn-bg:rgba(250,178,25,.18); --crit-bg:rgba(208,59,59,.22);
  --tip-bg:#eceee9; --tip-fg:#141716; --tip-muted:#4a4f4c; --link:#7cc4b3; --focus:#7cc4b3; color-scheme:dark}}
:root[data-theme="dark"]{
  --paper:#0f1312; --paper-glass:rgba(15,19,18,.9); --sheet:#171c1b; --thead:#1f2826; --thead-2:#1b2321; --zebra:#1a201f;
  --ink:#ecede8; --ink-2:#c2c7c3; --muted:#9aa09c; --line:#2c3331; --grid:#252b29; --axis:#4a514d; --ref:#7d8480;
  --hover:rgba(180,211,205,.08); --below:rgba(224,106,92,.08); --self:#1d2a27;
  --forest:#10201f; --forest-ink:#ecede8; --forest-soft:#9fbdb6; --forest-line:rgba(159,189,182,.22);
  --data:#8fc7ba; --s1:#24a58f; --s2:#c4862a; --s3:#7480dc; --s4:#d16a9f; --neg:#e06a5c; --neg-wash:rgba(224,106,92,.18); --neg-text:#f08a7c;
  --cost:#3a403d; --sga:#6b726e; --spark:#5d6461;
  --good-bg:rgba(12,163,12,.2); --warn-bg:rgba(250,178,25,.18); --crit-bg:rgba(208,59,59,.22);
  --tip-bg:#eceee9; --tip-fg:#141716; --tip-muted:#4a4f4c; --link:#7cc4b3; --focus:#7cc4b3; color-scheme:dark}

*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-padding-top:56px}
body{margin:0;background:var(--paper);color:var(--ink);font:400 15px/1.7 var(--font-sans);
  -webkit-font-smoothing:antialiased;word-break:keep-all;overflow-wrap:break-word}
a{color:var(--link);text-underline-offset:2px}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
b{font-weight:700}
.wrap{max-width:1240px;margin:0 auto;padding-inline:max(16px,4vw)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.muted{color:var(--muted)}

/* 헤더: 도면 표제란 */
.masthead{background:var(--forest);color:var(--forest-ink)}
.masthead .wrap{padding-block:48px 36px}
.eyebrow{margin:0;font:600 .72rem/1.4 var(--font-mono);letter-spacing:.14em;text-transform:uppercase;color:var(--muted)}
.eyebrow .ko{font-family:var(--font-sans);font-size:.8rem;letter-spacing:0;text-transform:none}
.masthead .eyebrow{color:var(--forest-soft)}
.live{display:inline-flex;align-items:center;gap:7px;margin-left:10px;padding:2px 10px;border:1px solid var(--forest-line);border-radius:999px;
  font:500 .74rem/1.6 var(--font-sans);letter-spacing:0;text-transform:none;color:var(--forest-ink)}
.live i{width:7px;height:7px;border-radius:50%;background:#3fd18a;box-shadow:0 0 0 3px rgba(63,209,138,.22)}
h1{margin:.4em 0 .45em;font-size:clamp(2rem,5.2vw,3.4rem);line-height:1.12;letter-spacing:-.035em;font-weight:700;text-wrap:balance}
.thesis{margin:0;max-width:42em;font-size:clamp(1.03rem,2vw,1.24rem);line-height:1.7}
.thesis b{color:var(--forest-soft)}
.titleblock{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,200px),1fr));gap:1px;margin:30px 0 0;
  background:var(--forest-line);border:1px solid var(--forest-line)}
.titleblock>div{background:var(--forest);padding:10px 14px;min-width:0}
.titleblock dt{font:600 .66rem/1.4 var(--font-mono);letter-spacing:.14em;text-transform:uppercase;color:var(--forest-soft)}
.titleblock dd{margin:3px 0 0;font-size:.9rem;font-weight:500}

/* 목차 */
.toc{position:sticky;top:0;z-index:20;background:var(--paper-glass);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);border-bottom:1px solid var(--line)}
.toc .wrap{display:flex;gap:2px;overflow-x:auto;scrollbar-width:none;padding-block:7px}
.toc .wrap::-webkit-scrollbar{display:none}
.toc a{flex:none;padding:6px 12px;border-radius:999px;font-size:.82rem;font-weight:600;color:var(--ink-2);text-decoration:none}
.toc a:hover{background:var(--hover);color:var(--ink)}
.toc .sep{flex:none;width:1px;margin:6px 6px;background:var(--line)}

/* 섹션 */
main section{padding-block:50px 4px}
.sec-head{max-width:46em;margin-bottom:20px}
.sec-head .eyebrow{color:var(--data)}
h2{margin:.3em 0 .35em;font-size:clamp(1.5rem,3.2vw,2.1rem);line-height:1.25;letter-spacing:-.025em;text-wrap:balance}
.answer{margin:0 0 .6em;font-size:clamp(1.05rem,2vw,1.18rem);font-weight:600;line-height:1.55;color:var(--ink)}
.sec-head p{margin:.45em 0;color:var(--ink-2)}
.sec-head p.answer{color:var(--ink)}
.explain{max-width:46em;margin-top:18px}
.explain p{margin:.55em 0;color:var(--ink-2)}
.sub-head{max-width:46em;margin:34px 0 0}
.sub-head h3{margin:0;font-size:1.12rem;letter-spacing:-.01em}
.sub-head p{margin:.4em 0 0;color:var(--ink-2)}
.grid-2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:14px;align-items:start}
.grid-3{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:14px;align-items:start;margin-top:14px}
.stack{display:grid;gap:14px}
h3{text-wrap:balance}
.band{border-block:1px solid var(--line);background:linear-gradient(var(--sheet),var(--paper))}
.band-label{display:flex;align-items:center;gap:12px;margin:56px 0 0;font:600 .72rem/1 var(--font-mono);letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}
.band-label::after{content:"";flex:1;border-top:1px solid var(--line)}

/* 판정 카드 */
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,240px),1fr));gap:12px}
.kpi{background:var(--sheet);border:1px solid var(--line);border-radius:8px;padding:16px 16px 14px;display:flex;flex-direction:column;gap:3px;min-width:0}
.kpi-top{display:flex;justify-content:space-between;align-items:center;gap:8px}
.kpi-label{margin:0;font-size:.82rem;font-weight:600;color:var(--ink-2);letter-spacing:0}
.kpi-basis{margin:2px 0 0;font-size:.74rem;color:var(--muted)}
.kpi-value{margin:0;font-size:2.25rem;font-weight:700;letter-spacing:-.03em;line-height:1.15}
.kpi-value small{margin-left:4px;font-size:.95rem;font-weight:600;letter-spacing:0;color:var(--ink-2)}
.kpi-delta{margin:0;font-size:.86rem;color:var(--ink-2)}
.kpi-delta b{color:var(--ink)}
.kpi-now{margin:0;font-size:.8rem;color:var(--muted)}
.kpi-term{margin:6px 0 0;padding-top:8px;border-top:1px solid var(--line);font-size:.74rem;color:var(--muted)}
.chip{flex:none;display:inline-flex;align-items:center;gap:5px;padding:2px 10px 2px 3px;border-radius:999px;font-size:.76rem;font-weight:700;background:var(--chip-bg);color:var(--ink)}
.chip .ic{width:17px;height:17px;border-radius:50%;display:grid;place-items:center;font-style:normal;font-size:.62rem;font-weight:800;background:var(--chip-c);color:#fff}
.chip.good{--chip-bg:var(--good-bg);--chip-c:var(--good)}
.chip.warn{--chip-bg:var(--warn-bg);--chip-c:var(--warn)}
.chip.warn .ic{color:#2a2208}
.chip.crit{--chip-bg:var(--crit-bg);--chip-c:var(--crit)}
.spark{position:relative;height:38px;margin:8px 6px 2px 0}
.spark svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.spark polyline{fill:none;stroke:var(--spark);stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}
.spark .z{stroke:var(--axis);stroke-width:1;vector-effect:non-scaling-stroke}
.spark .end{position:absolute;width:8px;height:8px;border-radius:50%;background:var(--c);box-shadow:0 0 0 2px var(--sheet);transform:translate(-50%,50%)}

/* 이번 달 카드 */
.card{background:var(--sheet);border:1px solid var(--line);border-radius:8px;padding:16px 18px;min-width:0}
.card h3{margin:0 0 6px;font-size:1.04rem;letter-spacing:-.01em}
ul.plain{margin:0;padding-left:1.05em;color:var(--ink-2);font-size:.9rem}
ul.plain li{margin:.4em 0}
ul.plain b{color:var(--ink)}
ul.small{font-size:.8rem}
.mini-h{margin:12px 0 2px;font-size:.78rem;font-weight:700;color:var(--ink)}
.card-foot{margin:12px 0 0;padding-top:10px;border-top:1px solid var(--line);font-size:.78rem;color:var(--muted)}
.callout{margin-top:12px;padding:10px 12px 10px 14px;border-radius:6px;border-left:4px solid var(--warn);background:var(--warn-bg);font-size:.84rem}
.callout .mini-h{margin-top:0}
.callout ul{margin:0;padding-left:1.1em}
.callout-foot{margin:6px 0 0;font-size:.76rem;color:var(--ink-2)}

/* 시기별 흐름 */
.acts{list-style:none;margin:0;padding:0;display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,196px),1fr));gap:12px}
.act{background:var(--sheet);border:1px solid var(--line);border-radius:8px;padding:16px;display:flex;flex-direction:column;gap:8px;min-width:0}
.act-years{margin:0;font:600 .74rem/1.2 var(--font-mono);letter-spacing:.06em;color:var(--muted)}
.act h3{margin:0;font-size:1.06rem;letter-spacing:-.01em}
.act ul{margin:0;padding-left:1.05em;font-size:.86rem;color:var(--ink-2)}
.act li{margin:.25em 0}
.act-why{margin:auto 0 0;padding:10px 12px;border-radius:6px;background:var(--hover);font-size:.8rem;color:var(--ink-2);line-height:1.6}
.act-why .tag{display:inline-block;margin-right:6px;font-weight:700;color:var(--ink)}
.act-why .src{display:block;margin-top:4px;font-size:.74rem}

/* 차트 공통 */
.chart{margin:0;background:var(--sheet);border:1px solid var(--line);border-radius:8px;padding:16px 16px 14px;min-width:0;container-type:inline-size}
.chart-head h3{margin:0;font-size:1.02rem;letter-spacing:-.01em}
.chart-head p{margin:2px 0 0;font-size:.78rem;color:var(--muted)}
.chart-note{margin:12px 0 0;font-size:.84rem;color:var(--ink-2)}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;margin:10px 0 0;font-size:.8rem;color:var(--ink-2)}
.legend .key{display:inline-flex;align-items:center;gap:6px}
.sw{width:12px;height:12px;border-radius:3px;background:var(--c)}
.sw.outline{background:var(--neg-wash);border:2px solid var(--c)}
.plot{display:grid;grid-template-columns:auto minmax(0,1fr);grid-template-rows:var(--h) auto;column-gap:8px;margin-top:14px}
.ya{grid-column:1;grid-row:1;position:relative;font-size:.69rem;color:var(--muted);font-variant-numeric:tabular-nums;text-align:right}
.ya .sizer{display:block;height:0;overflow:hidden;visibility:hidden;white-space:nowrap}
.ya span:not(.sizer){position:absolute;right:0;transform:translateY(50%);white-space:nowrap;line-height:1}
.pa{grid-column:2;grid-row:1;position:relative}
.xa{grid-column:2;grid-row:2;display:grid;grid-template-columns:repeat(var(--n),minmax(0,1fr));padding-top:6px;text-align:center;font-size:.69rem;color:var(--muted);font-variant-numeric:tabular-nums;line-height:1.35}
.xa>span{min-width:0;white-space:nowrap}
.y2{display:none}
.qq,.qy{display:block}
.qy{font-size:.92em;opacity:.85}
@container (max-width:560px){.y4{display:none}.y2{display:inline}}
@container (max-width:430px){.ml .xa>span:nth-child(even){visibility:hidden}}
.gl,.zl,.rl{position:absolute;left:0;right:0;height:0;border-top:1px solid var(--grid)}
.zl{border-top-color:var(--axis)}
.rl{border-top:1px dashed var(--ref)}
.rlab.left{left:4px}
.rlab.right{right:4px}
.rlab{position:absolute;transform:translateY(-2px);padding:0 4px;font-size:.66rem;line-height:1.3;color:var(--muted);background:var(--sheet);border-radius:3px;white-space:nowrap}
.below{position:absolute;left:0;right:0;bottom:0;background:var(--below)}
.slot{position:absolute;top:0;bottom:0;cursor:default;outline:none}
.slot::before{content:"";position:absolute;inset:0 7%;border-radius:4px}
.slot:hover::before,.slot.on::before,.slot:focus-visible::before{background:var(--hover)}
.slot:focus-visible{box-shadow:inset 0 0 0 2px var(--focus);border-radius:4px}
.bar{position:absolute;width:var(--bw);background:var(--c)}
.bar.pos{border-radius:4px 4px 0 0}
.bar.neg{border-radius:0 0 4px 4px}
.cc .slot{--bw:min(24px,54%)}
.cc.k2 .slot{--bw:min(13px,31%)}
.k1 .bar{left:calc(50% - var(--bw) / 2)}
.k2 .bar.j0{left:calc(50% - var(--bw) - 1px)}
.k2 .bar.j1{left:calc(50% + 1px)}
.vl,.ll{position:absolute;transform:translateX(-50%);font-size:.69rem;font-weight:700;line-height:1;white-space:nowrap;color:var(--ink);font-variant-numeric:tabular-nums;pointer-events:none}
.k1 .vl{left:50%}
.k2 .vl.j0{left:calc(50% - var(--bw) / 2 - 1px)}
.k2 .vl.j1{left:calc(50% + var(--bw) / 2 + 1px)}
.lc svg{position:absolute;inset:0;width:100%;height:100%;overflow:visible}
.lc polyline{fill:none;stroke-width:2;vector-effect:non-scaling-stroke;stroke-linejoin:round;stroke-linecap:round}
.dt{position:absolute;width:8px;height:8px;border-radius:50%;background:var(--c);box-shadow:0 0 0 2px var(--sheet);transform:translate(-50%,50%);pointer-events:none}
.lc .slot.on::after,.lc .slot:hover::after{content:"";position:absolute;top:0;bottom:0;left:50%;border-left:1px solid var(--axis)}
.lc .slot::before{display:none}

/* 매출 100원 가로 막대 */
.hb{margin-top:14px;font-variant-numeric:tabular-nums}
.hb-row{display:grid;grid-template-columns:2.7em minmax(0,1fr) 4.3em;column-gap:10px;height:28px;border-radius:4px;outline:none}
.hb-row:hover,.hb-row.on{background:var(--hover)}
.hb-row:focus-visible{box-shadow:inset 0 0 0 2px var(--focus)}
.hb-y{align-self:center;padding-left:4px;font-size:.74rem;color:var(--muted)}
.hb-t{position:relative}
.hb-t::after{content:"";position:absolute;top:0;bottom:0;left:var(--x100);border-left:1px dashed var(--ref)}
.seg{position:absolute;top:50%;height:14px;transform:translateY(-50%);background:var(--c)}
.seg.end{border-radius:0 4px 4px 0}
.over{position:absolute;top:50%;height:22px;transform:translateY(-50%);border:2px solid var(--neg);border-radius:3px;background:var(--neg-wash)}
.hb-v{align-self:center;text-align:right;padding-right:4px;font-size:.82rem;font-weight:700}
.hb-v.neg{color:var(--neg-text)}
.hb-scale{display:grid;grid-template-columns:2.7em minmax(0,1fr) 4.3em;column-gap:10px;margin-top:4px;font-size:.66rem;color:var(--muted)}
.hb-scale .ticks{position:relative;height:16px}
.hb-scale .ticks span{position:absolute;transform:translateX(-50%)}
.hb-unit{text-align:right;padding-right:4px}

/* 표 공통 */
.table-scroll{overflow:auto;border:1px solid var(--line);border-radius:8px;background:var(--sheet);margin-top:12px}
.table-scroll:focus-visible{outline-offset:-2px}
details .table-scroll{margin-top:10px}
table{width:100%;border-collapse:separate;border-spacing:0;font-size:.82rem;font-variant-numeric:tabular-nums}
caption{caption-side:top;text-align:left;padding:11px 12px 9px;font-weight:600;color:var(--ink-2);font-size:.82rem}
th,td{padding:7px 12px;text-align:right;white-space:nowrap;border-bottom:1px solid var(--grid)}
thead th{background:var(--thead);font-weight:600}
tbody th{text-align:left;font-weight:600;position:sticky;left:0;background:var(--sheet);z-index:1}
thead th:first-child{text-align:left;position:sticky;left:0;z-index:2}
tbody tr:nth-child(even) td,tbody tr:nth-child(even) th{background:var(--zebra)}
tbody tr:hover td,tbody tr:hover th{background:var(--hover)}
tbody tr:last-child td,tbody tr:last-child th{border-bottom:0}
td.neg{color:var(--neg-text)}
td.na{color:var(--muted)}
td.left,th.left{text-align:left}
td.wrap{white-space:normal;min-width:12em;max-width:22em}
.sig th small{display:block;font-size:.68rem;font-weight:500;color:var(--muted)}
.sig td.lab,.sig thead th:last-child{text-align:left}
.sig td.lab{font-weight:600;white-space:normal;min-width:7.5em}
.sig .ar{display:inline-block;width:1.2em;text-align:center;font-size:.72rem}
.sig .in .ar{color:var(--s1)}
.sig .out .ar{color:var(--neg)}
.sig .flat{color:var(--muted)}
.sig tr.minus td,.sig tr.minus th{background:var(--below)}
details.tv{margin-top:12px;border-top:1px solid var(--grid);padding-top:10px}
details.tv summary{cursor:pointer;display:inline-flex;align-items:center;gap:6px;font-size:.8rem;font-weight:600;color:var(--link);list-style:none}
details.tv summary::-webkit-details-marker{display:none}
details.tv summary::before{content:"";width:0;height:0;border:4px solid transparent;border-left:6px solid currentColor;border-right:0;transition:transform .15s}
details.tv[open] summary::before{transform:rotate(90deg)}

/* 큰 표 (Annual · Half-year · Quarterly) */
.tbl-sec{padding-block:40px 4px}
.tbl-head{display:flex;flex-wrap:wrap;justify-content:space-between;align-items:flex-end;gap:10px 24px}
.tbl-head>div:first-child{max-width:46em}
.tbl-head h2{margin-bottom:.2em}
.tbl-head p{margin:.3em 0 0;color:var(--ink-2);font-size:.92rem}
.tbl-head .eyebrow{color:var(--data)}
.tbl-meta{display:flex;flex-wrap:wrap;align-items:center;gap:6px 14px;font-size:.82rem}
.tbl-meta .count{color:var(--muted)}
.tbl-meta a{font-weight:600}
.big.tall{max-height:min(74vh,700px)}
.big table{font-size:.8rem}
.big th,.big td{padding:6px 11px}
.big thead th{position:sticky;top:0;z-index:2}
.big thead tr.g th{height:30px;padding-block:0;line-height:30px;background:var(--thead);font-size:.72rem;letter-spacing:.02em;color:var(--ink-2);text-align:left}
.big thead tr.c th{top:30px;background:var(--thead-2);font-size:.76rem}
.big thead th.corner{z-index:4;left:0;vertical-align:bottom;background:var(--thead);min-width:9.5em}
.big .gs{border-left:1px solid var(--line)}
.big tbody th{z-index:1;min-width:9.5em}
.big tbody th a{color:var(--ink);text-decoration:none}
.big tbody th a:hover{text-decoration:underline}
.pl{margin-right:6px}
.bd{display:inline-block;margin-left:3px;padding:0 5px;border:1px solid var(--line);border-radius:4px;font-size:.66rem;font-weight:600;line-height:1.5;color:var(--muted);vertical-align:1px;cursor:help}
.bd.warn{border-color:var(--warn);background:var(--warn-bg);color:var(--ink)}
.legend-row{display:flex;flex-wrap:wrap;gap:4px 16px;margin:14px 0 0;font-size:.78rem;color:var(--muted)}
.pe thead th small{display:block;font-size:.66rem;font-weight:500;color:var(--muted)}
.pe tbody th{min-width:13em;white-space:normal}
.pe .pn{display:flex;align-items:baseline;gap:6px;white-space:nowrap}
.pe .code{font-size:.7rem;font-weight:500;color:var(--muted)}
.pe .biz{display:block;font-size:.74rem;font-weight:400;color:var(--muted);line-height:1.45}
.peer-notes{margin-top:4px}
.pe tr.self td,.pe tr.self th{background:var(--self)}
.pe tr.self th::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--data)}

/* 6단계 카드 · 단계 표시 */
.kpis.six{grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr))}
.kpi-label a{color:inherit;text-decoration:none}
.kpi-label a:hover{color:var(--ink)}
.kpi-label .no{display:inline-grid;place-items:center;width:18px;height:18px;margin-right:6px;border-radius:50%;background:var(--data);color:var(--sheet);font:700 .66rem/1 var(--font-mono)}
.chip.info{--chip-bg:var(--hover);--chip-c:var(--ink-2)}
.chip.info .ic{font-family:var(--font-mono)}
.sec-top{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px}
.sec-top .eyebrow{margin:0}
.step-no{display:inline-block;padding:3px 8px;border-radius:4px;background:var(--data);color:var(--sheet);font:700 .66rem/1.2 var(--font-mono);letter-spacing:.12em}
.sw.line{height:3px;border-radius:2px}
.sw.dash{height:0;border-radius:0;background:none;border-top:2px dashed var(--c)}
.plot.ml{grid-template-columns:auto minmax(0,1fr) 3.6em}
.el{position:absolute;left:calc(100% + 8px);transform:translateY(50%);font-size:.7rem;font-weight:700;line-height:1;white-space:nowrap;color:var(--c);font-variant-numeric:tabular-nums;pointer-events:none}
.lc polyline[stroke-dasharray]{stroke-width:1.6}
/* 주가 수준 */
.vtiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,170px),1fr));gap:1px;margin:0 0 14px;background:var(--line);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.vt{background:var(--sheet);padding:12px 14px;min-width:0}
.vt-l{margin:0;font-size:.76rem;font-weight:600;color:var(--muted)}
.vt-v{margin:2px 0 0;font-size:1.55rem;font-weight:700;letter-spacing:-.02em;line-height:1.2}
.vt-v small{margin-left:3px;font-size:.78rem;font-weight:600;color:var(--ink-2)}
.vt-d{margin:3px 0 0;font-size:.72rem;line-height:1.45;color:var(--muted)}
.card.empty{border-style:dashed}
.card.empty p{margin:.3em 0 0;color:var(--ink-2);font-size:.9rem}
/* 지표 조합 점검 */
.combo td,.combo th{vertical-align:top}
.combo .det{display:block;margin-top:4px;font-size:.74rem;color:var(--muted);white-space:normal;min-width:13em}
.combo .res{font-size:.8rem;font-weight:600}
.combo .res.no,.combo .res.na{color:var(--muted)}
.combo .res.na{font-weight:500}
.combo tbody tr.hit th,.combo tbody tr.hit td{background:var(--warn-bg)}
.combo tbody th{min-width:11em;white-space:normal}
.combo td.wrap{max-width:none;min-width:13em}
/* 체크리스트 */
.ck{margin:0 0 14px}
.ck th,.ck td{text-align:left}
.ck td.st{font-weight:700;white-space:nowrap}
.ck td.st span{display:inline-block;width:1.3em}
.ck td.st.ok{color:var(--good)}
.ck td.st.part{color:var(--ink-2)}
/* 표 열 묶음 고르기 */
.gtoggle{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 0}
.gtoggle button{font:600 .76rem/1 var(--font-sans);padding:6px 11px;border-radius:999px;border:1px solid var(--line);background:var(--sheet);color:var(--ink-2);cursor:pointer}
.gtoggle button:hover{background:var(--hover);color:var(--ink)}
.gtoggle button[aria-pressed="true"]{background:var(--data);border-color:var(--data);color:var(--sheet)}
.big thead tr.c th small{display:block;font-size:.66rem;font-weight:500;color:var(--muted)}
.big[data-show="0"] [data-g]:not([data-g="0"]){display:none}
.big[data-show="1"] [data-g]:not([data-g="1"]){display:none}
.big[data-show="2"] [data-g]:not([data-g="2"]){display:none}
.big[data-show="3"] [data-g]:not([data-g="3"]){display:none}
.big[data-show="4"] [data-g]:not([data-g="4"]){display:none}
.big[data-show="5"] [data-g]:not([data-g="5"]){display:none}
.big[data-show="6"] [data-g]:not([data-g="6"]){display:none}
.big[data-show="7"] [data-g]:not([data-g="7"]){display:none}

/* 자료·검증 */
.notes{columns:3 300px;column-gap:14px}
.note-card{break-inside:avoid;margin:0 0 14px;background:var(--sheet);border:1px solid var(--line);border-radius:8px;padding:16px 18px;min-width:0}
.note-card h3{margin:0 0 6px;font-size:1rem}
.note-card h3.mt{margin-top:14px}
.note-card ul{margin:0;padding-left:1.1em;font-size:.84rem;color:var(--ink-2)}
.note-card li{margin:.35em 0}
footer{margin-top:64px;background:var(--forest);color:var(--forest-ink)}
footer .wrap{padding-block:22px;font-size:.82rem;display:flex;flex-wrap:wrap;gap:6px 18px}
footer a{color:var(--forest-soft)}

/* 가로 누적 막대 (사업부문·공사) */
.hs{margin-top:12px;display:grid;gap:2px;font-variant-numeric:tabular-nums}
.hs-row{display:grid;grid-template-columns:minmax(0,16em) minmax(0,1fr) auto;gap:4px 12px;align-items:center;padding:5px 6px;border-radius:6px;outline:none}
.hs-row:hover,.hs-row.on{background:var(--hover)}
.hs-row:focus-visible{box-shadow:inset 0 0 0 2px var(--focus)}
.hs-l{min-width:0}
.hs-l b{display:block;font-size:.84rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-meta{display:block;font-size:.7rem;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hs-t{position:relative;height:16px}
.hs-seg{position:absolute;top:0;bottom:0;background:var(--c)}
.hs-seg:first-child{border-radius:4px 0 0 4px}
.hs-seg:last-child{border-radius:0 4px 4px 0}
.hs-seg:only-child{border-radius:4px}
.hs-seg.left{background:color-mix(in srgb,var(--c) 20%,var(--sheet));box-shadow:inset 0 0 0 1.5px var(--c)}
.hs-seg+.hs-seg:not(.left){box-shadow:inset 2px 0 0 var(--sheet)}
.hs-v{font-size:.78rem;font-weight:700;white-space:nowrap;text-align:right}
.hs-unit{margin:8px 0 0;font-size:.72rem;color:var(--muted)}
.sw.tint{background:color-mix(in srgb,var(--c) 20%,var(--sheet));border:1.5px solid var(--c)}
@media (max-width:640px){.hs-row{grid-template-columns:minmax(0,1fr) auto}.hs-l{grid-column:1/-1}}
/* 누적 세로 막대 · 3개 묶음 */
.bar.stk{border-radius:0;box-shadow:inset 0 1px 0 var(--sheet)}
.bar.stk.top{border-radius:4px 4px 0 0}
.cc.k3 .slot{--bw:min(9px,24%)}
.k3 .bar.j0{left:calc(50% - var(--bw) * 1.5 - 2px)}
.k3 .bar.j1{left:calc(50% - var(--bw) / 2)}
.k3 .bar.j2{left:calc(50% + var(--bw) / 2 + 2px)}
.k3 .vl.j0{left:calc(50% - var(--bw) - 2px)}
.k3 .vl.j1{left:50%}
.k3 .vl.j2{left:calc(50% + var(--bw) + 2px)}
.cc.wb .slot{--bw:min(26px,40%)}
.cc.k2.wb .slot{--bw:min(22px,34%)}
.cc.k3.wb .slot{--bw:min(14px,26%)}
.heat th small{margin-left:5px;font-weight:500;font-size:.7rem;color:var(--muted)}
.heat td{text-align:center}
.lens-now ul.plain{columns:2 300px;column-gap:28px}
.lens-now li{break-inside:avoid}
/* 10가지 관점 */
.kpis.ten{grid-template-columns:repeat(auto-fit,minmax(min(100%,216px),1fr))}
.lens .kpi-value{font-size:1.9rem}
.cross{margin:20px 0 0;display:flex;flex-wrap:wrap;gap:8px}
.cross a{display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border:1px solid var(--forest-line);border-radius:999px;color:var(--forest-ink);text-decoration:none;font-weight:600;font-size:.86rem}
.cross a:hover{background:rgba(255,255,255,.08)}
.cross a[aria-current]{background:var(--forest-soft);color:var(--forest);border-color:var(--forest-soft)}

/* 툴팁 */
.tip{position:fixed;z-index:60;pointer-events:none;min-width:160px;max-width:min(290px,calc(100vw - 16px));padding:10px 12px;border-radius:8px;
  background:var(--tip-bg);color:var(--tip-fg);box-shadow:0 10px 28px rgba(0,0,0,.22);font-size:.8rem;line-height:1.45}
.tip .tt{margin-bottom:6px;font-weight:700}
.tip .tr{display:grid;grid-template-columns:12px auto minmax(0,1fr);align-items:center;gap:7px;margin:3px 0}
.tip .tk{width:12px;height:3px;border-radius:2px;background:var(--c)}
.tip .tv{font-weight:700;font-variant-numeric:tabular-nums;white-space:nowrap}
.tip .tl{color:var(--tip-muted)}
.tip .tn{margin-top:7px;padding-top:6px;border-top:1px solid color-mix(in srgb,var(--tip-muted) 35%,transparent);color:var(--tip-muted);font-size:.74rem}

@media (max-width:640px){
  body{font-size:14.5px}
  .masthead .wrap{padding-block:34px 26px}
  main section{padding-block:40px 0}
  .chart,.kpi,.act,.card{padding:14px 12px 12px}
  th,td{padding:7px 9px}
  .big th,.big td{padding:6px 8px}
  .big thead th.corner,.big tbody th{min-width:8em}
  .kpi-value{font-size:2.05rem}
  .hb-row,.hb-scale{grid-template-columns:2.4em minmax(0,1fr) 3.9em;column-gap:8px}
}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
@media print{.toc,.tip{display:none}.big.tall{max-height:none}}
"""

JS = """
(function(){
  var tip=document.createElement('div');tip.className='tip';tip.hidden=true;tip.setAttribute('aria-hidden','true');
  document.body.appendChild(tip);
  var cur=null;
  function el(tag,cls,text){var e=document.createElement(tag);e.className=cls;if(text!=null)e.textContent=text;return e;}
  function fill(target){
    var d;try{d=JSON.parse(target.getAttribute('data-tip'));}catch(e){return false;}
    tip.replaceChildren();tip.appendChild(el('div','tt',d.t||''));
    (d.r||[]).forEach(function(r){
      var row=el('div','tr'),key=el('i','tk');
      if(r[2]){key.style.setProperty('--c',r[2]);}else{key.style.visibility='hidden';}
      row.appendChild(key);row.appendChild(el('span','tv',r[1]));row.appendChild(el('span','tl',r[0]));tip.appendChild(row);
    });
    if(d.n){tip.appendChild(el('div','tn',d.n));}
    return true;
  }
  function place(x,y){
    tip.hidden=false;
    var w=tip.offsetWidth,h=tip.offsetHeight,left=x-w/2,top=y-h-14;
    if(top<8){top=y+18;}
    left=Math.max(8,Math.min(left,window.innerWidth-w-8));top=Math.max(8,Math.min(top,window.innerHeight-h-8));
    tip.style.left=left+'px';tip.style.top=top+'px';
  }
  function show(target,x,y){
    if(cur!==target){if(cur){cur.classList.remove('on');}cur=target;target.classList.add('on');if(!fill(target)){return;}}
    if(x==null){var r=target.getBoundingClientRect();x=r.left+r.width/2;y=r.top+Math.min(r.height*0.3,48);}
    place(x,y);
  }
  function hide(){tip.hidden=true;if(cur){cur.classList.remove('on');}cur=null;}
  function find(e){return e&&e.closest?e.closest('[data-tip]'):null;}
  document.addEventListener('pointermove',function(e){if(e.pointerType!=='mouse'){return;}var t=find(e.target);if(t){show(t,e.clientX,e.clientY);}else if(cur){hide();}});
  document.addEventListener('click',function(e){var t=find(e.target);if(t){show(t);}else{hide();}});
  document.addEventListener('focusin',function(e){var t=find(e.target);if(t){show(t);}});
  document.addEventListener('focusout',function(e){if(!find(e.relatedTarget)){hide();}});
  document.addEventListener('keydown',function(e){if(e.key==='Escape'){hide();}});
  window.addEventListener('scroll',function(){if(cur&&document.activeElement!==cur){hide();}},{passive:true});
})();
(function(){
  document.querySelectorAll('.gtoggle').forEach(function(bar){
    var wrap=bar.nextElementSibling;bar.hidden=false;
    bar.addEventListener('click',function(e){
      var b=e.target.closest('button');if(!b){return;}
      var g=b.getAttribute('data-g');
      if(g){wrap.setAttribute('data-show',g);}else{wrap.removeAttribute('data-show');}
      bar.querySelectorAll('button').forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false');});
    });
  });
})();
"""

FONT_LINK = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
             '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@500;600'
             '&family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap">')


REPORT_PDF = "reports/hyundai-company-report.pdf"     # 기업분석 보고서 (company_report.py가 매월 다시 만듦)


def doc_links(cfg):
    """머리글 아래 버튼: 기업분석 보고서(PDF) · 아래쪽 표 · 저장소."""
    return ('<nav class="cross" aria-label="함께 보는 자료">'
            f'<a href="../{REPORT_PDF}">📄 기업분석 보고서 PDF</a>'
            '<a href="#annual">연간·반기·분기 표 ↓</a>'
            f'<a href="{esc(cfg.get("repo_url", ""))}" target="_blank" rel="noopener">GitHub 저장소 ↗</a></nav>')


def page(title, description, body):
    return ("<!doctype html>\n<html lang=\"ko\"><head><meta charset=\"utf-8\">"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">"
            f"<title>{esc(title)}</title><meta name=\"description\" content=\"{esc(description)}\">"
            f"<meta name=\"theme-color\" content=\"#183d3d\">{FONT_LINK}<style>{CSS}</style></head><body>"
            f"{body}<script>{JS}</script></body></html>\n")


def render(ctx):
    cfg = ctx["company"]
    a = ctx["analysis"]
    title = f"{cfg['name']} 재무제표 대시보드"
    if not a.get("verdicts"):
        body = (f'<header class="masthead"><div class="wrap"><h1>{esc(title)}</h1>'
                f'<p class="thesis">아직 수집된 숫자가 없습니다. GitHub Actions에서 에이전트를 실행하면 채워집니다.</p></div></header>')
        return page(title, "수집 전", body)
    import statements as st
    v = an.View(ctx)
    vd = a["verdicts"]
    notes = a["notes"]
    status = ctx["status"]
    q_all, y_all = ctx["quarters"], ctx["annual"]
    lf = ctx.get("latest_filing")

    # 헤더
    block = [("Company", f"{cfg['name']} ({cfg['stock_code']}) · 연결재무제표"),
             ("Coverage", f"{short_q(q_all[0])} ~ {short_q(q_all[-1])}" if q_all else f"{y_all[0]['year']}~{y_all[-1]['year']}년"),
             ("Latest filing", f"{lf['report_nm'].strip()} · {fmt_date(lf['rcept_dt'])} 접수" if lf else "–"),
             ("Checked", status.get("checked_at", "")[:16].replace("T", " ") + (" KST" if "T" in status.get("checked_at", "") else "")),
             ("Next run", f"{ctx['next_run'].replace('-', '.')} 09:17 KST")]
    block_html = "".join(f"<div><dt>{esc(k)}</dt><dd>{esc(val)}</dd></div>" for k, val in block)
    header = (f'<header class="masthead"><div class="wrap"><p class="eyebrow">HSC-Class01 · OpenDART Financial Agent'
              f'<span class="live"><i aria-hidden="true"></i>매월 1일 자동 업데이트</span></p>'
              f'<h1>{esc(title)}</h1><p class="thesis">{rich(a["headline"])}</p><dl class="titleblock">{block_html}</dl>'
              f'{doc_links(cfg)}</div></header>')

    sections = []
    sections.append(f'<section id="summary" aria-labelledby="h-summary">'
                    + section_head("summary", "Summary", "한눈에 보기", "여섯 단계로 본 현대건설",
                                   "교수님 자료(재무제표·재무비율 실무가이드)의 분석 순서대로 매출 성장 → 이익률 → 현금흐름 → 차입 부담 → "
                                   "투자수익률 → 주가 수준을 봤습니다. 판정은 화면 아래 ‘판정 기준’의 단순 규칙을 따르고, 새 보고서가 나오면 자동으로 다시 매겨집니다. "
                                   "카드를 누르면 짝이 되는 재무비율 관점의 차트와 해설로 갑니다.")
                    + kpis(v, vd, ctx) + "</section>")
    now_desc = ("매월 1일 OpenDART에서 새 정기보고서(사업·반기·분기)가 나왔는지 확인하고, 있으면 아래 숫자와 문장을 모두 다시 씁니다. "
                + notes.get("quarters", ""))
    sections.append(f'<section id="now" aria-labelledby="h-now">'
                    + section_head("now", "Latest", "이번 달 업데이트", "가장 최근 분기에 무슨 일이 있었나", now_desc)
                    + f'<div class="grid-2">{latest_card(a)}{update_card(ctx, a)}</div>{quarter_figs(v, notes)}</section>')
    st_toc, st_html = [], ""
    try:
        st_toc, st_html = st.sections(ctx)
    except Exception as exc:     # 재무제표 10년 부분이 실패해도 요약과 표는 만듭니다
        print(f"::warning::재무제표 10년 · 10가지 관점 생략: {type(exc).__name__}: {exc}")
    sections.append(st_html)
    tail = '<p class="band-label" aria-hidden="true">Signals · 신호와 흐름</p>'
    if a.get("combos"):
        tail += combos_section(a)
    if a["acts"]:
        tail += (f'<section id="story" aria-labelledby="h-story">'
                 + section_head("story", "Timeline", "시기별 흐름", f"{y_all[0]['year']}년부터 지금까지, 다섯 장면",
                                "숫자는 재무제표에서 자동으로 계산하고, 배경 설명은 언론 보도에서 가져왔습니다. 각 장면 아래 링크가 출처입니다.")
                 + acts_html(a["acts"]) + "</section>")
    sections.append(tail)

    toc = [("summary", "요약"), ("now", "이번 달"), None] + st_toc + [None, ("combos", "조합 신호"), ("story", "흐름"), None,
                                                                    ("annual", "Annual"), ("half", "Half-year"), ("quarter", "Quarterly"),
                                                                    ("notes", "자료"), ("peers", "Peer firms")]
    toc_html = "".join('<span class="sep" aria-hidden="true"></span>' if t is None else f'<a href="#{t[0]}">{esc(t[1])}</a>'
                       for t in toc)

    tables = ['<p class="band-label" aria-hidden="true">Data tables · 전체 숫자</p>']
    tables.append(table_section("annual", "Annual", "연간", "연간 실적 (사업보고서)",
                                "1~12월 실적과 12월 말 재무상태입니다. 기간 이름을 누르면 DART 원문이 열립니다.",
                                y_all, "annual", "annual.csv"))
    tables.append(table_section("half", "Half-year", "반기", "반기 실적",
                                "상반기 = 반기보고서(1~6월), 하반기 = 연간 − 상반기(7~12월). 재무상태는 6월 말·12월 말 잔액입니다.",
                                ctx["halves"], "half", "half_year.csv"))
    tables.append(table_section("quarter", "Quarterly", "분기", "분기 실적",
                                "각 분기 3개월 실적입니다. 1분기는 1분기보고서, 2~4분기는 누적 보고서끼리 빼서 계산했습니다"
                                "(2분기 = 반기 − 1분기, 3분기 = 3분기 누적 − 반기, 4분기 = 연간 − 3분기 누적).",
                                q_all, "quarter", "quarterly.csv"))
    tables.append('<div class="legend-row"><span><span class="bd">계산</span> 누적 보고서끼리 뺀 기간</span>'
                  '<span><span class="bd">원문</span> 공시 원문 표에서 읽은 숫자(2010~2015년)</span>'
                  '<span><span class="bd">비교</span> 다음 해 보고서의 비교 숫자</span>'
                  '<span><span class="bd warn">주의</span> 마우스를 올리면 이유가 보입니다</span>'
                  '<span>붉은 글씨 = 마이너스 · – = 숫자 없음</span></div>')
    body = (header + f'<nav class="toc" aria-label="목차"><div class="wrap">{toc_html}</div></nav>'
            f'<main class="wrap">{"".join(sections)}{"".join(tables)}{notes_section(ctx, a)}{peers_section(ctx)}</main>'
            f'<footer><div class="wrap"><span>HSC-Class01 · KTG_Hyundai · OpenDART 공시로 매월 자동 생성하는 교육용 재무제표 대시보드</span>'
            f'<a href="../{REPORT_PDF}">기업분석 보고서 PDF</a>'
            f'<a href="{esc(cfg.get("repo_url", ""))}" target="_blank" rel="noopener">GitHub 저장소 ↗</a>'
            f'<a href="{esc(cfg.get("repo_url", ""))}/actions" target="_blank" rel="noopener">자동 실행 기록 ↗</a>'
            f'<a href="../">포트폴리오 홈</a></div></footer>')
    return page(title, an.to_plain(a["headline"]), body)


# ---------------------------------------------------------------------------
# 10. README 자동 구역
# ---------------------------------------------------------------------------
MARKERS = {
    "summary": ("<!-- AUTO:SUMMARY:START -->", "<!-- AUTO:SUMMARY:END -->"),
    "peers": ("<!-- AUTO:PEERS:START -->", "<!-- AUTO:PEERS:END -->"),
}
VERDICT_ICON = {"good": "🟢", "warn": "🟡", "crit": "🔴", "info": "ℹ️"}


def _md_table(headers, rows, align=None):
    align = align or ["---"] + ["---:"] * (len(headers) - 1)
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join(align) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def readme_summary(ctx):
    a = ctx["analysis"]
    status = ctx["status"]
    lf = ctx.get("latest_filing")
    if not a.get("verdicts"):
        return "_아직 수집된 숫자가 없습니다. Actions에서 에이전트를 한 번 실행하세요._"
    vd = a["verdicts"]
    lines = [f"> 마지막 확인 **{status.get('checked_at', '')[:10]}** · 가장 최근 반영 보고서 **"
             + (f"{lf['report_nm'].strip()}** ({fmt_date(lf['rcept_dt'])} 접수)" if lf else "–**")
             + f" · 다음 자동 확인 **{ctx['next_run']}**", "",
             a["headline"], "",
             "교수님 자료(재무제표·재무비율 실무가이드)의 분석 순서대로 본 판정입니다.", ""]
    rows = []
    for step in a["steps"]:
        tone, word = step["verdict"]
        rows.append([f"{step['no']} {step['ko']}", f"{VERDICT_ICON.get(tone, 'ℹ️')} {word}", an.to_plain(step["answer"])])
    lines.append(_md_table(["단계", "판정", "한 줄 답"], rows, ["---", "---", "---"]))
    hits = [c for c in a.get("combos", []) if c["hit"]]
    if hits:
        lines += ["", "지표 조합 신호(가이드 5장): " + ", ".join(f"**{c['name']}**({c['detail']})" for c in hits)]
    lines += readme_business(ctx)
    lq = a.get("latest")
    if lq:
        lines += ["", f"**{lq['title']}**", ""] + [f"- {x}" for x in lq["lines"]]
    recent = ctx["annual"][-5:]
    h1 = next((h for h in reversed(ctx["halves"]) if h["kind"] == "H1"), None)
    show = [(f"{r['year']}년", r) for r in recent]
    if h1 and recent and h1["year"] > recent[-1]["year"]:
        show.append((f"{h1['year']}년 상반기", h1))
    rows = []
    for name, r in show:
        rv, rr = r["values"], r["ratios"]
        rows.append([name, eok(rv.get("revenue")), eok(rv.get("operating_profit")), an.pct(rr.get("operating_margin_pct")),
                     eok(rv.get("ebitda")), eok(rv.get("net_income")), eok(rv.get("operating_cashflow")), eok(rv.get("fcf")),
                     an.pct(rr.get("debt_to_equity_pct"), 0), fmt_cell(rr.get("interest_coverage_x"), "x"),
                     an.pct(rr.get("roe_pct")), an.pct(rr.get("roic_pct"))])
    lines += ["", "최근 실적 (연결, 금액 단위: 억 원 · ROE·ROIC는 연간만)", "",
              _md_table(["기간", "매출액", "영업이익", "영업이익률(%)", "EBITDA", "당기순이익", "영업현금흐름", "FCF",
                         "부채비율(%)", "이자보상배율(배)", "ROE(%)", "ROIC(%)"], rows)]
    val = ctx.get("valuation") or {}
    if val.get("market_cap"):
        lines += ["", f"주가 수준({an.price_when(val)} 종가 {val['price']:,.0f}원): 시가총액 {an.jo(val['market_cap'], 2)}조 원"
                  + (f" · PER {val['per_x']:.1f}배" if val.get("per_x") else "") + (f" · PBR {val['pbr_x']:.2f}배" if val.get("pbr_x") else "")
                  + (f" · EV/EBITDA {val['ev_ebitda_x']:.1f}배" if val.get("ev_ebitda_x") else "")]
    url = ctx['company']['dashboard_url']
    lines += ["", f"대시보드: [재무제표 10년]({url}#is) · [10가지 관점]({url}#lenses) · 전체 표 [연간]({url}#annual) · [반기]({url}#half) · "
              f"[분기]({url}#quarter) · CSV: [annual](data/financials/annual.csv) · [half_year](data/financials/half_year.csv) · "
              f"[quarterly](data/financials/quarterly.csv) · 기업분석 보고서: [PDF]({REPORT_PDF})"]
    return "\n".join(lines)


def readme_business(ctx):
    """README 요약에 넣을 사업보고서 본문 숫자(수주잔고·신규 수주·PF 보증) 한 줄."""
    try:
        import report_view as rv
        lb = rv.latest_backlog(ctx)
        orders = (ctx.get("business") or {}).get("orders") or {}
        pf = rv.pf_rows(ctx)
        parts = []
        if lb:
            yrs = rv.years_of_work(ctx, lb)
            parts.append(f"수주잔고 **{an.jo(lb['total'])}조 원**({rv.period_label(lb['period'])}" + (f", 매출 {yrs:.1f}년 치" if yrs else "") + ")")
        if orders:
            oy = max(orders)
            parts.append(f"{oy}년 신규 수주 {an.jo(orders[oy]['total'])}조 원(현대건설 단독)")
        if pf:
            p, r = pf[-1]
            b = rv.balance_at(ctx, int(p[:4]), int(p[5:]))
            parts.append(f"PF 보증 {an.jo(r['amount'])}조 원" + (f"(자본의 {r['amount'] / b['values']['equity']:.1f}배)" if b else ""))
        return ["", "사업보고서 본문(수주·PF): " + " · ".join(parts) + f" → [기업분석 보고서(PDF)]({REPORT_PDF})"] if parts else []
    except Exception as exc:     # README 요약은 이 줄 없이도 만듭니다
        print(f"::warning::README 수주·PF 줄 생략: {type(exc).__name__}: {exc}")
        return []


def readme_peers(ctx):
    rows_, year = peer_table_rows(ctx)
    rank = ctx["company"].get("rank", {})
    rows = []
    for p, own in rows_:
        name = f"**{p['name']}**" if own else p["name"]
        if p.get("receipt"):
            name = f"[{name}]({DART_VIEW}{p['receipt']})"
        vals = [fmt_cell(peer_value(p, k, w), t) for k, _, t, w in PEER_COLS if k not in ("net_income", "net_margin_pct")]
        rows.append([f"{p['rank']}위" if p.get("rank") else "–", name, p["stock_code"], p.get("business", ""),
                     f"{p['year']}년" if p.get("year") else "수집 전", *vals])
    head = ["시평 순위", "회사", "종목코드", "주요 사업", "기준"] + [
        f"{lab}({PEER_UNITS[t]})" for k, lab, t, _ in PEER_COLS if k not in ("net_income", "net_margin_pct")]
    summary = peer_summary(rows_, ctx["company"]["name"])
    out = ([summary, ""] if summary else []) + [
        _md_table(head, rows, ["---:", "---", "---", "---", "---"] + ["---:"] * (len(head) - 5)), ""]
    if rank:
        out.append(f"- 순위: {rank.get('year')}년 {rank.get('basis')} ([{rank.get('source_name')}]({rank.get('source_url')}))")
    as_of = next((p["market"].get("as_of") for p, _ in rows_ if (p.get("market") or {}).get("as_of")), None)
    out.append("- 재무 숫자: 각 회사의 가장 최근 사업보고서 연결재무제표 (OpenDART, 매월 자동 갱신). ROE는 기말 자본 기준"
               + (f", PER·PBR은 {as_of} 주가 기준." if as_of else ", PER·PBR은 주가를 받은 뒤 채워집니다.")
               + " 동종기업 목록은 `config/company.json`에서 바꿀 수 있습니다.")
    for p, own in rows_:
        if not own and p.get("note"):
            out.append(f"- {p['name']}: {p['note']}")
    missing = [p["name"] for p, own in rows_ if not own and not p.get("year")]
    if missing:
        out.append(f"- {', '.join(missing)}: 다음 자동 실행 때 숫자를 채웁니다.")
    return "\n".join(out)


def update_readme(path, ctx):
    path = Path(path)
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8")
    new = text
    blocks = {"summary": readme_summary(ctx), "peers": readme_peers(ctx)}
    for key, (start, end) in MARKERS.items():
        pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.S)
        if pattern.search(new):
            new = pattern.sub(lambda m, b=blocks[key], s=start, e=end: f"{s}\n{b}\n{e}", new)
        else:
            print(f"::warning::README에 {start} 표시가 없어 자동 구역을 건너뜀")
    if new != text:
        path.write_text(new, encoding="utf-8")
        return True
    return False
