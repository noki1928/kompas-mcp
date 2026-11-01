"""Native model editing/introspection layered over the existing working API5 core."""
import math

from cad3d import finite
from diagnostics import error_info


class ModelingMixin:
    def _part3d(self):
        d3, _ = self._root('doc3d')
        return d3, d3.GetPart(-1)

    def _entity_handle(self, object_id):
        self._sync_handles()
        entry = self.registry.get(object_id, self._open_refs())
        if entry.scope != self._scope():
            raise ValueError('Activate the object owning document first')
        return entry.obj

    def _finish_feature(self, entity, operation, expected=None, volume_change=None):
        from safe_modeling import validate_contract, check_contract
        expected=validate_contract(expected)
        before=self._model_metrics()
        expected.setdefault('body_count',1 if operation=='revolve' else before['body_count'])
        d3, _ = self._part3d()
        after=None; failures=[]
        baseline_errors=self._native_feature_errors()
        try:
            if not entity.Create() or not entity.IsCreated():
                raise RuntimeError(f'{operation}: native feature creation failed')
            if not d3.RebuildDocument():
                raise RuntimeError('Native rebuild failed')
            after=self._model_metrics(); failures=check_contract(after,expected)
            delta=after['volume_mm3']-before['volume_mm3']; threshold=max(1e-7,abs(before['volume_mm3'])*1e-9)
            if (volume_change=='increase' and delta<=threshold) or (volume_change=='decrease' and delta>=-threshold):
                failures.append({'check':'volume_'+volume_change,'delta_mm3':delta})
            errors=self._new_feature_errors(baseline_errors)
            if errors: failures.append({'check':'native_document_valid','features':errors})
            if failures: raise RuntimeError('New feature result failed geometric contract')
        except Exception as exc:
            return {**error_info(exc,operation),'before':before,'rejected_result':after,'failures':failures,
                    'cleanup':self._cleanup_created(entity,before)}
        finally:
            self.registry.invalidate_topology(self._scope())
        return {'success': True, 'feature_id': self._remember3d(entity, 'feature'),
                'operation': operation, 'name': entity.name, 'document_reference': self._scope(),
                'rebuild_required': False,'before':before,'after':after,'volume_delta_mm3':delta,
                'checks_passed':True,'preexisting_feature_errors':baseline_errors,'warnings': []}

    def create_sketch(self, plane='XY', plane_object_id=None, name=''):
        d3, part = self._part3d()
        if plane_object_id:
            support = self._entity_handle(plane_object_id)
            if int(support.type) == 6 and not support.GetDefinition().IsPlanar():
                raise ValueError('Sketch support must be planar')
        else:
            if plane not in ('XY', 'XZ', 'YZ'):
                raise ValueError('plane must be XY/XZ/YZ')
            support = part.GetDefaultEntity({'XY': 1, 'XZ': 2, 'YZ': 3}[plane])
        sketch = part.NewEntity(5)
        if name:
            sketch.name = name
        if not sketch.GetDefinition().SetPlane(support) or not sketch.Create():
            raise RuntimeError('Could not create sketch on support')
        return {'success': True, 'sketch_id': self._remember3d(sketch, 'sketch'),
                'name': sketch.name, 'document_reference': self._scope()}

    def begin_sketch_edit(self, sketch_id):
        if getattr(self, '_editing_sketch', None):
            raise RuntimeError('Another managed sketch is already being edited; end it first')
        sketch = self._entity3d(sketch_id, 'sketch')
        definition = sketch.GetDefinition()
        edit = definition.BeginEdit()
        if edit is None:
            raise RuntimeError('BeginEdit returned no 2D context')
        self._editing_sketch = (self._scope(), sketch_id, definition, edit)
        key=self.registry.put(edit,self._scope(),'edit_context')
        return {'success': True, 'sketch_id': sketch_id,
                'edit_context':{'object_id':key,'kind':'edit_context','document_reference':self._scope()}}

    def create_sketch_entities(self, entities):
        state = getattr(self, '_editing_sketch', None)
        if not state or state[0] != self._scope():
            raise RuntimeError('Call begin_sketch_edit in the active part first')
        if len(entities) > 500:
            raise ValueError('Maximum 500 entities per batch')
        edit = state[3]
        refs = []
        for i, item in enumerate(entities):
            try:
                kind = item['kind']
                style = int(item.get('style', 1))
                if not 1 <= style <= 9:
                    raise ValueError('style must be 1..9; 3 is axial, 6 auxiliary')
                if kind == 'line':
                    coords = [finite(item[n]) for n in ('x1','y1','x2','y2')]
                    if coords[:2]==coords[2:]:
                        raise ValueError('Line must have nonzero length')
                    ref = edit.ksLineSeg(*coords, style)
                elif kind == 'circle':
                    ref = edit.ksCircle(finite(item['x']), finite(item['y']), finite(item['radius'], True), style)
                elif kind == 'arc':
                    ref = edit.ksArcByAngle(finite(item['x']), finite(item['y']), finite(item['radius'], True),
                                             finite(item['start_angle']), finite(item['end_angle']),
                                             int(item.get('direction', 1)), style)
                elif kind == 'point':
                    ref = edit.ksPoint(finite(item['x']), finite(item['y']), style)
                elif kind in ('rectangle', 'polygon'):
                    if kind == 'rectangle':
                        x,y,width,height = (finite(item['x']),finite(item['y']),
                                            finite(item['width'],True),finite(item['height'],True))
                        points = [[x,y],[x+width,y],[x+width,y+height],[x,y+height]]
                    else:
                        from cad3d import validate_profiles
                        points = validate_profiles([], [], [item['points']])[2][0]
                    for a,b in zip(points,points[1:]+points[:1]):
                        ref = edit.ksLineSeg(*a,*b,style)
                        if not ref:
                            raise RuntimeError('Segment not created')
                        refs.append(int(ref))
                    continue
                else:
                    raise ValueError('kind: line/circle/arc/point/rectangle/polygon; other entities via edit_context and generic API')
                if not ref:
                    raise RuntimeError('Sketch entity reference is zero')
                refs.append(int(ref))
            except Exception as exc:
                return {**error_info(exc,'create_sketch_entities'), 'failed_index': i,
                        'created_references': refs, 'atomic': False,
                        'suggested_actions': ['Delete partial entities through edit_context or restore checkpoint; end_sketch_edit before other operations']}
        return {'success': True, 'sketch_id': state[1], 'references': refs, 'atomic': False}

    def end_sketch_edit(self):
        state = getattr(self, '_editing_sketch', None)
        if not state or state[0] != self._scope():
            raise RuntimeError('No managed sketch edit in the active document')
        if not state[2].EndEdit():
            raise RuntimeError('EndEdit failed; edit state retained for recovery')
        self._editing_sketch = None
        self.registry.release([key for key,entry in self.registry.entries.items()
                               if entry.scope==state[0] and entry.kind=='edit_context'])
        self.registry.invalidate_topology(self._scope())
        return {'success': True, 'sketch_id': state[1], 'rebuild_required': True}

    def revolve(self, sketch_id, angle=360, cut=False, reverse=False, name='',expected=None):
        from safe_modeling import validate_contract
        expected=validate_contract(expected)
        angle = finite(angle, True)
        if angle > 360:
            raise ValueError('angle must be <=360 degrees')
        _, part = self._part3d()
        sketch = self._entity3d(sketch_id, 'sketch')
        entity = part.NewEntity(29 if cut else 28)
        definition = entity.GetDefinition()
        if not definition.SetSketch(sketch):
            raise RuntimeError('Could not set rotation sketch')
        definition.directionType=1 if reverse else 0
        if not definition.SetSideParam(not reverse, angle):
            raise RuntimeError('Could not set rotation angle')
        definition.chooseType=3  # ksChBodies, not ksChooseBodiesType
        definition.ChooseBodies().ChooseBodiesType=3 if cut else 1
        if name:
            entity.name = name
        return self._finish_feature(entity, 'cut_revolve' if cut else 'revolve',expected,'decrease' if cut else 'increase')

    def edge_operation(self, edge_ids, operation, size, distance2=None, tangent=False, name='',expected=None):
        from safe_modeling import validate_contract
        expected=validate_contract(expected)
        size = finite(size, True)
        distance2=finite(distance2,True) if distance2 is not None else size
        if operation not in ('chamfer','fillet') or not edge_ids:
            raise ValueError('operation=chamfer/fillet and non-empty edge_ids required')
        _, part = self._part3d()
        edges = [self._entity_handle(key) for key in edge_ids]
        if any(int(e.type) != 7 for e in edges):
            raise ValueError('All handles must refer to API5 edge entities')
        entity = part.NewEntity(33 if operation == 'chamfer' else 34)
        definition = entity.GetDefinition()
        if operation == 'chamfer':
            # transfer=True uses two distances; equal distances yield 45 degrees.
            if not definition.SetChamferParam(True, size, distance2):
                raise RuntimeError('Could not set chamfer distances')
        else:
            definition.radius=size
        definition.tangent=bool(tangent)
        array = definition.array()
        for edge in edges:
            if not array.Add(edge):
                raise RuntimeError('Could not add edge to operation')
        if name:
            entity.name = name
        return self._finish_feature(entity, operation,expected)

    def get_model_tree(self, name='', type_id=None, limit=1000):
        if not 1<=limit<=10000:
            raise ValueError('limit must be 1..10000')
        self._sync_handles()
        _, part = self._part3d()
        collection = part.EntityCollection(0)
        nodes, warnings = [], []
        for i in range(collection.GetCount()):
            entity = collection.GetByIndex(i)
            typ = int(entity.type)
            if typ in (6,7,8) or (type_id is not None and typ != type_id) or name.lower() not in entity.name.lower():
                continue
            key = self._remember3d(entity,'sketch' if typ == 5 else 'feature')
            row = {'object_id':key,'type':typ,'name':entity.name,'created':bool(entity.IsCreated()),
                   'hidden':bool(entity.hidden),'excluded':bool(entity.excluded)}
            try:
                feature = entity.GetFeature()
                row.update({'valid':bool(feature.IsValid()),'update_stamp':int(feature.updateStamp),
                            'error':self._encode(feature.objectError,self._scope())})
                owner = feature.GetOwnerFeature()
                row['owner'] = self._encode(owner,self._scope()) if owner else None
            except Exception as exc:
                row['diagnostic_error'] = error_info(exc,'IFeature inspection',key)
            nodes.append(row)
        return {'success':True,'document':self.describe(self.active()),'nodes':nodes[:limit],
                'total':len(nodes),'truncated':len(nodes)>limit,
                'warnings':warnings,'units':{'length':'mm','angle':'degree'}}

    def get_feature_parameters(self, feature_id):
        entity = self._entity_handle(feature_id)
        typ = int(entity.type)
        definition = entity.GetDefinition()
        params = {}
        if typ in (24,25,26):
            params = {'direction_type':int(definition.directionType),
                      'normal_side':self._encode(definition.GetSideParam(True)),
                      'reverse_side':self._encode(definition.GetSideParam(False))}
        elif typ in (27,28,29):
            params = {'direction_type':int(definition.directionType),
                      'normal_side':self._encode(definition.GetSideParam(True)),
                      'reverse_side':self._encode(definition.GetSideParam(False))}
        elif typ == 33:
            params = {'chamfer':self._encode(definition.GetChamferParam()),'tangent':bool(definition.tangent)}
        elif typ == 34:
            params = {'radius':float(definition.radius),'tangent':bool(definition.tangent)}
        return {'success':True,'feature_id':feature_id,'type':typ,'name':entity.name,
                'parameters':params,'definition':self._encode(definition,self._scope()),
                'warnings':[] if params else ['Use describe_object and kompas_api_call on definition for this operation']}

    def set_feature_parameters(self, feature_id, parameters):
        entity = self._entity_handle(feature_id)
        typ = int(entity.type)
        definition = entity.GetDefinition()
        allowed = {24:{'depth','reverse'},25:{'depth','reverse'},26:{'depth','reverse'},
                   27:{'angle','reverse'},28:{'angle','reverse'},29:{'angle','reverse'},
                   33:{'distance1','distance2','tangent'},34:{'radius','tangent'}}
        if typ not in allowed or set(parameters)-allowed[typ]:
            raise ValueError('Unsupported semantic parameters; inspect definition via generic API')
        old = self.get_feature_parameters(feature_id)['parameters']
        # Validate the entire request before assigning ANY native property.
        numeric={key:finite(value,True) for key,value in parameters.items()
                 if key in {'depth','angle','distance1','distance2','radius'}}
        if numeric.get('angle',0)>360:
            raise ValueError('angle must be <=360')
        for key in ('reverse','tangent'):
            if key in parameters and not isinstance(parameters[key],bool):
                raise ValueError(f'{key} must be a boolean')
        try:
            if typ in (24,25,26):
                direction = int(old['direction_type'])
                if 'reverse' in parameters:
                    direction = int(bool(parameters['reverse']) != (typ == 26))
                definition.directionType = direction
                side = not bool(direction)
                existing = definition.GetSideParam(side)
                depth = finite(parameters.get('depth',existing[2]),True)
                if not definition.SetSideParam(side,0,depth,0,False):
                    raise RuntimeError('SetSideParam failed')
            elif typ in (27,28,29):
                direction = int(parameters.get('reverse',old['direction_type']))
                existing=definition.GetSideParam(not bool(old['direction_type']))
                angle = finite(parameters.get('angle',existing[1]),True)
                if angle > 360:
                    raise ValueError('angle must be <=360')
                definition.directionType=direction
                if not definition.SetSideParam(not bool(direction),angle):
                    raise RuntimeError('SetSideParam failed')
            elif typ == 33:
                old_chamfer = definition.GetChamferParam()
                if not definition.SetChamferParam(True,finite(parameters.get('distance1',old_chamfer[2]),True),
                                                 finite(parameters.get('distance2',old_chamfer[3]),True)):
                    raise RuntimeError('SetChamferParam failed')
                definition.tangent=parameters.get('tangent',old['tangent'])
            else:
                definition.radius=finite(parameters.get('radius',old['radius']),True)
                definition.tangent=parameters.get('tangent',old['tangent'])
            if not entity.Update():
                raise RuntimeError('Feature Update failed; inspect rebuild errors and restore checkpoint')
            if not self.rebuild_model()['success']:
                raise RuntimeError('Rebuild failed after parameter update')
        except Exception as exc:
            return {**error_info(exc,'set_feature_parameters',feature_id),
                    'previous_parameters':old,'warnings':['Change may be partial; restore checkpoint or reapply previous parameters']}
        return self.get_feature_parameters(feature_id)

    def rebuild_model(self):
        d3,_ = self._part3d()
        ok = bool(d3.RebuildDocument())
        self.registry.invalidate_topology(self._scope())
        return {'success':ok,'document_reference':self._scope(),'warnings':[] if ok else ['Native rebuild returned false']}

    def get_model_properties(self):
        self._sync_handles()
        _,part = self._part3d()
        collection = part.BodyCollection()
        bodies = []
        for i in range(collection.GetCount()):
            body = collection.GetByIndex(i)
            bounds = body.GetGabarit()
            mass = body.CalcMassInertiaProperties(1)
            bodies.append({'object_id':self.registry.put(body,self._scope(),'topology'),
                           'solid':bool(body.IsSolid()),'bounds_mm':list(bounds[1:]) if bounds[0] else None,
                           'volume_mm3':float(mass.v),'surface_area_mm2':float(mass.F),
                           'mass_g':float(mass.m),'center_mm':[float(mass.xc),float(mass.yc),float(mass.zc)]})
        mass = part.CalcMassInertiaProperties(1)
        return {'success':True,'bodies':bodies,'volume_mm3':float(mass.v),'mass_g':float(mass.m),
                'center_mm':[float(mass.xc),float(mass.yc),float(mass.zc)],
                'warnings':['Mass uses the material density stored in KOMPAS; no default material was assigned by the server']}

    def find_faces(self, surface_type='', radius=None, tolerance=0.01, limit=100, largest_first=False):
        if not 1<=limit<=10000 or surface_type not in ('','plane','cylinder','cone','sphere','torus','nurbs','other'):
            raise ValueError('Invalid surface_type or limit (1..10000)')
        tolerance=finite(tolerance)
        if tolerance<0:
            raise ValueError('tolerance must be >=0')
        radius=finite(radius,True) if radius is not None else None
        self._sync_handles()
        _,part = self._part3d()
        collection = part.EntityCollection(6)
        rows = []
        for i in range(collection.GetCount()):
            entity = collection.GetByIndex(i)
            definition = entity.GetDefinition()
            typ = next((n for n,m in [('plane','IsPlanar'),('cylinder','IsCylinder'),('cone','IsCone'),
                                     ('sphere','IsSphere'),('torus','IsTorus'),('nurbs','IsNurbsSurface')]
                        if getattr(definition,m)()), 'other')
            if surface_type and surface_type != typ:
                continue
            row = {'surface_type':typ,'object_id':self.registry.put(entity,self._scope(),'topology')}
            try:
                row['area_mm2'] = float(definition.GetArea(1))
                surf = definition.GetSurface()
                b = surf.GetGabarit()
                row['bounds_mm'] = list(b[1:]) if b[0] else None
                if typ == 'cylinder':
                    cyl = definition.GetCylinderParam()
                    row['radius_mm'] = float(cyl[2])
                    row['height_mm'] = float(cyl[1])
                if radius is not None and (typ != 'cylinder' or abs(row['radius_mm']-radius)>tolerance):
                    continue
                u = (surf.GetParamUMin()+surf.GetParamUMax())/2
                v = (surf.GetParamVMin()+surf.GetParamVMax())/2
                if math.isfinite(u) and math.isfinite(v):
                    normal = surf.GetNormal(u,v)
                    row['sample_normal'] = list(normal[1:]) if normal[0] else None
                    row['normal_orientation'] = bool(definition.normalOrientation)
            except Exception as exc:
                row['diagnostic_error'] = error_info(exc,'face geometry',row['object_id'])
            rows.append(row)
        if largest_first:
            rows.sort(key=lambda r:r.get('area_mm2',0),reverse=True)
        return {'success':True,'faces':rows[:limit],'total':len(rows),'truncated':len(rows)>limit}

    def find_edges(self, curve_type='', min_length=0, max_length=None, limit=100):
        if not 1<=limit<=10000 or curve_type not in ('','line','circle','arc','ellipse','nurbs','other'):
            raise ValueError('Invalid curve_type or limit (1..10000)')
        min_length=finite(min_length)
        max_length=finite(max_length) if max_length is not None else None
        if min_length<0 or (max_length is not None and max_length<min_length):
            raise ValueError('Lengths must satisfy 0<=min_length<=max_length')
        self._sync_handles()
        _,part = self._part3d()
        collection = part.EntityCollection(7)
        rows = []
        for i in range(collection.GetCount()):
            entity = collection.GetByIndex(i)
            definition = entity.GetDefinition()
            typ = next((n for n,m in [('circle','IsCircle'),('arc','IsArc'),('line','IsStraight'),
                                     ('ellipse','IsEllipse'),('nurbs','IsNurbs')] if getattr(definition,m)()),'other')
            length = float(definition.GetLength(1))
            if (curve_type and typ!=curve_type) or length<min_length or (max_length is not None and length>max_length):
                continue
            row = {'object_id':self.registry.put(entity,self._scope(),'topology'),'curve_type':typ,'length_mm':length}
            try:
                points=[]
                for first in (True,False):
                    vertex=definition.GetVertex(first)
                    if vertex is not None:
                        if not hasattr(vertex,'GetPoint'):
                            vertex=vertex.GetDefinition()
                        point=vertex.GetPoint()
                        points.append(list(point[1:]) if point[0] else None)
                row['endpoints_mm']=points
                curve=definition.GetCurve3D()
                b=curve.GetGabarit()
                row['bounds_mm']=list(b[1:]) if b[0] else None
            except Exception as exc:
                row['diagnostic_error']=error_info(exc,'edge geometry',row['object_id'])
            rows.append(row)
        return {'success':True,'edges':rows[:limit],'total':len(rows),'truncated':len(rows)>limit}

    def validate_document(self):
        doc=self.active()
        if doc.DocumentType not in (4,5,7):
            return {'success':True,'document':self.describe(doc),'checks':['document accessible'],
                    'warnings':['2D geometry correctness and dimension sufficiency require visual review']}
        tree=self.get_model_tree()
        errors=[n for n in tree['nodes'] if not n.get('created') or n.get('valid') is False
                or (isinstance(n.get('error'),int) and n['error']!=0)]
        suppressed=[n for n in tree['nodes'] if n.get('excluded')]
        properties=self.get_model_properties()
        return {'success':not errors,'document':self.describe(doc),'invalid_features':errors,
                'suppressed_features':suppressed,'properties':properties,
                'warnings':['Validation is not a manufacturing/engineering approval; inspect errors, dimensions and images. Native feature errors are included in the tree.']}
