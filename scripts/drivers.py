"""실적을 움직인 요인을 재기 위한 숫자를 사업보고서 원문(주석·본문)과 현금흐름표 세부 항목에서 읽습니다.

기업분석 보고서 6~9장(무엇이 실적을 움직였나 · 번 돈을 어디에 썼나 · 미래)의 근거입니다.
재무제표 본문 숫자(매출·영업이익 등)는 financials.py가 OpenDART API로 받고, 여기서는 그 숫자를 '나누어 보는' 데 필요한
공시 주석을 읽습니다. 네트워크는 쓰지 않고, 저장된 원문 ZIP(data/financials/raw)과 API 응답(JSON)만 읽습니다.

연간 사업보고서마다 읽는 것 (연결 = 현대건설과 종속회사 전체, 별도 = 현대건설 본사 단독)
1. 영업부문 주석: 부문별 매출액·매출총이익 (건축/주택 · 토목 · 플랜트/전력 · 기타 · 연결조정)
2. 건설계약 주석: 진행 중인 공사의 총계약수익·총계약원가 추정이 바뀌어 그해와 미래의 손익(세전)에 생긴 영향, 공사손실충당부채
3. 종속기업 주석: 비지배지분이 중요한 종속기업(현대엔지니어링)의 매출·영업손익·순손익·영업활동현금흐름 (내부거래 제거 전)
4. Ⅱ장 연구개발활동: 현대건설 연구개발비용 합계와 매출 대비 비율
5. 배당에 관한 사항: 보통주 주당 현금배당금, 현금배당금 총액, 연결 배당성향
6. 시장위험 민감도(회사가 직접 계산해 공시한 숫자): 변동이자율 차입금 이자율 1% 변동 → 법인세비용차감전순이익,
   환율 10% 변동 → 결제되지 않은 외화 화폐성 항목 환산이 순자산(법인세효과 차감전)에 주는 영향
7. 국내 건설수주·해외건설 수주 통계, 주요 원자재 가격 (business.py의 읽기 함수를 해마다 적용)
8. 현금흐름표 세부(재무제표 API): 설비투자 · 지분투자 · 자산 처분 · 예금 운용 · 대여금 · 차입과 상환 · 배당 · 리스
9. 영업으로부터 창출된 현금(현금흐름표 주석): 당기순이익 + 비현금 조정 + 운전자본 변동 — 영업활동현금흐름을 나누어 보는 근거
10. 매출채권 연령분석(연체 기간별 잔액)과 매출채권 구성(공사미수금 · 분양미수금) — 돈이 어디에 묶였는지 보는 근거
11. 수익의 구분(도급공사 · 분양공사 · 자산관리 등, 2024년 보고서부터) — 도급 사업과 자체(분양) 사업의 비중

안전장치
- 연결/별도는 표 바로 앞의 장 제목(TITLE: '3. 연결재무제표 주석', '5. 재무제표 주석')으로 가립니다. 정정신고서 맨 앞의
  '정정 전/정정 후' 비교표처럼 장 제목 밖에 있는 표는 쓰지 않습니다(시장위험처럼 Ⅱ장에 연결 기준으로 실린 표는 예외).
- 부문 표는 '부문 합 + 연결조정 = 합계'가, 추정 변경 표는 '부문 합 = 합계'가 맞을 때만 씁니다.
- 연결 부문 매출 합계가 재무제표 API의 연결 매출과 0.5% 넘게 다르면 그 해 값을 버립니다(이 검사는 collect에서).
- 그 해 보고서에서 못 읽으면 다음 해 보고서의 전기(비교) 숫자로 채우고 basis='next'로 적습니다.
- 모든 금액은 원 단위 정수입니다.
"""
import re

import business as bz
import financials as fin
import legacy

TITLE_RE = re.compile(r"<TITLE[^>]*>(.*?)</TITLE>", re.S)
TABLE_RE = re.compile(r"<TABLE\b.*?</TABLE>", re.S)
UNIT_RE = re.compile(r"단위\s*[:：]?\s*(백만\s*원|천\s*원|억\s*원|원)")
UNITS = {"백만원": 1_000_000, "천원": 1_000, "억원": 100_000_000, "원": 1}
SEGMENTS = ("building", "civil", "plant", "other")
SEG_KO = {"building": "건축/주택", "civil": "토목", "plant": "플랜트/전력", "other": "기타", "adjust": "연결조정", "total": "합계"}
FIRST_YEAR = 2015          # 주석 공시 형식이 같은 2015년 사업보고서부터 읽습니다 (추정 변경 공시는 2016년부터 의무)


# ---------------------------------------------------------------------------
# 원문 한 권: 장 제목 위치와 표 목록
# ---------------------------------------------------------------------------
class Doc:
    def __init__(self, xml):
        self.xml = xml or ""
        self.titles = [(m.start(), legacy._text(m.group(1)).strip()) for m in TITLE_RE.finditer(self.xml)]
        self.tables = [(m.start(), m.group(0)) for m in TABLE_RE.finditer(self.xml)]

    def scope(self, pos):
        """'consolidated' | 'separate' | None — pos 앞의 제목들로 판단합니다.
        '2. 연결재무제표'·'3. 연결재무제표 주석'·'40. 영업부문 (연결)' → 연결, '4. 재무제표'·'5. 재무제표 주석'·'40. 영업부문 - 별도' → 별도.
        큰 장(Ⅰ~ⅩⅡ)이 바뀌거나 '6. 배당에 관한 사항'처럼 재무제표 밖의 절이 시작되면 None으로 돌아갑니다."""
        state = None
        for p, t in self.titles:
            if p > pos:
                break
            if re.match(r"^[IVX]+\.\s", t):
                state = None
            elif "연결재무제표" in t.replace(" ", "") or t.rstrip().endswith("(연결)"):
                state = "consolidated"
            elif re.match(r"^\d+\.\s*재무제표", t) or re.search(r"-\s*별도$|\(별도\)$", t.strip()):
                state = "separate"
            elif re.match(r"^\d+\.\s*(배당|증권의\s*발행|기타\s*재무|요약\s*재무)", t):
                state = None
        return state

    def chapter(self, pos):
        """pos가 들어 있는 큰 장(Ⅰ~ⅩⅡ) 제목. 정정신고서 앞부분이면 None."""
        last = None
        for p, t in self.titles:
            if p > pos:
                break
            if re.match(r"^[IVX]+\.\s", t):
                last = t
        return last

    def before(self, pos, chars=600):
        """표 바로 앞의 글자(태그 뺀 것) 마지막 chars자."""
        return legacy._text(self.xml[max(0, pos - chars * 8):pos])[-chars:]


def num(cell):
    s = (cell or "").strip().replace("△", "-").replace("▲", "-").replace("−", "-").replace("–", "-")
    if s in ("-", ""):
        return 0 if s == "-" else None
    if "%" in s:
        return None
    return fin.amount(s)


def numbers(cells):
    """셀 목록에서 숫자 칸만 (빈칸·글자 칸 제외, '-'는 0)."""
    out = []
    for c in cells:
        s = (c or "").strip()
        if not s:
            continue
        v = num(s)
        if v is not None and re.fullmatch(r"[\s\d,().\-△▲−–]+", s):
            out.append(v)
    return out


def unit_of(text):
    m = UNIT_RE.findall(text or "")
    return UNITS.get(re.sub(r"\s+", "", m[-1])) if m else None


def period_of(text):
    """표 앞 글자에서 마지막으로 나온 '당기'/'전기' → 'current'/'prior'."""
    found = re.findall(r"(당기|전기|당분기|전분기)", text or "")
    if not found:
        return None
    return "prior" if found[-1].startswith("전") else "current"


def seg_key(name):
    n = bz.label(name).replace("(", "").replace(")", "")
    if not n:
        return None
    if "부문합계" in n or n in ("부문계", "소계"):
        return "subtotal"
    if "연결조정" in n or "조정사항" in n or "제거" in n or n in ("조정", "내부거래"):
        return "adjust"
    if n in ("합계", "총계", "합", "계") or "전체총계합계" in n or n.endswith("합계") and "제품과용역" in n:
        return "total"
    if "토목" in n or "인프라" in n:
        return "civil"
    if "건축" in n or "주택" in n:
        return "building"
    if "플랜트" in n or "전력" in n or "뉴에너지" in n:
        return "plant"
    if n.startswith("기타"):
        return "other"
    return None


def _segment_names(rows, upto):
    """표 머리글 줄에서 부문 이름의 열 순서. 가장 아래 머리글 줄(부문 이름 2개 이상)을 기준으로,
    위 줄에만 있는 부문(예: XBRL 표의 '기타부문')은 뒤에 붙입니다."""
    found = []
    for r in rows[:upto]:
        keys = [seg_key(c) for c in r]
        segs = [k for k in keys if k in SEGMENTS]
        if len(segs) >= 1:
            found.append(segs)
    if not found:
        return []
    base = max((f for f in found if len(set(f)) >= 2), key=lambda f: found.index(f), default=found[-1])
    order = []
    for k in base:
        if k not in order:
            order.append(k)
    for f in found:
        for k in f:
            if k not in order:
                order.append(k)
    return order


def _split(nums, names):
    """[부문값들…, (부문합계), (연결조정), 합계] → {부문: 값, 'adjust', 'total'} (합이 맞을 때만)."""
    k = len(names)
    if len(nums) < k + 1:
        return None
    segs = dict(zip(names, nums[:k]))
    total = nums[-1]
    middle = nums[k:-1]
    s = sum(segs.values())
    tol = max(3, abs(total) * 0.001)
    if not middle:
        adjust = total - s
        if abs(adjust) > tol:
            return None
    elif len(middle) == 1:
        adjust = middle[0]
        if abs(s + adjust - total) > tol:
            if abs(middle[0] - s) <= tol:       # 가운데 값이 부문 합계였던 경우
                adjust = total - s
            else:
                return None
    else:
        sub, adjust = middle[0], middle[-1]
        if abs(sub - s) > tol or abs(sub + adjust - total) > tol:
            return None
    return {**segs, "adjust": total - s, "total": total}


# ---------------------------------------------------------------------------
# 1. 영업부문: 부문별 매출액 · 매출총이익
# ---------------------------------------------------------------------------
REV_LABELS = ("매출액", "수익(매출액)", "영업수익", "매출")
GP_PREFIX = ("매출총이익", "매출총손익", "매출총손실")


def parse_segment_tables(doc):
    """{(scope, period): {'revenue': {...}, 'gross_profit': {...}}}"""
    out = {}
    for pos, table in doc.tables:
        head = doc.before(pos, 700)
        flat = legacy._text(table[:60000])
        if "매출총" not in flat or not any(w in flat for w in ("플랜트", "토목", "인프라")):
            continue
        scope = doc.scope(pos)
        if scope is None:
            continue
        rows = bz.table_rows(table)
        rev_i = next((i for i, r in enumerate(rows) if r and bz.label(r[0]) in REV_LABELS), None)
        gp_i = next((i for i, r in enumerate(rows) if r and bz.label(r[0]).startswith(GP_PREFIX)), None)
        if rev_i is None or gp_i is None:
            continue
        names = _segment_names(rows, rev_i)
        if len(names) < 3:
            continue
        unit = unit_of(head) or unit_of(legacy._text(table[:1500]))
        period = period_of(head[-250:])
        if not unit or not period:
            continue
        rev = _split(numbers(rows[rev_i][1:]), names)
        gp = _split(numbers(rows[gp_i][1:]), names)
        if not rev or not gp:
            continue
        key = (scope, period)
        if key in out:            # 같은 표가 두 번(본문·감사보고서) 나오면 첫 번째를 씁니다
            continue
        out[key] = {"revenue": {k: v * unit for k, v in rev.items()}, "gross_profit": {k: v * unit for k, v in gp.items()}}
    return out


REGIONS = ("domestic", "asia", "mideast", "other")


def region_key(name):
    n = bz.label(name)
    if n in ("국내",) or "본사소재지" in n:
        return "domestic"
    if n.startswith("아시아"):
        return "asia"
    if "중동" in n:
        return "mideast"
    if n.startswith("기타") or n in ("미주", "유럽"):
        return "other"
    return None


def parse_region_tables(doc):
    """{(scope, period): {'domestic','asia','mideast','other','adjust','total'}} — 영업부문 주석의 '지역별 분석' 매출."""
    out = {}
    for pos, table in doc.tables:
        flat = legacy._text(table[:60000])
        if "중동" not in flat or "아시아" not in flat:
            continue
        scope = doc.scope(pos)
        if scope is None:
            continue
        rows = bz.table_rows(table)
        rev_i = next((i for i, r in enumerate(rows) if r and bz.label(r[0]) in REV_LABELS), None)
        if rev_i is None:
            continue
        found = []
        for r in rows[:rev_i]:
            for c in r:
                k = region_key(c)
                if k and k not in found:
                    found.append(k)
        if "domestic" in found:              # XBRL 표는 '본사 소재지 국가'가 위 줄에 있어도 맨 앞 열입니다
            found.remove("domestic")
            found.insert(0, "domestic")
        if len(found) < 3:
            continue
        head = doc.before(pos, 700)
        unit = unit_of(head) or unit_of(flat[:600])
        period = period_of(head[-250:])
        got = _split(numbers(rows[rev_i][1:]), found)
        if not unit or not period or not got:
            continue
        key = (scope, period)
        if key not in out:
            out[key] = {k: v * unit for k, v in got.items()}
    return out


def parse_mdna(doc):
    """Ⅳ(또는 Ⅴ)장 '이사의 경영진단 및 분석의견'에서 회사가 밝힌 매출·영업이익 증감 이유 문장(자동 추출).
    영업이익 문장 최대 2개 + 매출 문장 1개, 보고서에 나온 순서대로. 재무상태(자산·부채) 설명 문장은 뺍니다."""
    start = next((p for p, t in doc.titles if "경영진단" in t), None)
    if start is None:
        return None
    end = next((p for p, t in doc.titles if p > start and re.match(r"^[IVX]+\.\s", t)), len(doc.xml))
    text = legacy._text(doc.xml[start:end])
    i = text.find("영업실적")
    body = text[i:] if i >= 0 else text
    why = r"(기인|영향|따라|반영|힘입어|때문)"
    bs = r"(자산|부채|유동|현금성|매출채권|미청구|재고|선수금|차입금|부채비율)"
    picks, op_n, rev_n = [], 0, 0
    for sent in re.split(r"(?<=다)\.\s*", body):
        sent = re.sub(r"\s+", " ", sent).strip(" -·")
        sent = re.sub(r"^\(\d\)\s*연결\s*영업실적\s*분석\s*", "", sent)
        if len(sent) < 20 or len(sent) > 400 or "(단위" in sent or re.search(r"(산업특성|경기변동의|예측정보|주의사항)", sent):
            continue
        if op_n < 2 and re.search(r"(영업이익|영업손실|흑자\s*전환|적자)", sent) and re.search(why + r"|전환", sent) and not re.search(bs, sent):
            picks.append(sent + ".")
            op_n += 1
        elif rev_n < 1 and re.search(r"매출", sent) and re.search(why, sent) and not re.search(bs, sent) and not re.search(r"영업이익", sent):
            picks.append(sent + ".")
            rev_n += 1
        if op_n >= 2 and rev_n >= 1:
            break
    return picks or None


# ---------------------------------------------------------------------------
# 2. 건설계약: 총계약수익·총계약원가 추정 변경의 손익 영향
# ---------------------------------------------------------------------------
EST_MEASURES = (("pl_future", r"미래\s*(기간의\s*)?손익"), ("pl_current", r"당기\s*손익"), ("loss_prov", r"공사손실충당"),
                ("ca_change", r"미청구공사|계약자산"), ("cl_change", r"초과청구공사|계약부채"),
                ("cost_change", r"계약원가"), ("rev_change", r"계약(수익|금액)"))


def measure_key(text):
    t = re.sub(r"\s+", " ", text or "")
    for key, pat in EST_MEASURES:
        if re.search(pat, t):
            return key
    return None


def _est_from_rows(rows):
    """두 가지 서식을 모두 읽습니다.
    A) 줄=부문, 칸=항목 (2016~2022, 2025년 보고서)  B) 줄=항목, 칸=부문 (2023·2024년 XBRL 서식)"""
    # A: 머리글 줄에 항목 이름이 4개 이상
    for hi, r in enumerate(rows[:4]):
        keys = [measure_key(c) for c in r[1:]]
        if sum(1 for k in keys if k) >= 4:
            cols = [k for k in keys]
            out = {}
            for row in rows[hi + 1:]:
                if not row:
                    continue
                seg = seg_key(row[0])
                if seg is None or seg in ("subtotal",):
                    continue
                vals = numbers(row[1:])
                if len(vals) < sum(1 for k in cols if k):
                    continue
                measures = {}
                vi = 0
                for k in cols:
                    if vi >= len(vals):
                        break
                    if k:
                        measures[k] = vals[vi]
                    vi += 1
                key = "total" if seg in ("total",) else seg
                if key in out and key != "total":
                    continue
                out[key] = measures
            return out
    # B: 첫 칸에 항목 이름이 4개 이상
    labels = [(i, measure_key(r[0])) for i, r in enumerate(rows) if r]
    if sum(1 for _, k in labels if k) >= 4:
        first = min(i for i, k in labels if k)
        names = _segment_names(rows, first)
        if len(names) < 2:
            return None
        out = {k: {} for k in names + ["total"]}
        for i, k in labels:
            if not k:
                continue
            vals = numbers(rows[i][1:])
            if len(vals) < len(names) + 1:
                continue
            for seg, v in zip(names, vals[:len(names)]):
                out[seg][k] = v
            out["total"][k] = vals[len(names)] if len(vals) == len(names) + 1 else vals[-1]
        return out
    return None


def parse_estimate_tables(doc):
    """{(scope, period): {부문|'total': {'rev_change','cost_change','pl_current','pl_future','ca_change','cl_change','loss_prov'}}}"""
    out = {}
    for pos, table in doc.tables:
        flat = legacy._text(table[:60000])
        if not re.search(r"손익", flat) or not re.search(r"계약원가", flat):
            continue
        scope = doc.scope(pos)
        if scope is None:
            continue
        head = doc.before(pos, 900)
        if not re.search(r"추정의?\s*변경|추정치\s*변경|추정\s*변동", head + flat[:400]):
            continue
        rows = bz.table_rows(table)
        got = _est_from_rows(rows)
        if not got or "total" not in got or "pl_current" not in got["total"]:
            continue
        unit = unit_of(head) or unit_of(flat[:400])
        period = period_of(head[-260:])
        if not unit or not period:
            continue
        segs = [k for k in got if k in SEGMENTS]
        tot = got["total"]["pl_current"]
        s = sum(got[k].get("pl_current", 0) for k in segs)
        if segs and abs(s - tot) > max(3, abs(tot) * 0.002) and "other" not in segs:
            continue
        key = (scope, period)
        if key in out:
            continue
        out[key] = {seg: {m: v * unit for m, v in vals.items()} for seg, vals in got.items()}
    return out


# ---------------------------------------------------------------------------
# 3. 종속기업(현대엔지니어링) 요약 경영성과·현금흐름
# ---------------------------------------------------------------------------
SUB_NAME = "현대엔지니어링"
SUB_ROWS = (("revenue", r"^(매출액|수익\(매출액\)|영업수익)"), ("operating_profit", r"^영업(이익|손익|손실)"),
            ("net_income", r"^(당기|전기)순(이익|손익|손실)"), ("cfo", r"영업활동"), ("cfi", r"투자활동"), ("cff", r"재무활동"))


def parse_subsidiary_tables(doc):
    """{period: {'revenue','operating_profit','net_income','cfo','cfi','cff'}} — 연결 주석의 비지배지분 정보 표."""
    out = {}
    for pos, table in doc.tables:
        flat = legacy._text(table[:3000])
        if SUB_NAME not in flat or len(flat) > 2500:
            continue
        if doc.scope(pos) != "consolidated":
            continue
        head = doc.before(pos, 1200)
        if "비지배" not in head and "비지배" not in flat:
            continue
        rows = bz.table_rows(table)
        header = next((r for r in rows if any(SUB_NAME in c for c in r)), None)
        if not header:
            continue
        companies = [c for c in header if re.search(r"현대|HYUNDAI|Hyundai", c)]
        col = next(i for i, c in enumerate(companies) if SUB_NAME in c)
        period = period_of(head[-200:])
        unit = unit_of(head) or unit_of(flat[:300])
        if not period or not unit:
            continue
        got = {}
        for r in rows:
            if not r:
                continue
            lab = bz.label(r[0])
            vals = numbers(r[1:])
            if len(vals) <= col:
                continue
            for key, pat in SUB_ROWS:
                if key not in got and re.search(pat, lab):
                    if key in ("cfo", "cfi", "cff") and "현금흐름" not in lab:
                        continue
                    got[key] = vals[col] * unit
        if got:
            out.setdefault(period, {}).update({k: v for k, v in got.items() if k not in out.get(period, {})})
    return out


# ---------------------------------------------------------------------------
# 4. 연구개발비 (현대건설 본사)  5. 배당  6. 시장위험 민감도
# ---------------------------------------------------------------------------
def parse_rnd(doc, report_year):
    """{연도: {'total', 'ratio_pct'}} — 현대건설(제N기 = 연도 − 1949) 표만."""
    want = report_year - 1949
    for pos, table in doc.tables:
        flat = legacy._text(table[:4000])
        if "연구개발비" not in flat or not re.search(r"제\s*\d+\s*기", flat):
            continue
        rows = bz.table_rows(table)
        periods = [int(x) for x in re.findall(r"제\s*(\d+)\s*기", " ".join(rows[0]))][:3] if rows else []
        if not periods or periods[0] != want:
            continue
        unit = unit_of(doc.before(pos, 300)) or unit_of(flat[:300]) or 1_000_000
        out = {}
        for r in rows:
            lab = bz.label(" ".join(r[:1]))
            if lab.startswith("연구개발비용계") or lab in ("연구개발비용합계", "연구개발비계"):
                vals = numbers(r[1:])[:len(periods)]
                for p, v in zip(periods, vals):
                    out.setdefault(p + 1949, {})["total"] = v * unit
            elif "매출액비율" in lab or "매출액대비" in lab:
                pcts = [float(x) for x in re.findall(r"(-?\d+(?:\.\d+)?)\s*%", " ".join(r[1:]))][:len(periods)]
                for p, v in zip(periods, pcts):
                    out.setdefault(p + 1949, {})["ratio_pct"] = v
        if out:
            return out
    return {}


def parse_dividends(doc, report_year):
    """{연도: {'dps', 'total', 'payout_pct'}} — '주요배당지표' 표(당기·전기·전전기)."""
    for pos, table in doc.tables:
        if not doc.chapter(pos):
            continue                       # 정정신고서 앞부분의 '정정 전/후' 표는 건너뜁니다
        flat = legacy._text(table[:5000])
        if "현금배당금" not in flat or "주당" not in flat or "전전기" not in flat:
            continue
        rows = bz.table_rows(table)
        out = {report_year - i: {} for i in range(3)}
        for r in rows:
            lab = bz.label(r[0]) if r else ""
            if lab.startswith("주당현금배당금") and len(r) >= 2 and "보통" in r[1]:
                for i, v in enumerate(numbers(r[2:])[:3]):
                    out[report_year - i]["dps"] = v
            elif lab.startswith("현금배당금총액"):
                for i, v in enumerate(numbers(r[1:])[:3]):
                    out[report_year - i]["total"] = v * 1_000_000
            elif "현금배당성향" in lab:
                cells = r[1:]
                for i, c in enumerate(cells[:3]):
                    try:
                        out[report_year - i]["payout_pct"] = float(c.replace(",", "").strip())
                    except ValueError:
                        out[report_year - i]["payout_pct"] = None
        if any(v.get("dps") is not None for v in out.values()):
            return out
    return {}


def parse_sensitivity(doc):
    """{'fx': {'pct': 10, 'impact': 원, 'measure', 'scope'}, 'rate': {...}} — 원화 환율 10% 상승(원화 약세)·이자율 1% 상승 시 영향.
    이자율은 '법인세비용차감전순이익', 환율은 '순자산(법인세효과 차감전)'에 대한 영향입니다(measure에 원문 문구)."""
    out = {}
    for pos, table in doc.tables:
        if doc.scope(pos) == "separate":
            continue
        head = doc.before(pos, 900)
        rows = bz.table_rows(table)
        if not rows or not rows[0]:
            continue
        top = " ".join(rows[0])
        m = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:p\s*)?상승", top)
        if not m or "하락" not in top:
            continue
        pct = float(m.group(1))
        tail = head[-500:]
        fx_at = max((x.end() for x in re.finditer(r"환\s*위험|환율", tail)), default=-1)
        rate_at = max((x.end() for x in re.finditer(r"이자율", tail)), default=-1)
        kind = "fx" if fx_at > rate_at else ("rate" if rate_at >= 0 else None)
        if not kind or kind in out:
            continue
        if not re.search(r"연결", head) and doc.scope(pos) != "consolidated":
            continue
        unit = unit_of(tail) or unit_of(legacy._text(table[:300])) or 1_000_000
        total_row = next((r for r in rows[1:] if bz.label(r[0]) in ("합계", "합 계", "계", "총계")), None)
        if total_row:
            vals = numbers(total_row[1:])
            impact = vals[0] if vals else None
        else:
            firsts = [numbers(r[1:]) for r in rows[1:]]
            impact = sum(v[0] for v in firsts if v) if any(firsts) else None
        if impact is None:
            continue
        # 회사가 무엇에 대한 영향으로 계산했는지 원문 문구 그대로: 이자율 → '법인세비용차감전순이익', 환율 → '순자산(법인세효과 차감전)'
        measure = re.findall(r"변동이\s*([^.]{2,30}?)에\s*미치는\s*영향", tail)
        scope = None
        if kind == "rate" and re.search(r"변동이자율\s*차입금", tail):
            scope = "변동이자율 차입금"
        elif kind == "fx" and re.search(r"외화표시\s*화폐성\s*항목", head):
            scope = "결제되지 않은 외화표시 화폐성 항목"
        out[kind] = {"pct": pct, "impact": impact * unit, "measure": re.sub(r"\s+", " ", measure[-1]).strip() if measure else None,
                     "scope": scope}
        if len(out) == 2:
            break
    return out


# ---------------------------------------------------------------------------
# 7. 국내 건설수주 · 해외건설 수주 (Ⅱ장 '지배회사 현황' 문단, 대한건설협회·해외건설협회 인용)
# ---------------------------------------------------------------------------
def _amounts_jo(sentence):
    return [bz.korean_amount(m.group(1)) for m in re.finditer(bz.KAMT, sentence)]


def parse_market_any(xml, year):
    """{'domestic_total', 'domestic_growth_pct', 'domestic_months', 'overseas_usd_100m', 'overseas_growth_pct', 'overseas_months'}
    — 그 해 숫자를 적은 문장에서 읽습니다. 문장 형식이 해마다 달라서(총 OO조 / 공공·민간을 나눠 적음) 합계는 문장 안에서
    가장 큰 금액으로 고릅니다. 보고서가 1~11월 누계를 적은 해가 많아 금액보다 '전년 같은 기간 대비 증감률'이 비교에 알맞습니다."""
    text = legacy._text(xml or "")
    start = text.find("지배회사 현황")
    part = text[start:start + 12000] if start >= 0 else text[:60000]
    out = {}

    def months(sent):
        m = re.search(str(year) + r"\s*년\s*(?:1\s*~\s*(\d{1,2})\s*월|상반기|하반기)?", sent)
        return int(m.group(1)) if m and m.group(1) else 12

    def growth(sent):
        g = re.search(r"(\d+(?:\.\d+)?)\s*%\s*(증가|감소|상승|하락)", sent)
        if not g:
            return None
        v = float(g.group(1))
        return -v if g.group(2) in ("감소", "하락") else v

    for sent in re.split(r"(?<=[다요])\.\s*|\n", part):
        if str(year) not in sent:
            continue
        if "domestic_total" not in out and re.search(r"국내\s*(건설)?\s*(공사)?\s*(건설)?\s*수주", sent) and "당사" not in sent[:40]:
            vals = [v for v in _amounts_jo(sent) if v]
            if vals and 80 * 10**12 <= max(vals) <= 500 * 10**12:
                out.update(domestic_total=max(vals), domestic_months=months(sent), domestic_growth_pct=growth(sent),
                           provisional="잠정" in sent)
        if "overseas_usd_100m" not in out and re.search(r"해외\s*건설\s*(시장)?\s*수주", sent):
            usd = [fin.amount(x) for x in re.findall(r"(\d[\d,]*)\s*억\s*(?:달러|불|\$|US)", sent)]
            usd = [u for u in usd if u and 100 <= u <= 1500]
            if usd:
                out.update(overseas_usd_100m=max(usd), overseas_months=months(sent), overseas_growth_pct=growth(sent))
    return out or None


# ---------------------------------------------------------------------------
# 8. 현금흐름표 세부 (OpenDART 재무제표 API, 연결)
# ---------------------------------------------------------------------------
CF_RULES = (  # (분류, 이름 패턴, 방향: +1 유입 / -1 유출) — 위에서부터 먼저 맞는 규칙
    ("skip", r"현금유입액|현금유출액|현금흐름$|현금흐름\)|기초|기말|환율변동|현금및현금성자산의", 0),
    ("capex", r"(유형자산|무형자산|투자부동산|사용권자산|건설중인자산)의?\s*(취득|증가)", -1),
    ("asset_sale", r"(유형자산|무형자산|투자부동산|사용권자산)의?\s*처분", +1),
    ("equity_invest", r"(관계기업|공동기업|종속기업|사업결합).*(취득|유출|증가)", -1),
    ("equity_sale", r"(관계기업|공동기업|종속기업|매각예정).*(처분|유입|감소)", +1),
    ("fin_invest", r"(공정가치측정금융자산|매도가능금융자산|당기손익|기타포괄).*(취득|증가)", -1),
    ("fin_sale", r"(공정가치측정금융자산|매도가능금융자산|당기손익|기타포괄).*(처분|감소)", +1),
    ("deposits", r"(단기금융상품|장기금융상품|상각후원가측정금융자산|만기보유금융자산).*(증가|취득)", -1),
    ("deposits", r"(단기금융상품|장기금융상품|상각후원가측정금융자산|만기보유금융자산).*(감소|처분)", +1),
    ("loans", r"(기타채권|장기성기타채권|대여금|보증금).*(증가|대여)", -1),
    ("loans", r"(기타채권|장기성기타채권|대여금|보증금).*(감소|회수)", +1),
    ("dividends", r"배당금의?\s*지급", -1),
    ("lease", r"리스부채", -1),
    ("borrow", r"(사채|차입금|유동성장기부채).*(상환)", -1),
    ("borrow", r"발행비|발행비용", -1),
    ("borrow", r"(사채|차입금).*(발행|차입)", +1),
    ("equity_tx", r"유상증자|신주|전환사채|비지배", 0),
)


OP_RULES = (  # 영업활동 구역: 영업에서 창출된 현금(이자·법인세 전)과 이자·법인세·배당 수취
    ("cash_generated", r"영업(에서|으로부터|활동에서)창출된현금", 0),
    ("interest_received", r"이자(의)?수취", +1),
    ("interest_paid", r"이자(의)?지급", -1),
    ("dividends_received", r"배당금(의)?수취", +1),
    ("tax_paid", r"법인세(의)?(납부|환급)|법인세납부", -1),
)


def cf_detail(records):
    """현금흐름표 줄 → 분류별 합계(원, 유입 +, 유출 −). 보고된 투자·재무활동 합계와의 차이는 'other_invest'·'other_fin'."""
    out = {k: 0 for k in ("capex", "asset_sale", "equity_invest", "equity_sale", "fin_invest", "fin_sale", "deposits", "loans",
                          "dividends", "lease", "borrow", "equity_tx")}
    out.update({k: None for k, _, _ in OP_RULES})
    totals = {"cfo": None, "cfi": None, "cff": None}
    seen = set()
    section = None
    # 보고서마다 유출 금액을 음수(−)로 적기도 하고 양수로 적기도 합니다. 대표 유출 항목의 부호로 판단합니다.
    probe = [fin.amount(r.get("thstrm_amount")) for r in records if r.get("sj_div") == "CF"
             and re.search(r"(유형자산의?\s*취득|배당금의?\s*지급|차입금의?\s*상환)", fin.norm(r.get("account_nm")))]
    probe = [x for x in probe if x]
    signed = bool(probe) and sum(1 for x in probe if x < 0) > len(probe) / 2
    for r in records:
        if r.get("sj_div") != "CF":
            continue
        name = fin.norm(r.get("account_nm"))
        aid = r.get("account_id") or ""
        val = fin.amount(r.get("thstrm_amount"))
        if "OperatingActivities" in aid and aid.endswith(("CashFlowsFromUsedInOperatingActivities",)):
            totals["cfo"] = val
            section = "op"
            continue
        if aid.endswith("CashFlowsFromUsedInInvestingActivities"):
            totals["cfi"] = val
            section = "inv"
            continue
        if aid.endswith("CashFlowsFromUsedInFinancingActivities"):
            totals["cff"] = val
            section = "fin"
            continue
        if val is not None and section == "op":
            for key, pat, sign in OP_RULES:
                if re.search(pat, name) and out.get(key) is None:
                    out[key] = sign * abs(val) if sign else val
                    break
            continue
        if val is None or section not in ("inv", "fin"):
            continue
        key = (name, aid, val)
        if key in seen:
            continue
        seen.add(key)
        for cat, pat, sign in CF_RULES:
            if re.search(pat, name):
                if cat == "skip":
                    break
                if signed:
                    out[cat] += val
                elif cat == "equity_tx":
                    s = -1 if ("Payments" in aid or "취득" in name or "감소" in name) else +1
                    out[cat] += s * abs(val)
                elif sign:
                    out[cat] += sign * abs(val)
                break
    inv = sum(out[k] for k in ("capex", "asset_sale", "equity_invest", "equity_sale", "fin_invest", "fin_sale", "deposits", "loans"))
    fin_ = sum(out[k] for k in ("dividends", "lease", "borrow", "equity_tx"))
    out["other_invest"] = (totals["cfi"] - inv) if totals["cfi"] is not None else None
    out["other_fin"] = (totals["cff"] - fin_) if totals["cff"] is not None else None
    out.update(totals)
    return out


# ---------------------------------------------------------------------------
# 9. 영업으로부터 창출된 현금 (현금흐름표 주석): 당기순이익 + 비현금 조정 + 운전자본 변동
# ---------------------------------------------------------------------------
# 조정(현금이 오가지 않은 손익) 분류 — 위에서부터 먼저 맞는 규칙
CG_ADJ = (
    ("provisions", r"충당부채.*(전입|환입)|충당부채의?(전입|환입)"),
    ("fx", r"외환|외화환산|해외사업환산|파생상품"),
    ("impairment", r"대손|손상|재고자산평가"),          # '대손상각비'가 감가상각으로 가지 않게 먼저 봅니다
    ("dep_amort", r"감가상각|상각비"),
    ("interest_tax", r"^이자(비용|수익)|^법인세비용|^배당(금)?수익"),
    ("employee", r"퇴직급여|장기종업원급여"),
)
# 운전자본(영업활동으로 인한 자산·부채의 변동) 분류
CG_WC = (
    ("receivables", r"^매출채권"),
    ("contract_assets", r"미청구공사|계약자산"),
    ("inventories", r"재고자산"),
    ("payables", r"^매입채무"),
    ("contract_liabilities", r"초과청구공사|계약부채"),
    ("advances", r"선수금"),
    ("provisions_used", r"^충당부채|퇴직급여채무|장기종업원급여충당부채|퇴직금"),
    ("other_receivables", r"기타채권|장기성기타채권|장기미수채권"),
    ("other_payables", r"기타채무|장기성기타채무"),
)
CG_ADJ_KEYS = tuple(k for k, _ in CG_ADJ) + ("other_adj",)
CG_WC_KEYS = tuple(k for k, _ in CG_WC) + ("other_wc",)


def _cg_key(label, rules, rest):
    for key, pat in rules:
        if re.search(pat, label):
            return key
    return rest


def _cg_rows(rows):
    """표의 줄 → [(라벨, [숫자…], 묶음 머리글)] — XBRL 서식은 첫 칸이 묶음 이름이고 둘째 칸이 항목 이름입니다."""
    out = []
    for r in rows:
        if not r:
            continue
        group = bz.label(r[0])
        if len(r) >= 3 and r[1].strip() and num(r[1]) is None and not re.fullmatch(r"[\s\d,().\-△▲−–]+", r[1]):
            label, vals = bz.label(r[1]), numbers(r[2:])
        else:
            label, vals, group = group, numbers(r[1:]), ""
        out.append((label, vals, group))
    return out


WC_HEAD = r"자산\s*부채의?\s*변동|자산부채의변동"
CG_TOTAL = r"(영업에서|영업으로부터|영업활동에서|영업활동으로부터)창출된현금"


def _cg_classify(items, col):
    """[(라벨, 숫자들, 묶음)] → 영업으로부터 창출된 현금의 구성 (col: 0 = 당기, 1 = 전기 열).
    lines: 원문 줄 그대로 [(라벨, 분류, 금액)] — 분류가 맞는지 사람이 다시 볼 수 있게 남깁니다."""
    got = {"net_income": None, "adj": {k: 0 for k in CG_ADJ_KEYS}, "wc": {k: 0 for k in CG_WC_KEYS},
           "adj_total": None, "wc_total": None, "cash_generated": None, "lines": []}
    section = None
    for label, vals, group in items:
        val = vals[col] if len(vals) > col else None
        if re.search(r"^(이자|배당금|법인세)(의)?(수취|지급|납부|환급|수입)", label):
            break                                   # 현금흐름표 본문이면 여기부터는 영업으로부터 창출된 현금 밖입니다
        if re.search(CG_TOTAL, label):
            got["cash_generated"] = val
            continue
        if label.startswith("당기순이익") and not re.search(r"조정|가감", label):
            got["net_income"] = val
            continue
        for head in (group, label):
            if re.search(WC_HEAD, head):
                section = "wc"
            elif head and section != "wc" and re.search(r"^조정|가감", head):
                section = "adj"
        if val is None:
            continue
        # 묶음 합계 줄: '당기순이익조정을 위한 가감 257,894' · '영업활동으로 인한 자산 부채의 변동 588,…' · '소 계'
        if not group and (re.search(r"가감$|" + WC_HEAD + r"$", label) or re.search(r"소계$|^합계$", label)):
            got["wc_total" if section == "wc" else "adj_total"] = val
            continue
        if re.search(r"소계$", label):
            got["wc_total" if section == "wc" else "adj_total"] = val
            continue
        if section == "wc":
            key = _cg_key(label, CG_WC, "other_wc")
            got["wc"][key] += val
            got["lines"].append((label, "wc." + key, val))
        elif section == "adj":
            key = _cg_key(label, CG_ADJ, "other_adj")
            got["adj"][key] += val
            got["lines"].append((label, "adj." + key, val))
    return got


def _cg_check(got):
    """당기순이익 + 조정 합 + 운전자본 합 − 영업으로부터 창출된 현금 (0이어야 맞게 읽은 것)."""
    parts = [got.get("net_income"), sum(got["adj"].values()), sum(got["wc"].values())]
    if None in parts or got.get("cash_generated") is None:
        return None
    return sum(parts) - got["cash_generated"]


def _label_table(table_xml):
    """'(단위 : 백만원)'·'당기'·'영업활동현금흐름'처럼 숫자 칸이 없는 작은 머리글 표인지."""
    rows = bz.table_rows(table_xml)
    return len(rows) <= 4 and not any(numbers(r) for r in rows)


def _prev_table(doc, idx):
    """표 idx 앞의 '진짜' 표(숫자 칸이 있는 표)의 번호. 없으면 -1."""
    j = idx - 1
    while j >= 0 and _label_table(doc.tables[j][1]):
        j -= 1
    return j


def _lead(doc, idx, chars=500):
    """표 idx 바로 앞의 글자 — 앞의 '진짜' 표가 끝난 곳부터. 단위·당기/전기만 적힌 작은 표는 건너뛰되 그 글자는 포함합니다."""
    j = _prev_table(doc, idx)
    start = doc.tables[j][0] + len(doc.tables[j][1]) if j >= 0 else 0
    pos = doc.tables[idx][0]
    return legacy._text(doc.xml[max(start, pos - chars * 8):pos])[-chars:]


def parse_cash_generated(doc):
    """{period: {...}} — 연결 현금흐름표 주석의 '영업으로부터(영업에서) 창출된 현금' 표.
    당기순이익 + 조정(현금이 오가지 않은 손익) + 영업활동으로 인한 자산·부채의 변동 = 영업으로부터 창출된 현금.
    2017년 사업보고서부터 이 한 표로 공시합니다(2016년 숫자는 2017년 보고서의 전기 열). 그 전 보고서는 조정 내역을
    '가산'·'차감' 두 표로만 공시하고 운전자본 줄은 본문에만 있어 여기서는 읽지 않습니다.
    합계 검사: 구성 합계가 표의 '영업으로부터 창출된 현금'과 다르면 gap에 차이를 남깁니다(쓰는 쪽에서 0이 아니면 버림)."""
    out = {}
    for idx, (pos, table) in enumerate(doc.tables):
        if doc.scope(pos) != "consolidated":
            continue
        flat = legacy._text(table[:80000])
        if not (re.search(r"당기순이익", flat) and re.search(r"창출된\s*현금", flat) and re.search(r"자산\s*[ㆍ·]?\s*부채의?\s*변동", flat)):
            continue
        lead = _lead(doc, idx)
        if re.search(r"제\s*\d+\s*기", lead):          # 재무제표 본문(현금흐름표)은 주석이 아님
            continue
        unit = unit_of(lead[-200:]) or unit_of(flat[:300])
        if not unit:
            continue
        items = _cg_rows(bz.table_rows(table))
        two_cols = sum(1 for _, v, _ in items if len(v) >= 2) >= 3
        periods = [("current", 0), ("prior", 1)] if two_cols else [(period_of(lead[-120:]) or "current", 0)]
        for period, col in periods:
            if period in out:
                continue
            got = _cg_classify(items, col)
            if got["cash_generated"] is None or got["net_income"] is None:
                continue
            scaled = {}
            for k, v in got.items():
                if isinstance(v, dict):
                    scaled[k] = {kk: vv * unit for kk, vv in v.items()}
                elif k == "lines":
                    scaled[k] = [(a, b, c * unit) for a, b, c in v]
                else:
                    scaled[k] = v * unit if v is not None else None
            scaled["gap"] = _cg_check(scaled)
            checks = []
            if scaled["adj_total"] is not None:
                checks.append(("adj", sum(scaled["adj"].values()) - scaled["adj_total"]))
            if scaled["wc_total"] is not None:
                checks.append(("wc", sum(scaled["wc"].values()) - scaled["wc_total"]))
            scaled["subtotal_gaps"] = dict(checks)
            out[period] = scaled
    return out


# ---------------------------------------------------------------------------
# 10. 매출채권 연령분석 · 매출채권 구성(공사미수금 / 분양미수금) — 영업활동현금흐름이 왜 나빠졌는지 보는 근거
# ---------------------------------------------------------------------------
AGING_KEYS = ("b0", "b1", "b2", "b3")      # 표의 구간 순서 그대로: 연체되지 않음(3개월 이내) · 1년 이내 · 1~3년 · 3년 초과


def _aging_from_values(vals):
    """한 줄의 숫자 → 구간 4개 + 손상차손누계액(음수) + 장부금액. '구간 합 + 손상 = 장부금액'이 맞을 때만."""
    neg = [i for i, v in enumerate(vals) if v < 0]
    if len(vals) < 6 or len(neg) != 1:
        return None
    buckets, allowance, net = vals[:4], vals[neg[0]], vals[-1]
    if sum(buckets) + allowance != net:
        return None
    return {"buckets": dict(zip(AGING_KEYS, buckets)), "allowance": allowance, "net": net}


def parse_receivable_aging(doc):
    """{period: {'buckets': {b0..b3}, 'allowance', 'net', 'labels'}} — 연결 매출채권 연령분석(원).
    2022년 보고서까지: '구 분 | 당기말 | 전기말' 표에 '연체되지 않은 채권 · 1년 이하 · 1년 초과 3년 이하 · 3년 초과 · 대손충당금 · 합 계'.
    2023년 보고서부터: 당기·전기 표가 따로 있고 한 줄에 구간 숫자가 이어집니다(구간 이름은 보고서마다 '현재'·'3개월 이내' 등으로 다름)."""
    out = {}
    matched = -2
    for idx, (pos, table) in enumerate(doc.tables):
        if doc.scope(pos) != "consolidated":
            continue
        lead = _lead(doc, idx, 400)
        if not (re.search(r"매출채권의\s*연령분석|연체되거나\s*손상된\s*매출채권", lead)
                or (_prev_table(doc, idx) == matched and re.search(r"전기", lead[-60:]))):
            continue
        matched = idx
        rows = bz.table_rows(table)
        unit = unit_of(lead[-200:]) or unit_of(legacy._text(table[:3000]))
        if not unit or not rows:
            continue
        by_label = {bz.label(r[0]): numbers(r[1:]) for r in rows if r}
        if "연체되지않은채권" in by_label:                     # 2022년 보고서까지의 서식
            keys = ("연체되지않은채권", "1년이하", "1년초과3년이하", "3년초과")
            if not all(k in by_label for k in keys) or "대손충당금" not in by_label:
                continue
            total = next((v for k, v in by_label.items() if k in ("합계", "계")), None)
            for period, col in (("current", 0), ("prior", 1)):
                try:
                    vals = [by_label[k][col] for k in keys] + [by_label["대손충당금"][col], 0, total[col]]
                except (IndexError, TypeError):
                    continue
                got = _aging_from_values([v for i, v in enumerate(vals) if i != 5])
                if got and period not in out:
                    out[period] = {**{k: (v * unit if isinstance(v, int) else {kk: vv * unit for kk, vv in v.items()})
                                      for k, v in got.items()},
                                   "labels": ["연체되지 않은 채권", "1년 이하", "1년 초과 3년 이하", "3년 초과"]}
            continue
        period = period_of(lead[-120:]) or "current"
        if period in out:
            continue
        flat = [c for r in rows for c in r]
        labels = [bz.label(c) for c in flat if re.search(r"^(현재|3개월이내|1년이내|3개월초과1년이내|1년초과3년이내|3년초과)$", bz.label(c))]
        for r in rows:
            got = _aging_from_values(numbers(r[1:]))
            if got:
                out[period] = {"buckets": {k: v * unit for k, v in got["buckets"].items()}, "allowance": got["allowance"] * unit,
                               "net": got["net"] * unit, "labels": list(dict.fromkeys(labels))[:4]}
                break
    return out


def parse_receivable_mix(doc):
    """{period: {'construction': 총액, 'construction_allowance', 'sales': 총액, 'sales_allowance'}} — 연결 매출채권 중
    공사미수금(도급공사 대금 중 청구한 것)과 분양미수금(자체·분양 사업의 분양대금)의 총장부금액과 대손충당금(원). 장기공사미수금은 뺍니다."""
    out = {}
    matched = -2
    for idx, (pos, table) in enumerate(doc.tables):
        if doc.scope(pos) != "consolidated":
            continue
        lead = _lead(doc, idx, 400)
        if not (re.search(r"매출채권[^.]{0,60}(구성내역|의\s*공시)", lead)
                or (_prev_table(doc, idx) == matched and re.search(r"전기", lead[-60:]))):
            continue
        matched = idx
        rows = bz.table_rows(table)
        unit = unit_of(lead[-200:]) or unit_of(legacy._text(table[:3000]))
        if not unit:
            continue
        flat_head = " ".join(bz.label(c) for r in rows[:2] for c in r)
        two_col = "당기말" in flat_head and "전기말" in flat_head
        found = {}
        for i, r in enumerate(rows):
            cells = [bz.label(c) for c in r]
            name = next((c for c in cells[:2] if c in ("공사미수금", "분양미수금")), None)
            if not name or name in found:
                continue
            vals = numbers(r[1:])
            if two_col:
                nxt = rows[i + 1] if i + 1 < len(rows) else []
                allow = numbers(nxt[1:]) if nxt and bz.label(nxt[0]) == "대손충당금" else []
                if len(vals) >= 2:
                    found[name] = [(vals[0], allow[0] if len(allow) > 0 else 0), (vals[1], allow[1] if len(allow) > 1 else 0)]
            elif vals:
                neg = [v for v in vals[1:] if v < 0]
                found[name] = [(vals[0], neg[0] if neg else 0)]
        if "공사미수금" not in found:
            continue
        periods = [("current", 0), ("prior", 1)] if two_col else [(period_of(lead[-120:]) or "current", 0)]
        for period, col in periods:
            if period in out:
                continue
            try:
                c, ca = found["공사미수금"][col]
                sl, sa = found.get("분양미수금", [(0, 0), (0, 0)])[col]
            except IndexError:
                continue
            out[period] = {"construction": c * unit, "construction_allowance": ca * unit, "sales": sl * unit, "sales_allowance": sa * unit}
    return out


REV_TYPES = {"도급공사수익": "contract", "분양공사수익": "sales", "자산관리수익": "asset_mgmt", "기타수익": "other", "임대료수익": "rent"}


def parse_revenue_types(doc):
    """{period: {'contract': 도급공사수익, 'sales': 분양공사수익, 'asset_mgmt', 'other', 'rent', 'total'}} — 연결 건설계약 주석
    '고객과의 계약에서 생기는 수익의 구분'(2024년 사업보고서부터의 XBRL 표, 원). 기간에 걸쳐·한 시점에 인식한 금액을 더합니다.
    표는 [이름] + (기간에 걸쳐: 다섯 칸 + 소계) + (한 시점에: 다섯 칸 + 소계) 순서이고, 칸 합 = 소계가 맞을 때만 씁니다."""
    out = {}
    matched = -2
    for idx, (pos, table) in enumerate(doc.tables):
        if doc.scope(pos) != "consolidated":
            continue
        lead = _lead(doc, idx, 300)
        if not (re.search(r"고객과의\s*계약에서\s*생기는\s*수익의\s*구분", lead)
                or (_prev_table(doc, idx) == matched and re.search(r"전기", lead[-60:]))):
            continue
        rows = bz.table_rows(table)
        head = next((r for r in rows if sum(1 for c in r if bz.label(c) in REV_TYPES) >= 6), None)
        if not head:
            continue
        matched = idx
        labels = [REV_TYPES[bz.label(c)] for c in head if bz.label(c) in REV_TYPES]
        n = len(labels) // 2
        unit = unit_of(lead[-200:]) or unit_of(legacy._text(table[:2000]))
        period = period_of(lead[-120:]) or "current"
        if not unit or period in out or n < 4:
            continue
        got = {k: 0 for k in REV_TYPES.values()}
        ok = True
        for r in rows:
            if not bz.label(r[0] if r else "").startswith(("고객과의계약에서생기는수익", "기타원천으로부터의수익")):
                continue
            cells = [num(c) if (c or "").strip() else 0 for c in r[1:]]
            if len(cells) != 2 * (n + 1):
                ok = False
                break
            for g in range(2):
                part = cells[g * (n + 1): g * (n + 1) + n]
                sub = cells[g * (n + 1) + n]
                if None in part or sub is None or sum(part) != sub:
                    ok = False
                for k, x in zip(labels[g * n:(g + 1) * n], part):
                    got[k] += (x or 0) * unit
        if ok and any(got.values()):
            got["total"] = sum(got.values())
            out[period] = got
    return out


def _fill(series, year, value, basis, receipt):
    """그 해 보고서(own) 값이 있으면 다음 해 보고서(next) 값으로 덮어쓰지 않습니다."""
    if value is None:
        return
    cur = series.get(str(year))
    if cur and cur.get("basis") == "own" and basis == "next":
        return
    if cur and cur.get("basis") == "own" and basis == "own":
        return
    series[str(year)] = {**value, "basis": basis, "receipt": receipt}


def collect(latest, raw_dir, api_revenue=None, load_json=None):
    """연간 사업보고서(12월)마다 위 1~8을 읽어 {항목: {연도: …}}로 돌려줍니다.
    api_revenue: {연도: 연결 매출(원)} — 부문 표 검증용. load_json: 현금흐름 세부를 읽을 함수(경로 → dict)."""
    out = {"segments": {}, "segments_separate": {}, "regions": {}, "estimates": {}, "estimates_separate": {}, "subsidiary": {},
           "rnd": {}, "dividends": {}, "sensitivity": {}, "market": {}, "materials": {}, "mdna": {}, "cashflow": {},
           "cash_generated": {}, "receivable_aging": {}, "receivable_mix": {}, "revenue_types": {}, "errors": []}
    annual = sorted((y, f) for (y, m), f in latest.items() if m == 12 and y >= FIRST_YEAR)
    for y, f in annual:
        rcept = f["rcept_no"]
        xml = bz.main_document(raw_dir / f"{rcept}.zip", rcept)
        if xml is None:
            continue
        doc = Doc(xml)
        try:
            seg = parse_segment_tables(doc)
            for (scope, period), v in seg.items():
                year = y if period == "current" else y - 1
                target = out["segments"] if scope == "consolidated" else out["segments_separate"]
                if scope == "consolidated" and api_revenue and api_revenue.get(year):
                    if abs(v["revenue"]["total"] - api_revenue[year]) > 0.005 * api_revenue[year]:
                        out["errors"].append(f"{year}년 부문 매출 합계가 연결 매출과 달라 쓰지 않음({rcept})")
                        continue
                _fill(target, year, v, "own" if period == "current" else "next", rcept)
            est = parse_estimate_tables(doc)
            for (scope, period), v in est.items():
                year = y if period == "current" else y - 1
                target = out["estimates"] if scope == "consolidated" else out["estimates_separate"]
                _fill(target, year, {"by": v}, "own" if period == "current" else "next", rcept)
            sub = parse_subsidiary_tables(doc)
            for period, v in sub.items():
                _fill(out["subsidiary"], y if period == "current" else y - 1, v, "own" if period == "current" else "next", rcept)
            for year, v in parse_rnd(doc, y).items():
                _fill(out["rnd"], year, v, "own" if year == y else "next", rcept)
            for year, v in parse_dividends(doc, y).items():
                if v:
                    _fill(out["dividends"], year, v, "own" if year == y else "next", rcept)
            for (scope, period), v in parse_region_tables(doc).items():
                if scope == "consolidated":
                    _fill(out["regions"], y if period == "current" else y - 1, {"revenue": v}, "own" if period == "current" else "next", rcept)
            md = parse_mdna(doc)
            if md:
                out["mdna"][str(y)] = {"sentences": md, "receipt": rcept}
            sens = parse_sensitivity(doc)
            if sens:
                out["sensitivity"][str(y)] = {**sens, "receipt": rcept}
            mk = parse_market_any(xml, y)
            if mk:
                out["market"][str(y)] = {**mk, "receipt": rcept}
            mat = bz.parse_materials(xml)
            if mat:
                nums = [int(re.sub(r"\D", "", p)) for p in mat["periods"]]
                if nums and nums[0] == y - 1949:
                    for it in mat["items"]:
                        item = out["materials"].setdefault(it["name"], {"unit": it["unit"], "values": {}})
                        for i, v in enumerate(it["values"]):
                            if v is not None and str(y - i) not in item["values"]:
                                item["values"][str(y - i)] = v
        except Exception as exc:       # 한 보고서의 형식이 낯설어도 나머지 해는 계속 읽습니다
            out["errors"].append(f"{y}년 사업보고서 주석 읽기({rcept}): {type(exc).__name__}: {exc}")
        try:
            for period, v in parse_cash_generated(doc).items():
                if v.get("gap") != 0 or any(v["subtotal_gaps"].values()):
                    out["errors"].append(f"{y}년 영업으로부터 창출된 현금 주석({period}): 구성 합계가 표의 합계와 달라 쓰지 않음({rcept})")
                    continue
                _fill(out["cash_generated"], y if period == "current" else y - 1, v, "own" if period == "current" else "next", rcept)
        except Exception as exc:
            out["errors"].append(f"{y}년 영업으로부터 창출된 현금 주석 읽기({rcept}): {type(exc).__name__}: {exc}")
        for key, fn in (("receivable_aging", parse_receivable_aging), ("receivable_mix", parse_receivable_mix),
                        ("revenue_types", parse_revenue_types)):
            try:
                for period, v in fn(doc).items():
                    _fill(out[key], y if period == "current" else y - 1, v, "own" if period == "current" else "next", rcept)
            except Exception as exc:
                out["errors"].append(f"{y}년 매출채권 주석 읽기({key}, {rcept}): {type(exc).__name__}: {exc}")
        doc_cf = (load_json(raw_dir / f"{y}_11011_CFS.json") or {}) if load_json else {}
        if doc_cf.get("status") == "000":
            out["cashflow"][str(y)] = cf_detail(doc_cf.get("list", []))
    for item in out["materials"].values():
        item["values"] = dict(sorted(item["values"].items()))
    for k in ("segments", "segments_separate", "regions", "estimates", "estimates_separate", "subsidiary", "rnd", "dividends",
              "sensitivity", "market", "mdna", "cashflow", "cash_generated", "receivable_aging", "receivable_mix",
              "revenue_types"):
        out[k] = dict(sorted(out[k].items()))
    return out
