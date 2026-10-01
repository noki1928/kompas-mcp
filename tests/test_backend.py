import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from kompas import Kompas, number, output_path, reference


class BackendTests(unittest.TestCase):
    def test_finite_numbers(self):
        for invalid in (float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                number(invalid)
        with self.assertRaises(ValueError):
            number(0, positive=True)

    def test_zero_reference_is_failure(self):
        with self.assertRaises(RuntimeError):
            reference(0)
        self.assertEqual(reference(42), 42)

    def test_overwrite_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "test.frw"
            path.write_text("existing")
            with self.assertRaises(FileExistsError):
                output_path(str(path))
            self.assertEqual(output_path(str(path), True), path.resolve())

    def test_no_active_document(self):
        k = Kompas()
        k.app7 = Mock(ActiveDocument=None)
        with self.assertRaises(RuntimeError):
            k.doc2d()

    def test_wrong_document_type(self):
        k = Kompas()
        k.app7 = Mock(ActiveDocument=Mock(DocumentType=4))
        with self.assertRaises(RuntimeError):
            k.doc2d()

    def test_script_disabled(self):
        with patch.dict(os.environ, {"KOMPAS_ALLOW_SCRIPTS": "0"}):
            with self.assertRaises(PermissionError):
                Kompas().execute_python_script("result=1")

    def test_rectangle_segments(self):
        k = Kompas()
        k.line = Mock(side_effect=[{"reference": i} for i in range(1, 5)])
        result = k.rectangle(10, 20, 100, 50)
        self.assertEqual(result["references"], [1, 2, 3, 4])
        self.assertEqual(k.line.call_args_list[-1].args, (10, 70, 10, 20, 1))

    def test_invalid_polyline_creates_nothing(self):
        k = Kompas()
        k.line = Mock()
        with self.assertRaises(ValueError):
            k.polyline([[1, 2], [1, 2]])
        k.line.assert_not_called()

    def test_polyline_rollback(self):
        k = Kompas()
        k.line = Mock(side_effect=[{"reference": 7}, RuntimeError("failed")])
        d = Mock()
        k.doc2d = Mock(return_value=d)
        with self.assertRaises(RuntimeError):
            k.polyline([[0, 0], [1, 1], [2, 2]])
        d.ksDeleteObj.assert_called_once_with(7)


if __name__ == "__main__":
    unittest.main()
