"""Basic native API5 3D operations. COM handles never leave the worker thread.

Constants verified against KOMPAS v25 Bin/constants3d.py:
XOY=1, XOZ=2, YOZ=3, sketch=5, bossExtrusion=25, cutExtrusion=26,
pTop_Part=-1, dtNormal=0, dtReverse=1, etBlind=0.
"""
import math
import time
import uuid


def finite(value, positive=False):
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("Нужно конечное число" + (" > 0" if positive else ""))
    return value


def validate_profiles(rectangles, circles, polygons):
    if not (rectangles or circles or polygons):
        raise ValueError("Эскиз должен содержать хотя бы один замкнутый профиль")
    rects, circs, polys = [], [], []
    for rect in rectangles:
        if len(rect) != 4:
            raise ValueError("Прямоугольник: [x, y, width, height]")
        rects.append([finite(rect[0]), finite(rect[1]), finite(rect[2], True), finite(rect[3], True)])
    for circle in circles:
        if len(circle) != 3:
            raise ValueError("Окружность: [x, y, radius]")
        circs.append([finite(circle[0]), finite(circle[1]), finite(circle[2], True)])
    for polygon in polygons:
        if any(len(p) != 2 for p in polygon):
            raise ValueError("Вершина многоугольника: [x, y]")
        pts = [[finite(v) for v in p] for p in polygon]
        if len(pts) > 1 and pts[0] == pts[-1]:
            pts.pop()
        if len(pts) < 3 or len({tuple(p) for p in pts}) != len(pts):
            raise ValueError("Нужно минимум три разные вершины")
        area2 = sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(pts, pts[1:]+pts[:1]))
        if abs(area2) < 1e-9:
            raise ValueError("Профиль имеет нулевую площадь")
        polys.append(pts)
    return rects, circs, polys


class Cad3DMixin:
    def doc3d(self):
        import pythoncom
        doc = self.active()
        if doc.DocumentType != 4:
            raise RuntimeError("Нужна активная 3D-деталь (kind=part), не сборка или 2D.")
        # UI activation and API5 synchronization can lag behind Documents.Add.
        for _ in range(20):
            pythoncom.PumpWaitingMessages()
            d3 = self.kompas.ActiveDocument3D
            if d3 is not None and int(d3.reference) == int(doc.Reference):
                return d3
            time.sleep(0.05)
        raise RuntimeError("API5/API7 не согласовали активную 3D-деталь. Повторите status.")

    def _remember3d(self, entity, kind):
        if hasattr(self, 'registry'):
            return self.registry.put(entity, int(self.active().Reference), kind,
                                     {'name': entity.name, 'type': int(entity.type)})
        if not hasattr(self, "_entities3d"):
            self._entities3d = {}
        docref = int(self.active().Reference)
        # Prune references to other documents; IDs are session/document-local.
        self._entities3d = {k: v for k, v in self._entities3d.items() if v[0] == docref}
        handle = uuid.uuid4().hex
        self._entities3d[handle] = (docref, entity, kind)
        return handle

    def _entity3d(self, handle, kind):
        if hasattr(self, 'registry') and handle.startswith('obj_'):
            entry = self.registry.get(handle, self._open_refs())
            if entry.scope != int(self.active().Reference) or entry.kind != kind:
                raise ValueError('3D handle belongs to another document or type')
            if not entry.obj.IsCreated():
                raise ValueError('3D object no longer exists')
            return entry.obj
        entry = getattr(self, "_entities3d", {}).get(handle)
        if entry is None or entry[0] != int(self.active().Reference) or entry[2] != kind:
            raise ValueError("Неизвестный/устаревший 3D-ID или другой документ. Запросите model_info.")
        if not entry[1].IsCreated():
            raise ValueError("3D-объект уже не существует")
        return entry[1]

    def sketch3d(self, plane="XY", rectangles=(), circles=(), polygons=(), name=""):
        if plane not in ("XY", "XZ", "YZ"):
            raise ValueError("plane must be XY, XZ or YZ")
        rects, circs, polys = validate_profiles(rectangles, circles, polygons)
        d3 = self.doc3d()
        part = d3.GetPart(-1)
        sketch = part.NewEntity(5)
        definition = sketch.GetDefinition()
        if not definition.SetPlane(part.GetDefaultEntity({"XY": 1, "XZ": 2, "YZ": 3}[plane])):
            raise RuntimeError("Не удалось задать плоскость эскиза")
        if name:
            sketch.name = name
        if not sketch.Create():
            raise RuntimeError("Не удалось создать эскиз")
        try:
            edit = definition.BeginEdit()
            if edit is None:
                raise RuntimeError("Не удалось открыть эскиз на редактирование")
            try:
                for x, y, width, height in rects:
                    polys.append([[x, y], [x+width, y], [x+width, y+height], [x, y+height]])
                for pts in polys:
                    for a, b in zip(pts, pts[1:]+pts[:1]):
                        if not edit.ksLineSeg(*a, *b, 1):
                            raise RuntimeError("Не удалось добавить отрезок эскиза")
                for x, y, radius in circs:
                    if not edit.ksCircle(x, y, radius, 1):
                        raise RuntimeError("Не удалось добавить окружность эскиза")
            finally:
                if not definition.EndEdit():
                    raise RuntimeError("Не удалось завершить редактирование эскиза")
        except Exception:
            d3.DeleteObject(sketch)
            raise
        if hasattr(self,'registry'):
            self.registry.invalidate_topology(int(self.active().Reference))
        return {"sketch_id": self._remember3d(sketch, "sketch"), "plane": plane,
                "name": sketch.name, "document_reference": int(self.active().Reference)}

    def extrusion3d(self, sketch_id, depth, cut=False, reverse=False, name="", direction=None,
                    result_mode='join',expected=None,through_all=False,both_sides=False,target_body_ids=None):
        depth = finite(depth, True)
        from geometry import unit, dot, bbox_overlap
        from safe_modeling import validate_contract, check_contract
        from diagnostics import error_info
        expected=validate_contract(expected)
        if result_mode not in ('join','auto','new_body'): raise ValueError('result_mode must be join/auto/new_body')
        if target_body_ids is not None and (not cut or not target_body_ids or len(set(target_body_ids))!=len(target_body_ids)):
            raise ValueError('Nonempty unique target_body_ids are supported for cuts only')
        if both_sides and not through_all: raise ValueError('both_sides requires through_all')
        if through_all and not cut: raise ValueError('Through-all is a cut operation')
        direction=unit(direction) if direction is not None else None
        if direction is not None and reverse: raise ValueError('Use direction OR reverse, not both')
        d3 = self.doc3d()
        sketch = self._entity3d(sketch_id, "sketch")
        part = d3.GetPart(-1)
        native=self.get_sketch_frame(sketch_id)
        if direction is not None:
            alignment=dot(direction,native['normal'])
            if abs(abs(alignment)-1)>1e-8: raise ValueError('Extrusion direction must be perpendicular to sketch plane')
            reverse=alignment<0
        actual_direction=[(-1 if reverse else 1)*v for v in native['normal']]
        before=self._model_metrics()
        target_bodies=[]
        if target_body_ids is not None:
            import pythoncom
            collection=part.BodyCollection()
            identities=[collection.GetByIndex(i)._oleobj_.QueryInterface(pythoncom.IID_IUnknown) for i in range(collection.GetCount())]
            for key in target_body_ids:
                body=self._entity_handle(key)
                if not hasattr(body,'IsSolid') or body._oleobj_.QueryInterface(pythoncom.IID_IUnknown) not in identities:
                    raise ValueError('Target must be a fresh body handle in active top part')
                target_bodies.append(body)
        if cut and not before['body_count']:
            raise ValueError("Вырез требует существующего тела")
        if not before['all_solid']: raise ValueError('Operation requires solid target bodies')
        if not cut and result_mode=='join':
            if 'body_count' in expected and expected['body_count']!=1: raise ValueError('join requires expected body_count=1')
            expected['body_count']=1
        if cut: expected.setdefault('body_count',before['body_count'])
        if not cut and result_mode=='new_body': expected.setdefault('body_count',before['body_count']+1)
        # Necessary direction check only; native kernel decides true intersection.
        if cut and not both_sides:
            import itertools
            b=before['bounds_mm']; origin=native['origin_mm']
            distances=[dot([p[i]-origin[i] for i in range(3)],actual_direction)
                       for p in itertools.product(*[(b[i],b[i+3]) for i in range(3)])]
            if max(distances)<-1e-7 or (not through_all and min(distances)>depth+1e-7):
                raise ValueError('Cut direction/depth cannot reach target body bounding box; no mutation performed')
        precheck='direction_interval_only' if cut else 'not_applicable'
        cached=getattr(self,'_profile_bounds',{}).get(sketch_id)
        if cut and cached and cached['scope']==self._scope() and cached['stamp']==int(sketch.GetFeature().updateStamp):
            import itertools
            b=before['bounds_mm']; o=native['origin_mm']
            reach=max(0,max(dot([p[i]-o[i] for i in range(3)],actual_direction)
                              for p in itertools.product(*[(b[i],b[i+3]) for i in range(3)])))+1
            if both_sides:
                reach=max(reach,max(abs(dot([p[i]-o[i] for i in range(3)],actual_direction))
                                    for p in itertools.product(*[(b[i],b[i+3]) for i in range(3)]))+1)
            distance=reach if through_all else depth
            pb=cached['bounds_mm']; shifts=[v*distance for v in actual_direction]
            swept=[pb[i]+(-abs(shifts[i]) if both_sides else min(0,shifts[i])) for i in range(3)]+[pb[i+3]+(abs(shifts[i]) if both_sides else max(0,shifts[i])) for i in range(3)]
            targets=[list(body.GetGabarit()[1:]) for body in target_bodies] if target_bodies else [body['bounds_mm'] for body in before['bodies']]
            if not any(bbox_overlap(swept,b) for b in targets):
                raise ValueError('Swept profile bounding box misses all target bodies; no mutation performed')
            precheck='swept_bbox_overlap_only'
        entity = part.NewEntity(26 if cut else 25)
        after=None; failures=[]
        try:
            definition = entity.GetDefinition()
            if not definition.SetSketch(sketch): raise RuntimeError('SetSketch failed')
            # SDK dtBoth=2 and etThroughAll=1, audited from constants3d.
            api_reverse = bool(reverse) != bool(cut)
            definition.directionType = 2 if both_sides else (1 if api_reverse else 0)
            # chooseType is ksChooseType (bodies vs components), NOT the body
            # selection mode. That mode lives in ksChooseBodies.ChooseBodiesType.
            definition.chooseType = 3  # ksChBodies: top-part bodies only
            selection=definition.ChooseBodies()
            selection.ChooseBodiesType=(2 if target_bodies else 3) if cut else (0 if result_mode=='new_body' else 1)
            if target_bodies:
                selected=selection.BodyCollection(); selected.Clear()
                for body in target_bodies:
                    if not selected.Add(body): raise RuntimeError('Could not select target body')
            for side in (True,False) if both_sides else (not api_reverse,):
                if not definition.SetSideParam(side,1 if through_all else 0,depth,0,False):
                    raise RuntimeError('SetSideParam failed')
            if name: entity.name = name
            if not entity.Create() or not entity.IsCreated(): raise RuntimeError('Native extrusion creation failed')
            if not d3.RebuildDocument(): raise RuntimeError('Native extrusion rebuild failed')
            after=self._model_metrics(); failures=check_contract(after,expected)
            delta=after['volume_mm3']-before['volume_mm3']
            threshold=max(1e-7,abs(before['volume_mm3'])*1e-9)
            if (cut and delta>=-threshold) or (not cut and delta<=threshold):
                failures.append({'check':'volume_decreased' if cut else 'volume_increased','delta_mm3':delta})
            feature=entity.GetFeature()
            if not feature.IsValid() or int(feature.objectError)!=0:
                failures.append({'check':'native_feature_valid','error':int(feature.objectError)})
            errors=self._native_feature_errors()
            if errors: failures.append({'check':'native_document_valid','features':errors})
            if failures: raise RuntimeError('Operation result failed geometric contract')
        except Exception as exc:
            cleanup=self._cleanup_created(entity,before)
            return {**error_info(exc,'extrusion3d'),'before':before,'rejected_result':after,
                    'failures':failures,'cleanup':cleanup,'direction':actual_direction,
                    'warnings':['No opposite-direction retry. Cleanup removes only the newly created feature.']}
        finally:
            self.registry.invalidate_topology(int(self.active().Reference))
        return {'success':True,"feature_id": self._remember3d(entity, "feature"), "name": entity.name,
                "operation": "cut" if cut else "extrude", "depth": depth,
                "reverse": reverse, "solid": True,'direction':actual_direction,
                'through_all':through_all,'both_sides':both_sides,
                'target_scope':('selected_top_part_bodies' if target_bodies else 'all_top_part_bodies') if cut else result_mode,
                'target_body_ids':target_body_ids,
                'intersection_precheck':precheck,
                'before':before,'after':after,'volume_delta_mm3':delta,'checks_passed':True}

    def model_info(self):
        d3 = self.doc3d()
        part = d3.GetPart(-1)
        collection = part.EntityCollection(0)
        features = []
        for i in range(collection.GetCount()):
            entity = collection.GetByIndex(i)
            typ = int(entity.type)
            # API5 collection also contains generated faces/edges; omit those.
            if typ in (5, 25, 26):
                features.append({"id": self._remember3d(entity, "sketch" if typ == 5 else "feature"),
                                 "name": entity.name, "type": typ,
                                 "created": bool(entity.IsCreated())})
        body = part.GetMainBody()
        summary = None
        if body is not None:
            bounds = body.GetGabarit()
            if not bounds[0]:
                raise RuntimeError("Не удалось получить габариты тела")
            mass = body.CalcMassInertiaProperties(1)
            summary = {"solid": bool(body.IsSolid()), "bounds_mm": list(bounds[1:]),
                       "volume_mm3": float(mass.v)}
        return {"document": self.describe(self.active()), "features": features,
                "main_body": summary, "scope": "sketches_and_extrusions_in_top_part"}

    def fit_view3d(self):
        d3 = self.doc3d()
        if not d3.RebuildDocument() or not d3.ZoomPrevNextOrAll(2):
            raise RuntimeError("Не удалось перестроить модель/подобрать масштаб")
        if hasattr(self,'registry'):
            self.registry.invalidate_topology(int(self.active().Reference))
        return {"rebuilt": True, "fit": True}
