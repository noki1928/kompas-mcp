import unittest
from unittest.mock import Mock

from cad3d import validate_profiles
from kompas import Kompas


class ThreeDTests(unittest.TestCase):
    def test_empty_profile(self):
        with self.assertRaises(ValueError):
            validate_profiles([], [], [])

    def test_invalid_profiles(self):
        for args in (([[0, 0, -1, 2]], [], []), ([], [[0, 0, 0]], []),
                     ([], [], [[[0, 0], [1, 1], [2, 2]]]),
                     ([], [], [[[0, 0], [1, 0], [1, 0]]])):
            with self.assertRaises(ValueError):
                validate_profiles(*args)

    def test_closed_polygon_normalization(self):
        _, _, polygons = validate_profiles([], [], [[[0, 0], [2, 0], [0, 2], [0, 0]]])
        self.assertEqual(len(polygons[0]), 3)

    def test_invalid_depth_precedes_com(self):
        for depth in (0, -1, float("inf")):
            with self.assertRaises(ValueError):
                Kompas().extrusion3d("unknown", depth)

    def test_wrong_document_handle(self):
        k = Kompas()
        k.active = Mock(return_value=Mock(Reference=20))
        k._entities3d = {"id": (10, Mock(), "sketch")}
        with self.assertRaises(ValueError):
            k._entity3d("id", "sketch")

    def test_wrong_handle_kind(self):
        k = Kompas()
        k.active = Mock(return_value=Mock(Reference=10))
        k._entities3d = {"id": (10, Mock(), "feature")}
        with self.assertRaises(ValueError):
            k._entity3d("id", "sketch")

    def test_closed_entity(self):
        k = Kompas()
        k.active = Mock(return_value=Mock(Reference=10))
        entity = Mock()
        entity.IsCreated.return_value = False
        k._entities3d = {"id": (10, entity, "sketch")}
        with self.assertRaises(ValueError):
            k._entity3d("id", "sketch")
