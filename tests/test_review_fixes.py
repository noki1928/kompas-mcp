import json
import unittest
from unittest.mock import Mock

from diagnostics import tool_result
from safe_modeling import check_contract
from kompas import Kompas


def entity(name, typ=25):
    e = Mock(); e.name = name; e.type = typ
    return e


def part_with(*entities):
    collection = Mock()
    collection.GetCount.return_value = len(entities)
    collection.GetByIndex.side_effect = lambda i: entities[i]
    part = Mock(); part.EntityCollection.return_value = collection
    return part


class ToolResultTests(unittest.TestCase):
    def test_success_passes_through(self):
        ok = {'success': True, 'x': 1}
        self.assertIs(tool_result(ok), ok)
        self.assertEqual(tool_result(b'png'), b'png')

    def test_failure_is_protocol_error_with_same_json(self):
        failure = {'success': False, 'message': 'boom', 'cleanup': {'success': True}}
        r = tool_result(failure)
        self.assertTrue(r.isError)
        self.assertEqual(r.structuredContent, failure)
        self.assertEqual(json.loads(r.content[0].text), failure)


class ToleranceTests(unittest.TestCase):
    def test_default_tolerance_accepts_kernel_noise(self):
        # Observed live: 25404.650 actual vs 25404.636 analytic after a 406 mm3 extrusion.
        metrics = {'body_count': 1, 'all_solid': True, 'volume_mm3': 25404.650, 'bounds_mm': None}
        self.assertEqual(check_contract(metrics, {'volume_mm3': 25404.636}), [])

    def test_default_tolerance_still_rejects_real_mismatch(self):
        metrics = {'body_count': 1, 'all_solid': True, 'volume_mm3': 25404.65, 'bounds_mm': None}
        self.assertTrue(check_contract(metrics, {'volume_mm3': 25400.0}))


class CleanupTests(unittest.TestCase):
    def test_cleanup_error_survives_missing_kompas(self):
        # CI has no KOMPAS: the scope lookup in cleanup's finally must not mask the structured error.
        k = Kompas()
        k._part3d = Mock(side_effect=RuntimeError('lost native session'))
        k._scope = Mock(side_effect=OSError('Invalid class string'))
        result = k._cleanup_created(Mock())
        self.assertFalse(result['success']); self.assertIn('lost native session', result['message'])


class FeatureErrorTests(unittest.TestCase):
    def test_only_new_errors_count(self):
        k = Kompas()
        old = {'name': 'Эскиз:10', 'type': 5, 'error': 0}
        new = {'name': 'Элемент выдавливания:11', 'type': 25, 'error': 3}
        k._native_feature_errors = Mock(return_value=[old, new])
        self.assertEqual(k._new_feature_errors([old]), [new])

    def test_delete_feature_requires_one_selector(self):
        k = Kompas()
        with self.assertRaises(ValueError): k.delete_feature()
        with self.assertRaises(ValueError): k.delete_feature('obj_x', 'Эскиз:1')

    def test_delete_feature_name_must_be_unique(self):
        k = Kompas()
        k._part3d = Mock(return_value=(Mock(), part_with(entity('Вырез'), entity('Вырез'))))
        with self.assertRaisesRegex(ValueError, 'found 2'): k.delete_feature(name='Вырез')

    def test_delete_feature_reports_dependents(self):
        k = Kompas()
        sketch, cut = entity('Эскиз:1', 5), entity('Вырез:1', 26)
        d3 = Mock(); d3.DeleteObject.return_value = True; d3.RebuildDocument.return_value = True
        k._part3d = Mock(return_value=(d3, part_with(sketch, cut)))
        k._feature_names = Mock(side_effect=[['Эскиз:1', 'Вырез:1'], []])
        k._model_metrics = Mock(side_effect=[{'volume_mm3': 90.0}, {'volume_mm3': 100.0}])
        k._native_feature_errors = Mock(return_value=[])
        k._scope = Mock(return_value=1); k.registry = Mock()
        r = k.delete_feature(name='Эскиз:1')
        d3.DeleteObject.assert_called_once_with(sketch)
        self.assertEqual(r['removed_features'], ['Эскиз:1', 'Вырез:1'])
        self.assertEqual(r['volume_delta_mm3'], 10.0)
        self.assertTrue(r['warnings'])


if __name__ == '__main__':
    unittest.main()
