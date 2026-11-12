"""Native OpenGL playback benchmark; run on a desktop, optionally keep the window.

python scripts/benchmark_playback.py --seconds 10 --speed 10 --output playback.json
Actual viewport swaps and delivered playback updates are measured separately.
"""
import argparse,hashlib,json,platform,sys,time,tempfile
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6 import QtCore,QtWidgets
from carvera_sim.cli import argument_parser,prepare
from carvera_sim.engine import Simulator
from carvera_sim.viewer import Window


def main():
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=10)
    p.add_argument('--speed',type=float,default=10);p.add_argument('--output',type=Path,default=Path('playback.json'))
    p.add_argument('--quit-after',action='store_true');args=p.parse_args()
    if args.seconds<=0:p.error('--seconds must be positive')
    temporary=tempfile.TemporaryDirectory(prefix='carvera-playback-')
    directory=Path(temporary.name)
    lines=['G21 G90 G17','S12000 M3','G0 X5 Y5 Z3 F1000']
    for layer in (1,2,3):
        lines+=['G0 Z3 F1000','G0 X5 Y5 F1000',f'G1 Z{-layer} F100']
        for row,y in enumerate(range(5,56,2)):
            lines += [f'G1 Y{y} F600',f'G1 X{75 if row%2==0 else 5}']
    lines+=['G0 Z5 F1000','M5','M30']
    nc=directory/'raster.nc';nc.write_text('\n'.join(lines))
    tools=Path(__file__).resolve().parents[1]/'examples/tools.json'
    a=argument_parser().parse_args([str(nc),'--stock','80','60','12','--tools',str(tools),'--start','0','0','5'])
    stock,tool_map,machine,program,warnings,extra=prepare(a)
    sim=Simulator(stock,tool_map,machine,warnings=warnings)
    app=QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window=Window(sim,program,directory/'result.npy',extra)
    state={'started':False,'recording':False,'frames':[],'swaps':[]}

    def finish():
        elapsed=time.perf_counter()-state['start']
        state['recording']=False;window.pause()
        compute=np.array([f['frame_compute_ms'] for f in state['frames']])
        from OpenGL import GL
        window.view.makeCurrent()
        graphics={name:GL.glGetString(enum).decode() for name,enum in
                  (('vendor',GL.GL_VENDOR),('renderer',GL.GL_RENDERER),('version',GL.GL_VERSION))}
        window.view.doneCurrent()
        result={'platform':platform.platform(),'python':platform.python_version(),'grid_shape':list(stock.shape),
                'opengl':graphics,
                'pitch_mm':stock.pitch,'display_stride':window.detail.currentData(),'speed':args.speed,
                'elapsed_s':elapsed,'playback_frames':len(state['frames']),
                'playback_updates_per_second':len(state['frames'])/elapsed,
                'viewport_swaps_per_second':len(state['swaps'])/elapsed,
                'compute_median_ms':float(np.median(compute)) if len(compute) else None,
                'compute_p95_ms':float(np.percentile(compute,95)) if len(compute) else None,
                'last_nominal_time_s':state['frames'][-1]['time_s'] if state['frames'] else None,
                'note':'Native Qt/OpenGL window, full voxel detail; excludes initial verification, JIT and initial full mesh'}
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(result,indent=2))
        print(json.dumps(result,indent=2),flush=True)
        window.setWindowTitle('Carvera — playback benchmark complete')
        if args.quit_after:window.close()

    def begin():
        with (directory/'result.npy').open('rb') as stream:
            state['export_hash']=hashlib.file_digest(stream,'sha256').hexdigest()
        state['start']=time.perf_counter();state['recording']=True
        i=window.speed.findData(args.speed)
        if i<0:window.speed.addItem(f'{args.speed:g}×',args.speed);i=window.speed.count()-1
        window.speed.setCurrentIndex(i);window.start_playback()
        QtCore.QTimer.singleShot(round(args.seconds*1000),finish)

    def frame_received(frame):
        if not state['started']:
            state['started']=True;QtCore.QTimer.singleShot(1500,begin)
        if state['recording'] and frame['generation']==window.generation:
            state['frames'].append({'frame_compute_ms':frame['frame_compute_ms'],'time_s':frame['time_s']})

    window.worker.signals.frame.connect(frame_received)
    window.view.frameSwapped.connect(lambda:state['swaps'].append(time.perf_counter()) if state['recording'] else None)
    window.show();app.exec()
    if args.output.exists() and 'export_hash' in state:
        with (directory/'result.npy').open('rb') as stream:
            unchanged=hashlib.file_digest(stream,'sha256').hexdigest()==state['export_hash']
        result=json.loads(args.output.read_text())
        result['export_unchanged_by_playback']=unchanged
        args.output.write_text(json.dumps(result,indent=2))
    temporary.cleanup()
    if not args.output.exists():raise SystemExit('Playback benchmark did not complete')


if __name__=='__main__':main()
