import sqlite3
from pathlib import Path

import pytest

from clipauto.models import ClipRecord, JobStatus, Stage
from clipauto.store import JobStore


def test_creates_200_jobs_in_durable_input_order(tmp_path: Path):
    db = tmp_path / "jobs.db"
    urls = [f"https://youtu.be/video{i}" for i in range(200)]
    store = JobStore(db)

    batch = store.create_batch(urls)
    reopened = JobStore(db)
    jobs = reopened.list_jobs(batch.id)

    assert [job.url for job in jobs] == urls
    assert all(job.status is JobStatus.QUEUED for job in jobs)
    assert all(job.stage is Stage.WAITING for job in jobs)
    assert [job.position for job in jobs] == list(range(200))


def test_updates_measured_stage_progress_and_metadata(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]

    store.update_job(
        job.id,
        status=JobStatus.RUNNING,
        stage=Stage.DOWNLOADING,
        progress=0.375,
        title="A real title",
    )

    updated = store.get_job(job.id)
    assert updated.status is JobStatus.RUNNING
    assert updated.stage is Stage.DOWNLOADING
    assert updated.progress == 0.375
    assert updated.title == "A real title"


def test_progress_is_clamped_to_valid_range(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]

    store.update_job(job.id, progress=7.2)

    assert store.get_job(job.id).progress == 1.0


def test_cancel_request_is_persisted(tmp_path: Path):
    db = tmp_path / "jobs.db"
    store = JobStore(db)
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]

    store.request_cancel(job.id)

    assert JobStore(db).get_job(job.id).cancel_requested is True


def test_replaces_and_orders_topic_clips(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    clips = [
        ClipRecord("", job.id, 1, "Second", 20.0, 43.0, "/tmp/02.mp4"),
        ClipRecord("", job.id, 0, "First", 0.0, 20.0, "/tmp/01.mp4"),
    ]

    store.replace_clips(job.id, clips)

    assert [(clip.index, clip.title) for clip in store.list_clips(job.id)] == [
        (0, "First"),
        (1, "Second"),
    ]


def test_lists_compact_jobs_with_clip_count_without_clip_records(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    store.replace_clips(
        job.id,
        [
            ClipRecord("one", job.id, 0, "One", 0, 20, "/clips/one.mp4"),
            ClipRecord("two", job.id, 1, "Two", 20, 40, "/clips/two.mp4"),
        ],
    )

    compact = store.list_jobs(job.batch_id, include_clips=False)

    assert compact[0].clip_count == 2
    assert compact[0].clips == []


def test_lists_pending_jobs_after_restart(tmp_path: Path):
    db = tmp_path / "jobs.db"
    store = JobStore(db)
    batch = store.create_batch(["https://youtu.be/one", "https://youtu.be/two"])
    store.update_job(batch.jobs[0].id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED)

    pending = JobStore(db).list_pending_jobs()

    assert [job.url for job in pending] == ["https://youtu.be/two"]


def test_deletes_only_finished_history_and_returns_its_work_directories(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    batch = store.create_batch(
        ["https://youtu.be/done", "https://youtu.be/active", "https://youtu.be/waiting"]
    )
    done, active, waiting = batch.jobs
    store.update_job(
        done.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        work_dir="/safe/jobs/done",
    )
    store.update_job(
        active.id,
        status=JobStatus.RUNNING,
        stage=Stage.DOWNLOADING,
        work_dir="/safe/jobs/active",
    )

    deleted_count, work_dirs = store.delete_finished_history()

    assert deleted_count == 2
    assert work_dirs == ["/safe/jobs/done"]
    assert [job.id for job in store.list_jobs(batch.id)] == [active.id]
    assert store.get_job(active.id).status is JobStatus.RUNNING
    with pytest.raises(KeyError):
        store.get_job(waiting.id)


def test_deletes_one_finished_job_without_touching_its_batch_siblings(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    batch = store.create_batch(["https://youtu.be/remove", "https://youtu.be/keep"])
    remove, keep = batch.jobs
    for job in batch.jobs:
        store.update_job(job.id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED)
    store.update_job(remove.id, work_dir="/safe/jobs/remove")

    work_dir, batch_deleted = store.delete_job(remove.id)

    assert work_dir == "/safe/jobs/remove"
    assert batch_deleted is False
    with pytest.raises(KeyError):
        store.get_job(remove.id)
    assert [job.id for job in store.get_batch(batch.id).jobs] == [keep.id]


def test_deletes_one_waiting_job_but_refuses_active_job(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    waiting, active = store.create_batch(
        ["https://youtu.be/waiting", "https://youtu.be/active"]
    ).jobs
    store.update_job(active.id, status=JobStatus.RUNNING, stage=Stage.RENDERING)

    store.delete_job(waiting.id)
    with pytest.raises(KeyError):
        store.get_job(waiting.id)

    with pytest.raises(ValueError, match="still processing"):
        store.delete_job(active.id)
    assert store.get_job(active.id).id == active.id


def test_deletes_one_completed_clip_and_preserves_its_sibling(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    store.update_job(
        job.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        planned_clips=2,
    )
    store.replace_clips(
        job.id,
        [
            ClipRecord("remove", job.id, 0, "Intro", 0, 5, "/clips/remove.mp4"),
            ClipRecord("keep", job.id, 1, "Main", 5, 65, "/clips/keep.mp4"),
        ],
    )

    deleted = store.delete_clip("remove")

    assert deleted.id == "remove"
    remaining = store.get_job(job.id)
    assert remaining.status is JobStatus.COMPLETED
    assert remaining.planned_clips == 1
    assert [clip.id for clip in remaining.clips] == ["keep"]
    assert [clip.index for clip in remaining.clips] == [0]


def test_refuses_to_delete_final_completed_clip(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    store.update_job(
        job.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        planned_clips=1,
    )
    store.replace_clips(
        job.id,
        [ClipRecord("only", job.id, 0, "Only topic", 0, 60, "/clips/only.mp4")],
    )

    with pytest.raises(ValueError, match="final clip"):
        store.delete_clip("only")

    assert [clip.id for clip in store.get_job(job.id).clips] == ["only"]


def test_delete_clip_rejects_unknown_id(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")

    with pytest.raises(KeyError):
        store.delete_clip("missing")


@pytest.mark.parametrize("status", [JobStatus.FAILED, JobStatus.CANCELLED])
def test_retries_terminal_job_with_clean_queue_state(tmp_path: Path, status: JobStatus):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/retry"]).jobs[0]
    store.update_job(
        job.id,
        status=status,
        stage=Stage.FAILED if status is JobStatus.FAILED else Stage.CANCELLED,
        progress=0.8,
        error="old error",
        work_dir="/safe/jobs/retry",
        planned_clips=2,
        cancel_requested=True,
    )
    store.replace_clips(
        job.id,
        [ClipRecord("old", job.id, 0, "Old clip", 0, 10, "/safe/jobs/retry/old.mp4")],
    )

    work_dir, retried = store.retry_job(job.id)

    assert work_dir == "/safe/jobs/retry"
    assert retried.status is JobStatus.QUEUED
    assert retried.stage is Stage.WAITING
    assert retried.progress == 0
    assert retried.error is None
    assert retried.work_dir is None
    assert retried.planned_clips == 0
    assert retried.cancel_requested is False
    assert retried.clips == []


def test_refuses_to_retry_completed_or_active_job(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    completed, active = store.create_batch(
        ["https://youtu.be/completed", "https://youtu.be/active"]
    ).jobs
    store.update_job(completed.id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED)
    store.update_job(active.id, status=JobStatus.RUNNING, stage=Stage.DOWNLOADING)

    for job in (completed, active):
        with pytest.raises(ValueError, match="Only failed or cancelled"):
            store.retry_job(job.id)


def test_completes_job_and_replaces_entire_clip_generation_atomically(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/atomic"]).jobs[0]
    store.update_job(job.id, status=JobStatus.RUNNING, stage=Stage.RENDERING, progress=0.8)
    store.replace_clips(
        job.id,
        [ClipRecord("old", job.id, 0, "Old", 0, 60, "/old/generation.mp4")],
    )
    replacements = [
        ClipRecord("", job.id, 0, "First", 0, 60, "/new/01.mp4"),
        ClipRecord("", job.id, 1, "Second", 60, 120, "/new/02.mp4"),
    ]

    store.complete_job(job.id, replacements)

    completed = store.get_job(job.id)
    assert completed.status is JobStatus.COMPLETED
    assert completed.stage is Stage.COMPLETED
    assert completed.progress == 1
    assert completed.planned_clips == 2
    assert completed.error is None
    assert [clip.title for clip in completed.clips] == ["First", "Second"]


def test_failed_complete_transaction_preserves_previous_generation(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/atomic"]).jobs[0]
    store.update_job(job.id, status=JobStatus.RUNNING, stage=Stage.RENDERING, progress=0.8)
    store.replace_clips(
        job.id,
        [ClipRecord("old", job.id, 0, "Old", 0, 60, "/old/generation.mp4")],
    )
    invalid = [
        ClipRecord("", job.id, 0, "First", 0, 60, "/new/01.mp4"),
        ClipRecord("", job.id, 0, "Duplicate index", 60, 120, "/new/02.mp4"),
    ]

    with pytest.raises(sqlite3.IntegrityError):
        store.complete_job(job.id, invalid)

    preserved = store.get_job(job.id)
    assert preserved.status is JobStatus.RUNNING
    assert preserved.stage is Stage.RENDERING
    assert [(clip.id, clip.path) for clip in preserved.clips] == [
        ("old", "/old/generation.mp4")
    ]
