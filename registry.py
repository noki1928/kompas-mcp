"""Process-local, document-scoped COM handles. No COM objects cross STA boundary."""
from dataclasses import dataclass
import uuid


class StaleHandleError(ValueError):
    pass


@dataclass
class Entry:
    obj: object
    scope: int | None
    kind: str
    epoch: int
    locator: dict | None = None


class ObjectRegistry:
    def __init__(self, capacity=10000):
        self.entries = {}
        self.epochs = {}
        self.capacity = capacity

    def put(self, obj, scope=None, kind='object', locator=None):
        if scope is not None:
            self.epochs.setdefault(scope,0)
        epoch = self.epochs.get(scope, 0)
        for key, entry in self.entries.items():
            if entry.scope == scope and entry.kind == kind and entry.epoch == epoch:
                if obj is entry.obj:
                    return key
                try:
                    if hasattr(obj, '_oleobj_') and obj._oleobj_ == entry.obj._oleobj_:
                        return key
                except (AttributeError, TypeError):
                    pass
        if len(self.entries) >= self.capacity:
            raise RuntimeError('Object registry limit reached; release handles or close test documents')
        key = 'obj_' + uuid.uuid4().hex
        self.entries[key] = Entry(obj, scope, kind, epoch, locator)
        return key

    def get(self, key, open_documents=None):
        entry = self.entries.get(key)
        if entry is None:
            raise StaleHandleError(f'Unknown or released handle: {key}')
        if entry.scope is not None and open_documents is not None and entry.scope not in open_documents:
            self.drop_document(entry.scope)
            raise StaleHandleError(f'Document closed for handle: {key}')
        if entry.kind == 'topology' and entry.epoch != self.epochs.get(entry.scope, 0):
            raise StaleHandleError(f'Topology changed; reacquire this handle: {key}')
        return entry

    def invalidate_topology(self, scope):
        self.epochs[scope] = self.epochs.get(scope, 0) + 1
        for key in [k for k, e in self.entries.items() if e.scope == scope and e.kind == 'topology']:
            del self.entries[key]

    def drop_document(self, scope):
        for key in [k for k, e in self.entries.items() if e.scope == scope]:
            del self.entries[key]
        self.epochs.pop(scope, None)

    def release(self, keys):
        released = 0
        for key in keys:
            if self.entries.pop(key, None) is not None:
                released += 1
        return released
