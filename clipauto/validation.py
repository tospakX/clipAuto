from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


class MediaValidationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ReelMediaInfo:
    duration: float
    width: int
    height: int
    video_codec: str
    pixel_format: str
    audio_codec: str | None


def _run(command: list[str], label: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise MediaValidationError(f"Media {label} could not run: {error}") from error


def validate_reel(path: Path, expected_duration: float) -> ReelMediaInfo:
    path = Path(path)
    if not path.is_file() or path.stat().st_size <= 0:
        raise MediaValidationError(f"Rendered clip is missing or empty: {path}")
    if expected_duration <= 0:
        raise MediaValidationError("Expected reel duration must be positive")

    probe = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration,format_name:stream=codec_type,codec_name,width,height,pix_fmt",
            "-of",
            "json",
            str(path),
        ],
        "probe",
    )
    if probe.returncode != 0:
        detail = probe.stderr.strip()[-1000:] or "unknown ffprobe error"
        raise MediaValidationError(f"Media probe failed: {detail}")
    try:
        payload = json.loads(probe.stdout)
        duration = float(payload["format"]["duration"])
        format_name = str(payload["format"]["format_name"])
        video = next(
            stream for stream in payload["streams"] if stream.get("codec_type") == "video"
        )
        audio = next(
            (
                stream
                for stream in payload["streams"]
                if stream.get("codec_type") == "audio"
            ),
            None,
        )
        width = int(video["width"])
        height = int(video["height"])
        video_codec = str(video["codec_name"])
        pixel_format = str(video["pix_fmt"])
        audio_codec = str(audio["codec_name"]) if audio is not None else None
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError) as error:
        raise MediaValidationError("Media probe returned incomplete clip metadata") from error

    if "mp4" not in format_name:
        raise MediaValidationError(f"Rendered clip is not an MP4 container: {format_name}")
    if video_codec != "h264":
        raise MediaValidationError(f"Rendered clip must use H.264 video, got {video_codec}")
    if (width, height) != (1080, 1920):
        raise MediaValidationError(
            f"Rendered clip must be 1080x1920, got {width}x{height}"
        )
    if pixel_format != "yuv420p":
        raise MediaValidationError(
            f"Rendered clip must use yuv420p pixels, got {pixel_format}"
        )
    if audio_codec not in {None, "aac"}:
        raise MediaValidationError(f"Rendered clip audio must use AAC, got {audio_codec}")

    tolerance = max(0.75, expected_duration * 0.02)
    if abs(duration - expected_duration) > tolerance:
        raise MediaValidationError(
            f"Rendered clip duration {duration:.2f}s differs from expected "
            f"{expected_duration:.2f}s"
        )

    packets = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=pts_time,duration_time",
            "-of",
            "csv=p=0",
            str(path),
        ],
        "packet scan",
    )
    if packets.returncode != 0:
        detail = packets.stderr.strip()[-1000:] or "unknown packet scan error"
        raise MediaValidationError(f"Media packet scan failed: {detail}")
    packet_end = 0.0
    try:
        for line in packets.stdout.splitlines():
            values = [float(value) for value in line.split(",") if value and value != "N/A"]
            if values:
                packet_end = max(packet_end, sum(values[:2]))
    except ValueError as error:
        raise MediaValidationError("Media packet scan returned invalid timestamps") from error
    if packet_end <= 0 or duration - packet_end > max(0.5, duration * 0.02):
        raise MediaValidationError(
            f"Rendered clip is corrupt or truncated at {packet_end:.2f}s of {duration:.2f}s"
        )

    decode = _run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-xerror",
            "-i",
            str(path),
            "-map",
            "0",
            "-f",
            "null",
            "-",
        ],
        "decode",
    )
    if decode.returncode != 0:
        detail = decode.stderr.strip()[-1000:] or "unknown FFmpeg decode error"
        raise MediaValidationError(f"Rendered clip is corrupt or failed full decode: {detail}")

    return ReelMediaInfo(
        duration,
        width,
        height,
        video_codec,
        pixel_format,
        audio_codec,
    )
