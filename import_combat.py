#!/usr/bin/env python3
"""Convert CC BY 4.0 ComBat base parameters (repository also has MIT LICENSE), preserving original PDB atom order.
LAMMPS real -> GROMACS units. Source code is parsed as data, never imported/executed.
"""
import ast
import hashlib
import itertools
import json
from pathlib import Path
import shutil
import subprocess
import math
import numpy as np
from rdkit import Chem
from electrolyte.parameters import key, validate_bundle

ROOT = Path(__file__).resolve().parent
FAMILY = 'OPLS-AA-ComBat'


def literal(node):
    if isinstance(node, ast.Constant): return node.value
    if isinstance(node, (ast.List, ast.Tuple)): return [literal(x) for x in node.elts]
    if isinstance(node, ast.Dict):
        return {literal(k): literal(v) for k,v in zip(node.keys,node.values) if literal(k) != 'Molecule'}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub): return -literal(node.operand)
    if isinstance(node, ast.Call):
        call = ast.unparse(node.func)
        if call in ('OrderedDict', 'np.asarray') and len(node.args) == 1:
            return literal(node.args[0])
    raise ValueError('unsupported source expression: ' + ast.unparse(node))


def lookup(records, labels):
    values = []
    for record in records:
        if any(tuple(t) in (tuple(labels),tuple(labels[::-1])) for t in record['types']):
            values.append(record['coeffs'])
    if not values or any(v != values[0] for v in values):
        raise ValueError('missing/ambiguous coefficients: ' + str(labels))
    return values[0]


def topology(source_pdb, smiles):
    mol = Chem.MolFromPDBFile(str(source_pdb), removeHs=False, sanitize=False, proximityBonding=False)
    ref = Chem.AddHs(Chem.MolFromSmiles(smiles))
    if mol is None or mol.GetNumAtoms() != ref.GetNumAtoms():
        raise ValueError('PDB atom count differs from identity')
    def simple(m):
        graph=Chem.RWMol()
        for a in m.GetAtoms(): graph.AddAtom(Chem.Atom(a.GetAtomicNum()))
        for b in m.GetBonds(): graph.AddBond(b.GetBeginAtomIdx(),b.GetEndAtomIdx(),Chem.BondType.SINGLE)
        return graph.GetMol()
    mapping=simple(mol).GetSubstructMatch(simple(ref))
    if len(mapping) != ref.GetNumAtoms() or mol.GetNumBonds() != ref.GetNumBonds():
        raise ValueError('PDB CONECT graph differs from SMILES')
    bonds=sorted(tuple(sorted((b.GetBeginAtomIdx(),b.GetEndAtomIdx()))) for b in mol.GetBonds())
    neighbors={i:set() for i in range(mol.GetNumAtoms())}
    for a,b in bonds: neighbors[a].add(b);neighbors[b].add(a)
    angles=[(a,b,c) for b in neighbors for a,c in itertools.combinations(sorted(neighbors[b]),2)]
    torsions=[(a,b,c,d) for b,c in bonds for a in sorted(neighbors[b]-{c}) for d in sorted(neighbors[c]-{b}) if a != d]
    distances=np.full((len(neighbors),len(neighbors)),np.inf)
    for i in neighbors:
        distances[i,i]=0
        for j in neighbors[i]: distances[i,j]=1
    for k in neighbors: distances=np.minimum(distances,distances[:,k,None]+distances[None,k,:])
    pairs=[(a,b) for a,b in itertools.combinations(neighbors,2) if distances[a,b]==3]
    return mol,bonds,angles,torsions,pairs,distances


def render_block(name, rows):
    return '[ '+name+' ]\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n'


def convert(entry, data, source_pdb, out, commit, source_file):
    mol,bonds,angles,torsions,pairs,distances=topology(source_pdb, entry['smiles'])
    labels=data['Labels']; masses=data['Masses']; charges=data['Charges']
    if len(labels)!=mol.GetNumAtoms() or len(charges)!=len(labels): raise ValueError('source array length mismatch')
    if abs(sum(charges)-entry['formal_charge'])>1e-4: raise ValueError('source charge does not equal formal charge')
    types=list(masses)
    lj={t:(float(p[0])*4.184,float(p[1])/10) for t,p in zip(types,data['Nonbond'])}
    pdb_lines=[l for l in source_pdb.read_text().splitlines() if l.startswith(('ATOM  ','HETATM'))]
    atomnames=[l[12:16].strip() for l in pdb_lines]
    prefix='CMB_'+entry['name']+'_'
    type_z={}
    for label,atom in zip(labels,mol.GetAtoms()):
        if label in type_z and type_z[label]!=atom.GetAtomicNum(): raise ValueError('atomtype/element conflict')
        type_z[label]=atom.GetAtomicNum()
    out.mkdir(parents=True,exist_ok=False)
    shutil.copy2(source_pdb,out/'molecule.pdb')
    (out/'atomtypes.atp').write_text(render_block('atomtypes',[
        [prefix+t,prefix+t,type_z[t],format(masses[t],'.8f'),0,'A',lj[t][1],lj[t][0]] for t in types]))
    atomrows=[[i+1,prefix+t,1,entry['name'][:3],atomnames[i],1,charges[i],masses[t]] for i,t in enumerate(labels)]
    blocks=render_block('moleculetype',[[entry['name'],3]])+render_block('atoms',atomrows)
    bondrows=[]
    for a,b in bonds:
        k,r=lookup(data['Bonds'],[labels[a],labels[b]])
        bondrows.append([a+1,b+1,1,float(r)/10,float(k)*836.8])
    anglerows=[]
    for a,b,c in angles:
        k,theta=lookup(data['Angles'],[labels[a],labels[b],labels[c]])
        anglerows.append([a+1,b+1,c+1,1,float(theta),float(k)*8.368])
    torrows=[]
    for ids in torsions:
        coeff=lookup(data['Dihedrals'],[labels[i] for i in ids])
        if coeff[0]!='fourier' or len(coeff)!=2+3*int(coeff[1]): raise ValueError('unsupported Fourier source')
        for k,n,phase in zip(coeff[2::3],coeff[3::3],coeff[4::3]):
            torrows.append([*(i+1 for i in ids),9,float(phase),float(k)*4.184,int(n)])
    impropers=data.get('Improper Topologies') or []
    improperrows=[]
    for ids in impropers:
        coeff=lookup(data['Impropers'],[labels[i] for i in ids])
        if coeff[0]!='cvff': raise ValueError('unsupported source improper')
        _,k,d,n=coeff
        improperrows.append([*(i+1 for i in ids),4,0 if d==1 else 180,float(k)*4.184,int(n)])
    for name,rows in [('bonds',bondrows),('angles',anglerows),('pairs',[[a+1,b+1,1] for a,b in pairs]),('dihedrals',torrows+improperrows)]:
        if rows: blocks+=render_block(name,rows)
    (out/'molecule.itp').write_text(blocks)
    meta={'smiles':entry['smiles'],'name':entry['name'],'forcefield':FAMILY,'profile':'combat-opls-unscaled-v1',
          'source':'https://github.com/rashatwi/combat','upstream_commit':commit,'source_file':source_file,
          'source_doi':data.get('doi'), 'license':'ComBat database CC BY 4.0 per upstream README; repository MIT LICENSE retained; see DATA_ATTRIBUTION.md', 'charge_scale':1.0,
          'validation':{'level':'converted_pending_energy_check','physical_validation':False},
          'limitations':['Unscaled base parameters; published mixed-electrolyte workflow uses composition-dependent charge scaling. Not a reproduction of its screened model.']}
    (out/'metadata.json').write_text(json.dumps(meta,indent=2))
    validate_bundle(out,entry,FAMILY)
    # Independent LAMMPS-form analytical energies against OpenMM-converted topology.
    verify_energy(data,mol,bonds,angles,torsions,impropers,distances,out)
    meta['validation']['level']='structural_and_energy_equivalence_check'
    meta['validation']['checks']=['SMILES graph/PDB order/charge/mass checks','three geometries: LAMMPS-form vs OpenMM energies']
    (out/'metadata.json').write_text(json.dumps(meta,indent=2))
    (out/'source_parameters.json').write_text(json.dumps(data,indent=2))
    (out/'bundle_hashes.json').write_text(json.dumps({f:hashlib.sha256((out/f).read_bytes()).hexdigest() for f in ('molecule.itp','atomtypes.atp','molecule.pdb','metadata.json')},indent=2))


def phi(x,ids):
    a,b,c,d=x[list(ids)]
    v1=b-a;v2=c-b;v3=d-c
    n1=np.cross(v1,v2);n2=np.cross(v2,v3)
    return math.atan2(np.dot(np.cross(n1,n2),v2/np.linalg.norm(v2)),np.dot(n1,n2))


def analytic(data,x,bonds,angles,torsions,impropers,distances):
    labels=data['Labels'];types=list(data['Masses'])
    lj=dict(zip(types,data['Nonbond']))
    energy=[0.,0.,0.,0.]
    for a,b in bonds:
        k,r=lookup(data['Bonds'],[labels[a],labels[b]])
        energy[0]+=float(k)*(np.linalg.norm(x[a]-x[b])*10-float(r))**2*4.184
    for a,b,c in angles:
        k,t=lookup(data['Angles'],[labels[a],labels[b],labels[c]])
        v=x[a]-x[b];w=x[c]-x[b]
        theta=math.acos(np.clip(np.dot(v,w)/np.linalg.norm(v)/np.linalg.norm(w),-1,1))
        energy[1]+=float(k)*(theta-float(t)*math.pi/180)**2*4.184
    for ids in torsions:
        cf=lookup(data['Dihedrals'],[labels[i] for i in ids]);p=phi(x,ids)
        for k,n,d in zip(cf[2::3],cf[3::3],cf[4::3]):energy[2]+=float(k)*(1+math.cos(float(n)*p-float(d)*math.pi/180))*4.184
    for ids in impropers:
        _,k,d,n=lookup(data['Impropers'],[labels[i] for i in ids])
        energy[2]+=float(k)*(1+float(d)*math.cos(float(n)*phi(x,ids)))*4.184
    for a,b in itertools.combinations(range(len(x)),2):
        if distances[a,b]<3:continue
        scale=.5 if distances[a,b]==3 else 1.
        r=np.linalg.norm(x[a]-x[b]);ea,sa=map(float,lj[labels[a]]);eb,sb=map(float,lj[labels[b]])
        epsilon=math.sqrt(ea*eb)*4.184;sigma=math.sqrt(sa*sb)/10
        energy[3]+=scale*(4*epsilon*((sigma/r)**12-(sigma/r)**6)+138.93545764438198*data['Charges'][a]*data['Charges'][b]/r)
    return energy


def verify_energy(data,mol,bonds,angles,torsions,impropers,distances,out):
    from openmm import Context,Platform,VerletIntegrator,unit
    from openmm.app import GromacsTopFile,NoCutoff
    topfile=out/'energy_check.top'
    topfile.write_text('[ defaults ]\n1 3 yes 0.5 0.5\n#include "atomtypes.atp"\n#include "molecule.itp"\n[ system ]\ncheck\n[ molecules ]\n'+json.loads((out/'metadata.json').read_text())['name']+' 1\n')
    top=GromacsTopFile(str(topfile))
    system=top.createSystem(nonbondedMethod=NoCutoff,removeCMMotion=False)
    for f in system.getForces():
        f.setForceGroup({'HarmonicBondForce':1,'HarmonicAngleForce':2,'PeriodicTorsionForce':3}.get(type(f).__name__,4))
    integ=VerletIntegrator(.001*unit.picosecond)
    ctx=Context(system,integ,Platform.getPlatformByName('Reference'))
    x=np.array(mol.GetConformer().GetPositions())/10
    rng=np.random.default_rng(2026);checks=[]
    for trial in range(3):
        positions=x if trial==0 else x+rng.normal(0,.003,x.shape)
        ctx.setPositions(positions*unit.nanometer)
        observed=[ctx.getState(energy=True,groups=1<<i).getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole) for i in range(1,5)]
        expected=analytic(data,positions,bonds,angles,torsions,impropers,distances)
        np.testing.assert_allclose(observed,expected,rtol=2e-7,atol=.001)
        checks.append({'trial':trial,'source_LAMMPS_form_kJ_mol':expected,'OpenMM_kJ_mol':observed})
    (out/'energy_equivalence.json').write_text(json.dumps(checks,indent=2))


def main():
    upstream=ROOT/'upstream/combat'
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=upstream,text=True).strip()
    catalog=json.loads((ROOT/'library/catalog/index.json').read_text())['species']
    by_smiles={e['smiles']:e for e in catalog}
    root=ROOT/'library/profiles/combat-opls-unscaled-v1'
    root.mkdir(parents=True,exist_ok=True)
    templates=root/'templates';templates.mkdir(exist_ok=True)
    (templates/'defaults.itp').write_text('[ defaults ]\n1 3 yes 0.5 0.5\n')
    (templates/'profile.json').write_text(json.dumps({'name':'combat-opls-unscaled-v1','family':FAMILY,'defaults':['1','3','yes','0.5','0.5']},indent=2))
    shutil.copy2(ROOT/'templates/analysis.json',templates/'analysis.json')
    shutil.copy2(upstream/'LICENSE',root/'LICENSE.ComBat')
    sources=[]
    for f in (upstream/'force_field').glob('*.json'):
        data=json.loads(f.read_text());smiles=Chem.MolToSmiles(Chem.MolFromSmiles(data['smiles']))
        if smiles in by_smiles:sources.append((by_smiles[smiles],data,upstream/'pdb'/(f.stem+'.pdb'),str(f.relative_to(upstream))))
    tree=ast.parse((upstream/'scripts/run_md.py').read_text())
    for node in tree.body:
        if isinstance(node,ast.Assign) and isinstance(node.targets[0],ast.Name) and node.targets[0].id in ('li_param','tfsi_param','dol_param'):
            name={'li_param':'Li','tfsi_param':'TFSI','dol_param':'DOL'}[node.targets[0].id]
            entry=next(e for e in catalog if e['name']==name)
            sources.append((entry,literal(node.value),upstream/'pdb'/(name.lower()+'.pdb'),'scripts/run_md.py:'+node.targets[0].id))
    report=[]
    for entry,data,pdb,sourcefile in sources:
        out=root/key(entry['smiles'])
        if out.exists():continue
        try:
            convert(entry,data,pdb,out,commit,sourcefile)
            result={'name':entry['name'],'status':'structural_and_energy_equivalence_check','key':entry['key']}
        except Exception as exc:
            result={'name':entry['name'],'status':'failed','reason':str(exc)}
            if out.exists():
                failed=root/'_failed';failed.mkdir(exist_ok=True)
                out.rename(failed/entry['name'])
        print(json.dumps(result),flush=True);report.append(result)
    (root/'import_report.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':main()
