# note2webapp/tests/test_admin_stats.py
import tempfile
from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.urls import reverse

from note2webapp.models import ModelUpload, ModelVersion, Profile


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AdminStatsViewTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="adminpass"
        )
        # a normal user with a profile
        self.uploader = User.objects.create_user(
            username="u1", password="u1pass"
        )
        Profile.objects.filter(user=self.uploader).update(role="uploader")

        # create a model and a version so the stats page has data
        upload = ModelUpload.objects.create(user=self.uploader, name="model-1")
        ModelVersion.objects.create(
            upload=upload,
            model_file="models/dummy.pt",
            predict_file="predict/dummy.py",
            schema_file="schemas/dummy.json",
            tag="v1",
            status="PASS",
            is_active=True,
            category="sentiment",
        )

    def test_staff_can_see_stats(self):
        self.client.login(username="admin", password="adminpass")
        resp = self.client.get(reverse("admin_stats"))
        self.assertEqual(resp.status_code, 200)
        # a couple of key context vars
        self.assertIn("total_uploads", resp.context)
        self.assertIn("total_versions", resp.context)
        self.assertIn("role_counts_json", resp.context)

    def test_non_staff_redirected(self):
        self.client.login(username="u1", password="u1pass")
        resp = self.client.get(reverse("admin_stats"))
        # staff_member_required -> 302 to admin login
        self.assertEqual(resp.status_code, 302)
