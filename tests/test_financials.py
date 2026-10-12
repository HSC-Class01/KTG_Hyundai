"""계산 규칙 테스트 (네트워크 없이 실행).

GitHub Actions가 매달 수집 전에 먼저 실행합니다. 새 공시가 나와 숫자가 바뀌어도 깨지지 않도록,
실제 자료에 대해서는 '항상 성립해야 하는 관계'(분기 합 = 연간, 자산 = 부채 + 자본 등)만 확인합니다.
"""
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analysis  # noqa: E402
import dart_agent as agent  # noqa: E402
import dashboard  # noqa: E402
import financials as fin  # noqa: E402
import legacy  # noqa: E402


def api_row(sj, account_id, name, **amounts):
    row = {"sj_div": sj, "account_id": account_id, "account_nm": name, "account_detail": "-", "currency": "KRW"}
    row.update({k: str(v) for k, v in amounts.items()})
    return row


def period(year, month, **values):
    p = fin.blank_period(year, month)
    p["values"].update(values)
    p["sources"].update({k: "api" for k in values})
    p["report_name"] = f"{fin.REPORT_NAMES[month]} ({year}.{month:02d})"
    return p


class NumberParsing(unittest.TestCase):
    def test_amount(self):
        self.assertEqual(fin.amount("1,234"), 1234)
        self.assertEqual(fin.amount("(1,234)"), -1234)
        self.assertEqual(fin.amount("-5"), -5)
        self.assertIsNone(fin.amount("-"))
        self.assertIsNone(fin.amount(""))
        self.assertIsNone(fin.amount(None))

    def test_ratio_and_growth_need_positive_denominator(self):
        self.assertEqual(fin.ratio(50, 200), 25)
        self.assertIsNone(fin.ratio(10, 0))
        self.assertIsNone(fin.ratio(10, -5))
        self.assertIsNone(fin.ratio(None, 5))
        self.assertAlmostEqual(fin.growth(110, 100), 10)
        self.assertIsNone(fin.growth(110, 0))

    def test_korean_won_format(self):
        self.assertEqual(analysis.won(31_062_912_000_000), "31조 629억")
        self.assertEqual(analysis.won(-216_900_000_000), "−2,169억")
        self.assertEqual(dashboard.eok(123_456_000_000), "1,235")
        self.assertEqual(dashboard.eok(None), "–")


class AccountMatching(unittest.TestCase):
    def test_standard_code_first_then_name(self):
        rows = [api_row("CIS", "ifrs-full_Revenue", "수익(매출액)", thstrm_amount=100),
                api_row("CIS", "-표준계정코드 미사용-", "매출액", thstrm_amount=999)]
        self.assertEqual(fin.pick(rows, "revenue")[0], 100)
        rows = [api_row("BS", "x", "자산 총계", thstrm_amount=500)]
        self.assertEqual(fin.pick(rows, "assets")[0], 500)   # 띄어쓰기 무시

    def test_conflicting_candidates_are_left_empty(self):
        rows = [api_row("BS", "ifrs-full_Assets", "자산총계", thstrm_amount=20),
                api_row("BS", "ifrs-full_Assets", "자산총계", thstrm_amount=30)]
        value, _, issue = fin.pick(rows, "assets")
        self.assertIsNone(value)
        self.assertIn("충돌", issue)

    def test_interim_income_uses_cumulative_column(self):
        rows = [api_row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=40, thstrm_add_amount=75,
                        frmtrm_amount=35, frmtrm_add_amount=70),
                api_row("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", "영업활동현금흐름",
                        thstrm_amount=-12, frmtrm_amount=8)]
        cur = fin.extract(rows, 6, "current")["values"]
        self.assertEqual(cur["revenue"], 75)            # 반기 누적
        self.assertEqual(cur["operating_cashflow"], -12)  # 현금흐름은 thstrm_amount가 누적
        prior = fin.extract(rows, 6, "prior")["values"]
        self.assertEqual(prior["revenue"], 70)
        self.assertEqual(prior["operating_cashflow"], 8)
        self.assertNotIn("assets", prior)               # 분·반기 비교 열의 재무상태표는 전기말이라 쓰지 않음

    def test_first_quarter_falls_back_to_three_month_column(self):
        rows = [api_row("IS", "ifrs-full_Revenue", "매출액", thstrm_amount=40)]
        self.assertEqual(fin.extract(rows, 3)["values"]["revenue"], 40)
        self.assertIsNone(fin.extract(rows, 6)["values"]["revenue"])   # 반기에서 3개월 값을 누적으로 쓰지 않음


class Periods(unittest.TestCase):
    def make(self):
        periods = {}
        for year, scale in ((2024, 1), (2025, 2)):
            for month, cum in ((3, 10), (6, 30), (9, 45), (12, 70)):
                periods[(year, month)] = period(year, month, revenue=cum * scale, operating_profit=cum, net_income=cum // 2,
                                                operating_cashflow=-cum, assets=100 + month, liabilities=60, equity=40 + month)
        return periods

    def test_quarters_halves_and_balance(self):
        annual, halves, quarters = fin.build_tables(self.make())
        q = {(r["year"], r["kind"]): r for r in quarters}
        self.assertEqual(q[(2025, "Q1")]["values"]["revenue"], 20)
        self.assertEqual(q[(2025, "Q2")]["values"]["revenue"], 40)   # 60 − 20
        self.assertEqual(q[(2025, "Q3")]["values"]["revenue"], 30)   # 90 − 60
        self.assertEqual(q[(2025, "Q4")]["values"]["revenue"], 50)   # 140 − 90
        self.assertEqual(q[(2025, "Q2")]["values"]["assets"], 106)  # 재무상태표는 그 분기말 잔액
        self.assertTrue(q[(2025, "Q4")]["derived"])
        self.assertFalse(q[(2025, "Q1")]["derived"])
        h = {(r["year"], r["kind"]): r for r in halves}
        self.assertEqual(h[(2025, "H2")]["values"]["revenue"], 80)   # 140 − 60
        self.assertEqual(sum(q[(2025, k)]["values"]["revenue"] for k in ("Q1", "Q2", "Q3", "Q4")),
                         annual[-1]["values"]["revenue"])
        self.assertAlmostEqual(q[(2025, "Q2")]["ratios"]["revenue_growth_pct"], 100)   # 전년 같은 분기 대비
        self.assertAlmostEqual(q[(2025, "Q1")]["ratios"]["qoq_growth_pct"], (20 - 25) / 25 * 100)
        self.assertIsNotNone(annual[-1]["ratios"]["roe_pct"])
        self.assertIsNone(annual[0]["ratios"]["roe_pct"])   # 첫해는 평균 자본을 못 구함

    def test_missing_cumulative_period_is_not_guessed(self):
        periods = self.make()
        del periods[(2025, 6)]
        _, halves, quarters = fin.build_tables(periods)
        kinds = {(r["year"], r["kind"]) for r in quarters}
        self.assertNotIn((2025, "Q2"), kinds)
        self.assertNotIn((2025, "Q3"), kinds)
        self.assertIn((2025, "Q4"), kinds)
        self.assertNotIn((2025, "H2"), {(r["year"], r["kind"]) for r in halves})

    def test_amended_report_is_flagged_on_derived_rows(self):
        periods = self.make()
        periods[(2025, 12)]["report_name"] = "[기재정정]사업보고서 (2025.12)"
        _, _, quarters = fin.build_tables(periods)
        q4 = [r for r in quarters if (r["year"], r["kind"]) == (2025, "Q4")][0]
        self.assertTrue(any("정정" in w for w in q4["warnings"]))

    def test_ttm_needs_four_consecutive_quarters(self):
        _, _, quarters = fin.build_tables(self.make())
        total, last4 = fin.ttm(quarters, "revenue")
        self.assertEqual(total, 140)
        self.assertEqual([r["kind"] for r in last4], ["Q1", "Q2", "Q3", "Q4"])
        gap = [r for r in quarters if (r["year"], r["kind"]) != (2025, "Q2")]
        self.assertEqual(fin.ttm(gap, "revenue"), (None, None))

    def test_filing_selection(self):
        filings = [{"report_nm": "사업보고서 (2024.12)", "rcept_no": "20250301000001", "rm": ""},
                   {"report_nm": "[기재정정]사업보고서 (2024.12)", "rcept_no": "20251017000001", "rm": "정"},
                   {"report_nm": "분기보고서 (2025.03)", "rcept_no": "20250515000001", "rm": ""},
                   {"report_nm": "분기보고서 (2025.06)", "rcept_no": "20250814000001", "rm": ""},
                   {"report_nm": "사업보고서 (2009.12)", "rcept_no": "20100331000001", "rm": ""}]
        latest = agent.latest_by_period(filings, 2010)
        self.assertEqual(latest[(2024, 12)]["rcept_no"], "20251017000001")
        self.assertIn((2025, 3), latest)
        self.assertNotIn((2025, 6), latest)      # '분기보고서 (2025.06)'은 형식이 맞지 않음
        self.assertNotIn((2009, 12), latest)
        self.assertIsNone(agent.period_of({"report_nm": "반기보고서 (2025.06)", "rm": "철"}))

    def test_next_run_is_first_of_next_month(self):
        self.assertEqual(fin.next_run_date(date(2026, 10, 12)), date(2026, 11, 1))
        self.assertEqual(fin.next_run_date(date(2026, 12, 1)), date(2027, 1, 1))


LEGACY_XML = """<DOCUMENT><TABLE-GROUP ACLASS="{XBRL}IS">
<TABLE><TR><TD>연결 손익계산서</TD></TR>
<TR><TD>제 62 기 3분기 2011.01.01 부터 2011.09.30 까지</TD></TR>
<TR><TD>제 61 기 3분기 2010.01.01 부터 2010.09.30 까지</TD></TR>
<TR><TD>(단위 : 백만원)</TD></TR></TABLE>
<TABLE><THEAD><TR><TH>과 목</TH><TH COLSPAN="2">제 62 기 3분기</TH><TH COLSPAN="2">제 61 기 3분기</TH></TR>
<TR><TH>3개월</TH><TH>누적</TH><TH>3개월</TH><TH>누적</TH></TR></THEAD>
<TBODY><TR><TD>Ⅰ. 매출액</TD><TD>3,000</TD><TD>9,000</TD><TD>2,500</TD><TD>8,000</TD></TR>
<TR><TD>Ⅱ. 매출원가</TD><TD>2,700</TD><TD>8,100</TD><TD>2,300</TD><TD>7,200</TD></TR>
<TR><TD>판매비와관리비</TD><TD>(100)</TD><TD>(300)</TD><TD>(90)</TD><TD>(280)</TD></TR>
<TR><TD>Ⅲ. 영업이익</TD><TD>200</TD><TD>600</TD><TD>110</TD><TD>520</TD></TR></TBODY></TABLE>
</TABLE-GROUP>
<TABLE-GROUP ACLASS="{XBRL}IS_S">
<TABLE><TR><TD>손익계산서</TD></TR><TR><TD>제 62 기 3분기 2011.01.01 부터 2011.09.30 까지</TD></TR>
<TR><TD>(단위 : 백만원)</TD></TR></TABLE>
<TABLE><TBODY><TR><TD>매출액</TD><TD>1</TD></TR></TBODY></TABLE></TABLE-GROUP></DOCUMENT>"""


class LegacyDocuments(unittest.TestCase):
    def test_reads_cumulative_columns_of_consolidated_statement_only(self):
        found = legacy.parse_document(LEGACY_XML)
        by_period = {p: v for p, kind, v, _ in found}
        self.assertEqual(set(by_period), {(2011, 9), (2010, 9)})      # 별도(IS_S)·3개월 열은 읽지 않음
        self.assertEqual(by_period[(2011, 9)]["revenue"], 9_000 * 1_000_000)
        self.assertEqual(by_period[(2010, 9)]["operating_profit"], 520 * 1_000_000)
        self.assertEqual(by_period[(2011, 9)]["sga"], 300 * 1_000_000)  # (괄호) 비용은 양수로

    def test_cp949_documents_are_decoded(self):
        text = "연결 재무상태표"
        self.assertEqual(legacy.decode(text.encode("cp949")), text)
        self.assertEqual(legacy.decode(text.encode("utf-8")), text)


class RealData(unittest.TestCase):
    """저장소에 보관된 실제 공시 자료로 항상 성립해야 하는 관계를 확인합니다."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = agent.company_config()
        status = {"checked_at": "2026-10-12T09:17:00+09:00", "mode": "offline", "errors": [], "new_filings": []}
        cls.ctx, cls.periods = agent.make_context(cls.cfg, date(2026, 10, 12), status, log=[])
        if not cls.ctx["annual"]:
            raise unittest.SkipTest("아직 수집된 자료가 없습니다(첫 실행 전)")

    def test_coverage_starts_in_first_year(self):
        if self.ctx["archives"] < self.ctx["filing_count"]:
            self.skipTest("공시 원문 ZIP을 아직 다 받지 않았습니다(첫 실행 전)")
        annual = self.ctx["annual"]
        self.assertEqual(annual[0]["year"], self.cfg["first_year"])
        self.assertGreaterEqual(len(annual), 16)
        self.assertTrue(self.ctx["halves"] and self.ctx["quarters"])

    def test_four_quarters_add_up_to_the_year(self):
        q = {(r["year"], r["kind"]): r for r in self.ctx["quarters"]}
        checked = 0
        for row in self.ctx["annual"]:
            parts = [q.get((row["year"], k)) for k in ("Q1", "Q2", "Q3", "Q4")]
            if None in parts:
                continue
            for field in ("revenue", "operating_profit", "operating_cashflow"):
                vals = [p["values"].get(field) for p in parts]
                if None in vals or row["values"].get(field) is None:
                    continue
                self.assertEqual(sum(vals), row["values"][field], f"{row['year']} {field}")
                checked += 1
        self.assertGreaterEqual(checked, 20)

    def test_balance_sheet_identity(self):
        for row in self.ctx["annual"]:
            gap = fin.balance_gap(row["values"])
            if gap is not None:
                self.assertLessEqual(abs(gap), max(abs(row["values"]["assets"]) * 1e-5, 5_000_000), row["label"])

    def test_original_document_extraction_matches_api(self):
        lg = self.ctx["legacy"]
        if lg["checked"]:
            self.assertGreaterEqual(lg["matched"] / lg["checked"], 0.98)

    def test_expenses_are_positive(self):
        for row in self.ctx["annual"]:
            for field in ("cost_of_sales", "sga"):
                if row["values"].get(field) is not None:
                    self.assertGreater(row["values"][field], 0, f"{row['label']} {field}")

    def test_dashboard_and_readme_render(self):
        page = dashboard.render(self.ctx)
        for anchor in ('id="annual"', 'id="half"', 'id="quarter"', 'id="peers"', 'id="fig-revenue"'):
            self.assertIn(anchor, page)
        self.assertLess(page.index('id="quarter"'), page.index('id="peers"'))   # 동종업계 표는 맨 아래
        self.assertNotIn("None", page.split("<script>")[0].replace("NoneType", ""))
        with tempfile.TemporaryDirectory() as tmp:
            readme = Path(tmp) / "README.md"
            readme.write_text("top\n<!-- AUTO:SUMMARY:START -->\nold\n<!-- AUTO:SUMMARY:END -->\n"
                              "## Peer\n<!-- AUTO:PEERS:START -->\n<!-- AUTO:PEERS:END -->\n", encoding="utf-8")
            self.assertTrue(dashboard.update_readme(readme, self.ctx))
            text = readme.read_text(encoding="utf-8")
            self.assertNotIn("old", text)
            self.assertIn("| 관점 | 판정 | 근거 |", text)
            self.assertIn("시평 순위", text)
            self.assertFalse(dashboard.update_readme(readme, self.ctx))   # 두 번째는 바뀌는 것이 없음


class Packaging(unittest.TestCase):
    def test_workflow_schedule_and_secret(self):
        wf = ROOT / ".github" / "workflows" / "financial-agent.yml"
        if not wf.exists():
            wf = ROOT / "workflows" / "financial-agent.yml"     # 제출 ZIP을 푼 경우
        text = wf.read_text(encoding="utf-8")
        self.assertIn("cron: '17 0 1 * *'", text)
        self.assertIn("workflow_dispatch", text)
        self.assertIn("secrets.DART_API_KEY", text)
        self.assertNotIn("\t", text)

    def test_zip_has_no_hidden_files(self):
        if not (ROOT / ".github" / "workflows").is_dir():
            self.skipTest("제출 ZIP을 푼 폴더에서는 .github이 없습니다")
        import package_project
        with tempfile.TemporaryDirectory() as tmp:
            out, names = package_project.build(Path(tmp) / "test.zip")
            self.assertTrue(zipfile.is_zipfile(out))
        self.assertFalse([n for n in names if any(p.startswith(".") for p in Path(n).parts)])
        self.assertIn("workflows/financial-agent.yml", names)
        self.assertFalse([n for n in names if n.startswith("data/financials/raw/") and n.endswith(".zip")])


if __name__ == "__main__":
    unittest.main()
