import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_clipper.dependencies import DependencyReport
from youtube_clipper.downloader import DownloadedVideo
from youtube_clipper.pipeline import run_pipeline
from youtube_clipper.types import BoundarySuggestion, TranscriptSegment, VideoTimestamp


class PipelineTests(unittest.TestCase):
    @patch("youtube_clipper.pipeline.export_clips")
    @patch("youtube_clipper.pipeline.OllamaBoundaryReasoner")
    @patch("youtube_clipper.pipeline.detect_scene_changes", return_value=[20.0])
    @patch("youtube_clipper.pipeline.transcribe_video")
    @patch("youtube_clipper.pipeline.get_duration", return_value=45.0)
    @patch("youtube_clipper.pipeline.download_video")
    @patch("youtube_clipper.pipeline.check_dependencies")
    def test_stage_orchestration(
        self, check, download, duration, transcribe, scenes, reasoner, export
    ):
        check.return_value = DependencyReport(("local-model",))
        video_timestamps = (VideoTimestamp(20, "Second topic", 0.95),)
        download.return_value = DownloadedVideo(
            Path("work/abc123/source.mp4"),
            video_timestamps,
            "My Useful Video",
            "abc123",
        )
        transcribe.return_value = (
            [TranscriptSegment(0, 5, "Intro"), TranscriptSegment(20, 24, "Number two: details")],
            "en",
        )
        reasoner.return_value.suggest_boundaries.return_value = [BoundarySuggestion(20, 0.9)]
        export.return_value = [
            Path("output/my-useful-video-abc123/clips/01_intro.mp4"),
            Path("output/my-useful-video-abc123/clips/02_second-topic.mp4"),
        ]
        progress = []
        with tempfile.TemporaryDirectory() as tmp:
            result = run_pipeline(
                "https://youtu.be/example",
                Path(tmp) / "out",
                Path(tmp) / "work",
                1.25,
                progress_callback=lambda value, stage: progress.append((value, stage)),
            )
        self.assertEqual(len(result), 2)
        self.assertEqual(progress[0], (3, "Checking local tools"))
        self.assertEqual(progress[-1], (100, "Your clips are ready"))
        reasoner.return_value.suggest_boundaries.assert_called_once_with(
            unittest.mock.ANY,
            [20.0],
            [20],
            video_timestamps,
        )
        export.assert_called_once_with(
            Path("work/abc123/source.mp4"),
            [0.0, 20.0],
            45.0,
            Path(tmp) / "out" / "my-useful-video-abc123" / "clips",
            1.25,
            unittest.mock.ANY,
            clip_names=["intro", "second-topic"],
        )


if __name__ == "__main__":
    unittest.main()
