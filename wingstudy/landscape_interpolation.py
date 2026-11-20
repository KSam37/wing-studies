"""Shared bounded interpolation for measured three-dimensional landscapes."""
import math
import numpy as np


def interpolate(points,force_curve=False):
    """Keep every measured glyph; interpolate the highest Z at duplicate XY.

    Surface patches remain inside the measured convex hull and inside their
    measured corner-value range. Collinear/fixed-span data use a bounded curve.
    """
    xy=np.array([p["coords"][:2] for p in points]);scales=np.maximum(np.max(np.abs(xy),axis=0),1e-12)
    groups={}
    for i,p in enumerate(points):groups.setdefault(tuple(np.round(xy[i]/scales,10)),[]).append(i)
    selected=[max(group,key=lambda i:points[i]["value"]) for group in groups.values()]
    vertices=np.array([points[i]["coords"] for i in selected]);triangles=[];curve=[];kind="points"
    from scipy.interpolate import PchipInterpolator,CloughTocher2DInterpolator
    def smooth_curve(knots,values):
        steps=max(2,min(32,2000//len(knots)))
        samples=np.r_[np.concatenate([np.linspace(a,b,steps,endpoint=False) for a,b in zip(knots,knots[1:])]),knots[-1]]
        return samples,PchipInterpolator(knots,values,axis=0,extrapolate=False)(samples)
    if len(vertices)>=2:
        extent=np.ptp(vertices[:,:2],axis=0);origin=vertices[:,:2].min(axis=0)
        norm=(vertices[:,:2]-origin)/np.where(extent>0,extent,1.)
        if not force_curve and len(vertices)>=3 and np.linalg.matrix_rank(norm-norm.mean(axis=0),tol=1e-10)==2:
            from scipy.spatial import Delaunay,QhullError
            try:
                base=Delaunay(norm)
                interpolator=CloughTocher2DInterpolator(base,vertices[:,2],tol=1e-10,maxiter=1000)
                # Sample each original triangle barycentrically: shared edge
                # vertices stay shared and no point extends outside the hull.
                subdivisions=max(1,min(14,int(math.sqrt(2400/len(base.simplices)))))
                dense=[];bounded_values=[];lookup={};faces=[]
                # Cubic Bezier controls stay between measured endpoint values.
                # Shared edge controls make adjacent patches continuous.
                gradients=interpolator.grad[:,0,:]
                for tri in base.simplices:
                    local={}
                    heights=vertices[tri,2];controls={}
                    for a in range(3):
                        for b in range(3):
                            if a!=b:
                                estimate=heights[a]+np.dot(gradients[tri[a]],norm[tri[b]]-norm[tri[a]])/3
                                controls[a,b]=float(np.clip(estimate,min(heights[a],heights[b]),max(heights[a],heights[b])))
                    center=float(np.mean(list(controls.values())))
                    for i in range(subdivisions+1):
                        for j in range(subdivisions+1-i):
                            uv=((subdivisions-i-j)*norm[tri[0]]+i*norm[tri[1]]+j*norm[tri[2]])/subdivisions
                            key=tuple(np.round(uv,13))
                            if key not in lookup:
                                weights=np.array([subdivisions-i-j,i,j],dtype=float)/subdivisions
                                value=float(np.dot(heights,weights**3))
                                value+=sum(3*weights[a]**2*weights[b]*v for (a,b),v in controls.items())
                                value+=6*float(np.prod(weights))*center
                                lookup[key]=len(dense);dense.append(uv);bounded_values.append(value)
                            local[i,j]=lookup[key]
                    for i in range(subdivisions):
                        for j in range(subdivisions-i):
                            faces.append([local[i,j],local[i+1,j],local[i,j+1]])
                            if i+j<subdivisions-1:faces.append([local[i+1,j],local[i+1,j+1],local[i,j+1]])
                dense=np.array(dense);values=np.asarray(bounded_values)
                if not np.all(np.isfinite(values)):raise ValueError("Cubic interpolation returned non-finite values.")
                vertices=np.column_stack((origin+dense*extent,values));triangles=faces;kind="bounded_cubic_surface"
            except QhullError:pass
        if not triangles:
            axis=int(np.argmax(extent/scales));order=np.argsort(vertices[:,axis]);vertices=vertices[order];selected=[selected[i] for i in order]
            distance=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(norm[order],axis=0),axis=1))]
            _,values=smooth_curve(distance,vertices);curve=values.tolist();kind="smooth_sampled_curve"
    return vertices,triangles,curve,kind,selected
