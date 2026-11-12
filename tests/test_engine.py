import json
import numpy as np
import pytest
from carvera_sim.engine import Stock,Machine,Simulator,SnapshotCache,save_result
from carvera_sim.tools import make_tool,load_tools
from carvera_sim.gcode import Parser
from carvera_sim.replay import Replay
from carvera_sim.cli import main
from carvera_sim.mesh import stock_mesh


def tool(**kwargs):
    return make_tool(1,dict(type='flat',diameter=1,flute_length=3,shoulder_length=3,
                            shank_diameter=1,stickout=5,verified=True,**kwargs))


def machine(**kwargs):
    return Machine(dict(name='Synthetic test geometry',verified=True,tool_change_restores_tip=True,
      bodies=[dict(name=n,role=n,shape='cylinder',anchor='gauge',radius=r,z=[z,z+2])
              for n,r,z in [('holder',2,0),('spindle',3,2),('head',4,4)]],**kwargs))


def test_removal_and_spindle_state_and_rapid():
    stock=Stock([10,4,2],[0,0,-2],.1)
    p=Parser(start=(-2,2,1)).parse('S12000 M3\nG1 Z-1 F100\nG1 X12\nM5\nG1 Y3\nG1 X-2')
    sim=Simulator(stock,{1:tool()},machine());report=sim.run(p)
    assert report['removed_voxels']>0
    assert any(c['reason']=='spindle_off' for c in report['collisions'])
    assert report['exit_code']==2
    # The stopped spindle must leave the second slot uncut.
    assert sim.grid[50,30,:].all()
    p=Parser(start=(-2,2,-1)).parse('G0 X12')
    sim=Simulator(stock,{1:tool()},machine());report=sim.run(p)
    assert report['removed_voxels']==0
    assert any(c['reason']=='rapid_into_stock' for c in report['collisions'])


def test_head_holder_fixture_and_limits():
    stock=Stock([10,10,10],[0,0,-10],.1)
    p=Parser(start=(-10,5,-8)).parse('S12000 M3\nG1 X20 F500')
    sim=Simulator(stock,{1:tool()},machine(fixtures=[dict(name='thin clamp',min=[-5,4,-10],max=[-4.99,6,2])],
                                           travel_limits=dict(min=[-15,-10,-5],max=[30,20,20])))
    r=sim.run(p)
    assert {'holder','spindle','head'}.issubset({c['body'] for c in r['collisions']})
    assert any(c['target']=='thin clamp' for c in r['collisions'])
    assert any(c['reason']=='travel_limit' for c in r['collisions'])


def test_true_3d_undercut_and_output_roundtrip(tmp_path):
    spec=dict(type='t_slot',diameter=4,flute_length=1,shoulder_length=4,neck_diameter=1,
              shank_diameter=1,stickout=8,verified=True)
    stock=Stock([8,8,6],[0,0,-6],.1)
    sim=Simulator(stock,{1:make_tool(1,spec)},machine())
    p=Parser(start=(-4,4,-4)).parse('S12000 M3\nG1 X12 F500')
    r=sim.run(p)
    # Under the roof, away from the narrow neck: material/air/material along Z.
    assert sim.grid[40,55,5]
    assert not sim.grid[40,55,25]
    assert sim.grid[40,55,45]
    r,path,rpath=save_result(tmp_path/'test result.npy',sim.grid,r)
    out=np.load(path,mmap_mode='r')
    np.testing.assert_array_equal(out,sim.grid)
    assert out.dtype==np.bool_ and out.shape==(80,80,60)
    assert json.loads(rpath.read_text())['array']['axis_order']=='XYZ'
    out._mmap.close()


def test_checkpoints_backward_seek_and_fractional_replay():
    stock=Stock([6,4,2],[0,0,-2],.1)
    p=Parser(start=(-2,1,2)).parse('S12000 M3\nG1 Z-1 F100\nG1 X8\nG1 Y3\nG1 X-2\nG0 Z2')
    sim=Simulator(stock,{1:tool()},machine());cache=SnapshotCache(len(p.moves),count=3)
    sim.run(p,snapshots=cache);expected=sim.grid.copy()
    replay=Replay(sim,p,cache)
    for t in [0,p.duration*.2,p.duration*.6,p.duration*.1,p.duration*.3,p.duration*.99,p.duration]:replay.seek(t)
    np.testing.assert_array_equal(sim.grid,expected)
    replay.seek(0)
    assert sim.grid.all()


def test_all_axes_partial_stock_and_mesh():
    stock=Stock([1.04,2.06,.23],[-2,1,-.23],.1)
    sim=Simulator(stock,{1:tool()},machine())
    assert sim.grid.shape==(11,21,3)
    assert sim.grid.sum()==10*21*2
    v,f,stride=stock_mesh(sim.grid,stock,stride=1)
    assert len(f)==12
    assert np.isfinite(v).all()
    assert np.all(v>=stock.origin-1e-6)
    assert np.all(v<=stock.origin+stock.dimensions+1e-6)


def test_cli_headless_memmap_json_and_incomplete_exit(tmp_path,capsys):
    nc=tmp_path/'job ünicode with spaces.nc';nc.write_text('G21 G90\nS12000 M3\nG0 X1 Y1 Z1\nG1 Z-.5 F100\nG0 Z2\nM30')
    tools=tmp_path/'tools.json';tools.write_text(json.dumps({'tools':{'1':tool().spec}}))
    out=tmp_path/'result with spaces.npy'
    code=main([str(nc),'--stock','3','3','2','--tools',str(tools),'--start','0','0','2','--memmap','--quiet','--json','-o',str(out)])
    assert code==3  # Nominal CAD is deliberately unverified.
    r=json.loads(capsys.readouterr().out)
    assert r['status']=='incomplete' and r['removed_voxels']>0
    assert np.load(out).shape==(30,30,20)


def test_cli_rejects_unsupported_without_writing_result(tmp_path,capsys):
    nc=tmp_path/'bad.nc';nc.write_text('G1 X1 A90 F100')
    tools=tmp_path/'tools.json';tools.write_text(json.dumps({'tools':{'1':tool().spec}}))
    out=tmp_path/'bad.npy'
    assert main([str(nc),'--stock','3','3','2','--tools',str(tools),'--json','-o',str(out)])==1
    assert json.loads(capsys.readouterr().out)['status']=='error'
    assert not out.exists()


def test_initial_overlap_detected_and_stationary_rotating_dwell_removes():
    stock=Stock([3,3,2],[0,0,-2],.1)
    p=Parser(start=(1,1,-.5)).parse('S12000 M3\nG4 P1')
    sim=Simulator(stock,{1:tool()},machine());r=sim.run(p)
    assert r['removed_voxels']>0
    assert any(c['reason']=='initial_tool_overlap' for c in r['collisions'])


def test_configuration_typos_and_string_boolean_are_rejected():
    for config in ({'verified':'false'},{'tool_change_restores_tip':'false'},{'bodys':[]},
                   {'clearance_moves':[{'Z':20}]}):
        with pytest.raises(ValueError):Machine(config)
    for spec in ({'verified':'false'},{'noncut_profiel':[[1,1],[2,1]]}):
        params=tool().spec.copy();params.update(spec)
        with pytest.raises(ValueError):make_tool(1,params)

