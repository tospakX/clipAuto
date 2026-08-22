from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from clipauto.models import Topic, TranscriptSegment
from clipauto.process import run_process
from clipauto.subtitles import write_ass

OUTPUT_SPEED = 1.10


def _filter_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\\\''")


def build_ffmpeg_command(
    source: Path,
    subtitles: Path,
    output: Path,
    start: float,
    duration: float,
    speed: float = OUTPUT_SPEED,
) -> list[str]:
    if speed <= 0:
        raise ValueError("Playback speed must be positive")
    filters = (
        "[0:v]scale=270:480:force_original_aspect_ratio=increase,"
        "crop=270:480,gblur=sigma=8,scale=1080:1920:flags=bilinear[bg];"
        "[0:v]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[base];"
        f"[base]ass=filename='{_filter_path(subtitles)}',setpts=PTS/{speed:.5f}[v]"
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        str(source),
        "-filter_complex",
        filters,
        "-map",
        "[v]",
        "-map",
        "0:a?",
        "-filter:a",
        f"atempo={speed:.5f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        "-progress",
        "pipe:1",
        "-nostats",
        str(output),
    ]


def parse_ffmpeg_time(line: str, duration: float) -> float | None:
    if not line.startswith("out_time_us=") or duration <= 0:
        return None
    try:
        return min(1.0, max(0.0, float(line.split("=", 1)[1]) / 1_000_000 / duration))
    except ValueError:
        return None


async def render_topics(
    source: Path,
    output_dir: Path,
    topics: list[Topic],
    segments: list[TranscriptSegment],
    progress: Callable[[int, int, float], None],
    cancel_event: asyncio.Event | None = None,
    concurrency: int = 2,
) -> list[Path]:
    if concurrency < 1:
        raise ValueError("Render concurrency must be at least one")
    output_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(concurrency)

    async def render_one(index: int, topic: Topic) -> Path:
        ass = write_ass(output_dir / f"clip_{index + 1:02d}.ass", segments, topic.start, topic.end)
        output = output_dir / f"clip_{index + 1:02d}.mp4"
        duration = topic.end - topic.start

        def handle(
            line: str,
            current: int = index,
            clip_duration: float = duration / OUTPUT_SPEED,
            total: int = len(topics),
        ) -> None:
            value = parse_ffmpeg_time(line, clip_duration)
            if value is not None:
                progress(current, total, value)

        async with semaphore:
            await run_process(
                build_ffmpeg_command(source, ass, output, topic.start, duration),
                handle,
                cancel_event,
            )
        progress(index, len(topics), 1.0)
        return output

    return list(
        await asyncio.gather(
            *(render_one(index, topic) for index, topic in enumerate(topics))
        )
    )
