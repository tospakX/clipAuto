from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress

from clipauto.models import JobStatus, Stage
from clipauto.store import JobStore


class JobQueue:
    def __init__(
        self,
        store: JobStore,
        processor: Callable[[str, asyncio.Event], Awaitable[None]],
        worker_count: int = 2,
    ):
        if worker_count < 1:
            raise ValueError("worker_count must be at least 1")
        self.store = store
        self.processor = processor
        self.worker_count = worker_count
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._active: dict[str, asyncio.Event] = {}
        self._scheduled: set[str] = set()

    async def start(self, resume: bool = True) -> None:
        if self._workers:
            return
        self._workers = [
            asyncio.create_task(self._worker(), name=f"clipauto-worker-{index}")
            for index in range(self.worker_count)
        ]
        if resume:
            for job in self.store.list_pending_jobs():
                if job.cancel_requested:
                    self.store.update_job(job.id, status=JobStatus.CANCELLED, stage=Stage.CANCELLED)
                else:
                    self.store.update_job(
                        job.id, status=JobStatus.QUEUED, stage=Stage.WAITING, progress=0
                    )
                    await self.enqueue(job.id)

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    async def enqueue(self, job_id: str) -> None:
        if job_id in self._scheduled or job_id in self._active:
            return
        self._scheduled.add(job_id)
        await self._queue.put(job_id)

    async def cancel(self, job_id: str) -> None:
        job = self.store.request_cancel(job_id)
        event = self._active.get(job_id)
        if event:
            event.set()
        elif job.status is JobStatus.QUEUED:
            self.store.update_job(job_id, status=JobStatus.CANCELLED, stage=Stage.CANCELLED)

    async def join(self) -> None:
        await self._queue.join()

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            self._scheduled.discard(job_id)
            try:
                try:
                    job = self.store.get_job(job_id, include_clips=False)
                except KeyError:
                    continue
                if job.cancel_requested or job.status is JobStatus.CANCELLED:
                    with suppress(KeyError):
                        self.store.update_job(
                            job_id, status=JobStatus.CANCELLED, stage=Stage.CANCELLED
                        )
                    continue
                event = asyncio.Event()
                self._active[job_id] = event
                try:
                    await self.processor(job_id, event)
                except asyncio.CancelledError:
                    event.set()
                    raise
                except Exception as error:
                    try:
                        current = self.store.get_job(job_id, include_clips=False)
                    except KeyError:
                        continue
                    if current.status not in {JobStatus.FAILED, JobStatus.CANCELLED}:
                        self.store.update_job(
                            job_id,
                            status=JobStatus.FAILED,
                            stage=Stage.FAILED,
                            error=str(error)[:2000],
                        )
                finally:
                    self._active.pop(job_id, None)
            finally:
                self._queue.task_done()
