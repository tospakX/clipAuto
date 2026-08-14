import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_clipper.exporter import build_ffmpeg_command, export_clips


class ExportCommandTests(unittest.TestCase):
    def test_vertical_export_preserves_the_complete_frame(self):
        command = build_ffmpeg_command(Path("source.mp4"), Path("out.mp4"), 10, 40, 1.0)
        joined = " ".join(command)
        self.assertIn("scale=1080:1920:force_original_aspect_ratio=decrease", joined)
        self.assertIn("pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1", joined)
        self.assertNotIn("crop=", joined)
        self.assertIn("-c:v libx264", joined)
        self.assertIn("-c:a aac", joined)
        self.assertNotIn("atempo", joined)

    def test_all_non_normal_speeds_preserve_audio_pitch(self):
        for speed in (0.5, 0.75, 1.25, 1.5, 1.75, 2.0):
            with self.subTest(speed=speed):
                joined = " ".join(
                    build_ffmpeg_command(Path("source.mp4"), Path("out.mp4"), 0, 20, speed)
                )
                self.assertIn(f"setpts=PTS/{speed:g}", joined)
                self.assertIn(f"atempo={speed:g}", joined)

    def test_invalid_timestamps_are_rejected_before_ffmpeg(self):
        for start, end in ((-1, 10), (10, 10), (11, 10)):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                build_ffmpeg_command(Path("source.mp4"), Path("out.mp4"), start, end, 1.0)

    @patch("youtube_clipper.exporter.subprocess.run")
    def test_invalid_boundary_lists_do_not_touch_existing_outputs(self, run):
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            existing = output_dir / "part_01.mp4"
            existing.write_bytes(b"keep")
            for starts in ([], [10.0, 5.0], [0.0, 20.0]):
                with self.subTest(starts=starts), self.assertRaises(ValueError):
                    export_clips(Path("source.mp4"), starts, 20.0, output_dir)
            self.assertEqual(existing.read_bytes(), b"keep")
            run.assert_not_called()

    @patch("youtube_clipper.exporter.subprocess.run")
    def test_reports_each_export_and_removes_only_stale_numbered_parts(self, run):
        def create_output(command, **_kwargs):
            Path(command[-1]).write_bytes(b"new")

        run.side_effect = create_output
        progress = []
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "part_03.mp4").write_bytes(b"stale")
            (output_dir / "part_notes.mp4").write_bytes(b"keep")
            outputs = export_clips(
                Path("source.mp4"),
                [0.0, 10.0],
                20.0,
                output_dir,
                progress_callback=lambda current, total: progress.append((current, total)),
            )

            self.assertEqual([path.name for path in outputs], ["part_01.mp4", "part_02.mp4"])
            self.assertFalse((output_dir / "part_03.mp4").exists())
            self.assertTrue((output_dir / "part_notes.mp4").exists())
        self.assertEqual(progress, [(1, 2), (2, 2)])

    @patch("youtube_clipper.exporter.subprocess.run")
    def test_descriptive_names_are_numbered_safe_and_replace_stale_managed_clips(self, run):
        def create_output(command, **_kwargs):
            Path(command[-1]).write_bytes(b"new")

        run.side_effect = create_output
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            (output_dir / "03_old-topic.mp4").write_bytes(b"stale")
            (output_dir / "notes.mp4").write_bytes(b"keep")

            outputs = export_clips(
                Path("source.mp4"),
                [0.0, 10.0],
                20.0,
                output_dir,
                clip_names=["Camera setup", "AUX / unsafe? title"],
            )

            self.assertEqual(
                [path.name for path in outputs],
                ["01_camera-setup.mp4", "02_aux-unsafe-title.mp4"],
            )
            self.assertFalse((output_dir / "03_old-topic.mp4").exists())
            self.assertTrue((output_dir / "notes.mp4").exists())

    @patch("youtube_clipper.exporter.subprocess.run")
    def test_clip_name_count_must_match_boundaries_before_ffmpeg(self, run):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaisesRegex(
            ValueError, "one name per clip boundary"
        ):
            export_clips(
                Path("source.mp4"),
                [0.0, 10.0],
                20.0,
                Path(tmp),
                clip_names=["only one"],
            )
        run.assert_not_called()

    @patch("youtube_clipper.exporter.subprocess.run")
    def test_failed_export_preserves_previous_complete_output_set(self, run):
        calls = 0

        def fail_second(command, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise subprocess.CalledProcessError(1, command, stderr="encoder failed")
            Path(command[-1]).write_bytes(b"pending")

        run.side_effect = fail_second
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp)
            first = output_dir / "part_01.mp4"
            second = output_dir / "part_02.mp4"
            first.write_bytes(b"old one")
            second.write_bytes(b"old two")

            with self.assertRaisesRegex(RuntimeError, "part 02: encoder failed"):
                export_clips(Path("source.mp4"), [0.0, 10.0], 20.0, output_dir)

            self.assertEqual(first.read_bytes(), b"old one")
            self.assertEqual(second.read_bytes(), b"old two")
            self.assertEqual(list(output_dir.glob("*.pending.mp4")), [])


if __name__ == "__main__":
    unittest.main()
