from __future__ import annotations

import re
import shutil
import uuid
from pathlib import Path

from clipauto.models import BatchRecord, JobStatus


def _safe_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return name[:80] or fallback


def export_batch_mp4s(
    batch: BatchRecord,
    destination_root: Path,
    media_root: Path,
) -> tuple[Path, int]:
    allowed = (media_root / "jobs").resolve()
    entries: list[tuple[Path, str]] = []
    for job in batch.jobs:
        if job.status is not JobStatus.COMPLETED:
            continue
        video_name = _safe_name(job.title or f"video_{job.position + 1}", "video")
        for clip in job.clips:
            source = Path(clip.path).resolve()
            if not source.is_relative_to(allowed) or not source.is_file():
                raise ValueError("A completed clip file is unavailable")
            topic = _safe_name(clip.title, "topic")
            filename = (
                f"video_{job.position + 1:03d}_{video_name}_topic_{clip.index + 1:03d}_{topic}.mp4"
            )
            entries.append((source, filename))
    if not entries:
        raise ValueError("No completed clips are available to export")

    destination_root = destination_root.expanduser().resolve()
    folder = destination_root / f"ClipAuto-{batch.id[:8]}-{uuid.uuid4().hex[:8]}"
    try:
        folder.mkdir(parents=True)
        for source, filename in entries:
            shutil.copy2(source, folder / filename)
    except OSError:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return folder, len(entries)
