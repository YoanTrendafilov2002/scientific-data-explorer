"""Build a local source ZIP from an allowlist; never include private run data."""
import hashlib
import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    destination=ROOT.parent / ('scientific-data-explorer-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')+'.zip')
    paths=[]
    for folder in ('src','scripts','ui','tests','reference','contracts','scenarios'):
        paths.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.js','.cjs','.html','.json','.sql','.csv'))
    paths.extend(ROOT/p for p in ('Start Explorer.bat','run_ui.bat','EXPLORER_README.md','README.md','LICENSE','requirements.txt','AGENTS.md','scientific_contract.yaml','examples/reader_data.json','examples/reader_config.json','examples/noaa_config.json','examples/noaa_lga_20240101.json','docs/dependency_graph.json'))
    paths=sorted(set(paths))
    paths.extend(ROOT/p for p in ('docs/EXPLORER_USER_MANUAL.md', 'docs/USER_MANUAL.md', 'docs/PRESENTATION_3_MIN.md'))
    manifest={str(p.relative_to(ROOT)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED) as bundle:
        for p in paths:bundle.write(p,'scientific-data-explorer/'+p.relative_to(ROOT).as_posix())
        bundle.writestr('scientific-data-explorer/PACKAGE_MANIFEST.json',json.dumps(manifest,indent=2))
    with zipfile.ZipFile(destination) as bundle:
        assert bundle.testzip() is None
        assert not any('workflow_runs/' in n or 'bob_sessions/' in n or 'bob-task-' in n for n in bundle.namelist())
    print(json.dumps({'zip':str(destination),'files':len(paths)+1,'sha256':hashlib.sha256(destination.read_bytes()).hexdigest()},indent=2))


if __name__=='__main__':main()
