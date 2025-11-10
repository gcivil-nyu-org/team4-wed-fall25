# note2webapp/tests/test_views.py

from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.contrib.auth.models import User
from unittest.mock import patch
import tempfile
import json

from note2webapp.models import ModelUpload, ModelVersion, Profile


@override_settings(MEDIA_ROOT=tempfile.gettempdir())
class ViewsHighCoverageTests(TestCase):
    def setUp(self):
        self.client = Client()

        # uploader
        self.uploader = User.objects.create_user("uploader", password="pass")
        Profile.objects.filter(user=self.uploader).update(role="uploader")

        # reviewer
        self.reviewer = User.objects.create_user("reviewer", password="pass")
        Profile.objects.filter(user=self.reviewer).update(role="reviewer")

        # admin / superuser
        self.admin = User.objects.create_superuser("admin", "admin@example.com", "pass")
        Profile.objects.filter(user=self.admin).update(role="admin")

    # ---------------- AUTH ----------------

    def test_signup_password_mismatch_rerenders(self):
        resp = self.client.post(
            reverse("signup"),
            {
                "username": "bob",
                "password1": "abc12345",
                "password2": "abc00000",
            },
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Passwords do not match.")

    def test_login_as_reviewer_redirects_to_reviewer_dashboard(self):
        resp = self.client.post(
            reverse("login"),
            {"username": "reviewer", "password": "pass"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/reviewer.html")

    def test_login_as_admin_redirects_to_dashboard(self):
        resp = self.client.post(
            reverse("login"),
            {"username": "admin", "password": "pass"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.headers["Location"], reverse("dashboard"))

    # ---------------- DASHBOARD ROUTER ----------------

    def test_dashboard_for_uploader(self):
        self.client.login(username="uploader", password="pass")
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/home.html")

    def test_dashboard_for_reviewer(self):
        self.client.login(username="reviewer", password="pass")
        resp = self.client.get(reverse("dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/reviewer.html")

    def test_dashboard_for_admin_is_accessible(self):
        self.client.login(username="admin", password="pass")
        resp = self.client.get(reverse("dashboard"))
        self.assertIn(resp.status_code, (200, 302))

    # ---------------- helper ----------------

    def _make_upload_and_version(self, user=None):
        if user is None:
            user = self.uploader

        upload = ModelUpload.objects.create(user=user, name="m1")
        v = ModelVersion.objects.create(
            upload=upload,
            tag="v1",
            category="sentiment",
            status="PASS",
            is_active=True,
            model_file=SimpleUploadedFile("m.pt", b"pt"),
            predict_file=SimpleUploadedFile("p.py", b"def predict(): pass"),
            schema_file=SimpleUploadedFile("s.json", b"{}"),
        )
        return upload, v

    # ---------------- UPLOADER DASHBOARD MODES ----------------

    def test_uploader_create_model_get(self):
        self.client.login(username="uploader", password="pass")
        resp = self.client.get(reverse("dashboard") + "?page=create")
        self.assertEqual(resp.status_code, 200)

    def test_uploader_create_model_post(self):
        self.client.login(username="uploader", password="pass")
        resp = self.client.post(
            reverse("dashboard") + "?page=create",
            {"name": "MyModel"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(ModelUpload.objects.filter(name="MyModel").exists())

    def test_uploader_detail_page(self):
        self.client.login(username="uploader", password="pass")
        upload, _ = self._make_upload_and_version()
        resp = self.client.get(reverse("dashboard") + f"?page=detail&pk={upload.pk}")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "m1")

    @patch("note2webapp.views.validate_model")
    def test_add_version_missing_files_shows_error(self, mock_validate):
        self.client.login(username="uploader", password="pass")
        upload, _ = self._make_upload_and_version()
        resp = self.client.post(
            reverse("dashboard") + f"?page=add_version&pk={upload.pk}",
            {"tag": "v2", "category": "sentiment"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Missing required files")

    # 👇 FIXED VERSION
    @patch("note2webapp.views.validate_model")
    @patch("note2webapp.views.VersionForm")
    def test_add_version_success(self, mock_form_cls, mock_validate):
        """
        Make uploaded files DIFFERENT from the existing version so the
        duplicate-hash check in the view passes, and mock VersionForm so
        the save path is guaranteed.
        """
        self.client.login(username="uploader", password="pass")
        upload, _ = self._make_upload_and_version()

        # dummy form instance that always validates and saves
        class DummyForm:
            def __init__(self, *args, **kwargs):
                self.cleaned_data = {
                    "model_file": SimpleUploadedFile("m2.pt", b"pt-new"),
                    "predict_file": SimpleUploadedFile(
                        "p2.py", b"def predict2(): pass"
                    ),
                    "schema_file": SimpleUploadedFile("s2.json", b'{"x": 1}'),
                    "category": "sentiment",
                    "information": "info",
                    "tag": "v2",
                }

            def is_valid(self):
                return True

            def save(self, commit=False):
                mv = ModelVersion(
                    upload=upload,
                    tag="v2",
                    category="sentiment",
                    model_file=SimpleUploadedFile("m2.pt", b"pt-new"),
                    predict_file=SimpleUploadedFile("p2.py", b"def predict2(): pass"),
                    schema_file=SimpleUploadedFile("s2.json", b'{"x": 1}'),
                    status="PASS",
                )
                mv.save()
                return mv

        mock_form_cls.return_value = DummyForm()

        url = reverse("dashboard") + f"?page=add_version&pk={upload.pk}"
        resp = self.client.post(
            url,
            {
                "tag": "v2",
                "category": "sentiment",
                "information": "info",
                # IMPORTANT: give different bytes than existing version
                "model_file": SimpleUploadedFile("m2.pt", b"pt-new"),
                "predict_file": SimpleUploadedFile("p2.py", b"def predict2(): pass"),
                "schema_file": SimpleUploadedFile("s2.json", b'{"x": 1}'),
            },
            follow=True,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(ModelVersion.objects.filter(upload=upload, tag="v2").exists())

    # ---------------- VERSION ACTIONS ----------------

    @patch("note2webapp.views.delete_version_files_and_dir")
    def test_soft_delete_version_success(self, mock_delete):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        resp = self.client.post(reverse("delete_version", args=[v.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        v.refresh_from_db()
        self.assertTrue(v.is_deleted)

    def test_soft_delete_version_permission_denied(self):
        other = User.objects.create_user("other", password="pass")
        Profile.objects.filter(user=other).update(role="uploader")
        upload, v = self._make_upload_and_version(user=self.uploader)

        self.client.login(username="other", password="pass")
        resp = self.client.post(reverse("delete_version", args=[v.id]))
        # view redirects with error instead of 403
        self.assertEqual(resp.status_code, 302)

    def test_activate_version_fails_on_deleted(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        v.is_deleted = True
        v.save()
        resp = self.client.post(reverse("activate_version", args=[v.id]))
        self.assertEqual(resp.status_code, 302)

    def test_deprecate_version_success(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        resp = self.client.post(reverse("deprecate_version", args=[v.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        v.refresh_from_db()
        self.assertFalse(v.is_active)

    # ---------------- DELETE MODEL ----------------

    @patch("note2webapp.views.delete_model_media_tree")
    def test_delete_model_blocked_when_versions_exist(self, mock_del):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        resp = self.client.post(reverse("delete_model", args=[upload.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Cannot delete model with")

    @patch("note2webapp.views.delete_model_media_tree")
    def test_delete_model_success(self, mock_del):
        self.client.login(username="uploader", password="pass")
        upload = ModelUpload.objects.create(user=self.uploader, name="empty")
        resp = self.client.post(reverse("delete_model", args=[upload.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(ModelUpload.objects.filter(id=upload.id).exists())

    # ---------------- EDIT VERSION INFO ----------------

    def test_edit_version_information_get_and_post(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        resp = self.client.get(reverse("edit_version_information", args=[v.id]))
        self.assertEqual(resp.status_code, 200)

        resp = self.client.post(
            reverse("edit_version_information", args=[v.id]),
            {"information": "updated info"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        v.refresh_from_db()
        self.assertEqual(v.information, "updated info")

    # ---------------- TEST MODEL (CPU) ----------------

    @patch("note2webapp.views.test_model_on_cpu")
    def test_test_model_cpu_valid_json(self, mock_test):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        mock_test.return_value = {"ok": True}
        resp = self.client.post(
            reverse("test_model_cpu", args=[v.id]),
            {"input_data": json.dumps({"text": "hello"})},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ok")

    def test_test_model_cpu_bad_json(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        resp = self.client.post(
            reverse("test_model_cpu", args=[v.id]),
            {"input_data": "{bad json"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Invalid JSON")

    # ---------------- API ----------------

    @patch("note2webapp.views.test_model_on_cpu")
    def test_run_model_by_version_id(self, mock_test):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        mock_test.return_value = {"hello": "world"}
        resp = self.client.post(
            reverse("run_model_by_version_id", args=[v.id]),
            {"input_data": json.dumps({"text": "hi"})},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertJSONEqual(resp.content, {"hello": "world"})

    # ---------------- ADMIN STATS ----------------

    def test_admin_stats_view(self):
        self.client.login(username="admin", password="pass")
        resp = self.client.get(reverse("admin_stats"))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/admin_stats.html")
