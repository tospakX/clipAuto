from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from clipauto.config import Settings
from clipauto.models import ClipRecord, JobRecord, Topic
from clipauto.store import JobStore
from clipauto.topics import partition_topic_groups


@dataclass(slots=True)
class RegroupSummary:
    jobs_seen: int = 0
    jobs_changed: int = 0
    clips_before: int = 0
    clips_after: int = 0
    failures: list[str] = field(default_factory=list)


def _managed_clip(path: str, job_root: Path) -> Path:
    candidate = Path(path).resolve()
    if not candidate.is_relative_to(job_root.resolve()) or not candidate.is_file():
        raise FileNotFoundError(f"Managed clip is unavailable: {path}")
    return candidate


def _write_concat_manifest(path: Path, sources: list[Path]) -> None:
    lines = []
    for source in sources:
        escaped = str(source.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'\n")
    path.write_text("".join(lines), encoding="utf-8")


def _concat_mp4s(sources: list[Path], manifest: Path, output: Path) -> None:
    _write_concat_manifest(manifest, sources)
    result = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(manifest),
            "-map",
            "0:v:0",
            "-map",
            "0:a?",
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip()[-1000:] or "unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg concat failed: {detail}")


def _probe_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.strip()[-1000:]}")
    try:
        duration = float(json.loads(result.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise RuntimeError("ffprobe did not return a valid duration") from error
    if duration <= 0:
        raise RuntimeError(f"ffprobe returned a non-positive duration for {path}")
    return duration


def _validate_duration(path: Path, expected: float) -> None:
    duration = _probe_duration(path)
    tolerance = max(2.0, expected * 0.08)
    if abs(duration - expected) > tolerance:
        raise RuntimeError(
            f"Combined clip duration {duration:.2f}s differs from expected {expected:.2f}s"
        )


def _regroup_job(
    store: JobStore,
    job: JobRecord,
    data_dir: Path,
    minimum: float,
    maximum: float,
) -> int | None:
    if not job.clips:
        return None
    job_root = (Path(data_dir) / "jobs" / job.id).resolve()
    sources = [_managed_clip(clip.path, job_root) for clip in job.clips]
    media_durations = {source: _probe_duration(source) for source in sources}
    topics = [Topic(clip.title, clip.start, clip.end) for clip in job.clips]
    groups = partition_topic_groups(topics, minimum, maximum)
    if all(len(group) == 1 for group in groups):
        return None

    clip_by_topic = {id(topic): clip for topic, clip in zip(topics, job.clips, strict=True)}
    source_by_clip_id = {clip.id: source for clip, source in zip(job.clips, sources, strict=True)}
    staging = job_root / f".regroup-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    moved: list[Path] = []
    replacements: list[ClipRecord] = []
    superseded: set[Path] = set()
    try:
        for index, group in enumerate(groups):
            group_clips = [clip_by_topic[id(topic)] for topic in group]
            if len(group) == 1:
                clip = group_clips[0]
                replacements.append(
                    ClipRecord(
                        clip.id,
                        job.id,
                        index,
                        clip.title,
                        clip.start,
                        clip.end,
                        clip.path,
                    )
                )
                continue

            group_sources = [source_by_clip_id[clip.id] for clip in group_clips]
            staged_output = staging / f"group_{index + 1:04d}.mp4"
            manifest = staging / f"group_{index + 1:04d}.txt"
            _concat_mp4s(group_sources, manifest, staged_output)
            expected = sum(media_durations[source] for source in group_sources)
            _validate_duration(staged_output, expected)
            permanent = job_root / "clips" / f"regroup_{uuid.uuid4().hex}.mp4"
            staged_output.replace(permanent)
            moved.append(permanent)
            superseded.update(group_sources)
            replacements.append(
                ClipRecord(
                    uuid.uuid4().hex,
                    job.id,
                    index,
                    " + ".join(clip.title for clip in group_clips),
                    group_clips[0].start,
                    group_clips[-1].end,
                    str(permanent),
                )
            )

        store.replace_clips_and_plan(job.id, replacements)
    except Exception:
        for path in moved:
            path.unlink(missing_ok=True)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)

    retained = {Path(clip.path).resolve() for clip in replacements}
    for path in superseded - retained:
        path.unlink(missing_ok=True)
        path.with_suffix(".ass").unlink(missing_ok=True)
    return len(replacements)


def regroup_completed_jobs(
    store: JobStore,
    data_dir: Path,
    progress: Callable[[str], None] | None = None,
    minimum: float = 44.0,
    maximum: float = 66.0,
) -> RegroupSummary:
    report = progress or (lambda _message: None)
    summary = RegroupSummary()
    for job in store.list_completed_jobs():
        summary.jobs_seen += 1
        summary.clips_before += len(job.clips)
        try:
            result = _regroup_job(store, job, data_dir, minimum, maximum)
        except Exception as error:
            summary.clips_after += len(job.clips)
            message = f"{job.id} ({job.title or job.url}): {error}"
            summary.failures.append(message)
            report(f"FAILED {message}")
            continue
        final_count = result if result is not None else len(job.clips)
        summary.clips_after += final_count
        if result is None:
            report(f"UNCHANGED {job.title or job.url}: {len(job.clips)} clips")
        else:
            summary.jobs_changed += 1
            report(f"REGROUPED {job.title or job.url}: {len(job.clips)} -> {result} clips")
    return summary


def main() -> None:
    settings = Settings()
    store = JobStore(settings.database_path)
    summary = regroup_completed_jobs(store, settings.data_dir, print)
    print(
        f"Completed: {summary.jobs_changed}/{summary.jobs_seen} videos changed; "
        f"{summary.clips_before} -> {summary.clips_after} clips; "
        f"{len(summary.failures)} failures"
    )
    if summary.failures:
        raise SystemExit(1)
