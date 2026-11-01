"""Explicit sketch coordinates and verified constructive steps."""
import math
from cad3d import finite
from diagnostics import error_info
from geometry import frame, vector, dot, to_local, to_world, closed_profiles, profile_world_bounds


def validate_contract(expected):
    expected=dict(expected or {})
    if set(expected)-{'body_count','bounds_mm','volume_mm3','tolerance','relative_tolerance'}:
        raise ValueError('Contract keys: body_count/bounds_mm/volume_mm3/tolerance/relative_tolerance')
    if 'body_count' in expected:
        n=expected['body_count']
        if isinstance(n,bool) or not isinstance(n,int) or n<0: raise ValueError('body_count must be an integer >=0')
    if 'bounds_mm' in expected:
        b=vector(expected['bounds_mm'],6)
        if any(b[i]>b[i+3] for i in range(3)): raise ValueError('Invalid bounds')
        expected['bounds_mm']=b
    if 'volume_mm3' in expected:
        expected['volume_mm3']=finite(expected['volume_mm3'])
        if expected['volume_mm3']<0: raise ValueError('volume_mm3 must be >=0')
    # Kernel volume readback noise is ~5e-7 relative on 1e4..1e5 mm3 models, so 1e-8 rejected valid features.
    for key,default in (('tolerance',1e-6),('relative_tolerance',1e-6)):
        expected[key]=finite(expected.get(key,default))
        if expected[key]<0 or expected[key]>0.01: raise ValueError('Contract tolerances must be 0..0.01')
    return expected


def check_contract(metrics,expected):
    expected=validate_contract(expected); failures=[]
    for key in ('body_count','bounds_mm','volume_mm3'):
        if key not in expected: continue
        actual=metrics[key]; wanted=expected[key]
        if key=='body_count': ok=actual==wanted
        elif key=='bounds_mm': ok=actual is not None and all(math.isclose(a,b,abs_tol=expected['tolerance'],rel_tol=expected['relative_tolerance']) for a,b in zip(actual,wanted))
        else: ok=math.isclose(actual,wanted,abs_tol=expected['tolerance'],rel_tol=expected['relative_tolerance'])
        if not ok: failures.append({'check':key,'expected':wanted,'actual':actual})
    if not metrics['all_solid']: failures.append({'check':'all_bodies_solid','actual':False})
    return failures


class SafeModelingMixin:
    def get_sketch_frame(self,sketch_id):
        sketch=self._entity3d(sketch_id,'sketch')
        import win32com.client as com
        # Support-surface UV is NOT sketch UV (especially XZ/YZ). Use the native
        # sketch conversion, including handedness, location and rotation.
        native=com.CastTo(self.kompas.TransferInterface(sketch,2,11006),'ISketch')
        points=[]
        for uv in ((0,0),(1,0),(0,1)):
            p=native.GetPoint3D(*uv)
            if not p[0]: raise RuntimeError('Cannot read sketch support coordinates')
            points.append(vector(p[1:]))
        origin=points[0]
        x=[a-b for a,b in zip(points[1],origin)]; y=[a-b for a,b in zip(points[2],origin)]
        if not math.isclose(dot(x,x),1,abs_tol=1e-7) or not math.isclose(dot(y,y),1,abs_tol=1e-7):
            raise RuntimeError('Sketch support is not an orthonormal planar parameterization')
        f=frame(origin,x,y)
        return {'success':True,'sketch_id':sketch_id,**f,'units':'mm',
                'coordinate_system':'native sketch-local -> model; normal=x_axis cross y_axis'}

    def transform_sketch_points(self,sketch_id,points,to='model',tolerance=1e-7):
        if to not in ('model','sketch'): raise ValueError('to must be model/sketch')
        tolerance=finite(tolerance,True)
        if tolerance>0.001 or len(points)>1000: raise ValueError('tolerance<=0.001; at most 1000 points')
        points=[vector(p,2 if to=='model' else 3) for p in points]
        f=self.get_sketch_frame(sketch_id)
        return {'success':True,'points':[to_world(f,p) if to=='model' else to_local(f,p,tolerance) for p in points],
                'coordinate_system':to,'sketch_id':sketch_id}

    def _cleanup_created(self,entity,before=None):
        """Delete only this new feature, then verify metrics; no generic Undo."""
        try:
            d3,_=self._part3d()
            if entity.IsCreated() and not d3.DeleteObject(entity): raise RuntimeError('DeleteObject failed')
            if not d3.RebuildDocument(): raise RuntimeError('Cleanup rebuild failed')
            restored=self._model_metrics()
            if before is not None and check_contract(restored,{'body_count':before['body_count'],
                                                              'volume_mm3':before['volume_mm3'],
                                                              **({'bounds_mm':before['bounds_mm']} if before['bounds_mm'] else {})}):
                raise RuntimeError('Metrics after cleanup do not match pre-operation state')
            return {'success':True,'metrics_restored':before is not None}
        except Exception as exc:
            return error_info(exc,'cleanup_new_entity')
        finally:
            try:
                self.registry.invalidate_topology(self._scope())
            except Exception:
                pass  # lost/absent session: the structured cleanup result above must still reach the caller

    def create_closed_profile(self,contours,plane='XY',plane_object_id=None,origin=None,x_axis=None,y_axis=None,name='',tolerance=1e-7):
        loops=closed_profiles(contours,tolerance)
        if (x_axis is None)!=(y_axis is None): raise ValueError('Supply both x_axis and y_axis')
        logical=frame(origin if origin is not None else [0,0,0],x_axis,y_axis) if x_axis is not None else None
        if origin is not None and logical is None: raise ValueError('origin needs explicit x_axis/y_axis')
        sketch_id=None
        try:
            result=self.create_sketch(plane,plane_object_id,name); sketch_id=result['sketch_id']
            native=self.get_sketch_frame(sketch_id)
            logical=logical or native
            # Validate the complete conversion before the first sketch entity.
            to_local(native,logical['origin_mm'],tolerance)
            for axis in ('x_axis','y_axis'):
                if abs(dot(logical[axis],native['normal']))>1e-8: raise ValueError('Requested axes do not lie in the support plane')
            reflection=dot(logical['normal'],native['normal'])<0
            entities=[]
            for loop in loops:
                for s in loop:
                    convert=lambda p:to_local(native,to_world(logical,p),tolerance)
                    if s['kind']=='line':
                        a,b=convert(s['start']),convert(s['end'])
                        entities.append({'kind':'line','x1':a[0],'y1':a[1],'x2':b[0],'y2':b[1]})
                    else:
                        c=convert(s['center']); item={'kind':s['kind'],'x':c[0],'y':c[1],'radius':s['radius']}
                        if s['kind']=='arc':
                            angles=[]
                            for p in (s['start'],s['end']):
                                a=convert(p); angles.append(math.degrees(math.atan2(a[1]-c[1],a[0]-c[0])))
                            item.update(start_angle=angles[0],end_angle=angles[1],direction=-s['direction'] if reflection else s['direction'])
                        entities.append(item)
            self.begin_sketch_edit(sketch_id)
            try:
                created=self.create_sketch_entities(entities)
                if not created['success']: raise RuntimeError(created['message'])
            finally:
                self.end_sketch_edit()
            sketch=self._entity3d(sketch_id,'sketch')
            cache=getattr(self,'_profile_bounds',{})
            bounds=profile_world_bounds(loops,logical)
            cache[sketch_id]={'scope':self._scope(),'stamp':int(sketch.GetFeature().updateStamp),'bounds_mm':bounds}
            self._profile_bounds=cache
            return {'success':True,'sketch_id':sketch_id,'frame':native,'input_frame':logical,
                    'contour_count':len(loops),'entity_count':len(entities),'profile_bounds_mm':bounds,'warnings':[]}
        except Exception as exc:
            cleanup=None
            if sketch_id and not getattr(self,'_editing_sketch',None):
                cleanup=self._cleanup_created(self._entity3d(sketch_id,'sketch'))
            return {**error_info(exc,'create_closed_profile'),'cleanup':cleanup,
                    'warnings':['Cleanup concerns only the new sketch; no transaction/Undo is promised']}

    def _model_metrics(self):
        _,part=self._part3d(); collection=part.BodyCollection(); bodies=[]
        for i in range(collection.GetCount()):
            b=collection.GetByIndex(i); bounds=b.GetGabarit()
            if not bounds[0]: raise RuntimeError('Cannot read body bounds')
            bodies.append({'solid':bool(b.IsSolid()),'bounds_mm':vector(bounds[1:],6),
                           'volume_mm3':finite(b.CalcMassInertiaProperties(1).v)})
        bounds=None
        if bodies:
            bounds=[min(b['bounds_mm'][i] for b in bodies) for i in range(3)]+[max(b['bounds_mm'][i] for b in bodies) for i in range(3,6)]
        return {'body_count':len(bodies),'all_solid':all(b['solid'] for b in bodies),'bounds_mm':bounds,
                'volume_mm3':sum(b['volume_mm3'] for b in bodies),'bodies':bodies}

    def _native_feature_errors(self):
        # Readback without allocating registry handles on EVERY constructive step.
        _,part=self._part3d(); collection=part.EntityCollection(0); errors=[]
        for i in range(collection.GetCount()):
            entity=collection.GetByIndex(i)
            if int(entity.type) in (6,7,8): continue
            feature=entity.GetFeature(); code=int(feature.objectError)
            if not entity.IsCreated() or not feature.IsValid() or code:
                errors.append({'name':entity.name,'type':int(entity.type),'error':code})
        return errors

    def _new_feature_errors(self,baseline):
        """Errors the operation introduced; pre-existing broken user features must not block new work."""
        known={(e['name'],e['type'],e['error']) for e in baseline}
        return [e for e in self._native_feature_errors() if (e['name'],e['type'],e['error']) not in known]

    def _feature_names(self):
        _,part=self._part3d(); collection=part.EntityCollection(0)
        return [e.name for e in (collection.GetByIndex(i) for i in range(collection.GetCount())) if int(e.type) not in (6,7,8)]

    def delete_feature(self,object_id=None,name=''):
        """Delete one 3D feature/sketch by fresh handle or exact unique tree name; report everything removed."""
        from collections import Counter
        if (object_id is None)==(not name): raise ValueError('Give object_id OR an exact feature name')
        d3,part=self._part3d()
        if object_id is not None:
            entity=self._entity_handle(object_id)
        else:
            collection=part.EntityCollection(0)
            matches=[e for e in (collection.GetByIndex(i) for i in range(collection.GetCount()))
                     if int(e.type) not in (6,7,8) and e.name==name]
            if len(matches)!=1: raise ValueError(f'Exact name must match one feature, found {len(matches)}')
            entity=matches[0]
        target=entity.name; names_before=self._feature_names(); before=self._model_metrics()
        try:
            if not d3.DeleteObject(entity): raise RuntimeError('DeleteObject failed')
            if not d3.RebuildDocument(): raise RuntimeError('Rebuild after delete failed')
        finally:
            self.registry.invalidate_topology(self._scope())
        after=self._model_metrics()
        removed=list((Counter(names_before)-Counter(self._feature_names())).elements())
        warnings=[] if removed==[target] else ['Native delete also removed dependent features: inspect removed_features']
        return {'success':True,'deleted':target,'removed_features':removed,'before':before,'after':after,
                'volume_delta_mm3':after['volume_mm3']-before['volume_mm3'],
                'feature_errors':self._native_feature_errors(),'warnings':warnings}

    def check_model_contract(self,expected=None):
        expected=validate_contract(expected); metrics=self._model_metrics(); failures=check_contract(metrics,expected)
        errors=self._native_feature_errors()
        if errors: failures.append({'check':'native_feature_errors','features':errors})
        return {'success':not failures,'metrics':metrics,'failures':failures,'expected':expected,
                'warnings':['Metrics and native validity checks are not manufacturing approval']}

    def cut_through_all(self,sketch_id,direction,both_sides=False,name='',expected=None,target_body_ids=None,cleanup_sketch=False):
        return self.extrusion3d(sketch_id,1,True,False,name,direction,'auto',expected,True,both_sides,target_body_ids,cleanup_sketch)
