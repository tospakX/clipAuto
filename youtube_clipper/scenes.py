from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from .config import SCENE_DETECTION_THRESHOLD

LOGGER = logging.getLogger(__name__)


def _opencv_can_decode(video_path: Path) -> bool:
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    try:
        success, frame = capture.read()
        return bool(success and frame is not None)
    finally:
        capture.release()


def _detect(video_path: Path, threshold: float) -> list[float]:
    from scenedetect import ContentDetector, detect

    scene_list = detect(str(video_path), ContentDetector(threshold=threshold), show_progress=False)
    return [float(start.get_seconds()) for start, _ in scene_list[1:]]


def detect_scene_changes(
    video_path: Path, threshold: float = SCENE_DETECTION_THRESHOLD
) -> list[float]:
    LOGGER.info("Detecting visual scene changes")
    if _opencv_can_decode(video_path):
        boundaries = _detect(video_path, threshold)
    else:
        LOGGER.warning(
            "OpenCV cannot decode the source video; creating a temporary H.264 scene proxy"
        )
        with tempfile.TemporaryDirectory(prefix="localcut-scenes-") as temporary_dir:
            proxy = Path(temporary_dir) / "scene-proxy.mp4"
            command = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(video_path),
                "-an",
                "-vf",
                "scale=640:-2",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-crf",
                "30",
                str(proxy),
            ]
            try:
                subprocess.run(command, check=True)
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(
                    "FFmpeg could not create a compatible video for scene detection"
                ) from exc
            boundaries = _detect(proxy, threshold)
    LOGGER.info("Scene detection complete: %d transitions", len(boundaries))
    return boundaries
