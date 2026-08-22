from __future__ import annotations

import asyncio
import shutil
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.background import BackgroundTask

from clipauto.config import Settings
from clipauto.exporter import export_batch_mp4s
from clipauto.models import InvalidURLs, parse_youtube_urls
from clipauto.ollama import OllamaClient
from clipauto.pipeline import Pipeline
from clipauto.queue import JobQueue
from clipauto.store import JobStore
from clipauto.transcriber import WhisperTranscriber
from clipauto.zipper import create_batch_zip


class BatchRequest(BaseModel):
    urls: str


def _safe_media_path(path: str, root: Path) -> Path:
    candidate = Path(path).resolve()
    allowed = (root / "jobs").resolve()
    if not candidate.is_relative_to(allowed) or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Clip file is unavailable")
    return candidate


def create_app(
    settings: Settings | None = None,
    *,
    store: JobStore | None = None,
    queue: JobQueue | None = None,
) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = store or JobStore(settings.database_path)
    if queue is None:
        pipeline = Pipeline(
            store,
            settings.data_dir,
            WhisperTranscriber(
                settings.whisper_model, cache_models=settings.worker_count == 1
            ),
            OllamaClient(settings.ollama_url),
        )
        queue = JobQueue(store, pipeline.process, settings.worker_count)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await queue.start(resume=True)
        yield
        await queue.stop()

    app = FastAPI(title="ClipAuto", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.store = store
    app.state.queue = queue

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok", "workers": settings.worker_count}

    @app.post("/api/batches", status_code=status.HTTP_201_CREATED)
    async def create_batch(body: BatchRequest) -> dict:
        try:
            urls = parse_youtube_urls(body.urls, settings.max_batch_urls)
        except InvalidURLs as error:
            raise HTTPException(
                status_code=422, detail={"message": str(error), "invalid": error.invalid}
            ) from error
        batch = store.create_batch(urls)
        for job in batch.jobs:
            await queue.enqueue(job.id)
        return batch.to_dict()

    @app.get("/api/batches")
    async def list_batches() -> list[dict]:
        return [batch.to_dict() for batch in store.list_batches(limit=1)]

    @app.delete("/api/history")
    async def clear_history() -> dict[str, int]:
        deleted_jobs, work_dirs = store.delete_finished_history()
        jobs_root = (settings.data_dir / "jobs").resolve()
        for work_dir in work_dirs:
            candidate = Path(work_dir).resolve()
            if candidate != jobs_root and candidate.is_relative_to(jobs_root):
                await asyncio.to_thread(shutil.rmtree, candidate, ignore_errors=True)
        return {"deleted_jobs": deleted_jobs}

    @app.get("/api/batches/{batch_id}")
    async def get_batch(batch_id: str) -> dict:
        try:
            return store.get_batch(batch_id).to_dict()
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Batch not found") from error

    @app.post("/api/jobs/{job_id}/cancel", status_code=status.HTTP_202_ACCEPTED)
    async def cancel_job(job_id: str) -> dict:
        try:
            store.get_job(job_id, include_clips=False)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Job not found") from error
        await queue.cancel(job_id)
        return {"status": "cancelling"}

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str) -> dict[str, str | bool]:
        try:
            work_dir, batch_deleted = store.delete_job(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Video not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if work_dir:
            jobs_root = (settings.data_dir / "jobs").resolve()
            candidate = Path(work_dir).resolve()
            if candidate != jobs_root and candidate.is_relative_to(jobs_root):
                await asyncio.to_thread(shutil.rmtree, candidate, ignore_errors=True)
        return {"deleted_job": job_id, "batch_deleted": batch_deleted}

    @app.post("/api/jobs/{job_id}/retry", status_code=status.HTTP_202_ACCEPTED)
    async def retry_job(job_id: str) -> dict[str, str]:
        try:
            work_dir, _ = store.retry_job(job_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Video not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if work_dir:
            jobs_root = (settings.data_dir / "jobs").resolve()
            candidate = Path(work_dir).resolve()
            if candidate != jobs_root and candidate.is_relative_to(jobs_root):
                await asyncio.to_thread(shutil.rmtree, candidate, ignore_errors=True)
        await queue.enqueue(job_id)
        return {"status": "queued"}

    def clip_file(clip_id: str) -> tuple[Path, str]:
        try:
            clip = store.get_clip(clip_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Clip not found") from error
        return _safe_media_path(clip.path, settings.data_dir), clip.title

    @app.delete("/api/clips/{clip_id}")
    async def delete_clip(clip_id: str) -> dict[str, str]:
        try:
            clip = store.delete_clip(clip_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Clip not found") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

        jobs_root = (settings.data_dir / "jobs").resolve()
        candidate = Path(clip.path).resolve()
        if candidate.is_relative_to(jobs_root):
            await asyncio.to_thread(candidate.unlink, missing_ok=True)
            await asyncio.to_thread(candidate.with_suffix(".ass").unlink, missing_ok=True)
        return {"deleted_clip": clip_id}

    @app.get("/api/clips/{clip_id}/media")
    async def preview_clip(clip_id: str) -> FileResponse:
        path, _ = clip_file(clip_id)
        return FileResponse(path, media_type="video/mp4")

    @app.get("/api/clips/{clip_id}/download")
    async def download_clip(clip_id: str) -> FileResponse:
        path, title = clip_file(clip_id)
        return FileResponse(path, media_type="video/mp4", filename=f"{title}.mp4")

    @app.get("/api/batches/{batch_id}/download")
    async def download_batch(batch_id: str) -> FileResponse:
        try:
            batch = store.get_batch(batch_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Batch not found") from error
        target = settings.data_dir / "tmp" / f"clipauto-{uuid.uuid4().hex}.zip"
        try:
            await asyncio.to_thread(create_batch_zip, batch, target)
        except ValueError as error:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OSError as error:
            target.unlink(missing_ok=True)
            raise HTTPException(status_code=507, detail=f"Could not create ZIP: {error}") from error
        return FileResponse(
            target,
            media_type="application/zip",
            filename=f"clipauto-{batch.id[:8]}.zip",
            background=BackgroundTask(target.unlink, missing_ok=True),
        )

    @app.post("/api/batches/{batch_id}/export")
    async def export_batch(batch_id: str) -> dict[str, str | int]:
        try:
            batch = store.get_batch(batch_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="Batch not found") from error
        try:
            folder, files = await asyncio.to_thread(
                export_batch_mp4s,
                batch,
                settings.export_dir,
                settings.data_dir,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except OSError as error:
            raise HTTPException(
                status_code=507, detail=f"Could not export MP4 files: {error}"
            ) from error
        return {"folder": str(folder), "files": files}

    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html", media_type="text/html")

    return app
