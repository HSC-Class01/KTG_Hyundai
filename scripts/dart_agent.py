#!/usr/bin/env python3
"""현대건설 OpenDART 재무분석 에이전트.

GitHub Actions가 매월 1일 실행합니다. 하는 일:
  1) OpenDART에서 2010년 이후 사업·반기·분기보고서 목록을 받고, 보고서 원문(ZIP)을 저장소에 보관
  2) 2015년 이후 연결재무제표를 API로 받아 저장 (2013~2014 연간, 2015 분기 손익은 다음 해 보고서의 비교 열로 보충)
  3) 연간·반기·분기 표, 재무비율, 자동 해설을 다시 계산하고 대시보드(dashboard/index.html)와 README를 갱신
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

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
DATA = ROOT / "data" / "financials"
RAW = DATA / "raw"
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


class Dart:
    def __init__(self, key):
        self.key = key
        self.calls = 0

    def get(self, endpoint, params, timeout=60):
        url = BASE_URL + endpoint + "?" + urllib.parse.urlencode({"crtfc_key": self.key, **params})
        for attempt in range(4):
            try:
                self.calls += 1
                with urllib.request.urlopen(url, timeout=timeout) as response:
                    return response.read()
            except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
                # 오류 메시지에 인증키가 들어 있는 주소가 남지 않도록 원인 문자열을 버립니다.
                if attempt == 3:
                    raise ApiError(f"{endpoint} 연결 실패(4회 시도)") from None
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
    dart = Dart(key)
    RAW.mkdir(parents=True, exist_ok=True)
    corp = cfg["corp_code"]

    # 회사·동종기업 고유번호
    codes = load_json(RAW / "corp_codes.json", {})
    wanted = {cfg["stock_code"], *[p["stock_code"] for p in cfg.get("peers", [])]}
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
            if time.monotonic() - started > budget_minutes * 60:
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
    status["api_calls"] = dart.calls
    return status


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
                             "current_ratio_pct": fin.ratio(v.get("current_assets"), v.get("current_liabilities"))}
        rows.append(row)
    return rows


CSV_AMOUNTS = ["revenue", "cost_of_sales", "gross_profit", "sga", "operating_profit", "net_income", "net_income_owners",
               "assets", "liabilities", "equity", "current_assets", "current_liabilities", "operating_cashflow",
               "investing_cashflow", "financing_cashflow", "cash_and_deposits", "borrowings_total", "net_cash",
               "receivables_total", "advances_total"]


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
    import legacy
    periods, latest = assemble(cfg)
    legacy_report = legacy.fill(periods, latest, RAW, cfg)
    finalize_warnings(periods)
    annual, halves, quarters = fin.build_tables(periods)
    latest_filing = max(latest.values(), key=lambda f: f["rcept_no"]) if latest else None
    ctx = {"company": cfg, "today": today.isoformat(), "next_run": fin.next_run_date(today).isoformat(),
           "annual": annual, "halves": halves, "quarters": quarters, "peers": peer_rows(cfg), "status": status,
           "log": log if log is not None else load_json(DATA / "update_log.json", []),
           "latest_filing": latest_filing, "filing_count": len(latest), "legacy": legacy_report,
           "archives": sum(1 for f in latest.values() if (RAW / f"{f['rcept_no']}.zip").exists())}
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
             f"- 대시보드: {ctx['company']['dashboard_url']}", ""]
    for f in status.get("new_filings", []):
        lines.append(f"  - {f['report_nm'].strip()} ({f['rcept_dt']})")
    if a.get("headline"):
        lines += ["", "**자동 해설**: " + a["plain"].get("headline", ""), ""]
    if status.get("errors"):
        lines += ["### 확인이 필요한 점", ""] + [f"- {e}" for e in status["errors"]]
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")


def build(cfg, today, status, online):
    import dashboard
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
    write_text(ROOT / "dashboard" / "index.html", dashboard.render(ctx))
    dashboard.update_readme(ROOT / "README.md", ctx)
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
    for name in ("index.html", "projects", "reports", "dashboard", "assets"):
        src = ROOT / name
        if src.is_dir():
            shutil.copytree(src, site / name)
        elif src.exists():
            shutil.copy2(src, site / name)
    out = site / "data" / "financials"
    out.mkdir(parents=True)
    for name in ("annual.csv", "half_year.csv", "quarterly.csv", "dashboard.json", "status.json", "filings.json"):
        if (DATA / name).exists():
            shutil.copy2(DATA / name, out / name)
    (site / ".nojekyll").write_text("")
    print("_site 조립 완료")


def main():
    parser = argparse.ArgumentParser(description="OpenDART 재무분석 에이전트")
    parser.add_argument("--offline", action="store_true", help="수집 없이 저장된 자료로 화면만 다시 만듭니다")
    parser.add_argument("--build-site", action="store_true", help="GitHub Pages(Actions 배포)용 _site 폴더를 만듭니다")
    parser.add_argument("--budget-minutes", type=float, default=25, help="원문 다운로드에 쓸 최대 시간(분)")
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
