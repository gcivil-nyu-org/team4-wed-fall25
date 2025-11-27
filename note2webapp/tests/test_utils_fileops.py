import os
import tempfile
import hashlib
from pathlib import Path
from unittest.mock import patch
from django.conf import settings
from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from note2webapp.utils import (
    sha256_uploaded_file,
    sha256_file_path,
    materialize_version_to_media,
    delete_version_files_and_dir,
    delete_model_media_tree,
)
from note2webapp.models import ModelUpload, ModelVersion, User


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class FileOpsTests(TestCase):
    """Covers file hashing, creation, materialization, and deletion utilities."""

    def setUp(self):
        self.user = User.objects.create_user("tester", password="123")
        self.upload = ModelUpload.objects.create(user=self.user, name="MyModel")

        # Django stores files automatically inside MEDIA_ROOT
        self.model_file = SimpleUploadedFile("m.pt", b"torchmodel")
        self.predict_file = SimpleUploadedFile("p.py", b"def predict(): return 1")
        self.schema_file = SimpleUploadedFile("s.json", b"{}")

        self.version = ModelVersion.objects.create(
            upload=self.upload,
            tag="v1",
            category="sentiment",
            model_file=self.model_file,
            predict_file=self.predict_file,
            schema_file=self.schema_file,
        )

    # ---------------------------------------------------------------
    # sha256 helpers
    # ---------------------------------------------------------------
    def test_sha256_uploaded_file_and_file_path_match(self):
        f = SimpleUploadedFile("hello.txt", b"hello world")
        digest1 = sha256_uploaded_file(f)

        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(b"hello world")
            digest2 = sha256_file_path(path)
        finally:
            os.remove(path)

        self.assertEqual(digest1, digest2)
        self.assertEqual(digest1, hashlib.sha256(b"hello world").hexdigest())

    # ---------------------------------------------------------------
    # materialize_version_to_media
    # ---------------------------------------------------------------
    def test_materialize_version_to_media_creates_expected_files(self):
        """Copies model/predict/schema into MEDIA_ROOT/category/name/v#"""
        materialize_version_to_media(self.version)

        target_dir = Path(
            settings.MEDIA_ROOT,
            self.version.category,
            self.upload.name,
            f"v{self.version.version_number}",
        )

        self.assertTrue(target_dir.exists())
        self.assertTrue((target_dir / "model.pt").exists())
        self.assertTrue((target_dir / "predict.py").exists())
        self.assertTrue((target_dir / "schema.json").exists())

    # ---------------------------------------------------------------
    # delete_version_files_and_dir
    # ---------------------------------------------------------------
    def test_delete_version_files_and_dir_removes_files(self):
        """Ensures uploaded files and version folder are deleted safely."""
        materialize_version_to_media(self.version)
        version_dir = Path(
            settings.MEDIA_ROOT,
            self.version.category,
            self.upload.name,
            f"v{self.version.version_number}",
        )
        self.assertTrue(version_dir.exists())

        delete_version_files_and_dir(self.version)

        # Uploaded files deleted
        self.assertFalse(os.path.exists(self.version.model_file.path))
        self.assertFalse(os.path.exists(self.version.predict_file.path))
        self.assertFalse(os.path.exists(self.version.schema_file.path))
        # Materialized dir deleted
        self.assertFalse(version_dir.exists())

    def test_delete_version_files_and_dir_handles_exceptions(self):
        """Should not crash even if os.remove raises."""
        with patch("os.remove", side_effect=OSError("permission denied")):
            delete_version_files_and_dir(self.version)

    # ---------------------------------------------------------------
    # delete_model_media_tree
    # ---------------------------------------------------------------
    def test_delete_model_media_tree_removes_all_category_dirs(self):
        """Creates fake category directories and ensures they get removed."""
        base = Path(settings.MEDIA_ROOT)
        for cat in ["sentiment", "recommendation", "text-classification"]:
            path = base / cat / self.upload.name
            path.mkdir(parents=True, exist_ok=True)
            (path / "dummy.txt").write_text("x")

        delete_model_media_tree(self.upload)

        for cat in ["sentiment", "recommendation", "text-classification"]:
            self.assertFalse((base / cat / self.upload.name).exists())

    def test_delete_model_media_tree_handles_exceptions(self):
        """If shutil.rmtree fails, it should swallow the exception."""
        with patch("shutil.rmtree", side_effect=OSError("no permission")):
            delete_model_media_tree(self.upload)
