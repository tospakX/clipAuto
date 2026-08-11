import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from youtube_clipper.downloader import (
    download_video,
    parse_description_timestamps,
    timestamps_from_metadata,
)


class DescriptionTimestampTests(unittest.TestCase):
    def test_parses_common_timestamp_formats_and_ignores_unrelated_text(self):
        description = """Chapters
0:00 Intro
- 01:25 First topic
Long topic — 1:02:03
https://example.com/watch?t=90
Order 1234 today
"""
        timestamps = parse_description_timestamps(description)
        self.assertEqual(
            [(item.timestamp, item.title) for item in timestamps],
            [(0.0, "Intro"), (85.0, "First topic"), (3723.0, "Long topic")],
        )
        self.assertTrue(all(item.confidence > 0.8 for item in timestamps))

    def test_lone_description_time_has_lower_confidence(self):
        timestamps = parse_description_timestamps("Jump ahead 5:30")
        self.assertEqual(len(timestamps), 1)
        self.assertLess(timestamps[0].confidence, 0.65)

    def test_structured_chapter_wins_when_description_time_is_duplicated(self):
        timestamps = timestamps_from_metadata(
            {
                "description": "0:00 Intro\n1:00 Description label",
                "chapters": [{"start_time": 60, "title": "Official chapter"}],
            }
        )
        self.assertEqual(len(timestamps), 2)
        self.assertEqual(timestamps[1].title, "Official chapter")
        self.assertEqual(timestamps[1].confidence, 0.95)


class DownloaderTests(unittest.TestCase):
    @patch("youtube_clipper.downloader.subprocess.run")
    def test_uses_video_id_in_output_to_avoid_cross_video_cache(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "source_abc123.mp4"
            output.write_bytes(b"video")
            output.with_suffix(".info.json").write_text(
                json.dumps({"description": "0:00 Intro\n1:30 Topic two"}), encoding="utf-8"
            )
            run.return_value = Mock(returncode=0, stdout=f"{output}\n", stderr="")
            result = download_video("https://youtu.be/abc123", Path(tmp))

        self.assertEqual(result.path, output)
        self.assertEqual([item.timestamp for item in result.timestamps], [0.0, 90.0])
        command = run.call_args.args[0]
        self.assertIn("source_%(id)s.%(ext)s", " ".join(command))
        self.assertIn("--write-info-json", command)

    @patch("youtube_clipper.downloader.subprocess.run")
    def test_reports_yt_dlp_error(self, run):
        run.return_value = Mock(returncode=1, stdout="", stderr="ERROR: unavailable video\n")
        with (
            tempfile.TemporaryDirectory() as tmp,
            self.assertRaisesRegex(
                RuntimeError, "yt-dlp download failed: ERROR: unavailable video"
            ),
        ):
            download_video("https://youtu.be/example", Path(tmp))


if __name__ == "__main__":
    unittest.main()
