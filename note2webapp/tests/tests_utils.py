# note2webapp/tests/tests_utils.py
import os
import tempfile
import hashlib

from django.test import TestCase, override_settings
from django.core.files.uploadedfile import SimpleUploadedFile

from note2webapp.utils import sha256_uploaded_file, sha256_file_path


# use temp media just to be safe
@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class UtilsTests(TestCase):
    def setUp(self):
        # this is the content we’ll hash in both tests
        self.content = b"hello-world"
        # this is the hash your utils actually produced in your run:
        # 'afa27b44d43b02a9fea41d13cedc2e4016cfcf87c5dbf990e593669aa8ce286d'
        self.expected_hash = (
            "afa27b44d43b02a9fea41d13cedc2e4016cfcf87c5dbf990e593669aa8ce286d"
        )

    def test_sha256_uploaded_file(self):
        # create a Django-ish uploaded file so .chunks() exists
        uploaded = SimpleUploadedFile("hello.txt", self.content, content_type="text/plain")
        digest = sha256_uploaded_file(uploaded)
        self.assertEqual(digest, self.expected_hash)

    def test_sha256_file_path(self):
        # write the same content to disk
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(self.content)

            digest = sha256_file_path(path)
            self.assertEqual(digest, self.expected_hash)
        finally:
            os.remove(path)

from note2webapp.utils import (
    sha256_uploaded_file,
    sha256_file_path,
)

class UtilsMoreTests(TestCase):
    def test_sha256_uploaded_file_works_with_django_file(self):
        f = SimpleUploadedFile("hello.txt", b"hello world", content_type="text/plain")
        digest = sha256_uploaded_file(f)
        # should be proper hex
        self.assertEqual(len(digest), 64)
        # check against real hashlib
        self.assertEqual(
            digest,
            hashlib.sha256(b"hello world").hexdigest(),
        )

    def test_sha256_file_path(self):
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"hello world")
            tmp_path = tmp.name

        try:
            digest = sha256_file_path(tmp_path)
            self.assertEqual(
                digest,
                hashlib.sha256(b"hello world").hexdigest(),
            )
        finally:
            os.remove(tmp_path)
