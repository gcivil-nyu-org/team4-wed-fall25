import os
import json
import tempfile
from django.test import TestCase
from note2webapp.utils import generate_dummy_input

class TestGenerateDummyInput(TestCase):

    def test_valid_schema_generates_expected_input(self):
        schema = {
            "input": {
                "x1": "float",
                "x2": "int",
                "x3": "str",
                "x4": "bool"
            },
            "output": {
                "prediction": "float"
            }
        }
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tmp:
            json.dump(schema, tmp)
            tmp_path = tmp.name

        dummy_input, expected_output = generate_dummy_input(tmp_path)

        self.assertEqual(dummy_input, {
            "x1": 1.0,
            "x2": 42,
            "x3": "example",
            "x4": True
        })
        self.assertEqual(expected_output, {"prediction": "float"})

        os.remove(tmp_path)

    def test_invalid_schema_raises_value_error(self):
        schema = {
            "input": {
                "foo": "list"  # unsupported type
            }
        }
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tmp:
            json.dump(schema, tmp)
            tmp_path = tmp.name

        with self.assertRaises(ValueError) as ctx:
            generate_dummy_input(tmp_path)

        self.assertIn("Unsupported type", str(ctx.exception))
        os.remove(tmp_path)

    def test_empty_schema_returns_empty_dicts(self):
        schema = {}
        with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False) as tmp:
            json.dump(schema, tmp)
            tmp_path = tmp.name

        dummy_input, expected_output = generate_dummy_input(tmp_path)

        self.assertEqual(dummy_input, {})
        self.assertEqual(expected_output, {})
        os.remove(tmp_path)
