#!/usr/bin/env python3
"""Audit bundle integrity and expose missing species/salts without false validation labels."""
import csv
import hashlib
import json
from pathlib import Path
from electrolyte.parameters import validate_bundle

ROOT=Path(__file__).resolve().parent


def main():
    catalog=json.loads((ROOT/'library/catalog/index.json').read_text())
    profiles={p.name:p for p in (ROOT/'library/profiles').iterdir() if p.is_dir()}
    rows=[];index={}
    for e in catalog['species']:
        record=dict(e);record['profiles']=[]
        for profile,root in profiles.items():
            path=root/e['key']
            if not (path/'metadata.json').exists():continue
            meta=json.loads((path/'metadata.json').read_text())
            validate_bundle(path,e,meta['forcefield'])
            hashes=json.loads((path/'bundle_hashes.json').read_text())
            for name,digest in hashes.items():
                if hashlib.sha256((path/name).read_bytes()).hexdigest()!=digest:
                    raise ValueError(f'modified library bundle: {profile}/{e["name"]}/{name}')
            record['profiles'].append({'name':profile,'family':meta['forcefield'],
                                       'validation':meta['validation'],'path':str(path.relative_to(ROOT))})
        record['parameter_status']='available_candidate' if record['profiles'] else 'missing_or_failed'
        record['validation_status']='not_physically_validated'
        index[e['name']]=record;rows.append(record)
    salts=[]
    for salt in catalog['salts']:
        record=dict(salt)
        record['available_profiles']=[p for p in profiles if all(any(x['name']==p for x in index[ion]['profiles']) for ion in salt['stoichiometry'])]
        record['status']='available_candidate' if record['available_profiles'] else 'missing_or_failed'
        salts.append(record)
    report={'species':rows,'salts':salts,'summary':{'catalog_species':len(rows),
            'species_with_parameters':sum(bool(r['profiles']) for r in rows),
            'bundle_count':sum(len(r['profiles']) for r in rows),
            'salts_with_complete_profile':sum(bool(r['available_profiles']) for r in salts),
            'physically_validated_species':0}}
    (ROOT/'library/inventory.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    with (ROOT/'library/inventory.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['name','chinese_name','category','formula','molar_mass','parameter_status','profiles','validation_status'])
        for r in rows:writer.writerow([r[k] for k in ('name','chinese_name','category','formula','molar_mass','parameter_status')]+[';'.join(p['name'] for p in r['profiles']),r['validation_status']])
    catalog['species'] = rows
    catalog['salts'] = salts
    (ROOT/'library/catalog/index.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
    for entry in rows:
        (ROOT/'library/catalog'/entry['name']/'identity.json').write_text(json.dumps(entry,ensure_ascii=False,indent=2))
    with (ROOT/'library/salts.csv').open('w') as f:
        writer=csv.writer(f);writer.writerow(['name','smiles','molar_mass','status','profiles'])
        for salt in salts:writer.writerow([salt[k] for k in ('name','smiles','molar_mass','status')]+[';'.join(salt['available_profiles'])])
    print(json.dumps(report['summary']))


if __name__=='__main__':main()
