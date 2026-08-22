import zipfile
from pathlib import Path

from clipauto.models import ClipRecord, JobStatus, Stage
from clipauto.store import JobStore
from clipauto.zipper import create_batch_zip


def test_zip_contains_all_and_only_completed_job_clips(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    batch = store.create_batch(["https://youtu.be/one", "https://youtu.be/two"])
    first, second = batch.jobs
    store.update_job(
        first.id, status=JobStatus.COMPLETED, stage=Stage.COMPLETED, title="Coffee / Tea"
    )
    store.update_job(second.id, status=JobStatus.FAILED, stage=Stage.FAILED, title="Broken")
    good = tmp_path / "good.mp4"
    ignored = tmp_path / "ignored.mp4"
    good.write_bytes(b"good")
    ignored.write_bytes(b"ignored")
    store.replace_clips(
        first.id, [ClipRecord("", first.id, 0, "Caffeine: basics", 0, 20, str(good))]
    )
    store.replace_clips(
        second.id, [ClipRecord("", second.id, 0, "Should not ship", 0, 20, str(ignored))]
    )

    target = create_batch_zip(store.get_batch(batch.id), tmp_path / "all.zip")

    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["01_Coffee_Tea/clip_01_Caffeine_basics.mp4"]
        assert archive.read(archive.namelist()[0]) == b"good"


def test_zip_rejects_batch_with_no_completed_clips(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.db")
    batch = store.create_batch(["https://youtu.be/one"])

    try:
        create_batch_zip(store.get_batch(batch.id), tmp_path / "all.zip")
    except ValueError as error:
        assert "No completed clips" in str(error)
    else:
        raise AssertionError("empty ZIP should be rejected")
