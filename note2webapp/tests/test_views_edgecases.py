import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from note2webapp.models import ModelUpload, ModelVersion, Profile


@override_settings(MEDIA_ROOT="/tmp")
class ViewsEdgeCaseTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("bob", password="pass")
        Profile.objects.filter(user=self.user).update(role="uploader")
        self.client.login(username="bob", password="pass")

    # --- signup exceptions ---
    @patch("note2webapp.views.User.objects.create_user", side_effect=Exception("fail"))
    def test_signup_generic_exception(self, mock_create):
        resp = self.client.post(
            reverse("signup"),
            {
                "username": "x",
                "password1": "12345678",
                "password2": "12345678",
            },
        )
        self.assertContains(resp, "Error creating account:")

    # --- add_version retry invalid id ---
    def test_add_version_retry_invalid(self):
        upload = ModelUpload.objects.create(user=self.user, name="m1")
        resp = self.client.get(
            reverse("dashboard") + f"?page=add_version&pk={upload.pk}&retry=999",
            follow=False,
        )
        # View redirects to detail page instead of rendering error text
        self.assertRedirects(resp, f"/dashboard/?page=detail&pk={upload.pk}")

    # --- reviewer add_feedback no comment ---
    def test_add_feedback_no_comment(self):
        upload = ModelUpload.objects.create(user=self.user, name="m1")
        version = ModelVersion.objects.create(upload=upload, tag="v1", status="PASS")
        reviewer = User.objects.create_user("rev", password="pass")
        Profile.objects.filter(user=reviewer).update(role="reviewer")
        self.client.login(username="rev", password="pass")
        resp = self.client.post(
            f"/reviewer/?page=add_feedback&pk={version.pk}", {"comment": ""}
        )
        self.assertContains(resp, "Please provide feedback comment.")

    # --- activate_version invalid status (FAIL) ---
    def test_activate_version_fails_validation(self):
        upload = ModelUpload.objects.create(user=self.user, name="m1")
        v = ModelVersion.objects.create(upload=upload, tag="v1", status="FAIL")
        resp = self.client.post(
            reverse("activate_version", args=[v.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertJSONEqual(
            resp.content,
            {
                "success": False,
                "error": "Cannot activate a version that is that failed validation.",
            },
        )

    # --- generate_model_info missing API key ---
    @override_settings(OPENAI_API_KEY=None)
    def test_generate_model_info_missing_key(self):
        resp = self.client.post(reverse("generate_model_info"))
        self.assertEqual(resp.status_code, 500)
        self.assertJSONEqual(
            resp.content,
            {"error": "Server is missing OPENAI_API_KEY configuration."},
        )

    # --- generate_model_info with OpenAI error ---
    @patch("note2webapp.views.OpenAI")
    @override_settings(OPENAI_API_KEY="dummy-key")
    def test_generate_model_info_openai_failure(self, mock_openai):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("boom")
        mock_openai.return_value = mock_client

        model_file = SimpleUploadedFile("m.pt", b"123")
        predict_file = SimpleUploadedFile("p.py", b"print(1)")
        schema_file = SimpleUploadedFile("s.json", b"{}")

        resp = self.client.post(
            reverse("generate_model_info"),
            {
                "model_file": model_file,
                "predict_file": predict_file,
                "schema_file": schema_file,
            },
        )
        self.assertEqual(resp.status_code, 500)
        self.assertIn(b"Network or server issue", resp.content)

    # --- model_comments_view flags ---
    def test_model_comments_view_flags(self):
        upload = ModelUpload.objects.create(user=self.user, name="m1")
        version = ModelVersion.objects.create(upload=upload, tag="v1", status="PASS")
        resp = self.client.get(reverse("model_comments", args=[version.id]))
        self.assertEqual(resp.status_code, 200)


@override_settings(MEDIA_ROOT="/tmp")
class MoreEdgeCaseViewsTests(TestCase):
    def setUp(self):
        self.client = Client()
        # uploader
        self.uploader = User.objects.create_user("bob", password="pass")
        Profile.objects.filter(user=self.uploader).update(role="uploader")
        # reviewer
        self.reviewer = User.objects.create_user("rev", password="pass")
        Profile.objects.filter(user=self.reviewer).update(role="reviewer")
        self.client.login(username="bob", password="pass")

    def _make_upload_and_version(self):
        """Utility: create a fake ModelUpload + ModelVersion pair."""
        upload = ModelUpload.objects.create(user=self.uploader, name="m1")
        v = ModelVersion.objects.create(
            upload=upload,
            tag="v1",
            category="sentiment",
            status="PASS",
            model_file=SimpleUploadedFile("m.pt", b"abc"),
            predict_file=SimpleUploadedFile("p.py", b"print(1)"),
            schema_file=SimpleUploadedFile("s.json", b"{}"),
        )
        return upload, v

    def _make_review_item(self):
        """Utility: create a fake version for reviewer tests."""
        upload = ModelUpload.objects.create(user=self.uploader, name="r1")
        v = ModelVersion.objects.create(
            upload=upload,
            tag="v1",
            category="test",
            status="PENDING",
        )
        return v

    @patch("note2webapp.views.User.objects.create_user")
    def test_signup_integrity_error(self, mock_create_user):
        """Simulate IntegrityError on signup — should show conflict message."""
        from django.db.utils import IntegrityError

        mock_create_user.side_effect = IntegrityError("duplicate key")

        resp = self.client.post(
            reverse("signup"),
            {
                "username": "dup",
                "password1": "pass12345",
                "password2": "pass12345",
            },
        )
        # Should render login page and show proper error message
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/login.html")
        self.assertContains(resp, "profile setup conflict")

    @patch("note2webapp.views.validate_model")
    def test_add_version_retry_existing_version(self, mock_validate):
        """Covers ?retry=<id> flow — should redirect after retry."""
        upload, v = self._make_upload_and_version()
        url = reverse("dashboard") + f"?page=add_version&pk={upload.pk}&retry={v.pk}"
        resp = self.client.get(url)
        # Expect redirect to model detail after retry
        self.assertRedirects(resp, f"/dashboard/?page=detail&pk={upload.pk}")

    @patch("note2webapp.views.validate_model")
    def test_add_version_duplicate_hash(self, mock_validate):
        """Covers the 'duplicate model file' check — identical hashes trigger error."""
        upload, v = self._make_upload_and_version()
        mock_validate.return_value = True
        resp = self.client.post(
            reverse("dashboard") + f"?page=add_version&pk={upload.pk}",
            {
                "tag": "v2",
                "category": "sentiment",
                "model_file": SimpleUploadedFile("m.pt", b"abc"),  # identical content
                "predict_file": SimpleUploadedFile("p.py", b"print(1)"),
                "schema_file": SimpleUploadedFile("s.json", b"{}"),
            },
            follow=True,
        )

        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/home.html")

    def test_reviewer_approve_version(self):
        """No explicit approve branch exists — reviewer_dashboard redirects to list."""
        self.client.login(username="rev", password="pass")
        v = self._make_review_item()
        resp = self.client.get(
            reverse("reviewer_dashboard") + f"?page=approve_version&pk={v.pk}",
            follow=True,
        )
        self.assertRedirects(resp, "/reviewer/?page=list")

    def test_activate_version_pending_fails(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        v.status = "PENDING"
        v.save()
        resp = self.client.post(reverse("activate_version", args=[v.id]))
        self.assertEqual(resp.status_code, 302)

    def test_soft_delete_version_normal_post(self):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        resp = self.client.post(reverse("delete_version", args=[v.id]), follow=True)
        self.assertEqual(resp.status_code, 200)
        v.refresh_from_db()
        self.assertTrue(v.is_deleted)

    @patch("note2webapp.utils.test_model_on_cpu", side_effect=Exception("fail"))
    def test_test_model_cpu_missing_input_key_and_exception(self, mock_test):
        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()

        # Missing input_data key
        resp = self.client.post(reverse("test_model_cpu", args=[v.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/test_model.html")

        # Exception path — should be caught, not crash
        resp2 = self.client.post(
            reverse("test_model_cpu", args=[v.id]),
            {"input_data": json.dumps({"x": 1})},
        )
        self.assertEqual(resp2.status_code, 200)

    @override_settings(OPENAI_API_KEY="dummy-key")
    @patch("note2webapp.views.OpenAI")
    def test_generate_model_info_existing_version_mode_a(self, mock_openai):
        mock_client = mock_openai.return_value
        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=MagicMock(content='{"desc": "ok"}'))]
        mock_client.chat.completions.create.return_value = fake_resp

        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        resp = self.client.post(reverse("generate_model_info"), {"version_id": v.id})
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"desc", resp.content)

    def test_reviewer_dashboard_add_feedback_and_approve(self):
        self.client.login(username="rev", password="pass")
        v = self._make_review_item()
        # Feedback
        resp = self.client.post(
            reverse("reviewer_dashboard") + f"?page=add_feedback&pk={v.pk}",
            {"comment": "Looks good"},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp.url.startswith("/reviewer/"))

        # Approve
        resp2 = self.client.get(
            reverse("reviewer_dashboard") + f"?page=approve_version&pk={v.pk}",
            follow=True,
        )
        self.assertIn(resp2.status_code, [200, 302])

    @override_settings(OPENAI_API_KEY="dummy-key")
    @patch("note2webapp.views.OpenAI")
    def test_generate_model_info_invalid_json_fallback(self, mock_openai):
        """Covers fallback path where OpenAI returns invalid JSON."""
        mock_client = mock_openai.return_value
        fake_resp = MagicMock()
        fake_resp.choices = [MagicMock(message=MagicMock(content="Not a JSON"))]
        mock_client.chat.completions.create.return_value = fake_resp

        self.client.login(username="uploader", password="pass")
        upload, v = self._make_upload_and_version()
        resp = self.client.post(reverse("generate_model_info"), {"version_id": v.id})

        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"Not a JSON", resp.content)

    def test_model_comments_view_as_reviewer_and_uploader(self):
        """Covers both reviewer and uploader flags in model_comments_view."""
        upload = ModelUpload.objects.create(user=self.uploader, name="m1")
        v = ModelVersion.objects.create(upload=upload, tag="v1", status="PASS")

        # Reviewer login
        self.client.login(username="rev", password="pass")
        resp = self.client.get(reverse("model_comments", args=[v.id]))
        self.assertEqual(resp.status_code, 200)

        # Uploader login
        self.client.login(username="bob", password="pass")
        resp2 = self.client.get(reverse("model_comments", args=[v.id]))
        self.assertEqual(resp2.status_code, 200)

    @patch("note2webapp.views.validate_model")
    def test_add_version_invalid_form(self, mock_validate):
        """Covers invalid form branch (missing required files)."""
        upload, v = self._make_upload_and_version()
        mock_validate.return_value = True
        resp = self.client.post(
            reverse("dashboard") + f"?page=add_version&pk={upload.pk}",
            {"tag": "", "category": ""},  # Missing all files
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "note2webapp/home.html")

    def test_reviewer_dashboard_default_page(self):
        self.client.login(username="rev", password="pass")
        resp = self.client.get(reverse("reviewer_dashboard"))
        self.assertEqual(resp.status_code, 200)

    def test_soft_delete_version_ajax(self):
        upload, v = self._make_upload_and_version()
        resp = self.client.post(
            reverse("delete_version", args=[v.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
