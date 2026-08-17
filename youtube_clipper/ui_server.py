"""Dependency-free local web interface for the clipping pipeline."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
import uuid
import webbrowser
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .config import (
    ALLOWED_SPEEDS,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_WORK_DIR,
)
from .dependencies import DependencyError, DependencyReport, check_dependencies
from .pipeline import ProgressCallback, run_pipeline

LOGGER = logging.getLogger(__name__)
PipelineRunner = Callable[..., list[Path]]
DependencyChecker = Callable[[str], DependencyReport]
ALLOWED_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")


class JobBusyError(RuntimeError):
    """Backward-compatible error for a duplicate active single job."""


def _youtube_video_id(parsed) -> str | None:
    host = (parsed.hostname or "").lower()
    parts = [unquote(part) for part in parsed.path.split("/") if part]
    if host == "youtu.be":
        candidate = parts[0] if parts else ""
    elif parsed.path.rstrip("/") == "/watch":
        candidate = parse_qs(parsed.query).get("v", [""])[0]
    elif parts and parts[0] in {"shorts", "embed", "live"}:
        candidate = parts[1] if len(parts) > 1 else ""
    else:
        candidate = ""
    is_safe = candidate and re.fullmatch(r"[A-Za-z0-9_-]+", candidate)
    return candidate if is_safe else None


def validate_youtube_url(value: str) -> str:
    """Return a normalized YouTube URL or raise a user-facing error."""
    value = value.strip()
    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    is_youtube = host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")
    video_id = _youtube_video_id(parsed)
    if parsed.scheme not in {"http", "https"} or not is_youtube or video_id is None:
        raise ValueError("Paste a valid youtube.com or youtu.be video URL")
    return f"https://www.youtube.com/watch?v={video_id}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ClipJob:
    id: str
    url: str
    speed: float
    whisper_model: str
    video_id: str
    status: str = "waiting"
    progress: int = 0
    stage: str = "Waiting to start"
    created_at: str = field(default_factory=_now)
    finished_at: str | None = None
    outputs: list[Path] = field(default_factory=list)
    error: str | None = None
    events: list[dict[str, object]] = field(default_factory=list)

    def public(self) -> dict[str, object]:
        return {
            "id": self.id,
            "url": self.url,
            "video_id": self.video_id,
            "status": self.status,
            "progress": self.progress,
            "stage": self.stage,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
            "error": self.error,
            "events": list(self.events),
            "clips": [
                {
                    "name": path.name,
                    "url": f"/clips/{self.id}/{path.name}",
                }
                for path in self.outputs
            ],
        }


class JobManager:
    """Run one local pipeline at a time and expose thread-safe job snapshots."""

    def __init__(
        self,
        output_dir: Path = DEFAULT_OUTPUT_DIR,
        work_dir: Path = DEFAULT_WORK_DIR,
        ollama_url: str = DEFAULT_OLLAMA_URL,
        pipeline_runner: PipelineRunner = run_pipeline,
    ) -> None:
        self.output_dir = output_dir
        self.work_dir = work_dir
        self.ollama_url = ollama_url
        self.pipeline_runner = pipeline_runner
        self._jobs: dict[str, ClipJob] = {}
        self._lock = threading.Lock()
        self._waiting: deque[str] = deque()
        self._worker: threading.Thread | None = None

    def start(self, url: str, speed: float, whisper_model: str) -> dict[str, object]:
        submission = self.enqueue([url], speed, whisper_model)
        if not submission["jobs"]:
            raise JobBusyError("This video is already waiting or processing")
        return submission["jobs"][0]

    def enqueue(
        self, urls: list[str], speed: float, whisper_model: str
    ) -> dict[str, list[object]]:
        if not urls:
            raise ValueError("Add at least one YouTube video URL")
        if speed not in ALLOWED_SPEEDS:
            raise ValueError(f"Speed must be one of {ALLOWED_SPEEDS}")
        if whisper_model not in ALLOWED_WHISPER_MODELS:
            raise ValueError("Choose a supported transcription quality")
        normalized = [validate_youtube_url(value) for value in urls]

        with self._lock:
            active_ids = {
                job.video_id
                for job in self._jobs.values()
                if job.status in {"waiting", "downloading", "analyzing", "clipping"}
            }
            jobs: list[dict[str, object]] = []
            duplicates: list[str] = []
            for url in normalized:
                video_id = str(parse_qs(urlparse(url).query)["v"][0])
                if video_id in active_ids:
                    duplicates.append(url)
                    continue
                active_ids.add(video_id)
                job = ClipJob(uuid.uuid4().hex[:12], url, speed, whisper_model, video_id)
                self._jobs[job.id] = job
                self._waiting.append(job.id)
                jobs.append(job.public())

            if jobs and (self._worker is None or not self._worker.is_alive()):
                self._worker = threading.Thread(
                    target=self._work_loop,
                    daemon=True,
                    name="clipauto-queue",
                )
                self._worker.start()
        return {"jobs": jobs, "duplicates": duplicates}

    def list(self) -> list[dict[str, object]]:
        with self._lock:
            return [job.public() for job in self._jobs.values()]

    def get(self, job_id: str) -> dict[str, object] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return job.public() if job else None

    def remove(self, job_id: str) -> bool:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "waiting":
                return False
            try:
                self._waiting.remove(job_id)
            except ValueError:
                return False
            del self._jobs[job_id]
            return True

    def output_for(self, job_id: str, filename: str) -> Path | None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for output in job.outputs:
                if output.name == filename and output.is_file():
                    return output
        return None

    def _update(self, job_id: str, progress: int, stage: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            if progress >= 86:
                job.status = "clipping"
            elif progress >= 25:
                job.status = "analyzing"
            else:
                job.status = "downloading"
            job.progress = max(job.progress, max(0, min(100, progress)))
            job.stage = stage
            job.events.append(
                {
                    "time": _now(),
                    "progress": job.progress,
                    "stage": stage,
                    "status": job.status,
                }
            )
            job.events = job.events[-20:]

    def _work_loop(self) -> None:
        while True:
            with self._lock:
                if not self._waiting:
                    self._worker = None
                    return
                job_id = self._waiting.popleft()
                if job_id not in self._jobs:
                    continue
            self._run(job_id)

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.status = "downloading"
            job.stage = "Preparing download"
            job.events.append(
                {
                    "time": _now(),
                    "progress": 0,
                    "stage": job.stage,
                    "status": job.status,
                }
            )
            url, speed, model = job.url, job.speed, job.whisper_model

        callback: ProgressCallback = partial(self._update, job_id)
        try:
            outputs = self.pipeline_runner(
                url,
                self.output_dir,
                self.work_dir,
                speed,
                model,
                "auto",
                "default",
                self.ollama_url,
                callback,
            )
            with self._lock:
                job = self._jobs[job_id]
                job.outputs = list(outputs)
                job.status = "completed"
                job.progress = 100
                job.stage = "Your clips are ready"
                job.finished_at = _now()
        except Exception as exc:
            LOGGER.exception("UI clipping job %s failed", job_id)
            with self._lock:
                job = self._jobs[job_id]
                job.status = "failed"
                job.stage = "Processing stopped"
                job.error = str(exc)
                job.finished_at = _now()


class ClipperHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        server_address: tuple[str, int],
        manager: JobManager,
        dependency_checker: DependencyChecker,
        ollama_url: str,
    ) -> None:
        super().__init__(server_address, UIRequestHandler)
        self.manager = manager
        self.dependency_checker = dependency_checker
        self.ollama_url = ollama_url


class UIRequestHandler(BaseHTTPRequestHandler):
    server: ClipperHTTPServer

    def log_message(self, format: str, *args: object) -> None:
        LOGGER.debug("UI request: " + format, *args)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/":
            self._asset("index.html")
        elif path.startswith("/assets/"):
            self._asset(path.removeprefix("/assets/"))
        elif path == "/api/health":
            self._health()
        elif path == "/api/jobs":
            self._json(HTTPStatus.OK, {"jobs": self.server.manager.list()})
        elif path.startswith("/api/jobs/"):
            self._job(path.rsplit("/", 1)[-1])
        elif path.startswith("/clips/"):
            self._clip(path)
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/jobs":
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        try:
            payload = self._read_json()
            raw_urls = payload.get("urls")
            if raw_urls is None and "url" in payload:
                raw_urls = [payload["url"]]
            if (
                not isinstance(raw_urls, list)
                or not 1 <= len(raw_urls)
                or any(not isinstance(value, str) for value in raw_urls)
            ):
                raise ValueError("urls must be a list of 1 or more YouTube links")
            submission = self.server.manager.enqueue(
                raw_urls,
                float(payload.get("speed", 1.0)),
                str(payload.get("whisper_model", DEFAULT_WHISPER_MODEL)),
            )
            self._json(HTTPStatus.ACCEPTED, submission)
        except JobBusyError as exc:
            self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def do_DELETE(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if not path.startswith("/api/jobs/"):
            self._json(HTTPStatus.NOT_FOUND, {"error": "Not found"})
            return
        job_id = path.rsplit("/", 1)[-1]
        if self.server.manager.remove(job_id):
            self._json(HTTPStatus.OK, {"removed": True})
        else:
            self._json(
                HTTPStatus.CONFLICT,
                {"error": "Only waiting queue items can be removed"},
            )

    def _health(self) -> None:
        try:
            report = self.server.dependency_checker(self.server.ollama_url)
            self._json(
                HTTPStatus.OK,
                {
                    "ready": True,
                    "version": __version__,
                    "models": list(report.ollama_models),
                    "warnings": list(report.warnings),
                    "message": "All local tools are ready",
                },
            )
        except DependencyError as exc:
            self._json(
                HTTPStatus.SERVICE_UNAVAILABLE,
                {
                    "ready": False,
                    "version": __version__,
                    "models": [],
                    "warnings": [],
                    "message": str(exc),
                },
            )

    def _job(self, job_id: str) -> None:
        job = self.server.manager.get(job_id)
        if job is None:
            self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown job"})
        else:
            self._json(HTTPStatus.OK, job)

    def _clip(self, request_path: str) -> None:
        parts = request_path.strip("/").split("/")
        if len(parts) != 3:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        output = self.server.manager.output_for(parts[1], unquote(parts[2]))
        if output is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_file(output)

    def _send_file(self, path: Path) -> None:
        """Stream a clip with byte-range support for browser seeking and previews."""
        size = path.stat().st_size
        start, end = 0, size - 1
        status = HTTPStatus.OK
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            try:
                start_text, end_text = range_header.removeprefix("bytes=").split("-", 1)
                if start_text:
                    start = int(start_text)
                    end = min(int(end_text), size - 1) if end_text else size - 1
                else:
                    suffix_length = int(end_text)
                    if suffix_length <= 0:
                        raise ValueError
                    start = max(0, size - suffix_length)
                    end = size - 1
                if start < 0 or start > end or start >= size:
                    raise ValueError
                status = HTTPStatus.PARTIAL_CONTENT
            except ValueError:
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return

        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(length))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "private, no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        if status == HTTPStatus.PARTIAL_CONTENT:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        remaining = length
        with path.open("rb") as handle:
            handle.seek(start)
            while remaining:
                chunk = handle.read(min(64 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)

    def _asset(self, name: str) -> None:
        if name not in {"index.html", "app.css", "app.js"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        resource = files("youtube_clipper.ui").joinpath(name)
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        self._send_bytes(HTTPStatus.OK, resource.read_bytes(), content_type)


    def _read_json(self) -> dict[str, object]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid request length") from exc
        if length <= 0:
            raise ValueError("Invalid request body")
        if length > 2_000_000:
            raise ValueError("Request body too large")
        payload = json.loads(self.rfile.read(length))
        if not isinstance(payload, dict):
            raise ValueError("Request must be a JSON object")
        return payload
    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        data = json.dumps(payload).encode()
        self._send_bytes(status, data, "application/json; charset=utf-8")

    def _send_bytes(self, status: HTTPStatus, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "img-src 'self' data:; media-src 'self'; connect-src 'self'",
        )
        self.end_headers()
        self.wfile.write(data)


def create_server(
    host: str = "127.0.0.1",
    port: int = 8787,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    work_dir: Path = DEFAULT_WORK_DIR,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    pipeline_runner: PipelineRunner = run_pipeline,
    dependency_checker: DependencyChecker = check_dependencies,
) -> ClipperHTTPServer:
    manager = JobManager(output_dir, work_dir, ollama_url, pipeline_runner)
    return ClipperHTTPServer((host, port), manager, dependency_checker, ollama_url)


def serve_ui(
    host: str = "127.0.0.1",
    port: int = 8787,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    work_dir: Path = DEFAULT_WORK_DIR,
    ollama_url: str = DEFAULT_OLLAMA_URL,
    open_browser: bool = True,
) -> None:
    server = create_server(host, port, output_dir, work_dir, ollama_url)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}"
    LOGGER.info("LocalCut interface: %s", url)
    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()
