# 제출 ZIP으로 에이전트 설치하기

이 ZIP에는 숨김 파일(이름이 점으로 시작하는 파일·폴더)이 없습니다. GitHub Actions 워크플로는 원래 `.github/workflows/` 라는 숨김 폴더에 있어야 해서, ZIP에서는 `workflows/financial-agent.yml` 로 옮겨 두었습니다. 아래 순서대로 하면 새 저장소에서도 매월 1일 자동 업데이트가 동작합니다.

## 1. 저장소에 파일 올리기

1. GitHub에서 새 저장소를 만들고(Public), ZIP을 푼 파일·폴더를 **Add file → Upload files** 로 올립니다. (`workflows` 폴더는 이 단계에서 올리지 않아도 됩니다.)
2. 워크플로 만들기: **Add file → Create new file**
   - 파일 이름 칸에 `.github/workflows/financial-agent.yml` 을 그대로 입력합니다. (`/`를 입력하면 폴더가 만들어집니다.)
   - ZIP의 `workflows/financial-agent.yml` 내용을 전부 복사해 붙여넣고 **Commit changes** 를 누릅니다.

## 2. OpenDART API 키 입력

1. [OpenDART](https://opendart.fss.or.kr/) → 인증키 신청/관리에서 40자리 인증키를 발급받습니다.
2. 저장소 **Settings → Secrets and variables → Actions → New repository secret**
   - Name: `DART_API_KEY`
   - Secret: 인증키
3. 키를 코드·README·ZIP 어디에도 적지 않습니다. 워크플로가 실행될 때만 환경변수로 전달됩니다.

## 3. 권한과 GitHub Pages

1. 워크플로 파일 안에 필요한 권한(`contents: write` 등)이 적혀 있어서 보통은 따로 설정할 것이 없습니다. 커밋 단계에서 권한 오류(403)가 나면 **Settings → Actions → General → Workflow permissions** 를 *Read and write permissions* 로 바꿉니다. (조직 저장소에서 막혀 있으면 조직 관리자에게 요청합니다.)
2. **Settings → Pages → Build and deployment → Source** 를 *Deploy from a branch* (Branch: `main`, 폴더: `/ (root)`) 또는 *GitHub Actions* 중 하나로 설정합니다. 워크플로가 어느 쪽인지 확인해서 알맞게 게시합니다.

## 4. 실행과 확인

1. **Actions → Financial Agent → Run workflow** 를 누릅니다. 처음에는 공시 원문을 모두 받느라 5~15분 걸릴 수 있습니다.
2. 초록색 체크가 뜨면 `https://<계정>.github.io/<저장소>/dashboard/` 에서 대시보드를 확인합니다.
3. 저장소 첫 화면 오른쪽 **About → ⚙️ → Website** 에 대시보드 주소를 넣고 Save 합니다.
4. 이후에는 매월 1일 09:17(한국시간)에 자동으로 실행됩니다.

## 다른 저장소·회사로 쓸 때

- `config/company.json` 의 `dashboard_url`, `repo_url` 을 새 주소로 바꿉니다.
- README 첫 줄의 배지 링크 주소도 새 대시보드 주소로 바꿉니다.
- 다른 회사를 분석하려면 같은 파일의 `name`, `stock_code`, `corp_code`(OpenDART 고유번호), `peers` 를 바꿉니다.

## 키 없이 화면만 확인하기

```bash
python scripts/dart_agent.py --offline     # 저장된 자료로 대시보드 다시 만들기
python -m http.server 8000                 # 브라우저에서 http://localhost:8000/dashboard/
```

Python 3.10 이상이면 추가로 설치할 패키지는 없습니다.
