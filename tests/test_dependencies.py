import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from youtube_clipper.dependencies import DependencyError, check_dependencies


class DependencyTests(unittest.TestCase):
    def _checks(self, importer=None):
        if importer is None:

            def importer(_name):
                return object()

        return (
            patch("youtube_clipper.dependencies.shutil.which", return_value="/usr/bin/tool"),
            patch("youtube_clipper.dependencies._ollama_models", return_value=("local-model",)),
            patch(
                "youtube_clipper.dependencies.subprocess.run",
                return_value=SimpleNamespace(
                    returncode=0,
                    stdout=" V..... libx264 H.264 encoder\n A..... aac AAC encoder\n",
                ),
            ),
            patch("youtube_clipper.transcriber.runtime_warning", return_value=None),
            patch(
                "youtube_clipper.dependencies.importlib.import_module",
                side_effect=importer,
            ),
        )

    def test_complete_local_environment_passes(self):
        first, second, third, fourth, fifth = self._checks()
        with first, second, third, fourth, fifth:
            report = check_dependencies()
        self.assertEqual(report.ollama_models, ("local-model",))

    def test_missing_opencv_is_reported_before_processing(self):
        def import_module(name):
            if name == "cv2":
                raise ImportError("missing cv2")
            return object()

        first, second, third, fourth, fifth = self._checks(import_module)
        with (
            first,
            second,
            third,
            fourth,
            fifth,
            self.assertRaisesRegex(DependencyError, "opencv-python"),
        ):
            check_dependencies()

    def test_missing_required_ffmpeg_encoder_is_reported(self):
        first, second, _third, fourth, fifth = self._checks()
        with (
            first,
            second,
            fourth,
            patch(
                "youtube_clipper.dependencies.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout=" A..... aac AAC encoder\n"),
            ),
            fifth,
            self.assertRaisesRegex(DependencyError, "libx264"),
        ):
            check_dependencies()

    def test_ffmpeg_encoder_probe_timeout_is_clear(self):
        first, second, _third, fourth, fifth = self._checks()
        with (
            first,
            second,
            fourth,
            patch(
                "youtube_clipper.dependencies.subprocess.run",
                side_effect=subprocess.TimeoutExpired("ffmpeg", 10),
            ),
            fifth,
            self.assertRaisesRegex(DependencyError, "Could not inspect FFmpeg encoders"),
        ):
            check_dependencies()


if __name__ == "__main__":
    unittest.main()
