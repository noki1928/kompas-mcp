"""COM access. All objects stay in a single dedicated STA thread."""
import contextlib
import io
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock

from cad3d import Cad3DMixin
from api_adapter import ApiMixin
from registry import ObjectRegistry
from diagnostics import AuditLog, error_info
from documents import DocumentMixin
from sdk_catalog import SdkCatalog
from modeling import ModelingMixin
from visualization import VisualizationMixin, staged_output
from drawing import DrawingMixin
from assembly import AssemblyMixin
from safe_modeling import SafeModelingMixin


def number(value: float, positive: bool = False) -> float:
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError("Expected a finite number" + (" > 0" if positive else ""))
    return value


def reference(value) -> int:
    if not value or int(value) <= 0:
        raise RuntimeError("КОМПАС не создал объект (reference=0). Проверьте активный документ.")
    return int(value)


def output_path(path: str, overwrite: bool = False) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists() and not overwrite:
        raise FileExistsError(f"Файл уже существует: {target}. Укажите overwrite=true.")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


class ConnectionLostError(RuntimeError):
    """A native session died; never replay a mutation in a new session."""
    def __init__(self,exc):
        super().__init__('KOMPAS connection lost. No operation retried; call status, reopen saved work and reacquire handles.')
        self.hresult=getattr(exc,'hresult',None)
        self.excepinfo=getattr(exc,'excepinfo',None)


class Kompas(SafeModelingMixin, Cad3DMixin, ApiMixin, DocumentMixin, ModelingMixin, VisualizationMixin, DrawingMixin, AssemblyMixin):
    def __init__(self):
        self.app7 = None
        self.kompas = None
        self.registry = ObjectRegistry()
        self._model_stamps = {}
        self.sdk = SdkCatalog()

    def connect(self):
        import win32com.client as com
        if self.app7 is not None:
            try:
                self.app7.Documents.Count
            except Exception as exc:
                if getattr(exc,'hresult',None) not in (-2147023174,-2147023170,-2147417848,-2147220995):
                    raise
                self.app7=None; self.kompas=None
                self.registry=ObjectRegistry()
                self._model_stamps.clear()
                self._editing_sketch=None
                self._profile_bounds={}
                raise ConnectionLostError(exc) from exc
        if self.app7 is None:
            # Obtain API7 from API5, keeping both interfaces in the same instance.
            try:
                self.kompas = com.GetActiveObject("KOMPAS.Application.5")
            except Exception:
                self.kompas = com.Dispatch("KOMPAS.Application.5")
            self.app7 = com.gencache.EnsureDispatch(self.kompas.ksGetApplication7)
            self.app7.Visible = True
        return self.app7

    def active(self):
        doc = self.connect().ActiveDocument
        if doc is None:
            raise RuntimeError("Нет активного документа. Вызовите create_document.")
        return doc

    def doc2d(self):
        doc = self.active()
        if doc.DocumentType not in (1, 2):
            raise RuntimeError("Нужен активный чертёж или фрагмент, не 3D-документ.")
        d = self.kompas.ActiveDocument2D
        if d is None or int(d.reference) != int(doc.Reference):
            raise RuntimeError("API5/API7 ссылаются на разные документы.")
        return d

    @staticmethod
    def describe(doc):
        return {"reference": int(doc.Reference), "type": int(doc.DocumentType),
                "name": doc.Name, "path": doc.PathName, "changed": bool(doc.Changed)}

    def status(self):
        warnings=[]
        try:
            app = self.connect()
        except ConnectionLostError as exc:
            warnings.append(str(exc))
            app=self.connect()
        docs = [self.describe(app.Documents.Item(i)) for i in range(app.Documents.Count)]
        return {"connected": True, "documents": docs,
                "active": self.describe(app.ActiveDocument) if app.ActiveDocument else None,
                 "scripts_enabled": os.getenv("KOMPAS_ALLOW_SCRIPTS") == "1",'warnings':warnings}

    def create_document(self, kind):
        types = {"drawing": 1, "fragment": 2, "specification": 3, "part": 4,
                 "assembly": 5, "text": 6, "technology_assembly": 7}
        if kind not in types:
            raise ValueError('kind must be '+', '.join(types))
        doc = self.connect().Documents.Add(types[kind], True)
        if doc is None:
            raise RuntimeError("Не удалось создать документ")
        return self.describe(doc)

    def open_document(self, path):
        path = Path(path).expanduser().resolve(strict=True)
        doc = self.connect().Documents.Open(str(path), True, False)
        if doc is None:
            raise RuntimeError("Не удалось открыть документ")
        return self.describe(doc)

    def save_document(self, path, overwrite=False):
        doc = self.active()
        expected={1:'.cdw',2:'.frw',3:'.spw',4:'.m3d',5:'.a3d',6:'.kdw',7:'.a3d'}[int(doc.DocumentType)]
        if Path(path).suffix.lower()!=expected:
            raise ValueError(f'Active document needs {expected} extension')
        target = output_path(path, overwrite)
        doc.SaveAs(str(target))
        if not target.is_file() or target.stat().st_size == 0 or doc.Changed or Path(doc.PathName).resolve()!=target:
            raise RuntimeError("КОМПАС не сохранил файл")
        return {"path": str(target), "bytes": target.stat().st_size}

    def line(self, x1, y1, x2, y2, style=1):
        coords = [number(v) for v in (x1, y1, x2, y2)]
        if coords[:2] == coords[2:]:
            raise ValueError("Отрезок не может иметь нулевую длину")
        return {"reference": reference(self.doc2d().ksLineSeg(*coords, style))}

    def circle(self, x, y, radius, style=1):
        return {"reference": reference(self.doc2d().ksCircle(
            number(x), number(y), number(radius, positive=True), style))}

    def arc(self, x, y, radius, start_angle, end_angle, direction=1, style=1):
        return {"reference": reference(self.doc2d().ksArcByAngle(
            number(x), number(y), number(radius, positive=True),
            number(start_angle), number(end_angle), direction, style))}

    def polyline(self, points, closed=False, style=1):
        if len(points) < 2 or any(len(p) != 2 for p in points):
            raise ValueError("Нужно минимум две точки [x, y]")
        pts = [[number(v) for v in p] for p in points]
        pairs = list(zip(pts, pts[1:] + ([pts[0]] if closed else [])))
        if any(a == b for a, b in pairs):
            raise ValueError("Повторяющиеся соседние точки")
        refs = []
        try:
            for a, b in pairs:
                refs.append(self.line(*a, *b, style)["reference"])
        except Exception:
            for ref in refs:
                self.doc2d().ksDeleteObj(ref)
            raise
        return {"references": refs, "representation": "line_segments"}

    def rectangle(self, x, y, width, height, style=1):
        x, y = number(x), number(y)
        w, h = number(width, True), number(height, True)
        return self.polyline([[x, y], [x+w, y], [x+w, y+h], [x, y+h]], True, style)

    def text(self, x, y, text, height=5, angle=0):
        return {"reference": reference(self.doc2d().ksText(
            number(x), number(y), number(angle), number(height, True), 1, 0, text))}

    def set_layer(self, layer):
        result = self.doc2d().ksLayer(layer)
        if not result:
            raise RuntimeError("Не удалось переключить слой")
        return {"layer": layer}

    def delete_object(self, ref):
        if not self.doc2d().ksDeleteObj(reference(ref)):
            raise RuntimeError("Объект не удалён (возможно, ссылка устарела)")
        return {"deleted": ref}

    def export_dxf(self, path, overwrite=False):
        if Path(path).suffix.lower()!='.dxf':
            raise ValueError('Use .dxf extension')
        with staged_output(path,overwrite) as (stage,target):
            self.doc2d().ksSaveToDXF(str(stage))
        return {"path": str(target), "bytes": target.stat().st_size}

    def screenshot(self):
        from capture import capture_window
        return capture_window(int(self.connect().MainWindowHandle))

    def execute_python_script(self, code):
        if os.getenv("KOMPAS_ALLOW_SCRIPTS") != "1":
            raise PermissionError("Скрипты отключены. Задайте KOMPAS_ALLOW_SCRIPTS=1.")
        self.connect()
        # This is intentionally NOT a sandbox. Do not accept untrusted code.
        namespace = {"kompas": self.kompas, "app7": self.app7,
                     "doc2d": self.doc2d() if self.app7.ActiveDocument and
                     self.app7.ActiveDocument.DocumentType in (1, 2) else None,
                     "doc3d": self.doc3d() if self.app7.ActiveDocument and
                     self.app7.ActiveDocument.DocumentType == 4 else None}
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(compile(code, "<kompas-agent>", "exec"), namespace)
        result = namespace.get("result")
        # COM objects must not escape the STA thread.
        json.dumps(result, allow_nan=False)
        return {"stdout": buf.getvalue()[-16000:], "result": result}


class ComWorker:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kompas-sta")
        self.backend = None
        self.log = AuditLog()
        self._lock=Lock()
        self._closed=False

    def _call(self, method, args, kwargs):
        import pythoncom
        if self.backend is None:
            pythoncom.CoInitializeEx(pythoncom.COINIT_APARTMENTTHREADED)
            self.backend = Kompas()
        pythoncom.PumpWaitingMessages()
        import time
        import inspect
        start = time.monotonic()
        func = getattr(self.backend, method)
        arguments = dict(inspect.signature(func).bind(*args, **kwargs).arguments)
        document = None
        try:
            state=getattr(self.backend,'_editing_sketch',None)
            if state and method in {'create_document','open_document','activate_document','close_document',
                                    'save_document','save_current_document','create_checkpoint','restore_checkpoint',
                                    'sketch3d','create_sketch','extrusion3d','revolve','edge_operation',
                                    'set_feature_parameters','rebuild_model','fit_view3d','add_component',
                                    'set_component_placement','create_closed_profile','cut_through_all',
                                    'create_model_projection','create_model_view'}:
                raise RuntimeError('Finish managed sketch editing with end_sketch_edit before this operation')
            if self.backend.app7 is not None:
                try:
                    doc = self.backend.app7.ActiveDocument
                    document = int(doc.Reference) if doc is not None else None
                except Exception:
                    pass # Logging must not prevent status from recovering a dead COM session.
            result = func(*args, **kwargs)
            logged = '<image bytes>' if isinstance(result, bytes) else result
            self.log.record(method, arguments, result=logged, document=document,
                            elapsed=time.monotonic()-start)
            return result
        except Exception as exc:
            self.log.record(method, arguments, error=error_info(exc, method),
                            document=document, elapsed=time.monotonic()-start)
            raise

    def call(self, method, *args, **kwargs):
        with self._lock:
            if self._closed:
                raise RuntimeError('COM worker is closed')
            future=self.executor.submit(self._call, method, args, kwargs)
        return future.result()

    def close(self):
        def release():
            if self.backend is not None:
                import pythoncom
                state=getattr(self.backend,'_editing_sketch',None)
                if state:
                    try:
                        state[2].EndEdit()
                    except Exception:
                        import logging
                        logging.getLogger(__name__).exception('Could not finish sketch edit during shutdown')
                self.backend.app7 = None
                self.backend.kompas = None
                self.backend._entities3d = {}
                self.backend.registry.entries.clear()
                self.backend._editing_sketch=None
                self.backend = None
                pythoncom.CoUninitialize()
        with self._lock:
            if self._closed:
                return
            self._closed=True
            future=self.executor.submit(release)
        try:
            future.result()
        finally:
            self.executor.shutdown()
