from __future__ import annotations

import subprocess
from pathlib import Path

from clipauto.models import ClipRecord, JobStatus, Stage
from clipauto.regroup import regroup_completed_jobs
from clipauto.store import JobStore


def _make_mp4(path: Path, color: str, frequency: int, duration: int = 1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color={color}:size=160x90:rate=12:duration={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=44100:duration={duration}",
            "-shortest",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(path),
        ],
        check=True,
    )


def test_regroups_completed_mp4s_in_order_and_replaces_records(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = JobStore(data_dir / "clipauto.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    work_dir = data_dir / "jobs" / job.id
    clips = []
    original_paths = []
    for index, (color, frequency) in enumerate([("red", 300), ("green", 500), ("blue", 700)]):
        path = work_dir / "clips" / f"clip_{index + 1:02d}.mp4"
        _make_mp4(path, color, frequency)
        original_paths.append(path)
        clips.append(ClipRecord(f"old-{index}", job.id, index, color, index, index + 1, str(path)))
    store.update_job(
        job.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        progress=1,
        title="Colors",
        work_dir=str(work_dir),
        planned_clips=3,
    )
    store.replace_clips(job.id, clips)

    summary = regroup_completed_jobs(store, data_dir, minimum=2.5, maximum=3.5)

    migrated = store.get_job(job.id)
    assert summary.jobs_seen == 1
    assert summary.jobs_changed == 1
    assert summary.clips_before == 3
    assert summary.clips_after == 1
    assert summary.failures == []
    assert migrated.planned_clips == 1
    assert [(clip.title, clip.start, clip.end) for clip in migrated.clips] == [
        ("red + green + blue", 0, 3)
    ]
    assert Path(migrated.clips[0].path).is_file()
    assert Path(migrated.clips[0].path).stat().st_size > 0
    assert all(not path.exists() for path in original_paths)


def test_failed_regroup_keeps_original_records_and_media(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = JobStore(data_dir / "clipauto.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    work_dir = data_dir / "jobs" / job.id
    valid = work_dir / "clips" / "clip_01.mp4"
    _make_mp4(valid, "red", 300)
    missing = work_dir / "clips" / "clip_02.mp4"
    original = [
        ClipRecord("old-1", job.id, 0, "red", 0, 1, str(valid)),
        ClipRecord("old-2", job.id, 1, "missing", 1, 2, str(missing)),
    ]
    store.update_job(
        job.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        progress=1,
        title="Incomplete files",
        work_dir=str(work_dir),
        planned_clips=2,
    )
    store.replace_clips(job.id, original)

    summary = regroup_completed_jobs(store, data_dir, minimum=1.5, maximum=2.5)

    persisted = store.get_job(job.id)
    assert summary.jobs_seen == 1
    assert summary.jobs_changed == 0
    assert len(summary.failures) == 1
    assert [clip.id for clip in persisted.clips] == ["old-1", "old-2"]
    assert persisted.planned_clips == 2
    assert valid.is_file()


def test_regroup_validates_against_sped_media_duration_not_source_timestamps(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = JobStore(data_dir / "clipauto.db")
    job = store.create_batch(["https://youtu.be/sped"]).jobs[0]
    work_dir = data_dir / "jobs" / job.id
    clips = []
    for index, color in enumerate(["red", "green", "blue"]):
        path = work_dir / "clips" / f"clip_{index + 1:02d}.mp4"
        _make_mp4(path, color, 300 + index * 100, duration=10)
        clips.append(
            ClipRecord(
                f"sped-{index}",
                job.id,
                index,
                color,
                index * 11,
                (index + 1) * 11,
                str(path),
            )
        )
    store.update_job(
        job.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        progress=1,
        title="Sped clips",
        work_dir=str(work_dir),
        planned_clips=3,
    )
    store.replace_clips(job.id, clips)

    summary = regroup_completed_jobs(store, data_dir, minimum=30, maximum=35)

    assert summary.failures == []
    assert summary.jobs_changed == 1
    assert len(store.get_job(job.id).clips) == 1
