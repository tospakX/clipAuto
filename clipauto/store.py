from __future__ import annotations

import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from clipauto.models import BatchRecord, ClipRecord, JobRecord, JobStatus, Stage


def _now() -> str:
    return datetime.now(UTC).isoformat()


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as db:
            db.executescript(
                """
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS batches (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress REAL NOT NULL DEFAULT 0,
                    title TEXT,
                    error TEXT,
                    work_dir TEXT,
                    planned_clips INTEGER NOT NULL DEFAULT 0,
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(batch_id, position)
                );
                CREATE TABLE IF NOT EXISTS clips (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                    clip_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    start REAL NOT NULL,
                    end REAL NOT NULL,
                    path TEXT NOT NULL,
                    UNIQUE(job_id, clip_index)
                );
                CREATE INDEX IF NOT EXISTS jobs_batch_position ON jobs(batch_id, position);
                CREATE INDEX IF NOT EXISTS jobs_status_position
                    ON jobs(status, created_at, position);
                """
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(jobs)")}
            if "planned_clips" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN planned_clips INTEGER NOT NULL DEFAULT 0")
            db.commit()

    def create_batch(self, urls: list[str]) -> BatchRecord:
        batch_id = uuid.uuid4().hex
        created_at = _now()
        jobs: list[JobRecord] = []
        with self._write_lock, self._connection() as db:
            db.execute("INSERT INTO batches(id, created_at) VALUES (?, ?)", (batch_id, created_at))
            for position, url in enumerate(urls):
                job_id = uuid.uuid4().hex
                db.execute(
                    """INSERT INTO jobs(
                        id, batch_id, url, position, status, stage, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        job_id,
                        batch_id,
                        url,
                        position,
                        JobStatus.QUEUED.value,
                        Stage.WAITING.value,
                        created_at,
                        created_at,
                    ),
                )
                jobs.append(
                    JobRecord(
                        job_id,
                        batch_id,
                        url,
                        position,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
            db.commit()
        return BatchRecord(batch_id, created_at, jobs)

    @staticmethod
    def _row_to_job(row: sqlite3.Row) -> JobRecord:
        return JobRecord(
            id=row["id"],
            batch_id=row["batch_id"],
            url=row["url"],
            position=row["position"],
            status=JobStatus(row["status"]),
            stage=Stage(row["stage"]),
            progress=row["progress"],
            title=row["title"],
            error=row["error"],
            work_dir=row["work_dir"],
            planned_clips=row["planned_clips"],
            cancel_requested=bool(row["cancel_requested"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            clip_count=row["clip_count"] if "clip_count" in set(row.keys()) else 0,
        )

    @staticmethod
    def _row_to_clip(row: sqlite3.Row) -> ClipRecord:
        return ClipRecord(
            id=row["id"],
            job_id=row["job_id"],
            index=row["clip_index"],
            title=row["title"],
            start=row["start"],
            end=row["end"],
            path=row["path"],
        )

    def get_job(self, job_id: str, include_clips: bool = True) -> JobRecord:
        with self._connection() as db:
            row = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            job = self._row_to_job(row)
            if include_clips:
                job.clips = self._list_clips(db, job_id)
                job.clip_count = len(job.clips)
            return job

    def list_jobs(self, batch_id: str, *, include_clips: bool = True) -> list[JobRecord]:
        with self._connection() as db:
            rows = db.execute(
                """SELECT jobs.*,
                          (SELECT COUNT(*) FROM clips WHERE clips.job_id = jobs.id) AS clip_count
                   FROM jobs WHERE batch_id = ? ORDER BY position""",
                (batch_id,),
            ).fetchall()
            jobs = [self._row_to_job(row) for row in rows]
            if not include_clips:
                return jobs
            clips = db.execute(
                """SELECT clips.* FROM clips
                   JOIN jobs ON jobs.id = clips.job_id
                   WHERE jobs.batch_id = ?
                   ORDER BY jobs.position, clips.clip_index""",
                (batch_id,),
            ).fetchall()
            jobs_by_id = {job.id: job for job in jobs}
            for row in clips:
                jobs_by_id[row["job_id"]].clips.append(self._row_to_clip(row))
            return jobs

    def get_batch(self, batch_id: str, *, include_clips: bool = True) -> BatchRecord:
        with self._connection() as db:
            row = db.execute("SELECT * FROM batches WHERE id = ?", (batch_id,)).fetchone()
        if row is None:
            raise KeyError(batch_id)
        return BatchRecord(
            row["id"],
            row["created_at"],
            self.list_jobs(batch_id, include_clips=include_clips),
        )

    def list_batches(self, limit: int = 20, *, include_clips: bool = True) -> list[BatchRecord]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM batches ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [
            BatchRecord(
                row["id"],
                row["created_at"],
                self.list_jobs(row["id"], include_clips=include_clips),
            )
            for row in rows
        ]

    def delete_finished_history(self) -> tuple[int, list[str]]:
        removable_statuses = (
            JobStatus.QUEUED.value,
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        )
        placeholders = ", ".join("?" for _ in removable_statuses)
        with self._write_lock, self._connection() as db:
            rows = db.execute(
                f"SELECT work_dir FROM jobs WHERE status IN ({placeholders})",  # noqa: S608
                removable_statuses,
            ).fetchall()
            db.execute(
                f"DELETE FROM jobs WHERE status IN ({placeholders})",  # noqa: S608
                removable_statuses,
            )
            db.execute(
                "DELETE FROM batches WHERE NOT EXISTS "
                "(SELECT 1 FROM jobs WHERE jobs.batch_id = batches.id)"
            )
            db.commit()
        work_dirs = [row["work_dir"] for row in rows if row["work_dir"]]
        return len(rows), work_dirs

    def delete_job(self, job_id: str) -> tuple[str | None, bool]:
        removable_statuses = {
            JobStatus.QUEUED.value,
            JobStatus.COMPLETED.value,
            JobStatus.FAILED.value,
            JobStatus.CANCELLED.value,
        }
        with self._write_lock, self._connection() as db:
            row = db.execute(
                "SELECT batch_id, status, work_dir FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in removable_statuses:
                raise ValueError("Video is still processing")
            db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            remaining = db.execute(
                "SELECT 1 FROM jobs WHERE batch_id = ? LIMIT 1", (row["batch_id"],)
            ).fetchone()
            batch_deleted = remaining is None
            if batch_deleted:
                db.execute("DELETE FROM batches WHERE id = ?", (row["batch_id"],))
            db.commit()
        return row["work_dir"], batch_deleted

    def delete_clip(self, clip_id: str) -> ClipRecord:
        with self._write_lock, self._connection() as db:
            row = db.execute(
                """SELECT clips.*, jobs.status AS job_status
                   FROM clips JOIN jobs ON jobs.id = clips.job_id
                   WHERE clips.id = ?""",
                (clip_id,),
            ).fetchone()
            if row is None:
                raise KeyError(clip_id)
            if row["job_status"] != JobStatus.COMPLETED.value:
                raise ValueError("Only clips from completed videos can be deleted")

            remaining = db.execute(
                "SELECT id FROM clips WHERE job_id = ? AND id != ? ORDER BY clip_index",
                (row["job_id"], clip_id),
            ).fetchall()
            if not remaining:
                raise ValueError("The final clip of a completed video cannot be deleted")

            deleted = self._row_to_clip(row)
            db.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
            for index, remaining_row in enumerate(remaining):
                db.execute(
                    "UPDATE clips SET clip_index = ? WHERE id = ?",
                    (-(index + 1), remaining_row["id"]),
                )
            for index, remaining_row in enumerate(remaining):
                db.execute(
                    "UPDATE clips SET clip_index = ? WHERE id = ?",
                    (index, remaining_row["id"]),
                )
            db.execute(
                "UPDATE jobs SET planned_clips = ?, updated_at = ? WHERE id = ?",
                (len(remaining), _now(), row["job_id"]),
            )
            db.commit()
        return deleted

    def retry_job(self, job_id: str) -> tuple[str | None, JobRecord]:
        retryable_statuses = {JobStatus.FAILED.value, JobStatus.CANCELLED.value}
        with self._write_lock, self._connection() as db:
            row = db.execute(
                "SELECT status, work_dir FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] not in retryable_statuses:
                raise ValueError("Only failed or cancelled videos can be retried")
            db.execute("DELETE FROM clips WHERE job_id = ?", (job_id,))
            db.execute(
                """UPDATE jobs
                   SET status = ?, stage = ?, progress = 0, error = NULL, work_dir = NULL,
                       planned_clips = 0, cancel_requested = 0, updated_at = ?
                   WHERE id = ?""",
                (JobStatus.QUEUED.value, Stage.WAITING.value, _now(), job_id),
            )
            db.commit()
        return row["work_dir"], self.get_job(job_id)

    def update_job(self, job_id: str, **changes: object) -> JobRecord:
        allowed = {
            "status",
            "stage",
            "progress",
            "title",
            "error",
            "work_dir",
            "planned_clips",
            "cancel_requested",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ValueError(f"Unknown job fields: {', '.join(sorted(unknown))}")
        values: dict[str, object] = dict(changes)
        if "status" in values and isinstance(values["status"], JobStatus):
            values["status"] = values["status"].value
        if "stage" in values and isinstance(values["stage"], Stage):
            values["stage"] = values["stage"].value
        if "progress" in values:
            values["progress"] = max(0.0, min(1.0, float(values["progress"])))
        if "cancel_requested" in values:
            values["cancel_requested"] = int(bool(values["cancel_requested"]))
        values["updated_at"] = _now()
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._write_lock, self._connection() as db:
            cursor = db.execute(
                f"UPDATE jobs SET {assignments} WHERE id = ?",  # noqa: S608 - keys are allowlisted
                (*values.values(), job_id),
            )
            if cursor.rowcount == 0:
                raise KeyError(job_id)
            db.commit()
        return self.get_job(job_id)

    def request_cancel(self, job_id: str) -> JobRecord:
        return self.update_job(job_id, cancel_requested=True)

    def list_pending_jobs(self) -> list[JobRecord]:
        with self._connection() as db:
            rows = db.execute(
                """SELECT * FROM jobs
                   WHERE status IN (?, ?)
                   ORDER BY created_at, position""",
                (JobStatus.QUEUED.value, JobStatus.RUNNING.value),
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def replace_clips(self, job_id: str, clips: list[ClipRecord]) -> None:
        with self._write_lock, self._connection() as db:
            db.execute("DELETE FROM clips WHERE job_id = ?", (job_id,))
            for clip in clips:
                clip.id = clip.id or uuid.uuid4().hex
                db.execute(
                    """INSERT INTO clips(id, job_id, clip_index, title, start, end, path)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (clip.id, job_id, clip.index, clip.title, clip.start, clip.end, clip.path),
                )
            db.commit()

    def replace_clips_and_plan(self, job_id: str, clips: list[ClipRecord]) -> None:
        with self._write_lock, self._connection() as db:
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] != JobStatus.COMPLETED.value:
                raise ValueError("Only completed videos can be regrouped")
            db.execute("DELETE FROM clips WHERE job_id = ?", (job_id,))
            for clip in clips:
                clip.id = clip.id or uuid.uuid4().hex
                db.execute(
                    """INSERT INTO clips(id, job_id, clip_index, title, start, end, path)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (clip.id, job_id, clip.index, clip.title, clip.start, clip.end, clip.path),
                )
            db.execute(
                "UPDATE jobs SET planned_clips = ?, updated_at = ? WHERE id = ?",
                (len(clips), _now(), job_id),
            )
            db.commit()

    def complete_job(self, job_id: str, clips: list[ClipRecord]) -> None:
        if not clips:
            raise ValueError("A completed job must contain at least one clip")
        with self._write_lock, self._connection() as db:
            row = db.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] != JobStatus.RUNNING.value:
                raise ValueError("Only a running job can publish a completed generation")
            db.execute("DELETE FROM clips WHERE job_id = ?", (job_id,))
            for clip in clips:
                clip.id = clip.id or uuid.uuid4().hex
                db.execute(
                    """INSERT INTO clips(id, job_id, clip_index, title, start, end, path)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (clip.id, job_id, clip.index, clip.title, clip.start, clip.end, clip.path),
                )
            db.execute(
                """UPDATE jobs
                   SET status = ?, stage = ?, progress = 1, planned_clips = ?, error = NULL,
                       updated_at = ?
                   WHERE id = ?""",
                (
                    JobStatus.COMPLETED.value,
                    Stage.COMPLETED.value,
                    len(clips),
                    _now(),
                    job_id,
                ),
            )
            db.commit()

    def list_completed_jobs(self) -> list[JobRecord]:
        with self._connection() as db:
            rows = db.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at, position",
                (JobStatus.COMPLETED.value,),
            ).fetchall()
            jobs = [self._row_to_job(row) for row in rows]
            for job in jobs:
                job.clips = self._list_clips(db, job.id)
            return jobs

    def _list_clips(self, db: sqlite3.Connection, job_id: str) -> list[ClipRecord]:
        rows = db.execute(
            "SELECT * FROM clips WHERE job_id = ? ORDER BY clip_index", (job_id,)
        ).fetchall()
        return [self._row_to_clip(row) for row in rows]

    def list_clips(self, job_id: str) -> list[ClipRecord]:
        with self._connection() as db:
            return self._list_clips(db, job_id)

    def get_clip(self, clip_id: str) -> ClipRecord:
        with self._connection() as db:
            row = db.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
        if row is None:
            raise KeyError(clip_id)
        return self._row_to_clip(row)
