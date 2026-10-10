import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import load_local_env


class BackendConfigTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[2] / "work" / "test-backend-config"
        root.mkdir(parents=True, exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(dir=root)
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / ".env"

    def test_data_directory_and_origins_load_from_backend_file(self):
        self.path.write_text('DATA_DIR="/example/resume-data"\nCORS_ORIGINS=http://localhost:5174\nUNRELATED_OPTION=ignored\n', encoding="utf-8")
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(load_local_env(self.path))
            self.assertEqual(os.environ["DATA_DIR"], "/example/resume-data")
            self.assertEqual(os.environ["CORS_ORIGINS"], "http://localhost:5174")
            self.assertNotIn("UNRELATED_OPTION", os.environ)

    def test_explicit_process_data_directory_wins(self):
        self.path.write_text("DATA_DIR=/example/default\n", encoding="utf-8")
        with patch.dict(os.environ, {"DATA_DIR": "/example/isolated-demo"}, clear=True):
            self.assertIsNone(load_local_env(self.path))
            self.assertEqual(os.environ["DATA_DIR"], "/example/isolated-demo")

    def test_malformed_file_reports_location_without_value(self):
        self.path.write_text("malformed-secret-line\n", encoding="utf-8")
        self.assertIn("第 1 行", load_local_env(self.path))
        self.assertNotIn("malformed-secret-line", load_local_env(self.path))
