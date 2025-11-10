# note2webapp/tests/test_validation_flow.py  (just the failing test)
from django.test import TestCase, Client
from django.contrib.auth.models import User
from note2webapp.models import ModelUpload, ModelVersion


class ModelValidationFlowTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user("u1", password="pass")
        self.client.login(username="u1", password="pass")
        self.upload = ModelUpload.objects.create(user=self.user, name="m1")
        ModelVersion.objects.create(
            upload=self.upload,
            model_file="models/dummy.pt",
            predict_file="predict/dummy.py",
            schema_file="schemas/dummy.json",
            tag="v1",
            status="PASS",
            is_active=True,
            category="sentiment",
        )

    def test_cannot_delete_model_with_versions(self):
        resp = self.client.post(f"/delete-model/{self.upload.id}/", follow=True)
        self.assertContains(
            resp,
            "Cannot delete model with 1 active versions. Please delete all versions first.",
        )
