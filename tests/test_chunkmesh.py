import numpy as np
from carvera_sim.chunkmesh import ChunkMesher,mesh_chunk
from carvera_sim.engine import Stock


def expected_faces(grid):
    result=set()
    for cell in np.argwhere(grid):
        for axis in range(3):
            u,v=(axis+1)%3,(axis+2)%3
            for sign in (-1,1):
                neighbour=cell.copy();neighbour[axis]+=sign
                if neighbour[axis]<0 or neighbour[axis]>=grid.shape[axis] or not grid[tuple(neighbour)]:
                    result.add((axis,sign,int(cell[axis]+(sign>0)),int(cell[u]),int(cell[v])))
    return result


def mesh_faces(meshes,stock):
    result=set()
    for vertices,faces in meshes.values():
        for q in range(len(vertices)//4):
            points=(vertices[q*4:q*4+4]-stock.origin)/stock.pitch
            axis=int(np.argmin(np.ptp(points,axis=0)))
            u,v=(axis+1)%3,(axis+2)%3
            triangle=vertices[faces[q*2]]
            normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])
            sign=1 if normal[axis]>0 else -1
            plane=int(round(points[0,axis]))
            for i in range(int(round(points[:,u].min())),int(round(points[:,u].max()))):
                for j in range(int(round(points[:,v].min())),int(round(points[:,v].max()))):
                    face=(axis,sign,plane,i,j)
                    assert face not in result,'Duplicate boundary face'
                    result.add(face)
    return result


def test_chunks_equal_voxel_boundary_oracle_without_internal_seams():
    rng=np.random.default_rng(19)
    grid=rng.random((9,10,7))>.4
    stock=Stock(np.array(grid.shape)*.1,[-2,3,-.7],.1)
    mesher=ChunkMesher(grid,stock,chunk_size=4)
    meshes={key:(v,f) for key,v,f in mesher.update(reset=True)}
    assert mesh_faces(meshes,stock)==expected_faces(grid)


def test_incremental_edits_invalidate_adjacent_chunk_faces():
    grid=np.ones((12,12,12),dtype=bool)
    stock=Stock([1.2,1.2,1.2],[0,0,0],.1)
    mesher=ChunkMesher(grid,stock,chunk_size=4)
    meshes={key:(v,f) for key,v,f in mesher.update(reset=True)}
    grid[3,6,6]=False  # Last cell of a chunk; neighbour must acquire a face.
    edits=mesher.update([(np.array([.3,.6,.6]),np.array([.4,.7,.7]))])
    assert 0<len(edits)<len(meshes)
    for key,v,f in edits:meshes[key]=(v,f)
    assert mesh_faces(meshes,stock)==expected_faces(grid)
    assert mesher.update()==[]
    # A backward seek/full reset restores all faces exactly.
    grid[:]=True
    meshes={key:(v,f) for key,v,f in mesher.update(reset=True)}
    assert mesh_faces(meshes,stock)==expected_faces(grid)


def test_full_resolution_grows_buffers_instead_of_downsampling():
    grid=np.indices((16,16,16)).sum(axis=0)%2==0
    stock=Stock([1.6]*3,[0,0,0],.1)
    vertices,faces=mesh_chunk(grid,stock,[0,0,0],[16,16,16])
    assert len(faces)==int(grid.sum())*12
    assert vertices.nbytes==vertices.size*4
    assert vertices.shape==(int(grid.sum())*24,3)


def test_mesh_is_clipped_to_partial_stock_dimensions():
    stock=Stock([1.04,2.06,.23],[-2,1,-.23],.1)
    grid=np.empty(stock.shape,dtype=bool);stock.initialize(grid)
    meshes=ChunkMesher(grid,stock,4).update(reset=True)
    for _,vertices,_ in meshes:
        assert np.all(vertices>=stock.origin-1e-6)
        assert np.all(vertices<=stock.origin+stock.dimensions+1e-6)
