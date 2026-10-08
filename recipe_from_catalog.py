#!/usr/bin/env python3
"""Create standard recipe JSON from catalog names and mass fractions."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from electrolyte.recipe import validate

ROOT=Path(__file__).resolve().parent


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--name',required=True)
    p.add_argument('--solvents',nargs='+',required=True,help='EC:0.30 EMC:0.55')
    p.add_argument('--additives',nargs='*',default=[])
    p.add_argument('--salts',nargs='*',default=[])
    p.add_argument('--temperature',type=float,default=298.15)
    p.add_argument('--pressure',type=float,default=1.0)
    p.add_argument('--box-nm',nargs=3,type=float,required=True)
    p.add_argument('--total-molecules',type=int,default=1000)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    catalog=json.loads((ROOT/'library/catalog/index.json').read_text())
    lookup={e['name']:e for e in catalog['species']+catalog['salts']}
    recipe={'recipe_name':args.name,'time':datetime.now(timezone.utc).isoformat(),
            'purity_policy':'reject','simulation':{'temperature':args.temperature,'pressure':args.pressure,
             'units':{'temperature':'K','pressure':'bar','concentration':'mol/L','box':'nm'},
             'box_nm':args.box_nm,'total_molecules':args.total_molecules}}
    for group,tokens in [('solvents',args.solvents),('additives',args.additives),('salts',args.salts)]:
        entries=[]
        for token in tokens:
            name,fraction=token.rsplit(':',1)
            if name not in lookup:p.error('unknown catalog name: '+name)
            e=lookup[name]
            if group=='salts' and name not in {s['name'] for s in catalog['salts']}:p.error('expected lithium salt name')
            if group!='salts' and e.get('category') not in ('solvent','additive'):p.error('expected neutral solvent/additive')
            entries.append({k:e[k] for k in ('name','full_name','smiles','molar_mass')}|{'mass_fraction':float(fraction),'purity':1.0})
        recipe[group]=entries
    recipe=validate(recipe)
    if args.out.exists():p.error('output already exists')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    args.out.write_text(json.dumps(recipe,ensure_ascii=False,indent=2))
    print(args.out)


if __name__=='__main__':main()
