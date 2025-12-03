from unittest.mock import patch
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.urls import resolve

from note2webapp.models import ModelUpload, ModelVersion, Profile
from note2webapp.admin import admin_site, ModelUploadAdmin, ModelVersionAdmin


class AdminTests(TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_superuser(
            username="admin", email="admin@example.com", password="pass"
        )
        Profile.objects.filter(user=self.user).update(role="admin")
        self.request = self.factory.get("/")
        self.request.user = self.user

    # ------------------------------------------------------------------
    # CustomAdminSite.get_urls()
    # ------------------------------------------------------------------
    def test_custom_admin_url_includes_stats(self):
        """Covers CustomAdminSite.get_urls (28–30)."""
        urls = admin_site.get_urls()
        names = [u.name for u in urls if hasattr(u, "name") and u.name]
        self.assertIn("admin_stats", names)

        match = resolve("/admin/stats/")
        self.assertEqual(match.url_name, "admin_stats")

    # ------------------------------------------------------------------
    # ModelUploadAdmin.delete_model / delete_queryset
    # ------------------------------------------------------------------
    @patch("note2webapp.admin.delete_model_media_tree")
    def test_modelupload_delete_model_calls_cleanup(self, mock_delete):
        """Covers ModelUploadAdmin.delete_model (67–68)."""
        obj = ModelUpload.objects.create(user=self.user, name="temp_model")
        ma = ModelUploadAdmin(ModelUpload, admin_site)
        ma.delete_model(self.request, obj)
        mock_delete.assert_called_once_with(obj)

    @patch("note2webapp.admin.delete_model_media_tree")
    def test_modelupload_delete_queryset_calls_cleanup(self, mock_delete):
        """Covers ModelUploadAdmin.delete_queryset (72–74)."""
        # create real queryset so Django's super().delete_queryset works
        objs = [
            ModelUpload.objects.create(user=self.user, name="a"),
            ModelUpload.objects.create(user=self.user, name="b"),
        ]
        queryset = ModelUpload.objects.filter(id__in=[o.id for o in objs])
        ma = ModelUploadAdmin(ModelUpload, admin_site)
        ma.delete_queryset(self.request, queryset)
        self.assertEqual(mock_delete.call_count, len(objs))

    # ------------------------------------------------------------------
    # ModelVersionAdmin.delete_model / delete_queryset
    # ------------------------------------------------------------------
    @patch("note2webapp.admin.delete_version_files_and_dir")
    def test_modelversion_delete_model_calls_cleanup(self, mock_delete):
        """Covers ModelVersionAdmin.delete_model (97–98)."""
        upload = ModelUpload.objects.create(user=self.user, name="m1")
        mv_obj = ModelVersion.objects.create(
            upload=upload,
            tag="v1",
            model_file="dummy.pt",
            predict_file="p.py",
            schema_file="s.json",
        )
        admin_inst = ModelVersionAdmin(ModelVersion, admin_site)
        admin_inst.delete_model(self.request, mv_obj)
        mock_delete.assert_called_once_with(mv_obj)

    @patch("note2webapp.admin.delete_version_files_and_dir")
    def test_modelversion_delete_queryset_calls_cleanup(self, mock_delete):
        """Covers ModelVersionAdmin.delete_queryset (101–103)."""
        upload = ModelUpload.objects.create(user=self.user, name="m1")
        mv_objs = [
            ModelVersion.objects.create(
                upload=upload,
                tag="v1",
                model_file="m.pt",
                predict_file="p.py",
                schema_file="s.json",
            ),
            ModelVersion.objects.create(
                upload=upload,
                tag="v2",
                model_file="m2.pt",
                predict_file="p2.py",
                schema_file="s2.json",
            ),
        ]
        queryset = ModelVersion.objects.filter(id__in=[o.id for o in mv_objs])
        mv_admin = ModelVersionAdmin(ModelVersion, admin_site)
        mv_admin.delete_queryset(self.request, queryset)
        self.assertEqual(mock_delete.call_count, len(mv_objs))

    # ------------------------------------------------------------------
    # CustomAdminSite.index()
    # ------------------------------------------------------------------
    def test_index_adds_show_stats_button_to_context(self):
        """Covers CustomAdminSite.index (lines 28–30)."""
        request = self.factory.get("/admin/")
        request.user = self.user

        response = admin_site.index(request)

        # Confirm response is a TemplateResponse
        from django.template.response import TemplateResponse

        self.assertIsInstance(response, TemplateResponse)

        # Validate extra_context contains the flag
        context = response.context_data
        self.assertIn("show_stats_button", context)
        self.assertTrue(context["show_stats_button"])
