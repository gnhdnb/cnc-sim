import numpy as np
import pytest
from cnc_sim.kernels import (frustum_span,first_frustum_hit,remove_sweep,collide_frusta,
                                frustum_fixture_hit,box_fixture_hit,quadratic_hit,collide_boxes)


def test_cylinder_continuous_sweep_matches_capsule():
    pitch=.1;origin=np.array([-2.,-2.,-1.]);grid=np.ones((80,40,20),dtype=bool)
    row=np.array([[0.,0.,0.,1.,.53,.53]])
    a=np.array([-.73,.04,-.61]);b=np.array([3.26,.04,-.61])
    removed=remove_sweep(grid,origin,pitch,row,a,b)
    x,y,z=np.meshgrid(*[origin[d]+(np.arange(grid.shape[d])+.5)*pitch for d in range(3)],indexing='ij')
    px=np.clip(x,a[0],b[0]);expected=(x-px)**2+(y-a[1])**2<=.53**2
    expected&=(z>=a[2])&(z<=a[2]+1)
    np.testing.assert_array_equal(~grid,expected)
    assert removed==expected.sum()


@pytest.mark.parametrize('r0,r1',[(.1,1.2),(1.2,.1),(.8,.8),(0,1.5)])
def test_ramped_frustum_against_independent_dense_sampling(r0,r1):
    pitch=.2;origin=np.array([-2.,-2.,-2.]);shape=(25,25,25)
    grid=np.ones(shape,dtype=bool);row=np.array([[0.,0.,0.,1.7,r0,r1]])
    a=np.array([-1.17,-.79,-1.24]);b=np.array([1.31,1.04,.87])
    remove_sweep(grid,origin,pitch,row,a,b)
    xyz=np.stack(np.meshgrid(*[origin[d]+(np.arange(shape[d])+.5)*pitch for d in range(3)],indexing='ij'),axis=-1)
    reference=np.zeros(shape,dtype=bool)
    near=np.zeros(shape,dtype=bool)
    step=np.linalg.norm(b-a)/4000
    for t in np.linspace(0,1,4001):
        p=a+t*(b-a);h=xyz[...,2]-p[2]
        radial=np.linalg.norm(xyz[...,:2]-p[:2],axis=-1)
        r=r0+(r1-r0)*np.clip(h/1.7,0,1)
        reference|=(h>=0)&(h<=1.7)&(radial<=r)
        near|=(h>=-step)&(h<=1.7+step)&(radial<=r+step*(1+abs(r1-r0)/1.7))
    assert np.all((~reference)|(~grid)),"Continuous sweep missed a sampled interior point"
    assert np.all(grid|near),"Continuous sweep removed a point outside the sampled boundary tolerance"


def test_collision_chronology_leading_and_trailing_body():
    grid=np.ones((20,5,5),dtype=bool);origin=np.array([0.,-.25,-.25]);pitch=.1
    a=np.array([-2.,0.,-.3]);b=np.array([4.,0.,-.3])
    cut=np.array([[0.,0.,0.,1.,.5,.5]])
    lead=np.array([[1.,0.,0.,1.,.2,.2]])
    trail=np.array([[-1.,0.,0.,1.,.2,.2]])
    assert collide_frusta(grid,origin,pitch,lead,cut,a,b)[0]<=1
    assert collide_frusta(grid,origin,pitch,trail,cut,a,b)[0]>1


def test_thin_fixture_cannot_be_skipped_by_long_move():
    row=np.array([0.,0.,0.,2.,.4,.4]);a=np.array([-100.,0.,0.]);b=np.array([100.,0.,0.])
    fixture=np.array([.003,-.01,.8,.008,.01,1.2])
    hit=frustum_fixture_hit(row,fixture,a,b)
    assert hit==pytest.approx((100+.003-.4)/200,abs=1e-9)


def test_fixture_cones_against_sampled_geometry():
    rng=np.random.default_rng(771)
    tt=np.linspace(0,1,10001)
    for _ in range(120):
        a=rng.uniform(-3,3,3);b=rng.uniform(-3,3,3)
        row=np.array([0.,0.,0.,rng.uniform(.1,3),rng.uniform(.1,2),rng.uniform(.1,2)])
        low=rng.uniform(-2,2,3);high=low+rng.uniform(.05,2,3);box=np.r_[low,high]
        p=a+(b-a)*tt[:,None]
        heights_low=np.maximum(row[2],low[2]-p[:,2]);heights_high=np.minimum(row[3],high[2]-p[:,2])
        h=heights_high if row[5]>=row[4] else heights_low
        radius=row[4]+(row[5]-row[4])*(h-row[2])/(row[3]-row[2])
        dist=np.linalg.norm(np.maximum(np.maximum(low[:2]-p[:,:2],p[:,:2]-high[:2]),0),axis=1)
        inside=(heights_low<=heights_high)&(dist<=radius)
        hit=frustum_fixture_hit(row,box,a,b)
        if inside.any():
            assert hit<=tt[np.flatnonzero(inside)[0]]+1e-8
            assert hit>=max(0,tt[np.flatnonzero(inside)[0]]-.001)
        elif hit<=1:
            # A sub-time-step grazing contact is possible, verify its geometry.
            p=a+(b-a)*hit
            hlow=max(row[2],low[2]-p[2]);hhigh=min(row[3],high[2]-p[2])
            h=hhigh if row[5]>=row[4] else hlow
            radius=row[4]+(row[5]-row[4])*(h-row[2])/(row[3]-row[2])
            d=np.linalg.norm(np.maximum(np.maximum(low[:2]-p[:2],p[:2]-high[:2]),0))
            assert hlow<=hhigh+1e-7 and d<=radius+1e-7


def test_stationary_cone_and_quadratic_tangencies():
    a=np.array([0.,0.,0.]);row=np.array([0.,0.,0.,2.,0.,1.])
    assert frustum_span(row,a,a,.5,0)==pytest.approx((1.,2.))
    assert first_frustum_hit(row,a,a,.5,0,1.1)==0
    assert first_frustum_hit(row,a,a,.5,0,.9)>1
    assert quadratic_hit(1,-1,.25,0,1)==pytest.approx(.5)
    assert quadratic_hit(-1,0,.25,0,1)==pytest.approx(.5)


def test_fixture_contact_only_at_motion_endpoint():
    row=np.array([0.,0.,0.,1.,1.,1.]);box=np.array([-.2,-.2,2.,.2,.2,3.])
    assert frustum_fixture_hit(row,box,np.array([0.,0.,0.]),np.array([0.,0.,1.]))==pytest.approx(1)


def test_box_head_swept_diagonally_through_stock():
    grid=np.ones((40,40,40),dtype=bool)
    origin=np.array([-2.,-2.,-2.]);empty=np.empty((0,6))
    box=np.array([[0.,0.,0.,1.,1.,1.]])
    a=np.array([-5.,-5.,-5.]);b=np.array([5.,5.,5.])
    hit,x,y,z=collide_boxes(grid,origin,.1,box,empty,a,b)
    assert hit==pytest.approx(.205,abs=1e-9)
    assert (x,y,z)==pytest.approx((-1.95,-1.95,-1.95))


def test_box_fixture_continuous_contact():
    moving=np.array([-.5,-.5,-.5,.5,.5,.5])
    fixture=np.array([0.,0.,0.,.001,.001,.001])
    hit=box_fixture_hit(moving,fixture,np.array([-10.,0.,0.]),np.array([10.,0.,0.]))
    assert hit==pytest.approx(.475)

