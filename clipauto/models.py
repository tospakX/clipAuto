from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from urllib.parse import parse_qs, urlparse


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Stage(StrEnum):
    WAITING = "waiting"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    SEGMENTING = "segmenting"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class ClipRecord:
    id: str
    job_id: str
    index: int
    title: str
    start: float
    end: float
    path: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class JobRecord:
    id: str
    batch_id: str
    url: str
    position: int
    status: JobStatus = JobStatus.QUEUED
    stage: Stage = Stage.WAITING
    progress: float = 0.0
    title: str | None = None
    error: str | None = None
    work_dir: str | None = None
    planned_clips: int = 0
    cancel_requested: bool = False
    created_at: str = ""
    updated_at: str = ""
    clips: list[ClipRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        result = asdict(self)
        result["status"] = self.status.value
        result["stage"] = self.stage.value
        return result


@dataclass(slots=True)
class BatchRecord:
    id: str
    created_at: str
    jobs: list[JobRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "jobs": [j.to_dict() for j in self.jobs],
        }


@dataclass(slots=True)
class TranscriptWord:
    start: float
    end: float
    text: str


@dataclass(slots=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: list[TranscriptWord] = field(default_factory=list)


@dataclass(slots=True)
class Topic:
    title: str
    start: float
    end: float


class InvalidURLs(ValueError):
    def __init__(self, message: str, invalid: list[str] | None = None):
        super().__init__(message)
        self.invalid = invalid or []


_TOKEN_SPLIT = re.compile(r"[\s,]+")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def _is_video_location(host: str, path: str, query: str) -> bool:
    parts = [part for part in path.split("/") if part]
    if host == "youtu.be":
        return len(parts) == 1
    if path.rstrip("/") == "/watch":
        return bool(parse_qs(query).get("v", [""])[0])
    return len(parts) == 2 and parts[0] in {"shorts", "live", "embed"}


def parse_youtube_urls(text: str, max_urls: int = 200) -> list[str]:
    tokens = [token.strip() for token in _TOKEN_SPLIT.split(text) if token.strip()]
    if not tokens:
        raise InvalidURLs("No YouTube URLs were provided")

    urls = list(dict.fromkeys(tokens))
    if len(urls) > max_urls:
        raise InvalidURLs(f"A batch can contain at most {max_urls} URLs")

    invalid = []
    for url in urls:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme not in {"http", "https"}
            or host not in _YOUTUBE_HOSTS
            or not _is_video_location(host, parsed.path, parsed.query)
        ):
            invalid.append(url)
    if invalid:
        raise InvalidURLs("Some entries are not valid YouTube URLs", invalid)
    return urls
