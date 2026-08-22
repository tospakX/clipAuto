from pathlib import Path
from types import SimpleNamespace

import pytest

from clipauto.process import ProcessCancelled
from clipauto.transcriber import TranscriptionError, WhisperTranscriber


def test_falls_back_from_cuda_to_cpu_and_keeps_timestamps(tmp_path: Path):
    calls = []

    class FakeModel:
        def transcribe(self, path, **options):
            assert options["word_timestamps"] is True
            assert options["beam_size"] == 1
            assert options["vad_filter"] is True
            word = SimpleNamespace(start=1.0, end=1.5, word=" hello")
            segment = SimpleNamespace(start=1.0, end=3.0, text=" Hello world.", words=[word])
            return iter([segment]), SimpleNamespace(duration=4.0, language="en")

    def factory(name, device, compute_type):
        calls.append((name, device, compute_type))
        if device == "cuda":
            raise RuntimeError("CUDA unavailable")
        return FakeModel()

    progress = []
    result = WhisperTranscriber("small", model_factory=factory).transcribe(
        tmp_path / "source.mp4", progress.append
    )

    assert calls == [("small", "cuda", "float16"), ("small", "cpu", "int8")]
    assert result.device == "cpu"
    assert result.language == "en"
    assert result.duration == 4.0
    assert result.segments[0].text == "Hello world."
    assert result.segments[0].words[0].text == "hello"
    assert progress[-1] == 0.75


def test_cancellation_during_cuda_transcription_does_not_retry_on_cpu(tmp_path: Path):
    calls = []

    class CancelledModel:
        def transcribe(self, path, **options):
            raise ProcessCancelled("cancelled")

    def factory(name, device, compute_type):
        calls.append(device)
        return CancelledModel()

    with pytest.raises(ProcessCancelled, match="cancelled"):
        WhisperTranscriber("small", model_factory=factory).transcribe(
            tmp_path / "source.mp4", lambda _: None
        )

    assert calls == ["cuda"]


def test_no_speech_result_does_not_repeat_full_transcription_on_cpu(tmp_path: Path):
    calls = []

    class SilentModel:
        def transcribe(self, path, **options):
            return iter([]), SimpleNamespace(duration=30.0, language="en")

    def factory(name, device, compute_type):
        calls.append(device)
        return SilentModel()

    with pytest.raises(TranscriptionError, match="did not detect any spoken transcript"):
        WhisperTranscriber("small", model_factory=factory).transcribe(
            tmp_path / "silent.mp4", lambda _: None
        )

    assert calls == ["cuda"]


def test_reuses_loaded_model_for_sequential_videos(tmp_path: Path):
    factory_calls = []

    class FakeModel:
        def transcribe(self, path, **options):
            segment = SimpleNamespace(start=0.0, end=1.0, text=" Speech.", words=[])
            return iter([segment]), SimpleNamespace(duration=1.0, language="en")

    def factory(name, device, compute_type):
        factory_calls.append((device, compute_type))
        return FakeModel()

    transcriber = WhisperTranscriber("small", model_factory=factory)
    transcriber.transcribe(tmp_path / "first.mp4", lambda _: None)
    transcriber.transcribe(tmp_path / "second.mp4", lambda _: None)

    assert factory_calls == [("cuda", "float16")]
