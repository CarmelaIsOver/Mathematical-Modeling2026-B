"""Conservative bearing geometry. Coordinates metres, angles degrees."""
import math
import itertools
import numpy as np

EPS_DEG = 1.005001  # 1 degree physical error plus 0.005 degree rounding

def unit(deg):
    a = math.radians(deg)
    return np.array([math.cos(a), math.sin(a)])

def clip(poly, normal, bound):
    """Clip convex polygon by normal @ x <= bound, retaining boundary."""
    if len(poly) == 0:
        return np.empty((0, 2))
    out = []
    prev = poly[-1]
    fp = float(np.dot(normal, prev) - bound)
    for cur in poly:
        fc = float(np.dot(normal, cur) - bound)
        if (fp <= 1e-8) != (fc <= 1e-8):
            out.append(prev + fp / (fp - fc) * (cur - prev))
        if fc <= 1e-8:
            out.append(cur)
        prev, fp = cur, fc
    if not out:
        return np.empty((0, 2))
    clean = [out[0]]
    for p in out[1:]:
        if np.linalg.norm(p-clean[-1]) > 1e-7:
            clean.append(p)
    if len(clean)>1 and np.linalg.norm(clean[0]-clean[-1])<1e-7:
        clean.pop()
    return np.asarray(clean)

def bearing_clip(poly, position, angle, error=EPS_DEG):
    p = np.asarray(position, dtype=float)
    lo, hi = unit(angle-error), unit(angle+error)
    # cross(lo, x-p)>=0 and cross(hi,x-p)<=0
    for n in (np.array([lo[1], -lo[0]]), np.array([-hi[1], hi[0]])):
        poly = clip(poly, n, float(n @ p))
    return poly

def feasible(observations, error=EPS_DEG):
    """Outer polygon, never an inscribed approximation of a physical disk."""
    poly = np.array([[-1800.,-1800.],[1800.,-1800.],[1800.,1800.],[-1800.,1800.]])
    for deg in np.arange(0.,360.,11.25):
        poly = clip(poly, unit(deg), 1800.)
    for p, angle in observations:
        poly = bearing_clip(poly, p, angle, error)
        for deg in np.arange(0.,360.,22.5):
            n = unit(deg)
            poly = clip(poly,n,float(n@p)+1500.)
    return poly

def diameter(poly):
    if len(poly)==0:
        raise ValueError('Empty region has no localization diameter')
    delta = poly[:,None,:]-poly[None,:,:]
    d2 = (delta*delta).sum(axis=2)
    i,j = np.unravel_index(np.argmax(d2), d2.shape)
    return math.sqrt(float(d2[i,j])), (poly[i],poly[j])

def region_from_bearings(observations,error=1.):
    """Q1 only: exact wedge intersection, with empty/unbounded classification.

    No artificial bounding square or reception disk is added in this function.
    Pair enumeration O(n^3); diameter over finite vertices O(v^2).
    """
    if not observations:
        return {'status':'unbounded','diameter':float('inf'),'vertices':np.empty((0,2))}
    normals=[];bounds=[]
    for p,angle in observations:
        p=np.asarray(p)
        lo,hi=unit(angle-error),unit(angle+error)
        for n in (np.array([lo[1],-lo[0]]),np.array([-hi[1],hi[0]])):
            normals.append(n);bounds.append(float(n@p))
    A=np.array(normals);b=np.array(bounds)
    vertices=[]
    for i,j in itertools.combinations(range(len(A)),2):
        mat=A[[i,j]]
        if abs(np.linalg.det(mat))<1e-12:
            continue
        p=np.linalg.solve(mat,b[[i,j]])
        if np.all(A@p<=b+1e-7) and all(np.linalg.norm(p-q)>1e-6 for q in vertices):
            vertices.append(p)
    if not vertices:
        return {'status':'empty','diameter':None,'vertices':np.empty((0,2))}
    for n in A:
        for d in (np.array([-n[1],n[0]]),np.array([n[1],-n[0]])):
            if np.all(A@d<=1e-10):
                return {'status':'unbounded','diameter':float('inf'),'vertices':np.array(vertices)}
    vertices=np.array(vertices)
    center=vertices.mean(axis=0)
    order=np.argsort(np.arctan2(vertices[:,1]-center[1],vertices[:,0]-center[0]))
    vertices=vertices[order]
    return {'status':'bounded','diameter':diameter(vertices)[0],'vertices':vertices}

def enclosing_circle(poly):
    """Exact candidate enumeration; final radius recomputed over every vertex."""
    if not len(poly):
        raise ValueError('Inconsistent or empty bearing intersection')
    best_c = np.mean(poly,axis=0)
    best_r = float(np.max(np.linalg.norm(poly-best_c,axis=1)))
    def consider(c):
        nonlocal best_c,best_r
        r = float(np.max(np.linalg.norm(poly-c,axis=1)))
        if r < best_r:
            best_c,best_r=c,r
    for p in poly:
        consider(p)
    for a,b in itertools.combinations(poly,2):
        consider((a+b)/2)
    for a,b,c in itertools.combinations(poly,3):
        mat = 2*np.array([b-a,c-a])
        if abs(np.linalg.det(mat))<1e-9:
            continue
        center = a+np.linalg.solve(mat,np.array([np.dot(b-a,b-a),np.dot(c-a,c-a)]))
        consider(center)
    return best_c,best_r

def optical_cover(poly, angle):
    """Cover enclosing rotated rectangle by cells of side <=27, radius <20."""
    u=unit(angle); v=np.array([-u[1],u[0]])
    axes=np.array([u,v])
    q=poly@axes.T
    lo=q.min(axis=0); hi=q.max(axis=0)
    counts=np.maximum(1,np.ceil((hi-lo)/27.).astype(int))
    step=(hi-lo)/counts
    out=[]
    # snake along long dimension; only <=2-3 rows for a single bearing cone
    for j in range(counts[1]):
        ix=range(counts[0]) if j%2==0 else range(counts[0]-1,-1,-1)
        for i in ix:
            out.append((lo+step*np.array([i+.5,j+.5]))@axes)
    return np.asarray(out)

def distance_origin_triangle(t):
    crosses=[]
    for i in range(3):
        a=t[(i+1)%3]-t[i]; b=-t[i]
        crosses.append(float(a[0]*b[1]-a[1]*b[0]))
    if min(crosses)>=-1e-9 or max(crosses)<=1e-9:
        return 0.
    ds=[]
    for a,b in zip(t,np.roll(t,-1,axis=0)):
        d=b-a
        s=np.clip(-float(a@d)/float(d@d),0,1)
        ds.append(np.linalg.norm(a+s*d))
    return float(min(ds))

def search_stations(problem, spacing=950., layout='original'):
    if layout not in ('original','compact','radial','rings'):
        raise ValueError('Unknown coverage layout')
    if layout=='rings':
        if problem!=4 or spacing!=950.:
            raise ValueError('Certified ring coverage requires Q4 and default spacing')
        # 22 sites. Continuous square subdivision certifies that every source
        # is in the convex hull of receivable-distance sites; triangle edge
        # lengths alone are not sufficient to verify this smaller layout.
        a=np.arange(7)*2*np.pi/7;b=np.arange(14)*np.pi/7
        return np.vstack([np.zeros((1,2)),999.*np.column_stack([np.cos(a),np.sin(a)]),
                          1870.*np.column_stack([np.cos(b),np.sin(b)])])
    if layout=='compact' and (problem!=4 or spacing!=950.):
        raise ValueError('Compact boundary coverage is verified only for Q4, spacing 950m')
    if layout=='radial':
        if problem!=4 or spacing!=950.:
            raise ValueError('Radial coverage is verified only for Q4, spacing 950m')
        original=search_stations(4,spacing,layout='original')
        inner=original[np.linalg.norm(original,axis=1)<2000]
        # Collapse each pair of distant vertices into one boundary vertex.
        # The resulting 36 triangles have edges <=983.513m and positive area.
        # Their regular 12-gon boundary has inradius 1835.259m >1800m.
        boundary=np.array([[1900*math.cos(math.radians(30+60*k)),
                            1900*math.sin(math.radians(30+60*k))] for k in range(6)])
        return np.vstack([inner,boundary])
    if problem==3:
        radius=1800*math.cos(math.pi/6)
        return np.array([[0.,0.]]+[list(radius*unit(60*k)) for k in range(6)])
    if not 0<spacing<=1000:
        raise ValueError('Directional coverage requires 0 < spacing <= 1000')
    a=np.array([spacing,0.]); b=np.array([spacing/2,spacing*math.sqrt(3)/2])
    k=math.ceil(2*1800/spacing)+3
    vertices=set()
    for i in range(-k,k+1):
        for j in range(-k,k+1):
            base=i*a+j*b
            for offsets in ([np.zeros(2),a,b],[a,b,a+b]):
                t=np.array([base+z for z in offsets])
                if distance_origin_triangle(t)<=1800+1e-8:
                    vertices.update(tuple(np.round(p,9)) for p in t)
    points=np.array(sorted(vertices))
    if layout=='compact':
        # Keep triangle connectivity and all 13 interior stations unchanged.
        # The 42 deformed triangles keep positive orientation and edges <=1000m;
        # their simple outer boundary stays outside the radius-1800m disk.
        # Thus each target remains enclosed by three receivable-distance sites,
        # at least one of which lies in any transmitting closed half-plane.
        distances=np.linalg.norm(points,axis=1)
        far=distances>2000.
        points[far]*=(1950./distances[far])[:,None]
    return points
