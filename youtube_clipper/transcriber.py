from __future__ import annotations

import ctypes
import logging
import os
import sys
import threading
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from .config import (
    DEFAULT_WHISPER_COMPUTE_TYPE,
    DEFAULT_WHISPER_DEVICE,
    DEFAULT_WHISPER_MODEL,
    WHISPER_MODEL_DOWNLOAD_MB,
)
from .types import TranscriptSegment, TranscriptWord

LOGGER = logging.getLogger(__name__)
TranscriptionProgress = Callable[[int, str], None]


def _cuda_library_directories() -> tuple[Path, ...]:
    """Return common locations for project-local and Ollama CUDA libraries."""
    directories = [
        Path("/usr/local/lib/ollama/cuda_v12"),
        Path(sys.prefix)
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
        / "nvidia"
        / "cublas"
        / "lib",
    ]
    directories.extend(
        Path(value) for value in os.environ.get("LD_LIBRARY_PATH", "").split(":") if value
    )
    return tuple(dict.fromkeys(directories))


def _load_cuda_library(library: str) -> bool:
    """Load a CUDA library, including copies bundled with a local Ollama install."""
    try:
        ctypes.CDLL(library, mode=ctypes.RTLD_GLOBAL)
        return True
    except OSError:
        pass

    for directory in _cuda_library_directories():
        candidate = directory / library
        if not candidate.is_file():
            continue
        try:
            ctypes.CDLL(str(candidate), mode=ctypes.RTLD_GLOBAL)
            LOGGER.info("Using CUDA library %s", candidate)
            return True
        except OSError:
            continue
    return False


def _cuda_libraries_available() -> tuple[bool, str | None]:
    """Preload the native library required by the installed CTranslate2 wheel."""
    # CTranslate2 4.8 uses cuBLAS for faster-whisper inference. Some older setup
    # guides also list cuDNN, but this wheel does not link to it.
    for library in ("libcublas.so.12",):
        if not _load_cuda_library(library):
            return False, library
    return True, None


def resolve_runtime(device: str, compute_type: str) -> tuple[str, str, str | None]:
    """Resolve `auto` to a usable backend instead of merely detecting a GPU device."""
    import ctranslate2

    resolved_device = device
    warning = None
    if device == "auto":
        has_cuda_device = ctranslate2.get_cuda_device_count() > 0
        libraries_ready, missing_library = _cuda_libraries_available()
        if has_cuda_device and libraries_ready:
            resolved_device = "cuda"
        else:
            resolved_device = "cpu"
            if has_cuda_device and missing_library:
                warning = (
                    f"GPU detected but {missing_library} is unavailable; using optimized CPU mode"
                )

    resolved_compute = compute_type
    if compute_type == "default":
        resolved_compute = "float16" if resolved_device == "cuda" else "int8"
    return resolved_device, resolved_compute, warning


def runtime_warning() -> str | None:
    """Return a non-fatal warning for the dependency/UI health report."""
    _device, _compute, warning = resolve_runtime("auto", "default")
    return warning


def _complete_model_path(model_size: str) -> Path | None:
    candidate = Path(model_size).expanduser()
    if candidate.is_dir():
        return candidate if (candidate / "model.bin").is_file() else None

    from faster_whisper.utils import download_model

    try:
        candidate = Path(download_model(model_size, local_files_only=True))
    except (OSError, RuntimeError, ValueError):
        return None
    return candidate if (candidate / "model.bin").is_file() else None


def _model_cache_bytes(model_size: str) -> int:
    try:
        from faster_whisper.utils import _MODELS
        from huggingface_hub.constants import HF_HUB_CACHE

        repo_id = _MODELS.get(model_size, model_size)
        cache_name = "models--" + repo_id.replace("/", "--")
        blob_dir = Path(HF_HUB_CACHE) / cache_name / "blobs"
        return sum(path.stat().st_size for path in blob_dir.iterdir() if path.is_file())
    except (OSError, ValueError):
        return 0


def _download_model(model_size: str, progress: TranscriptionProgress | None) -> Path:
    from faster_whisper.utils import download_model

    expected_mb = WHISPER_MODEL_DOWNLOAD_MB.get(model_size)
    stop = threading.Event()

    def monitor() -> None:
        last_message = ""
        while not stop.wait(2):
            downloaded_mb = _model_cache_bytes(model_size) // (1024 * 1024)
            if expected_mb:
                percent = min(99, round(downloaded_mb / expected_mb * 100))
                message = (
                    f"Downloading {model_size} AI model — {downloaded_mb} of "
                    f"~{expected_mb} MB ({percent}%)"
                )
                pipeline_progress = 31 + min(7, round(percent * 0.07))
            else:
                message = f"Downloading {model_size} AI model — {downloaded_mb} MB received"
                pipeline_progress = 32
            if progress and message != last_message:
                progress(pipeline_progress, message)
                last_message = message

    if progress:
        size_hint = f" (~{expected_mb} MB)" if expected_mb else ""
        progress(31, f"Downloading {model_size} AI model{size_hint} — one-time setup")
    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    try:
        path = Path(download_model(model_size))
    except Exception as exc:
        raise RuntimeError(
            f"Could not download the local Whisper '{model_size}' model. "
            "Check the internet connection and retry; partial downloads resume automatically. "
            f"({exc})"
        ) from exc
    finally:
        stop.set()
        monitor_thread.join(3)

    if not (path / "model.bin").is_file():
        raise RuntimeError(
            f"Whisper model '{model_size}' download is incomplete (model.bin is missing). Retry."
        )
    return path


def ensure_model(model_size: str, progress: TranscriptionProgress | None = None) -> Path:
    """Resolve a complete cached model, downloading it once when necessary."""
    path = _complete_model_path(model_size)
    if path is not None:
        if progress:
            progress(34, f"Using cached {model_size} transcription model")
        return path
    return _download_model(model_size, progress)


def _collect_segments(
    raw_segments: Iterator[Any],
    duration: float | None,
    progress: TranscriptionProgress | None,
) -> list[TranscriptSegment]:
    segments: list[TranscriptSegment] = []
    last_progress = 39
    for segment in raw_segments:
        if segment.text.strip():
            segments.append(
                TranscriptSegment(
                    float(segment.start),
                    float(segment.end),
                    segment.text.strip(),
                    tuple(
                        TranscriptWord(float(word.start), float(word.end), word.word)
                        for word in (segment.words or [])
                    ),
                )
            )
        if progress and duration:
            current = 39 + min(16, int(float(segment.end) / duration * 16))
            if current > last_progress:
                video_percent = min(100, round(float(segment.end) / duration * 100))
                progress(current, f"Transcribing locally — {video_percent}% of video processed")
                last_progress = current
    return segments


def _transcribe_with_runtime(
    model_path: Path,
    video_path: Path,
    device: str,
    compute_type: str,
    duration: float | None,
    progress: TranscriptionProgress | None,
) -> tuple[list[TranscriptSegment], str | None]:
    from faster_whisper import WhisperModel

    LOGGER.info("Loading faster-whisper on %s with %s", device, compute_type)
    if progress:
        progress(38, f"Loading transcription model on {device.upper()} ({compute_type})")
    model = WhisperModel(str(model_path), device=device, compute_type=compute_type)
    raw_segments, info = model.transcribe(
        str(video_path), vad_filter=True, beam_size=3, word_timestamps=True
    )
    segments = _collect_segments(raw_segments, duration, progress)
    return segments, info.language


def transcribe_video(
    video_path: Path,
    model_size: str = DEFAULT_WHISPER_MODEL,
    device: str = DEFAULT_WHISPER_DEVICE,
    compute_type: str = DEFAULT_WHISPER_COMPUTE_TYPE,
    duration: float | None = None,
    progress_callback: TranscriptionProgress | None = None,
) -> tuple[list[TranscriptSegment], str | None]:
    LOGGER.info("Preparing faster-whisper model '%s'", model_size)
    if progress_callback:
        progress_callback(30, f"Preparing {model_size} transcription model")
    model_path = ensure_model(model_size, progress_callback)
    resolved_device, resolved_compute, warning = resolve_runtime(device, compute_type)
    if warning:
        LOGGER.warning("%s", warning)
        if progress_callback:
            progress_callback(37, warning)

    LOGGER.info("Transcribing audio locally")
    try:
        segments, language = _transcribe_with_runtime(
            model_path,
            video_path,
            resolved_device,
            resolved_compute,
            duration,
            progress_callback,
        )
    except RuntimeError as exc:
        cuda_failure = resolved_device == "cuda" and device == "auto"
        if not cuda_failure:
            raise
        LOGGER.warning("CUDA transcription failed; retrying on CPU: %s", exc)
        if progress_callback:
            progress_callback(38, "GPU startup failed — retrying with optimized CPU mode")
        segments, language = _transcribe_with_runtime(
            model_path,
            video_path,
            "cpu",
            "int8",
            duration,
            progress_callback,
        )

    LOGGER.info("Transcription complete: %d segments, language=%s", len(segments), language)
    return segments, language
