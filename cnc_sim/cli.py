from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import numpy as np
from importlib.resources import files
from . import __version__
from .catalog import catalog
from .tools import load_tools, embedded_tools
from .gcode import Parser, NCError
from .engine import Stock, Machine, Simulator, save_result, warmup


def argument_parser():
    p=argparse.ArgumentParser(prog="cnc-sim",description="3-axis voxel CNC simulation and verification. Output: bool XYZ .npy + JSON report.",
                              formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    p.add_argument("nc",nargs="?",type=Path,help="NC/G-code file (UTF-8; BOM accepted)")
    p.add_argument("--stock",nargs=3,type=float,metavar=("X","Y","Z"),help="Stock dimensions in mm")
    p.add_argument("--stock-origin",nargs=3,type=float,metavar=("X","Y","Z"),help="Stock minimum corner; default (0,0,-height), top/front/left NC origin")
    p.add_argument("--pitch",type=float,default=.1,help="Voxel size in mm")
    p.add_argument("--tools",type=Path,help="JSON tools indexed by actual NC T number; overrides embedded @MKR tools")
    p.add_argument("--machine",type=Path,help="JSON machine/fixtures/offsets/G28; default: bundled unverified nominal machine profile")
    p.add_argument("--start",nargs=3,type=float,metavar=("X","Y","Z"),help="Actual initial tip position in the simulation frame; default assumed (0,0,5)")
    p.add_argument("--initial-tool",type=int,default=1,help="Tool installed at program entry")
    p.add_argument("--rapid-feed",type=float,default=2400.,help="Default rapid feed in mm/min; affects time only")
    p.add_argument("--arc-tolerance",type=float,default=None,help="Arc chord error in mm; default pitch/20")
    p.add_argument("--profile-tolerance",type=float,default=None,help="Curved tool profile chord error in mm; default pitch/20")
    p.add_argument("--collision-margin",type=float,default=0.,help="Inflate collision envelopes by this many mm; may create conservative false positives")
    p.add_argument("--metrics-period",type=float,default=.1,help="Maximum dynamic-metric interval, seconds")
    p.add_argument("--metrics-distance",type=float,default=1.,help="Maximum travel per dynamic-metric interval, mm")
    p.add_argument("--max-metric-samples",type=int,default=2_000_000,help="Time-series allocation guard")
    p.add_argument("-o","--output",type=Path,default=Path("result.npy"),help="Final stock file; existing output is replaced after successful simulation")
    p.add_argument("--visualize",action="store_true",help="Open the optional Qt/OpenGL playback window")
    p.add_argument("--memmap",action="store_true",help="Use a temporary disk-backed working grid instead of a RAM allocation")
    p.add_argument("--max-voxels",type=int,default=2_000_000_000,help="Allocation guard (one byte per voxel); increase explicitly for larger jobs")
    p.add_argument("--block-delete",action="store_true",help="Skip NC blocks starting with /; default executes them")
    p.add_argument("--json",action="store_true",help="Write the final machine-readable report to stdout; progress goes to stderr")
    p.add_argument("--quiet",action="store_true",help="Suppress progress on stderr")
    p.add_argument("--list-tools",action="store_true",help="List the bundled tool catalog as JSON and exit")
    p.add_argument("--version",action="version",version=__version__)
    return p


def prepare(args):
    if args.nc is None or args.stock is None:raise ValueError("An NC file and --stock X Y Z are required")
    if args.output.suffix.lower()!=".npy":raise ValueError("--output must end in .npy")
    if args.output.resolve()==args.nc.resolve():raise ValueError("Output cannot overwrite the NC input")
    dimensions=np.asarray(args.stock,dtype=float)
    origin=args.stock_origin if args.stock_origin is not None else (0.,0.,-dimensions[2])
    stock=Stock(dimensions,origin,args.pitch)
    if args.max_voxels<=0 or stock.nbytes>args.max_voxels:
        raise ValueError(f"Grid needs {stock.nbytes:,} bytes / voxels; exceeds --max-voxels {args.max_voxels:,}")
    data=args.nc.read_bytes()
    text=data.decode("utf-8-sig")
    profile_tol=args.profile_tolerance if args.profile_tolerance is not None else args.pitch/20
    arc_tol=args.arc_tolerance if args.arc_tolerance is not None else args.pitch/20
    if profile_tol<=0 or profile_tol>args.pitch/2 or arc_tol<=0 or arc_tol>args.pitch/2:
        raise ValueError("Arc/profile tolerances must be positive and <= pitch/2")
    tools=load_tools(args.tools,profile_tol) if args.tools else {}
    embedded,warnings=embedded_tools(text,profile_tol,skip=tools)
    tools={**embedded,**tools}
    if not tools:raise ValueError("NC has no usable embedded tool geometry; supply --tools tools.json")
    machine_data=(json.loads(args.machine.read_text(encoding="utf-8-sig")) if args.machine else
                  json.loads(files("cnc_sim").joinpath("data/default_machine.json").read_text(encoding="utf-8")))
    machine=Machine(machine_data)
    parser=Parser(start=args.start if args.start is not None else (0,0,5),initial_tool=args.initial_tool,
                  rapid_feed=args.rapid_feed,arc_tolerance=arc_tol,
                  work_offsets=machine_data.get("work_offsets"),machine_origin=machine_data.get("machine_origin"),
                  clearance_moves=machine_data.get("clearance_moves"),tool_change_moves=machine_data.get("tool_change_moves"),
                  block_delete=args.block_delete)
    program=parser.parse(text)
    missing={m.tool for m in program.moves}-set(tools)
    if missing:raise ValueError(f"Missing geometry for T numbers: {sorted(missing)}")
    extra={"input":{"nc_file":args.nc.name,"nc_sha256":hashlib.sha256(data).hexdigest(),
                    "initial_tip_mm":parser.start.tolist(),"initial_tool":args.initial_tool,
                    "rapid_feed_mm_min":args.rapid_feed,"block_delete":args.block_delete},
           "arc_chord_tolerance_mm":arc_tol,"profile_chord_tolerance_mm":profile_tol,
           "voxel_center_to_corner_mm":3**.5*args.pitch/2}
    return stock,tools,machine,program,warnings,extra


def main(argv=None):
    args=argument_parser().parse_args(argv)
    if args.list_tools:
        print(json.dumps(catalog(),indent=2));return 0
    working=None;sim=None
    try:
        stock,tools,machine,program,warnings,extra=prepare(args)
        if not args.quiet:
            print(f"Grid {stock.shape}: {stock.nbytes/1024**2:.1f} MiB; {len(program.moves):,} segments; compiling/warming kernels…",file=sys.stderr)
        grid=None
        if args.memmap:
            working=tempfile.TemporaryDirectory(prefix="cnc-sim-")
            grid=np.lib.format.open_memmap(Path(working.name)/"working.npy",mode="w+",dtype=np.bool_,shape=stock.shape)
        sim=Simulator(stock,tools,machine,grid=grid,margin=args.collision_margin,
                      start_verified=args.start is not None,warnings=warnings,
                      metrics_period=args.metrics_period,metrics_distance=args.metrics_distance,
                      max_metric_samples=args.max_metric_samples)
        if args.visualize:
            try:from .viewer import launch
            except ImportError as exc:raise ValueError('Viewer dependencies missing. Run: python -m pip install ".[viewer]"') from exc
            if args.json:raise ValueError("--json is for headless runs; the viewer still writes a JSON report beside the .npy")
            return launch(sim,program,args.output,extra)
        began=time.perf_counter();warmup();extra["jit_warmup_s"]=time.perf_counter()-began
        last=[-1]
        def progress(fraction,line):
            percent=int(fraction*100)
            if not args.quiet and (percent//10!=last[0]//10 or percent==100):
                print(f"{percent}% · NC line {line}",file=sys.stderr);last[0]=percent
        report=sim.run(program,progress=progress)
        report.update(extra)
        report,path,report_path=save_result(args.output,sim.grid,report)
        if args.json:print(json.dumps(report,allow_nan=False))
        else:
            print(f"{report['status']}: {report['collision_count']} collision records; {report['simulation_time_s']:.3f} s simulation")
            print(path);print(report_path)
            for issue in report["incomplete_reasons"]:print("INCOMPLETE: "+issue,file=sys.stderr)
        return report["exit_code"]
    except (ValueError,OSError,KeyError,TypeError,OverflowError,MemoryError) as exc:
        error={"status":"error","exit_code":1,"error":str(exc),"line":getattr(exc,"line",None)}
        print(json.dumps(error) if args.json else f"ERROR: {exc}",file=sys.stdout if args.json else sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled; no completed result was written.",file=sys.stderr);return 130
    finally:
        if working:
            if sim is not None and isinstance(sim.grid,np.memmap):sim.grid._mmap.close()
            working.cleanup()


if __name__=="__main__":raise SystemExit(main())
