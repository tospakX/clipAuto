from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from pathlib import Path

from clipauto.downloader import DownloadResult, download_video
from clipauto.models import ClipRecord, JobStatus, Stage
from clipauto.process import ProcessCancelled
from clipauto.renderer import OUTPUT_SPEED, render_topics
from clipauto.store import JobStore
from clipauto.topics import (
    extract_json_array,
    format_timestamped_transcript,
    normalize_topics,
    plan_reel_topics,
    topics_from_chapters,
    topics_from_transcript,
)
from clipauto.validation import validate_reel

logger = logging.getLogger(__name__)


class Pipeline:
    def __init__(
        self,
        store: JobStore,
        data_dir: Path,
        transcriber,
        segmenter,
        downloader: Callable[..., Awaitable[DownloadResult]] = download_video,
        renderer: Callable[..., Awaitable[list[Path]]] = render_topics,
        validator: Callable[[Path, float], object] = validate_reel,
    ):
        self.store = store
        self.jobs_dir = Path(data_dir) / "jobs"
        self.transcriber = transcriber
        self.segmenter = segmenter
        self.downloader = downloader
        self.renderer = renderer
        self.validator = validator

    @staticmethod
    def _remove_source(path: Path, work_dir: Path) -> None:
        candidate = path.resolve()
        managed_dir = work_dir.resolve()
        if candidate.is_relative_to(managed_dir) and candidate.is_file():
            with suppress(OSError):
                candidate.unlink()

    @staticmethod
    def _remove_tree(path: Path) -> None:
        with suppress(OSError):
            shutil.rmtree(path)

    @staticmethod
    def _remove_superseded(paths: list[str], work_dir: Path) -> None:
        managed_dir = work_dir.resolve()
        for value in paths:
            candidate = Path(value).resolve()
            if not candidate.is_relative_to(managed_dir):
                continue
            with suppress(OSError):
                candidate.unlink()
            with suppress(OSError):
                candidate.with_suffix(".ass").unlink()
            parent = candidate.parent
            if parent.parent.name == "renders":
                with suppress(OSError):
                    parent.rmdir()

    async def process(self, job_id: str, cancel_event: asyncio.Event | None = None) -> None:
        cancel_event = cancel_event or asyncio.Event()
        job = self.store.get_job(job_id)
        work_dir = self.jobs_dir / job.id
        work_dir.mkdir(parents=True, exist_ok=True)
        previous_paths = [clip.path for clip in job.clips]
        staging: Path | None = None
        permanent: Path | None = None
        generation_published = False
        stage = Stage.DOWNLOADING
        last_persisted_progress = 0.0

        def update_progress(value: float) -> None:
            nonlocal last_persisted_progress
            if cancel_event.is_set():
                raise ProcessCancelled("Processing was cancelled")
            value = max(0.0, min(1.0, value))
            if value < last_persisted_progress:
                last_persisted_progress = 0.0
            if value < 1.0 and value - last_persisted_progress < 0.01:
                return
            self.store.update_job(job_id, progress=value)
            last_persisted_progress = value

        try:
            self.store.update_job(
                job_id,
                status=JobStatus.RUNNING,
                stage=stage,
                progress=0,
                error=None,
                work_dir=str(work_dir),
            )
            downloaded = await self.downloader(job.url, work_dir, update_progress, cancel_event)
            self.store.update_job(job_id, title=downloaded.title)

            stage = Stage.TRANSCRIBING
            self.store.update_job(job_id, stage=stage, progress=0)
            transcription = await asyncio.to_thread(
                self.transcriber.transcribe, downloaded.path, update_progress
            )
            if cancel_event.is_set():
                raise ProcessCancelled("Processing was cancelled")

            stage = Stage.SEGMENTING
            self.store.update_job(job_id, stage=stage, progress=0)
            topics = topics_from_chapters(
                downloaded.chapters, downloaded.duration or transcription.duration
            )
            if topics is None:
                try:
                    response = await self.segmenter.segment(
                        format_timestamped_transcript(transcription.segments),
                        transcription.duration,
                    )
                    topics = normalize_topics(
                        extract_json_array(response),
                        transcription.segments,
                        transcription.duration,
                    )
                except ProcessCancelled:
                    raise
                except Exception as error:
                    logger.warning(
                        "Topic model result was unusable for job %s; using transcript fallback: %s",
                        job_id,
                        error,
                    )
                    topics = topics_from_transcript(
                        transcription.segments, transcription.duration
                    )
            topics = plan_reel_topics(topics, transcription.segments)
            self.store.update_job(job_id, progress=1, planned_clips=len(topics))

            stage = Stage.RENDERING
            self.store.update_job(job_id, stage=stage, progress=0)
            clip_progresses = [0.0] * len(topics)
            renders_dir = work_dir / "renders"
            renders_dir.mkdir(parents=True, exist_ok=True)
            generation = uuid.uuid4().hex
            staging = renders_dir / f".{generation}"
            permanent = renders_dir / generation

            def render_progress(index: int, total: int, clip_progress: float) -> None:
                if total != len(clip_progresses) or not 0 <= index < total:
                    raise ValueError("Renderer reported invalid clip progress")
                clip_progresses[index] = max(
                    clip_progresses[index], max(0.0, min(1.0, clip_progress))
                )
                update_progress(sum(clip_progresses) / total)

            outputs = await self.renderer(
                downloaded.path,
                staging,
                topics,
                transcription.segments,
                render_progress,
                cancel_event,
            )
            if len(outputs) != len(topics):
                raise ValueError(
                    f"expected {len(topics)} rendered clips, got {len(outputs)}"
                )
            staging_root = staging.resolve()
            resolved_outputs = [Path(path).resolve() for path in outputs]
            if len(set(resolved_outputs)) != len(resolved_outputs):
                raise ValueError("Renderer returned duplicate output paths")
            if any(not path.is_relative_to(staging_root) for path in resolved_outputs):
                raise ValueError("Renderer returned an output outside its staging generation")
            for topic, path in zip(topics, resolved_outputs, strict=True):
                self.validator(path, (topic.end - topic.start) / OUTPUT_SPEED)

            staging.replace(permanent)
            final_outputs = [
                permanent / path.relative_to(staging_root) for path in resolved_outputs
            ]
            clips = [
                ClipRecord("", job_id, index, topic.title, topic.start, topic.end, str(path))
                for index, (topic, path) in enumerate(zip(topics, final_outputs, strict=True))
            ]
            self.store.complete_job(job_id, clips)
            generation_published = True
            self._remove_superseded(previous_paths, work_dir)
            self._remove_source(downloaded.path, work_dir)
        except asyncio.CancelledError:
            self.store.update_job(
                job_id,
                status=JobStatus.QUEUED,
                stage=Stage.WAITING,
                progress=0,
                error=None,
            )
            raise
        except ProcessCancelled:
            self.store.update_job(
                job_id,
                status=JobStatus.CANCELLED,
                stage=Stage.CANCELLED,
                error="Processing was cancelled",
            )
        except Exception as error:
            label = {
                Stage.DOWNLOADING: "Download",
                Stage.TRANSCRIBING: "Transcription",
                Stage.SEGMENTING: "Topic detection",
                Stage.RENDERING: "Clip rendering",
            }.get(stage, "Processing")
            self.store.update_job(
                job_id,
                status=JobStatus.FAILED,
                stage=Stage.FAILED,
                error=f"{label} failed: {str(error).strip()}"[:2000],
            )
            raise
        finally:
            if staging is not None and staging.exists():
                self._remove_tree(staging)
            if permanent is not None and permanent.exists() and not generation_published:
                self._remove_tree(permanent)
