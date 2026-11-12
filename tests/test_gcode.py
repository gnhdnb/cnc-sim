import numpy as np
import pytest
from cnc_sim.gcode import Parser,NCError


def test_modal_units_offsets_incremental_and_local_rapid_feed():
    p=Parser(start=(0,0,5),rapid_feed=2400).parse('G21 G90\nG1 X10 F600\nG0 X20 F1200\nG1 X30\nG91\nX2\nM30\nG1 X999')
    assert len(p.moves)==4
    assert [m.t1-m.t0 for m in p.moves]==pytest.approx([1,.5,1,.2])
    np.testing.assert_allclose(p.moves[-1].end,[32,0,5])
    p=Parser().parse('G20 G90\nG1 X1 F10')
    assert p.moves[-1].end[0]==25.4
    assert p.duration==pytest.approx(6)
    p=Parser(machine_origin=(0,0,0)).parse('G10 L2 P2 X10 Y20 Z30\nG55\nG0 X1 Y2 Z3\nG92 X0\nG0 X2\nG92.1\nG0 X2')
    np.testing.assert_allclose(p.moves[-2].end,[13,22,33])
    np.testing.assert_allclose(p.moves[-1].end,[12,22,33])


@pytest.mark.parametrize('plane,start,code,end',[
    (17,(1,0,0),'G3 X0 Y1 I-1 J0',(0,1,0)),
    (18,(1,0,0),'G2 X0 Z1 I-1 K0',(0,0,1)),
    (19,(0,1,0),'G3 Y0 Z1 J-1 K0',(0,0,1))])
def test_arc_planes(plane,start,code,end):
    p=Parser(start=start).parse(f'G{plane} G90\n{code} F60')
    np.testing.assert_allclose(p.moves[-1].end,end)
    assert p.duration==pytest.approx(np.pi/2,abs=.008)
    for m in p.moves:assert np.all(m.end>=-1e-10)


def test_full_circle_helix_radius_and_inverse_time():
    p=Parser(start=(1,0,0)).parse('G17 G93\nG3 I-1 J0 Z-1 F2')
    assert p.duration==pytest.approx(30)
    np.testing.assert_allclose(p.moves[-1].end,[1,0,-1])
    short=Parser(start=(1,0,0)).parse('G3 X0 Y1 R1 F60')
    long=Parser(start=(1,0,0)).parse('G3 X0 Y1 R-1 F60')
    assert long.duration/short.duration==pytest.approx(3,abs=.02)


def test_arc_absolute_center_and_g53():
    p=Parser(start=(2,1,0)).parse('G90.1\nG3 X1 Y2 I1 J1 F60')
    assert p.duration==pytest.approx(np.pi/2,abs=.008)
    p=Parser(machine_origin=(10,20,30)).parse('G53 G0 X1 Y2 Z3')
    np.testing.assert_allclose(p.moves[-1].end,[11,22,33])


def test_cycles_and_dwell_and_clearance():
    p=Parser().parse('G21 G90\nS12000 M3\nG99 G83 X2 Y3 Z-3 R1 Q1 F120\nX4\nG80\nG4 P2')
    assert min(m.end[2] for m in p.moves)==-3
    np.testing.assert_allclose(p.moves[-1].end,[4,3,1])
    assert p.moves[-1].t1-p.moves[-1].t0==2
    p=Parser(clearance_moves=[{'z':10},{'x':0,'y':0}],start=(2,3,0)).parse('G28')
    np.testing.assert_allclose(p.moves[0].end,[2,3,10])
    np.testing.assert_allclose(p.moves[1].end,[0,0,10])


@pytest.mark.parametrize('text',[
    'G1 X1 A0 F100','G38.2 Z-10','G1 X#1','G1 X1 E2 F100','G41 D1',
    'G43 H1','G0 X1 X2','G0 G1 X1','G53 G0 X1','G28','M98 P1',
    'G2 X1 Y1 R.1 F100','G2 X1 I0 J0 F100','G1 X1',
    'G93\nG1 X1 F10\nG1 X2','G1 X1 F0','G92.4 A0','G0 Xnan',
    'G1 X1 (unterminated','G10 L20 P1 X0','G0 H3','T1 M6 S1'])
def test_unsupported_or_ambiguous_is_an_error(text):
    with pytest.raises(NCError):Parser().parse(text)


def test_comments_block_delete_and_tool_changes():
    p=Parser(block_delete=True).parse('(outer (nested))\nT2 M6\n/ G0 X99\nS12000 M3\nG0X1Y2Z3 ; comment\nM5\nG1Z0F100')
    assert p.moves[0].tool==2 and p.moves[0].spindle==1
    assert p.moves[1].spindle==0
    assert p.moves[0].end[0]==1


def test_machine_frame_g10_parser_reuse_and_dwell_s():
    parser=Parser(machine_origin=(-100,-200,-300))
    p=parser.parse('G10 L2 P2 X10 Y20 Z30\nG55\nG0 X1 Y2 Z3')
    np.testing.assert_allclose(p.moves[-1].end,[-89,-178,-267])
    with pytest.raises(NCError):parser.parse('G55\nG0 X1')
    p=Parser().parse('S12000 M3\nG4 S2\nF600\nG1 X10')
    assert p.moves[-1].rpm==12000 and p.duration==pytest.approx(3)


def test_length_compensation_cancellation_requires_reestablishment():
    with pytest.raises(NCError):Parser().parse('G49\nG0 Z2')
    p=Parser().parse('G49\nT1 M6\nG0 Z2')
    assert p.moves[-1].end[2]==2

