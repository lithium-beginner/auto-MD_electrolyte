#!/usr/bin/env python3
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
from electrolyte.parameters import parameterize, sections


def main():
    p = argparse.ArgumentParser(description='Parameterize, pack and assemble GROMACS topology')
    p.add_argument('--workdir', type=Path, default=Path('.'))
    p.add_argument('--library', type=Path, help='Parameter library compatible with the selected forcefield profile')
    p.add_argument('--auto-parameterize', action='store_true')
    args = p.parse_args()
    root = args.workdir.resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    family = manifest.get('forcefield_profile', {}).get('family', 'GAFF2')
    if (root / 'prepared.json').exists():
        p.error('already prepared; use a fresh work directory')
    if not shutil.which('packmol'):
        p.error('packmol executable missing')
    params = root / 'parameters'
    if params.exists():
        p.error('partial preparation exists: inspect logs and move parameters/ before retry')
    params.mkdir()
    for sp in manifest['species']:
        if sp['count']:
            parameterize(sp, params / sp['id'], args.library.resolve() if args.library else None, args.auto_parameterize, expected_forcefield=family)
    atomtypes = {}
    for sp in manifest['species']:
        if not sp['count']:
            continue
        for row in sections((params / sp['id'] / 'atomtypes.atp').read_text()).get('atomtypes', []):
            if row[0] in atomtypes and atomtypes[row[0]] != row:
                raise ValueError(f'conflicting atom type: {row[0]}')
            atomtypes[row[0]] = row
    for sp in manifest['species']:
        if sp['count']:
            for atom in sections((params / sp['id'] / 'molecule.itp').read_text())['atoms']:
                if atom[1] not in atomtypes:
                    raise ValueError(f'undefined atom type: {atom[1]}')
    top = ['#include "templates/defaults.itp"']
    # All atomtypes must precede all molecule definitions.
    top += [f'#include "parameters/{sp["id"]}/atomtypes.atp"' for sp in manifest['species'] if sp['count']]
    top += [f'#include "parameters/{sp["id"]}/molecule.itp"' for sp in manifest['species'] if sp['count']]
    top += ['[ system ]', manifest['recipe']['recipe_name'], '[ molecules ]']
    top += [f'{sp["id"]} {sp["count"]}' for sp in manifest['species'] if sp['count']]
    (root / 'topol.top').write_text('\n'.join(top) + '\n')
    box = [v * 10 for v in manifest['recipe']['simulation']['box_nm']]
    lines = ['tolerance 2.0', 'filetype pdb', 'output packed.pdb',
             f'seed {manifest["recipe"]["simulation"]["seed"]}']
    for sp in manifest['species']:
        if sp['count']:
            lines += [f'structure parameters/{sp["id"]}/molecule.pdb', f'  number {sp["count"]}',
                      '  inside box 0. 0. 0. ' + ' '.join(str(x) for x in box), 'end structure']
    (root / 'packmol.inp').write_text('\n'.join(lines) + '\n')
    with (root / 'packmol.inp').open() as inp, (root / 'packmol.log').open('w') as log:
        subprocess.run(['packmol'], cwd=root, stdin=inp, stdout=log, stderr=subprocess.STDOUT, check=True)
    from openmm import Vec3, unit
    from openmm.app import GromacsTopFile, PDBFile, PME, HBonds
    pdb = PDBFile(str(root / 'packed.pdb'))
    vectors = tuple(Vec3(*(v if i == j else 0 for j in range(3))) for i, v in enumerate(manifest['recipe']['simulation']['box_nm'])) * unit.nanometer
    topology = GromacsTopFile(str(root / 'topol.top'), periodicBoxVectors=vectors)
    packed_atoms, expected = list(pdb.topology.atoms()), list(topology.topology.atoms())
    if len(packed_atoms) != len(expected) or any(a.name != b.name or a.element != b.element for a, b in zip(packed_atoms, expected)):
        raise ValueError(f'Packmol atom order/elements disagree with topology: counts {len(packed_atoms)}/{len(expected)}, mismatches {[(a.name, str(a.element), b.name, str(b.element)) for a, b in zip(packed_atoms, expected) if a.name != b.name or a.element != b.element][:10]}')
    system = topology.createSystem(nonbondedMethod=PME, nonbondedCutoff=manifest['recipe']['simulation']['cutoff_nm'] * unit.nanometer, constraints=HBonds)
    from openmm import XmlSerializer
    (root / 'system.xml').write_text(XmlSerializer.serialize(system))
    with (root / 'system.pdb').open('w') as f:
        PDBFile.writeFile(topology.topology, pdb.positions, f)
    hashes = {str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
              for f in [root / 'manifest.json', root / 'topol.top', root / 'system.xml', root / 'system.pdb',
                        root / 'templates/defaults.itp', *sorted(params.rglob('*.itp')), *sorted(params.rglob('*.atp')), *sorted(params.rglob('metadata.json'))]}
    (root / 'prepared.json').write_text(json.dumps({'sha256': hashes}, indent=2))
    print('Prepared: system.xml, system.pdb, topol.top')


if __name__ == '__main__':
    main()
