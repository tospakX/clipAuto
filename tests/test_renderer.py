import asyncio
from pathlib import Path

import pytest

from clipauto.models import Topic, TranscriptSegment
from clipauto.renderer import build_ffmpeg_command, parse_ffmpeg_time, render_topics


def test_ffmpeg_command_produces_exact_vertical_delivery_format(tmp_path: Path):
    source = tmp_path / "source;safe.mp4"
    subtitles = tmp_path / "captions.ass"
    output = tmp_path / "clip.mp4"

    command = build_ffmpeg_command(source, subtitles, output, start=12.5, duration=65.0)
    joined = " ".join(command)

    assert command[0] == "ffmpeg"
    assert command[command.index("-ss") + 1] == "12.500"
    assert command[command.index("-t") + 1] == "65.000"
    assert "scale=270:480:force_original_aspect_ratio=increase" in joined
    assert "crop=270:480,gblur=sigma=8,scale=1080:1920:flags=bilinear" in joined
    assert "force_original_aspect_ratio=decrease" in joined
    assert "ass=filename=" in joined
    assert "setpts=PTS/1.10000" in joined
    assert "libx264" in command
    assert command[command.index("-preset") + 1] == "veryfast"
    assert command[command.index("-filter:a") + 1] == "atempo=1.10000"
    assert command[command.index("-c:a") + 1] == "aac"
    assert command[-1] == str(output)
    assert str(source) in command


def test_parses_ffmpeg_machine_progress_timestamp():
    assert parse_ffmpeg_time("out_time_us=32500000", duration=65.0) == 0.5
    assert parse_ffmpeg_time("progress=continue", duration=65.0) is None


@pytest.mark.asyncio
async def test_render_progress_uses_sped_up_output_duration(tmp_path: Path, monkeypatch):
    updates = []

    async def fake_run_process(command, on_line, cancel_event):
        on_line("out_time_us=5000000")

    monkeypatch.setattr("clipauto.renderer.run_process", fake_run_process)

    await render_topics(
        tmp_path / "source.mp4",
        tmp_path / "clips",
        [Topic("One", 0, 11)],
        [TranscriptSegment(0, 11, "Caption")],
        lambda index, total, progress: updates.append((index, total, progress)),
    )

    assert updates[0] == (0, 1, 0.5)
    assert updates[-1] == (0, 1, 1.0)


@pytest.mark.asyncio
async def test_renders_two_independent_clips_concurrently_in_output_order(
    tmp_path: Path, monkeypatch
):
    active = 0
    maximum_active = 0

    async def fake_run_process(command, on_line, cancel_event):
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1

    monkeypatch.setattr("clipauto.renderer.run_process", fake_run_process)
    topics = [
        Topic("One", 0, 10),
        Topic("Two", 10, 20),
        Topic("Three", 20, 30),
    ]

    outputs = await render_topics(
        tmp_path / "source.mp4",
        tmp_path / "clips",
        topics,
        [TranscriptSegment(0, 30, "Caption")],
        lambda *_: None,
    )

    assert maximum_active == 2
    assert [path.name for path in outputs] == ["clip_01.mp4", "clip_02.mp4", "clip_03.mp4"]
