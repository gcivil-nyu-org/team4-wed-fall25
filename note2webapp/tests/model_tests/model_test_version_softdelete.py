from django.test import TestCase
from django.utils import timezone
from django.contrib.auth import get_user_model
from note2webapp.models import ModelUpload, ModelVersion

User = get_user_model()


class ModelVersionSoftDeleteTests(TestCase):
    def setUp(self):
        # Create user + model upload
        self.user = User.objects.create_user(
            username="deleter", password="delete123", email="delete@example.com"
        )
        self.upload = ModelUpload.objects.create(name="Deletable Model", user=self.user)
        self.version = ModelVersion.objects.create(
            upload=self.upload,
            tag="v1.0",
            status="PASS",
            log="Initial version",
            is_active=True,
        )

    def test_soft_delete_sets_flags(self):
        """Ensure marking a version as deleted updates fields correctly."""
        # Simulate a soft delete
        self.version.is_deleted = True
        self.version.deleted_at = timezone.now()
        self.version.save()

        # Refresh from DB to verify values persisted
        version = ModelVersion.objects.get(id=self.version.id)
        self.assertTrue(version.is_deleted)
        self.assertIsNotNone(version.deleted_at)

    def test_deleted_versions_do_not_show_in_active_queryset(self):
        """Deleted versions should be excluded from active listings (if implemented)."""
        # Soft delete the version
        self.version.is_deleted = True
        self.version.deleted_at = timezone.now()
        self.version.save()

        # Create a new active version
        active_version = ModelVersion.objects.create(
            upload=self.upload, tag="v1.1", status="PASS", log="Still active"
        )

        # Assuming you have a helper queryset like ModelVersion.objects.filter(is_deleted=False)
        active_versions = ModelVersion.objects.filter(is_deleted=False)

        self.assertIn(active_version, active_versions)
        self.assertNotIn(self.version, active_versions)
