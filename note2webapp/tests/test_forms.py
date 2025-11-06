from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from note2webapp.forms import VersionForm


class VersionFormTests(TestCase):
    """Covers all clean() and clean_<field>() logic in VersionForm."""

    def setUp(self):
        self.valid_files = {
            "model_file": SimpleUploadedFile("model.pt", b"dummy model content"),
            "predict_file": SimpleUploadedFile("predict.py", b"print('ok')"),
            "schema_file": SimpleUploadedFile("schema.json", b"{}"),
            "tag": "v1.0",
            "category": "research",
            "information": "This is a valid model upload test.",
        }

    def test_valid_form_passes(self):
        form = VersionForm(data=self.valid_files, files=self.valid_files)
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_model_file_raises_error(self):
        data = self.valid_files.copy()
        data.pop("model_file")
        form = VersionForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn("Model file (.pt) is required", str(form.errors))

    def test_missing_predict_file_raises_error(self):
        """Provide model_file but omit predict_file."""
        data = self.valid_files.copy()
        data.pop("predict_file")
        files = {"model_file": self.valid_files["model_file"]}
        form = VersionForm(data=data, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("Predict file (.py) is required", str(form.errors))

    def test_missing_schema_file_raises_error(self):
        """Provide model_file and predict_file but omit schema_file."""
        data = self.valid_files.copy()
        data.pop("schema_file")
        files = {
            "model_file": self.valid_files["model_file"],
            "predict_file": self.valid_files["predict_file"],
        }
        form = VersionForm(data=data, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("Schema file (.json) is required", str(form.errors))

    def test_missing_information_raises_error(self):
        data = self.valid_files.copy()
        data["information"] = "   "
        form = VersionForm(data=data, files=self.valid_files)
        self.assertFalse(form.is_valid())
        self.assertIn("Model Information is required", str(form.errors))

    def test_invalid_model_file_extension(self):
        files = self.valid_files.copy()
        files["model_file"] = SimpleUploadedFile("bad.txt", b"fake")
        form = VersionForm(data=files, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("Only .pt files are allowed", str(form.errors))

    def test_invalid_predict_file_extension(self):
        files = self.valid_files.copy()
        files["predict_file"] = SimpleUploadedFile("badfile.txt", b"fake")
        form = VersionForm(data=files, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("Only .py files are allowed", str(form.errors))

    def test_invalid_schema_file_extension(self):
        files = self.valid_files.copy()
        files["schema_file"] = SimpleUploadedFile("badfile.txt", b"fake")
        form = VersionForm(data=files, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("Only .json files allowed", str(form.errors))

    def test_missing_tag_triggers_builtin_error(self):
        """Tag missing triggers Django's built-in required validation."""
        files = self.valid_files.copy()
        files["tag"] = ""
        form = VersionForm(data=files, files=files)
        self.assertFalse(form.is_valid())
        self.assertIn("This field is required", str(form.errors))

    def test_clean_tag_valid_path(self):
        """Ensure valid tag value passes through clean_tag() and returns correctly."""
        files = self.valid_files.copy()
        files["tag"] = "v2.0"
        form = VersionForm(data=files, files=files)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.clean_tag(), "v2.0")
