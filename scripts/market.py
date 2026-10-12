"""주가·주식수로 시장가치 지표(PER·PBR·EV/EBITDA·FCF 수익률)를 계산합니다.

- 주가: 네이버 금융 차트 자료의 월봉 종가. 받지 못하면 Yahoo Finance 월봉 종가를 씁니다.
- 주식수: OpenDART '주식의 총수 현황'(stockTotqySttus) 보통주·우선주 발행주식수 (2015년 사업연도부터 제공).
- 받은 자료는 data/financials/raw/market/ 에 저장하고, 계산은 저장된 자료로만 합니다(네트워크 없이 다시 계산 가능).

시가총액 = 그 달 말 보통주 종가 × (보통주 + 우선주 발행주식수). 우선주 주가는 따로 받지 않습니다(비중이 작음).
"""
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))
UA = {"User-Agent": "Mozilla/5.0 (compatible; KTG_Hyundai-financial-agent/1.0; +https://github.com/HSC-Class01/KTG_Hyundai)"}
SHARES_FIRST_YEAR = 2015


def _get(url, timeout=30):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def naver_monthly(code, start, end):
    """{'YYYYMM': 종가} (네이버 금융 월봉)."""
    url = "https://api.finance.naver.com/siseJson.naver?" + urllib.parse.urlencode(
        {"symbol": code, "requestType": 1, "startTime": start.strftime("%Y%m%d"), "endTime": end.strftime("%Y%m%d"),
         "timeframe": "month"})
    text = _get(url).decode("utf-8", "replace")
    rows = re.findall(r'\[\s*"(\d{8})"\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)', text)
    return {d[:6]: float(close) for d, _, _, _, close in rows}


def yahoo_monthly(code, start, end):
    """{'YYYYMM': 종가} (Yahoo Finance 월봉, 코스피 종목코드.KS)."""
    p1 = int(datetime(start.year, start.month, 1, tzinfo=KST).timestamp())
    p2 = int(datetime(end.year, end.month, end.day, 23, 59, tzinfo=KST).timestamp())
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{code}.KS?"
           + urllib.parse.urlencode({"period1": p1, "period2": p2, "interval": "1mo"}))
    doc = json.loads(_get(url).decode("utf-8"))
    res = doc["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    out = {}
    for ts, close in zip(res.get("timestamp") or [], closes):
        if close is not None:
            d = datetime.fromtimestamp(ts, KST) + timedelta(days=3)   # 월 초 시각이 전달 말일로 보이는 경우 보정
            out[f"{d.year}{d.month:02d}"] = float(close)
    return out


def fetch_prices(code, start, end):
    """(월별 종가, 출처, 오류 메시지 목록). 두 곳 모두 실패하면 빈 사전."""
    errors = []
    for name, fn in (("네이버 금융", naver_monthly), ("Yahoo Finance", yahoo_monthly)):
        try:
            got = fn(code, start, end)
            if len(got) >= 1:
                return got, name, errors
            errors.append(f"{name}: 자료 없음")
        except Exception as exc:  # 네트워크·형식 오류 모두 기록만 하고 다음 출처로
            errors.append(f"{name}: {type(exc).__name__}")
    return {}, "", errors


def parse_shares(doc):
    """stockTotqySttus 응답 → {'common': 보통주, 'preferred': 우선주} 발행주식수."""
    out = {}
    for row in (doc or {}).get("list", []):
        se = "".join(str(row.get("se", "")).split())
        raw = str(row.get("istc_totqy", "")).replace(",", "").strip()
        if not raw.lstrip("-").isdigit():
            continue
        if se.startswith("보통"):
            out["common"] = int(raw)
        elif se.startswith("우선"):
            out["preferred"] = int(raw)
    return out if out.get("common") else {}


def month_close(prices, year, month):
    """그 달(없으면 그 전 3개월 안의 가장 최근 달) 종가."""
    for back in range(0, 4):
        y, m = year, month - back
        while m <= 0:
            y, m = y - 1, m + 12
        v = prices.get(f"{y}{m:02d}")
        if v:
            return v, f"{y}.{m:02d}"
    return None, None


def valuation(price, shares, values, ebitda=None, net_income_owners=None, fcf=None):
    """시가총액과 배수. values는 그 시점 재무상태(지배주주지분·순차입금·비지배지분)."""
    if not price or not shares or not shares.get("common"):
        return {}
    count = shares["common"] + shares.get("preferred", 0)
    cap = price * count
    out = {"price": price, "shares": count, "market_cap": cap}
    eq = values.get("equity_owners")
    if net_income_owners is not None and net_income_owners > 0:
        out["per_x"] = cap / net_income_owners
    if eq is not None and eq > 0:
        out["pbr_x"] = cap / eq
    nd, nci = values.get("net_debt"), values.get("nci_equity")
    if nd is not None:
        out["ev"] = cap + nd + (nci or 0)
        if ebitda is not None and ebitda > 0:
            out["ev_ebitda_x"] = out["ev"] / ebitda
    if fcf is not None and cap > 0:
        out["fcf_yield_pct"] = fcf / cap * 100
    return out


def apply_annual(annual, prices, shares_by_year):
    """연간 행마다 연말 주가 기준 시장가치 지표를 붙입니다."""
    for r in annual:
        sh = shares_by_year.get(str(r["year"]))
        price, when = month_close(prices, r["year"], 12)
        v = r["values"]
        val = valuation(price, sh, v, ebitda=v.get("ebitda"), net_income_owners=v.get("net_income_owners"),
                        fcf=v.get("fcf"))
        if not val:
            continue
        v["price_close"] = price
        v["market_cap"] = val["market_cap"]
        for k in ("per_x", "pbr_x", "ev_ebitda_x", "fcf_yield_pct"):
            r["ratios"][k] = val.get(k)
        r["market_note"] = f"{when} 종가 {price:,.0f}원 × {val['shares']:,}주"
