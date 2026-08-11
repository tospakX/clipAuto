import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_clipper.scenes import detect_scene_changes


class SceneDetectionTests(unittest.TestCase):
    @patch("youtube_clipper.scenes._detect", return_value=[12.5])
    @patch("youtube_clipper.scenes._opencv_can_decode", return_value=True)
    def test_uses_original_when_opencv_can_decode(self, _can_decode, detect):
        self.assertEqual(detect_scene_changes(Path("source.mp4")), [12.5])
        self.assertEqual(detect.call_args.args[0], Path("source.mp4"))

    @patch("youtube_clipper.scenes._detect", return_value=[8.0])
    @patch("youtube_clipper.scenes.subprocess.run")
    @patch("youtube_clipper.scenes._opencv_can_decode", return_value=False)
    def test_creates_h264_proxy_when_opencv_cannot_decode(self, _can_decode, run, detect):
        self.assertEqual(detect_scene_changes(Path("source-av1.mp4")), [8.0])
        command = run.call_args.args[0]
        self.assertIn("libx264", command)
        self.assertIn("scale=640:-2", command)
        self.assertNotEqual(detect.call_args.args[0], Path("source-av1.mp4"))

    @patch(
        "youtube_clipper.scenes.subprocess.run",
        side_effect=subprocess.CalledProcessError(1, ["ffmpeg"]),
    )
    @patch("youtube_clipper.scenes._opencv_can_decode", return_value=False)
    def test_proxy_failure_is_clear(self, _can_decode, _run):
        with self.assertRaisesRegex(RuntimeError, "compatible video for scene detection"):
            detect_scene_changes(Path("broken.mp4"))


if __name__ == "__main__":
    unittest.main()
