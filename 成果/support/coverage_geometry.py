"""Conservative continuous disk/half-plane coverage certificate.

For each square, select sensors within 1000m of ALL its points. If their convex
hull contains the whole square, every emitting half-plane is detected there.
Squares entirely outside the task disk are discarded. Inconclusive is False.
"""
import time
import numpy as np

def hull_normals(points):
    points=sorted(set(map(tuple,points)))
    if len(points)<3:return None
    def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower=[];upper=[]
    for p in points:
        while len(lower)>=2 and cross(lower[-2],lower[-1],p)<=0:lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper)>=2 and cross(upper[-2],upper[-1],p)<=0:upper.pop()
        upper.append(p)
    hull=np.array(lower[:-1]+upper[:-1])
    if len(hull)<3:return None
    edges=np.roll(hull,-1,axis=0)-hull
    normals=np.column_stack([edges[:,1],-edges[:,0]])
    normals/=np.linalg.norm(normals,axis=1)[:,None]
    bounds=(normals*hull).sum(axis=1)
    return normals,bounds

def certify(points,max_depth=15,return_cells=False,max_cells=50000):
    points=np.asarray(points);n=len(points)
    if n>63:raise ValueError('At most 63 stations')
    centers=np.zeros((1,2));half=1800.;cache={};leaves=[];discarded=0;checked=0
    bits=np.left_shift(np.uint64(1),np.arange(n,dtype=np.uint64))
    for depth in range(max_depth+1):
        if len(centers)>max_cells:return dict(covered=False,reason='certificate_work_limit',depth=depth)
        nearest=np.maximum(np.abs(centers)-half,0)
        outside=(nearest*nearest).sum(axis=1)>1800.**2+1e-6
        discarded+=int(outside.sum());centers=centers[~outside]
        if not len(centers):return dict(covered=True,depth=depth,checked=checked,discarded=discarded,cells=leaves if return_cells else None)
        checked+=len(centers)
        d=np.abs(points[None,:,:]-centers[:,None,:])+half
        eligible=(d*d).sum(axis=2)<(1000.-1e-6)**2
        masks=(eligible.astype(np.uint64)*bits).sum(axis=1)
        covered=np.zeros(len(centers),dtype=bool)
        for mask in np.unique(masks):
            selected=masks==mask
            if int(mask) not in cache:
                cache[int(mask)]=hull_normals(points[(bits & mask)!=0])
            constraints=cache[int(mask)]
            if constraints is None:continue
            normals,bounds=constraints
            values=centers[selected]@normals.T+half*np.abs(normals).sum(axis=1)
            ok=np.all(values<=bounds-1e-7,axis=1)
            covered[selected]=ok
            if return_cells:
                for center in centers[selected][ok]:leaves.append(dict(center=center.tolist(),half=half,mask=int(mask)))
        centers=centers[~covered]
        if not len(centers):return dict(covered=True,depth=depth,checked=checked,discarded=discarded,cells=leaves if return_cells else None)
        if depth==max_depth:
            return dict(covered=False,depth=depth,checked=checked,unresolved=len(centers),example=centers[0].tolist())
        half/=2
        shifts=half*np.array([[-1,-1],[-1,1],[1,-1],[1,1]])
        centers=(centers[:,None,:]+shifts[None,:,:]).reshape(-1,2)

