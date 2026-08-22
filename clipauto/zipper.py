from __future__ import annotations

import re
import zipfile
from pathlib import Path

from clipauto.models import BatchRecord, JobStatus


def _safe_name(value: str, fallback: str) -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-")
    return name[:80] or fallback


def create_batch_zip(batch: BatchRecord, destination: Path) -> Path:
    entries: list[tuple[Path, str]] = []
    for job in batch.jobs:
        if job.status is not JobStatus.COMPLETED:
            continue
        video_name = _safe_name(job.title or f"video_{job.position + 1}", "video")
        directory = f"{job.position + 1:02d}_{video_name}"
        for clip in job.clips:
            source = Path(clip.path)
            if source.is_file():
                topic = _safe_name(clip.title, "topic")
                entries.append((source, f"{directory}/clip_{clip.index + 1:02d}_{topic}.mp4"))
    if not entries:
        raise ValueError("No completed clips are available to download")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(
        destination, "w", compression=zipfile.ZIP_STORED, allowZip64=True
    ) as archive:
        for source, archive_name in entries:
            archive.write(source, archive_name)
    return destination
