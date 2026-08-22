import asyncio
from pathlib import Path

import pytest

from clipauto.models import JobStatus, Stage
from clipauto.queue import JobQueue
from clipauto.store import JobStore


@pytest.mark.asyncio
async def test_processes_200_jobs_with_fixed_concurrency(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    batch = store.create_batch([f"https://youtu.be/video{i}" for i in range(200)])
    active = 0
    maximum = 0

    async def process(job_id, cancel_event):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.001)
        store.update_job(job_id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED, progress=1)
        active -= 1

    queue = JobQueue(store, process, worker_count=3)
    await queue.start(resume=False)
    for job in batch.jobs:
        await queue.enqueue(job.id)
    await queue.join()
    await queue.stop()

    assert maximum == 3
    assert all(job.status is JobStatus.COMPLETED for job in store.list_jobs(batch.id))


@pytest.mark.asyncio
async def test_resumes_persisted_waiting_jobs_in_fifo_order(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    batch = store.create_batch(["https://youtu.be/one", "https://youtu.be/two"])
    seen = []

    async def process(job_id, cancel_event):
        seen.append(job_id)
        store.update_job(job_id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED)

    queue = JobQueue(JobStore(tmp_path / "jobs.db"), process, worker_count=1)
    await queue.start(resume=True)
    await queue.join()
    await queue.stop()

    assert seen == [job.id for job in batch.jobs]


@pytest.mark.asyncio
async def test_worker_failure_does_not_block_following_job(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    batch = store.create_batch(["https://youtu.be/one", "https://youtu.be/two"])

    async def process(job_id, cancel_event):
        if job_id == batch.jobs[0].id:
            raise RuntimeError("adapter exploded")
        store.update_job(job_id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED)

    queue = JobQueue(store, process, worker_count=1)
    await queue.start(resume=False)
    for job in batch.jobs:
        await queue.enqueue(job.id)
    await queue.join()
    await queue.stop()

    assert store.get_job(batch.jobs[0].id).status is JobStatus.FAILED
    assert "adapter exploded" in store.get_job(batch.jobs[0].id).error
    assert store.get_job(batch.jobs[1].id).status is JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_cancels_waiting_job_without_processing_it(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    called = False

    async def process(job_id, cancel_event):
        nonlocal called
        called = True

    queue = JobQueue(store, process, worker_count=1)
    await queue.cancel(job.id)
    await queue.start(resume=True)
    await queue.join()
    await queue.stop()

    assert called is False
    assert store.get_job(job.id).status is JobStatus.CANCELLED


@pytest.mark.asyncio
async def test_worker_skips_deleted_waiting_job_and_processes_the_next_one(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    deleted = store.create_batch(["https://youtu.be/deleted"]).jobs[0]
    store.delete_finished_history()
    valid = store.create_batch(["https://youtu.be/valid"]).jobs[0]
    processed = []

    async def process(job_id, cancel_event):
        processed.append(job_id)
        store.update_job(job_id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED)

    queue = JobQueue(store, process, worker_count=1)
    await queue.start(resume=False)
    await queue.enqueue(deleted.id)
    await queue.enqueue(valid.id)
    await queue.join()
    await queue.stop()

    assert processed == [valid.id]
    assert store.get_job(valid.id).status is JobStatus.COMPLETED
