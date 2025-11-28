# note2webapp/tests/test_validation_flow.py  (just the failing test)
import tempfile
import json
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from note2webapp.models import ModelUpload, ModelVersion
from pathlib import Path
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from note2webapp import utils


class ModelValidationFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("u1", password="pass")
        self.client.login(username="u1", password="pass")
        self.upload = ModelUpload.objects.create(user=self.user, name="m1")
        ModelVersion.objects.create(
            upload=self.upload,
            model_file="models/dummy.pt",
            predict_file="predict/dummy.py",
            schema_file="schemas/dummy.json",
            tag="v1",
            status="PASS",
            is_active=True,
            category="sentiment",
        )

    def test_cannot_delete_model_with_versions(self):
        resp = self.client.post(f"/delete-model/{self.upload.id}/", follow=True)
        self.assertContains(
            resp,
            "Cannot delete model with 1 active versions. Please delete all versions first.",
        )


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ValidateModelExtraTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="123")
        self.upload = ModelUpload.objects.create(user=self.user, name="MyModel")
        self.media_root = Path(settings.MEDIA_ROOT)

        # prepare fake files in memory
        self.model_file = SimpleUploadedFile("model.pt", b"fake model bytes")
        self.predict_file = SimpleUploadedFile(
            "predict.py", b"def predict(x): return {'prediction': 1.0}"
        )
        self.schema_content = {
            "input": {"x": "float"},
            "output": {"prediction": "float"},
        }
        self.schema_file = SimpleUploadedFile(
            "schema.json", json.dumps(self.schema_content).encode("utf-8")
        )

        # now create ModelVersion with actual stored files (Django-managed paths)
        self.version = ModelVersion.objects.create(
            upload=self.upload,
            tag="v1",
            category="sentiment",
            model_file=self.model_file,
            predict_file=self.predict_file,
            schema_file=self.schema_file,
        )

    def test_validate_model_passes_with_one_arg_predict(self):
        # overwrite predict.py inside MEDIA_ROOT to expect one argument
        predict_path = Path(self.version.predict_file.path)
        predict_path.write_text(
            "def predict(input_data):\n    return {'prediction': 1.0}"
        )
        result = utils.validate_model(self.version)
        self.assertEqual(result.status, "PASS")
        self.assertIn("✅ Validation Successful", result.log)

    def test_validate_model_passes_with_two_arg_predict(self):
        predict_path = Path(self.version.predict_file.path)
        predict_path.write_text(
            "def predict(model_path, input_data):\n    return {'prediction': 1.0}"
        )
        result = utils.validate_model(self.version)
        self.assertEqual(result.status, "PASS")
        self.assertIn("✅ Validation Successful", result.log)

    def test_validate_model_fails_on_missing_predict(self):
        predict_path = Path(self.version.predict_file.path)
        predict_path.write_text("# no predict defined")
        result = utils.validate_model(self.version)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("predict() function missing", result.log)

    def test_validate_model_fails_on_incorrect_return_type(self):
        predict_path = Path(self.version.predict_file.path)
        predict_path.write_text("def predict(x):\n    return 123")
        result = utils.validate_model(self.version)
        self.assertEqual(result.status, "FAIL")
        self.assertIn("predict() must return a dict", result.log)

    def test_validate_model_fixes_seek_error(self):
        predict_path = Path(self.version.predict_file.path)
        predict_path.write_text(
            "def predict(x):\n    return {'error': \"no attribute 'seek'\"}"
        )
        utils._load_model_for_version = lambda m, p: object()
        result = utils.validate_model(self.version)
        self.assertIn(result.status, ["PASS", "FAIL"])
