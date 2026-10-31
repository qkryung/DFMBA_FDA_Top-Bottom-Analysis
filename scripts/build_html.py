"""Build the verified Data App and copy its portable HTML to artifacts/."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-plugin-root', type=Path)
    parser.add_argument('--node', default='node')
    args = parser.parse_args()
    plugin = args.data_plugin_root
    if plugin is None and os.environ.get('DATA_ANALYTICS_PLUGIN_ROOT'):
        plugin = Path(os.environ['DATA_ANALYTICS_PLUGIN_ROOT'])
    if plugin is None:
        base = Path.home()/'.codex/plugins/cache/openai-curated-remote/data-analytics'
        candidates = list(base.glob('*/scripts/data-app.mjs'))
        if candidates:
            plugin = max(candidates, key=lambda p:p.stat().st_mtime).parents[1]
    runner = plugin/'scripts/data-app.mjs' if plugin else None
    if runner is None or not runner.is_file():
        parser.error('Provide --data-plugin-root for the installed Data Analytics plugin. The existing artifacts/result_report.html can be read without it.')
    env = os.environ.copy()
    env.pop('CODEX_SESSION_ID', None)
    def run(argv):
        subprocess.run([str(v) for v in argv], cwd=ROOT, env=env, check=True)
    app = ROOT/'report-app'
    run([sys.executable, ROOT/'scripts/build_report.py', '--complete'])
    run([args.node,runner,'build','--project-dir',app,'--separate-data'])
    export = app/'.data-app-offline/exports/result_report.html'
    run([args.node,runner,'export-offline','--project-dir',app,'--output',export])
    out = ROOT/'artifacts/result_report.html'
    out.parent.mkdir(exist_ok=True)
    shutil.copy2(export,out)
    def digest(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()
    manifest={'html_sha256':digest(out),'snapshot_sha256':digest(app/'src/data.json'),'results_sha256':digest(ROOT/'reports/results.json'),'source':'Verified Data App split build followed by portable export.'}
    (out.parent/'report_manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8',newline='\n')
    print(f'Portable report: {out.relative_to(ROOT)} ({out.stat().st_size:,} bytes)')

if __name__ == '__main__':
    main()
