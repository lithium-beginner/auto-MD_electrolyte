#!/usr/bin/env python3
"""Register a user-verified, GAFF2-compatible molecular parameter bundle."""
import argparse
import json
from pathlib import Path
import shutil
import tempfile
from electrolyte.parameters import key, validate_bundle


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--smiles', required=True)
    p.add_argument('--source', required=True, help='Paper DOI / parameter database version / charge scheme')
    p.add_argument('--itp', type=Path, required=True)
    p.add_argument('--pdb', type=Path, required=True)
    p.add_argument('--atomtypes', type=Path, required=True)
    p.add_argument('--library', type=Path, required=True)
    args = p.parse_args()
    from rdkit import Chem
    mol = Chem.MolFromSmiles(args.smiles)
    if mol is None or len(Chem.GetMolFrags(mol)) != 1:
        p.error('expected valid single-fragment SMILES; register ions individually')
    smiles = Chem.MolToSmiles(mol)
    sp = {'smiles': smiles, 'formal_charge': sum(a.GetFormalCharge() for a in mol.GetAtoms())}
    args.library.mkdir(parents=True, exist_ok=True)
    target = args.library / key(smiles)
    if target.exists():
        p.error(f'entry already exists: {target}')
    with tempfile.TemporaryDirectory(dir=args.library) as tmp:
        folder = Path(tmp) / 'bundle'
        folder.mkdir()
        for source, name in ((args.itp, 'molecule.itp'), (args.pdb, 'molecule.pdb'), (args.atomtypes, 'atomtypes.atp')):
            shutil.copy2(source, folder / name)
        (folder / 'metadata.json').write_text(json.dumps({'smiles': smiles, 'source': args.source,
                            'forcefield': 'GAFF2', 'status': 'user-supplied; compatibility must be reviewed'}, indent=2))
        validate_bundle(folder, sp)
        folder.rename(target)
    print(target)


if __name__ == '__main__':
    main()
