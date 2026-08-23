from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.config import get_settings

ROOT = Path(__file__).resolve().parents[1]
_ENV_KEYS = (
    "DATA_DIR",
    "ENABLE_TRANSCRIPTION",
    "ENABLE_PUBLIC_COLLECTION",
    "EPHEMERAL_MODE",
    "GOOGLE_API_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "APIFY_API_TOKEN",
)


class CloudEntrypointTests(unittest.TestCase):
    def test_cloud_entrypoint_opens_link_only_lab_without_exception(self):
        previous = {key: os.environ.get(key) for key in _ENV_KEYS}

        try:
            with tempfile.TemporaryDirectory(prefix="viral-intel-cloud-") as temp_dir:
                os.environ["DATA_DIR"] = temp_dir
                os.environ["ENABLE_TRANSCRIPTION"] = "false"
                os.environ["ENABLE_PUBLIC_COLLECTION"] = "false"
                os.environ["EPHEMERAL_MODE"] = "true"
                for key in (
                    "GOOGLE_API_KEY",
                    "GEMINI_API_KEY",
                    "OPENAI_API_KEY",
                    "ANTHROPIC_API_KEY",
                    "APIFY_API_TOKEN",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()

                app = AppTest.from_file(
                    str(ROOT / "cloud" / "streamlit_app.py"),
                    default_timeout=50,
                ).run()

                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.error), 0)
                self.assertTrue(any(button.label == "Descobrir por que viralizou" for button in app.button))
                self.assertTrue(any(item.label == "Link público" for item in app.text_input))
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
