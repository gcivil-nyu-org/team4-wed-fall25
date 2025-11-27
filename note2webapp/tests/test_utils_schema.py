# note2webapp/tests/test_utils_schema.py
from unittest.mock import patch
from django.test import TestCase
from note2webapp import utils
from note2webapp.models import ModelUpload, ModelVersion, User


class UtilsSchemaTests(TestCase):
    """Covers schema/dummy-value generation and safe rmtree fallbacks."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="123")
        self.upload = ModelUpload.objects.create(user=self.user, name="MyModel")
        self.version = ModelVersion.objects.create(upload=self.upload, tag="v1")

    # --- 94–95: safe delete_version_files_and_dir() ---
    def test_delete_version_files_and_dir_safe_rmtree(self):
        """Should not crash even if shutil.rmtree raises."""
        with patch("os.path.isdir", return_value=True), patch(
            "shutil.rmtree", side_effect=OSError("permission denied")
        ):
            # Should silently handle the OSError
            utils.delete_version_files_and_dir(self.version)

    # --- 118–119: safe delete_model_media_tree() ---
    def test_delete_model_media_tree_safe_rmtree(self):
        """Should not crash if shutil.rmtree raises."""
        with patch("os.path.isdir", return_value=True), patch(
            "shutil.rmtree", side_effect=OSError("permission denied")
        ):
            utils.delete_model_media_tree(self.upload)

    # --- 127–137: _make_value_from_simple_type() ---
    def test_make_value_from_simple_type_returns_expected_values(self):
        """Covers all supported type branches."""
        self.assertEqual(utils._make_value_from_simple_type("float"), 1.0)
        self.assertEqual(utils._make_value_from_simple_type("int"), 42)
        self.assertEqual(utils._make_value_from_simple_type("str"), "example")
        self.assertTrue(utils._make_value_from_simple_type("bool"))
        self.assertEqual(utils._make_value_from_simple_type("object"), {})
        self.assertIsNone(utils._make_value_from_simple_type("weird"))

    # --- 148–163: _build_from_custom_schema() ---
    def test_build_from_custom_schema_handles_nested_types(self):
        schema = {
            "input": {
                "a": "int",
                "b": {"x": "float", "y": "str"},
                "c": {},
                "d": 123,  # unsupported type
            },
            "output": {"prediction": "float"},
        }
        dummy, output = utils._build_from_custom_schema(schema)
        self.assertIn("a", dummy)
        self.assertIsInstance(dummy["a"], int)
        self.assertIn("b", dummy)
        self.assertIn("x", dummy["b"])
        self.assertIn("y", dummy["b"])
        self.assertEqual(output, {"prediction": "float"})

    # --- 180–207: _build_from_json_schema() ---
    def test_build_from_json_schema_creates_defaults(self):
        """Covers default examples and types in _build_from_json_schema()."""
        schema = {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "score": {"type": "number"},
                "age": {"type": "integer"},
                "flag": {"type": "boolean"},
                "meta": {"type": "object"},
                "items": {"type": "array"},
                "custom": "bad_type",  # not dict
            },
        }

        data, _ = utils._build_from_json_schema(schema)
        self.assertEqual(data["text"], "example text")
        self.assertEqual(data["score"], 1.0)
        self.assertEqual(data["age"], 1)
        self.assertTrue(data["flag"])
        self.assertEqual(data["meta"], {})
        self.assertEqual(data["items"], [])
        self.assertEqual(data["custom"], "example")
