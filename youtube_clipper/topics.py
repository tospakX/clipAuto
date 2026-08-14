"""Derive concise, deterministic topic labels for exported clips."""

from __future__ import annotations

from .naming import safe_component
from .types import BoundarySuggestion, TranscriptSegment, VideoTimestamp

_MATCH_TOLERANCE = 4.0


def _nearby_label(
    start: float,
    timestamps: tuple[VideoTimestamp, ...],
    suggestions: list[BoundarySuggestion],
    segments: list[TranscriptSegment],
) -> str:
    creator = [item for item in timestamps if abs(item.timestamp - start) <= _MATCH_TOLERANCE]
    if creator:
        return min(creator, key=lambda item: (-item.confidence, abs(item.timestamp - start))).title

    semantic = [
        item
        for item in suggestions
        if item.reason.strip() and abs(item.timestamp - start) <= _MATCH_TOLERANCE
    ]
    if semantic:
        return min(
            semantic, key=lambda item: (-item.confidence, abs(item.timestamp - start))
        ).reason

    transcript = [
        item
        for item in segments
        if item.text.strip() and abs(item.start - start) <= _MATCH_TOLERANCE
    ]
    if transcript:
        text = min(transcript, key=lambda item: abs(item.start - start)).text
        return " ".join(text.split()[:8])
    return ""


def topic_names(
    starts: list[float],
    timestamps: tuple[VideoTimestamp, ...],
    suggestions: list[BoundarySuggestion],
    segments: list[TranscriptSegment],
) -> list[str]:
    """Return one unique, filesystem-safe topic name for each clip start."""
    names: list[str] = []
    counts: dict[str, int] = {}
    for index, start in enumerate(starts, start=1):
        fallback = f"topic-{index:02d}"
        base = safe_component(
            _nearby_label(start, timestamps, suggestions, segments), fallback, max_length=64
        )
        count = counts.get(base, 0) + 1
        counts[base] = count
        if count == 1:
            names.append(base)
            continue
        suffix = f"-{count}"
        names.append(f"{base[: 64 - len(suffix)].rstrip(' ._-')}{suffix}")
    return names
