"""기업분석 보고서 전용 차트 부품 (대시보드 차트와 같은 CSS 클래스를 씁니다).

- diverging_stack: 양수 요소는 0 위로, 음수 요소는 0 아래로 쌓고, 합계(순변화)를 가로 막대 표시로 겹쳐 보여 줍니다.
  영업이익 증감 분해(규모·원가율·판관비), 회사별 영업이익(본사·현대엔지니어링·기타), 원가 추정 변경(부문별),
  현금의 원천과 사용처럼 '+와 −가 섞인 합'을 한 막대로 보여 줄 때 씁니다.
- stage_ladder: 미래사업이 '구상 → 설계 → 본계약 → 시공 → 회수' 중 어디까지 왔는지 보여 주는 표 모양 그림.
"""
import dashboard as d

esc = d.esc


def diverging_stack(xlabels, comps, *, tips, net=None, ticks_fmt=d.tick_jo, height=200, net_labels=None):
    """comps: [{'name', 'values', 'color'}] (같은 단위). net: 위치별 순합계(없으면 요소 합). net_labels: {위치: 글자}"""
    n = len(xlabels)
    nets = net if net is not None else [sum(c["values"][i] or 0 for c in comps) for i in range(n)]
    ups = [sum(max(c["values"][i] or 0, 0) for c in comps) for i in range(n)]
    downs = [sum(min(c["values"][i] or 0, 0) for c in comps) for i in range(n)]
    lo, hi, ticks = d.axis(ups + downs + [x for x in nets if x is not None])
    span = hi - lo
    zero = (0 - lo) / span * 100
    slots = []
    for i in range(n):
        marks, up, down = [], 0.0, 0.0
        pos_items = [c for c in comps if (c["values"][i] or 0) > 0]
        neg_items = [c for c in comps if (c["values"][i] or 0) < 0]
        for k, c in enumerate(pos_items):
            v = c["values"][i]
            top = " top" if k == len(pos_items) - 1 else ""
            marks.append(f'<i class="bar stk{top}" style="bottom:{zero + up / span * 100:.3f}%;height:{v / span * 100:.3f}%;--c:var({c["color"]})"></i>')
            up += v
        for k, c in enumerate(neg_items):
            v = -c["values"][i]
            bot = " bot" if k == len(neg_items) - 1 else ""
            marks.append(f'<i class="bar stk neg{bot}" style="top:{100 - zero + down / span * 100:.3f}%;height:{v / span * 100:.3f}%;--c:var({c["color"]})"></i>')
            down += v
        if nets[i] is not None:
            y = (nets[i] - lo) / span * 100
            marks.append(f'<i class="netbar" style="bottom:{y:.3f}%"></i>')
            text = (net_labels or {}).get(i)
            if text:
                spot = f"bottom:calc({zero + up / span * 100:.3f}% + 4px)" if nets[i] >= 0 else \
                    f"top:calc({100 - zero + down / span * 100:.3f}% + 4px)"
                marks.append(f'<b class="vl" style="{spot}">{esc(text)}</b>')
        title, rows, note = tips(i)
        slots.append(f'<div class="slot" style="left:{i / n * 100:.4f}%;width:{100 / n:.4f}%"'
                     f'{d.tip_attr(title, rows, note)}>{"".join(marks)}</div>')
    return (f'<div class="plot cc k1 dv" style="--h:{height}px;--n:{n}">{d._y_axis(lo, hi, ticks, ticks_fmt)}'
            f'<div class="pa">{d._grid(lo, hi, ticks)}{"".join(slots)}</div>{d._xa(xlabels)}</div>')


def stage_ladder(stages, items):
    """items: [{'area', 'name', 'stage'(1~len(stages)), 'status'}] → 단계별 칸에 점을 찍은 표."""
    head = "".join(f'<th scope="col"><span class="sn">{i}</span>{esc(s)}</th>' for i, s in enumerate(stages, 1))
    rows = []
    for it in items:
        cells = []
        for i in range(1, len(stages) + 1):
            if i < it["stage"]:
                cells.append('<td class="done"><i></i></td>')
            elif i == it["stage"]:
                cells.append('<td class="now"><i></i></td>')
            else:
                cells.append('<td class="todo"><i></i></td>')
        rows.append(f'<tr><th scope="row"><b>{esc(it["name"])}</b><span>{esc(it["area"])}</span></th>{"".join(cells)}</tr>')
    return (f'<table class="ladder"><thead><tr><th scope="col">사업</th>{head}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')
