import json
import numpy as np
import pytest
from cnc_sim.metrics import stock_approach_speed, METRIC_DTYPE
from cnc_sim.engine import Stock,Machine,Simulator,save_result,load_metrics,load_result
from cnc_sim.gcode import Parser
from cnc_sim.tools import make_tool


def cutter():
    return make_tool(1,dict(type='flat',diameter=1,flute_length=2,shoulder_length=2,
                           shank_diameter=1,stickout=10,verified=True))


def approach(grid,stock,pos,vel):
    return stock_approach_speed(grid,stock.origin,stock.pitch,cutter().cutting,
                           np.array(pos,dtype=float),np.array(vel,dtype=float))


def test_plunge_normal_component_threshold_and_retreat():
    s=Stock([10,10,4],[0,0,-4],.1);g=np.ones(s.shape,dtype=bool)
    assert approach(g,s,[5,5,20.01],[0,0,-100])==0
    assert approach(g,s,[5,5,20],[0,0,-100])==100
    assert approach(g,s,[5,5,5],[300,0,-100])==100
    assert approach(g,s,[5,5,5],[300,0,0])==0
    assert approach(g,s,[5,5,5],[0,0,100])==0
    assert approach(g,s,[5,5,5],[0,0,0])==0


@pytest.mark.parametrize('axis,direction',[(0,1),(0,-1),(1,1),(1,-1),(2,1),(2,-1)])
def test_all_six_surface_normals(axis,direction):
    s=Stock([4,4,4],[0,0,0],.1);g=np.ones(s.shape,dtype=bool)
    pos=np.array([2.,2.,1.]);v=np.zeros(3);v[axis]=direction*123
    pos[axis]=-5 if direction>0 else 9
    assert approach(g,s,pos,v)==123
    assert approach(g,s,pos,-v)==0


def test_remaining_stock_pocket_and_undercut():
    s=Stock([8,8,8],[0,0,-8],.1);g=np.ones(s.shape,dtype=bool)
    # A real 3D pocket: empty above -6, still a floor below it.
    g[20:60,20:60,20:]=False
    assert approach(g,s,[4,4,15],[0,0,-100])==0  # floor 21 mm below tip
    assert approach(g,s,[4,4,14],[0,0,-100])==100
    g[:]=False
    g[:,:,60:]=True  # ceiling above an undercut: upward movement approaches it.
    assert approach(g,s,[4,4,-6],[0,0,100])==100
    assert approach(g,s,[4,4,-6],[0,0,-100])==0


def test_rates_conserve_removed_volume_and_rapid_is_zero(tmp_path):
    s=Stock([6,4,2],[0,0,-2],.1)
    p=Parser(start=(-2,2,1)).parse('S12000 M3\nG1 Z-1 F100\nG1 X8 F200\nG0 Z3')
    sim=Simulator(s,{1:cutter()},Machine());r=sim.run(p)
    m=sim.metrics
    assert m.dtype==METRIC_DTYPE and len(m)>len(p.moves)
    dt=m['t_end_s']-m['t_start_s']
    assert (dt<=.1+1e-12).all()
    assert m['removed_mm3'].sum()==pytest.approx(r['removed_volume_mm3'])
    assert np.sum(m['removal_rate_mm3_min']*dt/60)==pytest.approx(r['removed_volume_mm3'])
    assert (m['removal_rate_mm3_min'][m['rapid']]==0).all()
    r,path,_=save_result(tmp_path/'result ü.npy',sim.grid,r)
    assert r['metrics']['samples']==len(m)
    # Existing consumers still see a plain bool grid with memory mapping.
    legacy=np.load(path,mmap_mode='r',allow_pickle=False)
    np.testing.assert_array_equal(legacy,sim.grid);legacy._mmap.close()
    np.testing.assert_array_equal(load_metrics(path),m)
    with open(path,'rb') as f:
        np.testing.assert_array_equal(np.load(f,allow_pickle=False),sim.grid)
        np.testing.assert_array_equal(np.load(f,allow_pickle=False),m)
    grid,rows=load_result(path)
    np.testing.assert_array_equal(rows,m);grid._mmap.close()
    plain=dict(sim.report(p))
    with pytest.raises(ValueError,match='metrics explicitly'):save_result(tmp_path/'bad.npy',sim.grid,plain)


def test_legacy_output_has_no_metrics_and_corruption_is_not_silenced(tmp_path):
    path=tmp_path/'old.npy';np.save(path,np.ones((2,3,4),dtype=bool))
    assert len(load_metrics(path))==0
    with open(path,'ab') as f:f.write(b'broken')
    with pytest.raises((ValueError,EOFError)):load_metrics(path)


def test_zero_duration_removal_and_allocation_guard():
    s=Stock([2,2,2],[0,0,-2],.1)
    p=Parser(start=(1,1,-1)).parse('S12000 M3\nG4 P0')
    sim=Simulator(s,{1:cutter()});r=sim.run(p)
    assert np.isnan(sim.metrics['removal_rate_mm3_min'][0])
    assert r['metrics']['undefined_rate_samples']==1
    assert sim.metrics['removed_mm3'][0]>0
    long=Parser().parse('G1 X100 F1')
    with pytest.raises(ValueError,match='samples'):
        Simulator(s,{1:cutter()},max_metric_samples=2).run(long)


def test_replay_keeps_export_and_metric_history_unchanged(tmp_path):
    from cnc_sim.engine import SnapshotCache
    from cnc_sim.replay import Replay
    s=Stock([6,4,2],[0,0,-2],.1)
    p=Parser(start=(-2,2,1)).parse('S12000 M3\nG1 Z-1 F100\nG1 X8 F200\nG0 Z3')
    sim=Simulator(s,{1:cutter()})
    cache=SnapshotCache(len(p.moves))
    report=sim.run(p,snapshots=cache)
    _,path,report_path=save_result(tmp_path/'replay.npy',sim.grid,report)
    before=path.read_bytes();before_report=report_path.read_bytes();metrics=sim.metrics.copy()
    final=sim.grid.copy()
    replay=Replay(sim,p,cache)
    for seconds in (p.duration/2,0,p.duration):replay.seek(seconds)
    np.testing.assert_array_equal(sim.grid,final)
    np.testing.assert_array_equal(sim.metrics,metrics)
    assert path.read_bytes()==before and report_path.read_bytes()==before_report
