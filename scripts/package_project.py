#!/usr/bin/env python3
"""제출용 ZIP을 만듭니다.

- 점(.)으로 시작하는 파일·폴더는 하나도 넣지 않습니다. (.git, .github, .gitignore, .nojekyll …)
- GitHub Actions 워크플로(.github/workflows/*.yml)는 숨김 폴더라서 workflows/ 폴더로 옮겨 넣습니다.
- 용량이 큰 공시 원문 ZIP(data/financials/raw/*.zip)은 넣지 않습니다. 첫 실행 때 에이전트가 다시 받습니다.

실행: python scripts/package_project.py            → dist/KTG_Hyundai_agent.zip
      python scripts/package_project.py --output 경로.zip
"""
import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"_site", "__pycache__", "dist", "node_modules"}


def is_hidden(rel):
    return any(part.startswith(".") for part in rel.parts)


def included(path, output):
    rel = path.relative_to(ROOT)
    if not path.is_file() or path == output or is_hidden(rel) or SKIP_DIRS & set(rel.parts):
        return False
    if rel.parts[:3] == ("data", "financials", "raw") and path.suffix.lower() == ".zip":
        return False
    return path.suffix.lower() not in (".pyc", ".zip")


def build(output):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    names = []
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(ROOT.rglob("*")):
            if included(path, output):
                name = path.relative_to(ROOT).as_posix()
                zf.write(path, name)
                names.append(name)
        for path in sorted((ROOT / ".github" / "workflows").glob("*.yml")):
            name = "workflows/" + path.name
            zf.write(path, name)
            names.append(name)
    # 검사: 숨김 경로가 없고, 꼭 필요한 파일이 들어 있어야 합니다.
    with zipfile.ZipFile(output) as zf:
        inside = zf.namelist()
    hidden = [n for n in inside if is_hidden(Path(n))]
    if hidden:
        raise SystemExit(f"숨김 경로가 들어갔습니다: {hidden[:5]}")
    required = ["README.md", "SETUP.md", "scripts/dart_agent.py", "config/company.json", "workflows/financial-agent.yml",
                "dashboard/index.html"]
    missing = [n for n in required if n not in inside]
    if missing:
        raise SystemExit(f"필수 파일이 빠졌습니다: {missing}")
    return output, inside


def main():
    parser = argparse.ArgumentParser(description="숨김 파일 없는 제출용 ZIP 만들기")
    parser.add_argument("--output", default=str(ROOT / "dist" / "KTG_Hyundai_agent.zip"))
    args = parser.parse_args()
    output, inside = build(args.output)
    print(f"{output} · 파일 {len(inside)}개 · {output.stat().st_size:,} bytes · 숨김 파일 없음")


if __name__ == "__main__":
    main()
