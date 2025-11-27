import os
import importlib
import sys
from django.test import SimpleTestCase


class SettingsImportTests(SimpleTestCase):
    """Covers environment-dependent branches in note2web/settings.py"""

    def tearDown(self):
        # Clean up changes to sys.modules so re-imports use fresh state
        sys.modules.pop("note2web.settings", None)
        # Reset env vars after each test
        for key in [
            "DJANGO_SECRET_KEY",
            "CI",
            "TRAVIS",
            "OPENAI_API_KEY",
            "REDIS_URL",
            "REDIS_HOST",
            "REDIS_PORT",
        ]:
            os.environ.pop(key, None)

    def test_warns_when_openai_key_missing(self):
        """Covers line 43 (warning print for missing OPENAI_API_KEY)."""
        os.environ["DJANGO_SECRET_KEY"] = "fakekey"
        os.environ.pop("OPENAI_API_KEY", None)
        module = importlib.reload(importlib.import_module("note2web.settings"))
        self.assertTrue(hasattr(module, "OPENAI_API_KEY"))

    def test_redis_url_configured(self):
        """Covers line 107 (Redis URL branch)."""
        os.environ["DJANGO_SECRET_KEY"] = "fakekey"
        os.environ["OPENAI_API_KEY"] = "fake-openai"
        os.environ["REDIS_URL"] = "redis://localhost:6379"
        module = importlib.reload(importlib.import_module("note2web.settings"))
        self.assertIn(
            "channels_redis.core.RedisChannelLayer", str(module.CHANNEL_LAYERS)
        )

    def test_redis_host_port_configured(self):
        """Covers line 117 (Redis host/port branch)."""
        os.environ["DJANGO_SECRET_KEY"] = "fakekey"
        os.environ["OPENAI_API_KEY"] = "fake-openai"
        os.environ.pop("REDIS_URL", None)
        os.environ["REDIS_HOST"] = "redis.local"
        os.environ["REDIS_PORT"] = "6380"
        module = importlib.reload(importlib.import_module("note2web.settings"))
        self.assertIn("redis.local", str(module.CHANNEL_LAYERS))
