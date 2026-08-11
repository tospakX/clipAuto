from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

from .analysis_cache import load_analysis, save_analysis
from .boundaries import find_marker_times, fuse_boundaries
from .config import (
    DEFAULT_OLLAMA_URL,
    DEFAULT_WHISPER_COMPUTE_TYPE,
    DEFAULT_WHISPER_DEVICE,
    DEFAULT_WHISPER_MODEL,
)
from .dependencies import check_dependencies
from .downloader import download_video
from .exporter import export_clips
from .media import get_duration
from .ollama import OllamaBoundaryReasoner
from .scenes import detect_scene_changes
from .transcriber import transcribe_video

LOGGER = logging.getLogger(__name__)
ProgressCallback = Callable[[int, str], None]


def _report(callback: ProgressCallback | None, progress: int, stage: str) -> None:
    if callback is not None:
        callback(progress, stage)


def run_pipeline(
    url: str,
    output_dir: Path,
    work_dir: Path,
    speed: float = 1.0,
    whisper_model: str = DEFAULT_WHISPER_MODEL,
    whisper_device: str = DEFAULT_WHISPER_DEVICE,
    whisper_compute_type: str = DEFAULT_WHISPER_COMPUTE_TYPE,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    progress_callback: ProgressCallback | None = None,
) -> list[Path]:
    _report(progress_callback, 3, "Checking local tools")
    LOGGER.info("Checking local dependencies")
    report = check_dependencies(ollama_url)
    LOGGER.info("Dependency check passed; Ollama models: %s", ", ".join(report.ollama_models))
    _report(progress_callback, 10, "Downloading the source video")
    download = download_video(url, work_dir)
    video_path = download.path
    timestamp_note = (
        f"{len(download.timestamps)} description timestamps found"
        if download.timestamps
        else "No description timestamps found"
    )
    _report(progress_callback, 24, timestamp_note)
    duration = get_duration(video_path)
    cached = load_analysis(work_dir, video_path, whisper_model)
    if cached is None:
        _report(progress_callback, 30, "Preparing local transcription")
        segments, language = transcribe_video(
            video_path,
            whisper_model,
            whisper_device,
            whisper_compute_type,
            duration,
            progress_callback,
        )
        if not segments:
            raise RuntimeError(
                "Transcription produced no speech segments; topic detection cannot continue"
            )
        _report(progress_callback, 56, "Finding visual transitions")
        scene_times = detect_scene_changes(video_path)
        save_analysis(work_dir, video_path, whisper_model, segments, language, scene_times)
    else:
        LOGGER.info("Using cached transcript and scene analysis for %s", video_path)
        _report(progress_callback, 30, "Using cached video analysis")
        segments = cached.segments
        scene_times = cached.scene_times
        _report(progress_callback, 56, "Cached analysis loaded")
    if not segments:
        raise RuntimeError(
            "Transcription produced no speech segments; topic detection cannot continue"
        )
    marker_times = find_marker_times(segments)
    LOGGER.info("Found %d explicit spoken topic markers", len(marker_times))
    LOGGER.info("Using %d YouTube description/chapter timestamps", len(download.timestamps))
    _report(progress_callback, 68, "Reasoning about topic changes")
    suggestions = OllamaBoundaryReasoner(ollama_url).suggest_boundaries(
        segments, scene_times, marker_times, download.timestamps
    )
    LOGGER.info("Ollama suggested %d semantic topic boundaries", len(suggestions))
    _report(progress_callback, 79, "Combining boundary evidence")
    starts = fuse_boundaries(
        segments,
        scene_times,
        suggestions,
        duration,
        video_timestamps=download.timestamps,
    )
    LOGGER.info("Final topic split: %d clips at %s", len(starts), starts)
    _report(progress_callback, 86, f"Exporting {len(starts)} clips")
    outputs = export_clips(
        video_path,
        starts,
        duration,
        output_dir,
        speed,
        lambda current, total: _report(
            progress_callback,
            86 + round(current / total * 13),
            f"Exporting clip {current} of {total}",
        ),
    )
    LOGGER.info("Finished: wrote %d clips to %s", len(outputs), output_dir)
    _report(progress_callback, 100, "Your clips are ready")
    return outputs
