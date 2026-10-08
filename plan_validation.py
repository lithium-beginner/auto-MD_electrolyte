#!/usr/bin/env python3
"""Generate physical-validation recipes and references; does not launch long jobs."""
import argparse
import csv
import json
import math
from pathlib import Path
from electrolyte.recipe import NA

ROOT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--profile',default='gaff2-am1bcc-fullcharge-v1')
    p.add_argument('--names',nargs='*')
    p.add_argument('--replicas',type=int,default=3)
    p.add_argument('--molecules',type=int,default=1000)
    args=p.parse_args()
    inventory=json.loads((ROOT/'library/inventory.json').read_text())
    source=ROOT/'upstream/combat/data.csv'
    rows=list(csv.DictReader(source.open()))
    by_smiles={}
    from rdkit import Chem
    for row in rows:
        if row.get('CanonicalSMILES'):
            by_smiles[Chem.MolToSmiles(Chem.MolFromSmiles(row['CanonicalSMILES']))]=row
    out=ROOT/'library/validation/physical'/args.profile
    out.mkdir(parents=True,exist_ok=True)
    plan=[]
    for e in inventory['species']:
        if e['category']!='solvent' or not any(x['name']==args.profile for x in e['profiles']):continue
        if args.names and e['name'] not in args.names:continue
        reference=by_smiles.get(e['smiles'],{})
        density=reference.get('Density','');temp=reference.get('DensityT','')
        verified=False
        try:
            density=float(density);temperature=float(temp)+273.15
            if not math.isfinite(density) or density<=0 or not math.isfinite(temperature):raise ValueError()
        except ValueError:
            density=1.0;temperature=298.15
        else:verified=True
        volume_nm3=args.molecules*e['molar_mass']/NA/density*1e21
        box=volume_nm3**(1/3)
        if box<=2:raise ValueError('increase molecule count for PME cutoff')
        paths=[]
        for rep in range(args.replicas):
            recipe={'recipe_name':f'validate_{e["name"]}_r{rep+1}','time':'2026-10-08',
                'solvents':[{k:e[k] for k in ('name','full_name','smiles','molar_mass')}|{'mass_fraction':1.0,'purity':1.0}],
                'additives':[],'salts':[], 'simulation':{'temperature':temperature,'pressure':1.,
                  'units':{'temperature':'K','pressure':'bar','concentration':'mol/L','box':'nm'},
                  'total_molecules':args.molecules,'box_nm':[box]*3,'timestep_fs':1,
                  'nvt_steps':100000,'npt_steps':5000000,'production_steps':20000000,
                  'report_interval':1000,'seed':2026+rep,'platform':'CPU'},
                'validation_target':{'property':'density_g_cm3','reference':density if verified else None,
                  'source':'ComBat data.csv' if verified else None,'reference_status':'source_verification_pending',
                  'notes':'Confirm phase, temperature, pressure, purity and original experimental citation before accepting.'}}
            path=out/(recipe['recipe_name']+'.json')
            if not path.exists():path.write_text(json.dumps(recipe,indent=2))
            paths.append(str(path.relative_to(ROOT)))
        plan.append({'name':e['name'],'profile':args.profile,'reference_density_g_cm3':density if verified else None,
                     'reference_temperature_K':temperature if verified else None,
                     'reference_status':'source_verification_pending','recipes':paths})
    (out/'plan.json').write_text(json.dumps({'jobs':plan,'run_status':'not_run',
                'acceptance_protocol':['Verify experimental references and liquid phase first.',
                  'Check NPT density equilibration; use independent replicas and block uncertainty.',
                  'Compare density, diffusion/viscosity and solvation across temperature/concentration.',
                  'Tune on training mixtures; validate on held-out mixtures; publish applicable range.']},indent=2))
    print(f'{len(plan)} solvent benchmarks, {len(plan)*args.replicas} replica recipes; not launched')


if __name__=='__main__':main()
