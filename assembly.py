"""API5 component insertion, API7 assembly structure and placement."""
from pathlib import Path
import math
from cad3d import finite


class AssemblyMixin:
    def _update_component_origin(self,component,position):
        values=[finite(v) for v in position]
        if not component.Placement.SetOrigin(*values):
            raise RuntimeError('Placement.SetOrigin failed')
        native=bool(component.UpdatePlacement(True))
        actual=component.Placement.GetOrigin()
        if not actual[0] or not all(math.isclose(a,b,abs_tol=1e-7) for a,b in zip(actual[1:],values)):
            raise RuntimeError('Component origin readback differs from requested placement')
        return [] if native else ['UpdatePlacement returned false; origin readback matches. Verify assembly image and rebuild.']

    def _assembly7(self):
        import win32com.client as com
        doc=self.active()
        if doc.DocumentType not in (5,7):
            raise ValueError('Active assembly required')
        return com.CastTo(doc,'IKompasDocument3D')

    def get_assembly_tree(self,max_depth=10,limit=1000):
        if not 0<=max_depth<=50 or not 1<=limit<=10000:
            raise ValueError('max_depth must be 0..50, limit 1..10000')
        import win32com.client as com
        top=self._assembly7().TopPart
        count=0
        def node(part,depth):
            nonlocal count
            count+=1
            row={'object_id':self.registry.put(part,self._scope(),'component'),'name':part.Name,
                 'file':part.FileName,'marking':part.Marking,'fixed':bool(part.Fixed),
                 'hidden':bool(part.Hidden),'children':[]}
            placement=part.Placement
            row['origin_mm']=self._encode(placement.GetOrigin())
            row['axes']={'x':self._encode(placement.GetVector(71)),
                         'y':self._encode(placement.GetVector(72)),
                         'z':self._encode(placement.GetVector(73))}
            if depth<max_depth:
                for i in range(part.Parts.Count):
                    if count>=limit: break
                    row['children'].append(node(com.CastTo(part.Parts.Item(i),'IPart7'),depth+1))
            return row
        return {'success':True,'tree':node(top,0),'nodes_returned':count,'truncated':count>=limit,
                'warnings':['Component placements are relative to their parent assembly']}

    def add_component(self,path,position=(0,0,0),external=True):
        import pythoncom
        import win32com.client as com
        assembly=self._assembly7()
        target=Path(path).expanduser().resolve(strict=True)
        if len(position)!=3:
            raise ValueError('position=[x,y,z] in mm')
        position=[finite(v) for v in position]
        if target.suffix.lower() not in ('.m3d','.a3d'):
            raise ValueError('Component source must be .m3d/.a3d')
        d3=self.kompas.ActiveDocument3D
        part=d3.GetPart(-1)
        before=assembly.TopPart.Parts.Count
        if not d3.SetPartFromFile(str(target),part,bool(external)):
            raise RuntimeError('SetPartFromFile failed')
        pythoncom.PumpWaitingMessages()
        components=assembly.TopPart.Parts
        if components.Count<=before:
            raise RuntimeError('Component count did not increase')
        component=com.CastTo(components.Item(components.Count-1),'IPart7')
        component.Fixed=False
        warnings=self._update_component_origin(component,position)
        self.registry.invalidate_topology(self._scope())
        return {'success':True,'component_id':self.registry.put(component,self._scope(),'component'),
                'name':component.Name,'source':str(target),'position_mm':list(position),'warnings':warnings}

    def set_component_placement(self,component_id,position,x_axis=None,y_axis=None,fixed=None):
        component=self._entity_handle(component_id)
        if len(position)!=3:
            raise ValueError('position=[x,y,z]')
        if x_axis is not None or y_axis is not None:
            if x_axis is None or y_axis is None or len(x_axis)!=3 or len(y_axis)!=3:
                raise ValueError('Both x_axis/y_axis must contain three coordinates')
            x=[finite(v) for v in x_axis]; y=[finite(v) for v in y_axis]
            nx=math.sqrt(sum(v*v for v in x)); ny=math.sqrt(sum(v*v for v in y))
            if nx<1e-12 or ny<1e-12 or abs(sum(a*b for a,b in zip(x,y))/nx/ny)>1e-6:
                raise ValueError('Component axes must be nonzero and orthogonal')
            x=[v/nx for v in x]; y=[v/ny for v in y]
            z=[x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
        values=[finite(v) for v in position]
        was_fixed=bool(component.Fixed)
        component.Fixed=False
        try:
            if x_axis is not None:
                import pythoncom
                from win32com.client import VARIANT
                # SetVector rotates the whole basis at each call. Initialize all
                # axes together with the official SAFEARRAY(double) matrix API.
                matrix=(*x,0.,*y,0.,*z,0.,*values,1.)
                if not component.Placement.InitByMatrix3D(VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,matrix)):
                    raise RuntimeError('Placement.InitByMatrix3D failed')
            warnings=self._update_component_origin(component,values)
            if x_axis is not None:
                for axis,expected in ((71,x),(72,y),(73,z)):
                    actual=component.Placement.GetVector(axis)
                    if not actual[0] or not all(math.isclose(a,b,abs_tol=1e-7) for a,b in zip(actual[1:],expected)):
                        raise RuntimeError('Component axis readback differs from requested orientation')
        finally:
            component.Fixed=was_fixed if fixed is None else bool(fixed)
        self.registry.invalidate_topology(self._scope())
        return {'success':True,'component_id':component_id,'position_mm':list(position),'warnings':warnings}
