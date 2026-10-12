#!/usr/bin/env python3
"""OpenDART periodic filings: archive, normalize, validate, render. No key is persisted."""
import argparse
import copy
import hashlib
import io
import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from lxml import etree
import dart_10y as core

ROOT = core.ROOT
DATA = ROOT / 'data' / 'financials'
RAW = DATA / 'raw'
CORP = '00164478'  # validated against corpCode.xml on every online run
CODES = {3: '11013', 6: '11012', 9: '11014', 12: '11011'}
FLOW = {'revenue', 'operating_profit', 'net_income', 'operating_cashflow'}
NAMES = {3: 'Q1', 6: 'H1', 9: 'Q3', 12: 'FY'}


def write_json(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def api(endpoint, params, allow_empty=False):
    doc = json.loads(core.get_api(endpoint, params).decode('utf-8-sig'))
    if doc.get('status') == '013' and allow_empty:
        return doc
    if doc.get('status') != '000':
        raise RuntimeError(f"OpenDART {endpoint}: status={doc.get('status')} (인증·한도·서비스 상태 확인)")
    return doc


def period_of(filing):
    title = filing['report_nm']
    match = re.search(r'(사업|반기|분기)보고서\s*\((\d{4})\.(\d{2})\)', title)
    if not match or '철' in filing.get('rm', ''):
        return None
    kind, year, month = match.groups()
    year, month = int(year), int(month)
    if year < 2010 or month not in CODES:
        return None
    if (kind == '사업' and month != 12) or (kind == '반기' and month != 6) or (kind == '분기' and month not in (3,9)):
        return None
    return year, month


def list_filings(today):
    result, page = [], 1
    while True:
        doc = api('list.json', {'corp_code': CORP, 'bgn_de': '20100101', 'end_de': today,
                  'pblntf_ty': 'A', 'last_reprt_at': 'N', 'page_count': '100', 'page_no': str(page)}, True)
        result.extend(doc.get('list', []))
        if page >= int(doc.get('total_page', 0)):
            break
        page += 1
    return [f for f in result if period_of(f)]


def select_latest(filings):
    result = {}
    for filing in sorted(filings, key=lambda f: f['rcept_no']):
        result[period_of(filing)] = filing
    return result


def pick_api(records, field, month):
    """IS interim thstrm_amount is 3 months; use add_amount for YTD. CF is YTD."""
    rows = copy.deepcopy(records)
    if field in FLOW - {'operating_cashflow'} and month != 12:
        for row in rows:
            value = row.get('thstrm_add_amount')
            # Q1 can use its 3-month value; never treat H1/Q3 quarter as cumulative.
            row['thstrm_amount'] = value if core.amount(value) is not None else row.get('thstrm_amount') if month == 3 else None
    return core.pick(rows, field)


def normalized_api(doc, year, month, filing):
    records = doc.get('list', [])
    if not records:
        return blank_row(year, month, filing, '재무 API 미제공')
    for r in records:
        if str(r.get('bsns_year', year)) != str(year) or r.get('corp_code', CORP) != CORP or r.get('reprt_code', CODES[month]) != CODES[month]:
            raise RuntimeError('재무 응답의 기업·연도·보고서 코드 불일치')
        if r.get('fs_div') not in (None, '', 'CFS'):
            raise RuntimeError('연결 이외 재무제표 혼입')
    row = blank_row(year, month, filing, '')
    row['source'] = 'OpenDART CFS API'
    api_receipts = sorted({r['rcept_no'] for r in records if r.get('rcept_no')})
    row['financial_receipts'] = api_receipts
    row['warnings'] = []
    if api_receipts != [filing['rcept_no']]:
        row['warnings'].append('원문 최신 접수번호와 재무 API 접수번호 차이: 각 출처 별도 보존')
    for field in core.FIELDS:
        value, (aid, name), issue = pick_api(records, field, month)
        row[field] = value
        column = 'thstrm_add_amount' if field in FLOW - {'operating_cashflow'} and month != 12 else 'thstrm_amount'
        if month == 3 and column == 'thstrm_add_amount':
            matched = [r for r in records if r.get('account_id') == aid and r.get('account_nm') == name]
            if matched and all(core.amount(r.get('thstrm_add_amount')) is None for r in matched):
                column = 'thstrm_amount'
        row['evidence'][field] = {'account_id': aid, 'account_name': name, 'column': column}
        if issue:
            row['warnings'].append(issue)
    validate_balance(row)
    return row


def blank_row(year, month, filing=None, warning='미공시 또는 미수집'):
    filing = filing or {}
    return {'year': year, 'month': month, 'period': f'{year}-{NAMES[month]}', 'basis': 'CFS',
            'receipt': filing.get('rcept_no', ''), 'report_name': filing.get('report_nm', ''),
            'source': '', 'warnings': [warning] if warning else [], 'evidence': {},
            **{k: None for k in core.FIELDS}}


def validate_balance(row):
    a, l, e = (row[x] for x in ('assets', 'liabilities', 'equity'))
    if None not in (a,l,e) and abs(a-l-e) > max(abs(a)*1e-6, 1000000):
        raise RuntimeError(f"{row['period']}: 자산=부채+자본 검증 실패")


def legacy_candidates(content, year, month):
    """Conservative CFS table candidates only, never promote them without review.

    Historical documents may mix K-GAAP/IFRS, summaries, 3/6/9 month and
    standalone figures. Candidates + context make a human check reproducible.
    """
    root = etree.fromstring(content, etree.XMLParser(recover=True, resolve_entities=False, no_network=True, huge_tree=True))
    if root is None:
        return []
    found = []
    for table in root.iter():
        if str(table.tag).upper() != 'TABLE':
            continue
        context = ' '.join(' '.join(x.itertext()) for x in [x for x in table.itersiblings(preceding=True) if isinstance(x.tag, str)][:6])
        text = ' '.join(table.itertext())
        if '연결' not in context + text:
            continue
        for tr in table.iter():
            if str(tr.tag).upper() != 'TR':
                continue
            cells = [' '.join(x.itertext()).strip() for x in tr if str(x.tag).upper() in ('TD','TH','TE')]
            if len(cells) < 2:
                continue
            label = re.sub(r'^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ\d.\s]+', '', cells[0]).replace(' ', '')
            for field, (_, _, names) in core.FIELDS.items():
                if label in {x.replace(' ', '') for x in names}:
                    found.append({'metric':field, 'cells':cells, 'context':context[-1400:], 'table_header':text[:700], 'year':year, 'month':month})
    return found


def reviewed_legacy(row):
    path = ROOT / 'config' / 'historical_verified.json'
    reviews = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
    matching = [v for v in reviews if v['year']==row['year'] and v['month']==row['month'] and v['receipt']==row['receipt']]
    for v in matching:
        if v.get('basis') != 'CFS' or not v.get('evidence') or not v.get('reviewed_by'):
            raise RuntimeError('과거 수기검증 값의 연결기준·근거·검토자 누락')
        for field, value in v['values_krw'].items():
            if field not in core.FIELDS or not isinstance(value, int) or isinstance(value,bool):
                raise RuntimeError('수기검증 값 형식 오류')
            row[field] = value
            row['evidence'][field] = v['evidence']
        row['source'] = '공시 원문 수기검증 CFS'
        row['warnings'] = ['2010~2014 회계기준·연결범위 차이 검토 필요']
        validate_balance(row)
    return row


def ratios(row, prior_year, prior_end):
    n, rev = row['net_income'], row['revenue']
    prev_rev = prior_year.get('revenue') if prior_year else None
    def average(key):
        a, b = row.get(key), prior_end.get(key) if prior_end else None
        return (a+b)/2 if a is not None and b is not None else None
    # Interim returns represent actual YTD periods, deliberately not annualized.
    return {'revenue_growth_pct': core.ratio(rev-prev_rev if rev is not None and prev_rev is not None else None, prev_rev),
            'operating_margin_pct': core.ratio(row['operating_profit'], rev),
            'net_margin_pct': core.ratio(n,rev), 'debt_to_equity_pct':core.ratio(row['liabilities'],row['equity']),
            'current_ratio_pct':core.ratio(row['current_assets'],row['current_liabilities']),
            'roa_pct':core.ratio(n,average('assets')), 'roe_pct':core.ratio(n,average('equity'))}


def analyze(rows, today):
    lookup = {(r['year'],r['month']):r for r in rows}
    annual, half, quarters = [], [], []
    for r in rows:
        r['ratios'] = ratios(r,lookup.get((r['year']-1,r['month'])),lookup.get((r['year']-1,12)))
        (annual if r['month']==12 else half if r['month']==6 else []).append(r)
    for year in range(2010,int(today[:4])+1):
        for q in range(1,5):
            month = q*3
            if f'{year}{month:02d}01' > today:
                continue
            current = lookup.get((year,month), blank_row(year,month))
            previous = lookup.get((year,month-3)) if q>1 else None
            item = copy.deepcopy(current)
            item['period'] = f'{year}-Q{q}'
            item['derived'] = q>1
            for key in FLOW:
                a,b = current[key], previous.get(key) if previous else None
                item[key] = a if q==1 else a-b if a is not None and b is not None else None
            item['prior_receipt'] = previous.get('receipt','') if previous else ''
            item['warnings'] = list(current['warnings'])
            if q>1 and (not previous or any(previous[k] is None for k in FLOW)):
                item['warnings'].append('前 누적期 결측: 해당 개별분기 계산 불가')
            # Balance sheet is period end. Q4 takes FY year-end values.
            item['ratios'] = ratios(item, None, None)
            quarters.append(item)
    qlookup = {r['period']:r for r in quarters}
    for q in quarters:
        prev = qlookup.get(f"{q['year']-1}-Q{q['month']//3}")
        q['ratios'] = ratios(q,prev,None)  # ROA/ROE only meaningful on YTD/annual tables
    return {'company':'현대건설', 'stock_code':core.STOCK_CODE, 'corp_code':CORP, 'updated_at':today,
            'annual':annual, 'half_year':half, 'quarterly':quarters,
            'peers':json.loads((ROOT/'config/peers.json').read_text(encoding='utf-8'))}


def export(rows, today):
    doc = analyze(rows,today)
    write_json(DATA/'dashboard.json',doc)
    for category in ('annual','half_year','quarterly'):
        flattened = [{**{k:v for k,v in r.items() if k in ['year','month','period','receipt','basis','source'] or k in core.FIELDS}, **r['ratios'], 'warnings':'; '.join(r['warnings'])} for r in doc[category]]
        core.write_csv(DATA/f'{category}.csv', flattened, ['year','month','period','receipt','basis','source',*core.FIELDS,*core.RATIO_LABELS,'warnings'])
    # Embed verified data for file:// offline use and a self-contained dashboard.
    template = (ROOT/'dashboard/template.html').read_text(encoding='utf-8')
    payload = json.dumps(doc,ensure_ascii=False,allow_nan=False).replace('<','\\u003c')
    (ROOT/'dashboard/index.html').write_text(template.replace('__DATA_JSON__',payload),encoding='utf-8')
    return doc


def offline(today):
    path = DATA/'periods.json'
    if path.exists():
        rows=json.loads(path.read_text(encoding='utf-8'))
    else:
        rows=[]
        for year in range(2010,int(today[:4])+1):
            for month in CODES:
                if f'{year}{month:02d}01' > today: continue
                old = ROOT/'data/dart10y'/f'financial_{year}.json'
                if month==12 and old.exists():
                    doc=json.loads(old.read_text(encoding='utf-8'))
                    filing={'rcept_no':doc['list'][0]['rcept_no'],'report_nm':f'사업보고서 ({year}.12)'}
                    rows.append(normalized_api(doc,year,month,filing))
                else: rows.append(blank_row(year,month))
    return export(rows,today)


def collect(today):
    if core.get_corp_code() != CORP:
        raise RuntimeError('현대건설 고유번호 불일치')
    RAW.mkdir(parents=True,exist_ok=True)
    filings=list_filings(today)
    write_json(DATA/'filings.json',filings)
    latest=select_latest(filings)
    rows=[]
    for year in range(2010,int(today[:4])+1):
        for month in CODES:
            if f'{year}{month:02d}01' > today: continue
            filing=latest.get((year,month))
            if not filing:
                rows.append(blank_row(year,month)); continue
            receipt=filing['rcept_no']
            archive=RAW/f'{receipt}.zip'
            if not archive.exists():
                content=core.get_api('document.xml',{'rcept_no':receipt})
                if not zipfile.is_zipfile(io.BytesIO(content)):
                    raise RuntimeError(f'{receipt}: 공시 원문 ZIP 응답 실패')
                if len(content)>90*1024*1024:
                    raise RuntimeError(f'{receipt}: GitHub 원문 파일 크기 제한 초과')
                archive.write_bytes(content)
            row=blank_row(year,month,filing,'2015년 이전: 재무 API 미제공 · 원문 수치 검증 대기')
            if year<2015:
                candidate_path=RAW/f'{receipt}_candidates.json'
                if not candidate_path.exists():
                    candidates=[]
                    with zipfile.ZipFile(archive) as z:
                        for name in z.namelist():
                            if name.lower().endswith(('.xml','.html','.htm')):
                                candidates.extend(legacy_candidates(z.read(name),year,month))
                    write_json(candidate_path,candidates)
                row=reviewed_legacy(row)
            else:
                doc=api('fnlttSinglAcntAll.json',{'corp_code':CORP,'bsns_year':str(year),'reprt_code':CODES[month],'fs_div':'CFS'},True)
                write_json(RAW/f'{year}_{CODES[month]}_CFS.json',doc)
                row=normalized_api(doc,year,month,filing)
            row['archive']=str(archive.relative_to(ROOT))
            row['archive_sha256']=hashlib.sha256(archive.read_bytes()).hexdigest()
            rows.append(row)
            print(f"{year} {NAMES[month]}: 수집 완료 · {sum(row[k] is not None for k in core.FIELDS)}/{len(core.FIELDS)} 항목")
    write_json(DATA/'periods.json',rows)
    export(rows,today)
    write_json(DATA/'last_run.json',{'checked_at':datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),'filing_count':len(filings),'period_count':len(rows),'status':'success'})


def build_site():
    site=ROOT/'_site'
    if site.exists(): shutil.rmtree(site)
    site.mkdir()
    for name in ('index.html','projects','reports','dashboard','assets'):
        src=ROOT/name
        if src.is_dir(): shutil.copytree(src,site/name)
        elif src.exists(): shutil.copy2(src,site/name)
    (site/'data/financials').mkdir(parents=True,exist_ok=True)
    for name in ('dashboard.json','annual.csv','half_year.csv','quarterly.csv','filings.json','last_run.json'):
        src=DATA/name
        if src.exists(): shutil.copy2(src,site/'data/financials'/name)
    (site/'.nojekyll').write_text('')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--offline',action='store_true')
    parser.add_argument('--build-site',action='store_true')
    parser.add_argument('--today',default=datetime.now(ZoneInfo('Asia/Seoul')).strftime('%Y%m%d'))
    args=parser.parse_args()
    if args.build_site: build_site()
    elif args.offline: offline(args.today)
    else: collect(args.today)
