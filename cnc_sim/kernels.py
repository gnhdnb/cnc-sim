"""Compiled continuous geometry. No time/position sampling in straight sweeps.

A swept convex frustum intersects a vertical voxel column in one interval.
Extrema of z(t) are endpoints, radius kinks, or stationary points of
v_z*t + sqrt(a*t*t+b*t+c)/slope. This reduces removal to contiguous spans.
Collision candidates are tested in time, before mutating stock, and compared
with the first cutter arrival. A cutter cannot erase a preceding crash.
"""
import math
import numpy as np
from numba import njit

EPS = 1e-10
MISS = 2.0


@njit(cache=True, nogil=True)
def quadratic_hit(a, b, c, lo, hi):
    """Earliest t in [lo,hi] with a*t^2+b*t+c <= 0; MISS otherwise."""
    if lo > hi + EPS:
        return MISS
    if (a*lo+b)*lo+c <= EPS:
        return lo
    if abs(a) < 1e-14:
        if b >= 0:
            return MISS
        root = -c/b
        return max(lo, root) if root <= hi+EPS else MISS
    disc = b*b-4*a*c
    if disc < -EPS:
        return MISS
    root = math.sqrt(max(0., disc))
    # Stable quadratic roots for trajectories far from the coordinate origin.
    q = -0.5*(b+math.copysign(root, b))
    if abs(q) > 1e-30:
        r0, r1 = q/a, c/q
    else:
        r0 = r1 = -b/(2*a)
    if r0 > r1:
        r0, r1 = r1, r0
    hit = max(lo, r0) if a > 0 else max(lo, r1)
    if hit > hi+EPS or (a > 0 and hit > r1+EPS):
        return MISS
    return min(hi, hit)


@njit(cache=True, nogil=True)
def slab(lo, hi, p, v, lower, upper):
    if abs(v) < 1e-14:
        if p < lower-EPS or p > upper+EPS:
            return 1., 0.
        return lo, hi
    u, w = (lower-p)/v, (upper-p)/v
    return max(lo, min(u, w)), min(hi, max(u, w))


@njit(cache=True, nogil=True)
def disk_interval(rx, ry, vx, vy, radius):
    length2 = vx*vx+vy*vy
    dot = rx*vx+ry*vy
    dist2 = rx*rx+ry*ry
    if length2 < 1e-20:
        return (0., 1.) if dist2 <= radius*radius+EPS else (1., 0.)
    perpendicular = max(0., dist2-dot*dot/length2)
    if perpendicular > radius*radius+EPS:
        return 1., 0.
    delta = math.sqrt(max(0., (radius*radius-perpendicular)/length2))
    center = dot/length2
    return max(0., center-delta), min(1., center+delta)


@njit(cache=True, nogil=True)
def frustum_span(row, a, b, x, y):
    """Exact vertical interval of the union of a moving solid frustum."""
    rx, ry = x-a[0]-row[0], y-a[1]-row[1]
    vx, vy, vz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
    h, r0, r1 = row[3]-row[2], row[4], row[5]
    lo, hi = disk_interval(rx, ry, vx, vy, max(r0, r1))
    if lo > hi+EPS:
        return 1., 0.
    base = a[2]+row[2]
    if abs(r1-r0) < 1e-12:
        return base+min(vz*lo, vz*hi), base+h+max(vz*lo, vz*hi)
    slope = (r1-r0)/h
    k = 1/slope
    length2 = vx*vx+vy*vy
    dot = rx*vx+ry*vy
    d2 = rx*rx+ry*ry
    candidates = np.empty(6, dtype=np.float64)
    candidates[0], candidates[1] = lo, hi
    count = 2
    ilo, ihi = disk_interval(rx, ry, vx, vy, min(r0, r1))
    if ilo <= ihi:
        candidates[count], candidates[count+1] = max(lo, ilo), min(hi, ihi)
        count += 2
    if length2 > 1e-20:
        t0 = dot/length2
        perpendicular = max(0., d2-dot*dot/length2)
        candidates[count] = min(hi, max(lo, t0))
        count += 1
        denom = k*k*length2-vz*vz
        if denom > 1e-20:
            u = -vz*math.copysign(1., k)*math.sqrt(perpendicular/(length2*denom))
            candidates[count] = min(hi, max(lo, t0+u))
            count += 1
    extreme = math.inf if slope > 0 else -math.inf
    for i in range(count):
        t = candidates[i]
        if t < lo-EPS or t > hi+EPS:
            continue
        distance = math.hypot(rx-vx*t, ry-vy*t)
        z = base+vz*t+min(h, max(0., (distance-r0)/slope))
        extreme = min(extreme, z) if slope > 0 else max(extreme, z)
    if slope > 0:
        return extreme, base+h+max(vz*lo, vz*hi)
    return base+min(vz*lo, vz*hi), extreme


@njit(cache=True, nogil=True)
def first_frustum_hit(row, a, b, x, y, z):
    vx, vy, vz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
    lo, hi = slab(0., 1., a[2], vz, z-row[3], z-row[2])
    if lo > hi+EPS:
        return MISS
    rx, ry = x-a[0]-row[0], y-a[1]-row[1]
    slope = (row[5]-row[4])/(row[3]-row[2])
    radius = row[4]+slope*(z-a[2]-row[2])
    rv = -slope*vz
    return quadratic_hit(vx*vx+vy*vy-rv*rv,
                         -2*(rx*vx+ry*vy+radius*rv),
                         rx*rx+ry*ry-radius*radius, lo, hi)


@njit(cache=True, nogil=True)
def first_cut_hit(cutters, a, b, x, y, z):
    best = MISS
    for row in cutters:
        best = min(best, first_frustum_hit(row, a, b, x, y, z))
    return best


@njit(cache=True, nogil=True)
def voxel_range(lower, upper, origin, pitch, size):
    return (max(0, int(math.ceil((lower-origin)/pitch-0.5-1e-8))),
            min(size-1, int(math.floor((upper-origin)/pitch-0.5+1e-8))))


@njit(cache=True, nogil=True)
def remove_sweep(grid, origin, pitch, cutters, a, b):
    removed = 0
    nx, ny, nz = grid.shape
    for row in cutters:
        radius = max(row[4], row[5])
        k0, k1 = voxel_range(min(a[2], b[2])+row[2], max(a[2], b[2])+row[3], origin[2], pitch, nz)
        if k0 > k1:
            continue
        i0, i1 = voxel_range(min(a[0], b[0])+row[0]-radius,
                             max(a[0], b[0])+row[0]+radius, origin[0], pitch, nx)
        for i in range(i0, i1+1):
            x = origin[0]+(i+0.5)*pitch
            # Project the swept capsule on y at this x, avoiding a diagonal's
            # huge rectangular bounding box without subdividing the motion.
            lo, hi = slab(0., 1., a[0]+row[0], b[0]-a[0], x-radius, x+radius)
            if lo > hi:
                continue
            ya = a[1]+row[1]+(b[1]-a[1])*lo
            yb = a[1]+row[1]+(b[1]-a[1])*hi
            j0, j1 = voxel_range(min(ya, yb)-radius, max(ya, yb)+radius, origin[1], pitch, ny)
            for j in range(j0, j1+1):
                y = origin[1]+(j+0.5)*pitch
                low, high = frustum_span(row, a, b, x, y)
                if low > high:
                    continue
                z0, z1 = voxel_range(low, high, origin[2], pitch, nz)
                for k in range(z0, z1+1):
                    if grid[i, j, k]:
                        grid[i, j, k] = False
                        removed += 1
    return removed


@njit(cache=True, nogil=True)
def collide_frusta(grid, origin, pitch, bodies, cutters, a, b):
    best, bx, by, bz = MISS, 0., 0., 0.
    nx, ny, nz = grid.shape
    for row in bodies:
        k0, k1 = voxel_range(min(a[2], b[2])+row[2], max(a[2], b[2])+row[3], origin[2], pitch, nz)
        if k0 > k1:
            continue
        radius = max(row[4], row[5])
        i0, i1 = voxel_range(min(a[0], b[0])+row[0]-radius,
                             max(a[0], b[0])+row[0]+radius, origin[0], pitch, nx)
        for i in range(i0, i1+1):
            x = origin[0]+(i+0.5)*pitch
            lo, hi = slab(0., 1., a[0]+row[0], b[0]-a[0], x-radius, x+radius)
            if lo > hi:
                continue
            ya, yb = a[1]+row[1]+(b[1]-a[1])*lo, a[1]+row[1]+(b[1]-a[1])*hi
            j0, j1 = voxel_range(min(ya, yb)-radius, max(ya, yb)+radius, origin[1], pitch, ny)
            for j in range(j0, j1+1):
                y = origin[1]+(j+0.5)*pitch
                low, high = frustum_span(row, a, b, x, y)
                if low > high:
                    continue
                z0, z1 = voxel_range(low, high, origin[2], pitch, nz)
                for k in range(z0, z1+1):
                    if not grid[i, j, k]:
                        continue
                    z = origin[2]+(k+0.5)*pitch
                    hit = first_frustum_hit(row, a, b, x, y, z)
                    if hit >= best:
                        continue
                    cut = first_cut_hit(cutters, a, b, x, y, z)
                    if cut <= hit+EPS:
                        continue
                    best, bx, by, bz = hit, x, y, z
                    if best <= EPS:
                        return best, bx, by, bz
    return best, bx, by, bz


@njit(cache=True, nogil=True)
def first_box_hit(box, a, b, point):
    lo, hi = 0., 1.
    for d in range(3):
        lo, hi = slab(lo, hi, a[d], b[d]-a[d], point[d]-box[d+3], point[d]-box[d])
    return max(0., lo) if lo <= hi+EPS else MISS


@njit(cache=True, nogil=True)
def collide_boxes(grid, origin, pitch, boxes, cutters, a, b):
    best, bx, by, bz = MISS, 0., 0., 0.
    nx, ny, nz = grid.shape
    for box in boxes:
        k0, k1 = voxel_range(min(a[2], b[2])+box[2], max(a[2], b[2])+box[5], origin[2], pitch, nz)
        if k0 > k1:
            continue
        i0, i1 = voxel_range(min(a[0], b[0])+box[0], max(a[0], b[0])+box[3], origin[0], pitch, nx)
        for i in range(i0, i1+1):
            x = origin[0]+(i+0.5)*pitch
            lo, hi = slab(0., 1., a[0], b[0]-a[0], x-box[3], x-box[0])
            if lo > hi:
                continue
            ya, yb = a[1]+(b[1]-a[1])*lo, a[1]+(b[1]-a[1])*hi
            j0, j1 = voxel_range(min(ya, yb)+box[1], max(ya, yb)+box[4], origin[1], pitch, ny)
            for j in range(j0, j1+1):
                y = origin[1]+(j+0.5)*pitch
                tl, th = slab(lo, hi, a[1], b[1]-a[1], y-box[4], y-box[1])
                if tl > th:
                    continue
                za, zb = a[2]+(b[2]-a[2])*tl, a[2]+(b[2]-a[2])*th
                z0, z1 = voxel_range(min(za, zb)+box[2], max(za, zb)+box[5], origin[2], pitch, nz)
                for k in range(z0, z1+1):
                    if not grid[i, j, k]:
                        continue
                    z = origin[2]+(k+0.5)*pitch
                    hit = first_box_hit(box, a, b, (x, y, z))
                    if hit < best and first_cut_hit(cutters, a, b, x, y, z) > hit+EPS:
                        best, bx, by, bz = hit, x, y, z
                        if best <= EPS:
                            return best, bx, by, bz
    return best, bx, by, bz


@njit(cache=True, nogil=True)
def box_fixture_hit(body, fixture, a, b):
    lo, hi = 0., 1.
    for d in range(3):
        lo, hi = slab(lo, hi, a[d], b[d]-a[d], fixture[d]-body[d+3], fixture[d+3]-body[d])
    return max(0., lo) if lo <= hi+EPS else MISS


@njit(cache=True, nogil=True)
def frustum_fixture_hit(row, fixture, a, b):
    """Exact continuous rotating-frustum versus fixed axis-aligned box."""
    vx, vy, vz = b[0]-a[0], b[1]-a[1], b[2]-a[2]
    cx, cy = a[0]+row[0], a[1]+row[1]
    cuts = np.empty(10, dtype=np.float64)
    cuts[0], cuts[1], count = 0., 1., 2
    for p, v, low, high in ((cx, vx, fixture[0], fixture[3]),
                            (cy, vy, fixture[1], fixture[4])):
        if abs(v) > 1e-14:
            for boundary in (low, high):
                t = (boundary-p)/v
                if 0 < t < 1:
                    cuts[count], count = t, count+1
    if abs(vz) > 1e-14:
        for z in (fixture[2], fixture[5]):
            for h in (row[2], row[3]):
                t = (z-a[2]-h)/vz
                if 0 < t < 1:
                    cuts[count], count = t, count+1
    cuts = np.sort(cuts[:count])
    slope = (row[5]-row[4])/(row[3]-row[2])
    best = MISS
    # An endpoint can touch a fixture without any open interval of overlap.
    for t in cuts:
        tip = a[2]+vz*t
        low = max(row[2], fixture[2]-tip)
        high = min(row[3], fixture[5]-tip)
        if low > high+EPS:
            continue
        h = high if slope >= 0 else low
        radius = row[4]+slope*(h-row[2])
        dx = max(0., fixture[0]-(cx+vx*t), cx+vx*t-fixture[3])
        dy = max(0., fixture[1]-(cy+vy*t), cy+vy*t-fixture[4])
        if dx*dx+dy*dy <= radius*radius+EPS:
            best = min(best, t)
    for index in range(count-1):
        lo, hi = cuts[index], cuts[index+1]
        mid = (lo+hi)/2
        tip = a[2]+vz*mid
        if tip+row[2] > fixture[5]+EPS or tip+row[3] < fixture[2]-EPS:
            continue
        dx, dxv, dy, dyv = 0., 0., 0., 0.
        if cx+vx*mid < fixture[0]:
            dx, dxv = fixture[0]-cx, -vx
        elif cx+vx*mid > fixture[3]:
            dx, dxv = cx-fixture[3], vx
        if cy+vy*mid < fixture[1]:
            dy, dyv = fixture[1]-cy, -vy
        elif cy+vy*mid > fixture[4]:
            dy, dyv = cy-fixture[4], vy
        # Largest radius of the part whose height overlaps the fixture.
        h = min(row[3], fixture[5]-tip) if slope >= 0 else max(row[2], fixture[2]-tip)
        moving_h = ((slope >= 0 and fixture[5]-tip < row[3]) or
                    (slope < 0 and fixture[2]-tip > row[2]))
        rv = -slope*vz if moving_h else 0.
        rmid = row[4]+slope*(h-row[2])
        r = rmid-rv*mid
        hit = quadratic_hit(dxv*dxv+dyv*dyv-rv*rv,
                            2*(dx*dxv+dy*dyv-r*rv), dx*dx+dy*dy-r*r, lo, hi)
        if hit <= 1:
            return min(best, hit)
    return best
