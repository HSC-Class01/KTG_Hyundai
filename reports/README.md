# 현대건설 10개년 재무제표 자동 분석

## 과제 범위
- 분석 기업: 현대건설(상장종목코드 000720)
- 대상 연도: 2016~2025년 (최근 완료된 10개 사업연도)
- 출처: 금융감독원 OpenDART 단일회사 전체 재무제표
- API 설명: https://opendart.fss.or.kr/guide/detail.do?apiGrpCd=DS003&apiId=2019020
- 기준: 연결재무제표(CFS), 각 연도 사업보고서(11011)
- 연도별 당기금액(thstrm_amount)을 사용합니다.

## 실행 방법
1. 저장소 HSC-Class01/KTG_Hyundai의 Settings → Secrets and variables → Actions → Repository secrets에 DART_API_KEY 등록
2. 저장소 상단 Actions 클릭
3. 왼쪽 Hyundai OpenDART 10-Year Report 선택
4. Run workflow → Branch: main → Run workflow 클릭
5. 실행이 녹색으로 끝나면 reports/hyundai-10y-report.html을 열어 확인합니다.

웹 보고서: https://hsc-class01.github.io/KTG_Hyundai/reports/hyundai-10y-report.html

## 생성되는 파일
- data/dart10y/financial_2016.json ~ financial_2025.json: DART 원문 응답 10개
- data/dart10y/financial_summary.csv: 10년치 핵심 재무제표 항목 (원)
- data/dart10y/financial_ratios.csv: 매출증감률, 영업이익률, 순이익률, 부채비율, 유동비율, ROA, ROE (%)
- data/dart10y/account_sources.csv: 선택 계정명·계정ID·사업보고서 접수번호·검증 상태
- reports/hyundai-10y-report.md: 보고서 Markdown 원본
- reports/hyundai-10y-report.html: GitHub Pages용 보고서

## 검증 및 유의사항
- 결측 데이터나 동일 계정에서 서로 충돌하는 금액은 0으로 대체하지 않고 자료 없음으로 표시하며 보고서에 주의를 남깁니다.
- 각 연도 원본 JSON과 계정 매칭 기록을 보존합니다.
- 연결·별도, 연도별 회계기준 변화, 정정공시, 계정 분류 및 연결 범위 차이로 연도 간 직접 비교에 한계가 있을 수 있습니다.
- 2016년 전년대비 매출증감률, ROA, ROE는 계산에 필요한 2015년 연결재무상태표를 별도로 수집하지 않아 비워 둡니다.
- 이 분석은 정량 지표를 자동 계산한 1차 분석입니다. 실적 변동 원인과 최종 평가에는 원문 주석 검토가 필요합니다.
- API 인증키는 공개 파일에 쓰지 마세요. 반드시 GitHub Secret에만 보관합니다.
- GitHub Actions 실행에는 저장소 Actions 실행 권한과 contents: write 권한이 필요합니다. 조직 정책으로 제한된 경우 관리자 설정이 필요할 수 있습니다.

기존 2022~2025년 현대건설 재무분석 대시보드는 변경하지 않습니다.
