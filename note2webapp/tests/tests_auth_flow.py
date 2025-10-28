from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User


class TestAuthFlow(TestCase):
    def test_signup_creates_user_with_email(self):
        """Check that signup view successfully creates user with email."""
        response = self.client.post(
            reverse("signup"),
            {
                "username": "testuser",
                "email": "test@example.com",
                "password1": "Testpass123",
                "password2": "Testpass123",
            },
        )
        # Redirect to dashboard after successful signup
        self.assertEqual(response.status_code, 302)
        self.assertTrue(User.objects.filter(username="testuser").exists())

        user = User.objects.get(username="testuser")
        self.assertEqual(user.email, "test@example.com")

    def test_password_reset_request(self):
        """Verify that password reset request works."""
        user = User.objects.create_user(
            username="resetuser", email="reset@example.com", password="OldPass123"
        )
        self.assertEqual(user.username, "resetuser")
        response = self.client.post(
            reverse("password_reset"), {"email": "reset@example.com"}, follow=True
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Check your email")
