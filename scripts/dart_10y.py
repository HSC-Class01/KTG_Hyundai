#!/usr/bin/env python3
"""현대건설 연결재무제표 2016~2025년 OpenDART 수집·분석·보고서 생성.

공개 데이터는 OpenDART에서 조회합니다. 인증키는 GitHub Actions Secret
DART_API_KEY로만 전달되며 코드 또는 결과 파일에 저장하지 않습니다.
"""
import csv
import html
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "dart10y"
REPORT_DIR = ROOT / "reports"
YEARS = list(range(2016, 2026))
STOCK_CODE = "000720"
COMPANY = "현대건설"
BASE_URL = "https://opendart.fss.or.kr/api/"
KEY = os.environ.get("DART_API_KEY", "").strip()

# 계정 표준코드 우선, 과거 비표준계정은 정확한 한글 계정명 보조.
# 연결 전체 합계(account_detail='-')만 선택합니다.
FIELDS = {
    "revenue": (("IS", "CIS"),
                ("ifrs-full_Revenue", "ifrs_Revenue",
                 "ifrs-full_RevenueFromContractsWithCustomers",
                 "ifrs_RevenueFromContractsWithCustomers"),
                ("매출액", "수익(매출액)", "매출", "영업수익")),
    "operating_profit": (("IS", "CIS"),
                         ("dart_OperatingIncomeLoss",),
                         ("영업이익", "영업이익(손실)", "영업손익")),
    "net_income": (("IS", "CIS"),
                   ("ifrs-full_ProfitLoss", "ifrs_ProfitLoss"),
                   ("당기순이익", "당기순이익(손실)", "연결당기순이익")),
    "assets": (("BS",),
               ("ifrs-full_Assets", "ifrs_Assets"),
               ("자산총계",)),
    "liabilities": (("BS",),
                    ("ifrs-full_Liabilities", "ifrs_Liabilities"),
                    ("부채총계",)),
    "equity": (("BS",),
               ("ifrs-full_Equity", "ifrs_Equity"),
               ("자본총계",)),
    "current_assets": (("BS",),
                       ("ifrs-full_CurrentAssets", "ifrs_CurrentAssets"),
                       ("유동자산",)),
    "current_liabilities": (("BS",),
                            ("ifrs-full_CurrentLiabilities", "ifrs_CurrentLiabilities"),
                            ("유동부채",)),
    "operating_cashflow": (("CF",),
                           ("ifrs-full_CashFlowsFromUsedInOperatingActivities",
                            "ifrs_CashFlowsFromUsedInOperatingActivities"),
                           ("영업활동현금흐름", "영업활동으로인한현금흐름",
                            "영업활동으로 인한 현금흐름", "영업활동 현금흐름")),
}
LABELS = {
    "revenue": "매출액", "operating_profit": "영업이익",
    "net_income": "당기순이익", "assets": "자산총계",
    "liabilities": "부채총계", "equity": "자본총계",
    "current_assets": "유동자산", "current_liabilities": "유동부채",
    "operating_cashflow": "영업활동현금흐름",
}
RATIO_LABELS = {
    "revenue_growth_pct": "매출증감률(%)",
    "operating_margin_pct": "영업이익률(%)",
    "net_margin_pct": "순이익률(%)",
    "debt_to_equity_pct": "부채비율(%)",
    "current_ratio_pct": "유동비율(%)",
    "roa_pct": "ROA(%)",
    "roe_pct": "ROE(%)",
}


def get_api(endpoint, parameters=None):
    if not KEY:
        raise RuntimeError("DART_API_KEY가 없습니다. 저장소 Settings → Secrets and variables → Actions를 확인하세요.")
    params = {"crtfc_key": KEY}
    params.update(parameters or {})
    url = BASE_URL + endpoint + "?" + urllib.parse.urlencode(params)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=45) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            # 예외 문자열에 인증키가 포함된 요청 URL을 남기지 않습니다.
            if attempt == 2:
                raise RuntimeError(f"OpenDART 연결 실패: {endpoint} (3회 시도)") from None
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("OpenDART 연결 실패")


def get_corp_code():
    content = get_api("corpCode.xml")
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            root = ET.fromstring(zf.read(zf.namelist()[0]))
    except (zipfile.BadZipFile, ET.ParseError, IndexError) as exc:
        raise RuntimeError("OpenDART 회사 고유번호 파일을 해석할 수 없습니다. 인증키/응답을 확인하세요.") from None
    for item in root.findall("list"):
        if (item.findtext("stock_code", "").strip() == STOCK_CODE
                and item.findtext("corp_name", "").strip() == COMPANY):
            return item.findtext("corp_code")
    raise RuntimeError("현대건설의 DART 고유번호를 찾지 못했습니다.")


def fetch_year(corp_code, year):
    raw = get_api("fnlttSinglAcntAll.json", {
        "corp_code": corp_code,
        "bsns_year": str(year),
        "reprt_code": "11011",  # 사업보고서(연간)
        "fs_div": "CFS",        # 연결재무제표
    })
    try:
        doc = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise RuntimeError(f"{year}년 OpenDART 응답이 JSON이 아닙니다.") from None
    if doc.get("status") != "000" or not doc.get("list"):
        raise RuntimeError(f"{year}년 연결 재무제표 조회 실패: {doc.get('status')} {doc.get('message', '')}")
    records = doc["list"]
    if any(str(r.get("bsns_year", year)) != str(year) for r in records):
        raise RuntimeError(f"{year}년 응답에 다른 사업연도의 자료가 섞여 있습니다.")
    if any(r.get("fs_div") not in (None, "", "CFS") for r in records):
        raise RuntimeError(f"{year}년 응답에 연결 이외의 자료가 섞여 있습니다.")
    return doc


def amount(value):
    s = str(value if value is not None else "").replace(",", "").replace(" ", "").strip()
    if not s or s in ("-", "null"):
        return None
    if s.startswith("(") and s.endswith(")"):
        s = "-" + s[1:-1]
    try:
        return int(s)
    except ValueError:
        return None


def pick(records, key):
    statement_types, account_ids, names = FIELDS[key]
    choices = []
    for r in records:
        if r.get("sj_div") not in statement_types:
            continue
        if str(r.get("account_detail", "-")).strip() not in ("", "-"):
            continue
        if str(r.get("currency", "KRW")) not in ("", "KRW"):
            continue
        value = amount(r.get("thstrm_amount"))
        if value is not None:
            choices.append((r, value))
    for account_id in account_ids:
        matches = [(r, v) for r, v in choices if r.get("account_id") == account_id]
        values = set(v for _, v in matches)
        if len(values) == 1:
            r, v = matches[0]
            return v, (r.get("account_id", ""), r.get("account_nm", "")), ""
        if len(values) > 1:
            return None, ("", ""), f"{LABELS[key]}: 표준계정코드의 후보 금액 충돌"
    matches = [(r, v) for r, v in choices if r.get("account_nm", "").strip() in names]
    values = set(v for _, v in matches)
    if len(values) == 1:
        r, v = matches[0]
        return v, (r.get("account_id", ""), r.get("account_nm", "")), ""
    if len(values) > 1:
        return None, ("", ""), f"{LABELS[key]}: 한글 계정명 후보 금액 충돌"
    return None, ("", ""), f"{LABELS[key]}: 해당 연도 계정 미확인"


def ratio(n, d):
    if n is None or d is None or d <= 0:
        return None
    return n / d * 100


def fmt_trillion(value):
    return "자료 없음" if value is None else f"{value / 1_000_000_000_000:,.3f}"


def fmt_pct(value):
    return "자료 없음" if value is None else f"{value:,.2f}"


def write_csv(path, rows, fields):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def generate():
    if not KEY:
        raise RuntimeError("GitHub Repository secret DART_API_KEY를 등록하세요.")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    corp_code = get_corp_code()
    financials, evidence, warnings = [], [], []
    for year in YEARS:
        doc = fetch_year(corp_code, year)
        with (DATA_DIR / f"financial_{year}.json").open("w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=2)
        records = doc["list"]
        receipt = next((r.get("rcept_no", "") for r in records if r.get("rcept_no")), "")
        row = {"year": year, "rcept_no": receipt}
        for field in FIELDS:
            value, (account_id, account_name), issue = pick(records, field)
            row[field] = value
            evidence.append({
                "year": year, "metric": LABELS[field], "account_id": account_id,
                "account_name": account_name, "receipt_no": receipt,
                "status": issue or "확인",
            })
            if issue:
                warnings.append(f"{year}년 {issue}")
        financials.append(row)
        print(f"{year}년 연결재무제표 수집 완료 (원본 {len(records)}개 계정)")
    summary_fields = ["year", "rcept_no"] + list(FIELDS)
    write_csv(DATA_DIR / "financial_summary.csv", financials, summary_fields)
    write_csv(DATA_DIR / "account_sources.csv", evidence,
              ["year", "metric", "account_id", "account_name", "receipt_no", "status"])

    ratios = []
    for index, f in enumerate(financials):
        previous = financials[index - 1] if index else None
        avg_assets = ((f["assets"] + previous["assets"]) / 2
                      if previous and f["assets"] is not None and previous["assets"] is not None else None)
        avg_equity = ((f["equity"] + previous["equity"]) / 2
                      if previous and f["equity"] is not None and previous["equity"] is not None else None)
        ratios.append({
            "year": f["year"],
            "revenue_growth_pct": ratio(
                f["revenue"] - previous["revenue"]
                if previous and f["revenue"] is not None and previous["revenue"] is not None else None,
                previous["revenue"] if previous else None),
            "operating_margin_pct": ratio(f["operating_profit"], f["revenue"]),
            "net_margin_pct": ratio(f["net_income"], f["revenue"]),
            "debt_to_equity_pct": ratio(f["liabilities"], f["equity"]),
            "current_ratio_pct": ratio(f["current_assets"], f["current_liabilities"]),
            "roa_pct": ratio(f["net_income"], avg_assets),
            "roe_pct": ratio(f["net_income"], avg_equity),
        })
    ratio_fields = ["year"] + list(RATIO_LABELS)
    write_csv(DATA_DIR / "financial_ratios.csv", ratios, ratio_fields)

    first, last, prev = financials[0], financials[-1], financials[-2]
    last_r = ratios[-1]
    cagr = None
    if first["revenue"] is not None and last["revenue"] is not None and first["revenue"] > 0 and last["revenue"] > 0:
        cagr = ((last["revenue"] / first["revenue"]) ** (1 / (len(YEARS) - 1)) - 1) * 100
    op = last["operating_profit"]
    op_prev = prev["operating_profit"]
    if op is None or op_prev is None:
        op_story = "최근 영업이익의 연도별 변화는 자료 확인이 필요합니다."
    elif op_prev < 0 < op:
        op_story = f"{prev['year']}년 영업손실 {fmt_trillion(op_prev)}조 원에서 {last['year']}년 영업이익 {fmt_trillion(op)}조 원으로 흑자 전환했습니다."
    elif op_prev > 0 > op:
        op_story = f"{prev['year']}년 영업이익 {fmt_trillion(op_prev)}조 원에서 {last['year']}년 영업손실 {fmt_trillion(op)}조 원으로 적자 전환했습니다."
    else:
        direction = "증가" if op > op_prev else "감소" if op < op_prev else "동일"
        op_story = f"영업이익은 전년 {fmt_trillion(op_prev)}조 원에서 {fmt_trillion(op)}조 원으로 {direction}했습니다."
    negative_cfo = [x["year"] for x in financials if x["operating_cashflow"] is not None and x["operating_cashflow"] < 0]
    cash_story = (f"{last['year']}년 영업활동현금흐름은 {fmt_trillion(last['operating_cashflow'])}조 원입니다. "
                  if last["operating_cashflow"] is not None else "최근 연도 현금흐름은 확인이 필요합니다. ")
    if last["operating_cashflow"] is not None and last["operating_cashflow"] < 0 and op is not None and op > 0:
        cash_story += "영업이익은 흑자지만 영업활동현금흐름은 마이너스이므로 현금 회수 및 운전자본 흐름을 추가 검토할 필요가 있습니다."
    else:
        cash_story += "영업이익과 현금흐름을 구분하여 해석해야 합니다."
    if negative_cfo:
        cash_story += " 음(-)의 영업활동현금흐름이 나타난 연도: " + ", ".join(map(str, negative_cfo)) + "."
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    report_title = "현대건설 10개년 재무제표 자동 분석보고서 (2016~2025)"
    insights = [
        f"연결 매출액은 {first['year']}년 {fmt_trillion(first['revenue'])}조 원, {last['year']}년 {fmt_trillion(last['revenue'])}조 원입니다."
        + (f" 9개 연도 간격을 적용한 매출 연평균복합성장률(CAGR)은 {fmt_pct(cagr)}%입니다." if cagr is not None else ""),
        op_story,
        cash_story,
        f"{last['year']}년 영업이익률은 {fmt_pct(last_r['operating_margin_pct'])}%, 부채비율은 {fmt_pct(last_r['debt_to_equity_pct'])}%, 유동비율은 {fmt_pct(last_r['current_ratio_pct'])}%입니다.",
    ]
    caveats = [
        "금액은 원(KRW) 단위 원자료를 조 원 단위로 환산해 표시합니다. 비율은 원 단위에서 계산합니다.",
        "연결재무제표(CFS) 각 연도 사업보고서의 당기(thstrm_amount) 값을 사용합니다. 이후 정정공시·회계정책 변화·연결범위 변동으로 비교 가능한 숫자가 달라질 수 있습니다.",
        "2016→2025는 10개 연도, 성장률 계산 구간은 9개입니다. 2016년 전년대비 증감률 및 평균자산·자본을 활용하는 ROA/ROE는 산출하지 않습니다.",
        "ROA·ROE는 전기말과 당기말 자산·자본의 단순평균을 분모로 사용합니다. 순이익은 연결 당기순이익 기준으로 지배기업 소유주 귀속이익과 다를 수 있습니다.",
        "자료 없음은 0원이 아닙니다. 계정 미확인 또는 계정 금액 충돌은 임의로 보정하지 않았습니다.",
        "이 보고서는 자동 계산된 1차 분석 자료입니다. 원인 분석과 평가 결론에는 주석, 사업보고서, 수주·원가·공사채권 등을 별도로 검토해야 합니다.",
    ]
    headings = ["연도", "매출(조원)", "영업이익(조원)", "순이익(조원)",
                "영업CF(조원)", "자산(조원)", "부채(조원)", "자본(조원)"]
    row_keys = ["revenue", "operating_profit", "net_income",
                "operating_cashflow", "assets", "liabilities", "equity"]
    table_values = [[str(f["year"])] + [fmt_trillion(f[k]) for k in row_keys] for f in financials]
    ratio_headers = ["연도"] + list(RATIO_LABELS.values())
    ratio_values = [[str(r["year"])] + [fmt_pct(r[k]) for k in RATIO_LABELS] for r in ratios]

    def md_table(headers, items):
        output = ["| " + " | ".join(headers) + " |",
                  "| " + " | ".join(["---"] * len(headers)) + " |"]
        output += ["| " + " | ".join(row) + " |" for row in items]
        return "\n".join(output)

    md = [
        "# " + report_title, "",
        f"- 대상: 현대건설(종목코드 {STOCK_CODE}), 연결재무제표(CFS)",
        f"- 자료: OpenDART 단일회사 전체 재무제표 API, 각 연도 사업보고서(11011)",
        f"- 분석 기간: {YEARS[0]}~{YEARS[-1]}년 / 생성: {generated_at}",
        "- 원본 JSON: data/dart10y/financial_YYYY.json",
        "- 상세 출처: data/dart10y/account_sources.csv", "",
        "## 1. 핵심 분석", "",
        *[f"{i}. {line}" for i, line in enumerate(insights, 1)], "",
        "## 2. 10개년 주요 재무제표", "",
        md_table(headings, table_values), "",
        "## 3. 주요 재무비율", "",
        md_table(ratio_headers, ratio_values), "",
        "## 4. 데이터 검증 결과", "",
        ("모든 대상 계정의 금액이 추출되었습니다." if not warnings else
         "추출하지 못한 계정이 있습니다. 임의의 금액을 채우지 않았습니다."), "",
        *[f"- {w}" for w in warnings], "",
        "## 5. 해석의 한계", "",
        *[f"- {c}" for c in caveats], "",
        "## 6. 사업보고서 원문", "",
        *[f"- {f['year']}년: https://dart.fss.or.kr/dsaf001/main.do?rcpNo={f['rcept_no']}" for f in financials],
        "",
        "API 가이드: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020", "",
    ]
    (REPORT_DIR / "hyundai-10y-report.md").write_text("\n".join(md), encoding="utf-8")

    def html_table(headers, items):
        th = "".join("<th scope='col'>" + html.escape(v) + "</th>" for v in headers)
        trs = "".join("<tr>" + "".join("<td>" + html.escape(v) + "</td>" for v in row) + "</tr>" for row in items)
        return "<div class='table-scroll'><table><thead><tr>" + th + "</tr></thead><tbody>" + trs + "</tbody></table></div>"

    insight_html = "".join("<li>" + html.escape(line) + "</li>" for line in insights)
    caution_html = "".join("<li>" + html.escape(line) + "</li>" for line in caveats)
    warning_html = ("<p class='ok'>대상 계정 모두 추출됨</p>" if not warnings else
                    "<ul>" + "".join("<li>" + html.escape(w) + "</li>" for w in warnings) + "</ul>")
    sources_html = "".join(
        "<li><a href='https://dart.fss.or.kr/dsaf001/main.do?rcpNo=" + html.escape(f["rcept_no"], quote=True) +
        "' target='_blank' rel='noopener'>" + str(f["year"]) + "년 사업보고서 ↗</a></li>" for f in financials)
    style = """
    :root{--forest:#183D3D;--paper:#F3F0E8;--line:#D8D3CA;--muted:#5D6864}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);font:15px/1.75 system-ui,-apple-system,'Noto Sans KR',sans-serif;color:#17231F}
    header{background:var(--forest);color:white;padding:76px max(6vw,24px) 68px}
    header small{font-weight:700;letter-spacing:.16em;color:#B4D3CD}
    h1{font-size:clamp(32px,5vw,58px);line-height:1.17;letter-spacing:-.04em;max-width:900px;margin:15px 0}
    h2{font-size:clamp(24px,3vw,36px);letter-spacing:-.03em;margin:0 0 24px}
    main{max-width:1260px;margin:auto;padding:54px 6% 100px}
    section{padding:38px 0;border-bottom:1px solid var(--line)}
    .meta{color:#D6E4E1}.meta a{color:#D6E4E1}.intro{font-size:17px;max-width:920px}
    .insights{list-style:decimal;padding-left:22px;max-width:1000px}
    .insights li{margin:15px 0;padding-left:6px}
    .table-scroll{overflow-x:auto;border:1px solid var(--line);background:white}
    table{border-collapse:collapse;min-width:990px;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
    th,td{padding:12px 13px;white-space:nowrap;border-bottom:1px solid #E5E2DC;text-align:right}
    th:first-child,td:first-child{text-align:left;font-weight:700}th{background:#E7EFEB;color:#1B4940}
    tr:nth-child(even){background:#F9F9F6}a{color:#1A6252}
    .note{color:var(--muted)}.ok{color:#267552;font-weight:700}
    .sources{columns:2;max-width:600px}.sources li{break-inside:avoid;margin-bottom:8px}
    footer{padding:26px 6%;background:var(--forest);color:#E3EDEB}
    @media(max-width:700px){header{padding-top:50px}main{padding-top:18px}.sources{columns:1}}
    """
    webpage = (
        "<!doctype html><html lang='ko'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<meta name='description' content='현대건설 2016~2025년 연결재무제표 OpenDART 자동 분석보고서'>"
        "<title>" + html.escape(report_title) + "</title><style>" + style + "</style></head><body>"
        "<header><small>HSC-CLASS01 / CIVIL ENGINEERING × DATA</small>"
        "<h1>" + html.escape(report_title) + "</h1>"
        "<p class='meta'>OpenDART 연결재무제표 · 사업보고서 · 10개 사업연도 · 생성 " + html.escape(generated_at) +
        "</p></header><main>"
        "<section><h2>01 / 핵심 분석</h2><ol class='insights'>" + insight_html + "</ol></section>"
        "<section><h2>02 / 10개년 주요 재무제표</h2><p class='note'>금액 단위: 조 원 (연간 사업보고서의 당기 금액)</p>" +
        html_table(headings, table_values) + "</section>"
        "<section><h2>03 / 주요 재무비율</h2><p class='note'>비율 단위: % (매출증감률·ROA·ROE의 첫해 값은 산출 불가)</p>" +
        html_table(ratio_headers, ratio_values) + "</section>"
        "<section><h2>04 / 자료 검증</h2>" + warning_html + "</section>"
        "<section><h2>05 / 해석의 한계</h2><ul>" + caution_html + "</ul></section>"
        "<section><h2>06 / 원본 사업보고서</h2><ul class='sources'>" + sources_html + "</ul>"
        "<p><a href='https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&amp;apiId=2019020' target='_blank' rel='noopener'>OpenDART API 설명 ↗</a></p>"
        "</section></main><footer>HSC-Class01 · KTG_Hyundai · 자동 생성된 교육용 1차 분석보고서</footer></body></html>"
    )
    (REPORT_DIR / "hyundai-10y-report.html").write_text(webpage, encoding="utf-8")
    print("2016~2025년 10개년 재무제표, 비율 CSV, Markdown 및 HTML 보고서 생성 완료")
    if warnings:
        print(f"데이터 품질 주의: {len(warnings)}건. 보고서의 검증 절을 확인하세요.")


if __name__ == "__main__":
    generate()
