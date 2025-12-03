# note2webapp/tests/test_utils_schema.py
from unittest.mock import patch
from django.test import TestCase
from note2webapp import utils
from note2webapp.models import ModelUpload, ModelVersion, User
import tempfile
import json
from pathlib import Path


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


class UtilsSchemaExtraTests(TestCase):
    def test_build_from_custom_schema_nested_none(self):
        schema = {
            "input": {"outer": {"a": "float", "b": 123}},
            "output": {"res": "int"},
        }
        dummy, output = utils._build_from_custom_schema(schema)
        self.assertIn("outer", dummy)
        self.assertIn("a", dummy["outer"])
        self.assertIn("b", dummy["outer"])
        self.assertIsNone(dummy["outer"]["b"])
        self.assertEqual(output, {"res": "int"})

    def test_build_from_json_schema_uses_example_and_handles_non_dict(self):
        schema = {
            "type": "object",
            "properties": {
                "a": {"example": "explicit value"},
                "b": "notadict",
            },
        }
        data, _ = utils._build_from_json_schema(schema)
        self.assertEqual(data["a"], "explicit value")
        self.assertEqual(data["b"], "example")

    def test_generate_input_and_output_schema_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            wrapped = {"input": {"text": "str"}, "output": {"prediction": "float"}}
            p1 = tmp_path / "wrapped.json"
            p1.write_text(json.dumps(wrapped))
            input_data, output_schema = utils.generate_input_and_output_schema(str(p1))
            self.assertIn("text", input_data)
            self.assertEqual(output_schema, {"prediction": "float"})

            json_schema = {
                "type": "object",
                "properties": {"foo": {"type": "string"}},
            }
            p2 = tmp_path / "direct.json"
            p2.write_text(json.dumps(json_schema))
            input_data, output_schema = utils.generate_input_and_output_schema(str(p2))
            self.assertEqual(input_data["foo"], "example text")
            self.assertIsNone(output_schema)

            fallback = {"something": "else"}
            p3 = tmp_path / "fallback.json"
            p3.write_text(json.dumps(fallback))
            input_data, output_schema = utils.generate_input_and_output_schema(str(p3))
            self.assertEqual(input_data, {})
            self.assertIsNone(output_schema)

    def test_is_seek_error_detects_and_rejects(self):
        err_out = {"error": "no attribute 'seek' in dict()"}
        self.assertTrue(utils._is_seek_error(err_out))
        self.assertFalse(utils._is_seek_error({"error": "some other error"}))
        self.assertFalse(utils._is_seek_error({"wrongkey": "no attribute 'seek'"}))
        self.assertFalse(utils._is_seek_error("notadict"))
