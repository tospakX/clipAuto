from __future__ import annotations

import logging
import re
import subprocess
import uuid
from collections.abc import Callable
from contextlib import suppress
from pathlib import Path

from .config import (
    ALLOWED_SPEEDS,
    OUTPUT_AUDIO_BITRATE,
    OUTPUT_AUDIO_CODEC,
    OUTPUT_CRF,
    OUTPUT_HEIGHT,
    OUTPUT_VIDEO_CODEC,
    OUTPUT_WIDTH,
)
from .naming import safe_component

LOGGER = logging.getLogger(__name__)
ExportProgress = Callable[[int, int], None]


def build_ffmpeg_command(
    source: Path, output: Path, start: float, end: float, speed: float
) -> list[str]:
    if start < 0 or end <= start:
        raise ValueError("clip timestamps must satisfy 0 <= start < end")
    if speed not in ALLOWED_SPEEDS:
        raise ValueError(f"speed must be one of {ALLOWED_SPEEDS}")
    duration = end - start
    video_filter = (
        f"scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:force_original_aspect_ratio=decrease,"
        f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
    )
    audio_filter = None
    if speed != 1.0:
        video_filter += f",setpts=PTS/{speed:g}"
        # FFmpeg's atempo changes tempo while preserving perceived pitch.
        audio_filter = f"atempo={speed:g}"
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        video_filter,
    ]
    if audio_filter:
        command.extend(["-af", audio_filter])
    command.extend(
        [
            "-c:v",
            OUTPUT_VIDEO_CODEC,
            "-preset",
            "medium",
            "-crf",
            str(OUTPUT_CRF),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            OUTPUT_AUDIO_CODEC,
            "-b:a",
            OUTPUT_AUDIO_BITRATE,
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    return command


def export_clips(
    source: Path,
    starts: list[float],
    duration: float,
    output_dir: Path,
    speed: float = 1.0,
    progress_callback: ExportProgress | None = None,
    clip_names: list[str] | None = None,
) -> list[Path]:
    if speed not in ALLOWED_SPEEDS:
        raise ValueError(f"speed must be one of {ALLOWED_SPEEDS}")
    if duration <= 0:
        raise ValueError("video duration must be positive")
    if not starts:
        raise ValueError("at least one clip boundary is required")
    if any(start < 0 or start >= duration for start in starts):
        raise ValueError("clip boundaries must be inside the video duration")
    if any(current >= following for current, following in zip(starts, starts[1:], strict=False)):
        raise ValueError("clip boundaries must be in strictly increasing order")
    if clip_names is not None and len(clip_names) != len(starts):
        raise ValueError("provide exactly one name per clip boundary")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    pending_outputs: list[Path] = []
    ends = starts[1:] + [duration]
    token = uuid.uuid4().hex[:8]
    number_width = max(2, len(str(len(starts))))
    try:
        for index, (start, end) in enumerate(zip(starts, ends, strict=True), start=1):
            if clip_names is None:
                filename = f"part_{index:02d}.mp4"
            else:
                topic = safe_component(clip_names[index - 1], f"topic-{index:02d}", 64)
                filename = f"{index:0{number_width}d}_{topic}.mp4"
            output = output_dir / filename
            pending = output_dir / f".{output.stem}.{token}.pending.mp4"
            pending_outputs.append(pending)
            LOGGER.info("Exporting part %02d (%.2fs to %.2fs)", index, start, end)
            try:
                subprocess.run(
                    build_ffmpeg_command(source, pending, start, end, speed),
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as exc:
                detail = (exc.stderr or "").strip().splitlines()
                message = f": {detail[-1]}" if detail else ""
                raise RuntimeError(
                    f"FFmpeg failed while exporting part {index:02d}{message}"
                ) from exc
            if not pending.is_file():
                raise RuntimeError(f"FFmpeg did not create part {index:02d}")
            outputs.append(output)
            if progress_callback:
                progress_callback(index, len(starts))

        # Publish only after every clip encoded successfully, preserving the previous set on
        # encoding failures.
        for pending, output in zip(pending_outputs, outputs, strict=True):
            pending.replace(output)
    finally:
        for pending in pending_outputs:
            with suppress(OSError):
                pending.unlink(missing_ok=True)

    # Remove only obsolete files created by this tool, and only after every new export succeeds.
    output_names = {path.name for path in outputs}
    managed_pattern = r"part_\d+\.mp4" if clip_names is None else r"\d{2,}_[a-z0-9._-]+\.mp4"
    for old_output in output_dir.glob("*.mp4"):
        if re.fullmatch(managed_pattern, old_output.name) and old_output.name not in output_names:
            old_output.unlink()
    return outputs
