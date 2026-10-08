#!/usr/bin/env python3
"""Preserve a sourced Li+ candidate; no claim of nonaqueous validation."""
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
import openmm.app
from rdkit import Chem
from electrolyte.parameters import key, validate_bundle

ROOT=Path(__file__).resolve().parent


def main():
    path=Path(openmm.app.__file__).parent/'data/amber14/tip3p.xml'
    xml=ET.parse(path).getroot()
    typ=next(x for x in xml.find('AtomTypes') if x.attrib.get('element')=='Li')
    nb=next(x for x in xml.find('NonbondedForce') if x.attrib.get('type')==typ.attrib['name'])
    out=ROOT/'library/profiles/gaff2-am1bcc-fullcharge-v1'/key('[Li+]')
    out.mkdir(exist_ok=False)
    mol=Chem.MolFromSmiles('[Li+]');conf=Chem.Conformer(1);conf.SetAtomPosition(0,(0,0,0));mol.AddConformer(conf)
    Chem.MolToPDBFile(mol,str(out/'molecule.pdb'))
    name=next(l for l in (out/'molecule.pdb').read_text().splitlines() if l.startswith('HETATM'))[12:16].strip()
    mass=float(typ.attrib['mass']);sigma=float(nb.attrib['sigma']);epsilon=float(nb.attrib['epsilon'])
    (out/'molecule.itp').write_text(f'[ moleculetype ]\nLi 3\n[ atoms ]\n1 JC_LI 1 LI {name} 1 1.0 {mass}\n')
    (out/'atomtypes.atp').write_text(f'[ atomtypes ]\nJC_LI JC_LI 3 {mass:.8f} 0 A {sigma} {epsilon}\n')
    (out/'metadata.json').write_text(json.dumps({'name':'Li','smiles':'[Li+]','forcefield':'GAFF2',
       'profile':'gaff2-am1bcc-fullcharge-v1','ion_model':'Joung-Cheatham TIP3P; transferred candidate',
       'source':'OpenMM amber14/tip3p.xml from AmberTools frcmod.ionsjc_tip3p',
       'source_url':'https://github.com/openmm/openmm/blob/master/wrappers/python/openmm/app/data/amber14/tip3p.xml',
       'source_doi':'10.1021/jp8001614','source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
       'charge_scale':1.0,'units':{'sigma':'nm','epsilon':'kJ/mol','mass':'g/mol'},
       'parameters':{'sigma':sigma,'epsilon':epsilon,'mass':mass},
       'validation':{'level':'structural_check','physical_validation':False},
       'limitations':['This ion model was developed for TIP3P water. Structural AMBER compatibility does not demonstrate validity in carbonate/ether electrolytes. Validate before quantitative use.'],
       'compatibility':'12-6 LJ, full +1 charge, Lorentz-Berthelot; GAFF2 here names assembly convention, not the origin of this ion'},indent=2))
    (out/'source_tip3p.xml').write_bytes(path.read_bytes())
    validate_bundle(out,{'smiles':'[Li+]','formal_charge':1})
    (out/'bundle_hashes.json').write_text(json.dumps({f:hashlib.sha256((out/f).read_bytes()).hexdigest() for f in ('molecule.itp','atomtypes.atp','molecule.pdb','metadata.json')},indent=2))
    print(out)


if __name__=='__main__':main()
