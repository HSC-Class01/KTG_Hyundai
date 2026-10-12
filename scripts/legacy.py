"""2010~2015년 공시 원문에서 연결재무제표 숫자 추출.

OpenDART 재무제표 API는 2015년(분·반기는 2016년)부터만 숫자를 줍니다. 그 이전 보고서도 원문(XML)에는
'XBRL 재무제표' 표가 들어 있어서, 표 제목의 날짜로 각 열이 어느 기간인지 판단해 숫자를 읽습니다.

안전장치
- 제목에 '연결'이 있는 재무상태표·손익계산서·현금흐름표만 읽습니다. (별도·개별 재무제표 제외)
- 각 열의 기간은 제목에 적힌 날짜(… 부터 … 까지 / … 현재)로만 정합니다. '3개월' 열은 쓰지 않습니다.
- 그 기간의 자기 보고서 숫자를 먼저 쓰고, 없을 때만 다음 보고서의 비교 열을 씁니다.
- API 숫자가 있는 칸은 덮어쓰지 않습니다. 대신 원문 추출값과 비교해 일치율을 기록합니다.
- 자산 = 부채 + 자본이 맞지 않는 기간의 재무상태표 숫자는 쓰지 않습니다.
"""
import re
import zipfile
from datetime import date

import financials as fin

LAST_YEAR = 2015   # 이 연도까지 원문에서 보충합니다

EXTRA_NAMES = {
    "revenue": ("매출액", "매출", "수익(매출액)", "영업수익"),
    "net_income": ("당기순이익", "당기순이익(손실)", "분기순이익", "분기순이익(손실)", "반기순이익", "반기순이익(손실)",
                   "연결당기순이익", "연결분기순이익", "연결반기순이익"),
    "operating_profit": ("영업이익", "영업이익(손실)", "영업손익"),
    "operating_cashflow": ("영업활동현금흐름", "영업활동으로인한현금흐름", "영업활동으로부터의현금흐름"),
    "investing_cashflow": ("투자활동현금흐름", "투자활동으로인한현금흐름", "투자활동으로부터의현금흐름"),
    "financing_cashflow": ("재무활동현금흐름", "재무활동으로인한현금흐름", "재무활동으로부터의현금흐름"),
}
SKIP_FIELDS = {"net_income_owners", "net_income_nci"}   # 같은 이름의 행이 여러 번 나와 원문에서는 읽지 않습니다
EXPENSE_FIELDS = {"cost_of_sales", "sga"}   # 일부 원문은 비용을 (괄호) 음수로 적습니다. 비용은 양수로 맞춥니다.
STATEMENT_FIELDS = {"BS": fin.BS_FIELDS, "IS": fin.IS_FIELDS, "CF": fin.CF_FIELDS}

DATE = r"(\d{4})\s*[.년]\s*(\d{1,2})\s*[.월]\s*(\d{1,2})\s*일?"
SPEC_RE = re.compile(r"제\s*(\d+)\s*기\s*((?:[1-4]\s*분기|반기)?\s*(?:말|초|누적)?)\s*" + DATE
                     + r"\s*(?:부터\s*" + DATE + r"\s*까지|현재)")
UNIT_RE = re.compile(r"단위\s*[:：]\s*(백만원|천원|원)")
UNITS = {"백만원": 1_000_000, "천원": 1_000, "원": 1}


def _names():
    out = {}
    for field, (_, _, names) in fin.FIELDS.items():
        if field in SKIP_FIELDS:
            continue
        for n in names + EXTRA_NAMES.get(field, ()):
            out.setdefault(_label(n), field)
    return out


def _label(text):
    """'Ⅰ. 매출액(주석 3)' → '매출액'. 번호·주석 표시·띄어쓰기를 지웁니다."""
    t = re.sub(r"\(주석[^)]*\)|\(주\s*[\d,\s]+\)", "", text)
    t = re.sub(r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ]+|\d{1,2}|\(\d{1,2}\)|[가-하])\s*[.)]\s*", "", t)
    return re.sub(r"[\s　]+", "", t)


NAMES = None


def _text(fragment):
    s = re.sub(r"<[^>]+>", " ", fragment)
    s = s.replace("&cr;", " ").replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"[\s　]+", " ", s).strip()


def _value(text, unit):
    t = text.strip()
    if t in ("-", "–", "—"):
        return 0
    v = fin.amount(t)
    return None if v is None else v * unit


def decode(data):
    for enc in ("utf-8", "cp949"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("cp949", errors="replace")


def statement_kind(title):
    if "연결" not in title or "자본변동" in title:
        return None
    if "재무상태표" in title or "대차대조표" in title:
        return "BS"
    if "현금흐름표" in title:
        return "CF"
    if "손익계산서" in title:
        return "IS"
    return None


def _specs(title):
    out = []
    for m in SPEC_RE.finditer(title):
        d1 = date(int(m.group(3)), int(m.group(4)), int(m.group(5)))
        if m.group(6):
            d2 = date(int(m.group(6)), int(m.group(7)), int(m.group(8)))
            out.append({"gi": int(m.group(1)), "start": d1, "end": d2})
        else:
            out.append({"gi": int(m.group(1)), "start": None, "end": d1})
    return out


def _cells(tr):
    out = []
    for m in re.finditer(r"<(TH|TD|TE|TU)\b([^>]*)>(.*?)</\1>", tr, re.S):
        span = re.search(r'COLSPAN="(\d+)"', m.group(2))
        out.append((_text(m.group(3)), int(span.group(1)) if span else 1))
    return out


def _columns(head_rows, specs, n_values):
    """머리글 행과 제목의 기간 목록으로 각 숫자 열의 (기간 명세, 3개월 여부)를 만듭니다."""
    if not head_rows:
        return None
    top = head_rows[0][1:]          # 첫 칸은 '과목'
    sub = [c[0] for c in head_rows[1]] if len(head_rows) > 1 else []
    cols, si = [], 0
    for gi, (_, span) in enumerate(top):
        if gi >= len(specs):
            return None
        for _ in range(span):
            label = sub[si] if span > 1 and si < len(sub) else ""
            if span > 1:
                si += 1
            cols.append((specs[gi], "3개월" in label))
    return cols if len(cols) == n_values else None


def parse_document(text):
    """원문 하나에서 [(기간(연,월), 재무제표 종류, {필드: 값}, 설명)]을 돌려줍니다."""
    global NAMES
    if NAMES is None:
        NAMES = _names()
    found = []
    for g in re.finditer(r"<TABLE-GROUP\b[^>]*>(.*?)</TABLE-GROUP>", text, re.S):
        tables = re.findall(r"<TABLE\b[^>]*>(.*?)</TABLE>", g.group(1), re.S)
        if len(tables) < 2:
            continue
        title = _text(tables[0])
        kind = statement_kind(title)
        unit_m = UNIT_RE.search(title)
        specs = _specs(title)
        if not kind or not unit_m or not specs:
            continue
        unit = UNITS[unit_m.group(1)]
        data = tables[1]
        head = re.search(r"<THEAD>(.*?)</THEAD>", data, re.S)
        head_rows = [_cells(tr) for tr in re.findall(r"<TR\b[^>]*>(.*?)</TR>", head.group(1), re.S)] if head else []
        body = re.sub(r"<THEAD>.*?</THEAD>", "", data, flags=re.S)
        rows = [_cells(tr) for tr in re.findall(r"<TR\b[^>]*>(.*?)</TR>", body, re.S)]
        rows = [r for r in rows if len(r) >= 2]
        if not rows:
            continue
        n_values = max(len(r) - 1 for r in rows)
        cols = _columns(head_rows, specs, n_values)
        if cols is None:
            continue
        per_col = [dict() for _ in cols]
        allowed = set(STATEMENT_FIELDS[kind])
        for r in rows:
            field = NAMES.get(_label(r[0][0]))
            if field not in allowed:
                continue
            for j, (txt, _) in enumerate(r[1:len(cols) + 1]):
                if field in per_col[j]:
                    continue     # 같은 이름이 다시 나오면 처음 값을 씁니다
                v = _value(txt, unit)
                if v is not None:
                    per_col[j][field] = abs(v) if field in EXPENSE_FIELDS else v
        for (spec, three_month), values in zip(cols, per_col):
            if not values or three_month:
                continue
            end = spec["end"]
            if end.month not in (3, 6, 9, 12) or end.day < 28:
                continue
            if kind != "BS" and (spec["start"] is None or (spec["start"].month, spec["start"].day) != (1, 1)
                                 or spec["start"].year != end.year):
                continue
            found.append(((end.year, end.month), kind, values, title[:60]))
    return found


def parse_archive(path):
    results = []
    with zipfile.ZipFile(path) as z:
        for name in sorted(z.namelist()):
            if name.lower().endswith(".xml"):
                results.extend(parse_document(decode(z.read(name))))
    return results


def _balanced(v):
    gap = fin.balance_gap(v)
    return gap is None or abs(gap) <= max(abs(v.get("assets") or 0) * 1e-5, 5_000_000)


def fill(periods, latest, raw_dir, cfg):
    """원문 숫자로 2010~2015년을 채웁니다.

    우선순위: 그 기간 보고서의 API 숫자 > 그 기간 보고서 원문 > 다음 보고서(API)의 비교 숫자 > 다음 보고서 원문의 비교 열.
    2016년 보고서도 읽어서, 같은 보고서의 API 숫자와 원문 추출값이 일치하는지(추출 정확도) 확인합니다.
    """
    report = {"parsed": 0, "filled_periods": [], "checked": 0, "matched": 0, "mismatches": [],
              "restated": 0, "errors": []}
    own, prior = {}, {}
    for (y, m), filing in sorted(latest.items()):
        if y > LAST_YEAR + 1:
            continue
        path = raw_dir / f"{filing['rcept_no']}.zip"
        if not path.exists():
            continue
        try:
            items = parse_archive(path)
        except (zipfile.BadZipFile, OSError) as exc:
            report["errors"].append(f"{filing['report_nm']}: {exc}")
            continue
        report["parsed"] += 1
        for target, kind, values, title in items:
            bucket = own if target == (y, m) else prior
            slot = bucket.setdefault(target, {})
            for field, value in values.items():
                slot.setdefault(field, value)   # 비교 열은 가장 먼저 나온(가까운) 보고서의 값을 씁니다
    for target in sorted(set(own) | set(prior)):
        y, m = target
        if y < cfg["first_year"]:
            continue
        for bucket, source in ((own, "document"), (prior, "document-prior")):
            values = dict(bucket.get(target) or {})
            if not values:
                continue
            bs = {f: values[f] for f in fin.BS_FIELDS if f in values}
            if bs and not _balanced(bs):
                values = {f: v for f, v in values.items() if f not in fin.BS_FIELDS}
                report["errors"].append(f"{y}.{m:02d} 재무상태표: 자산 ≠ 부채 + 자본이라 사용하지 않음")
            if target not in periods:
                periods[target] = fin.blank_period(y, m)
                f = latest.get(target)
                if f:
                    periods[target].update(receipt=f["rcept_no"], report_name=f["report_nm"], filed=f["rcept_dt"])
            p = periods[target]
            changed = False
            for field, value in values.items():
                current, cur_source = p["values"].get(field), p["sources"].get(field, "")
                if current is not None and cur_source == "api":
                    if source == "document":   # 같은 보고서: 추출 정확도 확인
                        report["checked"] += 1
                        if abs(current - value) <= max(abs(current) * 0.001, 1_000_000):
                            report["matched"] += 1
                        elif len(report["mismatches"]) < 20:
                            report["mismatches"].append(f"{y}.{m:02d} {fin.LABELS[field]}: API {current:,} · 원문 {value:,}")
                    continue
                if y > LAST_YEAR:
                    continue
                if current is None or (source == "document" and cur_source in ("api-prior", "document-prior")):
                    if current is not None and abs(current - value) > max(abs(current) * 0.001, 1_000_000):
                        report["restated"] += 1
                    p["values"][field] = value
                    p["sources"][field] = source
                    changed = True
            if changed and target not in report["filled_periods"]:
                report["filled_periods"].append(target)
    report["filled_periods"] = [f"{y}.{m:02d}" for y, m in sorted(report["filled_periods"])]
    return report
