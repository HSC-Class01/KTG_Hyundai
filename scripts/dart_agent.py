#!/usr/bin/env python3
"""현대건설 OpenDART 재무분석 에이전트.

GitHub Actions가 매월 1일 실행합니다. 하는 일:
  1) OpenDART에서 2010년 이후 사업·반기·분기보고서 목록을 받고, 보고서 원문(ZIP)을 저장소에 보관
  2) 2015년 이후 연결재무제표를 API로 받아 저장 (2013~2014 연간, 2015 분기 손익은 다음 해 보고서의 비교 열로 보충)
  3) 연간·반기·분기 표, 재무비율, 자동 해설을 다시 계산하고 재무제표 대시보드(dashboard/index.html)와 README를 갱신
  4) 사업보고서 본문(수주·PF 등)과 재무제표로 기업분석 보고서 PDF(reports/)를 다시 인쇄 (내용이 바뀐 경우만)
새 보고서가 없으면 숫자는 그대로 두고 '확인 기록'만 남깁니다.

실행
  python scripts/dart_agent.py                 # 수집 + 화면 생성 (환경변수 DART_API_KEY 필요)
  python scripts/dart_agent.py --offline       # 저장된 자료로 화면만 다시 생성 (키 불필요)
  python scripts/dart_agent.py --build-site    # GitHub Pages(Actions 배포)용 _site 폴더 조립
인증키는 환경변수로만 읽고 어떤 파일에도 쓰지 않습니다.
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import financials as fin  # noqa: E402
import market  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data" / "financials"
RAW = DATA / "raw"
MARKET = RAW / "market"
KST = timezone(timedelta(hours=9))
BASE_URL = "https://opendart.fss.or.kr/api/"
API_FIRST_YEAR = 2015          # OpenDART 재무제표 API 제공 시작 연도
MAX_ARCHIVE_BYTES = 90 * 1024 * 1024


def now_kst():
    return datetime.now(KST)


def load_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_text(path, text):
    """내용이 바뀐 경우에만 씁니다(불필요한 커밋 방지)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def write_json(path, doc):
    write_text(path, json.dumps(doc, ensure_ascii=False, indent=1, allow_nan=False) + "\n")


def company_config():
    cfg = load_json(CONFIG / "company.json")
    if not cfg:
        raise SystemExit("config/company.json 파일이 없습니다.")
    return cfg


# ---------------------------------------------------------------------------
# OpenDART 접속
# ---------------------------------------------------------------------------
class ApiError(Exception):
    pass


def read_limited(response, limit_seconds):
    """응답을 조금씩 읽다가 전체 시간이 limit_seconds를 넘으면 멈춥니다(느린 서버에 워크플로가 붙잡히지 않게)."""
    started = time.monotonic()
    chunks = []
    while True:
        if time.monotonic() - started > limit_seconds:
            raise TimeoutError("응답이 너무 느림")
        chunk = response.read(65536)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)


class Dart:
    def __init__(self, key, deadline=None):
        self.key = key
        self.calls = 0
        self.deadline = deadline          # time.monotonic() 기준 전체 수집 마감 시각

    def get(self, endpoint, params, timeout=60):
        url = BASE_URL + endpoint + "?" + urllib.parse.urlencode({"crtfc_key": self.key, **params})
        for attempt in range(3):
            if self.deadline and time.monotonic() > self.deadline:
                raise ApiError(f"{endpoint}: 수집 시간 제한을 넘어 다음 실행으로 넘김")
            try:
                self.calls += 1
                with urllib.request.urlopen(url, timeout=30) as response:
                    return read_limited(response, timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                # 오류 메시지에 인증키가 들어 있는 주소가 남지 않도록 원인 문자열을 버립니다.
                if attempt == 2:
                    raise ApiError(f"{endpoint} 연결 실패(3회 시도)") from None
                time.sleep(3 * (attempt + 1))
        raise ApiError(f"{endpoint} 연결 실패")

    def json(self, endpoint, params):
        raw = self.get(endpoint, params)
        try:
            doc = json.loads(raw.decode("utf-8-sig"))
        except (UnicodeError, json.JSONDecodeError):
            raise ApiError(f"{endpoint} 응답이 JSON이 아닙니다") from None
        if doc.get("status") in ("000", "013"):   # 013 = 조회된 데이터 없음
            return doc
        raise ApiError(f"{endpoint}: OpenDART status {doc.get('status')} {doc.get('message', '')}".strip())


def corp_codes(dart, stock_codes):
    """corpCode.xml에서 종목코드 → (고유번호, 회사명)을 찾습니다."""
    content = dart.get("corpCode.xml", {}, timeout=120)
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            root = ET.fromstring(zf.read(zf.namelist()[0]))
    except (zipfile.BadZipFile, ET.ParseError, IndexError):
        raise ApiError("corpCode.xml을 해석할 수 없습니다(인증키 확인)") from None
    found = {}
    for item in root.findall("list"):
        code = (item.findtext("stock_code") or "").strip()
        if code in stock_codes:
            found[code] = {"corp_code": item.findtext("corp_code"), "corp_name": (item.findtext("corp_name") or "").strip()}
    return found


PERIOD_RE = re.compile(r"(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)")


def period_of(filing):
    match = PERIOD_RE.search(filing.get("report_nm", ""))
    if not match or "철" in filing.get("rm", ""):
        return None
    kind, year, month = match.group(1), int(match.group(2)), int(match.group(3))
    ok = (kind == "사업" and month == 12) or (kind == "반기" and month == 6) or (kind == "분기" and month in (3, 9))
    return (year, month) if ok else None


def latest_by_period(filings, first_year):
    """기간마다 가장 최근 접수(정정 포함) 보고서를 고릅니다."""
    latest = {}
    for f in sorted(filings, key=lambda f: f["rcept_no"]):
        p = period_of(f)
        if p and p[0] >= first_year:
            latest[p] = f
    return latest


def list_filings(dart, corp_code, start, end):
    out, page = [], 1
    while True:
        doc = dart.json("list.json", {"corp_code": corp_code, "bgn_de": start, "end_de": end, "pblntf_ty": "A",
                                      "last_reprt_at": "N", "page_count": "100", "page_no": str(page)})
        out.extend(doc.get("list", []))
        if page >= int(doc.get("total_page") or 0):
            break
        page += 1
    return [f for f in out if period_of(f)]


# ---------------------------------------------------------------------------
# 1) 수집
# ---------------------------------------------------------------------------
def api_path(year, month):
    return RAW / f"{year}_{fin.REPORT_CODES[month]}_CFS.json"


def collect(cfg, today, budget_minutes):
    """수집 단계. 자료 문제는 status에 기록하고 계속 진행합니다(워크플로를 멈추지 않음)."""
    started = time.monotonic()
    status = {"checked_at": now_kst().isoformat(timespec="seconds"), "mode": "online", "errors": [], "notes": [],
              "new_filings": [], "api_calls": 0, "archives_downloaded": 0, "archives_pending": 0}
    key = os.environ.get("DART_API_KEY", "").strip()
    if not key:
        status["mode"] = "offline"
        status["errors"].append("DART_API_KEY가 없어 새 자료를 받지 못했습니다. 저장소 Settings → Secrets and variables → "
                                "Actions에 DART_API_KEY를 등록하세요. 저장된 자료로 화면만 다시 만들었습니다.")
        return status
    dart = Dart(key, deadline=started + budget_minutes * 60)
    RAW.mkdir(parents=True, exist_ok=True)
    corp = cfg["corp_code"]

    # 회사·동종기업 고유번호 (저장된 목록에 없는 회사가 있을 때만 큰 목록 파일을 받습니다)
    codes = load_json(RAW / "corp_codes.json", {})
    wanted = {cfg["stock_code"], *[p["stock_code"] for p in cfg.get("peers", [])]}
    if not wanted <= set(codes):
        try:
            fresh = corp_codes(dart, wanted)
            own = fresh.get(cfg["stock_code"], {}).get("corp_code")
            if own and own != corp:
                status["errors"].append(f"고유번호가 설정({corp})과 다릅니다: {own}")
            codes.update(fresh)
            write_json(RAW / "corp_codes.json", codes)
        except ApiError as exc:
            status["errors"].append(f"회사 고유번호 목록: {exc} · 저장된 목록을 사용합니다.")

    # 공시 목록 (정정 포함)
    previous = load_json(DATA / "filings.json", [])
    try:
        filings = list_filings(dart, corp, f"{cfg['first_year']}0101", today.strftime("%Y%m%d"))
        # 2010년 초에 접수된 2009년 사업보고서처럼 분석 시작 연도 이전 기간의 보고서는 뺍니다.
        filings = [f for f in filings if period_of(f)[0] >= cfg["first_year"]]
        if previous and not filings:
            raise ApiError("공시 목록이 비어 있습니다")
        old_ids = {f["rcept_no"] for f in previous}
        status["new_filings"] = [{"rcept_no": f["rcept_no"], "report_nm": f["report_nm"], "rcept_dt": f["rcept_dt"]}
                                 for f in sorted(filings, key=lambda f: f["rcept_no"]) if f["rcept_no"] not in old_ids]
        write_json(DATA / "filings.json", sorted(filings, key=lambda f: f["rcept_no"], reverse=True))
    except ApiError as exc:
        status["errors"].append(f"공시 목록: {exc} · 지난번 목록을 사용합니다.")
        filings = previous
    latest = latest_by_period(filings, cfg["first_year"])

    # 재무제표 API (2015년 이후). 처음 받는 기간·정정된 기간·최근 2년만 다시 받습니다.
    recent_cut = (today.year - 2, today.month)
    for (year, month), filing in sorted(latest.items()):
        if year < API_FIRST_YEAR:
            continue
        path = api_path(year, month)
        cached = load_json(path)
        cached_receipts = {r.get("rcept_no") for r in (cached or {}).get("list", [])}
        refresh = (cached is None or (year, month) >= recent_cut
                   or (cached.get("status") == "000" and filing["rcept_no"] not in cached_receipts)
                   or (cached.get("status") == "013" and year > API_FIRST_YEAR))
        if not refresh:
            continue
        try:
            doc = dart.json("fnlttSinglAcntAll.json", {"corp_code": corp, "bsns_year": str(year),
                                                       "reprt_code": fin.REPORT_CODES[month], "fs_div": "CFS"})
            for r in doc.get("list", []):
                if str(r.get("bsns_year", year)) != str(year) or r.get("reprt_code", fin.REPORT_CODES[month]) != fin.REPORT_CODES[month]:
                    raise ApiError(f"응답의 연도·보고서 코드가 요청과 다릅니다")
            write_json(path, doc)
        except ApiError as exc:
            status["errors"].append(f"{fin.period_label(year, month)} 재무제표: {exc}")

    # 보고서 원문 보관 (오래 걸리면 다음 실행으로 넘김)
    todo = [f for f in latest.values() if not (RAW / f"{f['rcept_no']}.zip").exists()]
    archive_budget = budget_minutes * 60 * 0.6   # 전체 시간의 60%까지만 원문 받기에 씁니다

    def fetch_archive(filing):
        content = dart.get("document.xml", {"rcept_no": filing["rcept_no"]}, timeout=180)
        if not zipfile.is_zipfile(io.BytesIO(content)):
            raise ApiError(f"{filing['report_nm']} 원문이 ZIP 형식이 아닙니다")
        if len(content) > MAX_ARCHIVE_BYTES:
            raise ApiError(f"{filing['report_nm']} 원문이 90MB를 넘어 보관하지 않았습니다")
        (RAW / f"{filing['rcept_no']}.zip").write_bytes(content)

    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = {}
        for filing in todo:
            if time.monotonic() - started > archive_budget:
                break
            futures[pool.submit(fetch_archive, filing)] = filing
        for future in as_completed(futures):
            try:
                future.result()
                status["archives_downloaded"] += 1
            except ApiError as exc:
                status["errors"].append(f"원문 보관: {exc}")
    status["archives_pending"] = sum(1 for f in latest.values() if not (RAW / f"{f['rcept_no']}.zip").exists())
    if status["archives_pending"]:
        status["notes"].append(f"보고서 원문 {status['archives_pending']}건은 시간 제한으로 다음 실행에서 받습니다.")

    # 동종기업 최근 사업보고서 (작년 → 재작년 순으로 시도)
    for peer in cfg.get("peers", []):
        info = codes.get(peer["stock_code"])
        if not info:
            status["errors"].append(f"{peer['name']}: 고유번호를 찾지 못했습니다")
            continue
        for year in (today.year - 1, today.year - 2):
            try:
                doc = dart.json("fnlttSinglAcntAll.json", {"corp_code": info["corp_code"], "bsns_year": str(year),
                                                           "reprt_code": "11011", "fs_div": "CFS"})
            except ApiError as exc:
                status["errors"].append(f"{peer['name']} {year}년: {exc}")
                break
            if doc.get("status") == "000":
                write_json(RAW / "peers" / f"{peer['stock_code']}_{year}.json", doc)
                break

    # 시장가치 계산용: 주식수(OpenDART)와 월말 주가(네이버 금융 → 실패 시 Yahoo Finance)
    collect_market(dart, cfg, codes, latest, today, status)
    status["api_calls"] = dart.calls
    return status


def collect_market(dart, cfg, codes, latest, today, status):
    """주식수와 주가를 받아 data/financials/raw/market/ 에 저장합니다. 실패해도 계속 진행합니다."""
    MARKET.mkdir(parents=True, exist_ok=True)

    def shares_of(corp_code, year, reprt_code):
        doc = dart.json("stockTotqySttus.json", {"corp_code": corp_code, "bsns_year": str(year), "reprt_code": reprt_code})
        return market.parse_shares(doc)

    # 회사: 2015년 이후 사업보고서마다 + 가장 최근 보고서
    own = cfg["stock_code"]
    saved = load_json(MARKET / f"{own}_shares.json", {}) or {}
    wanted = [(str(y), y, fin.REPORT_CODES[12]) for (y, m) in sorted(latest) if m == 12 and y >= market.SHARES_FIRST_YEAR]
    if latest:
        (ly, lm) = max(latest)
        wanted.append(("latest", ly, fin.REPORT_CODES[lm]))
    for key, year, code in wanted:
        if key in saved and key != "latest" and str(year) != str(today.year - 1) and not saved[key].get("missing"):
            continue
        if saved.get(key, {}).get("missing") and year < today.year - 2:
            continue
        try:
            got = shares_of(cfg["corp_code"], year, code)
        except ApiError as exc:
            status["errors"].append(f"주식수 {year}: {exc}")
            continue
        # 자료가 없는 연도도 표시해 두어 매달 다시 묻지 않습니다.
        saved[key] = {**got, "period": f"{year}.{fin.CODE_MONTH[code]:02d}"} if got else {"period": f"{year}", "missing": True}
    write_json(MARKET / f"{own}_shares.json", saved)

    # 동종기업: 저장된 최근 사업보고서 연도의 주식수
    for peer in cfg.get("peers", []):
        info = codes.get(peer["stock_code"])
        files = sorted((RAW / "peers").glob(f"{peer['stock_code']}_*.json"))
        if not info or not files:
            continue
        year = files[-1].stem.split("_")[1]
        path = MARKET / f"{peer['stock_code']}_shares.json"
        saved = load_json(path, {}) or {}
        if year in saved:
            continue
        try:
            got = shares_of(info["corp_code"], year, fin.REPORT_CODES[12])
        except ApiError as exc:
            status["errors"].append(f"{peer['name']} 주식수: {exc}")
            continue
        if got:
            saved[year] = {**got, "period": f"{year}.12"}
            write_json(path, saved)

    # 주가 (월말 종가)
    for code in [own] + [p["stock_code"] for p in cfg.get("peers", [])]:
        if dart.deadline and time.monotonic() > dart.deadline:
            status["notes"].append("수집 시간 제한으로 일부 주가는 다음 실행에서 받습니다.")
            break
        start = date(cfg["first_year"], 1, 1) if code == own else date(today.year - 2, 1, 1)
        prices, source, errs = market.fetch_prices(code, start, today)
        path = MARKET / f"{code}_prices.json"
        if prices:
            old = (load_json(path, {}) or {}).get("monthly", {})
            merged = dict(sorted({**old, **prices}.items()))
            write_json(path, {"source": source, "fetched": today.isoformat(), "monthly": merged})
        else:
            status["errors"].append(f"주가({code}) 받기 실패: {', '.join(errs)} · 저장된 주가로 계산합니다.")


# ---------------------------------------------------------------------------
# 2) 정리 · 계산 (네트워크 없음)
# ---------------------------------------------------------------------------
def assemble(cfg):
    """저장된 원자료로 보고서 기간별 숫자를 만듭니다."""
    filings = load_json(DATA / "filings.json", [])
    latest = latest_by_period(filings, cfg["first_year"])
    periods = {}

    def period(y, m):
        if (y, m) not in periods:
            p = fin.blank_period(y, m)
            f = latest.get((y, m))
            if f:
                p.update(receipt=f["rcept_no"], report_name=f["report_nm"], filed=f["rcept_dt"])
            periods[(y, m)] = p
        return periods[(y, m)]

    docs = {}
    for path in sorted(RAW.glob("*_CFS.json")):
        m = re.match(r"(\d{4})_(\d{5})_CFS\.json$", path.name)
        if not m or m.group(2) not in fin.CODE_MONTH:
            continue
        doc = load_json(path)
        if doc and doc.get("status") == "000" and doc.get("list"):
            docs[(int(m.group(1)), fin.CODE_MONTH[m.group(2)])] = doc["list"]

    # (1) 각 보고서 자체 숫자
    for (y, m), records in docs.items():
        got = fin.extract(records, m, "current")
        p = period(y, m)
        fin.merge(p, got["values"], "api", overwrite=True)
        p["evidence"] = got["evidence"]
        p["warnings"].extend(sorted(set(got["issues"])))
        receipts = sorted({r.get("rcept_no") for r in records if r.get("rcept_no")})
        if receipts and p["receipt"] and p["receipt"] not in receipts:
            p["warnings"].append("공시 목록의 최신 접수번호와 재무 API 접수번호가 다릅니다")
    # (2) 다음 해 보고서의 비교 열로 빈 기간 보충 (2013~2014 연간, 2015 분·반기 손익·현금흐름)
    for (y, m), records in sorted(docs.items()):
        for which, back in (("prior", 1), ("prior2", 2)):
            target = (y - back, m)
            if target[0] < cfg["first_year"] or target in docs:
                continue
            got = fin.extract(records, m, which)
            if not any(v is not None for v in got["values"].values()):
                continue
            fin.merge(period(*target), got["values"], "api-prior")
    # (3) 보고서는 있지만 숫자가 없는 기간도 표에 보이도록 칸을 만듭니다
    for (y, m) in latest:
        period(y, m)
    return periods, latest


SOURCE_NOTES = {
    "api-prior": "일부 숫자는 다음 해 보고서(API)의 비교 열",
    "document": "공시 원문 표에서 읽은 숫자",
    "document-prior": "일부 숫자는 다음 보고서 원문의 비교 열",
}


def finalize_warnings(periods):
    for (y, m), p in periods.items():
        for source in sorted(set(p["sources"].values())):
            if source in SOURCE_NOTES:
                p["warnings"].append(SOURCE_NOTES[source])
        if not p["values"]:
            p["warnings"].append("숫자 없음 · 원문 보관만 함" if y < API_FIRST_YEAR else "재무제표 API 자료 없음")
        gap = fin.balance_gap(p["values"])
        if gap is not None and abs(gap) > max(abs(p["values"]["assets"]) * 1e-6, 2_000_000):
            p["warnings"].append(f"자산 ≠ 부채 + 자본 (차이 {gap:,}원)")


def peer_rows(cfg):
    codes = load_json(RAW / "corp_codes.json", {})
    rows = []
    for peer in cfg.get("peers", []):
        files = sorted((RAW / "peers").glob(f"{peer['stock_code']}_*.json"))
        row = {**peer, "dart_name": codes.get(peer["stock_code"], {}).get("corp_name") or peer["name"],
               "year": None, "values": {}, "ratios": {}, "receipt": ""}
        if files:
            doc = load_json(files[-1], {})
            got = fin.extract(doc.get("list", []), 12, "current")
            v = fin.add_derived(got["values"])
            row.update(year=int(files[-1].stem.split("_")[1]), values=v,
                       receipt=(doc.get("list") or [{}])[0].get("rcept_no", ""))
            row["ratios"] = {"operating_margin_pct": fin.ratio(v.get("operating_profit"), v.get("revenue")),
                             "net_margin_pct": fin.ratio(v.get("net_income"), v.get("revenue")),
                             "debt_to_equity_pct": fin.ratio(v.get("liabilities"), v.get("equity")),
                             "current_ratio_pct": fin.ratio(v.get("current_assets"), v.get("current_liabilities")),
                             "roe_pct": fin.ratio(v.get("net_income"), v.get("equity"))}
            row.update(peer_market(peer["stock_code"], row["year"], v))
        rows.append(row)
    return rows


def peer_market(stock_code, year, values):
    """현재 주가 × 주식수로 PER·PBR (최근 사업보고서 숫자 기준)."""
    prices = (load_json(MARKET / f"{stock_code}_prices.json", {}) or {}).get("monthly", {})
    shares = (load_json(MARKET / f"{stock_code}_shares.json", {}) or {}).get(str(year))
    if not prices or not shares:
        return {"market": {}}
    month = max(prices)
    val = market.valuation(prices[month], shares, values, net_income_owners=values.get("net_income_owners"))
    val["as_of"] = f"{month[:4]}.{month[4:]}"
    return {"market": val}


def current_valuation(quarters, annual, prices, shares):
    """가장 최근 주가 기준 시장가치 (최근 4개 분기 이익·현금흐름, 최근 분기말 재무상태)."""
    monthly = prices.get("monthly", {}) if prices else {}
    sh = shares.get("latest") or (shares.get(str(annual[-1]["year"])) if annual else None)
    if not monthly or not sh or not quarters:
        return {}
    month = max(monthly)
    bal = next((q for q in reversed(quarters) if q["values"].get("assets") is not None), None)
    if bal is None:
        return {}
    ttm = {k: fin.ttm(quarters, k)[0] for k in ("net_income_owners", "ebitda", "fcf", "net_income")}
    val = market.valuation(monthly[month], sh, bal["values"], ebitda=ttm["ebitda"],
                           net_income_owners=ttm["net_income_owners"], fcf=ttm["fcf"])
    if val:
        val.update(as_of=f"{month[:4]}.{month[4:]}", source=prices.get("source", ""), fetched=prices.get("fetched", ""),
                   balance_label=f"{bal['year']}년 {bal['month']}월 말", shares_period=sh.get("period", ""), ttm=ttm)
    return val


CSV_AMOUNTS = ["revenue", "cost_of_sales", "gross_profit", "sga", "operating_profit", "ebitda", "dep_amort",
               "interest_expense", "pretax_income", "income_tax", "net_income", "net_income_owners",
               "assets", "current_assets", "cash", "short_term_deposits", "trade_receivables", "contract_assets",
               "inventories", "ppe", "liabilities", "current_liabilities", "trade_payables", "borrowings_total", "net_debt",
               "equity", "equity_owners", "operating_cashflow", "investing_cashflow", "financing_cashflow", "capex", "fcf",
               "receivables_total", "advances_total", "price_close", "market_cap"]


def write_csv(path, rows):
    fields = ["period", "year", "month", "kind", *CSV_AMOUNTS, *fin.RATIO_LABELS, "derived", "sources", "receipt", "warnings"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        out = {"period": r["label"], "year": r["year"], "month": r["month"], "kind": r["kind"],
               "derived": "계산" if r["derived"] else "", "sources": " ".join(r["sources"]), "receipt": r["receipt"],
               "warnings": " / ".join(r["warnings"])}
        out.update({k: r["values"].get(k) for k in CSV_AMOUNTS})
        out.update({k: (None if r["ratios"].get(k) is None else round(r["ratios"][k], 4)) for k in fin.RATIO_LABELS})
        writer.writerow(out)
    write_text(path, "﻿" + buf.getvalue())


def make_context(cfg, today, status, log=None):
    """저장된 원자료로 표·비율·자동 해설을 계산합니다. 파일은 쓰지 않습니다. 반환: (ctx, periods)"""
    import analysis
    import business
    import legacy
    import notes
    periods, latest = assemble(cfg)
    legacy_report = legacy.fill(periods, latest, RAW, cfg)
    notes_report = notes.fill(periods, latest, RAW, cfg["first_year"])
    finalize_warnings(periods)
    annual, halves, quarters = fin.build_tables(periods)
    prices = (load_json(MARKET / f"{cfg['stock_code']}_prices.json", {}) or {})
    shares = load_json(MARKET / f"{cfg['stock_code']}_shares.json", {}) or {}
    market.apply_annual(annual, prices.get("monthly", {}), shares)
    latest_filing = max(latest.values(), key=lambda f: f["rcept_no"]) if latest else None
    ctx = {"company": cfg, "today": today.isoformat(), "next_run": fin.next_run_date(today).isoformat(),
           "annual": annual, "halves": halves, "quarters": quarters, "peers": peer_rows(cfg), "status": status,
           "log": log if log is not None else load_json(DATA / "update_log.json", []),
           "latest_filing": latest_filing, "filing_count": len(latest), "legacy": legacy_report, "notes": notes_report,
           "archives": sum(1 for f in latest.values() if (RAW / f"{f['rcept_no']}.zip").exists()),
           "valuation": current_valuation(quarters, annual, prices, shares)}
    peer_years = [p["year"] for p in ctx["peers"] if p.get("year")]
    base = next((r for r in annual if peer_years and r["year"] == max(peer_years)), annual[-1] if annual else None)
    ctx["own_market"] = peer_market(cfg["stock_code"], base["year"], base["values"])["market"] if base else {}
    ctx["prices"] = prices.get("monthly", {})
    saved = load_json(DATA / "business.json", {}) or {}
    try:
        fresh = business.collect(latest, RAW)
    except Exception as exc:    # 사업보고서 본문을 못 읽어도 재무제표 화면은 만듭니다
        fresh = {"errors": [f"사업보고서 본문 읽기 실패: {type(exc).__name__}"]}
    # 원문 ZIP이 없는 환경(제출용 ZIP을 푼 폴더 등)에서는 지난번에 저장한 값을 그대로 씁니다
    keys = list(fresh) + [k for k in saved if k not in fresh]     # 순서를 고정해야 매달 JSON 차이가 생기지 않습니다
    ctx["business"] = {k: (fresh.get(k) if fresh.get(k) else saved.get(k)) for k in keys}
    ctx["business"]["errors"] = fresh.get("errors") or []
    ctx["analysis"] = analysis.analyze(ctx)
    return ctx, periods


def step_summary(ctx):
    """GitHub Actions 실행 요약 화면에 이번 실행 결과를 남깁니다."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    status, a = ctx["status"], ctx["analysis"]
    lines = [f"## {ctx['company']['name']} 재무 에이전트 실행 결과", "",
             f"- 확인 시각: {status.get('checked_at', '')} ({'OpenDART 접속' if status.get('mode') == 'online' else '저장된 자료로 다시 생성'})",
             f"- 표: 연간 {len(ctx['annual'])} · 반기 {len(ctx['halves'])} · 분기 {len(ctx['quarters'])}개 기간",
             f"- 새로 나온 공시: {len(status.get('new_filings', []))}건 · OpenDART 호출 {status.get('api_calls', 0)}회",
             f"- 대시보드: {ctx['company']['dashboard_url']}",
             f"- 기업분석 보고서 PDF: {ctx.get('report_pdf', '–')}", ""]
    for f in status.get("new_filings", []):
        lines.append(f"  - {f['report_nm'].strip()} ({f['rcept_dt']})")
    if a.get("headline"):
        lines += ["", "**자동 해설**: " + a["plain"].get("headline", ""), ""]
    if status.get("errors"):
        lines += ["### 확인이 필요한 점", ""] + [f"- {e}" for e in status["errors"]]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def build(cfg, today, status, online):
    import company_report
    import dashboard
    import statements
    log = load_json(DATA / "update_log.json", [])
    if online:
        log.insert(0, {"checked_at": status["checked_at"], "new_filings": status.get("new_filings", []),
                       "errors": len(status.get("errors", []))})
        log = log[:24]
        write_json(DATA / "update_log.json", log)
    ctx, periods = make_context(cfg, today, status, log)
    annual, halves, quarters, peers = ctx["annual"], ctx["halves"], ctx["quarters"], ctx["peers"]
    write_csv(DATA / "annual.csv", annual)
    write_csv(DATA / "half_year.csv", halves)
    write_csv(DATA / "quarterly.csv", quarters)
    write_json(DATA / "periods.json", [{"period": f"{y}.{m:02d}", **p} for (y, m), p in sorted(periods.items())])
    write_json(DATA / "dashboard.json", {"company": cfg["name"], "checked_at": status["checked_at"],
                                         "annual": annual, "half_year": halves, "quarterly": quarters,
                                         "peers": peers, "analysis": ctx["analysis"]["plain"]})
    write_json(DATA / "business.json", {k: v for k, v in ctx["business"].items()})
    write_text(ROOT / "dashboard" / "index.html", dashboard.render(ctx))
    write_text(ROOT / "statements" / "index.html", statements.redirect_page(ctx))   # 예전 주소 → 대시보드
    dashboard.update_readme(ROOT / "README.md", ctx)
    try:
        ctx["report_pdf"] = company_report.write(ctx, ROOT)       # 기업분석 보고서 PDF (내용이 바뀐 경우에만 다시 인쇄)
    except Exception as exc:    # PDF를 못 만들어도 대시보드·데이터 갱신은 그대로 진행합니다
        ctx["report_pdf"] = f"기업분석 보고서 PDF 생략: {type(exc).__name__}: {exc}"
        print(f"::warning::{ctx['report_pdf']}")
    write_json(DATA / "status.json", {**status, "periods": len(periods), "annual_rows": len(annual),
                                      "half_year_rows": len(halves), "quarter_rows": len(quarters)})
    step_summary(ctx)
    print(f"완료: 연간 {len(annual)} · 반기 {len(halves)} · 분기 {len(quarters)}행 · 오류 {len(status.get('errors', []))}건")
    for line in status.get("errors", []):
        print(f"::warning::{line}")


def build_site():
    site = ROOT / "_site"
    if site.exists():
        shutil.rmtree(site)
    site.mkdir()
    for name in ("index.html", "projects", "reports", "dashboard", "statements", "assets"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, site / name)
        elif src.exists():
            shutil.copy2(src, site / name)
    out = site / "data" / "financials"
    out.mkdir(parents=True)
    for name in ("annual.csv", "half_year.csv", "quarterly.csv", "dashboard.json", "business.json", "status.json", "filings.json"):
        if (DATA / name).exists():
            shutil.copy2(DATA / name, out / name)
    (site / ".nojekyll").write_text("")
    print("_site 조립 완료")


def main():
    parser = argparse.ArgumentParser(description="OpenDART 재무분석 에이전트")
    parser.add_argument("--offline", action="store_true", help="수집 없이 저장된 자료로 화면만 다시 만듭니다")
    parser.add_argument("--build-site", action="store_true", help="GitHub Pages(Actions 배포)용 _site 폴더를 만듭니다")
    parser.add_argument("--budget-minutes", type=float, default=20, help="수집 전체에 쓸 최대 시간(분)")
    parser.add_argument("--today", help="기준일 YYYY-MM-DD (테스트용)")
    args = parser.parse_args()
    if args.build_site:
        build_site()
        return
    cfg = company_config()
    today = date.fromisoformat(args.today) if args.today else now_kst().date()
    if args.offline:
        # 저장된 마지막 확인 기록을 그대로 쓰고, 화면만 다시 만듭니다.
        status = load_json(DATA / "status.json", {}) or {}
        status.setdefault("checked_at", now_kst().isoformat(timespec="seconds"))
        status.setdefault("mode", "offline")
        status.setdefault("errors", [])
        status.setdefault("new_filings", [])
    else:
        try:
            status = collect(cfg, today, args.budget_minutes)
        except Exception as exc:  # 예상 못 한 수집 오류도 기록하고 화면은 다시 만듭니다
            status = {"checked_at": now_kst().isoformat(timespec="seconds"), "mode": "online", "notes": [],
                      "errors": [f"수집 중 예상하지 못한 오류: {type(exc).__name__}: {exc}"], "new_filings": []}
    build(cfg, today, status, online=not args.offline and status.get("mode") == "online")


if __name__ == "__main__":
    main()
