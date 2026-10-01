"""Managed document lifecycle and non-destructive snapshot recovery."""
from pathlib import Path
import shutil
import uuid


class DocumentMixin:
    def _document(self, document_reference=None):
        if document_reference is None:
            return self.active()
        app = self.connect()
        for i in range(app.Documents.Count):
            doc = app.Documents.Item(i)
            if int(doc.Reference) == int(document_reference):
                return doc
        raise ValueError('Document reference is not open')

    def list_documents(self):
        self._sync_handles()
        app = self.connect()
        return {'success': True, 'documents': [self.describe(app.Documents.Item(i))
                                              for i in range(app.Documents.Count)]}

    def activate_document(self, document_reference):
        doc = self._document(document_reference)
        doc.Active = True
        import pythoncom
        pythoncom.PumpWaitingMessages()
        if int(self.active().Reference) != int(document_reference):
            raise RuntimeError('Document activation did not complete')
        return {'success': True, 'document': self.describe(doc)}

    def close_document(self, document_reference, discard_changes=False):
        doc = self._document(document_reference)
        if doc.Changed and not discard_changes:
            raise PermissionError('Document has unsaved changes; save or explicitly set discard_changes=true')
        doc.Close(0)  # no interactive save prompt; existing saved files are untouched
        self.registry.drop_document(int(document_reference))
        self._model_stamps.pop(int(document_reference),None)
        getattr(self,'_camera_names',{}).pop(int(document_reference),None)
        cache=getattr(self,'_profile_bounds',{})
        for key in [key for key,value in cache.items() if value['scope']==int(document_reference)]: cache.pop(key)
        if int(document_reference) in self._open_refs():
            raise RuntimeError('KOMPAS did not close the document')
        return {'success': True, 'closed': document_reference}

    def save_current_document(self, confirm_overwrite=False):
        doc = self.active()
        if not doc.PathName:
            raise ValueError('Unsaved document needs save_document(path=...)')
        if not confirm_overwrite:
            raise PermissionError('Saving current file overwrites it; confirm_overwrite=true required')
        doc.Save()
        if doc.Changed:
            raise RuntimeError('Document still has unsaved changes')
        return {'success': True, 'document': self.describe(doc)}

    def create_checkpoint(self):
        doc = self.active()
        original = doc.PathName
        ext = {1: '.cdw', 2: '.frw', 3: '.spw', 4: '.m3d', 5: '.a3d', 6: '.kdw', 7: '.a3d'}[int(doc.DocumentType)]
        key = 'checkpoint_' + uuid.uuid4().hex
        directory = Path(__file__).parent / 'artifacts' / 'checkpoints' / key
        directory.mkdir(parents=True)
        working = directory / ('working' + ext)
        snapshot = directory / ('snapshot' + ext)
        doc.SaveAs(str(working))
        if not working.is_file() or not working.stat().st_size or doc.Changed:
            raise RuntimeError('Could not save checkpoint working copy')
        shutil.copy2(working, snapshot)
        if not hasattr(self, '_checkpoints'):
            self._checkpoints = {}
        self._checkpoints[key] = {'snapshot': str(snapshot), 'original_path': original,
                                  'document_reference': int(doc.Reference)}
        return {'success': True, 'checkpoint_id': key, 'path': str(snapshot),
                'document': self.describe(doc), 'original_path': original,
                'warnings': ['SaveAs changes current document file association to a working copy. Original file not overwritten. Restore opens a NEW recovered document, not in-place Undo.']}

    def restore_checkpoint(self, checkpoint_id):
        entry = getattr(self, '_checkpoints', {}).get(checkpoint_id)
        if entry is None:
            raise ValueError('Unknown checkpoint (process-local); open the snapshot manually after restart')
        snapshot = Path(entry['snapshot'])
        path = snapshot.with_name('recovered-' + uuid.uuid4().hex + snapshot.suffix)
        shutil.copy2(snapshot, path)
        doc = self.connect().Documents.Open(str(path), True, False)
        if doc is None:
            raise RuntimeError('Could not open recovered document')
        self.activate_document(int(doc.Reference))
        return {'success': True, 'document': self.describe(doc), 'path': str(path),
                'warnings': ['Original edited document remains open; close it explicitly only when safe. Old handles are not valid for the recovered copy.']}
