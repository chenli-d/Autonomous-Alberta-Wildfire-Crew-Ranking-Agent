import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.config import load_local_environment


class ConfigurationTests(unittest.TestCase):
    def test_local_loading_and_environment_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, ".env").write_text(
                'OPENAI_API_KEY=fixture-only\nOPENAI_MODEL=gpt-4.1-mini\n', encoding="utf-8")
            with patch.dict(os.environ, {}, clear=True):
                load_local_environment(directory)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "fixture-only")
                self.assertEqual(os.environ["OPENAI_MODEL"], "gpt-4.1-mini")
            with patch.dict(os.environ, {"OPENAI_API_KEY": "process-fixture"}, clear=True):
                load_local_environment(directory)
                self.assertEqual(os.environ["OPENAI_API_KEY"], "process-fixture")

    def test_missing_file_is_safe(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {}, clear=True):
            load_local_environment(directory)
            self.assertNotIn("OPENAI_API_KEY", os.environ)
