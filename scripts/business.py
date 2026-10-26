"""사업보고서 본문에서 재무제표 밖의 숫자를 읽습니다 (수주잔고, PF 보증, 사업부문, 직원 등).

재무제표는 OpenDART 재무제표 API로 받지만, 건설사를 이해하는 데 꼭 필요한 숫자 중 일부는
보고서 본문(Ⅱ. 사업의 내용, Ⅷ. 직원 현황, 연결 주석의 우발부채)에만 있습니다.
저장된 원문(XML)에서 아래 숫자를 읽습니다. 네트워크는 쓰지 않습니다.

- 수주잔고: 'Ⅱ. 사업의 내용 > 수주상황' 표의 회사별 국내·해외 합계 줄(계약잔액)을 더한 값.
  보고서가 내부거래를 뺀 '연결기준 계약잔액'을 문장으로 적어 두면 그 값도 함께 기록합니다.
- PF 보증: 연결 주석 '우발부채 및 약정사항'의 '보증금액 기준 … 신용보강' 문장.
  2023년 사업보고서부터 정비사업 PF까지 포함하는 새 공시 기준으로 바뀌어서, 그 이후만 같은 기준입니다.
- 사업부문별 매출(국내·해외), 주요 공사(공사별 도급액·완성액·잔액), 국내 건설 수주 통계, 원자재 가격
  : 가장 최근 사업보고서 한 건에서 읽습니다.
- 직원 수·1인 평균 급여, 별도(현대건설 단독) 매출·영업이익: 각 연도 사업보고서에서 읽습니다.

안전장치
- 표 머리글에 '계약잔액'(또는 '수주잔고')과 '도급액'이 있는 표만 수주 표로 봅니다.
- 합계 줄에 금액이 세 개(도급액·완성액·잔액) 이상 있을 때만 씁니다.
- 회사 표 중 하나라도 합계를 못 읽으면 그 기간 수주잔고는 비워 둡니다(일부만 더한 값을 쓰지 않음).
- 읽은 값은 모두 원 단위 정수입니다. 단위가 '백만원'으로 확인될 때만 씁니다.
"""
import re
import zipfile

import financials as fin
import legacy

MILLION = 1_000_000
COMPANY_RE = re.compile(r"(현대건설|현대엔지니어링|현대스틸산업|현대종합설계|현대씨엔아이|현대도시개발|현대케미칼|현대엠코"
                        r"|현대서산농장|현대에코에너지|Hyundai[A-Za-z .,&]+)")
BACKLOG_HEAD = re.compile(r"계약\s*잔액|수주\s*잔고|잔\s*고")
CONTRACT_HEAD = re.compile(r"도급\s*액|수주\s*총액|계약\s*금액|도급\s*금액")
STOP_RE = re.compile(r"<TITLE|판매\s*경로|판매\s*방법|시장\s*위험|위험\s*관리|파생\s*상품|주요\s*계약|연구\s*개발")
TOTAL_KIND = {"국내합계": "domestic", "국내소계": "domestic", "국내계": "domestic",
              "해외합계": "overseas", "해외소계": "overseas", "해외계": "overseas",
              "국내/해외합계": "total", "국내외합계": "total", "합계": "total", "총계": "total", "총합계": "total"}
CONS_RE = re.compile(r"연결\s*기준\s*계약\s*잔액은\s*([\d,]+)\s*백만\s*원|연결\s*회사의\s*건설\s*계약\s*수주\s*잔고는\s*([\d,]+)\s*백만\s*원")


# ---------------------------------------------------------------------------
# 공통: 원문 열기, 표 읽기
# ---------------------------------------------------------------------------
def main_document(path, rcept_no):
    """보고서 압축 파일에서 본문 XML(접수번호.xml)을 글자로 돌려줍니다. 없으면 None."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            main = [n for n in names if n.rsplit("/", 1)[-1].lower() == f"{rcept_no}.xml"]
            if not main:
                return None
            return legacy.decode(zf.read(main[0]))
    except (OSError, zipfile.BadZipFile, KeyError):
        return None


def table_rows(table_xml):
    """<TABLE> 하나 → [[셀 글자, …], …]"""
    rows = []
    for tr in re.finditer(r"<TR\b.*?</TR>", table_xml, re.S):
        rows.append([legacy._text(c.group(3)) for c in re.finditer(r"<(TH|TD|TE|TU)\b([^>]*)>(.*?)</\1>", tr.group(0), re.S)])
    return rows


def tables_between(xml, start, end):
    """xml[start:end] 안의 표: [(표 시작 위치, 행 목록)]"""
    out = []
    for m in re.finditer(r"<TABLE\b.*?</TABLE>", xml[start:end], re.S):
        out.append((start + m.start(), table_rows(m.group(0))))
    return out


def label(text):
    return re.sub(r"[\s　·ㆍ]+", "", text or "")


def amounts(cells):
    """셀 목록에서 금액만(퍼센트·날짜 제외) 순서대로."""
    out = []
    for c in cells:
        s = c.strip()
        if not s or "%" in s or re.match(r"^\d{4}[-.]\d{1,2}([-.]\d{1,2})?$", s):
            continue
        if s in ("-", "–", "—"):
            out.append(0)
            continue
        v = fin.amount(s)
        if v is not None:
            out.append(v)
    return out


def plain(xml_fragment):
    return legacy._text(xml_fragment)


# ---------------------------------------------------------------------------
# 1. 수주잔고 (수주상황 표)
# ---------------------------------------------------------------------------
def _table_head(xml, pos):
    """pos에서 시작하는 표의 머리글(앞의 두 줄) 글자. 표가 길어도 앞부분만 봅니다."""
    part = xml[pos:pos + 8000]
    rows = [legacy._text(tr.group(0)) for tr in re.finditer(r"<TR\b.*?</TR>", part, re.S)][:2]
    return " ".join(rows)


def _order_start(xml):
    """'수주상황' 제목 중 바로 뒤(표 네 개 안)에 수주 표가 오는 위치. 없으면 None."""
    for m in re.finditer(r"수주\s*상황|수주\s*현황", xml):
        after = xml[m.end():m.end() + 40]
        if re.match(r"[\s<>/A-Za-z=\"\-0-9]*\.{3,}", after) or "...." in after:
            continue   # 목차 줄
        for t in list(re.finditer(r"<TABLE\b", xml[m.end():m.end() + 60000]))[:4]:
            head = _table_head(xml, m.end() + t.start())
            if BACKLOG_HEAD.search(head) and CONTRACT_HEAD.search(head):
                return m.start()
    return None


def _company_before(xml, pos):
    found = COMPANY_RE.findall(plain(xml[max(0, pos - 1200):pos]))
    return found[-1].strip() if found else ""


def parse_backlog(xml):
    """수주상황 표 → {'total', 'domestic', 'overseas', 'companies', 'consolidated', 'complete'} (원). 표가 없으면 None."""
    if not xml:
        return None
    start = _order_start(xml)
    if start is None:
        return None
    stop = STOP_RE.search(xml, start + 200)
    end = stop.start() if stop else min(len(xml), start + 600000)
    companies = []
    unit_ok = "백만원" in plain(xml[start:start + 4000]).replace(" ", "")
    for pos, rows in tables_between(xml, start, end):
        head = " ".join(" ".join(r) for r in rows[:2])
        if not (BACKLOG_HEAD.search(head) and CONTRACT_HEAD.search(head)):
            continue
        got = {"name": _company_before(xml, pos), "domestic": None, "overseas": None, "total": None}
        for r in rows:
            if not r:
                continue
            kind = TOTAL_KIND.get(label(r[0]))
            if not kind:
                continue
            nums = amounts(r[1:])
            if len(nums) >= 3:
                got[kind] = nums[2] * MILLION
        if got["total"] is None and (got["domestic"] is not None or got["overseas"] is not None):
            if got["domestic"] is not None and got["overseas"] is not None:
                got["total"] = got["domestic"] + got["overseas"]
        companies.append(got)
    if not companies or not unit_ok:
        return None
    complete = all(c["total"] is not None for c in companies)
    total = sum(c["total"] or 0 for c in companies)
    dom = sum(c["domestic"] or 0 for c in companies if c["domestic"] is not None)
    ovs = sum(c["overseas"] or 0 for c in companies if c["overseas"] is not None)
    cons = None
    m = CONS_RE.search(plain(xml))
    if m:
        cons = fin.amount(m.group(1) or m.group(2)) * MILLION
    return {"total": total if complete else None, "domestic": dom or None, "overseas": ovs or None,
            "companies": companies, "consolidated": cons, "complete": complete}


# ---------------------------------------------------------------------------
# 2. 금액 글자 ("25조 5,151억원", "12조 8천억원", "4.9조원", "473억달러")
# ---------------------------------------------------------------------------
KAMT = r"(\d[\d,]*(?:\.\d+)?\s*조(?:\s*\d[\d,]*(?:\.\d+)?\s*천?\s*억)?|\d[\d,]*(?:\.\d+)?\s*천?\s*억)\s*원"


def korean_amount(text):
    """'25조 5,151억원' → 25,515,100,000,000 (원). 읽지 못하면 None."""
    s = (text or "").replace(",", "").replace(" ", "")
    m = re.match(r"^(?:(\d+(?:\.\d+)?)조)?(?:(\d+(?:\.\d+)?)(천)?억)?원?$", s)
    if not m or (m.group(1) is None and m.group(2) is None):
        return None
    jo = float(m.group(1) or 0)
    eok = float(m.group(2) or 0) * (1000 if m.group(3) else 1)
    return int(round(jo * 1e12 + eok * 1e8))


# ---------------------------------------------------------------------------
# 3. PF 보증 (2023년 사업보고서부터의 공시 기준)
# ---------------------------------------------------------------------------
PF_RE = re.compile(r"PF\s*\(?\s*대출\s*\)?\s*(?:과|와)?\s*관련하여\s*보증\s*금액\s*기준\s*([\d,]+)\s*백만\s*원\s*"
                   r"\(\s*전기\s*말?\s*:?\s*([\d,]+)\s*백만\s*원\s*\)")


def parse_pf(xml):
    """{'current': 원, 'prior': 원} — 연결 기준(같은 문장이 별도 주석에도 있어 가장 큰 값). 없으면 None."""
    if not xml:
        return None
    found = [(fin.amount(m.group(1)), fin.amount(m.group(2))) for m in PF_RE.finditer(plain(xml))]
    found = [f for f in found if f[0] and f[1] is not None]
    if not found:
        return None
    cur, prior = max(found)
    return {"current": cur * MILLION, "prior": prior * MILLION}


# ---------------------------------------------------------------------------
# 4. 신규 수주 (현대건설 단독, '지배회사 현황' 문단)
# ---------------------------------------------------------------------------
ORDER_ANCHORS = (r"지배회사\s*현황", r"\[\s*현대건설\s*\]", r"◎\s*현대건설")
NEAR = r"(?:[^.]|\.(?=\d)){0,80}?"
ORDER_TOTAL = (r"총\s*" + KAMT + r"\s*의\s*수주\s*실적",
               KAMT + r"\s*의\s*수주\s*실적",
               KAMT + r"\s*을\s*수주하며",
               r"신규\s*수주\s*금액은\s*" + KAMT,
               r"수주\s*\(\s*별도\s*기준\s*\)\s*는" + NEAR + KAMT)
ORDER_PART = r"\s*(?:의\s*수주|을\s*수주|를\s*수주|을\s*기록|를\s*기록|을\s*달성|를\s*달성)"


def _part(para, region, other):
    """'국내부문에서는 … 5조 7,375억원을 수주' 같은 문장에서 그 부문 금액. 다른 부문 이름을 넘어가지 않습니다.
    괄호 안 금액(전년 수치 등)은 쓰지 않습니다."""
    near = r"(?:(?!" + other + r")[^.]|\.(?=\d)){0,80}?"
    m = re.search(region + r"\s*부문" + near + KAMT + ORDER_PART, para)
    if not m:
        m = re.search(region + r"\s*부문(?:에서는|은|은\s|에서)?\s*" + r"(?:(?!" + other + r")[^.(]){0,40}?" + KAMT + r"(?!\s*\))", para)
        if m and para[max(0, m.start(1) - 1)] == "(":
            m = None
    return korean_amount(m.group(1)) if m else None


def _first(patterns, text):
    """여러 패턴 중 글에서 가장 먼저 나오는 금액."""
    hits = [(m.start(), m.group(1)) for p in patterns for m in [re.search(p, text)] if m]
    return korean_amount(min(hits)[1]) if hits else None


def parse_new_orders(xml):
    """{'total', 'domestic', 'overseas'} (원, 현대건설 별도). 문단을 못 찾으면 None."""
    if not xml:
        return None
    text = plain(xml)
    for anchor in ORDER_ANCHORS:
        for m in re.finditer(anchor, text):
            para = text[m.start():m.start() + 700]
            if "수주" not in para[:400]:
                continue
            dom = ovs = None
            g = re.search(r"국내\s*" + KAMT + r"\s*,\s*해외\s*" + KAMT + r"\s*,\s*총\s*" + KAMT, para)
            if g:
                dom, ovs, total = (korean_amount(g.group(i)) for i in (1, 2, 3))
            else:
                total = _first(ORDER_TOTAL, para[:400])
                dom, ovs = _part(para, "국내", "해외"), _part(para, "해외", "국내")
                if dom is None or ovs is None:
                    dom = ovs = None
            if total is None and dom and ovs:
                total = dom + ovs
            if total and 1e12 <= total <= 1e14:
                if dom and ovs and abs(dom + ovs - total) > 0.02 * total:
                    dom = ovs = None          # 국내·해외 합이 총액과 안 맞으면 총액만 씁니다
                return {"total": total, "domestic": dom, "overseas": ovs}
    m = re.search(r"지난\s*해\s*신규\s*수주\s*(?:역시|는|도)?\s*" + KAMT, text)   # 2010년 보고서 문장
    if m:
        total = korean_amount(m.group(1))
        if total and 1e12 <= total <= 1e14:
            return {"total": total, "domestic": None, "overseas": None}
    return None


# ---------------------------------------------------------------------------
# 5. 사업부문별 매출 (Ⅱ. 사업의 내용 > 주요 제품 및 서비스 / 매출실적)
# ---------------------------------------------------------------------------
def _num_start(cells):
    for i, c in enumerate(cells):
        s = c.strip()
        if s and (fin.amount(s) is not None or s in ("-", "–")) and not re.match(r"^\d{4}[-.]", s):
            return i
    return None


def parse_segments(xml):
    """{'periods': ['제76기', …], 'rows': [{'segment', 'products', 'domestic': [3], 'overseas': [3]}], 'subtotal', 'internal', 'total'}"""
    if not xml:
        return None
    for m in re.finditer(r"주요\s*제품\s*및\s*서비스|매출\s*실적", xml):
        for t in list(re.finditer(r"<TABLE\b", xml[m.end():m.end() + 30000]))[:3]:
            pos = m.end() + t.start()
            end = xml.find("</TABLE>", pos)
            rows = table_rows(xml[pos:end + 8])
            head = " ".join(" ".join(r) for r in rows[:2])
            if not ("사업부문" in head.replace(" ", "") and re.search(r"제\s*\d+\s*기", head)):
                continue
            periods = re.findall(r"제\s*\d+\s*기", " ".join(rows[0]))[:3]
            out, seg, prod = [], None, ""
            sub = internal = total = None
            for r in rows[1:]:
                i = _num_start(r)
                if i is None or i == 0:
                    continue
                kind = label(r[i - 1])
                nums = amounts(r[i:])
                vals = [nums[k] * MILLION if k < len(nums) else None for k in (0, 2, 4)]
                if i >= 3:
                    seg, prod = r[0].strip(), r[1].strip()
                if kind in ("국내", "해외") and seg:
                    if not out or out[-1]["segment"] != seg:
                        out.append({"segment": seg, "products": prod, "domestic": None, "overseas": None})
                    out[-1]["domestic" if kind == "국내" else "overseas"] = vals
                elif "소계" in kind:
                    sub = vals
                elif "내부" in kind:
                    internal = vals
                elif kind in ("합계", "총계"):
                    total = vals
            if out and total:
                return {"periods": periods, "rows": out, "subtotal": sub, "internal": internal, "total": total}
    return None


# ---------------------------------------------------------------------------
# 6. 국내 건설 수주 통계 (지배회사 현황 문단, 대한건설협회 인용)
# ---------------------------------------------------------------------------
ANY = r"(?:[^.]|\.(?=\d))*?"


def parse_market(xml):
    if not xml:
        return None
    text = plain(xml)
    m = re.search(r"(\d{4})\s*년\s*(1\s*~\s*\d+\s*월\s*)?국내\s*건설\s*수주는" + ANY + KAMT, text)
    if not m:
        return None
    para = text[m.start():m.start() + 900]
    out = {"year": int(m.group(1)), "partial": bool(m.group(2)), "total": korean_amount(m.group(3))}
    for key, pat in (("public", r"공공\s*부문은"), ("private", r"민간\s*부문은"),
                     ("civil", r"토목\s*공종은"), ("building", r"건축\s*공종은")):
        g = re.search(pat + ANY + KAMT, para)
        out[key] = korean_amount(g.group(1)) if g else None
    out["provisional"] = "잠정" in para[:200]
    ov = re.search(r"해외\s*건설\s*수주\s*(?:누계\s*금액|액)은" + ANY + r"(\d[\d,]*)\s*억\s*달러", text[m.start():m.start() + 2500])
    out["overseas_usd_100m"] = fin.amount(ov.group(1)) if ov else None
    if out["public"] and out["private"] and out["total"] and abs(out["public"] + out["private"] - out["total"]) > 0.02 * out["total"]:
        out["public"] = out["private"] = None
    return out


# ---------------------------------------------------------------------------
# 7. 원자재 가격 (Ⅱ. 3. 원재료 > 주요 원자재 가격변동 추이)
# ---------------------------------------------------------------------------
def parse_materials(xml):
    if not xml:
        return None
    m = re.search(r"원자재\s*가격\s*변동\s*추이", xml)
    if not m:
        return None
    t = re.search(r"<TABLE\b", xml[m.end():m.end() + 8000])
    if not t:
        return None
    pos = m.end() + t.start()
    rows = table_rows(xml[pos:xml.find("</TABLE>", pos) + 8])
    if not rows:
        return None
    periods = re.findall(r"제\s*\d+\s*기", " ".join(rows[0]))[:3]
    items = []
    for r in rows[1:]:
        i = _num_start(r[1:])
        if i is None:
            continue
        i += 1
        name = r[i - 1].strip()
        nums = amounts(r[i:i + 3])
        note = r[i + 3].strip() if len(r) > i + 3 else ""
        if name and len(nums) == 3:
            unit = re.search(r"원\s*/\s*([^\s,()]+)", note)
            items.append({"name": name, "values": nums, "unit": f"원/{unit.group(1)}" if unit else "원", "note": note})
    return {"periods": periods, "items": items} if items else None


# ---------------------------------------------------------------------------
# 8. 직원 수·급여 (Ⅷ. 직원 현황 '합계' 줄), 별도 매출·영업이익 (Ⅲ. 요약재무정보)
# ---------------------------------------------------------------------------
def parse_employees(xml):
    """{'count', 'salary_total'(원), 'avg_salary'(원)} — 합계 줄에서 (인원, 급여총액, 1인평균)이 서로 맞는 세 수를 찾습니다."""
    if not xml:
        return None
    for m in re.finditer(r"직원\s*(?:등의?)?\s*현황|직원의\s*현황", xml):
        for t in list(re.finditer(r"<TABLE\b", xml[m.end():m.end() + 30000]))[:4]:
            pos = m.end() + t.start()
            rows = table_rows(xml[pos:xml.find("</TABLE>", pos) + 8])
            head = " ".join(" ".join(r) for r in rows[:3])
            if "급여" not in head:
                continue
            for r in rows:
                if not r or label(r[0]) not in ("합계", "계", "총계"):
                    continue
                nums = amounts(r[1:])
                best = None
                for a in range(len(nums)):
                    for b in range(a + 1, len(nums)):
                        for c in range(b + 1, len(nums)):
                            n, tot, avg = nums[a], nums[b], nums[c]
                            if not (500 <= n <= 100000 and tot >= 10000 and avg > 0):
                                continue
                            for scale in (1, 1000):          # 1인평균이 백만원 또는 천원 단위
                                if avg / scale >= 20 and abs(tot / n * scale / avg - 1) <= 0.15:
                                    if best is None or n > best[0]:
                                        best = (n, tot, avg / scale)
                if best:
                    n, tot, avg = best
                    return {"count": n, "salary_total": tot * MILLION, "avg_salary": int(avg * MILLION)}
    return None


def parse_separate_summary(xml):
    """{'periods': [...], 'revenue': [3], 'operating_profit': [3], 'net_income': [3]} (원, 별도). 없으면 None."""
    if not xml:
        return None
    best = None
    for m in re.finditer(r"별도\s*요약\s*재무|별도\s*재무\s*제표에\s*관한\s*사항|별도\s*\)?\s*요약\s*재무\s*정보|개별\s*요약\s*재무", xml):
        rows = None
        for t in list(re.finditer(r"<TABLE\b", xml[m.end():m.end() + 8000]))[:3]:
            pos = m.end() + t.start()
            cand = table_rows(xml[pos:xml.find("</TABLE>", pos) + 8])
            if len(cand) >= 3 and any(c and label(c[0]) in ("매출액", "수익(매출액)") for c in cand):
                rows = cand
                break
        if not rows:
            continue
        periods = re.findall(r"제\s*\d+\s*기", " ".join(rows[0]))[:3]
        out = {"periods": periods}
        for r in rows:
            key = {"매출액": "revenue", "수익(매출액)": "revenue", "영업이익": "operating_profit", "영업이익(손실)": "operating_profit",
                   "당기순이익": "net_income", "당기순이익(손실)": "net_income"}.get(label(r[0]) if r else "")
            if key and key not in out:
                nums = amounts(r[1:4])
                if len(nums) >= 1:
                    out[key] = [v * MILLION for v in nums]
        if periods and out.get("revenue"):
            best = out          # 정정 보고서는 앞쪽에 정정 전 표가 있어, 마지막 표를 씁니다
    return best


# ---------------------------------------------------------------------------
# 9. 주요 공사 (수주상황 표의 공사별 줄)
# ---------------------------------------------------------------------------
DATE_RE = re.compile(r"^\d{4}\s*[-.]\s*\d{1,2}(\s*[-.]\s*\d{1,2})?\.?$")


def parse_projects(xml):
    """[{'company', 'region', 'name', 'client', 'start', 'end', 'contract', 'done', 'remain'}] (원). 없으면 []."""
    if not xml:
        return []
    start = _order_start(xml)
    if start is None:
        return []
    stop = STOP_RE.search(xml, start + 200)
    end = stop.start() if stop else min(len(xml), start + 600000)
    out = []
    for pos, rows in tables_between(xml, start, end):
        head_rows = rows[:2]
        head = " ".join(" ".join(r) for r in head_rows)
        if not (BACKLOG_HEAD.search(head) and CONTRACT_HEAD.search(head)):
            continue
        h0 = [label(c) for c in rows[0]]
        name_first = True
        if "공사명" in h0 and "발주처" in h0:
            name_first = h0.index("공사명") < h0.index("발주처")
        company = _company_before(xml, pos)
        region = ""
        for r in rows[1:]:
            if not r:
                continue
            first = label(r[0])
            if first in ("국내", "해외"):
                region, r = first, r[1:]
            if not r or TOTAL_KIND.get(label(r[0])) or label(r[0]) in ("기타", "구분"):
                continue
            dates = [i for i, c in enumerate(r) if DATE_RE.match(c.strip())]
            nums = amounts([c for i, c in enumerate(r) if i not in dates])
            if len(dates) < 1 or len(nums) < 3:
                continue
            texts = [c.strip() for c in r[:dates[0]] if c.strip()]
            if len(texts) < 2:
                continue
            name, client = (texts[0], texts[1]) if name_first else (texts[1], texts[0])
            contract, done, remain = nums[-3] * MILLION, nums[-2] * MILLION, nums[-1] * MILLION
            if contract <= 0:
                continue
            out.append({"company": company, "region": region, "name": name, "client": client,
                        "start": r[dates[0]].strip(), "end": r[dates[1]].strip() if len(dates) > 1 else "",
                        "contract": contract, "done": done, "remain": remain})
    return out


# ---------------------------------------------------------------------------
# 10. 모으기
# ---------------------------------------------------------------------------
BACKLOG_FIRST_YEAR = 2014     # 2013년 이전 수주 표는 일부 공사만 적혀 있어(보고서의 수주잔고 문장과 크게 다름) 쓰지 않습니다
JUMP = 0.15                   # 앞뒤 분기와 15% 넘게 어긋나면 표기 기준이 바뀐 값으로 보고 그래프에서 뺍니다
PROJECT_TOP = 12


def _period(y, m):
    return f"{y}.{m:02d}"


def _flag_jumps(rows):
    """앞뒤 보고서 값과 모두 크게 다른 값(그 보고서만 표 범위가 다른 경우)에 표시를 붙입니다."""
    for i, r in enumerate(rows):
        if 0 < i < len(rows) - 1:
            prev, nxt = rows[i - 1]["total"], rows[i + 1]["total"]
            lo, hi = min(prev, nxt), max(prev, nxt)
            if r["total"] < lo * (1 - JUMP) or r["total"] > hi * (1 + JUMP):
                r["flag"] = (f"앞뒤 보고서({rows[i - 1]['period']} {prev / 1e12:.1f}조 원, {rows[i + 1]['period']} {nxt / 1e12:.1f}조 원)와 "
                             "크게 달라 이 보고서만 표에 넣은 공사 범위가 다른 것으로 보입니다. 그래프에서는 뺐습니다.")


def collect(latest, raw_dir):
    """보고서별 원문에서 숫자를 모읍니다. latest: {(연, 월): 공시 목록 한 줄}. 반환은 JSON으로 저장할 수 있는 dict."""
    out = {"backlog": [], "pf": {}, "orders": {}, "employees": {}, "separate": {}, "segments": None, "market": None,
           "materials": None, "projects": None, "errors": []}
    docs = {}
    for (y, m), f in sorted(latest.items()):
        x = main_document(raw_dir / f"{f['rcept_no']}.zip", f["rcept_no"])
        if x is None:
            continue
        docs[(y, m)] = (f, x)
        try:
            b = parse_backlog(x)
            if b and b["total"] and y >= BACKLOG_FIRST_YEAR:
                out["backlog"].append({"period": _period(y, m), "year": y, "month": m, "total": b["total"],
                                       "domestic": b["domestic"], "overseas": b["overseas"], "consolidated": b["consolidated"],
                                       "companies": [{"name": c["name"], "total": c["total"]} for c in b["companies"]],
                                       "receipt": f["rcept_no"], "report": f["report_nm"].strip()})
            pf = parse_pf(x)
            if pf:
                out["pf"][_period(y, m)] = {"amount": pf["current"], "receipt": f["rcept_no"], "basis": "own"}
                prior = _period(y - 1, 12)
                if out["pf"].get(prior, {}).get("basis") != "own":
                    out["pf"][prior] = {"amount": pf["prior"], "receipt": f["rcept_no"], "basis": "next"}
            if m != 12:
                continue
            o = parse_new_orders(x)
            if o:
                out["orders"][str(y)] = {**o, "receipt": f["rcept_no"]}
            e = parse_employees(x)
            if e:
                out["employees"][str(y)] = {**e, "receipt": f["rcept_no"]}
            sp = parse_separate_summary(x)
            if sp:
                nums = [int(re.sub(r"\D", "", p)) for p in sp["periods"]]
                ok = all(a - b == 1 for a, b in zip(nums, nums[1:]))
                for i in range(min(3, len(sp["revenue"]))):
                    year = str(y - i)
                    if not ok or (out["separate"].get(year, {}).get("basis") == "own"):
                        continue
                    out["separate"][year] = {"revenue": sp["revenue"][i],
                                             "operating_profit": (sp.get("operating_profit") or [None] * 3)[i],
                                             "net_income": (sp.get("net_income") or [None] * 3)[i],
                                             "basis": "own" if i == 0 else "next", "receipt": f["rcept_no"]}
        except Exception as exc:     # 원문 형식이 낯설어도 나머지는 계속 읽습니다
            out["errors"].append(f"{_period(y, m)} 사업보고서 본문 읽기: {type(exc).__name__}")
    _flag_jumps(out["backlog"])
    annual = [k for k in docs if k[1] == 12]
    if annual:
        ya = max(annual)
        f, x = docs[ya]
        src = {"receipt": f["rcept_no"], "report": f["report_nm"].strip(), "year": ya[0]}
        seg = parse_segments(x)
        if seg:
            out["segments"] = {**seg, **src}
        mk = parse_market(x)
        if mk:
            out["market"] = {**mk, **src}
        mat = parse_materials(x)
        if mat:
            out["materials"] = {**mat, **src}
    if docs:
        yl = max(docs)
        f, x = docs[yl]
        rows = parse_projects(x)
        if rows:
            rows.sort(key=lambda r: -r["remain"])
            out["projects"] = {"period": _period(*yl), "receipt": f["rcept_no"], "report": f["report_nm"].strip(),
                               "count": len(rows), "rows": rows[:PROJECT_TOP]}
    return out
