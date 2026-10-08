#!/usr/bin/env python3
"""Generate and execute multiple recipes sequentially, preserving per-stage logs."""
import argparse
from pathlib import Path
import subprocess
import sys
import json

ROOT = Path(__file__).resolve().parent


def main():
    p = argparse.ArgumentParser()
    p.add_argument('inputs', nargs='+')
    p.add_argument('--workdir', type=Path, default=Path('workdir'))
    p.add_argument('--library', type=Path)
    p.add_argument('--auto-parameterize', action='store_true')
    p.add_argument('--generate-only', action='store_true')
    p.add_argument('--templates', type=Path)
    args = p.parse_args()
    if not args.generate_only and not args.library:
        p.error('--library is required for simulation; use --generate-only to only generate')
    workdir = args.workdir.resolve()
    before = set(workdir.iterdir()) if workdir.exists() else set()
    generate = [sys.executable, str(ROOT / 'recipe_generate.py'), *args.inputs, '--workdir', str(workdir)]
    templates = args.templates or (args.library / 'templates' if args.library and (args.library / 'templates').exists() else None)
    if templates:
        generate += ['--templates', str(templates.resolve())]
    subprocess.run(generate, check=True)
    directories = sorted(set(workdir.iterdir()) - before)
    if args.generate_only:
        return
    failures = []
    for folder in directories:
        for script in ('prepare_system.py', 'run_md.py', 'analyze.py'):
            command = [sys.executable, str(folder / script)]
            if script == 'prepare_system.py':
                command += ['--library', str(args.library.resolve())]
                if args.auto_parameterize:
                    command.append('--auto-parameterize')
            with (folder / (script + '.log')).open('w') as log:
                status = subprocess.run(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT).returncode
            if status:
                failures.append({'recipe': folder.name, 'stage': script, 'returncode': status})
                break
            print(f'{folder.name}: {script} complete', flush=True)
    (workdir / 'batch_status.json').write_text(json.dumps({'recipes': [f.name for f in directories], 'failures': failures}, indent=2))
    if failures:
        p.exit(1, 'Some recipes failed; inspect batch_status.json and stage logs.\n')


if __name__ == '__main__':
    main()
