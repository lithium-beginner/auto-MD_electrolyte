#!/usr/bin/env python3
import csv
import json
from pathlib import Path
from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolDescriptors, AllChem
from electrolyte.parameters import key
from library.catalog_seed import SOLVENTS, ADDITIVES, ANIONS

ROOT = Path(__file__).resolve().parent


def main():
    root = ROOT / 'library/catalog'
    root.mkdir(exist_ok=True, parents=True)
    items = []
    for category, records in [('solvent', SOLVENTS), ('additive', ADDITIVES), ('anion', ANIONS),
                               ('cation', [('Li', 'Lithium ion', '锂离子', '[Li+]')])]:
        for name, full, chinese, raw in records:
            mol = Chem.MolFromSmiles(raw)
            if mol is None:
                raise ValueError(f'invalid catalog SMILES: {name}')
            smiles = Chem.MolToSmiles(mol)
            charge = Chem.GetFormalCharge(mol)
            if charge != (-1 if category == 'anion' else 1 if category == 'cation' else 0):
                raise ValueError(f'incorrect catalog charge: {name}')
            entry = {'name': name, 'full_name': full, 'chinese_name': chinese, 'category': category,
                     'smiles': smiles, 'formal_charge': charge, 'molar_mass': Descriptors.MolWt(mol),
                     'formula': rdMolDescriptors.CalcMolFormula(mol), 'key': key(smiles),
                     'identity_status': 'RDKit structure/formula checked; nomenclature not independently certified',
                     'parameter_status': 'pending', 'validation_status': 'not_physically_validated',
                     'stereochemistry': 'unspecified where applicable', 'profiles': []}
            folder = root / name
            folder.mkdir(exist_ok=True)
            hmol = Chem.AddHs(mol)
            if AllChem.EmbedMolecule(hmol, randomSeed=2026) < 0:
                entry['geometry_status'] = 'embedding_failed'
            else:
                if AllChem.MMFFHasAllMoleculeParams(hmol):
                    AllChem.MMFFOptimizeMolecule(hmol)
                Chem.MolToMolFile(hmol, str(folder / 'identity.mol'))
                Chem.MolToPDBFile(hmol, str(folder / 'identity.pdb'))
                entry['geometry_status'] = 'RDKit starting geometry; not optimized quantum geometry'
            (folder / 'identity.json').write_text(json.dumps(entry, ensure_ascii=False, indent=2))
            items.append(entry)
    salts = []
    for name, full, chinese, raw in ANIONS:
        mol = Chem.MolFromSmiles('[Li+].' + raw)
        salts.append({'name': 'Li' + name, 'full_name': 'Lithium ' + full.lower(),
                      'anion': name, 'cation': 'Li', 'smiles': Chem.MolToSmiles(mol),
                      'molar_mass': Descriptors.MolWt(mol), 'formula': rdMolDescriptors.CalcMolFormula(mol),
                      'stoichiometry': {'Li': 1, name: 1}})
    payload = {'version': '0.2.0', 'species': items, 'salts': salts,
               'note': 'Identity catalog is not a numerical force-field library; check profiles/ for actual bundles.'}
    (root / 'index.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    with (root / 'index.csv').open('w') as handle:
        writer = csv.DictWriter(handle, fieldnames=['name','chinese_name','category','formula','molar_mass','smiles','key','parameter_status','validation_status'])
        writer.writeheader()
        writer.writerows({field: row[field] for field in writer.fieldnames} for row in items)
    print(f'{len(items)} species; {len(salts)} lithium salts')


if __name__ == '__main__':
    main()
