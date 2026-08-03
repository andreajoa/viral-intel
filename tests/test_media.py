import tempfile
import unittest
from pathlib import Path

from PIL import Image

from app.config import Settings
from app.media.inspector import MediaInspector, media_kind, validate_media_selection


class MediaTests(unittest.TestCase):
    def test_upload_must_match_selected_format(self):
        self.assertIsNotNone(validate_media_selection([Path("slide.png")], "reel"))
        self.assertIsNotNone(validate_media_selection([Path("video.mp4")], "carousel"))
        self.assertIsNone(validate_media_selection([Path("video.mp4")], "reel"))
        self.assertIsNone(validate_media_selection([Path("cover.png")], "carousel"))
        self.assertIsNone(validate_media_selection([Path("slide-1.png"), Path("slide-2.jpg")], "carousel"))
        self.assertEqual(media_kind([Path("one.mp4"), Path("two.mp4")]), "unknown")
        self.assertEqual(media_kind([Path("slide.png"), Path("clip.mp4")]), "unknown")

    def test_image_and_carousel_inspection(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "first.jpg"
            second = root / "second.png"
            Image.new("RGB", (1080, 1350), "#F3DED0").save(first)
            Image.new("RGB", (1080, 1350), "#09274B").save(second)
            settings = Settings(data_dir=root / "data", max_frames=12)
            settings.ensure_dirs()
            result = MediaInspector(settings).inspect([first, second], root / "out")
            self.assertEqual(media_kind([first, second]), "carousel")
            self.assertEqual(result["technical"]["slide_count"], 2)
            self.assertEqual(len(result["frames"]), 2)


if __name__ == "__main__":
    unittest.main()
