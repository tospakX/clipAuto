from __future__ import annotations

import json
import logging
import re
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from .config import SCENE_DETECTION_THRESHOLD
from .types import TranscriptSegment, TranscriptWord

LOGGER = logging.getLogger(__name__)
CACHE_VERSION = 2


@dataclass(frozen=True)
class CachedAnalysis:
    segments: list[TranscriptSegment]
    language: str | None
    scene_times: list[float]


def _cache_path(work_dir: Path, video_path: Path, model_size: str) -> Path:
    safe_model = re.sub(r"[^a-zA-Z0-9_.-]+", "_", model_size)
    return work_dir / f"analysis_{video_path.stem}_{safe_model}.json"


def _source_fingerprint(video_path: Path) -> dict[str, int] | None:
    try:
        stat = video_path.stat()
    except OSError:
        return None
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def load_analysis(work_dir: Path, video_path: Path, model_size: str) -> CachedAnalysis | None:
    fingerprint = _source_fingerprint(video_path)
    if fingerprint is None:
        return None
    path = _cache_path(work_dir, video_path, model_size)
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            payload.get("version") != CACHE_VERSION
            or payload.get("source") != fingerprint
            or payload.get("model") != model_size
            or payload.get("scene_threshold") != SCENE_DETECTION_THRESHOLD
        ):
            return None
        segments = [
            TranscriptSegment(
                float(item["start"]),
                float(item["end"]),
                str(item["text"]),
                tuple(
                    TranscriptWord(float(word["start"]), float(word["end"]), str(word["text"]))
                    for word in item.get("words", [])
                ),
            )
            for item in payload["segments"]
        ]
        scene_times = [float(value) for value in payload["scene_times"]]
        language = payload.get("language")
        return CachedAnalysis(segments, str(language) if language else None, scene_times)
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError) as exc:
        LOGGER.warning("Ignoring invalid analysis cache %s: %s", path, exc)
        return None


def save_analysis(
    work_dir: Path,
    video_path: Path,
    model_size: str,
    segments: list[TranscriptSegment],
    language: str | None,
    scene_times: list[float],
) -> None:
    fingerprint = _source_fingerprint(video_path)
    if fingerprint is None:
        return
    path = _cache_path(work_dir, video_path, model_size)
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = {
        "version": CACHE_VERSION,
        "source": fingerprint,
        "model": model_size,
        "scene_threshold": SCENE_DETECTION_THRESHOLD,
        "language": language,
        "scene_times": scene_times,
        "segments": [
            {
                "start": segment.start,
                "end": segment.end,
                "text": segment.text,
                "words": [
                    {"start": word.start, "end": word.end, "text": word.text}
                    for word in segment.words
                ],
            }
            for segment in segments
        ],
    }
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)
        LOGGER.info("Saved reusable transcript and scene analysis to %s", path)
    except OSError as exc:
        LOGGER.warning("Could not save analysis cache %s: %s", path, exc)
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
