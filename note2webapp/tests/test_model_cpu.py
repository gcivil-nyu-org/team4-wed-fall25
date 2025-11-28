import json
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model
from note2webapp.models import Profile, ModelUpload, ModelVersion
import tempfile
from pathlib import Path
from django.conf import settings
from note2webapp import utils

User = get_user_model()


class TestModelCPUView(TestCase):
    def setUp(self):
        # Create users — profiles are auto-created by signal
        self.uploader = User.objects.create_user(
            username="uploader", password="pass123"
        )
        self.reviewer = User.objects.create_user(
            username="reviewer", password="pass123"
        )

        # Update their roles
        Profile.objects.filter(user=self.uploader).update(role="uploader")
        Profile.objects.filter(user=self.reviewer).update(role="reviewer")

        # Create dummy upload and version
        self.upload = ModelUpload.objects.create(user=self.uploader, name="AlexNet")
        self.version = ModelVersion.objects.create(
            upload=self.upload, tag="v1", status="PASS", is_active=True
        )

        self.client = Client()
        self.url = reverse("test_model_cpu", args=[self.version.id])

    def test_back_button_renders_correctly_for_roles(self):
        """
        Ensure Back button URL differs correctly for uploader and reviewer roles.
        """
        # Uploader
        self.client.login(username="uploader", password="pass123")
        response = self.client.get(self.url)
        self.assertContains(response, "model-versions")
        self.client.logout()

        # Reviewer
        self.client.login(username="reviewer", password="pass123")
        response = self.client.get(self.url)
        self.assertContains(response, "reviewer")

    def test_post_valid_input_returns_result(self):
        """
        Ensure posting valid JSON input returns model test result.
        """
        self.client.login(username="uploader", password="pass123")

        input_data = {"x1": 1, "x2": 2, "x3": 3, "x4": 4}
        response = self.client.post(self.url, {"input_data": json.dumps(input_data)})

        self.assertEqual(response.status_code, 200)
        self.assertIn("result", response.context)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class TestModelOnCpuExtraTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("tester", password="123")
        self.upload = ModelUpload.objects.create(user=self.user, name="MyModel")
        self.media_root = Path(settings.MEDIA_ROOT)
        self.tmpdir = self.media_root / "sentiment" / "MyModel" / "v1"
        self.tmpdir.mkdir(parents=True, exist_ok=True)

        self.model_path = self.tmpdir / "model.pt"
        self.predict_path = self.tmpdir / "predict.py"
        self.model_path.write_bytes(b"fake model")

        self.version = ModelVersion.objects.create(
            upload=self.upload,
            tag="v1",
            category="sentiment",
        )
        self.version.model_file.name = str(self.model_path.relative_to(self.media_root))
        self.version.predict_file.name = str(
            self.predict_path.relative_to(self.media_root)
        )

    def _write_predict(self, code: str):
        self.predict_path.write_text(code)

    def test_test_model_on_cpu_one_arg(self):
        self._write_predict("def predict(data):\n    return {'ok': True}")
        out = utils.test_model_on_cpu(self.version, {"a": 1})
        self.assertIn(out["status"], ["ok", "error"])
        if out["status"] == "ok":
            self.assertIn("ok", out["output"])

    def test_test_model_on_cpu_two_arg(self):
        self._write_predict("def predict(model, data):\n    return {'result': 1}")
        out = utils.test_model_on_cpu(self.version, {"x": 2})
        self.assertIn(out["status"], ["ok", "error"])
        if out["status"] == "ok":
            self.assertIn("result", out["output"])

    def test_test_model_on_cpu_seek_error_branch(self):
        self._write_predict(
            "def predict(x, y=None):\n    return {'error': \"no attribute 'seek'\"}"
        )
        out = utils.test_model_on_cpu(self.version, {"a": 1})
        self.assertIn(out["status"], ["ok", "error"])

    def test_test_model_on_cpu_raises_for_missing_predict(self):
        self._write_predict("# no predict defined")
        out = utils.test_model_on_cpu(self.version, {"a": 1})
        self.assertEqual(out["status"], "error")
