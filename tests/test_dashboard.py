from __future__ import annotations

import io
import os
import tempfile
import unittest

from PIL import Image, ImageDraw
from streamlit.testing.v1 import AppTest

from app.config import get_settings


class DashboardTests(unittest.TestCase):
    def test_image_upload_generates_report_without_ui_exception(self):
        previous_data_dir = os.environ.get("DATA_DIR")
        previous_transcription = os.environ.get("ENABLE_TRANSCRIPTION")
        previous_collection = os.environ.get("ENABLE_PUBLIC_COLLECTION")

        try:
            with tempfile.TemporaryDirectory(prefix="viral-intel-ui-") as temp_dir:
                os.environ["DATA_DIR"] = temp_dir
                os.environ["ENABLE_TRANSCRIPTION"] = "false"
                os.environ["ENABLE_PUBLIC_COLLECTION"] = "false"
                get_settings.cache_clear()

                image = Image.new("RGB", (720, 900), (243, 222, 208))
                ImageDraw.Draw(image).text((60, 100), "TESTE DO POST", fill=(9, 39, 75))
                content = io.BytesIO()
                image.save(content, "PNG")

                app = AppTest.from_file("app/ui/dashboard.py", default_timeout=40).run()
                self.assertEqual(len(app.exception), 0)
                app.selectbox[1].select("image")
                app.get("file_uploader")[0].upload("post.png", content.getvalue(), "image/png")
                app.run()
                app.button[0].click().run()

                self.assertEqual(len(app.exception), 0)
                self.assertEqual(len(app.error), 0)
                self.assertTrue(any(item.label == "Confiança dos dados" for item in app.metric))
                downloads = [item.label for item in app.get("download_button")]
                self.assertIn("Baixar relatório completo (.json)", downloads)
                self.assertIn("Baixar relatório para leitura (.md)", downloads)
        finally:
            if previous_data_dir is None:
                os.environ.pop("DATA_DIR", None)
            else:
                os.environ["DATA_DIR"] = previous_data_dir
            if previous_transcription is None:
                os.environ.pop("ENABLE_TRANSCRIPTION", None)
            else:
                os.environ["ENABLE_TRANSCRIPTION"] = previous_transcription
            if previous_collection is None:
                os.environ.pop("ENABLE_PUBLIC_COLLECTION", None)
            else:
                os.environ["ENABLE_PUBLIC_COLLECTION"] = previous_collection
            get_settings.cache_clear()


if __name__ == "__main__":
    unittest.main()
