"""Change effects, labelled change stages with feature-level rollback, and stored model assertions.

KOMPAS Undo is not used: COM features are separate Undo records, UndoContainer delays the rebuild our
contracts read, and a live Undo/UndoContainer probe ended in a native crash (see STABILITY.md).
"""
import math
import uuid
from collections import Counter

from geometry import vector

# Methods that can change the active model; a stage pins them to its document.
STAGE_MUTATIONS = {'sketch3d', 'create_sketch', 'create_closed_profile', 'extrusion3d', 'cut_through_all',
                   'revolve', 'edge_operation', 'set_feature_parameters', 'delete_feature', 'rebuild_model',
                   'begin_sketch_edit', 'create_sketch_entities', 'end_sketch_edit', 'kompas_api_call',
                   'api_batch', 'execute_python_script', 'fit_view3d'}
ASSERTION_KINDS = ('contract', 'bounds_within', 'volume_range')


def compact_metrics(metrics):
    """Metrics without the per-body list; what a caller needs to judge a successful step."""
    if not metrics:
        return metrics
    return {key: metrics[key] for key in ('body_count', 'all_solid', 'bounds_mm', 'volume_mm3')}


def _bounds_changed(a, b, tolerance=1e-6):
    if (a is None) != (b is None):
        return True
    return a is not None and any(not math.isclose(x, y, abs_tol=tolerance) for x, y in zip(a, b))


def effect_summary(before, after, new_errors=(), assertion_failures=(), geometry_expected=True):
    """Measured outcome of one mutation. verdict: ok | no_effect | broken | assertion_failed."""
    delta = after['volume_mm3'] - before['volume_mm3']
    # Same kernel-noise allowance as contracts (relative 1e-6).
    noise = max(1e-6, abs(before['volume_mm3']) * 1e-6)
    bounds_changed = _bounds_changed(before['bounds_mm'], after['bounds_mm'])
    changed = abs(delta) > noise or before['body_count'] != after['body_count'] or bounds_changed
    if new_errors or not after['all_solid']:
        verdict = 'broken'
    elif assertion_failures:
        verdict = 'assertion_failed'
    elif geometry_expected and not changed:
        verdict = 'no_effect'
    else:
        verdict = 'ok'
    return {'verdict': verdict, 'geometry_changed': changed, 'volume_delta_mm3': delta,
            'body_count': [before['body_count'], after['body_count']], 'bounds_changed': bounds_changed,
            'bounds_mm': after['bounds_mm'], 'new_feature_errors': list(new_errors),
            'assertion_failures': list(assertion_failures)}


def validate_assertion(kind, spec):
    from safe_modeling import validate_contract
    if kind not in ASSERTION_KINDS:
        raise ValueError('kind must be ' + '/'.join(ASSERTION_KINDS))
    spec = dict(spec or {})
    if kind == 'contract':
        spec = validate_contract(spec)
        if not set(spec) & {'body_count', 'bounds_mm', 'volume_mm3'}:
            raise ValueError('contract needs body_count, bounds_mm or volume_mm3')
    elif kind == 'bounds_within':
        if set(spec) - {'bounds_mm', 'tolerance'}:
            raise ValueError('bounds_within keys: bounds_mm, tolerance')
        b = vector(spec.get('bounds_mm'), 6)
        if any(b[i] > b[i + 3] for i in range(3)):
            raise ValueError('Invalid bounds')
        spec = {'bounds_mm': b, 'tolerance': float(spec.get('tolerance', 1e-6))}
    else:
        if set(spec) - {'min_mm3', 'max_mm3'} or not spec:
            raise ValueError('volume_range keys: min_mm3 and/or max_mm3')
        spec = {k: float(v) for k, v in spec.items()}
        if spec.get('min_mm3', -math.inf) > spec.get('max_mm3', math.inf):
            raise ValueError('min_mm3 > max_mm3')
    return spec


def evaluate_assertion(kind, spec, metrics):
    """Failures of one stored assertion against model metrics (empty list = holds)."""
    from safe_modeling import check_contract
    if kind == 'contract':
        return check_contract(metrics, spec)
    if kind == 'bounds_within':
        b, box, tol = metrics['bounds_mm'], spec['bounds_mm'], spec['tolerance']
        if b is None:
            return [{'check': 'bounds_within', 'actual': None, 'expected': box}]
        inside = all(b[i] >= box[i] - tol for i in range(3)) and all(b[i] <= box[i] + tol for i in range(3, 6))
        return [] if inside else [{'check': 'bounds_within', 'actual': b, 'expected': box}]
    volume = metrics['volume_mm3']
    if volume < spec.get('min_mm3', -math.inf) or volume > spec.get('max_mm3', math.inf):
        return [{'check': 'volume_range', 'actual': volume, 'expected': spec}]
    return []


class StageMixin:
    # ---------------- effects and assertions
    def _assertion_failures(self, metrics, scope=None):
        scope = self._scope() if scope is None else scope
        failures = []
        for name, item in getattr(self, '_assertions', {}).get(scope, {}).items():
            for failure in evaluate_assertion(item['kind'], item['spec'], metrics):
                failures.append({'assertion': name, **failure})
        return failures

    def _effect(self, before, after, new_errors=(), geometry_expected=True):
        return effect_summary(before, after, new_errors, self._assertion_failures(after), geometry_expected)

    def assert_register(self, name, kind, spec):
        if not name or not isinstance(name, str):
            raise ValueError('name must be a non-empty string')
        spec = validate_assertion(kind, spec)
        doc = self.active()
        if int(doc.DocumentType) not in (4, 5, 7):
            raise ValueError('Assertions apply to 3D documents')
        scope = int(doc.Reference)
        store = self.__dict__.setdefault('_assertions', {}).setdefault(scope, {})
        store[name] = {'kind': kind, 'spec': spec, 'path': doc.PathName}
        failures = evaluate_assertion(kind, spec, self._model_metrics())
        return {'success': True, 'name': name, 'kind': kind, 'spec': spec, 'document_reference': scope,
                'holds_now': not failures, 'failures': failures,
                'warnings': ['Assertions are process-local and bound to this open document reference']}

    def assert_list(self):
        scope = self._scope()
        items = getattr(self, '_assertions', {}).get(scope, {})
        return {'success': True, 'document_reference': scope,
                'assertions': [{'name': n, 'kind': v['kind'], 'spec': v['spec']} for n, v in items.items()]}

    def assert_remove(self, name):
        items = getattr(self, '_assertions', {}).get(self._scope(), {})
        if name not in items:
            raise ValueError(f'No assertion named {name!r} in the active document')
        del items[name]
        return {'success': True, 'removed': name}

    def assert_check(self):
        metrics = self._model_metrics()
        failures = self._assertion_failures(metrics)
        errors = self._native_feature_errors()
        return {'success': not failures, 'metrics': compact_metrics(metrics), 'failures': failures,
                'checked': len(getattr(self, '_assertions', {}).get(self._scope(), {})),
                'feature_errors': errors}

    # ---------------- stages
    def _tree_signature(self):
        _, part = self._part3d()
        collection = part.EntityCollection(0)
        return [(e.name, int(e.type)) for e in (collection.GetByIndex(i) for i in range(collection.GetCount()))
                if int(e.type) not in (6, 7, 8)]

    def _semantic_parameters(self, entity):
        """Current values in set_feature_parameters vocabulary, used to restore edits on abort."""
        typ = int(entity.type); definition = entity.GetDefinition()
        if typ in (24, 25, 26):
            direction = int(definition.directionType)
            return {'depth': float(definition.GetSideParam(not bool(direction))[2]),
                    'reverse': bool(direction) != (typ == 26)}
        if typ in (27, 28, 29):
            direction = int(definition.directionType)
            return {'angle': float(definition.GetSideParam(not bool(direction))[1]), 'reverse': bool(direction)}
        if typ == 33:
            chamfer = definition.GetChamferParam()
            return {'distance1': float(chamfer[2]), 'distance2': float(chamfer[3]), 'tangent': bool(definition.tangent)}
        if typ == 34:
            return {'radius': float(definition.radius), 'tangent': bool(definition.tangent)}
        return None

    def _stage_open(self):
        stage = getattr(self, '_stage', None)
        if stage and stage['document_reference'] not in self._open_refs():
            self._stage = None  # its document was closed outside the server
            return None
        return stage

    def _stage_guard(self, method, arguments=None):
        if not getattr(self, '_stage', None) or (method not in STAGE_MUTATIONS and method != 'close_document'):
            return  # read-only and status calls never touch the stage (status must recover dead sessions)
        stage = self._stage_open()
        if not stage:
            return
        if method == 'close_document':
            if int((arguments or {}).get('document_reference', 0)) == stage['document_reference']:
                raise RuntimeError('This document has an open change stage; change_end or change_abort it first')
        elif self._scope() != stage['document_reference']:
            raise RuntimeError(f"Change stage '{stage['label']}' is open in document {stage['document_reference']}; "
                               'activate it, or change_end/change_abort before editing another document')

    def _stage_note(self, method, result):
        stage = self._stage_open()
        if not stage or method not in STAGE_MUTATIONS or not isinstance(result, dict):
            return
        effect = result.get('effect') or {}
        stage['log'].append({'method': method, 'name': result.get('name') or result.get('deleted'),
                             'verdict': effect.get('verdict')})
        if method in ('kompas_api_call', 'api_batch', 'execute_python_script'):
            stage['generic_calls'] += 1

    def _stage_remember_parameters(self, feature_id, entity):
        stage = self._stage_open()
        if stage and stage['document_reference'] == self._scope():
            previous = self._semantic_parameters(entity)
            if previous is not None:
                stage['parameter_edits'].append({'feature_id': feature_id, 'name': entity.name, 'previous': previous})

    def change_begin(self, label, intent=''):
        if self._stage_open():
            raise RuntimeError(f"Stage '{self._stage['label']}' is already open; change_end or change_abort it first")
        if not label or not isinstance(label, str):
            raise ValueError('label must be a non-empty string')
        doc = self.active()
        if int(doc.DocumentType) != 4:
            raise ValueError('Change stages support parts (rollback is by feature tree)')
        metrics = self._model_metrics()
        self._stage = {'id': 'stage_' + uuid.uuid4().hex[:12], 'label': label, 'intent': intent,
                       'document_reference': int(doc.Reference), 'document': self.describe(doc),
                       'tree': self._tree_signature(), 'metrics': metrics, 'errors': self._native_feature_errors(),
                       'parameter_edits': [], 'log': [], 'generic_calls': 0}
        return {'success': True, 'stage_id': self._stage['id'], 'label': label,
                'document': self._stage['document'], 'metrics': compact_metrics(metrics),
                'assertions': len(getattr(self, '_assertions', {}).get(int(doc.Reference), {}))}

    def _stage_summary(self, stage):
        tree = self._tree_signature()
        before = Counter(name for name, _ in stage['tree']); now = Counter(name for name, _ in tree)
        known = {(e['name'], e['type'], e['error']) for e in stage['errors']}
        errors = [e for e in self._native_feature_errors() if (e['name'], e['type'], e['error']) not in known]
        metrics = self._model_metrics()
        return tree, metrics, {
            'stage_id': stage['id'], 'label': stage['label'], 'intent': stage['intent'],
            'added_features': list((now - before).elements()), 'removed_features': list((before - now).elements()),
            'parameter_edits': [{'name': p['name'], 'previous': p['previous']} for p in stage['parameter_edits']],
            'operations': len(stage['log']), 'generic_calls': stage['generic_calls'],
            'effect': self._effect(stage['metrics'], metrics, errors, geometry_expected=False),
            'metrics': compact_metrics(metrics)}

    def change_status(self):
        stage = self._stage_open()
        if not stage:
            return {'success': True, 'open': False}
        if self._scope() != stage['document_reference']:
            return {'success': True, 'open': True, 'stage_id': stage['id'], 'label': stage['label'],
                    'document': stage['document'], 'warnings': ['Stage document is not active; summary not computed']}
        _, _, summary = self._stage_summary(stage)
        return {'success': True, 'open': True, 'document': stage['document'], **summary, 'log': stage['log']}

    def change_end(self, force=False):
        stage = self._stage_open()
        if not stage:
            raise RuntimeError('No open change stage')
        if self._scope() != stage['document_reference']:
            raise RuntimeError('Activate the stage document before change_end')
        _, _, summary = self._stage_summary(stage)
        verdict = summary['effect']['verdict']
        if verdict in ('broken', 'assertion_failed') and not force:
            return {'success': False, 'message': f'Stage verdict {verdict}: fix it, change_abort, or change_end(force=true)',
                    'stage_open': True, **summary}
        self._stage = None
        return {'success': True, 'closed': True, 'forced': bool(force and verdict in ('broken', 'assertion_failed')),
                **summary}

    def change_abort(self):
        """Delete every feature appended during the stage (newest first), restore recorded parameter edits,
        rebuild and verify the model metrics returned to the stage start."""
        from safe_modeling import check_contract
        stage = self._stage_open()
        if not stage:
            raise RuntimeError('No open change stage')
        if self._scope() != stage['document_reference']:
            raise RuntimeError('Activate the stage document before change_abort')
        start = stage['tree']; tree = self._tree_signature()
        if tree[:len(start)] != start:
            return {'success': False, 'stage_open': True,
                    'message': 'Features that existed at change_begin were deleted, renamed or reordered; '
                               'feature-level rollback is impossible. Restore a checkpoint or fix manually.',
                    'tree_at_begin': [n for n, _ in start], 'tree_now': [n for n, _ in tree]}
        d3, part = self._part3d()
        deleted, failures = [], []
        try:
            while True:
                collection = part.EntityCollection(0)
                entities = [e for e in (collection.GetByIndex(i) for i in range(collection.GetCount()))
                            if int(e.type) not in (6, 7, 8)]
                if len(entities) <= len(start):
                    break
                last = entities[-1]; name = last.name
                if not d3.DeleteObject(last):
                    failures.append({'check': 'delete', 'feature': name}); break
                deleted.append(name)
            restored = []
            for edit in reversed(stage['parameter_edits']):
                try:
                    alive = self._entity_handle(edit['feature_id']).IsCreated()
                except Exception:
                    alive = False
                if not alive:
                    continue  # the edited feature was created in this stage and is gone now
                result = self.set_feature_parameters(edit['feature_id'], edit['previous'], _restoring=True)
                (restored if result.get('success') else failures).append(
                    {'feature': edit['name'], **({} if result.get('success') else {'message': result.get('message')})})
            if not d3.RebuildDocument():
                failures.append({'check': 'rebuild'})
        finally:
            self.registry.invalidate_topology(self._scope())
        metrics = self._model_metrics(); before = stage['metrics']
        expected = {'body_count': before['body_count'], 'volume_mm3': before['volume_mm3'],
                    **({'bounds_mm': before['bounds_mm']} if before['bounds_mm'] else {})}
        failures += check_contract(metrics, expected)
        if not failures:
            self._stage = None
        warnings = []
        if stage['generic_calls']:
            warnings.append('Generic API/script calls ran in this stage; their non-feature side effects are not reverted')
        return {'success': not failures, 'stage_open': bool(failures), 'label': stage['label'],
                'deleted_features': deleted, 'restored_parameters': restored, 'failures': failures,
                'metrics': compact_metrics(metrics), 'warnings': warnings}
