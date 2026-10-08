#!/usr/bin/env python3
"""Minimization -> NVT -> NPT -> fixed-volume NVT production."""
import argparse
import hashlib
import json
from pathlib import Path
import platform as pyplatform


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--workdir', type=Path, default=Path('.'))
    args = p.parse_args()
    root = args.workdir.resolve()
    if (root / 'run_started.json').exists():
        p.error('run output exists; use a fresh prepared directory (no silent trajectory overwrite)')
    prepared = json.loads((root / 'prepared.json').read_text())
    for name, digest in prepared['sha256'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError(f'prepared artifact modified: {name}')
    from openmm import XmlSerializer, LangevinMiddleIntegrator, MonteCarloBarostat, Platform, unit, __version__
    from openmm.app import Simulation, PDBFile, DCDReporter, StateDataReporter, CheckpointReporter
    settings = json.loads((root / 'manifest.json').read_text())['recipe']['simulation']
    system = XmlSerializer.deserialize((root / 'system.xml').read_text())
    pdb = PDBFile(str(root / 'system.pdb'))
    temperature = settings['temperature'] * unit.kelvin
    barostat = MonteCarloBarostat(settings['pressure'] * unit.bar, temperature, 25)
    barostat.setRandomNumberSeed(settings['seed'] + 1)
    barostat.setFrequency(0)
    system.addForce(barostat)
    integrator = LangevinMiddleIntegrator(temperature, settings['friction_per_ps'] / unit.picosecond,
                                          settings['timestep_fs'] * unit.femtosecond)
    integrator.setRandomNumberSeed(settings['seed'])
    platform = Platform.getPlatformByName(settings['platform'])
    sim = Simulation(pdb.topology, system, integrator, platform)
    sim.context.setPositions(pdb.positions)
    provenance = {'openmm': __version__, 'python': pyplatform.python_version(), 'platform': platform.getName(),
                  'settings': settings, 'production_ensemble': 'NVT at final NPT volume',
                  'transport_note': 'Langevin thermostat can affect transport; validate friction dependence.'}
    (root / 'run_started.json').write_text(json.dumps(provenance, indent=2))
    sim.minimizeEnergy(maxIterations=5000)
    sim.context.setVelocitiesToTemperature(temperature, settings['seed'])
    equil_log = (root / 'equilibration.csv').open('w')
    sim.reporters.append(StateDataReporter(equil_log, settings['report_interval'], step=True, time=True,
                                           potentialEnergy=True, temperature=True, volume=True, density=True))
    sim.step(settings['nvt_steps'])
    barostat.setFrequency(25)
    # Reinitialize to update barostat frequency while retaining coordinates and velocities.
    sim.context.reinitialize(preserveState=True)
    sim.step(settings['npt_steps'])
    barostat.setFrequency(0)
    sim.context.reinitialize(preserveState=True)
    sim.reporters.clear()
    equil_log.close()
    state = sim.context.getState(positions=True, velocities=True)
    vectors = state.getPeriodicBoxVectors()
    sim.topology.setPeriodicBoxVectors(vectors)
    with (root / 'production.pdb').open('w') as f:
        PDBFile.writeFile(sim.topology, state.getPositions(), f)
    sim.saveState(str(root / 'production_start.xml'))
    sim.currentStep = 0
    provenance['production_box_nm'] = [[v.value_in_unit(unit.nanometer) for v in vec] for vec in vectors]
    provenance['frame_dt_ps'] = settings['report_interval'] * settings['timestep_fs'] / 1000
    (root / 'run_metadata.json').write_text(json.dumps(provenance, indent=2))
    sim.reporters.append(DCDReporter(str(root / 'trajectory.dcd'), settings['report_interval'], enforcePeriodicBox=False))
    with (root / 'thermodynamics.csv').open('w') as log:
        sim.reporters.append(StateDataReporter(log, settings['report_interval'], step=True, time=True,
                            potentialEnergy=True, kineticEnergy=True, totalEnergy=True, temperature=True,
                            volume=True, density=True, speed=True))
        sim.reporters.append(CheckpointReporter(str(root / 'checkpoint.chk'), settings['report_interval'] * 10))
        sim.step(settings['production_steps'])
        sim.saveCheckpoint(str(root / 'checkpoint.chk'))
        sim.saveState(str(root / 'final_state.xml'))
    final = sim.context.getState(positions=True)
    with (root / 'final.pdb').open('w') as f:
        PDBFile.writeFile(sim.topology, final.getPositions(), f)
    (root / 'completed.json').write_text(json.dumps({'steps': sim.currentStep}))
    print('MD complete; run python analyze.py')


if __name__ == '__main__':
    main()
