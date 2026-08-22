from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from clipauto.process import ProcessError, run_process


@dataclass(slots=True)
class DownloadResult:
    path: Path
    title: str
    duration: float
    used_brave_cookies: bool
    chapters: list[dict] = field(default_factory=list)


def parse_progress(line: str) -> float | None:
    match = re.fullmatch(r"download:(\d+(?:\.\d+)?)%", line.strip())
    return min(1.0, float(match.group(1)) / 100) if match else None


def needs_brave_fallback(output: str) -> bool:
    lowered = output.lower()
    markers = ("403", "age", "sign in", "not a bot", "login", "cookies")
    return any(marker in lowered for marker in markers)


def parse_chapters(value: str) -> list[dict]:
    try:
        chapters = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(chapters, list) or not all(isinstance(item, dict) for item in chapters):
        return []
    return chapters


def build_download_command(url: str, work_dir: Path, use_brave: bool = False) -> list[str]:
    command = [
        "yt-dlp",
        "--newline",
        "--no-playlist",
        "--concurrent-fragments",
        "4",
        "--restrict-filenames",
        "--format",
        "bv*[height<=1080]+ba/b[height<=1080]",
        "--merge-output-format",
        "mp4",
        "--output",
        str(work_dir / "source.%(ext)s"),
        "--progress-template",
        "download:download:%(progress._percent_str)s",
        "--print",
        "after_move:clipauto_filepath:%(filepath)s",
        "--print",
        "after_move:clipauto_title:%(title)s",
        "--print",
        "after_move:clipauto_duration:%(duration)s",
        "--print",
        "after_move:clipauto_chapters:%(chapters)j",
    ]
    if use_brave:
        command.extend(["--cookies-from-browser", "brave"])
    command.append(url)
    return command


async def download_video(
    url: str,
    work_dir: Path,
    progress: Callable[[float], None],
    cancel_event: asyncio.Event | None = None,
) -> DownloadResult:
    work_dir.mkdir(parents=True, exist_ok=True)

    async def attempt(use_brave: bool) -> DownloadResult:
        metadata: dict[str, str] = {}

        def handle(line: str) -> None:
            value = parse_progress(line.replace(" ", ""))
            if value is not None:
                progress(value)
            for key in ("filepath", "title", "duration", "chapters"):
                prefix = f"clipauto_{key}:"
                if line.startswith(prefix):
                    metadata[key] = line[len(prefix) :]

        output = await run_process(
            build_download_command(url, work_dir, use_brave), handle, cancel_event
        )
        if "filepath" not in metadata:
            raise ProcessError(["yt-dlp"], 1, f"yt-dlp did not report an output file\n{output}")
        return DownloadResult(
            Path(metadata["filepath"]),
            metadata.get("title", "Untitled video"),
            float(metadata.get("duration") or 0),
            use_brave,
            parse_chapters(metadata.get("chapters", "null")),
        )

    try:
        return await attempt(False)
    except ProcessError as error:
        if not needs_brave_fallback(error.output):
            raise
        return await attempt(True)
