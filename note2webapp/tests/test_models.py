from django.test import TestCase
from django.contrib.auth import get_user_model
from ..models import ModelUpload, ModelVersion

User = get_user_model()


class ModelVersionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.upload = ModelUpload.objects.create(name="Test Model", user=self.user)

    def test_version_creation(self):
        version = ModelVersion.objects.create(
            upload=self.upload,
            tag="v1.0",
            status="PASS",
            log="Test log",
            is_active=True,
        )
        self.assertEqual(str(version), "Test Model - v1 (PASS)")
        self.assertTrue(version.is_active)
        self.assertEqual(version.upload, self.upload)

    def test_version_ordering(self):
        v1 = ModelVersion.objects.create(upload=self.upload, tag="v1.0")
        v2 = ModelVersion.objects.create(upload=self.upload, tag="v2.0")

        versions = list(ModelVersion.objects.all())
        self.assertEqual(versions, [v2, v1])  # Newest first
