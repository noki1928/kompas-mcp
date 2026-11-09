import unittest
from unittest.mock import Mock

from kompas import Kompas
from stages import effect_summary, evaluate_assertion, validate_assertion, compact_metrics


def metrics(volume, bodies=1, bounds=(0, 0, 0, 10, 10, 10), solid=True):
    return {'body_count': bodies, 'all_solid': solid, 'bounds_mm': list(bounds) if bounds else None,
            'volume_mm3': volume, 'bodies': [{'volume_mm3': volume}]}


def entity(name, typ=25):
    e = Mock(); e.name = name; e.type = typ
    return e


class FakePart:
    """Feature tree whose DeleteObject really removes the entity, like the native part."""
    def __init__(self, *entities):
        self.entities = list(entities)
        self.d3 = Mock(); self.d3.DeleteObject.side_effect = self.delete; self.d3.RebuildDocument.return_value = True

    def delete(self, e):
        self.entities.remove(e); return True

    def EntityCollection(self, kind):
        c = Mock(); items = list(self.entities)
        c.GetCount.return_value = len(items); c.GetByIndex.side_effect = lambda i: items[i]
        return c


def staged_kompas(part, scope=7):
    k = Kompas()
    k._part3d = Mock(return_value=(part.d3, part)); k._scope = Mock(return_value=scope)
    k._open_refs = Mock(return_value={scope}); k.registry = Mock()
    k.active = Mock(return_value=Mock(DocumentType=4, Reference=scope, PathName='p.m3d'))
    k.describe = Mock(return_value={'reference': scope})
    k._native_feature_errors = Mock(return_value=[])
    return k


class EffectTests(unittest.TestCase):
    def test_verdicts(self):
        self.assertEqual(effect_summary(metrics(100), metrics(120))['verdict'], 'ok')
        self.assertEqual(effect_summary(metrics(100), metrics(100))['verdict'], 'no_effect')
        self.assertEqual(effect_summary(metrics(100), metrics(100), geometry_expected=False)['verdict'], 'ok')
        broken = effect_summary(metrics(100), metrics(90), new_errors=[{'name': 'Вырез', 'type': 26, 'error': 3}])
        self.assertEqual(broken['verdict'], 'broken')
        self.assertEqual(effect_summary(metrics(100), metrics(90, solid=False))['verdict'], 'broken')
        self.assertEqual(effect_summary(metrics(100), metrics(90), assertion_failures=[{'x': 1}])['verdict'],
                         'assertion_failed')

    def test_kernel_noise_is_not_an_effect_but_bounds_are(self):
        self.assertFalse(effect_summary(metrics(25404.636), metrics(25404.650))['geometry_changed'])
        moved = effect_summary(metrics(100), metrics(100, bounds=(0, 0, 0, 10, 10, 11)))
        self.assertTrue(moved['geometry_changed']); self.assertTrue(moved['bounds_changed'])

    def test_compact_drops_body_list(self):
        self.assertNotIn('bodies', compact_metrics(metrics(5)))


class AssertionTests(unittest.TestCase):
    def test_validation(self):
        with self.assertRaises(ValueError): validate_assertion('unknown', {})
        with self.assertRaises(ValueError): validate_assertion('contract', {})
        with self.assertRaises(ValueError): validate_assertion('bounds_within', {'bounds_mm': [1, 0, 0, 0, 1, 1]})
        with self.assertRaises(ValueError): validate_assertion('volume_range', {'min_mm3': 5, 'max_mm3': 1})
        self.assertEqual(validate_assertion('volume_range', {'min_mm3': 1})['min_mm3'], 1.0)

    def test_evaluation(self):
        box = validate_assertion('bounds_within', {'bounds_mm': [-1, -1, -1, 10, 10, 10]})
        self.assertEqual(evaluate_assertion('bounds_within', box, metrics(1)), [])
        self.assertTrue(evaluate_assertion('bounds_within', box, metrics(1, bounds=(0, 0, 0, 10, 10, 10.5))))
        rng = validate_assertion('volume_range', {'max_mm3': 50})
        self.assertTrue(evaluate_assertion('volume_range', rng, metrics(60)))
        contract = validate_assertion('contract', {'body_count': 1})
        self.assertTrue(evaluate_assertion('contract', contract, metrics(1, bodies=2)))

    def test_registered_assertion_reaches_effect(self):
        k = staged_kompas(FakePart())
        k._model_metrics = Mock(return_value=metrics(40))
        k.assert_register('volume cap', 'volume_range', {'max_mm3': 50})
        effect = k._effect(metrics(40), metrics(60))
        self.assertEqual(effect['verdict'], 'assertion_failed')
        self.assertEqual(effect['assertion_failures'][0]['assertion'], 'volume cap')
        k.assert_remove('volume cap')
        self.assertEqual(k._effect(metrics(40), metrics(60))['verdict'], 'ok')


class StageTests(unittest.TestCase):
    def test_abort_deletes_only_appended_features_newest_first(self):
        base, sketch, boss = entity('Эскиз:1', 5), entity('Эскиз:2', 5), entity('Бобышка', 25)
        part = FakePart(entity('Плоскость XY', 1), base)
        k = staged_kompas(part)
        k._model_metrics = Mock(return_value=metrics(100))
        k.change_begin('bosses')
        part.entities += [sketch, boss]
        r = k.change_abort()
        self.assertTrue(r['success'], r)
        self.assertEqual(r['deleted_features'], ['Бобышка', 'Эскиз:2'])
        self.assertEqual([e.name for e in part.entities], ['Плоскость XY', 'Эскиз:1'])
        self.assertIsNone(k._stage)

    def test_abort_refuses_when_existing_features_changed(self):
        keep = entity('Эскиз:1', 5)
        part = FakePart(keep)
        k = staged_kompas(part)
        k._model_metrics = Mock(return_value=metrics(100))
        k.change_begin('edit')
        part.entities = [entity('Эскиз:9', 5)]
        r = k.change_abort()
        self.assertFalse(r['success']); self.assertTrue(r['stage_open'])
        part.d3.DeleteObject.assert_not_called()

    def test_abort_reports_metric_mismatch_and_keeps_stage(self):
        part = FakePart(entity('Эскиз:1', 5))
        k = staged_kompas(part)
        k._model_metrics = Mock(side_effect=[metrics(100), metrics(101)])
        k.change_begin('x')
        r = k.change_abort()
        self.assertFalse(r['success']); self.assertIsNotNone(k._stage)

    def test_end_refuses_broken_unless_forced(self):
        part = FakePart(entity('Эскиз:1', 5))
        k = staged_kompas(part)
        k._model_metrics = Mock(return_value=metrics(100))
        k.change_begin('x')
        part.entities.append(entity('Вырез', 26))
        k._native_feature_errors = Mock(return_value=[{'name': 'Вырез', 'type': 26, 'error': 3}])
        r = k.change_end()
        self.assertFalse(r['success']); self.assertEqual(r['effect']['verdict'], 'broken')
        self.assertEqual(r['added_features'], ['Вырез'])
        self.assertTrue(k.change_end(force=True)['forced']); self.assertIsNone(k._stage)

    def test_guard_pins_mutations_to_stage_document(self):
        k = staged_kompas(FakePart(entity('Эскиз:1', 5)))
        k._model_metrics = Mock(return_value=metrics(1))
        k.change_begin('x')
        k._scope = Mock(return_value=8); k._open_refs = Mock(return_value={7, 8})
        with self.assertRaisesRegex(RuntimeError, 'open in document 7'): k._stage_guard('extrusion3d', {})
        k._stage_guard('get_model_tree', {})  # reads are allowed anywhere
        k._stage_guard('close_document', {'document_reference': 8})
        with self.assertRaisesRegex(RuntimeError, 'change_end'): k._stage_guard('close_document', {'document_reference': 7})

    def test_closed_stage_document_drops_stage(self):
        k = staged_kompas(FakePart())
        k._model_metrics = Mock(return_value=metrics(1))
        k.change_begin('x')
        k._open_refs = Mock(return_value=set())
        self.assertFalse(k.change_status()['open'])

    def test_only_parts_and_one_stage(self):
        k = staged_kompas(FakePart())
        k._model_metrics = Mock(return_value=metrics(1))
        k.change_begin('x')
        with self.assertRaisesRegex(RuntimeError, 'already open'): k.change_begin('y')
        k2 = staged_kompas(FakePart()); k2.active = Mock(return_value=Mock(DocumentType=5, Reference=7))
        with self.assertRaises(ValueError): k2.change_begin('asm')

    def test_parameter_edit_recorded_and_restored(self):
        cut = entity('Вырез', 26)
        definition = Mock(directionType=0); definition.GetSideParam.return_value = (True, 0, 5.0, 0, False)
        cut.GetDefinition.return_value = definition
        part = FakePart(cut)
        k = staged_kompas(part)
        k._model_metrics = Mock(return_value=metrics(100))
        k.change_begin('deeper')
        k._stage_remember_parameters('obj_cut', cut)
        self.assertEqual(k._stage['parameter_edits'][0]['previous'], {'depth': 5.0, 'reverse': True})
        k._entity_handle = Mock(return_value=cut)
        k.set_feature_parameters = Mock(return_value={'success': True})
        r = k.change_abort()
        self.assertTrue(r['success'], r)
        k.set_feature_parameters.assert_called_once_with('obj_cut', {'depth': 5.0, 'reverse': True}, _restoring=True)


if __name__ == '__main__':
    unittest.main()
