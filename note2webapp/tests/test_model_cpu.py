import json
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from note2webapp.models import Profile, ModelUpload, ModelVersion

User = get_user_model()


class TestModelCPUView(TestCase):
    def setUp(self):
        # Create users — profiles are auto-created by signal
        self.uploader = User.objects.create_user(
            username="uploader", password="pass123"
        )
        self.reviewer = User.objects.create_user(
            username="reviewer", password="pass123"
        )

        # Update their roles
        Profile.objects.filter(user=self.uploader).update(role="uploader")
        Profile.objects.filter(user=self.reviewer).update(role="reviewer")

        # Create dummy upload and version
        self.upload = ModelUpload.objects.create(user=self.uploader, name="AlexNet")
        self.version = ModelVersion.objects.create(
            upload=self.upload, tag="v1", status="PASS", is_active=True
        )

        self.client = Client()
        self.url = reverse("test_model_cpu", args=[self.version.id])

    def test_back_button_renders_correctly_for_roles(self):
        """
        Ensure Back button URL differs correctly for uploader and reviewer roles.
        """
        # Uploader
        self.client.login(username="uploader", password="pass123")
        response = self.client.get(self.url)
        self.assertContains(response, "model-versions")
        self.client.logout()

        # Reviewer
        self.client.login(username="reviewer", password="pass123")
        response = self.client.get(self.url)
        self.assertContains(response, "reviewer")

    def test_post_valid_input_returns_result(self):
        """
        Ensure posting valid JSON input returns model test result.
        """
        self.client.login(username="uploader", password="pass123")

        input_data = {"x1": 1, "x2": 2, "x3": 3, "x4": 4}
        response = self.client.post(self.url, {"input_data": json.dumps(input_data)})

        self.assertEqual(response.status_code, 200)
        self.assertIn("result", response.context)
