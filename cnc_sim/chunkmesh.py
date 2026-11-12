"""Incremental full-resolution voxel surfaces, with shared-boundary ownership.

Only voxels changed by cutting (plus a one-cell halo) invalidate chunks. A
face belongs to the chunk containing its solid cell, so no internal chunk
walls or cracks are introduced. Full-resolution meshes never downsample.
"""
import itertools
import numpy as np
from numba import njit


@njit(cache=True,nogil=True)
def chunk_mesh_kernel(grid,origin,pitch,extent,lower,upper,capacity):
    vertices=np.empty((capacity*4,3),np.float32)
    faces=np.empty((capacity*2,3),np.uint32)
    count=0
    pos=np.zeros(3,np.int64)
    for axis in range(3):
        u,v=(axis+1)%3,(axis+2)%3
        nu,nv=upper[u]-lower[u],upper[v]-lower[v]
        mask=np.empty((nu,nv),np.int8)
        for plane in range(lower[axis],upper[axis]+1):
            for i in range(nu):
                for j in range(nv):
                    pos[u],pos[v]=lower[u]+i,lower[v]+j
                    before,after=False,False
                    if plane>0:
                        pos[axis]=plane-1;before=grid[pos[0],pos[1],pos[2]]
                    if plane<grid.shape[axis]:
                        pos[axis]=plane;after=grid[pos[0],pos[1],pos[2]]
                    # At a chunk boundary, a neighbouring solid owns its face.
                    if before and not after and plane>lower[axis]:mask[i,j]=1
                    elif after and not before and plane<upper[axis]:mask[i,j]=-1
                    else:mask[i,j]=0
            for i in range(nu):
                j=0
                while j<nv:
                    sign=mask[i,j]
                    if sign==0:j+=1;continue
                    width=1
                    while j+width<nv and mask[i,j+width]==sign:width+=1
                    height=1
                    while i+height<nu:
                        good=True
                        for w in range(width):
                            if mask[i+height,j+w]!=sign:good=False;break
                        if not good:break
                        height+=1
                    if count==capacity:
                        return vertices,faces,True
                    for h in range(height):
                        for w in range(width):mask[i+h,j+w]=0
                    points=((i,j),(i+height,j),(i+height,j+width),(i,j+width))
                    for n in range(4):
                        uv=points[n]
                        vertices[count*4+n,axis]=origin[axis]+min(extent[axis],plane*pitch)
                        vertices[count*4+n,u]=origin[u]+min(extent[u],(lower[u]+uv[0])*pitch)
                        vertices[count*4+n,v]=origin[v]+min(extent[v],(lower[v]+uv[1])*pitch)
                    base=count*4
                    if sign>0:
                        faces[count*2,0],faces[count*2,1],faces[count*2,2]=base,base+1,base+2
                        faces[count*2+1,0],faces[count*2+1,1],faces[count*2+1,2]=base,base+2,base+3
                    else:
                        faces[count*2,0],faces[count*2,1],faces[count*2,2]=base,base+2,base+1
                        faces[count*2+1,0],faces[count*2+1,1],faces[count*2+1,2]=base,base+3,base+2
                    count+=1;j+=width
    # Do not retain large unused backing buffers for thousands of small chunks.
    return vertices[:count*4].copy(),faces[:count*2].copy(),False


def mesh_chunk(grid,stock,lower,upper):
    capacity=1024
    while True:
        vertices,faces,overflow=chunk_mesh_kernel(grid,stock.origin,stock.pitch,stock.dimensions,
                                                 np.asarray(lower),np.asarray(upper),capacity)
        if not overflow:return vertices,faces
        capacity*=2


def cutting_bounds(move,tool):
    rows=tool.cutting
    radii=np.maximum(rows[:,4],rows[:,5])
    low=np.array([np.min(rows[:,0]-radii),np.min(rows[:,1]-radii),np.min(rows[:,2])])
    high=np.array([np.max(rows[:,0]+radii),np.max(rows[:,1]+radii),np.max(rows[:,3])])
    return np.minimum(move.start,move.end)+low,np.maximum(move.start,move.end)+high


class ChunkMesher:
    def __init__(self,grid,stock,chunk_size=64):
        if chunk_size<1:raise ValueError('chunk_size must be positive')
        self.grid,self.stock=grid,stock
        self.chunk_size=int(chunk_size)
        self.shape=np.asarray(grid.shape,dtype=np.int64)
        self.chunk_shape=(self.shape+self.chunk_size-1)//self.chunk_size
        self.dirty=set()
        self.meshes={}

    def invalidate_all(self):
        self.dirty=set(itertools.product(*(range(int(n)) for n in self.chunk_shape)))

    def mark(self,bounds):
        low,high=bounds
        lo=np.maximum(0,np.floor((low-self.stock.origin)/self.stock.pitch).astype(np.int64)-1)
        hi=np.minimum(self.shape-1,np.floor((high-self.stock.origin)/self.stock.pitch).astype(np.int64)+1)
        if np.any(lo>hi):return
        clo,chi=lo//self.chunk_size,hi//self.chunk_size
        self.dirty.update(itertools.product(*(range(int(a),int(b)+1) for a,b in zip(clo,chi))))

    def update(self,bounds=(),reset=False,cancelled=None):
        if reset:self.invalidate_all()
        for bound in bounds:self.mark(bound)
        updates=[]
        for key in sorted(self.dirty):
            if cancelled and cancelled():raise InterruptedError()
            low=np.array(key)*self.chunk_size
            high=np.minimum(low+self.chunk_size,self.shape)
            vertices,faces=mesh_chunk(self.grid,self.stock,low,high)
            if len(faces):self.meshes[key]=(vertices,faces)
            else:self.meshes.pop(key,None)
            updates.append((key,vertices,faces))
        self.dirty.clear()
        return updates

    def combined(self):
        """Pack cached surfaces into one draw call, without rescanning any voxels."""
        vertices=np.empty((sum(len(v) for v,_ in self.meshes.values()),3),np.float32)
        faces=np.empty((sum(len(f) for _,f in self.meshes.values()),3),np.uint32)
        vo=fo=0
        for v,f in self.meshes.values():
            vertices[vo:vo+len(v)]=v
            faces[fo:fo+len(f)]=f+vo
            vo+=len(v);fo+=len(f)
        return vertices,faces
