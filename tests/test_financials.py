"""계산 규칙 테스트 (네트워크 없이 실행).

GitHub Actions가 매달 수집 전에 먼저 실행합니다. 새 공시가 나와 숫자가 바뀌어도 깨지지 않도록,
실제 자료에 대해서는 '항상 성립해야 하는 관계'(분기 합 = 연간, 자산 = 부채 + 자본 등)만 확인합니다.
"""
import contextlib
import io
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import analysis  # noqa: E402
import business  # noqa: E402
import company_report  # noqa: E402
import dart_agent as agent  # noqa: E402
import dashboard  # noqa: E402
import drivers  # noqa: E402
import financials as fin  # noqa: E402
import legacy  # noqa: E402
import lenses  # noqa: E402
import market  # noqa: E402
import notes  # noqa: E402
import research  # noqa: E402
import statements  # noqa: E402


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

    def test_price_date_label(self):
        # 끝난 달은 '월말', 아직 끝나지 않은 달은 받은 날짜로 적습니다
        self.assertEqual(analysis.price_when({"as_of": "2026.09", "fetched": "2026-10-01"}), "2026.09 월말")
        self.assertEqual(analysis.price_when({"as_of": "2026.10", "fetched": "2026-10-26"}), "2026.10.26")

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
            # 2010~2014년 숫자는 공시 원문 ZIP의 표에서 읽습니다. 제출 ZIP에는 용량 때문에 원문이 빠져 있어(첫 실행 때 다시 받음) 건너뜁니다.
            self.skipTest("공시 원문 ZIP(data/financials/raw)이 없는 환경: 2010~2014년 숫자는 원문에서 읽습니다")
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

    def test_six_steps_in_guide_order(self):
        steps = self.ctx["analysis"]["steps"]
        self.assertEqual([s["id"] for s in steps], ["growth", "profit", "cash", "debt", "returns", "valuation"])
        for s in steps:
            self.assertTrue(s["answer"])
            self.assertIn(s["verdict"][0], ("good", "warn", "crit", "info"))
        self.assertEqual(len(self.ctx["analysis"]["combos"]), 8)

    def test_ebitda_and_interest_from_notes(self):
        if self.ctx["archives"] < self.ctx["filing_count"]:
            # 감가상각비·이자비용은 현금흐름표 주석(원문 ZIP)에서 읽습니다. 제출 ZIP에는 원문이 없어 건너뜁니다.
            self.skipTest("공시 원문 ZIP(data/financials/raw)이 없는 환경: EBITDA의 감가상각비는 주석 원문에서 읽습니다")
        recent = [r for r in self.ctx["annual"] if r["year"] >= 2015]
        self.assertTrue(recent)
        for r in recent:
            v = r["values"]
            self.assertIsNotNone(v.get("ebitda"), r["label"])
            self.assertGreater(v["dep_amort"], 0)
            self.assertLess(v["dep_amort"], v["revenue"] * 0.05)   # 건설사 감가상각비는 매출의 몇 % 미만

    def test_dashboard_and_readme_render(self):
        page = dashboard.render(self.ctx)
        for anchor in ('id="annual"', 'id="half"', 'id="quarter"', 'id="peers"', 'id="fig-revenue"', 'id="stability"',
                       'id="dupont"', 'id="market"', 'id="combos"', 'id="fig-returns"', 'id="fig-coverage"', 'id="fig-cash"'):
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
            self.assertIn("| 단계 | 판정 | 한 줄 답 |", text)
            self.assertIn("시평 순위", text)
            self.assertFalse(dashboard.update_readme(readme, self.ctx))   # 두 번째는 바뀌는 것이 없음


    def test_business_report_numbers(self):
        """사업보고서 본문에서 읽은 숫자(수주잔고·PF 보증·신규 수주·직원·사업부문)가 공시 문장과 맞는지.
        원문 ZIP이 없는 환경(제출 ZIP을 푼 폴더)에서는 저장된 data/financials/business.json으로 확인합니다."""
        biz = self.ctx["business"]
        if not biz.get("backlog"):
            self.skipTest("사업보고서 본문에서 읽은 숫자(business.json)가 아직 없습니다(첫 실행 전)")
        self.assertFalse(biz.get("errors"))
        backlog = {r["period"]: r for r in biz["backlog"]}
        # 보고서가 직접 적은 연결기준 수주잔고와 회사별 합계는 내부거래만큼(1% 안팎)만 다릅니다
        for period in ("2024.12", "2025.12"):
            r = backlog[period]
            self.assertIsNotNone(r["consolidated"])
            self.assertLess(abs(r["total"] - r["consolidated"]) / r["consolidated"], 0.01)
            split = (r["domestic"] or 0) + (r["overseas"] or 0)    # 국내·해외 구분이 없는 작은 회사 표만큼만 모자랄 수 있음
            self.assertLessEqual(split, r["total"])
            self.assertGreater(split / r["total"], 0.98)
        self.assertEqual(backlog["2025.12"]["consolidated"], 95_038_562 * 1_000_000)
        self.assertTrue(backlog["2021.12"].get("flag"))          # 앞뒤 보고서와 범위가 다른 값은 표시
        self.assertEqual(biz["pf"]["2025.12"]["amount"], 13_940_533 * 1_000_000)
        self.assertEqual(biz["pf"]["2022.12"]["amount"], 9_567_709 * 1_000_000)   # 다음 해 보고서의 전기말
        self.assertEqual(biz["orders"]["2025"]["total"], 25_515_100_000_000)
        self.assertEqual(biz["orders"]["2025"]["domestic"] + biz["orders"]["2025"]["overseas"], 25_515_100_000_000)
        self.assertEqual(biz["employees"]["2025"]["count"], 6900)
        seg = biz["segments"]
        rev = next(r for r in self.ctx["annual"] if r["year"] == seg["year"])["values"]["revenue"]
        self.assertEqual(seg["total"][0], rev)                    # 사업부문 표 합계 = 연결 매출액
        parts = sum((x["domestic"] or [0])[0] + (x["overseas"] or [0])[0] for x in seg["rows"])
        self.assertEqual(parts + seg["internal"][0], seg["total"][0])
        self.assertGreaterEqual(len(biz["projects"]["rows"]), 5)
        for pj in biz["projects"]["rows"]:
            self.assertLessEqual(pj["done"], pj["contract"] * 1.05)

    def test_dashboard_is_financial_statements(self):
        """대시보드 = 재무제표: 위쪽 그래프(요약 → 이번 달 → 재무제표 10년 → 10가지 관점) → 아래쪽 표 → 맨 아래 동종업계."""
        page = dashboard.render(self.ctx)
        ids = ["summary", "now", "is", "bs", "cf", "lenses"] + [x["id"] for x in lenses.LENSES] + ["combos", "annual", "half",
                                                                                                    "quarter", "notes", "peers"]
        order = [page.index(f'<section id="{x}"') if f'<section id="{x}"' in page else page.index(f'id="{x}"') for x in ids]
        self.assertEqual(order, sorted(order))
        for gone in ('id="structure"', 'id="orders"', 'id="fig-backlog"', "../statements/"):    # 사업보고서 부분은 PDF로
            self.assertNotIn(gone, page)
        self.assertIn('href="../reports/hyundai-company-report.pdf"', page)
        for step, lens in lenses.LENS_OF_STEP.items():      # 가이드 6단계 카드는 짝이 되는 관점으로 연결
            self.assertIn(f'href="#{lens}"', page)
        self.assertIn('class="table-scroll heat"', page)
        self.assertEqual(page.count("가이드 판정 · "), 6)
        self.assertNotIn("None", page.split("<script>")[0].replace("NoneType", ""))

    def test_old_statements_address_redirects(self):
        page = statements.redirect_page(self.ctx)
        self.assertIn('url=../dashboard/#is', page)
        self.assertIn('location.replace("../dashboard/"+h)', page)

    def test_company_report_html(self):
        import re
        html = company_report.build_html(self.ctx)
        chapters = ("summary", "ch1", "ch2", "ch3", "ch4", "ch5", "ch6", "ch7", "ch8", "ch9", "ch10", "appendix")
        found = re.findall(r'<section class="r-chap[^"]*" id="([^"]+)"', html)
        self.assertEqual(found, list(chapters))                   # 장이 모두, 이 순서로 (한 장이 실패하면 빠짐)
        nums = [int(n) for n in re.findall(r'<span class="fig-no">그림 (\d+)</span>', html)]
        self.assertEqual(nums, list(range(1, len(nums) + 1)))      # 그림 번호는 1부터 빠짐없이
        self.assertGreaterEqual(len(nums), 18)
        self.assertNotIn("<h3>", html.split("<body>")[1].split('class="r-sec')[0])     # 표지·요약 제목만 책갈피에
        body = html.split("<body>")[1]
        self.assertNotIn("None", body)
        self.assertIsNone(re.search(r"(?<![\w-])(nan|inf)(?![\w-])", body, re.I))
        self.assertIsNone(re.search(r"&lt;/?(span|a|b|p|br)\b", body))     # 태그가 글자로 새어 나오지 않음
        self.assertEqual(html, company_report.build_html(self.ctx))     # 같은 자료면 같은 글자(해시 비교로 PDF 재인쇄 판단)
        self.assertIn("2026년 10월판", html)
        # 근거 표시는 모두 배지로 바뀌고 [공시] 같은 글자가 그대로 남지 않습니다
        text = re.sub(r"<[^>]+>", " ", body)
        self.assertIsNone(re.search(r"\[(공시|계산|가정|보도|해석)[^\]]{0,30}\]", text))
        for cls in ("ev-d", "ev-c", "ev-a", "ev-n", "ev-h"):
            self.assertIn(f'class="ev {cls}"', body)
        # 숫자 뒤 조사(…조가/…억으로)가 받침에 맞는지
        bad = []
        for m in re.finditer(r"\d(조|억|원|배|%)(이|가|을|를|은|는|으로|로)(?=[\s.,)])", text):
            final = m.group(1) in ("억", "원")
            ok = {"이": final, "가": not final, "을": final, "를": not final, "은": final, "는": not final,
                  "으로": final, "로": not final}[m.group(2)]
            if not ok:
                bad.append(text[max(0, m.start() - 20):m.end()])
        self.assertEqual(bad, [])
        self.assertEqual(html.count('class="yc"'), 10 + (1 if company_report.half_after(self.ctx, company_report.facts(self.ctx)) else 0))

    def test_research_identities(self):
        """원인 분해는 회계 항등식이라 나머지 없이 맞아야 합니다. 원문 ZIP이 없으면 저장된 drivers.json으로 확인합니다."""
        if not (self.ctx.get("drivers") or {}).get("segments"):
            self.skipTest("사업보고서 주석에서 읽은 숫자(drivers.json)가 아직 없습니다(첫 실행 전)")
        R = research.build(self.ctx)
        self.assertEqual(len(R["years"]), 10)
        for b in R["bridges"] + [R["bridge_10y"]]:
            self.assertAlmostEqual(b["volume"] + b["cost"] + b["sga"] + b["other"], b["d_op"], delta=1)
            self.assertLess(abs(b["other"]), 1e9)                 # 현대건설은 영업이익 = 매출총이익 − 판관비 (기타 영업손익 없음)
        split = [r for r in R["entity"] if r["rest_op"] is not None]
        self.assertGreaterEqual(len(split), 9)
        for r in split:
            self.assertEqual(r["parent_op"] + r["hec_op"] + r["rest_op"], r["cons_op"])
        for r in R["alloc"]:
            self.assertAlmostEqual(sum(r[k] for k, _ in research.ALLOC), r["cash_change"], delta=1)
            self.assertLess(abs(r["other"]), 0.3e12)              # 분류하지 못한 현금 움직임은 작아야 함
        self.assertEqual(len(R["estimates"]), 10)
        for e in R["estimates"]:
            parts = [x for x in e["by_seg"].values() if x is not None]
            self.assertLess(abs(sum(parts) - e["current"]), max(abs(e["current"]) * 0.01, 2e9), e["year"])
        dr = self.ctx["drivers"]
        for y in R["years"]:
            seg = dr["segments"][str(y)]
            rev = next(r for r in self.ctx["annual"] if r["year"] == y)["values"]["revenue"]
            self.assertLess(abs(seg["revenue"]["total"] - rev) / rev, 0.005, y)
        self.assertEqual(dr["errors"], 0 if isinstance(dr["errors"], int) else [])
        # 원가 추정 변경 표: 총계약수익 변경 − 총계약원가 변경 = 당기 영향 + 미래 영향 (공시 표의 반올림 1백만원까지)
        for e in R["estimates"]:
            self.assertLessEqual(abs(e["identity_gap"]), 2_000_000, e["year"])
        # 영업활동현금흐름 = 순이익 + 조정 + 운전자본(주석) + 이자·배당·법인세(본문) — 재무제표 값과 같아야 함
        self.assertEqual([r["year"] for r in R["cash"]], R["years"])
        for r in R["cash"]:
            self.assertEqual(r["ni"] + r["adj_total"] + r["wc_total"], r["generated"], r["year"])
            self.assertLessEqual(abs(r["check"]), 2_000_000, r["year"])
            self.assertLessEqual(abs(r["ni_check"]), 2_000_000, r["year"])
            for key in ("trade_receivables", "contract_assets"):
                self.assertIn({"trade_receivables": "receivables", "contract_assets": "contract_assets"}[key], r["bs_delta"])
        for y, a in dr["receivable_aging"].items():
            self.assertEqual(sum(a["buckets"].values()) + a["allowance"], a["net"], y)
        for y, t in dr["revenue_types"].items():
            rev = next(r for r in self.ctx["annual"] if r["year"] == int(y))["values"]["revenue"]
            self.assertLessEqual(abs(t["total"] - rev), 2_000_000, y)
        # 회사가 공시한 민감도는 무엇에 대한 영향인지(원문 문구)와 범위를 함께 저장
        last = dr["sensitivity"][max(dr["sensitivity"])]
        self.assertEqual(last["rate"]["measure"], "법인세비용차감전순이익")
        self.assertEqual(last["fx"]["measure"], "순자산(법인세효과 차감전)")
        self.assertEqual(last["rate"]["scope"], "변동이자율 차입금")
        # 분해 방법을 바꿔도 합은 같고, 결론(원가율 효과 > 규모 효과)도 같아야 함
        for m in R["bridge_robust"]["methods"]:
            w = m["whole"]
            self.assertAlmostEqual(w["volume"] + w["cost"] + w["sga"] + w["other"], w["d_op"], delta=1)
            self.assertAlmostEqual(sum(m["abs_share"].values()), 100, places=6)
        for w in R["bridge_robust"]["windows"] + [m["whole"] for m in R["bridge_robust"]["methods"]]:
            self.assertGreater(abs(w["cost"]), abs(w["volume"]))
        # 검증표: '공시' 숫자는 접수번호가 있어야 하고, 접수번호는 보고서 이름·접수일로 찾아져야 함
        for v in R["verification"]:
            self.assertIn(v["kind"], ("공시", "계산"))
            if v["kind"] == "공시":
                self.assertTrue(v["receipts"], v["item"])
            for rc_, name, filed in v["sources"]:
                self.assertTrue(name and filed, (v["item"], rc_))

    def test_report_numbers_are_consistent(self):
        """표지 · 요약 · 본문 · 부록 검증표 · README가 같은 숫자를 같은 글자로 씁니다."""
        import re
        if not (self.ctx.get("drivers") or {}).get("cash_generated"):
            self.skipTest("현금흐름표 주석에서 읽은 숫자(drivers.json)가 아직 없습니다")
        html = company_report.build_html(self.ctx)
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.split("<body>")[1]))
        F = company_report.facts(self.ctx)
        R = F["R"]
        rows = {v["item"]: company_report.shown_value(v) for v in R["verification"]}
        cover = re.sub(r"<[^>]+>", " ", company_report.cover(self.ctx, F))
        summary = re.sub(r"<[^>]+>", " ", company_report.summary_page(self.ctx, F))
        ch6 = re.sub(r"<[^>]+>", " ", company_report.ch6_drivers(self.ctx, F))
        est = rows["2024년 원가 추정 변경의 그해 세전손익 영향"].replace(" 원", "")
        cfo_key = next(k for k in rows if k.endswith("영업활동현금흐름 합계"))
        cfo = rows[cfo_key].replace(" 원", "")
        wc = rows[next(k for k in rows if k.endswith("운전자본 변동 합계"))].replace(" 원", "")
        for part, name in ((summary, "요약"), (ch6, "6장")):
            for x in (est, cfo, wc):
                self.assertIn(x, part, (name, x))
        self.assertIn(est.replace("조", ""), cover)                  # 표지는 '−2.99 조 원'처럼 숫자와 단위를 나눠 씀
        self.assertIn(cfo.replace("조", ""), cover)
        for item, shown in rows.items():                              # 검증표의 표시값은 본문 어딘가에 같은 글자로 있어야 함
            self.assertGreaterEqual(text.count(shown.replace(" 원", "")), 2 if item != "연간 영업이익 변화 크기 중 원가율 효과의 몫" else 1, item)
        # 영업활동현금흐름 합계 = 대시보드·CSV의 연간 값(같은 ctx['annual'])을 더한 값
        w = next(x for x in R["cash_windows"] if x["start"] == R["alloc_split"])
        annual = {r["year"]: r["values"]["operating_cashflow"] for r in self.ctx["annual"]}
        self.assertEqual(sum(annual[y] for y in range(w["start"], w["end"] + 1)), w["cfo"])
        # README 자동 요약의 최근 영업활동현금흐름이 보고서와 같은 숫자
        with tempfile.TemporaryDirectory() as tmp:
            readme = Path(tmp) / "README.md"
            readme.write_text("<!-- AUTO:SUMMARY:START -->\n<!-- AUTO:SUMMARY:END -->\n<!-- AUTO:PEERS:START -->\n<!-- AUTO:PEERS:END -->\n",
                              encoding="utf-8")
            dashboard.update_readme(readme, self.ctx)
            readme_text = readme.read_text(encoding="utf-8")
        last_cfo = company_report.jo(annual[F["yl"]])
        self.assertIn(last_cfo.replace("조", ""), readme_text)
        self.assertIn(last_cfo, text)

    def test_review_flag_after_research_date(self):
        """조사 기준일 뒤에 새 공시가 접수되면 표지·요약에 '추가 검토 필요'를 띄우고, 아니면 띄우지 않습니다."""
        original = company_report.load_research
        lf = self.ctx["latest_filing"]
        before = f"{lf['rcept_dt'][:4]}-{lf['rcept_dt'][4:6]}-01"
        try:
            company_report.load_research = lambda path=None: {**original(), "as_of": before}
            F = company_report.facts(self.ctx)
            self.assertTrue(F["review"])
            self.assertIn("추가 검토 필요", company_report.summary_page(self.ctx, F))
            self.assertIn("추가 검토 필요", company_report.cover(self.ctx, F))
            company_report.load_research = lambda path=None: {**original(), "as_of": "2099-12-31"}
            F = company_report.facts(self.ctx)
            self.assertEqual(F["review"], [])
            self.assertNotIn("추가 검토 필요", company_report.summary_page(self.ctx, F))
        finally:
            company_report.load_research = original

    def test_report_without_new_note_data(self):
        """새로 읽는 주석(현금흐름표 주석·매출채권·수익의 구분)이 없는 해·환경에서도 보고서가 만들어지고 빈 값이 새지 않습니다."""
        import copy
        ctx = copy.copy(self.ctx)
        ctx["drivers"] = {k: v for k, v in self.ctx["drivers"].items()
                          if k not in ("cash_generated", "receivable_aging", "receivable_mix", "revenue_types")}
        html = company_report.build_html(ctx)
        body = html.split("<body>")[1]
        self.assertNotIn("None", body)
        self.assertIn('id="ch6"', body)
        self.assertIn("영업활동현금흐름 합계", body)          # 요약은 합계 비교로 대신함

    def test_timeline_marks_unresearched_years(self):
        """조사하지 않은 연도는 '조사 전'으로 표시하고 숫자·회사 설명만 자동으로 채웁니다."""
        original = company_report.load_research
        company_report.load_research = lambda path=None: {k: v for k, v in original().items() if k != "events"}
        try:
            F = company_report.facts(self.ctx)
            html = company_report.ch7_timeline(self.ctx, F)
        finally:
            company_report.load_research = original
        self.assertGreaterEqual(html.count("조사 전"), 10)
        self.assertIn("회사 설명", html)


    def test_dupont_identity(self):
        L = {x["id"]: x for x in lenses.build(self.ctx)}["dupont"]
        m = {x["key"]: x["values"] for x in L["metrics_data"]}
        checked = 0
        for roe, nm, at, lev in zip(m["roe_pct"], m["net_margin_pct"], m["asset_turnover_x"], m["leverage_x"]):
            if None in (roe, nm, at, lev):
                continue
            self.assertAlmostEqual(nm * at * lev, roe, places=6)
            checked += 1
        self.assertGreaterEqual(checked, 8)


class BusinessParsing(unittest.TestCase):
    """사업보고서 본문 읽기 규칙 (작은 예시 문서)."""

    def test_korean_amount(self):
        self.assertEqual(business.korean_amount("25조 5,151억원"), 25_515_100_000_000)
        self.assertEqual(business.korean_amount("12조 8천억원"), 12_800_000_000_000)
        self.assertEqual(business.korean_amount("4.9조원"), 4_900_000_000_000)
        self.assertEqual(business.korean_amount("8조 733억원"), 8_073_300_000_000)
        self.assertEqual(business.korean_amount("9,000억원"), 900_000_000_000)
        self.assertIsNone(business.korean_amount("약 3년"))

    def table(self, rows):
        trs = "".join("<TR>" + "".join(f"<TD>{c}</TD>" for c in r) + "</TR>" for r in rows)
        return f"<TABLE>{trs}</TABLE>"

    def test_backlog_sums_company_tables_and_reads_consolidated_sentence(self):
        head = ["구분", "공사명", "발주처", "공사착공일", "완공예정일", "기본도급액", "완성공사액", "계약잔액"]
        a = self.table([head, ["국내", "A현장", "갑", "2024-01-01", "2027-01-01", "1,000", "400", "600"],
                        ["국내합계", "1,000", "400", "600"], ["해외", "B현장", "을", "2023-01-01", "2028-01-01", "2,000", "500", "1,500"],
                        ["해외합계", "2,000", "500", "1,500"]])
        b = self.table([head, ["국내", "C현장", "병", "2025-01-01", "2026-12-31", "300", "100", "200"], ["국내/해외 합계", "300", "100", "200"]])
        xml = (f"<P>4. 매출 및 수주상황</P><P>다. 수주상황</P><P>1) 현대건설</P><P>(단위 : 백만원)</P>{a}"
               f"<P>2) 현대엔지니어링</P>{b}<P>연결기준 계약잔액은 2,250백만원입니다.</P><TITLE>5. 위험관리 및 파생거래</TITLE>")
        got = business.parse_backlog(xml)
        self.assertEqual(got["total"], 2_300 * 1_000_000)
        self.assertEqual(got["domestic"], 600 * 1_000_000)
        self.assertEqual(got["overseas"], 1_500 * 1_000_000)
        self.assertEqual(got["consolidated"], 2_250 * 1_000_000)
        self.assertEqual([c["name"] for c in got["companies"]], ["현대건설", "현대엔지니어링"])
        projects = business.parse_projects(xml)
        self.assertEqual([p["name"] for p in projects], ["A현장", "B현장", "C현장"])
        self.assertEqual(projects[1]["client"], "을")
        self.assertEqual(projects[1]["remain"], 1_500 * 1_000_000)

    def test_incomplete_company_table_leaves_total_empty(self):
        head = ["구분", "공사명", "발주처", "공사착공일", "완공예정일", "기본도급액", "완성공사액", "계약잔액"]
        a = self.table([head, ["국내합계", "1,000", "400", "600"]])
        xml = f"<P>수주상황</P><P>(단위 : 백만원)</P>{a}<TITLE>5. 위험관리</TITLE>"
        self.assertIsNone(business.parse_backlog(xml)["total"])

    def test_pf_takes_consolidated_sentence(self):
        xml = ("<P>회사는 PF(대출)과 관련하여 보증금액 기준 13,940,533백만원 (전기말 12,816,602백만원)의 신용보강을 제공</P>"
               "<P>회사는 PF(대출)과 관련하여 보증금액 기준 12,843,503백만원 (전기말 11,000,000백만원)의 신용보강</P>")
        self.assertEqual(business.parse_pf(xml), {"current": 13_940_533_000_000, "prior": 12_816_602_000_000})

    def test_new_orders_sentences(self):
        new = "<P>나. 지배회사 현황 [현대건설] 2025년 당사는 국내 20조 972억원, 해외 5조 4,179억원, 총 25조 5,151억원의 수주실적(별도기준)을 기록하였습니다.</P>"
        got = business.parse_new_orders(new)
        self.assertEqual((got["total"], got["domestic"], got["overseas"]), (25_515_100_000_000, 20_097_200_000_000, 5_417_900_000_000))
        old = ("<P>◎ 현대건설 2012년 당사는 전년대비 33% 증가한 15조 6,227억원을 수주하며 개선된 실적을 기록하였습니다. "
               "국내부문에서는 경기침체에 따라 전년대비 감소한 4조 8,374억원을 수주하였으나, 해외부문에서는 전년대비 2배 이상 증가한 "
               "10조 7,853억원의 수주실적을 기록하였습니다.</P>")
        got = business.parse_new_orders(old)
        self.assertEqual(got["total"], 15_622_700_000_000)
        self.assertEqual(got["domestic"] + got["overseas"], 15_622_700_000_000)

    def test_employee_total_row(self):
        xml = ("<P>직원 등 현황</P>" + self.table([["사업부문", "성별", "직원수", "평균근속연수", "연간급여 총액", "1인평균 급여액"],
                                                 ["합 계", "4,624", "3", "2,272", "1", "6,900", "13.9", "810,669", "112", "-"]]))
        got = business.parse_employees(xml)
        self.assertEqual(got["count"], 6900)
        self.assertEqual(got["avg_salary"], 112_000_000)


class GuideRatios(unittest.TestCase):
    """교수님 가이드(재무제표·재무비율 실무가이드)의 정의대로 계산하는지 확인합니다."""

    def make(self):
        periods = {}
        for year, k in ((2024, 1.0), (2025, 1.2)):
            periods[(year, 12)] = period(
                year, 12, revenue=int(1000 * k), cost_of_sales=int(900 * k), gross_profit=int(100 * k), sga=int(40 * k),
                operating_profit=int(60 * k), net_income=int(40 * k), net_income_owners=int(36 * k),
                pretax_income=int(50 * k), income_tax=int(12 * k), assets=int(2000 * k), liabilities=int(1200 * k),
                equity=int(800 * k), equity_owners=int(700 * k), current_assets=int(1500 * k), current_liabilities=int(1000 * k),
                cash=int(300 * k), inventories=int(100 * k), trade_receivables=int(200 * k), trade_payables=int(150 * k),
                short_term_borrowings=int(100 * k), current_portion_ltd=int(50 * k), bonds=int(100 * k),
                long_term_borrowings=int(150 * k), operating_cashflow=int(30 * k), investing_cashflow=int(-20 * k),
                financing_cashflow=int(10 * k), capex_ppe=int(15 * k), capex_intangible=int(5 * k),
                dep_amort=int(20 * k), interest_expense=int(10 * k))
        return periods

    def test_derived_values(self):
        annual, _, _ = fin.build_tables(self.make())
        v = annual[0]["values"]
        self.assertEqual(v["borrowings_total"], 400)
        self.assertEqual(v["net_debt"], 100)            # 이자부차입금 400 − 현금 300
        self.assertEqual(v["capex"], 20)
        self.assertEqual(v["fcf"], 10)                  # 영업현금흐름 30 − CAPEX 20
        self.assertEqual(v["ebitda"], 80)               # 영업이익 60 + 감가상각비 20
        self.assertEqual(v["quick_assets"], 1400)
        self.assertEqual(v["nci_equity"], 100)

    def test_ratios(self):
        annual, _, _ = fin.build_tables(self.make())
        r0, r1 = annual[0]["ratios"], annual[1]["ratios"]
        self.assertAlmostEqual(r0["ebitda_margin_pct"], 8.0)
        self.assertAlmostEqual(r0["quick_ratio_pct"], 140.0)
        self.assertAlmostEqual(r0["borrowing_dependency_pct"], 20.0)
        self.assertAlmostEqual(r0["interest_coverage_x"], 6.0)
        self.assertAlmostEqual(r0["net_debt_to_ebitda_x"], 1.25)
        self.assertAlmostEqual(r0["cfo_to_ni_x"], 0.75)
        self.assertIsNone(r0["roic_pct"])               # 첫해는 평균 투하자본이 없음
        # 2025년: 평균 매출채권 220, 매출 1200 → DSO = 220 / 1200 × 365
        self.assertAlmostEqual(r1["dso_days"], 220 / 1200 * 365)
        self.assertAlmostEqual(r1["dio_days"], 110 / 1080 * 365)
        self.assertAlmostEqual(r1["dpo_days"], 165 / 1080 * 365)
        self.assertAlmostEqual(r1["ccc_days"], r1["dso_days"] + r1["dio_days"] - r1["dpo_days"])
        self.assertAlmostEqual(r1["asset_turnover_x"], 1200 / 2200)
        # ROIC = 영업이익 × (1 − 실효세율) ÷ 평균(자본 + 순차입금)
        tax = 14 / 60
        ic = ((800 + 100) + (960 + 120)) / 2
        self.assertAlmostEqual(r1["roic_pct"], 72 * (1 - tax) / ic * 100)
        self.assertAlmostEqual(r1["roe_owners_pct"], 43 / 770 * 100)

    def test_cfo_to_ni_needs_positive_income(self):
        periods = self.make()
        periods[(2025, 12)]["values"]["net_income"] = -5
        annual, _, _ = fin.build_tables(periods)
        self.assertIsNone(annual[1]["ratios"]["cfo_to_ni_x"])

    def test_market_valuation(self):
        values = {"equity_owners": 1000, "net_debt": 200, "nci_equity": 50}
        val = market.valuation(10, {"common": 90, "preferred": 10}, values, ebitda=125, net_income_owners=100, fcf=-20)
        self.assertEqual(val["market_cap"], 1000)       # 10원 × 100주
        self.assertAlmostEqual(val["per_x"], 10)
        self.assertAlmostEqual(val["pbr_x"], 1)
        self.assertAlmostEqual(val["ev_ebitda_x"], (1000 + 200 + 50) / 125)
        self.assertAlmostEqual(val["fcf_yield_pct"], -2)
        self.assertNotIn("per_x", market.valuation(10, {"common": 100}, values, net_income_owners=-5))
        self.assertEqual(market.valuation(None, {"common": 100}, values), {})

    def test_month_close_and_shares(self):
        prices = {"202512": 30000.0, "202510": 28000.0}
        self.assertEqual(market.month_close(prices, 2025, 12), (30000.0, "2025.12"))
        self.assertEqual(market.month_close(prices, 2025, 11), (28000.0, "2025.10"))
        doc = {"list": [{"se": "보통주", "istc_totqy": "111,355,765"}, {"se": "우선주", "istc_totqy": "232,586"},
                        {"se": "합계", "istc_totqy": "111,588,351"}]}
        self.assertEqual(market.parse_shares(doc), {"common": 111355765, "preferred": 232586})


NOTE_XML = """<DOCUMENT><DOCUMENT-NAME>사업보고서</DOCUMENT-NAME>
<TITLE>3. 연결재무제표 주석</TITLE>
<P>34. 현금흐름표 (1) 당기 및 전기 중 영업으로부터 창출된 현금은 다음과 같습니다. (단위:백만원)</P>
<TABLE><TR><TD>과목</TD><TD>당기</TD><TD>전기</TD></TR>
<TR><TD>유형자산감가상각비</TD><TD>100</TD><TD>90</TD></TR>
<TR><TD>사용권자산상각비</TD><TD>50</TD><TD>40</TD></TR>
<TR><TD>무형자산상각비</TD><TD>10</TD><TD>8</TD></TR>
<TR><TD>이자비용</TD><TD>30</TD><TD>25</TD></TR></TABLE>
<TITLE>5. 재무제표 주석</TITLE>
<P>33. 현금흐름표 영업으로부터 창출된 현금 (단위:백만원)</P>
<TABLE><TR><TD>감가상각비</TD><TD>7</TD><TD>6</TD></TR><TR><TD>이자비용</TD><TD>3</TD><TD>2</TD></TR></TABLE>
</DOCUMENT>"""


class NoteParsing(unittest.TestCase):
    def test_consolidated_cash_flow_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "20990101000001.zip"
            with zipfile.ZipFile(path, "w") as zf:
                zf.writestr("20990101000001.xml", NOTE_XML.encode("utf-8"))
            got = notes.parse(path, "20990101000001")
        self.assertEqual(got["current"]["dep_amort"], 160 * 1_000_000)   # 별도 주석(7)이 아니라 연결 주석
        self.assertEqual(got["current"]["interest_expense"], 30 * 1_000_000)
        self.assertEqual(got["prior"]["dep_amort"], 138 * 1_000_000)

    def test_new_label_style(self):
        self.assertEqual(notes._row_key("감가상각비에 대한 조정"), "dep_ppe")
        self.assertEqual(notes._row_key("사용권자산감가상각비 조정"), "dep_rou")
        self.assertEqual(notes._row_key("무형자산상각비에 대한 조정"), "amort")
        self.assertIsNone(notes._row_key("대손상각비"))


class CompanyReportPrinting(unittest.TestCase):
    """PDF 인쇄 단계: Chrome·한글 글꼴이 없으면 건너뛰고, 내용이 같으면 다시 인쇄하지 않습니다(Chrome 없이 확인)."""
    _ctx = None

    def ctx(self):
        if CompanyReportPrinting._ctx is None:
            cfg = agent.company_config()
            status = {"checked_at": "2026-10-12T09:17:00+09:00", "mode": "offline", "errors": [], "new_filings": []}
            CompanyReportPrinting._ctx, _ = agent.make_context(cfg, date(2026, 10, 12), status, log=[])
        if not CompanyReportPrinting._ctx["annual"]:
            self.skipTest("아직 수집된 자료가 없습니다")
        return CompanyReportPrinting._ctx

    def test_skips_without_chrome_and_keeps_old_pdf(self):
        ctx = self.ctx()
        original = company_report.find_chrome
        company_report.find_chrome = lambda: None
        try:
            with tempfile.TemporaryDirectory() as tmp, contextlib.redirect_stdout(io.StringIO()):   # 경고 줄이 Actions 주석으로 남지 않게
                msg = company_report.write(ctx, tmp)
                self.assertIn("건너뜀", msg)
                self.assertFalse((Path(tmp) / company_report.PDF_PATH).exists())
        finally:
            company_report.find_chrome = original

    def test_same_content_is_not_printed_again(self):
        ctx = self.ctx()
        html = company_report.build_html(ctx)
        digest = __import__("hashlib").sha256(html.encode("utf-8")).hexdigest()
        original = company_report.print_pdf
        company_report.print_pdf = lambda *a, **k: self.fail("내용이 같으면 인쇄하지 않아야 합니다")
        try:
            with tempfile.TemporaryDirectory() as tmp:
                pdf = Path(tmp) / company_report.PDF_PATH
                pdf.parent.mkdir(parents=True)
                pdf.write_bytes(b"%PDF-1.4 old")
                state = Path(tmp) / company_report.STATE_PATH
                state.parent.mkdir(parents=True)
                state.write_text(__import__("json").dumps({"source_sha256": digest, "pages": 18}), encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertIn("그대로", company_report.write(ctx, tmp))
                self.assertEqual(pdf.read_bytes(), b"%PDF-1.4 old")
        finally:
            company_report.print_pdf = original

    def test_published_pdf_is_a_pdf(self):
        pdf = ROOT / company_report.PDF_PATH
        if not pdf.exists():
            self.skipTest("아직 인쇄한 PDF가 없습니다(첫 자동 실행 전)")
        data = pdf.read_bytes()
        self.assertTrue(data.startswith(b"%PDF"))
        self.assertGreater(len(data), 100_000)


SEG_TABLE = ("<TABLE><TR><TD>구분</TD><TD>건축/주택</TD><TD>토목</TD><TD>플랜트/전력</TD><TD>기타</TD><TD>연결조정</TD><TD>합계</TD></TR>"
             "<TR><TD>매출액</TD><TD>500</TD><TD>100</TD><TD>300</TD><TD>50</TD><TD>(20)</TD><TD>930</TD></TR>"
             "<TR><TD>매출총이익</TD><TD>50</TD><TD>5</TD><TD>(10)</TD><TD>8</TD><TD>(1)</TD><TD>52</TD></TR></TABLE>")
EST_TABLE = ("<TABLE><TR><TD>구분</TD><TD>총계약수익의 변동</TD><TD>추정총계약원가의 변동</TD><TD>당기손익에 미치는 영향</TD>"
             "<TD>미래손익에 미치는 영향</TD><TD>공사손실충당부채</TD></TR>"
             "<TR><TD>건축/주택</TD><TD>100</TD><TD>130</TD><TD>(20)</TD><TD>(10)</TD><TD>5</TD></TR>"
             "<TR><TD>토목</TD><TD>50</TD><TD>60</TD><TD>(7)</TD><TD>(3)</TD><TD>1</TD></TR>"
             "<TR><TD>플랜트/전력</TD><TD>80</TD><TD>120</TD><TD>(30)</TD><TD>(10)</TD><TD>9</TD></TR>"
             "<TR><TD>합계</TD><TD>230</TD><TD>310</TD><TD>(57)</TD><TD>(23)</TD><TD>15</TD></TR></TABLE>")
DRIVER_XML = ("<DOCUMENT><TITLE>III. 재무에 관한 사항</TITLE><TITLE>3. 연결재무제표 주석</TITLE>"
              f"<P>40. 영업부문 (2) 당기 부문별 정보 (단위:백만원)</P>{SEG_TABLE}"
              f"<P>(5) 추정의 변경: 당기 중 진행중인 공사의 추정총계약원가 변동 (단위:백만원)</P>{EST_TABLE}"
              f"<TITLE>5. 재무제표 주석</TITLE><P>35. 영업부문 당기 (단위:백만원)</P>{SEG_TABLE}"
              f"<TITLE>6. 배당에 관한 사항</TITLE><P>당기 (단위:백만원)</P>{SEG_TABLE}</DOCUMENT>")


class DriverParsing(unittest.TestCase):
    """사업보고서 주석 읽기 (작은 예시 문서): 연결/별도 구분, 부문 표, 원가 추정 변경 표의 두 서식."""

    def test_scope_follows_titles(self):
        doc = drivers.Doc(DRIVER_XML)
        scopes = [doc.scope(pos) for pos, _ in doc.tables]
        self.assertEqual(scopes, ["consolidated", "consolidated", "separate", None])   # 재무제표 밖(배당 절) 표는 쓰지 않음
        self.assertEqual(drivers.Doc("<TITLE>40. 영업부문 - 별도</TITLE><TABLE></TABLE>").scope(30), "separate")
        self.assertEqual(drivers.Doc("<TITLE>40. 영업부문 (연결)</TITLE><TABLE></TABLE>").scope(30), "consolidated")

    def test_segment_table(self):
        got = drivers.parse_segment_tables(drivers.Doc(DRIVER_XML))
        self.assertEqual(set(got), {("consolidated", "current"), ("separate", "current")})
        c = got[("consolidated", "current")]
        self.assertEqual(c["revenue"]["building"], 500 * 1_000_000)
        self.assertEqual(c["revenue"]["adjust"], -20 * 1_000_000)          # 부문 합 + 연결조정 = 합계
        self.assertEqual(c["revenue"]["total"], 930 * 1_000_000)
        self.assertEqual(c["gross_profit"]["plant"], -10 * 1_000_000)

    def test_estimate_tables_both_layouts(self):
        got = drivers.parse_estimate_tables(drivers.Doc(DRIVER_XML))[("consolidated", "current")]   # 줄 = 부문
        self.assertEqual(got["total"]["pl_current"], -57 * 1_000_000)
        self.assertEqual(got["plant"]["loss_prov"], 9 * 1_000_000)
        self.assertEqual(got["building"]["pl_future"], -10 * 1_000_000)
        rows = [["구분", "건축/주택", "토목", "플랜트/전력", "합계"],                                  # 줄 = 항목 (XBRL 서식)
                ["총계약수익의 변동", "100", "50", "80", "230"], ["추정총계약원가의 변동", "130", "60", "120", "310"],
                ["당기손익에 미치는 영향", "(20)", "(7)", "(30)", "(57)"], ["미래손익에 미치는 영향", "(10)", "(3)", "(10)", "(23)"]]
        t = drivers._est_from_rows(rows)
        self.assertEqual(t["total"]["pl_current"], -57)
        self.assertEqual(t["civil"]["cost_change"], 60)


CONS = "<TITLE>III. 재무에 관한 사항</TITLE><TITLE>3. 연결재무제표 주석</TITLE>"
CG_TWO_COL = (CONS + "<P>38. 현금흐름표 (1) 당기 및 전기 중 영업으로부터 창출된 현금은 다음과 같습니다. (단위:백만원)</P>"
              "<TABLE><TR><TD>구 분</TD><TD>당 기</TD><TD>전 기</TD></TR>"
              "<TR><TD>당기순이익</TD><TD>100</TD><TD>80</TD></TR><TR><TD>조정:</TD><TD></TD><TD></TD></TR>"
              "<TR><TD>감가상각비</TD><TD>30</TD><TD>25</TD></TR><TR><TD>대손상각비</TD><TD>5</TD><TD>4</TD></TR>"
              "<TR><TD>공사손실충당부채전입액</TD><TD>12</TD><TD>3</TD></TR><TR><TD>이자비용</TD><TD>8</TD><TD>7</TD></TR>"
              "<TR><TD>이자수익</TD><TD>(6)</TD><TD>(5)</TD></TR><TR><TD>소 계</TD><TD>49</TD><TD>34</TD></TR>"
              "<TR><TD>영업활동으로 인한 자산부채의 변동:</TD><TD></TD><TD></TD></TR>"
              "<TR><TD>매출채권</TD><TD>(70)</TD><TD>10</TD></TR><TR><TD>미청구공사</TD><TD>(20)</TD><TD>(5)</TD></TR>"
              "<TR><TD>매입채무</TD><TD>15</TD><TD>(3)</TD></TR><TR><TD>초과청구공사</TD><TD>4</TD><TD>2</TD></TR>"
              "<TR><TD>충당부채</TD><TD>(6)</TD><TD>(1)</TD></TR><TR><TD>소 계</TD><TD>(77)</TD><TD>3</TD></TR>"
              "<TR><TD>영업으로부터 창출된 현금흐름</TD><TD>72</TD><TD>117</TD></TR></TABLE>")
CG_XBRL_ROWS = ("<TR><TD></TD><TD></TD><TD>공시금액</TD></TR><TR><TD>당기순이익(손실)</TD><TD>(50)</TD></TR>"
                "<TR><TD>당기순이익조정을 위한 가감</TD><TD>70</TD></TR>"
                "<TR><TD>당기순이익조정을 위한 가감</TD><TD>공사손실충당부채전입액</TD><TD>60</TD></TR>"
                "<TR><TD>감가상각비</TD><TD>20</TD></TR><TR><TD>법인세비용</TD><TD>(10)</TD></TR>"
                "<TR><TD>영업활동으로 인한 자산 부채의 변동</TD><TD>(5)</TD></TR>"
                "<TR><TD>영업활동으로 인한 자산 부채의 변동</TD><TD>매출채권의 감소(증가)</TD><TD>(40)</TD></TR>"
                "<TR><TD>계약부채의 증가(감소)</TD><TD>35</TD></TR><TR><TD>영업에서 창출된 현금흐름</TD><TD>15</TD></TR>")
CG_XBRL = (CONS + "<P>34. 현금흐름표 (연결)</P><TABLE><TR><TD>영업활동현금흐름</TD></TR><TR><TD>당기</TD><TD>(단위 : 백만원)</TD></TR></TABLE>"
           f"<TABLE>{CG_XBRL_ROWS}</TABLE>"
           # 재무제표 본문(현금흐름표)에 같은 줄이 있어도 주석이 아니므로 읽지 않습니다
           "<P>2-4. 연결 현금흐름표</P><TABLE><TR><TD>제 76 기 2025.01.01 부터 2025.12.31 까지</TD></TR><TR><TD>(단위 : 백만원)</TD></TR></TABLE>"
           f"<TABLE>{CG_XBRL_ROWS.replace('(50)', '(51)')}</TABLE>")
AGING_OLD = (CONS + "<P>(3) 당기말 및 전기말 현재 연결회사의 매출채권의 연령분석내역은 다음과 같습니다. (단위:백만원)</P>"
             "<TABLE><TR><TD>구 분</TD><TD>당기말</TD><TD>전기말</TD></TR><TR><TD>연체되지 않은 채권</TD><TD>100</TD><TD>90</TD></TR>"
             "<TR><TD>1년 이하</TD><TD>20</TD><TD>10</TD></TR><TR><TD>1년 초과 3년 이하</TD><TD>8</TD><TD>6</TD></TR>"
             "<TR><TD>3년 초과</TD><TD>4</TD><TD>5</TD></TR><TR><TD>대손충당금</TD><TD>(7)</TD><TD>(6)</TD></TR>"
             "<TR><TD>합 계</TD><TD>125</TD><TD>105</TD></TR></TABLE>")
AGING_XBRL = (CONS + "<P>(3) 당기말 및 전기말 현재 연결회사의 매출채권의 연령분석내역은 다음과 같습니다. 연체되거나 손상된 매출채권에 대한 공시</P>"
              "<TABLE><TR><TD>당기</TD><TD>(단위 : 백만원)</TD></TR></TABLE>"
              "<TABLE><TR><TD>금융자산, 분류</TD><TD>매출채권</TD></TR><TR><TD></TD><TD>3개월 이내</TD><TD>3개월 초과 1년 이내</TD>"
              "<TD>1년 초과 3년 이내</TD><TD>3년초과</TD></TR>"
              "<TR><TD>금융자산</TD><TD>50</TD><TD>30</TD><TD>15</TD><TD>5</TD><TD>100</TD><TD>(10)</TD><TD>90</TD></TR></TABLE>"
              "<TABLE><TR><TD>전기</TD><TD>(단위 : 백만원)</TD></TR></TABLE>"
              "<TABLE><TR><TD>금융자산, 분류</TD><TD>매출채권</TD></TR>"
              "<TR><TD>금융자산</TD><TD>40</TD><TD>20</TD><TD>10</TD><TD>2</TD><TD>(4)</TD><TD>68</TD></TR></TABLE>")
MIX_OLD = (CONS + "<P>(1) 당기말 및 전기말 현재 연결회사의 매출채권, 기타채권, 미청구공사의 구성내역은 다음과 같습니다. (단위:백만원)</P>"
           "<TABLE><TR><TD>연결재무상태표</TD><TD>계정과목</TD><TD>당기말</TD><TD>전기말</TD></TR>"
           "<TR><TD>매출채권</TD><TD>분양미수금</TD><TD>30</TD><TD>20</TD></TR><TR><TD>대손충당금</TD><TD>(1)</TD><TD>(1)</TD></TR>"
           "<TR><TD>공사미수금</TD><TD>200</TD><TD>150</TD></TR><TR><TD>대손충당금</TD><TD>(9)</TD><TD>(8)</TD></TR></TABLE>")
REV_TYPES = (CONS + "<P>24. 건설계약 (연결) 고객과의 계약에서 생기는 수익의 구분에 대한 공시</P>"
             "<TABLE><TR><TD>당기</TD><TD>(단위 : 백만원)</TD></TR></TABLE>"
             "<TABLE><TR><TD></TD><TD>재화나 용역의 이전 시기</TD></TR><TR><TD></TD><TD>기간에 걸쳐</TD><TD>한 시점에</TD></TR>"
             "<TR><TD></TD>" + "".join(f"<TD>{x}</TD>" for x in ("도급공사수익", "분양공사수익", "자산관리수익", "기타수익", "임대료수익") * 2) + "</TR>"
             "<TR><TD>고객과의 계약에서 생기는 수익</TD>" + "".join(f"<TD>{x}</TD>" for x in ("900", "20", "40", "5", "", "965", "", "10", "", "1", "", "11")) + "</TR>"
             "<TR><TD>기타 원천으로부터의 수익: 임대료 수익</TD>" + "".join(f"<TD>{x}</TD>" for x in ("", "", "", "", "3", "3", "", "", "", "", "1", "1")) + "</TR>"
             "</TABLE>")
SENS = (CONS + "<P>민감도분석은 결제되지 않은 외화표시 화폐성항목만을 포함합니다. 당기말 현재 각 외화에 대한 기능통화의 환율 10% 변동시 환율변동이 "
        "순자산(법인세효과 차감전)에 미치는 영향은 다음과 같습니다. (단위:백만원)</P>"
        "<TABLE><TR><TD>구분</TD><TD>10% 상승시</TD><TD>10% 하락시</TD></TR><TR><TD>USD</TD><TD>150</TD><TD>(150)</TD></TR>"
        "<TR><TD>기타</TD><TD>(40)</TD><TD>40</TD></TR></TABLE>"
        "<P>② 이자율위험 연결회사는 고정이자율과 변동이자율로 자금을 차입하고 있습니다. 당기말 현재 각 변동이자율 차입금에 대한 이자율이 1% 변동시 "
        "이자율 변동이 법인세비용차감전순이익에 미치는 영향은 다음과 같습니다. (단위:백만원)</P>"
        "<TABLE><TR><TD>구 분</TD><TD>1% 상승시</TD><TD>1% 하락시</TD></TR><TR><TD>단기차입금</TD><TD>(8)</TD><TD>8</TD></TR>"
        "<TR><TD>장기차입금</TD><TD>(1)</TD><TD>1</TD></TR></TABLE>")
M = 1_000_000


class NoteTables(unittest.TestCase):
    """현금흐름표 주석·매출채권 주석·수익의 구분·민감도 (작은 예시 문서, 서식별로)."""

    def test_unit_words(self):
        self.assertEqual([drivers.unit_of(x) for x in ("(단위:백만원)", "(단위 : 백만원)", "단위: 천원", "(단위 : 원)", "단위 없음")],
                         [M, M, 1000, 1, None])

    def test_cash_generated_two_columns(self):
        got = drivers.parse_cash_generated(drivers.Doc(CG_TWO_COL))
        cur, pri = got["current"], got["prior"]
        self.assertEqual((cur["net_income"], cur["cash_generated"], cur["gap"]), (100 * M, 72 * M, 0))
        self.assertEqual((pri["net_income"], pri["cash_generated"], pri["gap"]), (80 * M, 117 * M, 0))
        self.assertEqual(cur["adj"]["impairment"], 5 * M)               # '대손상각비'는 감가상각이 아니라 손상
        self.assertEqual(cur["adj"]["dep_amort"], 30 * M)
        self.assertEqual(cur["adj"]["provisions"], 12 * M)
        self.assertEqual(cur["adj"]["interest_tax"], 2 * M)
        self.assertEqual((cur["wc"]["receivables"], cur["wc"]["contract_assets"], cur["wc"]["contract_liabilities"]), (-70 * M, -20 * M, 4 * M))
        self.assertEqual(cur["wc"]["provisions_used"], -6 * M)
        self.assertEqual(cur["subtotal_gaps"], {"adj": 0, "wc": 0})      # 표의 소계와도 맞음
        self.assertEqual(pri["wc"]["receivables"], 10 * M)

    def test_cash_generated_xbrl_and_statement_is_skipped(self):
        got = drivers.parse_cash_generated(drivers.Doc(CG_XBRL))
        self.assertEqual(list(got), ["current"])
        cur = got["current"]
        self.assertEqual((cur["net_income"], cur["adj_total"], cur["wc_total"], cur["cash_generated"], cur["gap"]),
                         (-50 * M, 70 * M, -5 * M, 15 * M, 0))                 # 본문 표의 (51)이 아니라 주석의 (50)
        self.assertEqual(cur["adj"]["provisions"], 60 * M)                    # 묶음 머리글 줄의 첫 항목도 읽음
        self.assertEqual(cur["adj"]["interest_tax"], -10 * M)
        self.assertEqual((cur["wc"]["receivables"], cur["wc"]["contract_liabilities"]), (-40 * M, 35 * M))

    def test_cash_generated_rejects_tables_that_do_not_add_up(self):
        broken = CG_TWO_COL.replace("<TD>매입채무</TD><TD>15</TD>", "<TD>매입채무</TD><TD>16</TD>")
        cur = drivers.parse_cash_generated(drivers.Doc(broken))["current"]
        self.assertEqual(cur["gap"], 1 * M)                                    # collect는 이런 해를 쓰지 않고 오류로 남김
        self.assertEqual(cur["subtotal_gaps"]["wc"], 1 * M)

    def test_receivable_aging_both_layouts(self):
        old = drivers.parse_receivable_aging(drivers.Doc(AGING_OLD))
        self.assertEqual(old["current"]["buckets"], {"b0": 100 * M, "b1": 20 * M, "b2": 8 * M, "b3": 4 * M})
        self.assertEqual((old["current"]["allowance"], old["current"]["net"]), (-7 * M, 125 * M))
        self.assertEqual(old["prior"]["net"], 105 * M)
        new = drivers.parse_receivable_aging(drivers.Doc(AGING_XBRL))
        self.assertEqual(new["current"]["buckets"], {"b0": 50 * M, "b1": 30 * M, "b2": 15 * M, "b3": 5 * M})   # 총액 칸(100)은 건너뜀
        self.assertEqual((new["current"]["allowance"], new["current"]["net"]), (-10 * M, 90 * M))
        self.assertEqual(new["current"]["labels"], ["3개월이내", "3개월초과1년이내", "1년초과3년이내", "3년초과"])
        self.assertEqual(new["prior"]["net"], 68 * M)                           # '전기' 표는 앞 표에 이어서 읽음

    def test_receivable_mix(self):
        got = drivers.parse_receivable_mix(drivers.Doc(MIX_OLD))
        self.assertEqual(got["current"], {"construction": 200 * M, "construction_allowance": -9 * M, "sales": 30 * M, "sales_allowance": -1 * M})
        self.assertEqual(got["prior"]["construction"], 150 * M)

    def test_revenue_types(self):
        got = drivers.parse_revenue_types(drivers.Doc(REV_TYPES))["current"]
        self.assertEqual((got["contract"], got["sales"], got["asset_mgmt"], got["other"], got["rent"], got["total"]),
                         (900 * M, 30 * M, 40 * M, 6 * M, 4 * M, 980 * M))
        bad = REV_TYPES.replace("<TD>965</TD>", "<TD>966</TD>")                  # 칸 합 ≠ 소계면 쓰지 않음
        self.assertEqual(drivers.parse_revenue_types(drivers.Doc(bad)), {})

    def test_sensitivity_keeps_measure_and_scope(self):
        got = drivers.parse_sensitivity(drivers.Doc(SENS))
        self.assertEqual(got["fx"], {"pct": 10.0, "impact": 110 * M, "measure": "순자산(법인세효과 차감전)", "scope": "결제되지 않은 외화표시 화폐성 항목"})
        self.assertEqual(got["rate"], {"pct": 1.0, "impact": -9 * M, "measure": "법인세비용차감전순이익", "scope": "변동이자율 차입금"})


class YearView:
    def __init__(self, data):
        self.data = data

    def a(self, year, key):
        return self.data.get(year, {}).get(key)


class ResearchMath(unittest.TestCase):
    """원인 분해 계산(가상의 숫자): 방법마다 합이 맞고, 평균 기준은 순서에 따라 달라지지 않습니다."""
    V = YearView({1: {"revenue": 100.0, "cost_of_sales": 88.0, "sga": 6.0, "operating_profit": 6.0},
                  2: {"revenue": 150.0, "cost_of_sales": 141.0, "sga": 6.6, "operating_profit": 2.4}})

    def test_bridge_methods_add_up(self):
        for method in ("start", "end", "mid"):
            b = research.op_bridge(self.V, 1, 2, method)
            self.assertAlmostEqual(b["volume"] + b["cost"] + b["sga"] + b["other"], -3.6, places=9)
            self.assertAlmostEqual(b["other"], 0, places=9)
        mid = research.op_bridge(self.V, 1, 2)
        self.assertEqual(mid["method"], "mid")
        self.assertAlmostEqual(mid["volume"], 50 * (0.06 + 0.016) / 2, places=9)
        self.assertAlmostEqual(mid["cost"], -0.06 * 125, places=9)
        back = research.op_bridge(self.V, 2, 1)                     # 순서를 바꾸면 정확히 부호만 바뀜
        for k in ("volume", "cost", "sga"):
            self.assertAlmostEqual(back[k], -mid[k], places=9)
        start = research.op_bridge(self.V, 1, 2, "start")
        self.assertAlmostEqual(start["volume"], 50 * 0.06, places=9)  # 앞 해 이익률 기준
        shares = research.abs_shares([mid])
        self.assertAlmostEqual(sum(shares.values()), 100, places=9)

    def test_scale_ratio_split(self):
        x = research._scale_ratio(10.0, 30.0, 100.0, 150.0)
        self.assertAlmostEqual(x["scale"] + x["ratio"], x["d"], places=9)
        self.assertAlmostEqual(x["scale"], 50 * 0.15, places=9)
        self.assertIsNone(research._scale_ratio(None, 30.0, 100.0, 150.0))

    def test_cash_window_and_missing_years(self):
        ctx = {"annual": [], "drivers": {}}
        self.assertEqual(research.cash_window([], 2022, 2025), None)
        rows = [{"year": 2022, "ni": 1, "adj_total": 2, "wc_total": -4, "generated": -1, "interest_received": 1, "interest_paid": -1,
                 "dividends_received": 0, "tax_paid": -1, "int_tax": -1, "cfo": -2, "cfo_calc": -2,
                 "adj": {k: 0 for k, _ in research.CF_ADJ}, "wc": {k: 0 for k, _ in research.CF_WC}}]
        w = research.cash_window(rows, 2021, 2025)
        self.assertEqual((w["years"], w["cfo"], w["wc_total"]), (1, -2, -4))
        self.assertTrue(ctx)


class FakeView:
    def __init__(self, values):
        self.values = values

    def a(self, year, key):
        return self.values.get(key)


class ReportWording(unittest.TestCase):
    """기업분석 보고서 문장 규칙: 조사, 경영진단 문장 고르기, 업계 공통/회사 고유 판정, 표 머리글의 근거 표시."""

    def test_josa(self):
        j = company_report.josa
        self.assertEqual([j("−1.24조", "이"), j("1,221억", "으로"), j("건축/주택", "이"), j("기타", "이"), j("3.5%", "으로"),
                          j("8", "으로"), j("3", "으로"), j("노출", "은"), j("0.94조", "을")],
                         ["−1.24조가", "1,221억으로", "건축/주택이", "기타가", "3.5%로", "8로", "3으로", "노출은", "0.94조를"])

    def test_mdna_sentences_must_match_consolidated_numbers(self):
        F = {"v": FakeView({"operating_profit": 574_902_000_000, "revenue": 21_239_082_000_000, "net_income": 470_900_000_000}),
             "dr": {"mdna": {"2022": {"receipt": "x", "sentences": [
                 "영업이익은 원가율이 상승한 영향에 전년대비 22.8% 감소한 5,820억원을 기록하였습니다.",          # 1.2% 차이 → 버림
                 "매출액은 전년대비 2조 1,837억원 증가한 12조 5,012억원을 기록하였으며, 이는 대형 현장 매출 증가에 기인합니다.",  # 부문 숫자
                 "영업이익은 연결자회사의 손실 반영에 따라 약 0.6조원을 기록하였습니다.",                       # '약' → 6% 안
                 "환율 상승에 따른 환관련 평가이익 영향으로 순이익이 늘었습니다."]}}}}                          # 금액 없음 + 이유
        picked, receipt = company_report.mdna_pick(F, 2022)
        self.assertEqual(receipt, "x")
        self.assertEqual(len(picked), 2)
        self.assertIn("약 0.6조원", picked[0])
        self.assertIn("환율", picked[1])

    def test_change_kind(self):
        peers = {2021: {"own": 4.2, "median": 8.3, "n": 4}, 2022: {"own": 2.7, "median": 5.6, "n": 4},
                 2023: {"own": 2.6, "median": 4.4, "n": 4}, 2024: {"own": -3.9, "median": 3.5, "n": 4}}
        kind = company_report.change_kind
        self.assertEqual(kind(peers, 2022)["word"], "업계 공통 하락")     # −1.5%p vs 동종사 −2.7%p
        self.assertEqual(kind(peers, 2023)["word"], "큰 변화 없음")
        self.assertEqual(kind(peers, 2024)["word"], "회사 고유 하락")     # −6.5%p vs −0.9%p
        self.assertIsNone(kind(peers, 2021))                              # 전년 자료 없음

    def test_table_head_tags(self):
        self.assertIn('class="ev ev-c"', company_report.head_tags("근거 [계산]"))
        self.assertEqual(company_report.head_tags("[abc]"), "[abc]")


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
        """저장소(.github/workflows)와 제출 ZIP을 푼 폴더(workflows/) 어느 쪽에서도 숨김 파일 없는 ZIP을 만듭니다."""
        import package_project
        with tempfile.TemporaryDirectory() as tmp:
            out, names = package_project.build(Path(tmp) / "test.zip")
            self.assertTrue(zipfile.is_zipfile(out))
        self.assertFalse([n for n in names if any(p.startswith(".") for p in Path(n).parts)])
        self.assertIn("workflows/financial-agent.yml", names)
        self.assertFalse([n for n in names if n.startswith("data/financials/raw/") and n.endswith(".zip")])


if __name__ == "__main__":
    unittest.main()
