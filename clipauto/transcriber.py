from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Lock
from typing import Any

from clipauto.models import TranscriptSegment, TranscriptWord
from clipauto.process import ProcessCancelled


class TranscriptionError(RuntimeError):
    pass


@dataclass(slots=True)
class TranscriptionResult:
    segments: list[TranscriptSegment]
    duration: float
    language: str
    device: str


def _default_factory(name: str, device: str, compute_type: str):
    from faster_whisper import WhisperModel

    return WhisperModel(name, device=device, compute_type=compute_type)


class WhisperTranscriber:
    def __init__(
        self,
        model_name: str,
        model_factory: Callable[..., Any] | None = None,
        *,
        cache_models: bool = True,
    ):
        self.model_name = model_name
        self.model_factory = model_factory or _default_factory
        self.cache_models = cache_models
        self._models: dict[tuple[str, str], Any] = {}
        self._model_lock = Lock()

    def _model(self, device: str, compute_type: str):
        if not self.cache_models:
            return self.model_factory(self.model_name, device=device, compute_type=compute_type)
        key = (device, compute_type)
        with self._model_lock:
            if key not in self._models:
                self._models[key] = self.model_factory(
                    self.model_name, device=device, compute_type=compute_type
                )
            return self._models[key]

    def _run(
        self, path: Path, device: str, compute_type: str, progress: Callable[[float], None]
    ) -> TranscriptionResult:
        model = self._model(device, compute_type)
        source, info = model.transcribe(
            str(path),
            beam_size=1,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=True,
        )
        duration = float(info.duration or 0)
        segments: list[TranscriptSegment] = []
        for item in source:
            words = [
                TranscriptWord(float(word.start), float(word.end), word.word.strip())
                for word in (item.words or [])
                if word.start is not None and word.end is not None and word.word.strip()
            ]
            segment = TranscriptSegment(
                float(item.start), float(item.end), item.text.strip(), words
            )
            segments.append(segment)
            if duration > 0:
                progress(min(1.0, segment.end / duration))
        if not segments:
            raise TranscriptionError("Whisper did not detect any spoken transcript")
        return TranscriptionResult(
            segments, duration or segments[-1].end, info.language or "unknown", device
        )

    def transcribe(self, path: Path, progress: Callable[[float], None]) -> TranscriptionResult:
        cuda_error: Exception | None = None
        try:
            return self._run(path, "cuda", "float16", progress)
        except ProcessCancelled:
            raise
        except TranscriptionError:
            raise
        except Exception as error:
            cuda_error = error
        try:
            return self._run(path, "cpu", "int8", progress)
        except ProcessCancelled:
            raise
        except TranscriptionError:
            raise
        except Exception as error:
            raise TranscriptionError(
                f"Transcription failed on GPU ({cuda_error}) and CPU ({error})"
            ) from error
