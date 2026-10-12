[![🔗 대시보드 바로가기](assets/dashboard-badge.svg)](https://hsc-class01.github.io/KTG_Hyundai/dashboard/)

# 현대건설 OpenDART 재무분석 에이전트

현대건설(000720)의 공시를 **2010년부터** 보존하고, 주요 연결재무수치와 비율을 계산하는 Python 에이전트입니다. 독립 보고서를 최대 3개씩 병렬 수집하고 기간순으로 정렬합니다. 사업·반기·1/3분기 보고서를 수집하며 GitHub Actions가 **매월 1일 오전 9시 17분(한국시간)** 실행합니다. 실행 지연은 가능하며, 실패하면 Actions에서 원인을 확인할 수 있습니다.

- [대시보드](https://hsc-class01.github.io/KTG_Hyundai/dashboard/): 상단 그래프·핵심 지표·자동 요약, 하단 Annual / Half-year / Quarterly 각각의 전체 표와 CSV, 마지막 Peer Firms 표
- [포트폴리오](https://hsc-class01.github.io/KTG_Hyundai/): 기존 토목 프로젝트
- [수집·배포 실행 이력](https://github.com/HSC-Class01/KTG_Hyundai/actions/workflows/financial-dashboard.yml)
- [기존 2016~2025 분석보고서](reports/hyundai-10y-report.html): 별도 보존된 연간 스냅샷

## 범위와 확인이 필요한 부분

| 항목 | 구현 |
|---|---|
| 공시 수집 | 2010년~현재 사업·반기·분기 보고서 목록, 최신 보고서 원문 ZIP 보존 |
| 재무수치 | 연결 CFS, 매출·영업이익·순이익·자산·부채·자본·유동자산·유동부채·영업CF |
| 비율 | 전년 동기간 매출증감률·영업/순이익률·부채/유동비율·ROA·ROE |
| 정정 | 전체 공시 이력에서 기간별 최신 접수번호 선택, 모든 2015년 이후 재무 API 매월 재조회 |
| 주기 | 매월 1일 09:17 KST, 수동 실행 가능, 에이전트 코드 변경 시 실행 |
| 저장·출처 | 공시 원문 ZIP·API 원본 JSON·선택 계정 근거·접수번호·SHA256·CSV |
| 배포 | 같은 워크플로에서 Pages artifact 업로드와 배포 수행 |
| 2010~2014 | 재무 API 미제공: 원문 후보를 추출하되 **검증된 항목만** 수치로 반영 |
| 교수님 첨부 항목·배지 | 첨부 미제공 상태: 기존 주요 항목과 자체 SVG 배지 사용 |

**2010년부터 공시를 수집하는 것과 모든 재무수치가 확정된 것은 다릅니다.** OpenDART 전체 재무제표 API는 2015년 이후부터 제공합니다. 2010~2014는 원문 XML/HTML 표에서 후보 계정·표 머리글·주변 설명을 뽑아 검증 자료를 만듭니다. 연결 여부·금액 단위·당기/전기·누적기간·회계기준을 확인하지 않은 값은 `—`로 남깁니다. 미공시·계정 미확인·0원을 구분합니다.

## API 키와 GitHub 설정

1. [OpenDART](https://opendart.fss.or.kr/)에서 인증키를 발급합니다.
2. 저장소 **Settings → Secrets and variables → Actions → New repository secret**에서 이름 `DART_API_KEY`, 값에 인증키를 넣습니다. 이미 등록한 경우 그대로 사용합니다. 코드·HTML·ZIP에는 키를 넣지 않습니다.
3. **Settings → Pages → Build and deployment → Source: GitHub Actions**를 선택합니다. 기존 포트폴리오도 함께 배포합니다.
4. **Actions → Hyundai Financial Dashboard → Run workflow → main**에서 최초 수집을 실행합니다. 기존 키가 유효하면 에이전트 코드 push로도 실행됩니다.
5. 저장소 오른쪽 **About → 톱니 → Website**에 `https://hsc-class01.github.io/KTG_Hyundai/dashboard/`를 입력합니다.

워크플로에는 `contents: write`, `pages: write`, `id-token: write`가 있습니다. 조직 정책이 이 권한을 제한하면 저장소/조직 관리자가 허용해야 합니다. 공개 저장소의 예약 실행은 60일 동안 저장소 활동이 없으면 중단될 수 있습니다. 매 실행 확인일을 commit하지만 GitHub의 예약 비활성화 상태도 Actions에서 확인하세요.

## 계산 기준

- Annual: 12개월 실적. Half-year: 1~6월 누적 실적. Quarterly: 각 3개월 실적.
- 반기·3분기 손익의 `thstrm_amount`는 3개월, `thstrm_add_amount`는 누적입니다. 반기 표에는 후자를 사용합니다. 누적필드가 없다고 3개월 값을 반기 누적으로 대신하지 않습니다.
- CF `thstrm_amount`는 해당 보고기간 누적이며, BS는 기말 잔액입니다.
- Q1=3개월, Q2=H1−Q1, Q3=9개월−H1, Q4=FY−9개월. 앞 누적값이 없으면 차감값을 비웁니다. 서로 다른 정정·비교기준일 수 있어 원문 확인이 필요합니다.
- 매출증감률: `(당기−전년 동기간) / 전년 동기간 ×100`.
- 이익률: `이익 / 매출 ×100`. 부채비율: `부채 / 자본 ×100`. 유동비율: `유동자산 / 유동부채 ×100`.
- 연간·반기 ROA/ROE: 해당 기간 연결순이익 / 전년말·당기말 총자산/총자본 단순평균 ×100. 반기는 연율화하지 않습니다. 개별분기 ROA/ROE는 제공하지 않습니다.
- 순이익은 비지배지분을 포함한 연결 전체 기준입니다. 지배주주 순이익 기준 ROE와 다릅니다.
- 분모 0 이하·값 누락·계정 금액 충돌은 공란으로 처리합니다. 표는 억원, 그래프는 조원, 계산·CSV 원자료는 원 기준입니다.
- 자산=부채+자본을 허용 오차 내에서 검증합니다. 원문 최신 접수번호와 API의 재무 접수번호가 다르면 각각 기록합니다.

## 파일 구조와 로컬 실행

```text
scripts/dart_agent.py                 수집·표준화·비율·출력·사이트 조립
scripts/dart_10y.py                   기존 계정 매칭과 10개년 보고서
config/peers.json                     동종기업 목록
config/historical_verified.json      원문 검증 후 등록할 과거 수치 (선택)
data/financials/filings.json          정정 포함 공시 목록
data/financials/raw/                 최신 보고서 원문 ZIP, 원본 API JSON, 과거 후보
data/financials/periods.json          누적 기간별 수치·계정 근거·검증 결과
data/financials/dashboard.json       대시보드 입력
data/financials/*.csv                Annual / Half-year / Quarterly
dashboard/template.html              화면 템플릿
dashboard/index.html                 데이터 포함 생성 화면
.github/workflows/financial-dashboard.yml  월간 수집·배포
tests/test_financials.py              누적·개별분기·결측·정정·계정 검증
```

Python 3.11 이상을 사용합니다.

```bash
python -m pip install -r requirements.txt
# 키는 환경변수 DART_API_KEY로 전달 (파일에 저장하지 않음)
python scripts/dart_agent.py
python -m unittest discover -s tests -v
# 키 없이 보존된 데이터로 화면 다시 생성
python scripts/dart_agent.py --offline
python scripts/dart_agent.py --build-site
python -m http.server 8000 --directory _site
```

Windows PowerShell 키 입력: `$env:DART_API_KEY = Read-Host 'OpenDART API key'`. Linux/macOS Bash: `read -s DART_API_KEY; export DART_API_KEY`. 실행 후 환경변수를 지워도 다음 GitHub 실행에는 저장소 Secret을 사용합니다.

과거 수기검증값은 `config/historical_verified.json`에 다음 구조의 배열로 등록합니다. 정확한 최신 접수번호와 일치할 때만 반영하므로 정정 후에는 재검증해야 합니다.

```json
[
  {
    "year": 2010,
    "month": 12,
    "receipt": "실제14자리접수번호",
    "basis": "CFS",
    "reviewed_by": "검토자",
    "evidence": {"table": "연결재무제표 표명", "unit": "원", "column": "당기", "note": "원문 위치·회계기준 확인"},
    "values_krw": {}
  }
]
```

## ZIP 제출과 숨김 파일

`python scripts/package_project.py`로 제출용 ZIP을 만듭니다. `.git`, `.github`, `.nojekyll`, 캐시를 포함한 **모든 점으로 시작하는 경로를 ZIP에서 제외**합니다. GitHub Actions 필수 워크플로는 ZIP의 `workflows/financial-dashboard.yml`과 `workflows/hyundai-10y.yml`로 제공합니다. 복원 방법은 `SETUP.md`에 있습니다. 용량이 큰 공시 원문 ZIP은 제출 ZIP에서 제외하며 GitHub 저장소에 보존합니다. 로컬 수집을 실행하면 누락된 원문을 다시 다운로드합니다. 실제 저장소에는 `.github/workflows` 경로가 필요합니다. ZIP을 웹에 올리는 것만으로 예약 실행이 설치되지는 않습니다.

## 국내 Peer Firms

| 기업 | 종목코드 | 비교 사업 | 주의 |
|---|---|---|---|
| [GS건설](https://www.gsenc.com/) | 006360 | 주택·건축·토목·플랜트 | 해외 프로젝트·자회사 구성 차이 |
| [DL이앤씨](https://www.dlenc.co.kr/) | 375500 | 주택·토목·플랜트 | 2021년 분할 신설, 과거 DL과 단순 연결 불가 |
| [대우건설](https://www.daewooenc.com/) | 047040 | 주택·건축·토목·플랜트 | 해외 비중·수익 인식 차이 |
| [삼성물산](https://www.samsungcnt.com/) | 028260 | 건설부문 중심 | 비건설·바이오 포함, 연결 전체 직접 비교 주의 |

Peer 재무수치 자동 비교까지 구현한 것은 아니며 사업구조 기반의 비교 후보 목록입니다.

자료 출처: [전체 재무제표 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020), [공시검색 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019001), [공시 원문 API](https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS001&apiId=2019003), [Pages 워크플로 가이드](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).
