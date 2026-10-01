"""Pure geometry validation and explicit coordinate transforms (no COM)."""
import math


def vector(values, size=3):
    if len(values)!=size:
        raise ValueError(f'Expected {size} coordinates')
    result=[float(v) for v in values]
    if not all(math.isfinite(v) for v in result):
        raise ValueError('Coordinates must be finite')
    return result


def dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def cross(a,b):
    return [a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0]]


def unit(values):
    v=vector(values); length=math.sqrt(dot(v,v))
    if length<1e-12:
        raise ValueError('Axis must be nonzero')
    return [x/length for x in v]


def frame(origin,x_axis,y_axis):
    origin=vector(origin); x=unit(x_axis); y=unit(y_axis)
    if abs(dot(x,y))>1e-8:
        raise ValueError('Axes must be orthogonal')
    return {'origin_mm':origin,'x_axis':x,'y_axis':y,'normal':cross(x,y)}


def to_world(f,p):
    p=vector(p,2)
    return [o+p[0]*x+p[1]*y for o,x,y in zip(f['origin_mm'],f['x_axis'],f['y_axis'])]


def to_local(f,p,tolerance=1e-7):
    d=[a-b for a,b in zip(vector(p),f['origin_mm'])]
    if abs(dot(d,f['normal']))>tolerance:
        raise ValueError('Point is outside the sketch support plane')
    return [dot(d,f['x_axis']),dot(d,f['y_axis'])]


def projection_matrix(f):
    # KOMPAS ProjectionMatrix/SetMatrix3D uses placement (view -> world), not
    # world -> view. GetProjectionPoint applies its inverse internally.
    x,y,z=f['x_axis'],f['y_axis'],f['normal']; o=f['origin_mm']
    return [*x,0.,*y,0.,*z,0.,*o,1.]


def arc_point(s,angle):
    a=math.radians(angle)
    return [s['center'][0]+s['radius']*math.cos(a),s['center'][1]+s['radius']*math.sin(a)]


def on_arc(s,p,tol):
    if s['kind']=='circle': return True
    a=math.degrees(math.atan2(p[1]-s['center'][1],p[0]-s['center'][0]))
    sweep=((s['end_angle']-s['start_angle'])*s['direction'])%360
    at=((a-s['start_angle'])*s['direction'])%360
    eps=math.degrees(tol/s['radius'])
    return at<=sweep+eps or at>=360-eps


def intersections(a,b,tol):
    """Exact line/arc boundary intersections; coincident overlap is rejected."""
    if a['kind']=='line' and b['kind']=='line':
        p=a['start']; q=b['start']
        r=[v-u for u,v in zip(p,a['end'])]; s=[v-u for u,v in zip(q,b['end'])]
        c=lambda u,v:u[0]*v[1]-u[1]*v[0]
        qp=[v-u for u,v in zip(p,q)]; det=c(r,s)
        if abs(det)<=tol*max(math.hypot(*r),math.hypot(*s)):
            if abs(c(qp,r))>tol*math.hypot(*r): return []
            rr=dot(r,r); t0=dot(qp,r)/rr; t1=t0+dot(s,r)/rr
            lo=max(0,min(t0,t1)); hi=min(1,max(t0,t1))
            if hi<lo-tol/math.sqrt(rr): return []
            if (hi-lo)*math.sqrt(rr)>tol: raise ValueError('Overlapping profile segments')
            return [[p[i]+lo*r[i] for i in range(2)]]
        t=c(qp,s)/det; u=c(qp,r)/det
        if -tol/math.hypot(*r)<=t<=1+tol/math.hypot(*r) and -tol/math.hypot(*s)<=u<=1+tol/math.hypot(*s):
            return [[p[i]+t*r[i] for i in range(2)]]
        return []
    if b['kind']=='line': return intersections(b,a,tol)
    if a['kind']=='line':
        p=a['start']; d=[v-u for u,v in zip(p,a['end'])]; f=[v-u for v,u in zip(p,b['center'])]
        aa=dot(d,d); bb=2*dot(f,d); cc=dot(f,f)-b['radius']**2
        disc=bb*bb-4*aa*cc
        if disc < -4*aa*tol*(2*b['radius']+tol): return []
        roots=[(-bb+sign*math.sqrt(max(0,disc)))/(2*aa) for sign in (-1,1)]
        points=[[p[i]+t*d[i] for i in range(2)] for t in roots if -tol/math.sqrt(aa)<=t<=1+tol/math.sqrt(aa)]
    else:
        c1,c2=a['center'],b['center']; r1,r2=a['radius'],b['radius']; dist=math.dist(c1,c2)
        if dist<=tol and abs(r1-r2)<=tol:
            if a['kind']=='circle' or b['kind']=='circle': raise ValueError('Coincident circular boundaries')
            def intervals(s):
                start=(s['start_angle'] if s['direction']==1 else s['end_angle'])%360
                sweep=((s['end_angle']-s['start_angle'])*s['direction'])%360
                end=start+sweep
                return [(start,min(360,end))]+([(0,end-360)] if end>360 else [])
            angular_tol=math.degrees(tol/r1)
            if any(min(u[1],v[1])-max(u[0],v[0])>angular_tol for u in intervals(a) for v in intervals(b)):
                raise ValueError('Overlapping arcs')
            return [p for p in (a['start'],a['end']) if on_arc(b,p,tol)]
        if dist<=tol or dist>r1+r2+tol or dist<abs(r1-r2)-tol: return []
        h=(r1*r1-r2*r2+dist*dist)/(2*dist); k=math.sqrt(max(0,r1*r1-h*h))
        u=[(v-w)/dist for v,w in zip(c2,c1)]
        points=[[c1[0]+h*u[0]+sign*k*(-u[1]),c1[1]+h*u[1]+sign*k*u[0]] for sign in (-1,1)]
        points=[p for p in points if on_arc(a,p,tol)]
    return [p for p in points if on_arc(b,p,tol)]


def closed_profiles(contours,tolerance=1e-7):
    tol=float(tolerance)
    if not math.isfinite(tol) or not 0<tol<=0.001: raise ValueError('tolerance must be >0 and <=0.001 mm')
    if not contours or sum(map(len,contours))>500: raise ValueError('Use 1..500 profile segments')
    loops=[]
    for contour in contours:
        if not contour: raise ValueError('Empty contour')
        loop=[]
        for item in contour:
            kind=item['kind']
            if kind=='line':
                s={'kind':kind,'start':vector(item['start'],2),'end':vector(item['end'],2)}
                if math.dist(s['start'],s['end'])<=tol: raise ValueError('Zero length segment')
            elif kind in ('arc','circle'):
                r=float(item['radius'])
                if not math.isfinite(r) or r<=tol: raise ValueError('Radius must exceed tolerance')
                s={'kind':kind,'center':vector(item['center'],2),'radius':r}
                if kind=='arc':
                    a,b=vector([item['start_angle'],item['end_angle']],2); direction=item.get('direction',1)
                    if direction not in (-1,1) or abs(b-a)>=360 or abs((b-a)%360)<1e-10: raise ValueError('Arc needs nonzero sweep <360 degrees')
                    s.update(start_angle=a,end_angle=b,direction=direction)
                    s.update(start=arc_point(s,a),end=arc_point(s,b))
            else: raise ValueError('Profile segments: line/arc/circle')
            loop.append(s)
        if any(s['kind']=='circle' for s in loop):
            if len(loop)!=1: raise ValueError('A circle must occupy its own contour')
        else:
            for a,b in zip(loop,loop[1:]+loop[:1]):
                if math.dist(a['end'],b['start'])>tol: raise ValueError('Contour is not closed: segment endpoints do not match')
        loops.append(loop)
    segments=[(li,si,s) for li,loop in enumerate(loops) for si,s in enumerate(loop)]
    for i,(li,si,a) in enumerate(segments):
        for lj,sj,b in segments[i+1:]:
            allowed=[]
            if li==lj:
                if sj==si+1: allowed.append(a.get('end'))
                if si==0 and sj==len(loops[li])-1: allowed.append(a.get('start'))
            for p in intersections(a,b,tol):
                if not any(q is not None and math.dist(p,q)<=tol for q in allowed):
                    raise ValueError('Profile boundaries intersect or touch outside adjacent endpoints')
    return loops


def profile_world_bounds(loops,f):
    points=[]
    for loop in loops:
        for s in loop:
            if s['kind']=='line': points.extend(to_world(f,p) for p in (s['start'],s['end']))
            else:
                candidates=[]
                for x,y in zip(f['x_axis'],f['y_axis']):
                    a=math.degrees(math.atan2(y,x)); candidates.extend((a,a+180))
                if s['kind']=='arc': candidates.extend((s['start_angle'],s['end_angle']))
                for a in candidates:
                    p=arc_point(s,a)
                    if on_arc(s,p,1e-7): points.append(to_world(f,p))
    return [min(p[i] for p in points) for i in range(3)]+[max(p[i] for p in points) for i in range(3)]


def bbox_overlap(a,b,tolerance=1e-7):
    return all(a[i]<=b[i+3]+tolerance and b[i]<=a[i+3]+tolerance for i in range(3))
