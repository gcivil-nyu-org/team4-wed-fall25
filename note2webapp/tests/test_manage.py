import unittest
from unittest.mock import patch
import importlib.util


class ManagePyTests(unittest.TestCase):
    """Tests for manage.py import and environment setup logic."""

    def setUp(self):
        # Dynamically load manage.py as a module
        spec = importlib.util.spec_from_file_location("manage", "manage.py")
        self.manage = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.manage)

    @patch("os.environ.setdefault")
    @patch("django.core.management.execute_from_command_line")
    def test_main_calls_execute_from_command_line(self, mock_exec, mock_setdefault):
        """Ensure manage.main() sets the env var and calls Django execute."""
        self.manage.main()

        mock_setdefault.assert_called_once_with(
            "DJANGO_SETTINGS_MODULE", "note2web.settings"
        )
        mock_exec.assert_called_once()

    @patch.dict("sys.modules", {"django.core.management": None})
    def test_main_raises_import_error_when_django_missing(self):
        """Ensure manage.main() raises ImportError if Django isn't installed."""
        with self.assertRaises(ImportError) as ctx:
            self.manage.main()

        self.assertIn("Couldn't import Django", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
