from django.test import TestCase
from django.contrib.auth import get_user_model
from ..models import ModelUpload, ModelVersion, ModelComment
from note2webapp.models import Profile

User = get_user_model()


class ModelVersionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser", password="testpass123", email="test@example.com"
        )
        self.upload = ModelUpload.objects.create(name="Test Model", user=self.user)

    def test_version_creation(self):
        version = ModelVersion.objects.create(
            upload=self.upload,
            tag="v1.0",
            status="PASS",
            log="Test log",
            is_active=True,
        )
        self.assertEqual(str(version), "Test Model - v1 (PASS)")
        self.assertTrue(version.is_active)
        self.assertEqual(version.upload, self.upload)

    def test_version_ordering(self):
        v1 = ModelVersion.objects.create(upload=self.upload, tag="v1.0")
        v2 = ModelVersion.objects.create(upload=self.upload, tag="v2.0")

        versions = list(ModelVersion.objects.order_by("-id"))
        self.assertEqual(versions, [v2, v1])

    def test_modelversion_str_handles_missing_upload(self):
        mv = ModelVersion(status="PASS")
        self.assertIn("unsaved", str(mv))

    def test_get_media_dir_with_and_without_upload_name(self):
        mv = ModelVersion(upload=self.upload, version_number=2, category="sentiment")
        result = mv.get_media_dir()
        self.assertIn("sentiment", result)
        self.assertIn("Test Model", result)


class ProfileSignalTests(TestCase):
    def test_existing_user_triggers_profile_update(self):
        """Covers create_or_update_profile non-created branch (line 23)."""
        user = User.objects.create_user("alice", password="123")
        # Signal already created profile; now simulate update
        user.email = "changed@example.com"
        user.save()  # triggers else branch
        profile = Profile.objects.get(user=user)
        self.assertEqual(profile.user.username, "alice")


class ModelVersionEdgeCaseTests(TestCase):
    def test_get_media_dir_fallback_without_upload_name(self):
        """Covers getattr fallback in get_media_dir (line 137) without hitting Django FK descriptor."""

        class DummyVersion:
            category = "sentiment"
            upload_id = 99
            version_number = 7
            # make upload an object with no .name
            upload = object()

            def get_media_dir(self):
                from note2webapp.models import ModelVersion

                # reuse real implementation but avoid ORM
                return ModelVersion.get_media_dir(self)

        mv = DummyVersion()
        result = mv.get_media_dir()
        assert "upload-99" in result


class ProfileStrTests(TestCase):
    def test_profile_str_returns_username_and_role(self):
        user = User.objects.create_user("testerx", password="123")
        profile = user.profile  # created by signal
        result = str(profile)
        self.assertIn("testerx", result)
        self.assertIn(profile.role, result)


class ModelVersionGetterTests(TestCase):
    def test_get_version_number_returns_integer(self):
        user = User.objects.create_user("u1", password="123")
        upload = ModelUpload.objects.create(user=user, name="ModelY")
        mv = ModelVersion.objects.create(upload=upload, tag="v1")
        self.assertEqual(mv.get_version_number(), mv.version_number)


class ModelCommentStrReplyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("bob2", password="x")
        self.upload = ModelUpload.objects.create(user=self.user, name="MZ")
        self.version = ModelVersion.objects.create(upload=self.upload, tag="v1")

    def test_comment_str_includes_username_and_tag(self):
        c = ModelComment.objects.create(
            model_version=self.version, user=self.user, content="great work"
        )
        s = str(c)
        self.assertIn(self.user.username, s)
        self.assertIn(self.version.tag, s)

    def test_is_reply_true_and_false(self):
        c1 = ModelComment.objects.create(
            model_version=self.version, user=self.user, content="base comment"
        )
        self.assertFalse(c1.is_reply())  # line 169 false branch
        reply = ModelComment.objects.create(
            model_version=self.version, user=self.user, content="reply", parent=c1
        )
        self.assertTrue(reply.is_reply())  # true branch
