"""Generic dispatch bridge: public one-member operations, no eval/code paths."""
import math
import re

from diagnostics import error_info

MEMBER = re.compile(r'^[A-Za-z][A-Za-z0-9_]*$')
# File writes/process shutdown go through managed tools, not unchecked raw dispatch.
BLOCKED = {'Quit', 'Close', 'close', 'Save', 'SaveAs', 'Open', 'OpenEx', 'OpenDocument',
           'ksSaveDocument', 'ksSaveDocumentEx', 'ksOpenDocument', 'ksCloseDocument',
           'ExecuteKompasCommand', 'CreateProcessParam', 'QueryInterface', 'AddRef', 'Release',
           'Invoke', 'InvokeTypes', 'GetIDsOfNames', 'GetTypeInfo', 'GetTypeInfoCount',
           'Convert', 'Execute', 'SpecialExecute', 'Load', 'SaveModifiedPartAs', 'OpenSourceDocument',
           'CreatePartFromFile', 'SetPartFromFile', 'SetPartFromFileEx'}
BLOCKED_LOWER = {name.lower() for name in BLOCKED}


def type_description(obj):
    info = obj._oleobj_.GetTypeInfo()
    attr = info.GetTypeAttr()
    name, doc, *_ = info.GetDocumentation(-1)
    members = {}
    for i in range(attr.cFuncs):
        desc = info.GetFuncDesc(i)
        names = info.GetNames(desc[0])
        item = members.setdefault(names[0], {'name': names[0], 'signatures': []})
        item['signatures'].append({'parameters': list(names[1:]), 'invkind': desc[4],
                                   'raw_signature': repr(desc), 'doc': info.GetDocumentation(desc[0])[1]})
    for i in range(attr.cVars):
        desc = info.GetVarDesc(i)
        name2 = info.GetNames(desc.memid)[0]
        members.setdefault(name2, {'name': name2, 'signatures': []})['property'] = True
    return {'type': name, 'guid': str(attr.iid), 'doc': doc, 'members': list(members.values())}


class ApiMixin:
    def _open_refs(self):
        app = self.connect()
        return {int(app.Documents.Item(i).Reference) for i in range(app.Documents.Count)}

    def _scope(self):
        doc = self.connect().ActiveDocument
        return int(doc.Reference) if doc is not None else None

    def _sync_handles(self):
        opened = self._open_refs()
        scopes=set(self.registry.epochs) | {e.scope for e in self.registry.entries.values()}
        for scope in scopes:
            if scope is not None and scope not in opened:
                self.registry.drop_document(scope)
                self._model_stamps.pop(scope,None)
                state=getattr(self,'_editing_sketch',None)
                if state and state[0]==scope:
                    self._editing_sketch=None
        # Update stamps detect many manual model changes, not an application-wide lock.
        doc = self.connect().ActiveDocument
        if doc is not None and doc.DocumentType in (4, 5, 7):
            d3 = self.kompas.ActiveDocument3D
            if d3 is not None:
                part = d3.GetPart(-1)
                if part is not None:
                    feature = part.GetFeature()
                    stamp = int(feature.updateStamp) if feature is not None else None
                    scope = int(doc.Reference)
                    previous = self._model_stamps.get(scope)
                    if previous is not None and stamp != previous:
                        self.registry.invalidate_topology(scope)
                    self._model_stamps[scope] = stamp
        return opened

    def _root(self, target):
        if target == 'api7':
            return self.connect(), None
        if target == 'api5':
            self.connect()
            return self.kompas, None
        if target == 'document':
            return self.active(), self._scope()
        if target == 'doc2d':
            return self.doc2d(), self._scope()
        if target in ('doc3d', 'part'):
            doc = self.active()
            if doc.DocumentType not in (4, 5, 7):
                raise ValueError('Active part or assembly required')
            obj = self.kompas.ActiveDocument3D
            if obj is None or int(obj.reference) != int(doc.Reference):
                raise RuntimeError('API5 document not synchronized; retry state')
            return (obj.GetPart(-1) if target == 'part' else obj), self._scope()
        self._sync_handles()
        entry = self.registry.get(target, self._open_refs())
        if entry.kind=='edit_context' and (not getattr(self,'_editing_sketch',None) or entry.scope!=self._scope()):
            raise ValueError('Sketch edit context is no longer active')
        return entry.obj, entry.scope

    def _kind(self, obj):
        try:
            typ = obj._oleobj_.GetTypeInfo().GetDocumentation(-1)[0]
            if typ.startswith('ks'):
                typ='I'+typ[2:]
            if typ in ('IFaceDefinition', 'IEdgeDefinition', 'IVertexDefinition',
                       'ISurface', 'ICurve3D', 'IBody', 'IBodyCollection', 'IFaceCollection',
                       'IEdgeCollection', 'IOrientedEdge', 'ILoop'):
                return 'topology'
            if typ == 'IEntity':
                t = int(obj.type)
                return 'topology' if t in (6, 7, 8) else ('sketch' if t == 5 else 'feature')
        except Exception:
            pass
        return 'object'

    def _encode(self, value, scope=None, depth=0):
        if depth > 12:
            raise ValueError('API result nesting exceeds limit')
        if value is None or isinstance(value, (str, bool, int)):
            return value
        if isinstance(value, float):
            if not math.isfinite(value):
                return {'nonfinite': str(value)}
            return value
        if hasattr(value, '_oleobj_'):
            if scope is None:
                try:
                    typ=value._oleobj_.GetTypeInfo().GetDocumentation(-1)[0]
                    if 'Document' in typ and 'Collection' not in typ and typ!='IDocuments':
                        ref=getattr(value,'Reference',None)
                        if ref is None:
                            ref=getattr(value,'reference',None)
                        if ref is not None and int(ref) in self._open_refs():
                            scope=int(ref)
                except (AttributeError,TypeError,ValueError):
                    pass
            kind = self._kind(value)
            key = self.registry.put(value, scope, kind)
            try:
                typ = value._oleobj_.GetTypeInfo().GetDocumentation(-1)[0]
            except Exception:
                typ = 'IDispatch'
            return {'object_id': key, 'api_type': typ, 'kind': kind,
                    'document_reference': scope, 'generation': self.registry.epochs.get(scope, 0)}
        if isinstance(value, (tuple, list)):
            return [self._encode(v, scope, depth+1) for v in value]
        if isinstance(value, dict):
            return {str(k): self._encode(v, scope, depth+1) for k, v in value.items()}
        raise TypeError(f'Unsupported API return type: {type(value).__name__}')

    def _decode(self, value, scope):
        if isinstance(value, dict) and set(value) == {'object_id'}:
            entry = self.registry.get(value['object_id'], self._open_refs())
            if scope is not None and entry.scope is not None and entry.scope != scope:
                raise ValueError('Cannot pass objects from a different document')
            return entry.obj
        if isinstance(value, dict) and set(value) == {'missing'} and value['missing'] is True:
            import pythoncom
            return pythoncom.Missing
        if isinstance(value, list):
            return tuple(self._decode(v, scope) for v in value)
        if isinstance(value, dict):
            raise ValueError('COM arguments accept scalars, arrays, {object_id}, or {missing:true}; no arbitrary dict')
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError('Nonfinite input')
        return value

    def describe_object(self, target):
        try:
            obj, scope = self._root(target)
            result = type_description(obj)
            result.update({'success': True, 'target': target, 'document_reference': scope,
                           'runtime_members': [n for n in dir(obj) if not n.startswith('_')],
                           'warnings': ['TLB declarations can differ from runtime dispatch; report unsupported members explicitly']})
            return result
        except Exception as exc:
            return error_info(exc, 'describe_object', target)

    def kompas_api_call(self, target, operation='get', member='', arguments=(), value=None,
                        interface='', allow_mutation=False):
        try:
            obj, scope = self._root(target)
            if operation == 'cast':
                import win32com.client as com
                if not MEMBER.fullmatch(interface):
                    raise ValueError('A public SDK interface name is required')
                result = com.CastTo(obj, interface)
            else:
                if not MEMBER.fullmatch(member):
                    raise ValueError('Use one public member, not a path/expression')
                if member.lower() in BLOCKED_LOWER or member.lower().startswith(('saveasto','saveas','kssaveto','saveconfiguration','loadconfiguration')):
                    raise PermissionError('Lifecycle/file I/O or raw IUnknown call prohibited; use managed document/export tools')
                if operation in ('call', 'set') and not allow_mutation:
                    raise PermissionError('Calls/setters require allow_mutation=true; create a checkpoint first')
                if operation == 'get':
                    # API5 dispatch can invoke a zero-argument METHOD on getattr.
                    # Inspect invocation kind before reading, rather than afterwards.
                    if hasattr(obj,'_oleobj_'):
                        declared=next((m for m in type_description(obj)['members'] if m['name'].lower()==member.lower()),None)
                        if declared and declared.get('signatures') and not any(s['invkind']==2 for s in declared['signatures']):
                            raise ValueError('This member is a method; use operation=call')
                    result = getattr(obj, member)
                    if callable(result) and not hasattr(result,'_oleobj_'):
                        raise ValueError('This member is a method; use operation=call and exact SDK arguments')
                elif operation == 'set':
                    setattr(obj, member, self._decode(value, scope))
                    result = {'property': member, 'assigned': True}
                elif operation == 'call':
                    method = getattr(obj, member)
                    args = [self._decode(v, scope) for v in arguments]
                    # pywin32 auto-invokes some zero-argument dispatch methods.
                    if callable(method) and not hasattr(method,'_oleobj_'):
                        result = method(*args)
                    elif not args:
                        result = method
                    else:
                        raise TypeError('Runtime auto-invoked a zero-argument member; no arguments accepted')
                else:
                    raise ValueError('operation must be get, set, call, or cast')
            if operation == 'call' and scope is not None and member in (
                'Create', 'Update', 'Delete', 'DeleteObject', 'RebuildDocument',
                'RebuildModel', 'RebuildModelEx', 'EndEdit', 'ksDeleteObj', 'ksEndObj'):
                self.registry.invalidate_topology(scope)
            if operation in ('set','call'):
                self._sync_handles()
            encoded = self._encode(result, scope)
            return {'success': True, 'target': target, 'api_method': member or interface,
                    'result': encoded, 'warnings': ['Inspect CAD state after mutations; API success does not prove geometry correctness'] if allow_mutation else []}
        except Exception as exc:
            return error_info(exc, member or interface, target)

    def api_batch(self, calls):
        if len(calls) > 100:
            raise ValueError('Maximum 100 API calls per batch')
        results = []
        for call in calls:
            result = self.kompas_api_call(**call)
            results.append(result)
            if not result['success']:
                break
        return {'success': all(r['success'] for r in results), 'results': results,
                'executed': len(results), 'atomic': False, 'warnings': ['Prior successful calls are not rolled back; use a checkpoint']}

    def release_objects(self, object_ids):
        return {'success': True, 'released': self.registry.release(object_ids)}

    def sdk_catalog(self, query='', interface='', library='', limit=30):
        return self.sdk.query(query,interface,library,limit)

    def api_constants(self, names=(), query='', limit=100):
        return self.sdk.enums(names,query,limit)

    def get_kompas_state(self):
        self._sync_handles()
        state=self.status()
        roots={}
        for name in ('api7','document','doc2d','doc3d','part'):
            try:
                obj,scope=self._root(name)
                roots[name]=self._encode(obj,scope)
            except (ValueError,RuntimeError):
                pass
        return {'success':True,**state,'roots':roots,'registry_objects':len(self.registry.entries),
                'topology_generations':self.registry.epochs,'length_unit':'mm','angle_unit':'degree',
                'editing_sketch':getattr(self,'_editing_sketch',None)[1] if getattr(self,'_editing_sketch',None) else None,
                'warnings':['Handles are process/document-local; topology changes invalidate geometric references. Manual modifications can occur between calls.']}

    def get_object_properties(self,target,members):
        if len(members)>100:
            raise ValueError('Maximum 100 properties')
        return {'success':True,'target':target,'properties':{name:self.kompas_api_call(target,'get',member=name) for name in members}}

    def selection(self,operation='get',object_ids=()):
        import win32com.client as com
        doc=self.active()
        if doc.DocumentType not in (4,5,7):
            raise ValueError('Selection tool currently supports API7 3D documents; 2D selection via generic API5')
        manager=com.CastTo(doc,'IKompasDocument3D').SelectionManager
        if operation=='get':
            return {'success':True,'selected':self._encode(manager.SelectedObjects,self._scope())}
        if operation=='clear':
            return {'success':bool(manager.UnselectAll())}
        if operation!='select':
            raise ValueError('operation=get/clear/select')
        objects=[self._entity_handle(key) for key in object_ids]
        return {'success':bool(manager.Select(tuple(objects))),
                'warnings':['API7 selection expects API7 model objects; obtain them through API7 handles, not API5 entities']}

    def show_application(self,visible=True,restore_window=True):
        import win32gui
        app=self.connect(); app.Visible=bool(visible)
        hwnd=int(app.MainWindowHandle)
        if visible and restore_window:
            win32gui.ShowWindow(hwnd,9)
        return {'success':True,'visible':bool(app.Visible),'minimized':bool(win32gui.IsIconic(hwnd))}
