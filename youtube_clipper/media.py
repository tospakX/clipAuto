from __future__ import annotations

import json
import subprocess
from pathlib import Path


def get_duration(video_path: Path) -> float:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "json",
                str(video_path),
            ],
            check=True,
            text=True,
            capture_output=True,
        )
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (subprocess.CalledProcessError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read video duration from {video_path}") from exc
    if duration <= 0:
        raise RuntimeError("Video duration must be greater than zero")
    return duration
