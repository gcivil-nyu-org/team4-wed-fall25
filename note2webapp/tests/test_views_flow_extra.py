# note2webapp/tests/test_views_flow_extra.py
import tempfile
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User

from note2webapp.models import ModelUpload, ModelVersion, Profile


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ViewsFlowExtraTests(TestCase):
    def setUp(self):
        self.client = Client()

        # uploader
        self.uploader = User.objects.create_user("uploader", password="pass")
        Profile.objects.filter(user=self.uploader).update(role="uploader")

        # reviewer
        self.reviewer = User.objects.create_user("reviewer", password="pass")
        Profile.objects.filter(user=self.reviewer).update(role="reviewer")

        # admin (superuser)
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "pass")
        # make sure admin has a profile too
        Profile.objects.get_or_create(user=self.admin, defaults={"role": "admin"})

    def _make_upload_with_version(self, owner=None):
        owner = owner or self.uploader
        upload = ModelUpload.objects.create(user=owner, name="model-one")
        v = ModelVersion.objects.create(
            upload=upload,
            model_file="models/dummy.pt",
            predict_file="predict/dummy.py",
            schema_file="schemas/dummy.json",
            tag="v1",
            status="PASS",
            is_active=True,
            category="sentiment",
        )
        return upload, v

    # ---- dashboard routing ----
    def test_dashboard_for_uploader(self):
        logged_in = self.client.login(username="uploader", password="pass")
        self.assertTrue(logged_in)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/home.html")

    def test_dashboard_for_reviewer(self):
        logged_in = self.client.login(username="reviewer", password="pass")
        self.assertTrue(logged_in)
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/reviewer.html")

    def test_dashboard_for_admin_falls_back(self):
        """
        Make sure an authenticated superuser can hit /dashboard/ without
        getting kicked to login. We force_login to avoid auth backend quirks.
        """
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("dashboard"), follow=True)
        self.assertEqual(resp.status_code, 200)

    # ---- create model (duplicate name) ----
    def test_create_model_duplicate_name_shows_error(self):
        self.client.login(username="uploader", password="pass")
        # first create
        self.client.post(
            reverse("dashboard") + "?page=create",
            {"name": "model-x"},
        )
        # second time same name -> error
        resp = self.client.post(
            reverse("dashboard") + "?page=create",
            {"name": "model-x"},
            follow=True,
        )
        self.assertContains(resp, "already exists")

    # ---- delete model with versions ----
    def test_cannot_delete_model_with_versions_message(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_with_version()
        resp = self.client.post(reverse("delete_model", args=[upload.id]), follow=True)
        self.assertContains(
            resp,
            "Cannot delete model with 1 active versions. Please delete all versions first.",
        )

    # ---- soft delete (ajax) ----
    def test_soft_delete_version_ajax(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_with_version()
        resp = self.client.post(
            reverse("delete_version", args=[v.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertJSONEqual(
            resp.content,
            {
                "success": True,
                "message": f"Version (Tag: {v.tag}) deleted successfully",
                "reload": True,
            },
        )
        v.refresh_from_db()
        self.assertTrue(v.is_deleted)

    # ---- activate version: cannot activate deleted ----
    def test_activate_deleted_version_fails(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_with_version()
        v.is_deleted = True
        v.save()

        resp = self.client.post(
            reverse("activate_version", args=[v.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 400)
        self.assertJSONEqual(
            resp.content,
            {"success": False, "error": "Cannot activate a deleted version."},
        )

    # ---- deprecate version ----
    def test_deprecate_version_ok(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_with_version()
        resp = self.client.post(reverse("deprecate_version", args=[v.id]))
        self.assertEqual(resp.status_code, 302)
        v.refresh_from_db()
        self.assertFalse(v.is_active)

    # ---- run_model_from_path input validation ----
    def test_run_model_from_path_requires_post(self):
        self.client.login(username="uploader", password="pass")
        resp = self.client.get(reverse("run_model_from_path"))
        self.assertEqual(resp.status_code, 405)

    def test_run_model_from_path_bad_json(self):
        self.client.login(username="uploader", password="pass")
        resp = self.client.post(
            reverse("run_model_from_path"),
            {
                "model_path": "/tmp/model.pt",
                "predict_path": "/tmp/predict.py",
                "input_data": "{not-json",
            },
        )
        self.assertEqual(resp.status_code, 400)
        self.assertJSONEqual(resp.content, {"error": "Invalid JSON in input_data"})

    # ---- run_model_by_version_id post only ----
    def test_run_model_by_version_requires_post(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_with_version()
        resp = self.client.get(reverse("run_model_by_version_id", args=[v.id]))
        self.assertEqual(resp.status_code, 405)
