"""API7 drawing sheets, associative model views, real dimensions and structural reading."""
from pathlib import Path
from contextlib import suppress

from cad3d import finite
from visualization import VIEWS


class DrawingMixin:
    def _drawing7(self):
        import win32com.client as com
        doc=self.active()
        if doc.DocumentType not in (1,2):
            raise ValueError('Active 2D drawing/fragment required')
        return com.CastTo(doc,'IKompasDocument2D')

    def _view7(self, view_id=None):
        import win32com.client as com
        self._drawing7()
        if view_id:
            return com.CastTo(self._entity_handle(view_id),'IView')
        return com.CastTo(self._drawing7().ViewsAndLayersManager.Views.ActiveView,'IView')

    def drawing_sheet(self,sheet=1,format=None,portrait=None,stamp=None):
        doc=self.active()
        if doc.DocumentType!=1 or not 1<=sheet<=doc.LayoutSheets.Count:
            raise ValueError('Drawing sheet number is 1-based')
        item=doc.LayoutSheets.Item(sheet-1)
        if format is not None and format not in ('A0','A1','A2','A3','A4','A5'):
            raise ValueError('format must be A0..A5')
        cells={int(key):str(value) for key,value in (stamp or {}).items()}
        for cell in cells:
            if not item.Stamp.IsCellPresent(cell):
                raise ValueError(f'Stamp cell unavailable: {cell}')
        if format is not None:
            if format not in ('A0','A1','A2','A3','A4','A5'):
                raise ValueError('format must be A0..A5')
            item.Format.Format=int(format[1:])
        if portrait is not None:
            item.Format.VerticalOrientation=portrait
        if (format is not None or portrait is not None) and not item.Update():
            raise RuntimeError('Sheet.Update failed')
        for cell,value in cells.items():
            item.Stamp.Text(cell).Str=value
        if stamp and not item.Stamp.Update():
            raise RuntimeError('Stamp.Update failed')
        return {'success':True,'sheet':sheet,'format':item.Format.Format,
                'width_mm':item.Format.FormatWidth,'height_mm':item.Format.FormatHeight,
                'portrait':bool(item.Format.VerticalOrientation)}

    def create_model_view(self,model_path,view='front',x=100,y=150,scale=1,name='',projection_name='',
                          x_axis=None,y_axis=None,origin=None):
        import win32com.client as com
        from geometry import frame, projection_matrix
        if (x_axis is None)!=(y_axis is None): raise ValueError('Supply both X/Y axes')
        if projection_name and x_axis is not None: raise ValueError('Choose named projection OR explicit axes')
        if origin is not None and x_axis is None: raise ValueError('origin requires X/Y axes')
        requested=frame(origin if origin is not None else [0,0,0],x_axis,y_axis) if x_axis is not None else None
        path=Path(model_path).expanduser().resolve(strict=True)
        if view not in VIEWS:
            raise ValueError('Unknown standard projection')
        x,y,scale=finite(x),finite(y),finite(scale,True)
        if path.suffix.lower() not in ('.m3d','.a3d'):
            raise ValueError('Source must be a saved .m3d/.a3d')
        drawing=self._drawing7()
        app=self.connect()
        model=next((app.Documents.Item(i) for i in range(app.Documents.Count)
                    if app.Documents.Item(i).PathName and Path(app.Documents.Item(i).PathName).resolve()==path),None)
        opened=model is None
        import pythoncom
        stage='open_source_model'
        try:
            if opened:
                model=app.Documents.Open(str(path),False,True)
            if model is None:
                raise RuntimeError('Could not open model for projection lookup')
            if model.Changed:
                raise ValueError('Source model has unsaved changes; save a separate copy first')
            model.Active=True
            stage='activate_source_model'
            pythoncom.PumpWaitingMessages()
            d3=self.kompas.ActiveDocument3D
            if d3 is None or int(d3.reference)!=int(model.Reference):
                raise RuntimeError('Model API5 not synchronized')
            collection=d3.GetViewProjectionCollection()
            stage='resolve_projection'
            projection=(collection.GetByName(projection_name) if projection_name else
                        next((collection.GetByIndex(i) for i in range(collection.GetCount())
                              if int(collection.GetByIndex(i).GetViewProjectonType())==VIEWS[view]),None))
            if projection is None:
                raise ValueError('Requested projection is not defined in model')
            projection_name=projection.name
            stage='read_source_bounds'
            # Drawing layout needs bounds, not inertia/material evaluation. Read
            # only native body boxes; avoid unrelated kernel mass computations.
            bodies=d3.GetPart(-1).BodyCollection(); boxes=[]
            for i in range(bodies.GetCount()):
                bounds=bodies.GetByIndex(i).GetGabarit()
                if not bounds[0]: raise RuntimeError('Cannot read source body bounds')
                boxes.append(list(bounds[1:]))
            model_bounds=([min(b[i] for b in boxes) for i in range(3)]+
                          [max(b[i] for b in boxes) for i in range(3,6)]) if boxes else None
        except Exception as exc:
            exc.cad_stage=stage
            # Restore activation/close only our lookup document, preserving the
            # primary native failure if the application has already died.
            with suppress(Exception): drawing.Active=True
            if opened and model is not None:
                with suppress(Exception): model.Close(0)
            raise
        finally:
            if stage=='read_source_bounds' and 'model_bounds' in locals():
                drawing.Active=True
                pythoncom.PumpWaitingMessages()
                if opened and model is not None: model.Close(0)
        obj=drawing.ViewsAndLayersManager.Views.Add(3) # vt_Standart
        association=com.CastTo(obj,'IAssociationView')
        stage='configure_associative_view'
        try:
            association.SourceFileName=str(path)
            association.ProjectionName=projection_name
            if requested:
                association.ProjectionMatrix=com.VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,projection_matrix(requested))
            association.X=x; association.Y=y; association.Scale=scale
            if name:
                association.Name=name
            stage='update_associative_view'
            if not association.Update():
                raise RuntimeError('Associative view.Update failed')
            stage='rebuild_associative_view'
            association.Rebuild()
            key=self.registry.put(association,self._scope(),'drawing_view')
            # Never certify orientation merely because property assignment succeeded.
            if requested:
                stage='verify_projection_axes'
                from geometry import to_world
                actual=self.project_model_points(key,[to_world(requested,p) for p in ([0,0],[1,0],[0,1])])['points']
                import math
                if any(not math.isclose(a,b,abs_tol=1e-6) for p,q in zip(actual,([0,0],[1,0],[0,1])) for a,b in zip(p,q)):
                    raise RuntimeError(f'ProjectionMatrix readback does not match requested axes: {actual}')
            import itertools
            projected_bounds=None
            if model_bounds:
                stage='project_model_bounds'
                corners=list(itertools.product(*[(model_bounds[i],model_bounds[i+3]) for i in range(3)]))
                points=self.project_model_points(key,corners)['points']
                projected_bounds=[min(p[i] for p in points) for i in range(2)]+[max(p[i] for p in points) for i in range(2)]
        except Exception as exc:
            exc.cad_stage=stage
            with suppress(Exception):
                obj.Delete()
            if 'key' in locals(): self.registry.release([key])
            raise
        return {'success':True,'view_id':key,
                'view':view,'name':association.Name,'source':str(path),'scale':scale,
                'position_mm':[x,y],'object_count':int(association.ObjectCount),
                'projection_name':projection_name,'projection_matrix':list(association.ProjectionMatrix),
                'projected_model_bbox_mm':projected_bounds,
                'warnings':['Projected model bounding box is conservative, not exact visible geometry extents']}

    def project_model_points(self,view_id,points,to_sheet=False):
        import win32com.client as com
        import math
        from geometry import vector
        if len(points)>1000: raise ValueError('At most 1000 points')
        points=[vector(p) for p in points]
        view=self._view7(view_id); association=com.CastTo(view,'IAssociationView')
        output=[]; angle=math.radians(float(view.Angle)); c,s=math.cos(angle),math.sin(angle)
        for p in points:
            actual=association.GetProjectionPoint(*p)
            if not actual[0]: raise RuntimeError('GetProjectionPoint failed')
            u,v=map(float,actual[1:])
            if to_sheet: u,v=view.X+view.Scale*(c*u-s*v),view.Y+view.Scale*(s*u+c*v)
            output.append([u,v])
        return {'success':True,'view_id':view_id,'points':output,
                'coordinate_system':'sheet' if to_sheet else 'view-local',
                'view_transform':{'position_mm':[view.X,view.Y],'scale':view.Scale,'angle_degrees':view.Angle}}

    def add_model_dimension(self,view_id,points,position,orientation='horizontal',prefix='',suffix=''):
        from geometry import vector
        import math
        if len(points)!=2: raise ValueError('Two model XYZ points required')
        points=[vector(p) for p in points]; position=vector(position)
        projected=self.project_model_points(view_id,points+[position])['points']
        result=self.add_dimension('linear',view_id,projected[:2],projected[2],orientation,prefix=prefix,suffix=suffix)
        a,b=projected[:2]
        nominal=abs(b[0]-a[0]) if orientation=='horizontal' else abs(b[1]-a[1]) if orientation=='vertical' else math.dist(a,b)
        if not math.isclose(result['nominal_value'],nominal,abs_tol=1e-6):
            obj=self._entity_handle(result['dimension_id'])
            deleted=bool(obj.Delete()); self.registry.release([result['dimension_id']])
            return {'success':False,'message':'Dimension nominal differs from projected points',
                    'expected':nominal,'actual':result['nominal_value'],'cleanup':{'success':deleted}}
        return {**result,'model_points':points,'view_points':projected[:2],'nominal_checked':True}

    def set_drawing_view(self,view_id,x=None,y=None,scale=None,active=True):
        x=finite(x) if x is not None else None
        y=finite(y) if y is not None else None
        scale=finite(scale,True) if scale is not None else None
        view=self._view7(view_id)
        if x is not None: view.X=finite(x)
        if y is not None: view.Y=finite(y)
        if scale is not None: view.Scale=finite(scale,True)
        if active: view.Current=True
        if not view.Update():
            raise RuntimeError('View update failed')
        return {'success':True,'view_id':view_id,'position_mm':[view.X,view.Y],'scale':view.Scale}

    def add_dimension(self,kind='linear',view_id=None,points=(),position=(),orientation='horizontal',
                       center=(),radius=None,angle=45,prefix='',suffix=''):
        import win32com.client as com
        if kind=='linear':
            if len(points)!=2 or any(len(p)!=2 for p in points) or len(position)!=2:
                raise ValueError('Linear dimension needs points=[[x1,y1],[x2,y2]], position=[x,y]')
            if orientation not in ('horizontal','vertical','parallel'):
                raise ValueError('orientation: horizontal/vertical/parallel')
            points=[[finite(v) for v in p] for p in points]
            position=[finite(v) for v in position]
            if points[0]==points[1] or (orientation=='horizontal' and points[0][0]==points[1][0]) or (orientation=='vertical' and points[0][1]==points[1][1]):
                raise ValueError('Dimension must have a nonzero projected length')
        elif kind in ('diameter','radius'):
            if len(center)!=2:
                raise ValueError('Diameter/radius dimension needs center=[x,y], radius>0')
            center=[finite(v) for v in center]; radius=finite(radius,True); angle=finite(angle)
        else:
            raise ValueError('kind: linear/diameter/radius')
        view=self._view7(view_id)
        container=com.CastTo(view,'ISymbols2DContainer')
        if kind=='linear':
            obj=container.LineDimensions.Add()
            com.CastTo(obj,'IDimensionParams').InitDefaultValues()
            obj.X1,obj.Y1=map(finite,points[0]); obj.X2,obj.Y2=map(finite,points[1])
            obj.X3,obj.Y3=map(finite,position)
            obj.Orientation={'horizontal':1,'vertical':2,'parallel':0}[orientation]
        elif kind in ('diameter','radius'):
            if len(center)!=2:
                raise ValueError('Diameter/radius dimension needs center=[x,y], radius>0')
            obj=(container.DiametralDimensions if kind=='diameter' else container.RadialDimensions).Add()
            com.CastTo(obj,'IDimensionParams').InitDefaultValues()
            obj.Xc,obj.Yc=map(finite,center); obj.Radius=finite(radius,True); obj.Angle=finite(angle)
        else:
            raise ValueError('kind: linear/diameter/radius; angular dimensions via generic API')
        text=com.CastTo(obj,'IDimensionText'); text.AutoNominalValue=True; text.Style=3
        text.Prefix.Str=prefix; text.Suffix.Str=suffix
        if not obj.Update():
            raise RuntimeError('Dimension.Update failed')
        return {'success':True,'dimension_id':self.registry.put(obj,self._scope(),'drawing_object'),
                'kind':kind,'nominal_value':float(text.NominalValue),'prefix':prefix,'suffix':suffix,
                'warnings':['Dimension uses supplied view-local coordinates, not automatic model edge references']}

    def get_document_structure(self,include_objects=True,limit=500):
        if not 1<=limit<=10000:
            raise ValueError('limit must be 1..10000')
        import win32com.client as com
        doc=self.active()
        if doc.DocumentType in (4,5,7):
            return self.get_model_tree(limit=limit)
        drawing=self._drawing7()
        sheets=[]
        for i in range(doc.LayoutSheets.Count if doc.DocumentType==1 else 0):
            s=doc.LayoutSheets.Item(i)
            sheets.append({'sheet':i+1,'width_mm':s.Format.FormatWidth,'height_mm':s.Format.FormatHeight,
                           'format':s.Format.Format,'portrait':bool(s.Format.VerticalOrientation)})
        views=[]; collected=0
        collections=(('geometry','IDrawingContainer',('LineSegments','Circles','Arcs','Points','DrawingTexts','Hatches','PolyLines2D','Rectangles','Nurbses')),
                     ('annotation','ISymbols2DContainer',('LineDimensions','DiametralDimensions','RadialDimensions','AngleDimensions','Leaders','CutLines','ViewPointers','DrawingTables')))
        for i in range(drawing.ViewsAndLayersManager.Views.Count):
            view=com.CastTo(drawing.ViewsAndLayersManager.Views.Item(i),'IView')
            row={'view_id':self.registry.put(view,self._scope(),'drawing_view'),'number':view.Number,
                 'name':view.Name,'position_mm':[view.X,view.Y],'scale':view.Scale,'angle_degrees':view.Angle,
                 'view_type':view.ViewType,'object_count':int(view.ObjectCount),'objects':[]}
            if include_objects:
                for category,interface,names in collections:
                    container=com.CastTo(view,interface)
                    for name in names:
                        try:
                            collection=getattr(container,name)
                            for j in range(collection.Count):
                                if collected>=limit: break
                                obj=collection.Item(j)
                                interface_name={'PolyLines2D':'IPolyLine2D','Nurbses':'INurbs'}.get(name,'I'+name[:-1])
                                obj=com.CastTo(obj,interface_name)
                                properties={}
                                for prop in ('X','Y','X1','Y1','X2','Y2','X3','Y3','Xc','Yc','Radius','Angle','Style','Name','Str'):
                                    try:
                                        val=getattr(obj,prop)
                                        if isinstance(val,(str,int,float,bool)):
                                            properties[prop]=val
                                    except AttributeError:
                                        pass
                                if 'Dimensions' in name:
                                    text=com.CastTo(obj,'IDimensionText')
                                    properties.update({'NominalValue':float(text.NominalValue),'Prefix':text.Prefix.Str,'Suffix':text.Suffix.Str})
                                row['objects'].append({'object_id':self.registry.put(obj,self._scope(),'drawing_object'),
                                                       'category':category,'collection':name,'properties':properties})
                                collected+=1
                        except Exception as exc:
                            row.setdefault('warnings',[]).append({'collection':name,'message':str(exc)})
            views.append(row)
        return {'success':True,'document':self.describe(doc),'sheets':sheets,'views':views,
                'objects_returned':collected,'truncated':collected>=limit,
                'units':{'length':'mm','angle':'degree'},'coordinate_system':'view-local; transform with position, scale and angle'}

    def find_drawing_objects(self,collection='',text='',limit=100):
        if not 1<=limit<=2000:
            raise ValueError('limit must be 1..2000')
        structure=self.get_document_structure(True,2000)
        rows=[]
        for view in structure['views']:
            for obj in view['objects']:
                if collection and obj['collection']!=collection: continue
                if text and text.lower() not in str(obj['properties']).lower(): continue
                rows.append({**obj,'view_id':view['view_id']})
        return {'success':True,'objects':rows[:limit],'total':len(rows),'truncated':len(rows)>limit or structure['truncated']}
