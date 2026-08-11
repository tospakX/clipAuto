import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from youtube_clipper.transcriber import (
    _collect_segments,
    _complete_model_path,
    _load_cuda_library,
    resolve_runtime,
)


class RuntimeSelectionTests(unittest.TestCase):
    def test_cuda_library_can_be_loaded_from_ollama_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "libcublas.so.12"
            library.touch()
            with (
                patch(
                    "youtube_clipper.transcriber._cuda_library_directories",
                    return_value=(Path(tmp),),
                ),
                patch("youtube_clipper.transcriber.ctypes.CDLL") as load,
            ):
                load.side_effect = [OSError("not on system path"), object()]
                self.assertTrue(_load_cuda_library("libcublas.so.12"))
                self.assertEqual(load.call_args.args[0], str(library))

    def test_auto_falls_back_to_cpu_when_cuda_runtime_is_incomplete(self):
        fake_ctranslate = SimpleNamespace(get_cuda_device_count=lambda: 1)
        with (
            patch.dict("sys.modules", {"ctranslate2": fake_ctranslate}),
            patch(
                "youtube_clipper.transcriber._cuda_libraries_available",
                return_value=(False, "libcublas.so.12"),
            ),
        ):
            device, compute, warning = resolve_runtime("auto", "default")
        self.assertEqual((device, compute), ("cpu", "int8"))
        self.assertIn("libcublas.so.12", warning)

    def test_auto_uses_cuda_only_when_device_and_libraries_are_ready(self):
        fake_ctranslate = SimpleNamespace(get_cuda_device_count=lambda: 1)
        with (
            patch.dict("sys.modules", {"ctranslate2": fake_ctranslate}),
            patch(
                "youtube_clipper.transcriber._cuda_libraries_available", return_value=(True, None)
            ),
        ):
            runtime = resolve_runtime("auto", "default")
        self.assertEqual(runtime, ("cuda", "float16", None))


class ModelAndProgressTests(unittest.TestCase):
    def test_local_model_directory_must_contain_model_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            model_dir = Path(tmp)
            self.assertIsNone(_complete_model_path(str(model_dir)))
            (model_dir / "model.bin").write_bytes(b"weights")
            self.assertEqual(_complete_model_path(str(model_dir)), model_dir)

    def test_transcription_progress_uses_video_timestamp(self):
        updates = []
        segments = [
            SimpleNamespace(start=0.0, end=25.0, text=" First ", words=[]),
            SimpleNamespace(start=25.0, end=75.0, text=" Second ", words=[]),
        ]
        result = _collect_segments(
            iter(segments), 100.0, lambda value, text: updates.append((value, text))
        )
        self.assertEqual(len(result), 2)
        self.assertTrue(any("75% of video processed" in text for _value, text in updates))


if __name__ == "__main__":
    unittest.main()
