"""공시 원문의 '주석'에서 감가상각비와 이자비용을 읽습니다 (EBITDA·이자보상배율 계산용).

감가상각비·이자비용은 재무제표 본문(OpenDART 재무제표 API)에 나오지 않고, 연결재무제표 주석의
'현금흐름표 - 영업으로부터 창출된 현금(조정 항목)' 표에 있습니다. 이 표를 찾아 당기(당분기 누적) 열을 읽습니다.

안전장치
- 연결재무제표 주석(또는 연결감사보고서)에 있는 표만 읽습니다. 별도 재무제표 주석은 건너뜁니다.
- 표 바로 앞 문장에 '현금'이 있고, 이자비용과 감가상각비(또는 상각비) 줄이 모두 있는 표만 씁니다.
- 단위(백만원·천원·원)가 확인되지 않으면 쓰지 않습니다.
- 그 기간 보고서에서 못 찾으면 다음 보고서의 전기(비교) 열로 채웁니다.
"""
import re
import zipfile

import legacy

# 줄 이름 → 항목. 이름 끝의 '에 대한 조정', '조정'은 지우고 비교합니다.
ROWS = {
    "유형자산감가상각비": "dep_ppe", "감가상각비": "dep_ppe", "감가상각비,유형자산": "dep_ppe",
    "투자부동산감가상각비": "dep_ip", "투자부동산상각비": "dep_ip",
    "운휴자산감가상각비": "dep_idle",
    "사용권자산상각비": "dep_rou", "사용권자산감가상각비": "dep_rou", "감가상각비,사용권자산": "dep_rou",
    "무형자산상각비": "amort", "상각비,무형자산": "amort",
    "이자비용": "interest",
}
DEPRECIATION_PARTS = ("dep_ppe", "dep_ip", "dep_idle", "dep_rou", "amort")
UNIT_RE = re.compile(r"단위\s*[:：]?\s*(백만원|천원|원)")
UNITS = {"백만원": 1_000_000, "천원": 1_000, "원": 1}


def _row_key(text):
    t = re.sub(r"\(주석[^)]*\)|\(주\s*[\d,\s]+\)|\(\*\d*\)", "", text)
    t = legacy._label(t)
    t = re.sub(r"(에대한조정|조정|의조정)$", "", t)
    return ROWS.get(t)


def _cells(tr):
    return [legacy._text(m.group(3)) for m in re.finditer(r"<(TH|TD|TE|TU)\b([^>]*)>(.*?)</\1>", tr, re.S)]


def _numbers(cells):
    out = []
    for c in cells:
        s = c.strip()
        if s in ("-", "–", "—"):
            out.append(0)
            continue
        v = legacy.fin.amount(s)
        if v is not None:
            out.append(v)
    return out


def _documents(zf, rcept_no):
    """(문서 이름, 본문, 문서 전체가 연결인지) 목록. 본문 보고서와 연결감사보고서만 봅니다."""
    docs = []
    for name in sorted(zf.namelist()):
        if not name.lower().endswith(".xml"):
            continue
        text = legacy.decode(zf.read(name))
        doc_name = re.search(r"<DOCUMENT-NAME[^>]*>(.*?)</DOCUMENT-NAME>", text, re.S)
        doc_name = legacy._text(doc_name.group(1)) if doc_name else ""
        if name.rsplit("/", 1)[-1].lower() == f"{rcept_no}.xml":
            docs.insert(0, (name, text, False))
        elif "연결" in doc_name and "감사보고서" in doc_name:
            docs.append((name, text, True))
    return docs


def _consolidated(text, pos, whole_doc):
    if whole_doc:
        return True
    titles = [(m.start(), legacy._text(m.group(1))) for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", text[:pos], re.S)]
    if not titles:
        return False
    near = titles[-1][1]
    if "별도" in near:
        return False
    if "(연결)" in near:
        return True
    majors = [t for _, t in titles if re.search(r"재무제표\s*(에\s*대한\s*)?주석", t)]
    return bool(majors) and "연결" in majors[-1]


def parse(path, rcept_no):
    """보고서 원문 ZIP 하나에서 {'current': {...}, 'prior': {...}} (원 단위)를 돌려줍니다. 못 찾으면 None."""
    with zipfile.ZipFile(path) as zf:
        docs = _documents(zf, rcept_no)
    for _, text, whole in docs:
        for m in re.finditer(r"<TABLE\b[^>]*>(.*?)</TABLE>", text, re.S):
            body = m.group(1)
            if "이자비용" not in body:
                continue
            cur, pri = {}, {}
            for tr in re.findall(r"<TR\b[^>]*>(.*?)</TR>", body, re.S):
                cells = _cells(tr)
                if not cells:
                    continue
                key = _row_key(cells[0])
                if not key or key in cur:
                    continue
                nums = _numbers(cells[1:])
                if nums:
                    cur[key] = nums[0]
                    if len(nums) > 1:
                        pri[key] = nums[1]
            if "interest" not in cur or not any(k in cur for k in DEPRECIATION_PARTS):
                continue
            head = legacy._text(text[max(0, m.start() - 1500):m.start()])
            if "현금" not in head[-700:]:
                continue
            if not _consolidated(text, m.start(), whole):
                continue
            units = UNIT_RE.findall(head[-500:]) or UNIT_RE.findall(legacy._text(body)[:200])
            if not units:
                continue
            unit = UNITS[units[-1]]

            def pack(d):
                if not d:
                    return None
                parts = [d[k] for k in DEPRECIATION_PARTS if k in d]
                out = {"dep_amort": sum(abs(x) for x in parts) * unit if parts else None,
                       "interest_expense": abs(d["interest"]) * unit if "interest" in d else None}
                return out
            # 당기·전기가 표 두 개로 나뉜 서식(2023년 이후)은 전기 열이 없습니다.
            return {"current": pack(cur), "prior": pack(pri) if len(pri) >= len(cur) - 1 else None}
    return None


def fill(periods, latest, raw_dir, first_year):
    """보고서 기간별로 주석 숫자를 채웁니다. 반환: 기록용 요약."""
    found, prior = {}, {}
    report = {"parsed": 0, "found": 0, "periods": [], "from_prior": []}
    for (y, m), filing in sorted(latest.items()):
        path = raw_dir / f"{filing['rcept_no']}.zip"
        if not path.exists():
            continue
        report["parsed"] += 1
        try:
            got = parse(path, filing["rcept_no"])
        except (zipfile.BadZipFile, OSError):
            continue
        if not got:
            continue
        report["found"] += 1
        if got["current"]:
            found[(y, m)] = got["current"]
        if got["prior"]:
            prior.setdefault((y - 1, m), got["prior"])
    for target in sorted(set(found) | set(prior)):
        if target[0] < first_year or target not in periods:
            continue
        values, source = (found[target], "note") if target in found else (prior[target], "note-prior")
        p = periods[target]
        for k, v in values.items():
            if v is not None and p["values"].get(k) is None:
                p["values"][k] = v
                p["sources"][k] = source
        (report["periods"] if source == "note" else report["from_prior"]).append(f"{target[0]}.{target[1]:02d}")
    return report
