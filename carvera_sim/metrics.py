"""Time-resolved stock removal and positive surface-normal approach diagnostics.

Approach queries the current voxel solid in the positive direction of each
velocity component. Each query translates the actual rotating cutter envelope
along a voxel-face normal by at most 20 mm. The largest inward component with
stock ahead is returned. This handles all six normals and undercuts; it does
not substitute distance to the original stock top or motion magnitude.
"""
from __future__ import annotations
import math
import numpy as np
from numba import njit
from .kernels import frustum_span, slab, voxel_range

METRIC_DTYPE = np.dtype([
    ('t_start_s', '<f8'), ('t_end_s', '<f8'), ('line', '<i8'), ('tool', '<i8'),
    ('removed_mm3', '<f8'), ('removal_rate_mm3_min', '<f8'),
    ('approach_speed_mm_min', '<f8'), ('rapid', '?'),
])


@njit(cache=True, nogil=True)
def has_stock_ahead(grid, origin, pitch, cutters, position, axis, direction, reach):
    """Centre-sampled cutter projection; half-cell correction gives face distance."""
    end = position.copy()
    end[axis] += direction * (reach + pitch/2)
    nx, ny, nz = grid.shape
    for row in cutters:
        radius = max(row[4], row[5])
        k0,k1 = voxel_range(min(position[2],end[2])+row[2],max(position[2],end[2])+row[3],origin[2],pitch,nz)
        if k0>k1: continue
        i0,i1 = voxel_range(min(position[0],end[0])+row[0]-radius,max(position[0],end[0])+row[0]+radius,origin[0],pitch,nx)
        for i in range(i0,i1+1):
            x=origin[0]+(i+.5)*pitch
            lo,hi=slab(0.,1.,position[0]+row[0],end[0]-position[0],x-radius,x+radius)
            if lo>hi: continue
            ya=position[1]+row[1]+(end[1]-position[1])*lo
            yb=position[1]+row[1]+(end[1]-position[1])*hi
            j0,j1=voxel_range(min(ya,yb)-radius,max(ya,yb)+radius,origin[1],pitch,ny)
            for j in range(j0,j1+1):
                y=origin[1]+(j+.5)*pitch
                low,high=frustum_span(row,position,end,x,y)
                if low>high: continue
                z0,z1=voxel_range(low,high,origin[2],pitch,nz)
                for k in range(z0,z1+1):
                    if grid[i,j,k]: return True
    return False


@njit(cache=True, nogil=True)
def normal_approach(grid, origin, pitch, cutters, position, velocity_mm_min, reach=20.):
    axes=np.argsort(np.abs(velocity_mm_min))
    for n in range(2,-1,-1):
        axis=axes[n]
        speed=abs(velocity_mm_min[axis])
        if speed<=1e-12: continue
        direction=1. if velocity_mm_min[axis]>0 else -1.
        if has_stock_ahead(grid,origin,pitch,cutters,position,axis,direction,reach):
            return speed
    return 0.


def sample_count(move, period=.1, distance=1.):
    duration=max(0.,move.t1-move.t0)
    length=float(np.linalg.norm(move.end-move.start))
    return max(1,math.ceil(duration/period-1e-10),math.ceil(length/distance-1e-10))


def metric_summary(rows, period, distance):
    finite=rows['removal_rate_mm3_min'][np.isfinite(rows['removal_rate_mm3_min'])]
    return {
        'schema_version':1, 'npy_array_index':1, 'samples':len(rows),
        'fields':[list(field) for field in METRIC_DTYPE.descr],
        'sample_period_max_s':period, 'sample_travel_max_mm':distance,
        'approach_range_mm':20.,
        'removal_definition':'Actual removed voxel volume divided by each interval duration, multiplied by 60; interval mean, mm^3/min',
        'approach_definition':'Maximum positive velocity component toward a voxel face within 20 mm of the rotating cutter envelope; centre-sampled transverse projection and half-cell axial face correction; maximum of interval start/mid/end probes against stock before that interval is cut',
        'approach_scope':'Remaining stock only, cutter envelope only; excludes fixtures and holder/head (checked separately for collisions); voxel-face normals, not fitted smooth-surface normals',
        'sampling_note':'Diagnostic samples, not an exact continuous peak bound; short transients can require smaller sample period/travel',
        'zero_duration_note':'A zero-duration interval that removes material has NaN rate; removed_mm3 is retained',
        'max_removal_rate_mm3_min':float(finite.max()) if len(finite) else 0.,
        'max_approach_speed_mm_min':float(rows['approach_speed_mm_min'].max()) if len(rows) else 0.,
        'undefined_rate_samples':int(np.count_nonzero(~np.isfinite(rows['removal_rate_mm3_min']))),
    }
