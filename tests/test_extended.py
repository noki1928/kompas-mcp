import tempfile
import unittest
from pathlib import Path

from api_adapter import ApiMixin
from diagnostics import error_info
from registry import ObjectRegistry, StaleHandleError
from visualization import checked_output, file_result


class FakeApi(ApiMixin):
    def __init__(self):
        self.obj=type('Fake',(),{'Name':'part'})()
        self.registry=ObjectRegistry()

    def _root(self,target):
        return self.obj,1

    def _sync_handles(self):
        return {1}


class ExtendedTests(unittest.TestCase):
    def test_registry_identity(self):
        r=ObjectRegistry(); obj=object()
        self.assertEqual(r.put(obj,1),r.put(obj,1))

    def test_topology_only_invalidated(self):
        r=ObjectRegistry(); edge=r.put(object(),1,'topology'); feature=r.put(object(),1,'feature')
        r.invalidate_topology(1)
        with self.assertRaises(StaleHandleError): r.get(edge,{1})
        self.assertEqual(r.get(feature,{1}).kind,'feature')

    def test_closed_document(self):
        r=ObjectRegistry(); h=r.put(object(),7)
        with self.assertRaises(StaleHandleError): r.get(h,set())
        self.assertNotIn(h,r.entries)

    def test_capacity_and_release(self):
        r=ObjectRegistry(capacity=1); h=r.put(object())
        with self.assertRaises(RuntimeError): r.put(object())
        self.assertEqual(r.release([h,h]),1)

    def test_generic_policy(self):
        a=FakeApi()
        for member in ('Quit','SaveAs','SaveAsToRasterFormat','__dict__','Name.Sub'):
            self.assertFalse(a.kompas_api_call('document','get',member)['success'])
        self.assertFalse(a.kompas_api_call('document','set','Name',value='new')['success'])
        self.assertEqual(a.obj.Name,'part')
        self.assertEqual(a.kompas_api_call('document','get','Name')['result'],'part')

    def test_batch_stops_without_rollback(self):
        a=FakeApi()
        r=a.api_batch([{'target':'document','operation':'set','member':'Name','value':'new','allow_mutation':True},
                       {'target':'document','operation':'get','member':'Quit'},
                       {'target':'document','operation':'set','member':'Name','value':'other','allow_mutation':True}])
        self.assertFalse(r['success']); self.assertEqual(r['executed'],2)
        self.assertEqual(a.obj.Name,'new')

    def test_output_guard_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'existing.png'; p.write_bytes(b'bytes')
            with self.assertRaises(FileExistsError): checked_output(p)
            self.assertEqual(checked_output(p,True),p.resolve())
            self.assertEqual(file_result(p)['bytes'],5)
            p.write_bytes(b'')
            with self.assertRaises(RuntimeError): file_result(p)

    def test_error_hresult(self):
        e=RuntimeError('native failure'); e.hresult=-2147352567
        r=error_info(e,'Update','obj_example')
        self.assertFalse(r['success']); self.assertEqual(r['api_error_hex'],'0x80020009')
