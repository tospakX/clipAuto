from __future__ import annotations

import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .types import VideoTimestamp

LOGGER = logging.getLogger(__name__)
_TIME_TOKEN = r"(?:\d{1,2}:)?\d{1,3}:[0-5]\d"
_TIME_AT_START = re.compile(
    rf"^\s*(?:[-*•]\s*)?[\[(]?(?P<time>{_TIME_TOKEN})[\])]?"
    r"\s*(?:[-–—|:]\s*)?(?P<title>\S.*)?$"
)
_TIME_AT_END = re.compile(
    rf"^\s*(?P<title>\S.*?\S)\s+(?:[-–—|]\s*)?[\[(]?(?P<time>{_TIME_TOKEN})[\])]?\s*$"
)


@dataclass(frozen=True)
class DownloadedVideo:
    path: Path
    timestamps: tuple[VideoTimestamp, ...] = ()


def _time_in_seconds(value: str) -> float | None:
    parts = [int(part) for part in value.split(":")]
    if len(parts) == 2:
        minutes, seconds = parts
        return float(minutes * 60 + seconds)
    if len(parts) == 3:
        hours, minutes, seconds = parts
        if minutes >= 60:
            return None
        return float(hours * 3600 + minutes * 60 + seconds)
    return None


def parse_description_timestamps(description: str) -> list[VideoTimestamp]:
    """Parse timestamped description lines without treating arbitrary numbers as chapters."""
    parsed: list[tuple[float, str]] = []
    for line in description.splitlines():
        match = _TIME_AT_START.fullmatch(line) or _TIME_AT_END.fullmatch(line)
        if not match:
            continue
        title = (match.group("title") or "").strip(" -–—|:[]()")
        timestamp = _time_in_seconds(match.group("time"))
        if timestamp is not None and title:
            parsed.append((timestamp, title))

    # A list is reliable chapter evidence. A lone mention is still passed to Ollama,
    # but starts below the automatic fusion threshold unless another signal supports it.
    confidence = 0.82 if len(parsed) >= 2 else 0.5
    return [VideoTimestamp(timestamp, title, confidence) for timestamp, title in parsed]


def timestamps_from_metadata(metadata: dict) -> tuple[VideoTimestamp, ...]:
    candidates = parse_description_timestamps(str(metadata.get("description") or ""))
    for chapter in metadata.get("chapters") or []:
        if not isinstance(chapter, dict):
            continue
        try:
            timestamp = float(chapter["start_time"])
        except (KeyError, TypeError, ValueError):
            continue
        title = str(chapter.get("title") or "").strip()
        if timestamp >= 0 and title:
            candidates.append(VideoTimestamp(timestamp, title, 0.95))

    deduplicated: list[VideoTimestamp] = []
    for candidate in sorted(candidates, key=lambda item: (item.timestamp, -item.confidence)):
        duplicate = next(
            (
                index
                for index, existing in enumerate(deduplicated)
                if abs(existing.timestamp - candidate.timestamp) <= 1.0
            ),
            None,
        )
        if duplicate is None:
            deduplicated.append(candidate)
        elif candidate.confidence > deduplicated[duplicate].confidence:
            deduplicated[duplicate] = candidate
    return tuple(deduplicated)


def _read_metadata(video_path: Path) -> dict:
    metadata_path = video_path.with_suffix(".info.json")
    if not metadata_path.is_file():
        LOGGER.warning("yt-dlp metadata file was not created; skipping description timestamps")
        return {}
    try:
        with metadata_path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Could not read yt-dlp metadata %s: %s", metadata_path, exc)
        return {}


def download_video(url: str, work_dir: Path) -> DownloadedVideo:
    work_dir.mkdir(parents=True, exist_ok=True)
    # Include the YouTube ID so a later job cannot silently reuse a different video's source.
    output_template = str(work_dir / "source_%(id)s.%(ext)s")
    command = [
        "yt-dlp",
        "--no-playlist",
        "--format",
        "bestvideo*[vcodec^=avc1]+bestaudio/best[vcodec^=avc1]/bestvideo*+bestaudio/best",
        "--merge-output-format",
        "mp4",
        "--write-info-json",
        "--print",
        "after_move:filepath",
        "-o",
        output_template,
        url,
    ]
    LOGGER.info("Downloading source video with yt-dlp")
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode:
        detail = result.stderr.strip().splitlines()
        message = detail[-1] if detail else f"exit status {result.returncode}"
        raise RuntimeError(f"yt-dlp download failed: {message}")
    paths = [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
    if not paths or not paths[-1].is_file():
        raise RuntimeError("yt-dlp completed but did not report a downloaded video path")
    video_path = paths[-1]
    timestamps = timestamps_from_metadata(_read_metadata(video_path))
    LOGGER.info("Downloaded video: %s", video_path)
    LOGGER.info("Found %d YouTube description/chapter timestamps", len(timestamps))
    return DownloadedVideo(video_path, timestamps)
