from __future__ import annotations

import logging
import re

from .config import BOUNDARY_MATCH_TOLERANCE, MIN_CLIP_DURATION
from .types import BoundarySuggestion, TranscriptSegment, VideoTimestamp

LOGGER = logging.getLogger(__name__)

_NUMBER = r"(?:\d{1,2}|one|two|three|four|five|six|seven|eight|nine|ten)"
_MARKERS = re.compile(
    rf"(?:^|[.!?]\s+)(?:number\s+)?{_NUMBER}\s*[.):,\-]?(?:\s+|$)|"
    r"\b(?:next|another)\s+(?:topic|point|tip|step|item)\b|"
    r"\b(?:moving|move)\s+on\s+to\b",
    re.IGNORECASE,
)
_MARKER_HEAD = re.compile(
    rf"(?:number\s+)?{_NUMBER}|"
    r"(?:next|another)\s+(?:topic|point|tip|step|item)|"
    r"(?:moving|move)\s+on\s+to",
    re.IGNORECASE,
)


def _find_marker_events(segments: list[TranscriptSegment]) -> list[tuple[float, str]]:
    events: list[tuple[float, str]] = []
    for segment in segments:
        joined_words = "".join(word.text for word in segment.words)
        source_text = joined_words if joined_words else segment.text
        leading_space = len(source_text) - len(source_text.lstrip())
        text = source_text.strip()
        if not text:
            continue
        span = max(0.0, segment.end - segment.start)
        for match in _MARKERS.finditer(text):
            head = _MARKER_HEAD.search(match.group())
            marker_start = match.start() + (head.start() if head else 0) + leading_space
            if segment.words:
                offset = 0
                timestamp = segment.start
                for word in segment.words:
                    next_offset = offset + len(word.text)
                    if next_offset > marker_start:
                        timestamp = word.start
                        break
                    offset = next_offset
            else:
                # Older/synthetic segments may not have word timing metadata.
                fraction = match.start() / max(1, len(text))
                timestamp = segment.start + span * fraction
            events.append(
                (round(timestamp, 3), head.group().lower() if head else match.group().lower())
            )
    return events


def find_marker_times(segments: list[TranscriptSegment]) -> list[float]:
    return [timestamp for timestamp, _label in _find_marker_events(segments)]


def _near(timestamp: float, values: list[float], tolerance: float) -> bool:
    return any(abs(timestamp - value) <= tolerance for value in values)


def fuse_boundaries(
    segments: list[TranscriptSegment],
    scene_times: list[float],
    llm_suggestions: list[BoundarySuggestion],
    duration: float,
    min_clip_duration: float = MIN_CLIP_DURATION,
    tolerance: float = BOUNDARY_MATCH_TOLERANCE,
    video_timestamps: tuple[VideoTimestamp, ...] = (),
) -> list[float]:
    """Fuse transcript, description, semantic, and visual evidence into clip start times."""
    marker_events = _find_marker_events(segments)
    marker_times = [timestamp for timestamp, _label in marker_events]
    description_times = [item.timestamp for item in video_timestamps]
    reliable_topic_map = [item for item in video_timestamps if item.confidence >= 0.8]
    has_creator_topic_map = (
        len(reliable_topic_map) >= 2
        and min(item.timestamp for item in reliable_topic_map) <= tolerance
    )
    proposals: list[tuple[float, float, str]] = []
    for timestamp in marker_times:
        score = 0.68 + (0.16 if _near(timestamp, scene_times, tolerance) else 0.0)
        matching_llm = [s for s in llm_suggestions if abs(s.timestamp - timestamp) <= tolerance]
        if matching_llm:
            score += 0.20 * max(s.confidence for s in matching_llm)
        proposals.append((timestamp, score, "spoken marker"))
    for suggestion in llm_suggestions:
        near_scene = _near(suggestion.timestamp, scene_times, tolerance)
        near_marker = _near(suggestion.timestamp, marker_times, tolerance)
        near_description = _near(suggestion.timestamp, description_times, tolerance)
        if has_creator_topic_map and not near_description and not near_marker:
            LOGGER.info(
                "Ignoring Ollama boundary at %.2fs inside the creator's topic map",
                suggestion.timestamp,
            )
            continue
        if not (near_scene or near_marker or near_description):
            LOGGER.info("Ignoring unsupported Ollama-only boundary at %.2fs", suggestion.timestamp)
            continue
        score = 0.45 + 0.20 * suggestion.confidence
        if near_scene:
            score += 0.10
        if near_marker:
            score += 0.12
        if near_description:
            score += 0.18
        proposals.append((suggestion.timestamp, score, "Ollama suggestion"))
    for video_timestamp in video_timestamps:
        timestamp = video_timestamp.timestamp
        score = 0.45 + 0.35 * video_timestamp.confidence
        if _near(timestamp, scene_times, tolerance):
            score += 0.10
        if _near(timestamp, marker_times, tolerance):
            score += 0.12
        matching_llm = [s for s in llm_suggestions if abs(s.timestamp - timestamp) <= tolerance]
        if matching_llm:
            score += 0.15 * max(s.confidence for s in matching_llm)
        proposals.append((timestamp, score, "creator timestamp"))

    # If the speaker explicitly introduces point one after a preamble, start the first
    # deliverable at point one instead of exporting the preamble as an extra "topic".
    first_topic_start = 0.0
    if marker_events:
        timestamp, label = marker_events[0]
        if timestamp <= duration - min_clip_duration and re.fullmatch(
            r"(?:number\s+)?(?:1|one)", label.strip(), re.IGNORECASE
        ):
            first_topic_start = timestamp
    accepted: list[float] = [first_topic_start]
    for timestamp, score, source in sorted(proposals, key=lambda value: value[0]):
        if score < 0.65:
            continue
        if timestamp < min_clip_duration or timestamp > duration - min_clip_duration:
            continue
        if timestamp - accepted[-1] < min_clip_duration:
            continue
        # Snap semantic estimates to a nearby explicit spoken marker, then scene cut.
        nearby_markers = [v for v in marker_times if abs(v - timestamp) <= tolerance]
        chosen = (
            min(nearby_markers, key=lambda v: abs(v - timestamp)) if nearby_markers else timestamp
        )
        nearby_scenes = [v for v in scene_times if abs(v - chosen) <= tolerance]
        if nearby_scenes:
            chosen = min(nearby_scenes, key=lambda v: abs(v - chosen))
        if chosen - accepted[-1] >= min_clip_duration:
            accepted.append(round(chosen, 3))
            LOGGER.info("Accepted %s boundary at %.2fs (score %.2f)", source, chosen, score)

    if len(accepted) > 1 and duration - accepted[-1] < min_clip_duration:
        accepted.pop()
    return accepted
