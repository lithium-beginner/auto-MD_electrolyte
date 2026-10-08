#!/usr/bin/env python3
"""Build auditable GAFF2/AM1-BCC candidate parameters; never claim experiment validation."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
from pathlib import Path
import shutil
import tempfile
from electrolyte.parameters import key, parameterize, validate_bundle, sections

ROOT = Path(__file__).resolve().parent
BUNDLES = ('molecule.itp', 'atomtypes.atp', 'molecule.pdb', 'metadata.json')


def smoke(folder):
    from openmm import Vec3, unit, VerletIntegrator, Context, Platform
    from openmm.app import GromacsTopFile, PDBFile, NoCutoff
    name = sections((folder / 'molecule.itp').read_text())['moleculetype'][0][0]
    topfile = folder / 'smoke.top'
    topfile.write_text('[ defaults ]\n1 2 yes 0.5 0.8333333333333333\n#include "atomtypes.atp"\n#include "molecule.itp"\n[ system ]\ncheck\n[ molecules ]\n' + name + ' 1\n')
    top = GromacsTopFile(str(topfile), periodicBoxVectors=(Vec3(5,0,0),Vec3(0,5,0),Vec3(0,0,5))*unit.nanometer)
    pdb = PDBFile(str(folder / 'molecule.pdb'))
    system = top.createSystem(nonbondedMethod=NoCutoff)
    integrator = VerletIntegrator(0.001*unit.picosecond)
    context = Context(system, integrator, Platform.getPlatformByName('Reference'))
    context.setPositions(pdb.positions)
    energy = context.getState(energy=True).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    if not math.isfinite(energy):
        raise ValueError('nonfinite isolated-molecule energy')
    return {'test': 'OpenMM isolated-molecule finite energy', 'energy_kJ_mol': energy,
            'physical_validation': False}


def build(entry, target):
    folder = target / key(entry['smiles'])
    if folder.exists():
        validate_bundle(folder, {'smiles': entry['smiles'], 'formal_charge': entry['formal_charge']})
        return {'name': entry['name'], 'status': 'existing', 'path': str(folder)}
    with tempfile.TemporaryDirectory(dir=target) as tmp:
        out = Path(tmp) / 'bundle'
        sp = {'id': entry['name'][:3].upper(), 'smiles': entry['smiles'], 'aliases': [entry['name']],
              'formal_charge': entry['formal_charge']}
        try:
            parameterize(sp, out, automatic=True)
            problems = []
            for f in out.rglob('*.frcmod'):
                if 'ATTN' in f.read_text():
                    problems.append(str(f.relative_to(out)))
            for atom in sections((out / 'molecule.itp').read_text())['atoms']:
                if atom[1].lower().endswith('_du') or atom[1].lower() == 'du':
                    problems.append('dummy atom type')
            if problems:
                raise ValueError('parameter gaps require review: ' + ', '.join(problems))
            # Restore a fixed residue/name after parameter normalization.
            check = smoke(out)
            meta = json.loads((out / 'metadata.json').read_text())
            meta.update(name=entry['name'], profile='gaff2-am1bcc-fullcharge-v1', charge_scale=1.0,
                        validation={'level': 'structural_and_energy_check', 'checks': [check], 'physical_validation': False})
            (out / 'metadata.json').write_text(json.dumps(meta, indent=2))
            (out / 'bundle_hashes.json').write_text(json.dumps({f: hashlib.sha256((out/f).read_bytes()).hexdigest() for f in BUNDLES}, indent=2))
            out.rename(folder)
            return {'name': entry['name'], 'status': 'structural_and_energy_check', 'key': entry['key']}
        except Exception as exc:
            failed = target / '_failed' / entry['name']
            if out.exists():
                failed.parent.mkdir(exist_ok=True)
                if not failed.exists():
                    shutil.copytree(out, failed)
            return {'name': entry['name'], 'status': 'failed', 'reason': str(exc)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--names', nargs='*')
    p.add_argument('--jobs', type=int, default=2)
    args = p.parse_args()
    catalog = json.loads((ROOT / 'library/catalog/index.json').read_text())
    entries = [e for e in catalog['species'] if e['category'] != 'cation' and (args.names is None or e['name'] in args.names)]
    target = ROOT / 'library/profiles/gaff2-am1bcc-fullcharge-v1'
    target.mkdir(parents=True, exist_ok=True)
    records = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        tasks = [pool.submit(build, e, target) for e in entries]
        for task in as_completed(tasks):
            result = task.result()
            records.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    previous = target / 'build_report.json'
    merged = {r['name']: r for r in json.loads(previous.read_text())} if previous.exists() else {}
    merged.update({r['name']: r for r in records})
    previous.write_text(json.dumps(list(merged.values()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
