import subprocess
from pathlib import Path

import pytest

from clipauto.validation import MediaValidationError, validate_reel


def _make_video(
    path: Path,
    *,
    size: str = "1080x1920",
    video_codec: str = "libx264",
    with_audio: bool = True,
) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=black:size={size}:rate=2:duration=1",
    ]
    if with_audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=440:sample_rate=44100:duration=1",
                "-shortest",
            ]
        )
    command.extend(["-c:v", video_codec, "-pix_fmt", "yuv420p"])
    if video_codec == "libx264":
        command.extend(["-preset", "ultrafast"])
    if with_audio:
        command.extend(["-c:a", "aac"])
    command.extend(["-movflags", "+faststart", str(path)])
    subprocess.run(command, check=True)


def test_accepts_fully_decodable_instagram_reel(tmp_path: Path):
    path = tmp_path / "valid.mp4"
    _make_video(path)

    info = validate_reel(path, expected_duration=1.0)

    assert info.duration == pytest.approx(1.0, abs=0.1)
    assert (info.width, info.height) == (1080, 1920)
    assert info.video_codec == "h264"
    assert info.audio_codec == "aac"


def test_rejects_missing_render(tmp_path: Path):
    with pytest.raises(MediaValidationError, match="missing"):
        validate_reel(tmp_path / "missing.mp4", expected_duration=1.0)


@pytest.mark.parametrize(
    "size, codec, message",
    [
        ("720x1280", "libx264", "1080x1920"),
        ("1080x1920", "mpeg4", "H.264"),
    ],
)
def test_rejects_wrong_delivery_format(tmp_path: Path, size: str, codec: str, message: str):
    path = tmp_path / "wrong.mp4"
    _make_video(path, size=size, video_codec=codec)

    with pytest.raises(MediaValidationError, match=message):
        validate_reel(path, expected_duration=1.0)


def test_rejects_wrong_rendered_duration(tmp_path: Path):
    path = tmp_path / "wrong-duration.mp4"
    _make_video(path)

    with pytest.raises(MediaValidationError, match="duration"):
        validate_reel(path, expected_duration=3.0)


def test_rejects_truncated_media(tmp_path: Path):
    valid = tmp_path / "valid.mp4"
    broken = tmp_path / "broken.mp4"
    _make_video(valid)
    payload = valid.read_bytes()
    broken.write_bytes(payload[: len(payload) // 2])

    with pytest.raises(MediaValidationError, match="corrupt|decode|probe"):
        validate_reel(broken, expected_duration=1.0)


def test_accepts_silent_source(tmp_path: Path):
    path = tmp_path / "silent.mp4"
    _make_video(path, with_audio=False)

    info = validate_reel(path, expected_duration=1.0)

    assert info.audio_codec is None
