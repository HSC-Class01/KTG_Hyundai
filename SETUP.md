# 제출 ZIP 실행 안내

대상: 현대건설(000720). 대시보드: https://hsc-class01.github.io/KTG_Hyundai/dashboard/

1. Python 3.11 이상 설치 후 `python -m pip install -r requirements.txt`.
2. API 키는 GitHub 저장소의 `DART_API_KEY` Secret에 등록합니다. 기존 저장소는 이미 등록한 키를 재사용합니다.
3. ZIP에는 숨김 파일/폴더가 없습니다. `workflows/*.yml`은 전달용입니다. GitHub 웹에서 **Add file → Create new file**을 눌러 `.github/workflows/financial-dashboard.yml` 경로를 입력하고, ZIP의 동일 이름 파일 내용을 붙여넣습니다. 기존 저장소에서는 이미 설치된 파일을 그대로 사용합니다.
4. Settings → Pages → Source를 **GitHub Actions**로 설정합니다.
5. Actions → Hyundai Financial Dashboard → Run workflow. 매월 1일 09:17 KST에도 실행됩니다.
6. About의 Website에 대시보드 URL을 입력합니다.

키 없이 현재 화면 확인: `python scripts/dart_agent.py --offline`, `python scripts/dart_agent.py --build-site`, `python -m http.server 8000 --directory _site` 실행 후 http://localhost:8000/dashboard/ .

**미확정 항목:** 2010~2014 재무수치는 원문 수기검증 이후 반영. 교수님 첨부 재무항목과 배지 이미지는 미제공. 구현 내용·계산식·결측 사유는 README 참고.
