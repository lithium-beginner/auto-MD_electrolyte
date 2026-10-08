#!/usr/bin/env python3
import argparse
import csv
from collections import Counter
import json
import math
from pathlib import Path
from electrolyte.transport import KB, E, unwrap_com, einstein_curves, fit_slope, viscosity


def main():
    p = argparse.ArgumentParser(description='RDF, solvation, diffusion and conductivity analysis')
    p.add_argument('--workdir', type=Path, default=Path('.'))
    p.add_argument('--config', type=Path)
    p.add_argument('--stress-csv', type=Path, help='CSV columns: time_ps,Pxy_bar,Pxz_bar,Pyz_bar from a validated NVT pressure-tensor reporter')
    args = p.parse_args()
    root = args.workdir.resolve()
    if not (root / 'completed.json').exists():
        p.error('MD has not completed')
    import numpy as np
    import MDAnalysis as mda
    from MDAnalysis.analysis.rdf import InterRDF
    from MDAnalysis.lib.distances import distance_array
    config = json.loads((args.config or root / 'templates/analysis.json').read_text())
    meta = json.loads((root / 'run_metadata.json').read_text())
    manifest = json.loads((root / 'manifest.json').read_text())
    u = mda.Universe(str(root / 'production.pdb'), str(root / 'trajectory.dcd'))
    cations = u.select_atoms(config['cation_selection'])
    donors = u.select_atoms(config['donor_selection'])
    anion_sites = u.select_atoms(config['anion_selection'])
    has_cations = any(sp['formal_charge'] > 0 and sp['count'] > 0 for sp in manifest['species'])
    if has_cations and (not len(cations) or not len(donors)):
        raise ValueError('empty cation or donor selection: edit analysis config for this chemistry')
    if np.intersect1d(cations.indices, donors.indices).size:
        raise ValueError('cation and donor selections must not overlap')
    boxes = np.array([ts.dimensions.copy() for ts in u.trajectory], dtype=np.float64)
    if not np.allclose(boxes[:, 3:], 90, atol=1e-3) or not np.allclose(boxes[:, :3], boxes[0, :3], atol=1e-3):
        raise ValueError('transport implementation requires fixed orthorhombic NVT box')
    if config['rdf_range_A'][1] >= min(boxes[0, :3]) / 2:
        raise ValueError('RDF maximum must be below half the smallest box length')
    out = root / 'results'
    out.mkdir(exist_ok=True)
    if len(cations) and len(donors):
        rdf = InterRDF(cations, donors, nbins=config['rdf_bins'], range=tuple(config['rdf_range_A'])).run()
        np.savetxt(out / 'rdf_cation_donor.csv', np.c_[rdf.results.bins, rdf.results.rdf], delimiter=',', header='r_A,g_r', comments='')
    if len(cations) and len(anion_sites):
        rdf_anion = InterRDF(cations, anion_sites, nbins=config['rdf_bins'], range=tuple(config['rdf_range_A'])).run()
        np.savetxt(out / 'rdf_cation_anion.csv', np.c_[rdf_anion.results.bins, rdf_anion.results.rdf], delimiter=',', header='r_A,g_r', comments='')
    species = {sp['id']: sp for sp in manifest['species']}
    residues = list(u.residues)
    expected_ids = [sp['id'] for sp in manifest['species'] for _ in range(sp['count'])]
    if [r.resname for r in residues] != expected_ids:
        raise ValueError('trajectory residue ordering differs from manifest')
    charges = np.array([species[r.resname]['formal_charge'] for r in residues])
    coms, environments, coordination = [], Counter(), Counter()
    contact_counts = Counter()
    cutoff = config['coordination_cutoff_A']
    if cutoff <= 0 or cutoff >= min(boxes[0, :3]) / 2:
        raise ValueError('invalid coordination cutoff')
    # Masses must come from the force-field topology, not element inference.
    from electrolyte.parameters import sections
    for residue in residues:
        atom_rows = sections((root / 'parameters' / residue.resname / 'molecule.itp').read_text())['atoms']
        masses = [float(a[7]) for a in atom_rows]
        if len(masses) != len(residue.atoms) or min(masses) <= 0:
            raise ValueError('invalid topology masses')
        residue.atoms.masses = masses
    for ts in u.trajectory:
        lengths = ts.dimensions[:3]
        coords = []
        for residue in residues:
            xyz = residue.atoms.positions.copy()
            # Molecules were output whole by OpenMM; minimum-image relative to first atom.
            xyz = xyz[0] + (xyz - xyz[0]) - lengths * np.round((xyz - xyz[0]) / lengths)
            coords.append(np.average(xyz, axis=0, weights=residue.atoms.masses))
        coms.append(coords)
        dist = distance_array(cations.positions, donors.positions, box=ts.dimensions)
        anion_resids = {r.ix for r in residues if species[r.resname]['role'] == 'anion'}
        for row in dist:
            selected = donors[row < cutoff]
            coordination[len(selected)] += 1
            unique = {atom.residue.ix: atom.residue.resname for atom in selected}
            composition = Counter(unique.values())
            label = '+'.join(f'{sid}:{n}' for sid, n in sorted(composition.items())) or 'empty'
            environments[label] += 1
            n_anions = len(anion_resids.intersection(unique))
            contact_counts['0_anions' if n_anions == 0 else '1_anion' if n_anions == 1 else '2plus_anions'] += 1
    com = unwrap_com(np.asarray(coms), boxes[0, :3])
    # Remove global mass-center drift. Collective neutral charge displacement is invariant.
    molecular_masses = np.array([r.atoms.masses.sum() for r in residues])
    com -= np.average(com, axis=1, weights=molecular_masses)[:, None, :]
    t, msd, collective, origins = einstein_curves(com, charges, meta['frame_dt_ps'], config.get('max_lag_fraction', 0.5))
    volume_m3 = float(np.prod(boxes[0, :3], dtype=np.float64)) * 1e-30
    temperature = meta['settings']['temperature']
    diffusion, total_ne = {}, 0
    columns, labels = [t * 1e12, collective, origins], ['lag_ps', 'collective_charge_displacement_m2_e2', 'time_origins']
    for sid, sp in species.items():
        mask = np.array([r.resname == sid for r in residues])
        if not mask.any():
            continue
        curve = msd[:, mask].mean(axis=1)
        slope, r2 = fit_slope(t, curve, config['fit_fraction'])
        d = slope / 6
        diffusion[sid] = {'aliases': sp['aliases'], 'D_m2_s': d, 'fit_r2': r2}
        total_ne += mask.sum() * sp['formal_charge'] ** 2 * d
        columns.append(curve)
        labels.append(sid + '_MSD_m2')
    slope, r2 = fit_slope(t, collective, config['fit_fraction'])
    ne = E ** 2 * total_ne / (volume_m3 * KB * temperature)
    sigma = E ** 2 * slope / (6 * volume_m3 * KB * temperature)
    np.savetxt(out / 'einstein_curves.csv', np.array(columns).T, delimiter=',', header=','.join(labels), comments='')
    denominator = sum(environments.values())
    report = {'status': 'screening estimates; convergence must be checked',
              'volume_nm3': float(volume_m3 / 1e-27), 'diffusion': diffusion,
              'conductivity': {'NE_S_m': float(ne), 'collective_S_m': float(sigma), 'collective_fit_r2': r2,
                               'collective_to_NE': float(sigma / ne) if ne > 0 else None},
              'coordination_number_distribution': {str(k): v / denominator for k, v in coordination.items()},
              'solvation_composition_fractions': {k: v / denominator for k, v in environments.items()},
              'local_anion_contact_fractions': {k: v / denominator for k, v in contact_counts.items()},
              'solvation_definition': 'Unique donor-bearing molecules inside cation-donor cutoff; contact classes are not full SSIP/CIP/AGG cluster labels.',
              'realized_salt_concentration_mol_L': {c['name']: c['formula_units'] / 6.02214076e23 / (volume_m3 * 1000)
                                                   for c in manifest['components'] if c['group'] == 'salts'},
              'warnings': ['Fit window and RDF/coordination cutoffs need chemistry-specific validation.',
                           'PBC unwrapping assumes each molecule moves less than half a box between stored frames.',
                           'Negative slopes are reported, not clipped; they indicate unreliable transport fits.',
                           'Independent replicas and block/convergence analysis required before quantitative conclusions.'],
              'viscosity': {'status': 'not computed: pressure-tensor time series required'}}
    with (root / 'thermodynamics.csv').open() as handle:
        reader = csv.DictReader(line.lstrip('#') for line in handle)
        rows = list(reader)
    report['thermodynamics'] = {}
    for field in ('Temperature (K)', 'Density (g/mL)', 'Volume (nm^3)', 'Potential Energy (kJ/mole)'):
        if rows and field in rows[0]:
            values = np.array([float(row[field]) for row in rows])
            report['thermodynamics'][field] = {'mean': float(values.mean()), 'std': float(values.std()),
                'first_half_mean': float(values[:max(1, len(values)//2)].mean()),
                'second_half_mean': float(values[len(values)//2:].mean())}
    if args.stress_csv:
        stress = np.loadtxt(args.stress_csv, delimiter=',', skiprows=1)
        if stress.ndim != 2 or stress.shape[1] != 4 or stress.shape[0] < 8:
            raise ValueError('stress CSV must have exactly four columns and at least eight rows')
        dt = np.diff(stress[:, 0])
        if not np.allclose(dt, dt[0]) or dt[0] <= 0:
            raise ValueError('stress sampling must be uniform and increasing')
        lags, acf, eta = viscosity(stress[:, 1:4], dt[0], volume_m3 / 1e-27, temperature)
        np.savetxt(out / 'viscosity_running_integral.csv', np.c_[lags, acf, eta], delimiter=',', header='lag_ps,stress_acf_Pa2,eta_Pa_s', comments='')
        report['viscosity'] = {'status': 'running integral only; choose and validate plateau externally'}
    (out / 'summary.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False))
    print(out / 'summary.json')


if __name__ == '__main__':
    main()
