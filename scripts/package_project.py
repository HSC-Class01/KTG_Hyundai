#!/usr/bin/env python3
"""Build submission ZIP without ANY dot paths; relocate workflows for easy upload."""
import argparse
import zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--output',default=str(ROOT.parent/'KTG_Hyundai_agent.zip'))
args=parser.parse_args()
output=Path(args.output)
output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
    for path in sorted(ROOT.rglob('*')):
        rel=path.relative_to(ROOT)
        if not path.is_file() or any(p.startswith('.') or p in ('_site','__pycache__','node_modules') for p in rel.parts) or path==output or (rel.parts[:3]==('data','financials','raw') and path.suffix=='.zip'):
            continue
        z.write(path,rel.as_posix())
    for path in sorted((ROOT/'.github/workflows').glob('*.yml')):
        z.write(path,'workflows/'+path.name)
with zipfile.ZipFile(output) as z:
    assert not any(any(p.startswith('.') for p in Path(n).parts) for n in z.namelist())
    assert 'workflows/financial-dashboard.yml' in z.namelist()
print(f'{output} ({output.stat().st_size:,} bytes)')
