import os
import shutil
import json
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth import get_user_model
from django.conf import settings
from django.core.exceptions import ValidationError
from ..models import ModelUpload, ModelVersion

# Create a temporary directory for test media files
TEST_MEDIA_ROOT = os.path.join(settings.BASE_DIR, "test_media")

User = get_user_model()


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ModelValidationFlowTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Create test media directory
        os.makedirs(TEST_MEDIA_ROOT, exist_ok=True)

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.client.login(username="testuser", password="testpass123")

        self.upload = ModelUpload.objects.create(name="Test Model", user=self.user)

        # Valid test files
        self.valid_schema = {
            "input": {"text": "string"},
            "output": {"result": "string"},
        }

        self.valid_predict = """
        def predict(input_data):
            return {"result": "success"}
        """

        # Create a dummy model file for testing
        self.model_file = SimpleUploadedFile(
            "model.pt", b"dummy model data", content_type="application/octet-stream"
        )

        self.predict_file = SimpleUploadedFile(
            "predict.py",
            self.valid_predict.encode("utf-8"),
            content_type="text/x-python",
        )

        self.schema_file = SimpleUploadedFile(
            "schema.json",
            json.dumps(self.valid_schema).encode("utf-8"),
            content_type="application/json",
        )

    @classmethod
    def tearDownClass(cls):
        # Clean up test media directory
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)
        super().tearDownClass()

    def test_cannot_delete_model_with_versions(self):
        ModelVersion.objects.create(
            upload=self.upload,
            tag="v1.0",
            status="PASS",
            is_active=True,
            model_file=SimpleUploadedFile("model.pt", b"dummy model data"),
            predict_file=SimpleUploadedFile(
                "predict.py", self.valid_predict.encode("utf-8")
            ),
            schema_file=SimpleUploadedFile(
                "schema.json", json.dumps(self.valid_schema).encode("utf-8")
            ),
        )

        # Try to delete the model
        response = self.client.post(
            reverse("delete_model", args=[self.upload.id]),
            follow=True,  # Follow the redirect to see the message
        )

        # Check that the model still exists
        self.assertTrue(ModelUpload.objects.filter(id=self.upload.id).exists())

        # Check for the error message in the response content
        self.assertContains(response, "Cannot delete model with active versions")

    def test_validation_failure_flow(self):
        version = ModelVersion.objects.create(
            upload=self.upload,
            tag="v1.0",
            status="PENDING",
            is_active=False,
            model_file=self.model_file,
            predict_file=self.predict_file,
            schema_file=self.schema_file,
        )

        # Simulate a validation failure
        version.status = "FAIL"
        version.log = "Validation failed: Invalid model structure"
        version.save()

        # Try to activate the failed version
        from django.contrib.messages import get_messages

        response = self.client.post(
            reverse("activate_version", args=[version.id]),
            follow=True,  # Follow redirect to access messages
        )

        # Check that we were redirected
        self.assertEqual(response.status_code, 200)

        # Check for error message in the messages
        messages = list(response.context["messages"])
        self.assertTrue(
            any(
                "Cannot activate a version that is that failed validation"
                in str(message)
                for message in messages
            )
        )

        # Version should still be inactive
        version.refresh_from_db()
        self.assertFalse(version.is_active)
