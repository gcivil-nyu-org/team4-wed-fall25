from django.test import TestCase
from django.contrib.auth import get_user_model
from django.utils import timezone
from note2webapp.models import ModelUpload, ModelVersion

User = get_user_model()


class ModelVersionTimestampTests(TestCase):
    """Tests that validate version creation and timestamp behavior."""

    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.upload = ModelUpload.objects.create(name="Test Model", user=self.user)

    def test_new_version_appears_immediately(self):
        """Check that when a new version is created, it appears in the queryset right away."""
        initial_count = ModelVersion.objects.count()
        ModelVersion.objects.create(upload=self.upload, tag="v3.0", log="Iteration 3")
        self.assertEqual(ModelVersion.objects.count(), initial_count + 1)

    def test_version_has_timestamp_and_notes(self):
        """Ensure a version has a timestamp and notes (log)."""
        version = ModelVersion.objects.create(
            upload=self.upload,
            tag="v1.1",
            log="Added dropout layer",
            created_at=timezone.now(),
        )
        self.assertIn("dropout", version.log)
        self.assertIsNotNone(version.created_at)
