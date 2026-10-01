"""Native converters, projections and bounded raster feedback."""
from io import BytesIO
from contextlib import contextmanager
from pathlib import Path
import uuid

from cad3d import finite
from sdk_catalog import sdk_directory

VIEWS = {'front':1,'back':2,'top':3,'bottom':4,'left':5,'right':6,'isometric':7,'dimetric':8}


def checked_output(path, overwrite=False):
    path = Path(path).expanduser().resolve()
    if path.exists() and not overwrite:
        raise FileExistsError(f'Output exists: {path}; overwrite=true required')
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def file_result(path, **kwargs):
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f'Native exporter did not create a nonempty file: {path}')
    return {'success':True,'path':str(path),'bytes':path.stat().st_size,**kwargs}


@contextmanager
def staged_output(path,overwrite=False):
    """Export to a private sibling; a failed converter cannot masquerade as old output."""
    target=checked_output(path,overwrite)
    stage=target.with_name(target.stem+'.mcp-'+uuid.uuid4().hex+target.suffix)
    try:
        yield stage,target
        file_result(stage)
        if target.exists() and not overwrite:
            raise FileExistsError(f'Output appeared during export: {target}')
        stage.replace(target)
    finally:
        stage.unlink(missing_ok=True)


class VisualizationMixin:
    def create_model_projection(self,name,origin,x_axis,y_axis):
        from geometry import frame, projection_matrix
        import pythoncom
        from win32com.client import VARIANT
        f=frame(origin,x_axis,y_axis)
        if not name.strip() or name.startswith('MCP camera '): raise ValueError('Use a nonempty permanent name, not reserved MCP camera prefix')
        d3,_=self._part3d(); collection=d3.GetViewProjectionCollection()
        if collection.GetByName(name) is not None: raise ValueError('Projection name already exists; existing projections are preserved')
        p=collection.NewViewProjection(); p.name=name
        matrix=projection_matrix(f)
        if not p.SetMatrix3D(VARIANT(pythoncom.VT_ARRAY|pythoncom.VT_R8,matrix)):
            raise RuntimeError('Projection.SetMatrix3D failed')
        actual=p.GetPlacement().GetMatrix3D()
        import math
        if not actual[0] or len(actual[1])!=16 or any(not math.isclose(a,b,abs_tol=1e-7) for a,b in zip(actual[1],matrix)):
            raise RuntimeError('Permanent projection matrix readback differs from request')
        if not collection.Add(p): raise RuntimeError('Could not attach permanent projection')
        return {'success':True,'projection_name':p.name,'frame':f,'matrix':matrix,'persistent':True,
                'warnings':['Save model explicitly before associative drawing lookup; no source file was saved']}

    def set_standard_view(self, view='isometric'):
        if view not in VIEWS:
            raise ValueError('view: front/back/top/bottom/left/right/isometric/dimetric')
        d3,_ = self._part3d()
        projections = d3.GetViewProjectionCollection()
        for i in range(projections.GetCount()):
            projection=projections.GetByIndex(i)
            if int(projection.GetViewProjectonType()) == VIEWS[view]:
                if not projection.IsCurrent() and not projection.SetCurrent() and not projection.IsCurrent():
                    raise RuntimeError('SetCurrent projection failed')
                d3.ZoomPrevNextOrAll(2)
                return {'success':True,'view':view,'projection_name':projection.name}
        raise ValueError('Standard projection not present in document; inspect projection collection via generic API')

    def set_camera(self, origin, x_axis, y_axis, scale=None):
        import math
        if any(len(v)!=3 for v in (origin,x_axis,y_axis)):
            raise ValueError('origin/x_axis/y_axis must contain 3 coordinates')
        origin=[finite(v) for v in origin]
        x=[finite(v) for v in x_axis]; y=[finite(v) for v in y_axis]
        nx=math.sqrt(sum(v*v for v in x)); ny=math.sqrt(sum(v*v for v in y))
        if nx<1e-12 or ny<1e-12 or abs(sum(a*b for a,b in zip(x,y))/nx/ny)>1e-6:
            raise ValueError('Camera axes must be nonzero and orthogonal')
        x=[v/nx for v in x]; y=[v/ny for v in y]
        scale=finite(scale,True) if scale is not None else None
        d3,_=self._part3d(); collection=d3.GetViewProjectionCollection()
        # Built-in projections expose a READ-ONLY placement. Initialize a detached
        # user projection, then attach it; never rewrite a standard orientation.
        projection=collection.NewViewProjection()
        if projection is None:
            raise RuntimeError('Could not allocate camera projection')
        projection.name='MCP camera '+uuid.uuid4().hex[:12]
        placement=projection.GetPlacement()
        if not placement.SetOrigin(*origin) or not placement.SetAxes(*x,*y):
            raise RuntimeError('Could not initialize camera placement')
        if not projection.SetPlacement(placement):
            raise RuntimeError('Could not set camera placement')
        if scale is not None:
            projection.scale=finite(scale,True)
        if not collection.Add(projection):
            raise RuntimeError('Could not attach camera projection')
        if not projection.SetCurrent() and not projection.IsCurrent():
            collection.DetachByBody(projection)
            raise RuntimeError('Could not activate camera projection')
        names=getattr(self,'_camera_names',{})
        previous=names.get(self._scope())
        if previous:
            old=collection.GetByName(previous)
            if old is not None:
                collection.DetachByBody(old)
        names[self._scope()]=projection.name
        self._camera_names=names
        return {'success':True,'origin_mm':origin,'x_axis':x,'y_axis':y,'scale':projection.scale,
                'projection_name':projection.name,'warnings':['Uses a dedicated user projection; standard orientations are preserved']}

    def fit_view(self):
        doc=self.active()
        if doc.DocumentType in (4,5,7):
            d3,_=self._part3d()
            ok=d3.ZoomPrevNextOrAll(2)
        else:
            ok=self.doc2d().ksZoomPrevNextOrAll(2)
        return {'success':bool(ok),'document_reference':int(doc.Reference)}

    def capture_viewport(self, path=None, overwrite=False):
        import win32gui
        from capture import capture_window
        hwnd=int(self.connect().MainWindowHandle)
        views=[]
        def collect(child,_):
            if (win32gui.GetClassName(child)=='View' or win32gui.GetWindowText(child)=='View') and win32gui.IsWindowVisible(child):
                views.append(child)
        win32gui.EnumChildWindows(hwnd,collect,None)
        target=max(views,key=lambda h: (lambda r:(r[2]-r[0])*(r[3]-r[1]))(win32gui.GetWindowRect(h))) if views else hwnd
        try:
            data=capture_window(target)
        except RuntimeError:
            if target==hwnd:
                raise
            # Some renderer child windows do not support PrintWindow; render the
            # parent then crop the child's rectangle. Never read desktop pixels.
            from PIL import Image
            raw=capture_window(hwnd,max_size=None)
            main_rect=win32gui.GetWindowRect(hwnd); child_rect=win32gui.GetWindowRect(target)
            box=(child_rect[0]-main_rect[0],child_rect[1]-main_rect[1],
                 child_rect[2]-main_rect[0],child_rect[3]-main_rect[1])
            with Image.open(BytesIO(raw)) as image:
                viewport=image.crop(box); out=BytesIO(); viewport.save(out,format='PNG')
                data=out.getvalue()
        if path:
            output=checked_output(path,overwrite); output.write_bytes(data)
            return file_result(output,method='PrintWindow',viewport_only=bool(views))
        return data

    def capture_views(self, views=('isometric','front','top','right'), directory=None):
        if not views or len(views)>8 or len(set(views))!=len(views) or any(v not in VIEWS for v in views):
            raise ValueError('Use 1..8 unique standard view names')
        directory=Path(directory).expanduser().resolve() if directory else Path(__file__).parent/'artifacts'/('views-'+uuid.uuid4().hex)
        for view in views:
            if (directory/(view+'.png')).exists():
                raise FileExistsError(f'Output exists: {directory/(view+".png")}')
        directory.mkdir(parents=True,exist_ok=True)
        files=[]
        for view in views:
            self.set_standard_view(view)
            files.append(self.capture_viewport(str(directory/(view+'.png'))))
        return {'success':True,'files':files,'warnings':['Camera remains at the last requested view; PrintWindow size depends on viewport dimensions']}

    def export_model(self,path,format='step',overwrite=False):
        if format not in ('step','stl','iges','parasolid'):
            raise ValueError('format: step/stl/iges/parasolid')
        suffixes={'step':('.step','.stp'),'stl':('.stl',),'iges':('.igs','.iges'),'parasolid':('.x_t','.x_b')}
        if Path(path).suffix.lower() not in suffixes[format]:
            raise ValueError(f'Expected extension: {suffixes[format]}')
        d3,_=self._part3d(); target=checked_output(path,overwrite)
        # Resolve from official enum catalog rather than assuming numeric values.
        self.sdk.load()
        enum={'step':'format_STEP','stl':'format_STL','iges':'format_IGES','parasolid':'format_XT'}[format]
        if enum not in self.sdk.constants:
            raise ValueError(f'Installed SDK has no {enum}; inspect api_constants')
        par=d3.AdditionFormatParam()
        par.Init(); par.format=self.sdk.constants[enum]
        par.formatBinary=format=='stl' or target.suffix.lower()=='.x_b'
        if format=='step':
            par.stepType=self.sdk.constants['format_STEP_AP214']
        with staged_output(target,overwrite) as (stage,target):
            ok=d3.SaveAsToAdditionFormat(str(stage),par)
        return file_result(target,format=format,api_return=self._encode(ok))

    def export_drawing_image(self,path,dpi=300,sheet=1,overwrite=False):
        if not 72<=dpi<=600:
            raise ValueError('dpi must be 72..600')
        doc=self.active()
        if doc.DocumentType not in (1,2):
            raise ValueError('Active drawing/fragment required')
        sheet_count=doc.LayoutSheets.Count if doc.DocumentType==1 else 1
        if not 1<=sheet<=max(1,sheet_count):
            raise ValueError('sheet is 1-based')
        target=checked_output(path,overwrite)
        if target.suffix.lower() not in ('.png','.jpg','.jpeg'):
            raise ValueError('Use .png/.jpg/.jpeg')
        par=self.doc2d().RasterFormatParam()
        par.Init(); par.format=3 if target.suffix.lower()=='.png' else 2
        par.colorBPP=24; par.extResolution=dpi; par.extScale=1
        par.pages=str(sheet); par.rangeIndex=1; par.multiPageOutput=False; par.saveWorkArea=doc.DocumentType==2
        with staged_output(target,overwrite) as (stage,target):
            self.doc2d().SaveAsToRasterFormat(str(stage),par)
        return file_result(target,dpi=dpi,sheet=sheet,scale=1,method='native raster export')

    def export_drawing_pdf(self,path,overwrite=False):
        if Path(path).suffix.lower()!='.pdf':
            raise ValueError('Use .pdf extension')
        doc=self.active()
        if doc.DocumentType!=1 or not doc.PathName or doc.Changed:
            raise ValueError('PDF converter needs a SAVED drawing with no unsaved changes; save_document to a new path first')
        target=checked_output(path,overwrite)
        converter=self.connect().Converter(str(sdk_directory()/'Pdf2d.dll'))
        if converter is None:
            raise RuntimeError('Native Pdf2d converter unavailable')
        with staged_output(target,overwrite) as (stage,target):
            result=converter.Convert(doc.PathName,str(stage),0,False)
            file_result(stage)
            with stage.open('rb') as stream:
                if stream.read(5)!=b'%PDF-':
                    raise RuntimeError('Converter result is not a PDF')
        return file_result(target,api_return=self._encode(result),method='native Pdf2d',warnings=['Check PDF media box and print scale before manufacture'])

    def capture_drawing_tiles(self,directory=None,sheet=1,rows=2,columns=3,dpi=300):
        if not 1<=rows<=8 or not 1<=columns<=8:
            raise ValueError('rows/columns must be 1..8')
        from PIL import Image
        directory=Path(directory).expanduser().resolve() if directory else Path(__file__).parent/'artifacts'/('tiles-'+uuid.uuid4().hex)
        directory.mkdir(parents=True,exist_ok=True)
        whole=directory/'sheet.png'
        for r in range(rows):
            for c in range(columns):
                if (directory/f'tile-{r+1}-{c+1}.png').exists():
                    raise FileExistsError('Tile output already exists; choose a new directory')
        self.export_drawing_image(str(whole),dpi,sheet)
        files=[]
        with Image.open(whole) as image:
            width,height=image.size
            for r in range(rows):
                for c in range(columns):
                    box=(c*width//columns,r*height//rows,(c+1)*width//columns,(r+1)*height//rows)
                    target=checked_output(str(directory/f'tile-{r+1}-{c+1}.png'))
                    image.crop(box).save(target)
                    files.append(file_result(target,row=r+1,column=c+1,pixel_bounds=list(box)))
        return {'success':True,'sheet':sheet,'dpi':dpi,'whole':str(whole),'files':files}
