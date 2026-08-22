from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import clipauto.api as api_module
from clipauto.api import create_app
from clipauto.config import Settings
from clipauto.models import ClipRecord, JobStatus, Stage
from clipauto.store import JobStore


class RecordingQueue:
    def __init__(self):
        self.enqueued = []
        self.cancelled = []

    async def start(self, resume=True):
        pass

    async def stop(self):
        pass

    async def enqueue(self, job_id):
        self.enqueued.append(job_id)

    async def cancel(self, job_id):
        self.cancelled.append(job_id)


def make_client(tmp_path: Path):
    settings = Settings(data_dir=tmp_path / "data")
    store = JobStore(settings.database_path)
    queue = RecordingQueue()
    return TestClient(create_app(settings, store=store, queue=queue)), store, queue


def test_creates_and_enqueues_200_url_batch(tmp_path: Path):
    client, store, queue = make_client(tmp_path)
    urls = "\n".join(f"https://youtu.be/video{i}" for i in range(200))

    with client:
        response = client.post("/api/batches", json={"urls": urls})

    assert response.status_code == 201
    assert len(response.json()["jobs"]) == 200
    assert len(queue.enqueued) == 200
    assert len(store.list_jobs(response.json()["id"])) == 200


def test_invalid_url_response_identifies_bad_entries(tmp_path: Path):
    client, _, _ = make_client(tmp_path)

    with client:
        response = client.post("/api/batches", json={"urls": "https://example.com/nope"})

    assert response.status_code == 422
    assert response.json()["detail"]["invalid"] == ["https://example.com/nope"]


def test_reads_batch_and_cancels_job(tmp_path: Path):
    client, store, queue = make_client(tmp_path)
    batch = store.create_batch(["https://youtu.be/one"])

    with client:
        fetched = client.get(f"/api/batches/{batch.id}")
        cancelled = client.post(f"/api/jobs/{batch.jobs[0].id}/cancel")

    assert fetched.status_code == 200
    assert fetched.json()["jobs"][0]["stage"] == "waiting"
    assert cancelled.status_code == 202
    assert queue.cancelled == [batch.jobs[0].id]


def test_serves_preview_download_and_backend_zip(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    batch = store.create_batch(["https://youtu.be/one"])
    job = batch.jobs[0]
    clip_path = tmp_path / "data" / "jobs" / job.id / "clips" / "clip_01.mp4"
    clip_path.parent.mkdir(parents=True)
    clip_path.write_bytes(b"real-video-bytes")
    store.update_job(job.id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED, title="Coffee")
    store.replace_clips(
        job.id, [ClipRecord("clip-id", job.id, 0, "Caffeine", 0, 20, str(clip_path))]
    )

    with client:
        preview = client.get("/api/clips/clip-id/media")
        download = client.get("/api/clips/clip-id/download")
        archive = client.get(f"/api/batches/{batch.id}/download")

    assert preview.content == b"real-video-bytes"
    assert preview.headers["content-type"].startswith("video/mp4")
    assert "attachment" in download.headers["content-disposition"]
    assert archive.content.startswith(b"PK")
    assert "attachment" in archive.headers["content-disposition"]


def test_deletes_one_clip_file_and_preserves_its_sibling(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    clips_dir = tmp_path / "data" / "jobs" / job.id / "renders" / "generation"
    clips_dir.mkdir(parents=True)
    remove = clips_dir / "clip_01.mp4"
    keep = clips_dir / "clip_02.mp4"
    remove.write_bytes(b"intro")
    keep.write_bytes(b"main")
    store.update_job(
        job.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        planned_clips=2,
    )
    store.replace_clips(
        job.id,
        [
            ClipRecord("remove", job.id, 0, "Intro", 0, 5, str(remove)),
            ClipRecord("keep", job.id, 1, "Main", 5, 65, str(keep)),
        ],
    )

    with client:
        response = client.delete("/api/clips/remove")

    assert response.status_code == 200
    assert response.json() == {"deleted_clip": "remove"}
    assert not remove.exists()
    assert keep.read_bytes() == b"main"
    assert [clip.id for clip in store.get_job(job.id).clips] == ["keep"]


def test_clip_delete_returns_not_found_and_refuses_final_clip(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    clip_path = tmp_path / "data" / "jobs" / job.id / "clip.mp4"
    clip_path.parent.mkdir(parents=True)
    clip_path.write_bytes(b"only")
    store.update_job(
        job.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        planned_clips=1,
    )
    store.replace_clips(
        job.id,
        [ClipRecord("only", job.id, 0, "Only", 0, 60, str(clip_path))],
    )

    with client:
        missing = client.delete("/api/clips/missing")
        final = client.delete("/api/clips/only")

    assert missing.status_code == 404
    assert final.status_code == 409
    assert clip_path.read_bytes() == b"only"
    assert [clip.id for clip in store.get_job(job.id).clips] == ["only"]


def test_exports_all_completed_clips_as_flat_mp4_folder(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        export_dir=tmp_path / "Downloads",
    )
    store = JobStore(settings.database_path)
    client = TestClient(create_app(settings, store=store, queue=RecordingQueue()))
    batch = store.create_batch(["https://youtu.be/one", "https://youtu.be/two"])
    for position, job in enumerate(batch.jobs, start=1):
        clip_path = settings.data_dir / "jobs" / job.id / "clips" / "clip_01.mp4"
        clip_path.parent.mkdir(parents=True)
        clip_path.write_bytes(f"video-{position}".encode())
        store.update_job(
            job.id,
            status=JobStatus.COMPLETED,
            stage=Stage.COMPLETED,
            title=f"Video {position}",
        )
        store.replace_clips(
            job.id,
            [ClipRecord(f"clip-{position}", job.id, 0, f"Topic {position}", 0, 10, str(clip_path))],
        )

    with client:
        response = client.post(f"/api/batches/{batch.id}/export")

    assert response.status_code == 200
    assert response.json()["files"] == 2
    folder = Path(response.json()["folder"])
    assert folder.parent == settings.export_dir
    assert folder.name.startswith(f"ClipAuto-{batch.id[:8]}-")
    assert sorted(path.name for path in folder.iterdir()) == [
        "video_001_Video_1_topic_001_Topic_1.mp4",
        "video_002_Video_2_topic_001_Topic_2.mp4",
    ]
    assert sorted(path.read_bytes() for path in folder.iterdir()) == [b"video-1", b"video-2"]


def test_export_refuses_clip_record_outside_managed_media(tmp_path: Path):
    settings = Settings(
        data_dir=tmp_path / "data",
        export_dir=tmp_path / "Downloads",
    )
    store = JobStore(settings.database_path)
    client = TestClient(create_app(settings, store=store, queue=RecordingQueue()))
    job = store.create_batch(["https://youtu.be/one"]).jobs[0]
    outside = tmp_path / "private.mp4"
    outside.write_bytes(b"private")
    store.update_job(job.id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED)
    store.replace_clips(
        job.id,
        [ClipRecord("outside", job.id, 0, "Outside", 0, 1, str(outside))],
    )

    with client:
        response = client.post(f"/api/batches/{job.batch_id}/export")

    assert response.status_code == 409
    assert outside.read_bytes() == b"private"
    assert not settings.export_dir.exists()


def test_failed_zip_creation_removes_partial_archive(tmp_path: Path, monkeypatch):
    client, store, _ = make_client(tmp_path)
    batch = store.create_batch(["https://youtu.be/one"])
    job = batch.jobs[0]
    store.update_job(job.id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED)

    def fail_after_writing(batch, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"partial")
        raise OSError("No space left on device")

    monkeypatch.setattr(api_module, "create_batch_zip", fail_after_writing)

    with client:
        response = client.get(f"/api/batches/{batch.id}/download")

    assert response.status_code == 507
    assert list((tmp_path / "data" / "tmp").iterdir()) == []


def test_refuses_clip_record_pointing_outside_data_directory(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    batch = store.create_batch(["https://youtu.be/one"])
    outside = tmp_path / "secret.mp4"
    outside.write_bytes(b"secret")
    store.replace_clips(
        batch.jobs[0].id, [ClipRecord("unsafe", batch.jobs[0].id, 0, "Unsafe", 0, 1, str(outside))]
    )

    with client:
        response = client.get("/api/clips/unsafe/media")

    assert response.status_code == 404


def test_clear_history_deletes_finished_media_but_keeps_active_jobs(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    batch = store.create_batch(
        ["https://youtu.be/done", "https://youtu.be/active", "https://youtu.be/waiting"]
    )
    done, active, waiting = batch.jobs
    done_dir = tmp_path / "data" / "jobs" / done.id
    active_dir = tmp_path / "data" / "jobs" / active.id
    done_dir.mkdir(parents=True)
    active_dir.mkdir(parents=True)
    (done_dir / "clip.mp4").write_bytes(b"done")
    (active_dir / "source.mp4").write_bytes(b"active")
    store.update_job(
        done.id,
        status=JobStatus.COMPLETED,
        stage=Stage.COMPLETED,
        work_dir=str(done_dir),
    )
    store.update_job(
        active.id,
        status=JobStatus.RUNNING,
        stage=Stage.DOWNLOADING,
        work_dir=str(active_dir),
    )

    with client:
        response = client.delete("/api/history")

    assert response.status_code == 200
    assert response.json() == {"deleted_jobs": 2}
    assert not done_dir.exists()
    assert active_dir.is_dir()
    assert store.get_job(active.id).status is JobStatus.RUNNING
    with pytest.raises(KeyError):
        store.get_job(waiting.id)


def test_clear_history_never_deletes_paths_outside_managed_jobs(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    job = store.create_batch(["https://youtu.be/done"]).jobs[0]
    outside = tmp_path / "do-not-delete"
    outside.mkdir()
    (outside / "keep.txt").write_text("keep")
    store.update_job(
        job.id,
        status=JobStatus.FAILED,
        stage=Stage.FAILED,
        work_dir=str(outside),
    )

    with client:
        response = client.delete("/api/history")

    assert response.status_code == 200
    assert outside.is_dir()
    assert (outside / "keep.txt").read_text() == "keep"


def test_removes_one_processed_video_and_its_files_only(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    remove, keep = store.create_batch(["https://youtu.be/remove", "https://youtu.be/keep"]).jobs
    remove_dir = tmp_path / "data" / "jobs" / remove.id
    keep_dir = tmp_path / "data" / "jobs" / keep.id
    for job, directory in ((remove, remove_dir), (keep, keep_dir)):
        clip = directory / "clips" / "clip_01.mp4"
        clip.parent.mkdir(parents=True)
        clip.write_bytes(job.id.encode())
        store.update_job(
            job.id,
            status=JobStatus.COMPLETED,
            stage=Stage.COMPLETED,
            work_dir=str(directory),
        )
        store.replace_clips(
            job.id,
            [ClipRecord(f"clip-{job.id}", job.id, 0, "Topic", 0, 10, str(clip))],
        )

    with client:
        response = client.delete(f"/api/jobs/{remove.id}")
        kept_media = client.get(f"/api/clips/clip-{keep.id}/media")

    assert response.status_code == 200
    assert response.json() == {"deleted_job": remove.id, "batch_deleted": False}
    assert not remove_dir.exists()
    assert keep_dir.is_dir()
    assert kept_media.content == keep.id.encode()
    with pytest.raises(KeyError):
        store.get_job(remove.id)
    assert store.get_job(keep.id).status is JobStatus.COMPLETED


def test_refuses_to_remove_video_that_is_still_processing(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    job = store.create_batch(["https://youtu.be/active"]).jobs[0]
    store.update_job(job.id, status=JobStatus.RUNNING, stage=Stage.TRANSCRIBING)

    with client:
        response = client.delete(f"/api/jobs/{job.id}")

    assert response.status_code == 409
    assert store.get_job(job.id).status is JobStatus.RUNNING


def test_removes_one_waiting_video_before_it_starts(tmp_path: Path):
    client, store, _ = make_client(tmp_path)
    remove, keep = store.create_batch(
        ["https://youtu.be/remove", "https://youtu.be/keep"]
    ).jobs

    with client:
        response = client.delete(f"/api/jobs/{remove.id}")

    assert response.status_code == 200
    with pytest.raises(KeyError):
        store.get_job(remove.id)
    assert store.get_job(keep.id).status is JobStatus.QUEUED


def test_retries_failed_video_after_removing_stale_managed_files(tmp_path: Path):
    client, store, queue = make_client(tmp_path)
    job = store.create_batch(["https://youtu.be/retry"]).jobs[0]
    work_dir = tmp_path / "data" / "jobs" / job.id
    work_dir.mkdir(parents=True)
    (work_dir / "stale.mp4").write_bytes(b"stale")
    store.update_job(
        job.id,
        status=JobStatus.FAILED,
        stage=Stage.FAILED,
        progress=0.7,
        error="network failed",
        work_dir=str(work_dir),
        cancel_requested=True,
    )

    with client:
        response = client.post(f"/api/jobs/{job.id}/retry")

    assert response.status_code == 202
    assert response.json() == {"status": "queued"}
    assert not work_dir.exists()
    assert queue.enqueued == [job.id]
    retried = store.get_job(job.id)
    assert retried.status is JobStatus.QUEUED
    assert retried.error is None
    assert retried.cancel_requested is False
