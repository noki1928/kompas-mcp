import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from diagnostics import AuditLog
from kompas import Kompas, ComWorker, ConnectionLostError
from registry import ObjectRegistry
from sdk_catalog import SdkCatalog
from visualization import staged_output


class StabilityTests(unittest.TestCase):
    def test_failed_export_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'drawing.pdf'; p.write_bytes(b'original')
            with self.assertRaises(RuntimeError):
                with staged_output(p,True) as (stage,target):
                    stage.write_bytes(b'partial')
                    raise RuntimeError('converter failed')
            self.assertEqual(p.read_bytes(),b'original')
            self.assertEqual(list(Path(tmp).iterdir()),[p])
            with staged_output(p,True) as (stage,target): stage.write_bytes(b'replacement')
            self.assertEqual(p.read_bytes(),b'replacement')

    def test_native_dxf_failure_cannot_reuse_old_output(self):
        k=Kompas(); k.doc2d=Mock(return_value=Mock())
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'old.dxf'; p.write_bytes(b'old')
            with self.assertRaises(RuntimeError): k.export_dxf(str(p),True)
            self.assertEqual(p.read_bytes(),b'old')
    def test_worker_close_idempotent(self):
        w=ComWorker(); w.close(); w.close()
        with self.assertRaisesRegex(RuntimeError,'closed'): w.call('status')

    def test_logging_cannot_turn_success_into_retry(self):
        log=AuditLog()
        with patch('diagnostics.json.dumps',side_effect=ValueError('bad serialization')):
            with self.assertLogs(level='ERROR'):
                log.record('test',{},result={'success':True})

    def test_closed_documents_without_topology_are_pruned(self):
        k=Kompas(); k._open_refs=Mock(return_value=set()); k.connect=Mock(return_value=Mock(ActiveDocument=None))
        h=k.registry.put(object(),12,'drawing_view'); k._model_stamps[12]=5
        k._sync_handles()
        self.assertNotIn(h,k.registry.entries); self.assertNotIn(12,k._model_stamps)

    def test_connection_loss_never_replays(self):
        k=Kompas(); k.registry.put(object(),12); k._model_stamps[12]=1
        exc=RuntimeError('RPC'); exc.hresult=-2147023174
        class Broken:
            @property
            def Count(self): raise exc
        k.app7=Mock(Documents=Broken()); k.kompas=object()
        with self.assertRaises(ConnectionLostError): k.connect()
        self.assertIsNone(k.app7); self.assertIsNone(k.kompas)
        self.assertFalse(k.registry.entries); self.assertFalse(k._model_stamps)

    def test_invalid_feature_request_assigns_nothing(self):
        k=Kompas(); entity=Mock(type=25); definition=Mock()
        entity.GetDefinition.return_value=definition
        k._entity_handle=Mock(return_value=entity)
        k.get_feature_parameters=Mock(return_value={'parameters':{'direction_type':0}})
        with self.assertRaises(ValueError):
            k.set_feature_parameters('feature',{'reverse':True,'depth':-1})
        definition.SetSideParam.assert_not_called(); entity.Update.assert_not_called()

    def test_invalid_dimension_precedes_native_creation(self):
        k=Kompas(); k._view7=Mock()
        for args in ({'points':[[0,0],[0,10]],'position':[0,0]},
                     {'kind':'radius','center':[0,0],'radius':-1},
                     {'points':[[0,0],[10,0]],'position':[float('nan'),0]}):
            with self.assertRaises(ValueError): k.add_dimension(**args)
        k._view7.assert_not_called()

    def test_output_extension_precedes_save(self):
        k=Kompas(); doc=Mock(DocumentType=4); k.active=Mock(return_value=doc)
        with self.assertRaises(ValueError): k.save_document('wrong.cdw')
        doc.SaveAs.assert_not_called()

    def test_capture_batch_validation_precedes_view_change(self):
        k=Kompas(); k.set_standard_view=Mock()
        with self.assertRaises(ValueError): k.capture_views(['front','unknown'])
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp)/'top.png').write_bytes(b'existing')
            with self.assertRaises(FileExistsError): k.capture_views(['front','top'],tmp)
        k.set_standard_view.assert_not_called()

    def test_catalog_limit_validation_precedes_loading(self):
        sdk=SdkCatalog(); sdk.load=Mock()
        with self.assertRaises(ValueError): sdk.enums(limit=-1)
        sdk.load.assert_not_called()

    def test_scripts_json_and_stdout(self):
        k=Kompas(); k.connect=Mock(); k.app7=Mock(ActiveDocument=None)
        with patch.dict('os.environ',{'KOMPAS_ALLOW_SCRIPTS':'1'}):
            r=k.execute_python_script('print("probe"); result={"ok":42}')
            self.assertEqual(r['stdout'],'probe\n'); self.assertEqual(r['result'],{'ok':42})
            with self.assertRaises((TypeError,ValueError)):
                k.execute_python_script('result=float("nan")')

    def test_empty_profiles_and_wrong_filters_precede_com(self):
        k=Kompas(); k._part3d=Mock()
        with self.assertRaises(ValueError): k.find_faces(limit=0)
        with self.assertRaises(ValueError): k.find_edges(min_length=20,max_length=10)
        with self.assertRaises(ValueError): k.find_faces(radius=-1)
        k._part3d.assert_not_called()
