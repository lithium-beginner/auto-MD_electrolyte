#!/usr/bin/env python3
import argparse
import glob
import json
from pathlib import Path
import shutil
import tempfile
from electrolyte.recipe import build_manifest
from electrolyte.parameters import sections

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser(description='Generate isolated electrolyte MD work directories')
    p.add_argument('inputs', nargs='+', help='JSON paths or quoted glob patterns')
    p.add_argument('--workdir', type=Path, default=Path('workdir'))
    p.add_argument('--templates', type=Path, default=ROOT / 'templates')
    args = p.parse_args()
    for name in ('defaults.itp', 'analysis.json'):
        if not (args.templates / name).is_file():
            p.error(f'missing template: {name}')
    profile_path = args.templates / 'profile.json'
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else {'family': 'GAFF2', 'defaults': ['1', '2', 'yes', '0.5', '0.8333333333333333']}
    defaults = sections((args.templates / 'defaults.itp').read_text()).get('defaults', [])
    if len(defaults) != 1 or len(defaults[0]) != 5:
        p.error('invalid defaults template')
    expected = profile['defaults']
    if defaults[0][:3] != expected[:3] or any(abs(float(a)-float(b)) > 1e-6 for a,b in zip(defaults[0][3:], expected[3:])):
        p.error('defaults template disagrees with forcefield profile')
    json.loads((args.templates / 'analysis.json').read_text())
    files = set()
    for pattern in args.inputs:
        matches = glob.glob(pattern)
        if not matches:
            p.error(f'no inputs match {pattern}')
        files.update(matches)
    manifests = []
    for path in sorted(files):
        data = json.loads(Path(path).read_text())
        for recipe in data if isinstance(data, list) else [data]:
            manifest = build_manifest(recipe)
            manifest['forcefield_profile'] = profile
            manifests.append(manifest)
    names = [m['recipe']['recipe_name'] for m in manifests]
    if len(names) != len(set(names)):
        p.error('duplicate recipe_name across inputs')
    args.workdir.mkdir(parents=True, exist_ok=True)
    for name in names:
        if (args.workdir / name).exists():
            p.error(f'work directory already exists: {name}')
    for m, name in zip(manifests, names):
        with tempfile.TemporaryDirectory(dir=args.workdir) as tmp:
            out = Path(tmp) / name
            out.mkdir()
            (out / 'manifest.json').write_text(json.dumps(m, indent=2, ensure_ascii=False))
            (out / 'recipe.json').write_text(json.dumps(m['recipe'], indent=2, ensure_ascii=False))
            for script in ('prepare_system.py', 'run_md.py', 'analyze.py'):
                shutil.copy2(ROOT / script, out / script)
            shutil.copytree(ROOT / 'electrolyte', out / 'electrolyte', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(args.templates, out / 'templates')
            out.rename(args.workdir / name)
        print(args.workdir / name)


if __name__ == '__main__':
    main()
