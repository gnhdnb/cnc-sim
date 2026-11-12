"""Reproducible, synthetic raster benchmark; no external NC download needed."""
import argparse
import json
import platform
from pathlib import Path
import sys
import time
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cnc_sim.engine import Stock,Machine,Simulator,warmup
from cnc_sim.tools import make_tool
from cnc_sim.gcode import Parser
from importlib.resources import files


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--pitch',type=float,default=.1)
    parser.add_argument('--layers',type=int,default=8)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    lines=['G21 G90 G17','S12000 M3','G0 X3 Y3 Z2']
    for layer in range(1,args.layers+1):
        z=-layer*.5
        lines.extend(['G0 Z2','G0 X3 Y3',f'G1 Z{z} F200'])
        for row,y in enumerate(np.arange(3,58,1.5)):
            lines.append(f'G1 Y{y:.3f} F700')
            xs=np.linspace(3,77,38)
            if row%2:xs=xs[::-1]
            for x in xs:lines.append(f'G1 X{x:.3f}')
    lines.extend(['G0 Z5','M5','M30'])
    began=time.perf_counter();warmup();jit=time.perf_counter()-began
    began=time.perf_counter();program=Parser(start=(0,0,5)).parse('\n'.join(lines));parse_time=time.perf_counter()-began
    stock=Stock([80,60,12],[0,0,-12],args.pitch)
    cutter=make_tool(1,dict(type='flat',diameter=3.175,flute_length=8,shoulder_length=8,shank_diameter=3.175,stickout=25,verified=True))
    machine=Machine(json.loads(files('cnc_sim').joinpath('data/default_machine.json').read_text()))
    simulator=Simulator(stock,{1:cutter},machine)
    report=simulator.run(program)
    result={key:report[key] for key in ['simulation_time_s','nominal_job_time_s','linearized_segments','removed_voxels','collision_count']}
    result.update(platform=platform.platform(),python=platform.python_version(),numpy=np.__version__,pitch_mm=args.pitch,
                  stock_mm=stock.dimensions.tolist(),grid_bytes=stock.nbytes,jit_warmup_s=jit,parse_s=parse_time,
                  note='Simulation time excludes JIT, initialization, parsing, UI and file export. Collisions enabled. Nominal CAD is unverified.')
    if args.output:args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
