from django.test import TestCase
from django.contrib.auth import get_user_model
from note2webapp.models import ModelUpload, ModelVersion

User = get_user_model()


class ModelUploadTests(TestCase):
    """Tests for ModelUpload model."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.upload = ModelUpload.objects.create(name="VisionNet", user=self.user)

    def test_upload_creation(self):
        """Test that a model upload can be created successfully."""
        self.assertEqual(self.upload.name, "VisionNet")
        self.assertEqual(self.upload.user.username, "testuser")

    def test_upload_str_representation(self):
        """Ensure __str__ returns readable name."""
        self.assertEqual(str(self.upload), "VisionNet")

    def test_upload_can_have_multiple_versions(self):
        """Ensure multiple versions can be linked to one upload."""
        v1 = ModelVersion.objects.create(upload=self.upload, tag="v1.0")
        v2 = ModelVersion.objects.create(upload=self.upload, tag="v2.0")
        versions = ModelVersion.objects.filter(upload=self.upload)
        self.assertEqual(versions.count(), 2)
        self.assertIn(v1, versions)
        self.assertIn(v2, versions)

    def test_deleting_upload_deletes_versions(self):
        """Deleting a ModelUpload cascades delete to ModelVersions."""
        version = ModelVersion.objects.create(upload=self.upload, tag="v1.0")
        self.upload.delete()
        self.assertFalse(ModelVersion.objects.filter(id=version.id).exists())
