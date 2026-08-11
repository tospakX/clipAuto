from __future__ import annotations

import importlib
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import DEFAULT_OLLAMA_URL


class DependencyError(RuntimeError):
    """Raised when a required local dependency is unavailable."""


@dataclass(frozen=True)
class DependencyReport:
    ollama_models: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _check_ffmpeg_encoders() -> list[str]:
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [f"Could not inspect FFmpeg encoders ({exc})."]
    if result.returncode:
        return ["FFmpeg could not list its available encoders."]
    problems = []
    if "libx264" not in result.stdout:
        problems.append("FFmpeg is missing the required H.264 encoder `libx264`.")
    if " aac " not in f" {result.stdout} ":
        problems.append("FFmpeg is missing the required AAC audio encoder `aac`.")
    return problems


def _ollama_models(base_url: str, timeout: float = 5.0) -> tuple[str, ...]:
    try:
        with urllib.request.urlopen(
            f"{base_url.rstrip('/')}/api/tags", timeout=timeout
        ) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise DependencyError(
            f"Ollama is not reachable at {base_url}. Start it with `ollama serve`. ({exc})"
        ) from exc
    names = tuple(item.get("name", "") for item in payload.get("models", []) if item.get("name"))
    if not names:
        raise DependencyError(
            "Ollama is running but has no models. Install one with `ollama pull <model>`."
        )
    return names


def check_dependencies(base_url: str = DEFAULT_OLLAMA_URL) -> DependencyReport:
    problems: list[str] = []
    warnings: list[str] = []
    faster_whisper_ready = True
    for executable, hint in (
        ("yt-dlp", "Install yt-dlp and ensure its executable is on PATH."),
        ("ffmpeg", "Install FFmpeg and ensure `ffmpeg` and `ffprobe` are on PATH."),
        ("ffprobe", "Install FFmpeg and ensure `ffmpeg` and `ffprobe` are on PATH."),
        ("ollama", "Install Ollama and ensure its executable is on PATH."),
    ):
        if shutil.which(executable) is None:
            problems.append(f"Missing executable `{executable}`. {hint}")

    for module, package in (
        ("yt_dlp", "yt-dlp"),
        ("scenedetect", "scenedetect[opencv]"),
        ("cv2", "opencv-python"),
        ("faster_whisper", "faster-whisper"),
    ):
        try:
            importlib.import_module(module)
        except Exception as exc:
            if module == "faster_whisper":
                faster_whisper_ready = False
            problems.append(
                f"Python package `{package}` is missing or cannot load ({exc}). "
                "Run `python -m pip install -e .`."
            )

    if shutil.which("ffmpeg") is not None:
        problems.extend(_check_ffmpeg_encoders())

    models: tuple[str, ...] = ()
    if shutil.which("ollama") is not None:
        try:
            models = _ollama_models(base_url)
        except DependencyError as exc:
            problems.append(str(exc))
    if problems:
        raise DependencyError("Dependency check failed:\n- " + "\n- ".join(problems))
    if faster_whisper_ready:
        from .transcriber import runtime_warning

        warning = runtime_warning()
        if warning:
            warnings.append(warning)
    return DependencyReport(ollama_models=models, warnings=tuple(warnings))
