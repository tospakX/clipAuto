import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_clipper.analysis_cache import load_analysis, save_analysis
from youtube_clipper.types import TranscriptSegment, TranscriptWord


class AnalysisCacheTests(unittest.TestCase):
    def test_round_trip_preserves_transcript_words_and_scenes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            segments = [
                TranscriptSegment(
                    1,
                    3,
                    "Hello",
                    (TranscriptWord(1, 2, " Hello"),),
                )
            ]
            save_analysis(root, source, "small", segments, "en", [2.5, 8.0])
            cached = load_analysis(root, source, "small")

            self.assertIsNotNone(cached)
            self.assertEqual(cached.segments, segments)
            self.assertEqual(cached.language, "en")
            self.assertEqual(cached.scene_times, [2.5, 8.0])

    def test_changed_model_or_source_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            save_analysis(root, source, "small", [], "en", [])

            self.assertIsNone(load_analysis(root, source, "medium"))
            source.write_bytes(b"different video")
            self.assertIsNone(load_analysis(root, source, "small"))

    def test_corrupt_cache_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            save_analysis(root, source, "small", [], None, [])
            cache_file = next(root.glob("analysis_*.json"))
            cache_file.write_text("not json", encoding="utf-8")

            with self.assertLogs("youtube_clipper.analysis_cache", level="WARNING"):
                self.assertIsNone(load_analysis(root, source, "small"))

    def test_changed_scene_threshold_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            source.write_bytes(b"video")
            save_analysis(root, source, "small", [], None, [])

            with patch("youtube_clipper.analysis_cache.SCENE_DETECTION_THRESHOLD", 99.0):
                self.assertIsNone(load_analysis(root, source, "small"))


if __name__ == "__main__":
    unittest.main()
