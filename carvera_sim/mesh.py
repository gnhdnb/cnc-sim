"""Greedy voxel boundary meshing. Rendering detail never changes simulation."""
import math
import numpy as np
from numba import njit


@njit(cache=True, nogil=True)
def pooled(grid, stride):
    nx,ny,nz=grid.shape
    out=np.zeros(((nx+stride-1)//stride,(ny+stride-1)//stride,(nz+stride-1)//stride),dtype=np.bool_)
    for x in range(out.shape[0]):
        for y in range(out.shape[1]):
            for z in range(out.shape[2]):
                found=False
                for i in range(x*stride,min(nx,(x+1)*stride)):
                    if found:break
                    for j in range(y*stride,min(ny,(y+1)*stride)):
                        if found:break
                        for k in range(z*stride,min(nz,(z+1)*stride)):
                            if grid[i,j,k]:found=True;break
                out[x,y,z]=found
    return out


@njit(cache=True, nogil=True)
def greedy_mesh(grid, origin, spacing, extent, max_quads=400000):
    vertices=np.empty((max_quads*4,3),dtype=np.float32)
    faces=np.empty((max_quads*2,3),dtype=np.uint32)
    count=0
    shape=grid.shape
    pos=np.zeros(3,dtype=np.int64)
    for axis in range(3):
        u,v=(axis+1)%3,(axis+2)%3
        mask=np.zeros((shape[u],shape[v]),dtype=np.int8)
        for plane in range(shape[axis]+1):
            for i in range(shape[u]):
                for j in range(shape[v]):
                    pos[u],pos[v]=i,j
                    before,after=False,False
                    if plane>0:
                        pos[axis]=plane-1;before=grid[pos[0],pos[1],pos[2]]
                    if plane<shape[axis]:
                        pos[axis]=plane;after=grid[pos[0],pos[1],pos[2]]
                    mask[i,j]=1 if before and not after else (-1 if after and not before else 0)
            for i in range(shape[u]):
                j=0
                while j<shape[v]:
                    sign=mask[i,j]
                    if sign==0:j+=1;continue
                    width=1
                    while j+width<shape[v] and mask[i,j+width]==sign:width+=1
                    height=1
                    while i+height<shape[u]:
                        good=True
                        for w in range(width):
                            if mask[i+height,j+w]!=sign:good=False;break
                        if not good:break
                        height+=1
                    if count>=max_quads:
                        return vertices[:count*4],faces[:count*2],True
                    for h in range(height):
                        for w in range(width):mask[i+h,j+w]=0
                    points=((i,j),(i+height,j),(i+height,j+width),(i,j+width))
                    for n in range(4):
                        uv=points[n]
                        vertices[count*4+n,axis]=origin[axis]+min(extent[axis],plane*spacing)
                        vertices[count*4+n,u]=origin[u]+min(extent[u],uv[0]*spacing)
                        vertices[count*4+n,v]=origin[v]+min(extent[v],uv[1]*spacing)
                    base=count*4
                    if sign>0:
                        faces[count*2]=np.array([base,base+1,base+2],dtype=np.uint32)
                        faces[count*2+1]=np.array([base,base+2,base+3],dtype=np.uint32)
                    else:
                        faces[count*2]=np.array([base,base+2,base+1],dtype=np.uint32)
                        faces[count*2+1]=np.array([base,base+3,base+2],dtype=np.uint32)
                    count+=1
                    j+=width
    return vertices[:count*4],faces[:count*2],False


def stock_mesh(grid,stock,stride=0,max_quads=400000):
    stride=int(stride) or max(1,int(math.ceil(max(grid.shape)/220)))
    # Retry at coarser display resolution rather than silently truncating faces.
    while True:
        display=pooled(grid,stride) if stride>1 else grid
        vertices,faces,overflow=greedy_mesh(display,stock.origin,stock.pitch*stride,stock.dimensions,max_quads)
        if not overflow:return vertices,faces,stride
        stride*=2


def frusta_mesh(rows,sides=40):
    vertices,faces=[],[]
    for x,y,z0,z1,r0,r1 in rows:
        base=len(vertices)
        for z,r in ((z0,r0),(z1,r1)):
            for angle in np.linspace(0,2*np.pi,sides,endpoint=False):
                vertices.append([x+r*np.cos(angle),y+r*np.sin(angle),z])
        for i in range(sides):
            j=(i+1)%sides
            faces.extend([[base+i,base+j,base+sides+j],[base+i,base+sides+j,base+sides+i]])
        vertices.extend([[x,y,z0],[x,y,z1]])
        for i in range(sides):
            j=(i+1)%sides
            faces.extend([[base+2*sides,base+j,base+i],[base+2*sides+1,base+sides+i,base+sides+j]])
    return np.asarray(vertices,dtype=np.float32).reshape(-1,3),np.asarray(faces,dtype=np.uint32).reshape(-1,3)


def boxes_mesh(boxes):
    vertices,faces=[],[]
    for x0,y0,z0,x1,y1,z1 in boxes:
        base=len(vertices)
        vertices.extend([[x0,y0,z0],[x1,y0,z0],[x1,y1,z0],[x0,y1,z0],
                         [x0,y0,z1],[x1,y0,z1],[x1,y1,z1],[x0,y1,z1]])
        for a,b,c,d in ((0,3,2,1),(4,5,6,7),(0,1,5,4),(3,7,6,2),(0,4,7,3),(1,2,6,5)):
            faces.extend([[base+a,base+b,base+c],[base+a,base+c,base+d]])
    return np.asarray(vertices,dtype=np.float32).reshape(-1,3),np.asarray(faces,dtype=np.uint32).reshape(-1,3)

