from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
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
)


class DashboardV3Tests(unittest.TestCase):
    def test_image_upload_generates_report_without_ui_exception(self):
        previous = {key: os.environ.get(key) for key in _ENV_KEYS}

        try:
            with tempfile.TemporaryDirectory(prefix="viral-intel-v3-") as temp_dir:
                os.environ["DATA_DIR"] = temp_dir
                os.environ["ENABLE_TRANSCRIPTION"] = "false"
                os.environ["ENABLE_PUBLIC_COLLECTION"] = "false"
                os.environ["EPHEMERAL_MODE"] = "true"
                for key in (
                    "GOOGLE_API_KEY",
                    "GEMINI_API_KEY",
                    "OPENAI_API_KEY",
                    "ANTHROPIC_API_KEY",
                ):
                    os.environ.pop(key, None)
                get_settings.cache_clear()

                image = Image.new("RGB", (1080, 1350), (243, 222, 208))
                ImageDraw.Draw(image).text(
                    (90, 140),
                    "TESTE DO VIRAL INTEL",
                    fill=(9, 39, 75),
                )
                content = io.BytesIO()
                image.save(content, "PNG")

                app = AppTest.from_file(
                    str(ROOT / "app" / "ui" / "dashboard_v3.py"),
                    default_timeout=50,
                ).run()
                self.assertEqual(len(app.exception), 0)

                app.get("file_uploader")[0].upload(
                    "post.png",
                    content.getvalue(),
                    "image/png",
                )
                app.run()
                app.button[0].click().run()

                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.error), 0)
                self.assertTrue(any(item.label == "Qualidade dos dados" for item in app.metric))
                downloads = [item.label for item in app.get("download_button")]
                self.assertIn("Baixar relatório completo (.json)", downloads)
                self.assertIn("Baixar relatório para leitura (.md)", downloads)
                self.assertEqual(list(Path(temp_dir).rglob("*.json")), [])
                self.assertEqual(list(Path(temp_dir).glob("inbox/upload_*")), [])
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
