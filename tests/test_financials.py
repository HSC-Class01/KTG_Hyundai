import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import dart_agent as agent
import dart_10y as core

class FinancialRules(unittest.TestCase):
    def test_interim_uses_cumulative_and_preserves_cf(self):
        rows=[{'sj_div':'IS','account_id':'ifrs-full_Revenue','account_nm':'매출액','thstrm_amount':'40','thstrm_add_amount':'75'},
              {'sj_div':'CF','account_id':'ifrs-full_CashFlowsFromUsedInOperatingActivities','thstrm_amount':'-12'}]
        self.assertEqual(agent.pick_api(rows,'revenue',6)[0],75)
        self.assertEqual(agent.pick_api(rows,'operating_cashflow',6)[0],-12)
        rows[0].pop('thstrm_add_amount')
        self.assertIsNone(agent.pick_api(rows,'revenue',6)[0])
        self.assertEqual(agent.pick_api(rows,'revenue',3)[0],40)
    def test_quarter_difference_missing_zero_and_yoy(self):
        rows=[]
        for year in [2024,2025]:
            for month,value in [(3,10),(6,30),(9,30),(12,60)]:
                r=agent.blank_row(year,month)
                for k in agent.FLOW:r[k]=value
                r['assets']=100;r['liabilities']=40;r['equity']=60
                rows.append(r)
        doc=agent.analyze(rows,'20260101')
        q={r['period']:r for r in doc['quarterly']}
        self.assertEqual(q['2025-Q2']['revenue'],20)
        self.assertEqual(q['2025-Q3']['revenue'],0)
        self.assertEqual(q['2025-Q4']['revenue'],30)
        self.assertEqual(q['2025-Q2']['ratios']['revenue_growth_pct'],0)
        self.assertEqual(q['2025-Q2']['assets'],100)
        rows[4]['revenue']=None
        self.assertIsNone({r['period']:r for r in agent.analyze(rows,'20260101')['quarterly']}['2025-Q2']['revenue'])
    def test_conflicting_accounts_and_nonpositive_denominator(self):
        rows=[{'sj_div':'BS','account_id':'ifrs-full_Assets','thstrm_amount':str(v)} for v in [20,30]]
        self.assertIsNone(core.pick(rows,'assets')[0])
        self.assertIsNone(core.ratio(10,0))
        self.assertIsNone(core.ratio(10,-5))
        self.assertEqual(core.amount('(1,234)'),-1234)
    def test_restatement_and_period_year(self):
        reports=[{'report_nm':'사업보고서 (2024.12)','rcept_no':'20250301000001'},
                 {'report_nm':'[기재정정]사업보고서 (2024.12)','rcept_no':'20260401000001'}]
        self.assertEqual(agent.select_latest(reports)[(2024,12)]['rcept_no'],'20260401000001')
        self.assertIsNone(agent.period_of({'report_nm':'사업보고서 (2009.12)'}))
    def test_legacy_candidates_do_not_become_facts(self):
        text='<DOCUMENT><P>연결재무제표 (단위: 백만원)</P>&nbsp;<TABLE><TR><TD>매출액</TD><TD>999</TD></TR></TABLE></DOCUMENT>'
        self.assertTrue(agent.legacy_candidates(text.encode(),2010,12))
        r=agent.blank_row(2010,12)
        self.assertIsNone(agent.reviewed_legacy(r)['revenue'])
    def test_existing_annual_source_balance(self):
        base=agent.ROOT/'data/dart10y'
        for path in sorted(base.glob('financial_*.json')):
            year=int(path.stem.split('_')[-1]);doc=json.loads(path.read_text())
            r=agent.normalized_api(doc,year,12,{'rcept_no':doc['list'][0]['rcept_no']})
            self.assertIsNotNone(r['revenue'])
            self.assertEqual(r['assets'],r['liabilities']+r['equity'])

if __name__=='__main__':unittest.main()
