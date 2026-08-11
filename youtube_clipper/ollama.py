from __future__ import annotations

import json
import logging
import math
import re
import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import DEFAULT_OLLAMA_TIMEOUT, DEFAULT_OLLAMA_URL, MAX_TRANSCRIPT_CHARACTERS
from .types import BoundarySuggestion, TranscriptSegment, VideoTimestamp

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TranscriptWindow:
    start: float
    end: float
    text: str


def _transcript_windows(
    segments: list[TranscriptSegment], limit: int = MAX_TRANSCRIPT_CHARACTERS
) -> list[TranscriptWindow]:
    """Split long transcripts at segment boundaries while retaining small context overlaps."""
    if limit < 1:
        raise ValueError("transcript window limit must be positive")
    lines = [(item, f"[{item.start:.1f}-{item.end:.1f}] {item.text}") for item in segments]
    windows: list[TranscriptWindow] = []
    current: list[tuple[TranscriptSegment, str]] = []
    current_chars = 0

    for segment, raw_line in lines:
        line = raw_line[:limit]
        added_chars = len(line) + (1 if current else 0)
        if current and current_chars + added_chars > limit:
            windows.append(
                TranscriptWindow(
                    current[0][0].start,
                    current[-1][0].end,
                    "\n".join(value for _item, value in current),
                )
            )
            # Two short preceding segments help the model understand whether the next window
            # begins mid-topic. Drop overlap lines if they would crowd out the new segment.
            current = current[-2:]
            while current and sum(len(value) + 1 for _item, value in current) + len(line) > limit:
                current.pop(0)
            current_chars = sum(len(value) + 1 for _item, value in current)
        current.append((segment, line))
        current_chars += len(line) + (1 if len(current) > 1 else 0)

    if current:
        windows.append(
            TranscriptWindow(
                current[0][0].start,
                current[-1][0].end,
                "\n".join(value for _item, value in current),
            )
        )
    return windows


def _parse_boundary_response(content: object) -> list[BoundarySuggestion]:
    try:
        payload = json.loads(content) if isinstance(content, str) else {}
        boundaries = payload.get("boundaries", [])
    except (json.JSONDecodeError, AttributeError) as exc:
        raise RuntimeError("Ollama returned invalid boundary JSON") from exc
    if not isinstance(boundaries, list):
        raise RuntimeError("Ollama returned invalid boundary JSON")

    suggestions: list[BoundarySuggestion] = []
    for item in boundaries:
        if not isinstance(item, dict) or "timestamp" not in item:
            continue
        try:
            timestamp = float(item["timestamp"])
            confidence = float(item.get("confidence", 0.7))
        except (TypeError, ValueError):
            continue
        if timestamp < 0 or not math.isfinite(timestamp) or not math.isfinite(confidence):
            continue
        suggestions.append(
            BoundarySuggestion(
                timestamp=timestamp,
                confidence=max(0.0, min(1.0, confidence)),
                reason=str(item.get("reason", "")),
            )
        )
    return suggestions


def _deduplicate_suggestions(
    suggestions: list[BoundarySuggestion], tolerance: float = 1.5
) -> list[BoundarySuggestion]:
    result: list[BoundarySuggestion] = []
    for suggestion in sorted(suggestions, key=lambda item: item.timestamp):
        duplicate = next(
            (
                index
                for index, existing in enumerate(result)
                if abs(existing.timestamp - suggestion.timestamp) <= tolerance
            ),
            None,
        )
        if duplicate is None:
            result.append(suggestion)
        elif suggestion.confidence > result[duplicate].confidence:
            result[duplicate] = suggestion
    return sorted(result, key=lambda item: item.timestamp)


def _parameter_billions(model: dict) -> float:
    value = str(model.get("details", {}).get("parameter_size", "0"))
    match = re.search(r"([0-9.]+)\s*B", value, re.IGNORECASE)
    return float(match.group(1)) if match else 0.0


def choose_model(models: list[dict]) -> str:
    candidates = []
    for model in models:
        name = model.get("name") or model.get("model")
        capabilities = model.get("capabilities", [])
        if not name or (capabilities and "completion" not in capabilities):
            continue
        size = _parameter_billions(model)
        lower = name.lower()
        quality = sum(token in lower for token in ("qwen", "llama", "mistral", "gemma"))
        # 7B-14B models are a good speed/quality default for structured boundary reasoning.
        size_fit = 3 if 7 <= size <= 14 else 2 if 3 <= size < 7 else 1
        candidates.append(((size_fit, quality, min(size, 30)), name))
    if not candidates:
        raise RuntimeError("Ollama has no installed text-completion model")
    return max(candidates)[1]


class OllamaBoundaryReasoner:
    def __init__(self, base_url: str = DEFAULT_OLLAMA_URL, timeout: float = DEFAULT_OLLAMA_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _request(self, path: str, payload: dict | None = None) -> dict:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"{self.base_url}{path}", data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.load(response)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Ollama request to {path} failed: {exc}") from exc

    def installed_models(self) -> list[dict]:
        return self._request("/api/tags").get("models", [])

    def suggest_boundaries(
        self,
        segments: list[TranscriptSegment],
        scene_times: list[float],
        marker_times: list[float],
        video_timestamps: tuple[VideoTimestamp, ...] = (),
    ) -> list[BoundarySuggestion]:
        model = choose_model(self.installed_models())
        LOGGER.info("Using local Ollama model '%s' for topic-boundary reasoning", model)
        timestamp_hints = [
            {"timestamp": item.timestamp, "title": item.title} for item in video_timestamps
        ]
        reliable_timestamps = [item for item in video_timestamps if item.confidence >= 0.8]
        has_creator_topic_map = (
            len(reliable_timestamps) >= 2
            and min((item.timestamp for item in reliable_timestamps), default=999) <= 4
        )
        creator_guidance = (
            "The creator timestamps form an authoritative topic map. Do not add a boundary "
            "inside one of those named topics unless an explicit spoken numbered/topic marker "
            "clearly starts a separate topic omitted by the creator."
            if has_creator_topic_map
            else "Treat description timestamps as candidate evidence, not automatic proof."
        )
        windows = _transcript_windows(segments)
        LOGGER.info("Analyzing transcript in %d Ollama window(s)", len(windows))
        schema = {
            "type": "object",
            "properties": {
                "boundaries": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "timestamp": {"type": "number"},
                            "confidence": {"type": "number"},
                            "reason": {"type": "string"},
                        },
                        "required": ["timestamp", "confidence", "reason"],
                    },
                }
            },
            "required": ["boundaries"],
        }
        suggestions: list[BoundarySuggestion] = []
        for index, window in enumerate(windows, start=1):
            window_markers = [
                value for value in marker_times if window.start - 4 <= value <= window.end + 4
            ]
            prompt = f"""Identify timestamps where a genuinely new, independently useful topic or
numbered point begins.
Use the transcript as primary semantic evidence. Numbered phrases and the candidate marker
times are strong evidence. {creator_guidance}
Do not split a named story or subject into its introduction, theories, investigation, examples,
consequences, or resolution. Those are normal progression within one topic. If there are no true
topic changes, return an empty boundaries array. Never include timestamp 0. Return JSON only.
This is transcript window {index} of {len(windows)}, covering {window.start:.1f}-{window.end:.1f}
seconds. Its first line may continue a topic from the preceding window and is not automatically a
new topic.

Candidate numbered/topic markers in this window (seconds): {window_markers}
YouTube description/chapter timestamps: {timestamp_hints}
Transcript:
{window.text}
"""
            response = self._request(
                "/api/chat",
                {
                    "model": model,
                    "stream": False,
                    "think": False,
                    "format": schema,
                    "options": {"temperature": 0},
                    "messages": [
                        {
                            "role": "system",
                            "content": "You analyze topic transitions in timestamped transcripts.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                },
            )
            suggestions.extend(
                _parse_boundary_response(response.get("message", {}).get("content", "{}"))
            )
        return _deduplicate_suggestions(suggestions)
