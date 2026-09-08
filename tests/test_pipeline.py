from pathlib import Path

import pytest

from clipauto.downloader import DownloadResult
from clipauto.models import ClipRecord, JobStatus, Stage, Topic, TranscriptSegment
from clipauto.ollama import OllamaError
from clipauto.pipeline import Pipeline
from clipauto.store import JobStore
from clipauto.transcriber import TranscriptionResult


def _accept_test_render(*_args):
    return None


@pytest.mark.asyncio
async def test_pipeline_falls_back_to_transcript_topics_when_ollama_fails(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/fallback"]).jobs[0]
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    async def downloader(url, work_dir, progress, cancel_event):
        return DownloadResult(source, "Fallback talk", 110, False)

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [
                    TranscriptSegment(0, 55, "First useful subject."),
                    TranscriptSegment(55, 110, "Second useful subject."),
                ],
                110,
                "en",
                "cpu",
            )

    class Segmenter:
        async def segment(self, transcript, duration):
            raise OllamaError("model unavailable")

    captured = []

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        captured.extend(topics)
        output_dir.mkdir(parents=True)
        outputs = []
        for index in range(len(topics)):
            output = output_dir / f"clip_{index + 1:02d}.mp4"
            output.write_bytes(b"clip")
            outputs.append(output)
        return outputs

    await Pipeline(
        store,
        tmp_path / "data",
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=_accept_test_render,
    ).process(job.id)

    assert captured == [
        Topic("First useful subject", 0, 55),
        Topic("Second useful subject", 55, 110),
    ]
    assert store.get_job(job.id).status is JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_pipeline_persists_every_normalized_topic_clip(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media-on-disk")

    async def downloader(url, work_dir, progress, cancel_event):
        progress(0.4)
        return DownloadResult(source, "Coffee talk", 44.0, False)

    class Transcriber:
        def transcribe(self, path, progress):
            progress(1)
            return TranscriptionResult(
                [
                    TranscriptSegment(0, 22, "Caffeine discussion ends."),
                    TranscriptSegment(22, 44, "Sleep discussion ends."),
                ],
                44,
                "en",
                "cpu",
            )

    class Segmenter:
        async def segment(self, transcript, duration):
            assert "[0.00-22.00]" in transcript
            return '[{"title":"Caffeine","start":0,"end":21},{"title":"Sleep","start":23,"end":44}]'

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        paths = []
        for index, topic in enumerate(topics):
            path = output_dir / f"clip_{index + 1:02d}.mp4"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(topic.title.encode())
            paths.append(path)
            progress(index, len(topics), 1)
        return paths

    pipeline = Pipeline(
        store,
        tmp_path / "data",
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=_accept_test_render,
    )
    await pipeline.process(job.id)

    result = store.get_job(job.id)
    assert result.status is JobStatus.COMPLETED
    assert result.stage is Stage.COMPLETED
    assert result.progress == 1
    assert result.title == "Coffee talk"
    assert result.planned_clips == 1
    assert [(clip.title, clip.start, clip.end) for clip in result.clips] == [
        ("Caffeine + Sleep", 0.0, 44.0),
    ]


@pytest.mark.asyncio
async def test_pipeline_prefers_description_chapters_over_ollama(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media-on-disk")

    async def downloader(url, work_dir, progress, cancel_event):
        return DownloadResult(
            source,
            "Chaptered talk",
            45.0,
            False,
            chapters=[
                {"title": "Introduction", "start_time": 0, "end_time": 15},
                {"title": "Main idea", "start_time": 15, "end_time": 30},
                {"title": "Conclusion", "start_time": 30, "end_time": 45},
            ],
        )

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [TranscriptSegment(0, 15, "First."), TranscriptSegment(15, 45, "Rest.")],
                45,
                "en",
                "cpu",
            )

    class Segmenter:
        async def segment(self, transcript, duration):
            raise AssertionError("Ollama must not run when yt-dlp returned valid chapters")

    captured_topics = []

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        captured_topics.extend(topics)
        output_dir.mkdir(parents=True)
        outputs = []
        for index in range(len(topics)):
            path = output_dir / f"clip_{index + 1:02d}.mp4"
            path.write_bytes(b"clip")
            outputs.append(path)
        return outputs

    pipeline = Pipeline(
        store,
        tmp_path / "data",
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=_accept_test_render,
    )
    await pipeline.process(job.id)

    assert [(topic.title, topic.start, topic.end) for topic in captured_topics] == [
        ("Main idea", 15.0, 30.0),
    ]


@pytest.mark.asyncio
async def test_pipeline_splits_single_oversized_model_topic_before_rendering(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/long"]).jobs[0]
    source = tmp_path / "source.mp4"
    source.write_bytes(b"media-on-disk")

    async def downloader(url, work_dir, progress, cancel_event):
        return DownloadResult(source, "Long talk", 240.0, False)

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [
                    TranscriptSegment(start, start + 30, f"Sentence {index}.")
                    for index, start in enumerate(range(0, 240, 30))
                ],
                240,
                "en",
                "cpu",
            )

    class Segmenter:
        async def segment(self, transcript, duration):
            return '[{"title":"Long discussion","start":0,"end":240}]'

    captured_topics = []

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        captured_topics.extend(topics)
        output_dir.mkdir(parents=True)
        outputs = []
        for index in range(len(topics)):
            path = output_dir / f"clip_{index + 1:02d}.mp4"
            path.write_bytes(b"clip")
            outputs.append(path)
        return outputs

    await Pipeline(
        store,
        tmp_path / "data",
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=_accept_test_render,
    ).process(job.id)

    assert [(topic.start, topic.end) for topic in captured_topics] == [
        (0, 60),
        (60, 120),
        (120, 180),
        (180, 240),
    ]


@pytest.mark.asyncio
async def test_pipeline_renders_lone_meaningful_short_source(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    source_path = None

    async def downloader(url, work_dir, progress, cancel_event):
        nonlocal source_path
        source_path = work_dir / "source.mp4"
        source_path.write_bytes(b"large source")
        return DownloadResult(source_path, "Talk", 10.0, False, chapters=[])

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [TranscriptSegment(0, 10, "One complete topic.")], 10, "en", "cpu"
            )

    class Segmenter:
        async def segment(self, transcript, duration):
            return '[{"title":"Topic","start":0,"end":10}]'

    captured_topics = []

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        captured_topics.extend(topics)
        output_dir.mkdir(parents=True)
        output = output_dir / "clip_01.mp4"
        output.write_bytes(b"clip")
        return [output]

    pipeline = Pipeline(
        store,
        tmp_path / "data",
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=_accept_test_render,
    )
    await pipeline.process(job.id)

    result = store.get_job(job.id)
    assert result.status is JobStatus.COMPLETED
    assert captured_topics == [Topic("Topic", 0, 10)]


@pytest.mark.asyncio
async def test_pipeline_preserves_two_natural_near_target_chapters(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/eighty"]).jobs[0]
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    async def downloader(url, work_dir, progress, cancel_event):
        return DownloadResult(
            source,
            "Eighty seconds",
            80,
            False,
            chapters=[
                {"title": "First", "start_time": 0},
                {"title": "Second", "start_time": 40},
            ],
        )

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [TranscriptSegment(0, 40, "First."), TranscriptSegment(40, 80, "Second.")],
                80,
                "en",
                "cpu",
            )

    captured_topics = []

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        captured_topics.extend(topics)
        output_dir.mkdir(parents=True)
        outputs = []
        for index in range(len(topics)):
            output = output_dir / f"clip_{index + 1:02d}.mp4"
            output.write_bytes(b"clip")
            outputs.append(output)
        return outputs

    class Segmenter:
        async def segment(self, transcript, duration):
            raise AssertionError("Valid chapters should bypass segmentation")

    await Pipeline(
        store,
        tmp_path / "data",
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=_accept_test_render,
    ).process(job.id)

    assert captured_topics == [Topic("First", 0, 40), Topic("Second", 40, 80)]


@pytest.mark.asyncio
async def test_pipeline_marks_stage_specific_failure(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]

    async def downloader(url, work_dir, progress, cancel_event):
        raise RuntimeError("HTTP Error 404")

    pipeline = Pipeline(store, tmp_path / "data", object(), object(), downloader=downloader)

    with pytest.raises(RuntimeError, match="404"):
        await pipeline.process(job.id)

    result = store.get_job(job.id)
    assert result.status is JobStatus.FAILED
    assert result.stage is Stage.FAILED
    assert "Download failed" in result.error


@pytest.mark.asyncio
async def test_pipeline_coalesces_tiny_progress_updates_before_persisting(tmp_path: Path):
    class RecordingStore(JobStore):
        def __init__(self, path):
            self.progress_writes = []
            super().__init__(path)

        def update_job(self, job_id, **changes):
            if "progress" in changes:
                self.progress_writes.append(changes["progress"])
            return super().update_job(job_id, **changes)

    store = RecordingStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]

    async def downloader(url, work_dir, progress, cancel_event):
        for value in (0.001, 0.005, 0.009, 0.011):
            progress(value)
        raise RuntimeError("stop after progress sample")

    pipeline = Pipeline(store, tmp_path / "data", object(), object(), downloader=downloader)

    with pytest.raises(RuntimeError, match="progress sample"):
        await pipeline.process(job.id)

    assert store.progress_writes == [0, 0.011]


@pytest.mark.asyncio
async def test_parallel_render_progress_is_aggregated_without_moving_backwards(tmp_path: Path):
    class RecordingStore(JobStore):
        def __init__(self, path):
            self.render_progress = []
            self.in_render = False
            super().__init__(path)

        def update_job(self, job_id, **changes):
            if changes.get("stage") is Stage.RENDERING:
                self.in_render = True
            elif changes.get("stage") in {Stage.COMPLETED, Stage.FAILED, Stage.CANCELLED}:
                self.in_render = False
            if self.in_render and "progress" in changes:
                self.render_progress.append(changes["progress"])
            return super().update_job(job_id, **changes)

    store = RecordingStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/parallel"]).jobs[0]
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")

    async def downloader(url, work_dir, progress, cancel_event):
        return DownloadResult(
            source,
            "Parallel render",
            120,
            False,
            chapters=[
                {"title": "First", "start_time": 0},
                {"title": "Second", "start_time": 60},
            ],
        )

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [
                    TranscriptSegment(0, 60, "First topic."),
                    TranscriptSegment(60, 120, "Second topic."),
                ],
                120,
                "en",
                "cuda",
            )

    class Segmenter:
        async def segment(self, transcript, duration):
            raise AssertionError("valid chapters do not need Ollama")

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        output_dir.mkdir(parents=True)
        outputs = [output_dir / "clip_01.mp4", output_dir / "clip_02.mp4"]
        for output in outputs:
            output.write_bytes(b"clip")
        progress(1, 2, 0.8)
        progress(0, 2, 0.5)
        return outputs

    await Pipeline(
        store,
        tmp_path / "data",
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=_accept_test_render,
    ).process(job.id)

    assert store.render_progress == [0, 0.4, 0.65]


@pytest.mark.asyncio
async def test_application_shutdown_leaves_active_job_resumable(tmp_path: Path):
    import asyncio

    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    started = asyncio.Event()

    async def downloader(url, work_dir, progress, cancel_event):
        started.set()
        await asyncio.Event().wait()

    pipeline = Pipeline(store, tmp_path / "data", object(), object(), downloader=downloader)
    task = asyncio.create_task(pipeline.process(job.id))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    persisted = store.get_job(job.id)
    assert persisted.status is JobStatus.QUEUED
    assert persisted.stage is Stage.WAITING
    assert persisted.cancel_requested is False


@pytest.mark.asyncio
async def test_explicit_running_cancellation_is_terminal(tmp_path: Path):
    import asyncio

    from clipauto.process import ProcessCancelled

    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    started = asyncio.Event()

    async def downloader(url, work_dir, progress, cancel_event):
        started.set()
        await cancel_event.wait()
        raise ProcessCancelled("cancelled")

    pipeline = Pipeline(store, tmp_path / "data", object(), object(), downloader=downloader)
    cancel_event = asyncio.Event()
    task = asyncio.create_task(pipeline.process(job.id, cancel_event))
    await started.wait()
    cancel_event.set()
    await task

    persisted = store.get_job(job.id)
    assert persisted.status is JobStatus.CANCELLED
    assert persisted.stage is Stage.CANCELLED


@pytest.mark.asyncio
async def test_missing_render_preserves_previous_generation_and_cleans_staging(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/atomic"]).jobs[0]
    work_dir = data_dir / "jobs" / job.id
    old_path = work_dir / "renders" / "old" / "clip_01.mp4"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"previous-good-generation")
    store.update_job(job.id, work_dir=str(work_dir))
    store.replace_clips(
        job.id,
        [ClipRecord("old", job.id, 0, "Old", 0, 60, str(old_path))],
    )

    async def downloader(url, target_work_dir, progress, cancel_event):
        source = target_work_dir / "source.mp4"
        source.write_bytes(b"source")
        return DownloadResult(
            source,
            "Atomic rerender",
            120,
            False,
            chapters=[
                {"title": "First", "start_time": 0},
                {"title": "Second", "start_time": 60},
            ],
        )

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [TranscriptSegment(0, 60, "First."), TranscriptSegment(60, 120, "Second.")],
                120,
                "en",
                "cpu",
            )

    async def incomplete_renderer(
        source, output_dir, topics, segments, progress, cancel_event
    ):
        output_dir.mkdir(parents=True)
        only_output = output_dir / "clip_01.mp4"
        only_output.write_bytes(b"partial-new-generation")
        return [only_output]

    class Segmenter:
        async def segment(self, transcript, duration):
            raise AssertionError("Valid chapters should bypass segmentation")

    pipeline = Pipeline(
        store,
        data_dir,
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=incomplete_renderer,
        validator=lambda *_: None,
    )

    with pytest.raises(ValueError, match="expected 2 rendered clips, got 1"):
        await pipeline.process(job.id)

    failed = store.get_job(job.id)
    assert failed.status is JobStatus.FAILED
    assert [(clip.id, clip.path) for clip in failed.clips] == [("old", str(old_path))]
    assert old_path.read_bytes() == b"previous-good-generation"
    assert sorted(path.name for path in (work_dir / "renders").iterdir()) == ["old"]


@pytest.mark.asyncio
async def test_invalid_render_preserves_previous_generation(tmp_path: Path):
    from clipauto.validation import MediaValidationError

    data_dir = tmp_path / "data"
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/invalid"]).jobs[0]
    work_dir = data_dir / "jobs" / job.id
    old_path = work_dir / "renders" / "old" / "clip_01.mp4"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"previous-good-generation")
    store.replace_clips(
        job.id,
        [ClipRecord("old", job.id, 0, "Old", 0, 60, str(old_path))],
    )

    async def downloader(url, target_work_dir, progress, cancel_event):
        source = target_work_dir / "source.mp4"
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"source")
        return DownloadResult(source, "Invalid rerender", 60, False)

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [TranscriptSegment(0, 60, "Complete topic.")], 60, "en", "cpu"
            )

    class Segmenter:
        async def segment(self, transcript, duration):
            return '[{"title":"Complete topic","start":0,"end":60}]'

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        output_dir.mkdir(parents=True)
        output = output_dir / "clip_01.mp4"
        output.write_bytes(b"corrupt")
        return [output]

    def reject(_path, _duration):
        raise MediaValidationError("corrupt rendered media")

    pipeline = Pipeline(
        store,
        data_dir,
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=reject,
    )

    with pytest.raises(MediaValidationError, match="corrupt"):
        await pipeline.process(job.id)

    failed = store.get_job(job.id)
    assert [(clip.id, clip.path) for clip in failed.clips] == [("old", str(old_path))]
    assert old_path.read_bytes() == b"previous-good-generation"
    assert sorted(path.name for path in (work_dir / "renders").iterdir()) == ["old"]


@pytest.mark.asyncio
async def test_validated_generation_replaces_database_before_old_media_cleanup(tmp_path: Path):
    data_dir = tmp_path / "data"
    store = JobStore(tmp_path / "jobs.db")
    job = store.create_batch(["https://youtu.be/valid"]).jobs[0]
    work_dir = data_dir / "jobs" / job.id
    old_path = work_dir / "renders" / "old" / "clip_01.mp4"
    old_path.parent.mkdir(parents=True)
    old_path.write_bytes(b"previous-good-generation")
    store.replace_clips(
        job.id,
        [ClipRecord("old", job.id, 0, "Old", 0, 60, str(old_path))],
    )
    source_path = work_dir / "source.mp4"

    async def downloader(url, target_work_dir, progress, cancel_event):
        source_path.write_bytes(b"source")
        return DownloadResult(
            source_path,
            "Valid rerender",
            120,
            False,
            chapters=[
                {"title": "First", "start_time": 0},
                {"title": "Second", "start_time": 60},
            ],
        )

    class Transcriber:
        def transcribe(self, path, progress):
            return TranscriptionResult(
                [TranscriptSegment(0, 60, "First."), TranscriptSegment(60, 120, "Second.")],
                120,
                "en",
                "cpu",
            )

    class Segmenter:
        async def segment(self, transcript, duration):
            raise AssertionError("Valid chapters should bypass segmentation")

    async def renderer(source, output_dir, topics, segments, progress, cancel_event):
        output_dir.mkdir(parents=True)
        outputs = []
        for index in range(2):
            output = output_dir / f"clip_{index + 1:02d}.mp4"
            output.write_bytes(f"validated-{index}".encode())
            outputs.append(output)
        return outputs

    validated = []
    await Pipeline(
        store,
        data_dir,
        Transcriber(),
        Segmenter(),
        downloader=downloader,
        renderer=renderer,
        validator=lambda path, duration: validated.append((path, duration)),
    ).process(job.id)

    completed = store.get_job(job.id)
    assert completed.status is JobStatus.COMPLETED
    assert len(validated) == 2
    assert [duration for _, duration in validated] == pytest.approx([60 / 1.1, 60 / 1.1])
    assert len(completed.clips) == 2
    assert all(Path(clip.path).is_file() for clip in completed.clips)
    assert all(not Path(clip.path).parent.name.startswith(".") for clip in completed.clips)
    assert not old_path.exists()
    assert not source_path.exists()
