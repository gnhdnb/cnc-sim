import numpy as np
import pytest
from carvera_sim.tools import make_tool,embedded_tools,make_body
from carvera_sim.catalog import catalog


def test_all_124_official_catalog_entries_construct():
    data=catalog();assert len(data['tools'])==124
    for i,record in enumerate(data['tools']):
        t=make_tool(i+1,{'catalog_id':record['id']})
        assert len(t.cutting)>0 and np.isfinite(t.cutting).all()
        assert not t.verified


@pytest.mark.parametrize('kind,extra',[
    ('flat',{}),('corn',{}),('O flute',{}),('ball',{}),('bull',{'corner_radius':.4}),
    ('V bit',{'angle':30,'tip_diameter':.1}),('drill',{'angle':118}),
    ('tapered_flat',{'angle':15,'tip_diameter':.5}),
    ('tapered_ball',{'tip_radius':.5,'half_angle':5}),
    ('thread',{'neck_diameter':1,'tooth_height':.4,'teeth':3,'pitch':.8}),
    ('dovetail',{'neck_diameter':1}),('t_slot',{'neck_diameter':1}),
    ('lollipop',{'flute_length':3,'neck_diameter':1}),
    ('profile',{'profile':[[0,.5],[1,1.5],[2,.5],[5,.5]]})])
def test_tool_families(kind,extra):
    spec=dict(type=kind,diameter=3,flute_length=5,shoulder_length=6,stickout=12,shank_diameter=3.175,verified=True)
    spec.update(extra);t=make_tool(1,spec)
    assert t.verified and (t.cutting[:,3]>t.cutting[:,2]).all()


def test_ball_profile_sagitta_bound():
    r=2;t=make_tool(1,dict(type='ball',diameter=4,flute_length=5,stickout=10),.005)
    for row in t.cutting:
        if row[3]>r:continue
        midpoint=np.array([(row[2]+row[3])/2,(row[4]+row[5])/2])
        sag=r-np.linalg.norm(midpoint-[r,0])
        assert 0<=sag<=.005+1e-12


def test_embedded_makera_metadata_and_overrides():
    text=';@MKR|TOOL|number=1|type=Flat End|name=flat|handlediameter=3.175|sticklength=0|shoulderlength=12|flutelength=12|diameter=3.175|tipdiameter=3.175|cornerradius=0|angle=0|halfAngle=0'
    tools,warnings=embedded_tools(text)
    assert tools[1].kind=='flat' and not tools[1].verified and warnings
    assert embedded_tools(text,skip={1})==({},[])


@pytest.mark.parametrize('spec',[
    {'type':'unknown'}, {'type':'flat','diameter':-1},{'type':'ball','diameter':10,'flute_length':1},
    {'type':'flat','stickout':1,'flute_length':2},{'type':'v','angle':180},
    {'type':'thread','neck_diameter':4,'diameter':3},{'type':'profile','profile':[[0,1],[2,2],[1,1]]},
    {'type':'flat','diameter':float('nan')},{'type':'flat','handedness':'both'}])
def test_invalid_tool_rejected(spec):
    with pytest.raises((ValueError,KeyError)):make_tool(1,spec)
