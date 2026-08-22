from pathlib import Path

from clipauto.downloader import (
    build_download_command,
    needs_brave_fallback,
    parse_chapters,
    parse_progress,
)


def test_parses_ytdlp_machine_progress():
    assert parse_progress("download:37.4%") == 0.374
    assert parse_progress("download:NA%") is None


def test_brave_fallback_is_limited_to_access_failures():
    assert needs_brave_fallback("ERROR: HTTP Error 403: Forbidden")
    assert needs_brave_fallback("Sign in to confirm your age")
    assert needs_brave_fallback("Sign in to confirm you’re not a bot")
    assert not needs_brave_fallback("ERROR: Unsupported URL")
    assert not needs_brave_fallback("No space left on device")


def test_download_command_uses_native_brave_cookie_option(tmp_path: Path):
    command = build_download_command("https://youtu.be/a;touch-pwn", tmp_path, use_brave=True)

    assert command[0] == "yt-dlp"
    assert command[-1] == "https://youtu.be/a;touch-pwn"
    assert command[command.index("--cookies-from-browser") + 1] == "brave"
    assert "--newline" in command


def test_download_command_requests_ytdlp_parsed_description_chapters(tmp_path: Path):
    command = build_download_command("https://youtu.be/video", tmp_path)

    assert "after_move:clipauto_chapters:%(chapters)j" in command


def test_download_command_does_not_fetch_resolution_above_output_size(tmp_path: Path):
    command = build_download_command("https://youtu.be/video", tmp_path)

    assert command[command.index("--format") + 1] == "bv*[height<=1080]+ba/b[height<=1080]"
    assert command[command.index("--concurrent-fragments") + 1] == "4"


def test_parses_ytdlp_chapter_json_without_interpreting_description_text():
    raw = (
        '[{"start_time":0,"end_time":42.5,"title":"Coffee"},'
        '{"start_time":42.5,"end_time":90,"title":"Sleep"}]'
    )

    assert parse_chapters(raw) == [
        {"start_time": 0, "end_time": 42.5, "title": "Coffee"},
        {"start_time": 42.5, "end_time": 90, "title": "Sleep"},
    ]


def test_invalid_or_missing_ytdlp_chapters_become_empty_metadata():
    assert parse_chapters("null") == []
    assert parse_chapters("not-json") == []
    assert parse_chapters('{"title":"not a list"}') == []
