from __future__ import annotations

import json
import math
import re
from typing import Any

from clipauto.models import Topic, TranscriptSegment


class TopicValidationError(ValueError):
    pass


_LEADING_SECTION_TITLES = {
    "channel intro",
    "intro",
    "introduction",
    "opening",
    "video intro",
}
_TRAILING_SECTION_TITLES = {
    "call to action",
    "outro",
    "conclusion",
    "end screen",
    "ending",
    "closing",
    "subscribe",
    "thanks for watching",
}
_SPONSOR_PREFIX = re.compile(
    r"^(?:(?:to\s+)?sponsor(?:ed|ship)?\b|advertisement\b|ad\s+(?:break|read)\b|"
    r"commercial\s+break\b|paid\s+promotion\b|partner\s+message\b|"
    r"a\s+word\s+from\s+(?:our|the)\s+sponsor\b|this\s+video\s+is\s+sponsored\s+by\b)"
)
_PART_SUFFIX = re.compile(r"\s*\(part \d+/\d+\)$", re.IGNORECASE)


def _normalized_section_title(title: str) -> str:
    return _PART_SUFFIX.sub("", title.casefold()).strip(" <>.:_-")


def _is_sponsor_only_title(title: str) -> bool:
    if re.search(r"\s+\+\s+", title):
        return False
    return _SPONSOR_PREFIX.match(_normalized_section_title(title)) is not None


def _is_leading_junk(topic: Topic, maximum_descriptive_duration: float) -> bool:
    normalized = _normalized_section_title(topic.title)
    if normalized in _LEADING_SECTION_TITLES:
        return True
    duration = topic.end - topic.start
    return duration <= maximum_descriptive_duration + 0.01 and any(
        normalized.startswith(f"{prefix} ")
        for prefix in _LEADING_SECTION_TITLES
    )


def _is_trailing_junk(topic: Topic, maximum_descriptive_duration: float) -> bool:
    normalized = _normalized_section_title(topic.title)
    if normalized in _TRAILING_SECTION_TITLES:
        return True
    duration = topic.end - topic.start
    return duration <= maximum_descriptive_duration + 0.01 and any(
        normalized.startswith(f"{prefix} ")
        for prefix in _TRAILING_SECTION_TITLES
    )


def extract_json_array(text: str) -> list[dict[str, Any]]:
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL | re.IGNORECASE)
    candidates = (
        [fenced.group(1)]
        if fenced
        else [text[index:] for index, char in enumerate(text) if char in "[{"]
    )
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            value, _ = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("topics", "segments", "clips"):
                nested = value.get(key)
                if isinstance(nested, list):
                    return nested
            if {"title", "start", "end"}.issubset(value):
                return [value]
    raise TopicValidationError("Ollama output did not contain a valid JSON array of topics")


def normalize_topics(
    raw: list[dict[str, Any]], segments: list[TranscriptSegment], duration: float
) -> list[Topic]:
    if not raw or not math.isfinite(duration) or duration <= 0:
        raise TopicValidationError("At least one topic and a positive duration are required")
    parsed: list[Topic] = []
    for item in raw:
        try:
            title = str(item["title"]).strip()
            start = float(item["start"])
            end = float(item["end"])
        except (KeyError, TypeError, ValueError):
            continue
        if (
            not title
            or not math.isfinite(start)
            or not math.isfinite(end)
            or start < 0
            or start >= duration
            or end <= start
        ):
            continue
        parsed.append(Topic(title, start, min(end, duration)))
    parsed.sort(key=lambda topic: topic.start)
    parsed = [
        topic
        for index, topic in enumerate(parsed)
        if index == 0 or not math.isclose(topic.start, parsed[index - 1].start, abs_tol=0.01)
    ]
    if not parsed:
        raise TopicValidationError("Ollama returned no usable topic ranges")
    if len(parsed) == 1:
        return [Topic(parsed[0].title, 0.0, duration)]

    sentence_boundaries = sorted(
        {segment.start for segment in segments if 0 < segment.start < duration}
    )
    boundaries = [0.0]
    for index, (previous, current) in enumerate(zip(parsed, parsed[1:], strict=False)):
        proposed = (previous.end + current.start) / 2
        available = [value for value in sentence_boundaries if boundaries[-1] < value < duration]
        remaining = len(parsed) - index - 2
        if available:
            reservable = available[: len(available) - remaining] if remaining else available
            boundary = min(reservable, key=lambda value: abs(value - proposed))
        else:
            room = max(0.001, (duration - boundaries[-1]) / (remaining + 2))
            boundary = min(duration - room * (remaining + 1), max(boundaries[-1] + room, proposed))
        boundaries.append(boundary)
    boundaries.append(duration)
    return [
        Topic(topic.title, boundaries[index], boundaries[index + 1])
        for index, topic in enumerate(parsed)
    ]


def format_timestamped_transcript(segments: list[TranscriptSegment]) -> str:
    return "\n".join(
        f"[{segment.start:.2f}-{segment.end:.2f}] {segment.text.strip()}" for segment in segments
    )


def topics_from_transcript(
    segments: list[TranscriptSegment], duration: float
) -> list[Topic]:
    if not segments or not math.isfinite(duration) or duration <= 0:
        raise TopicValidationError("A transcript and positive duration are required for fallback")

    part_count = max(1, math.ceil(duration / 66.0))
    candidates = sorted(
        {
            value
            for segment in segments
            for value in (segment.start, segment.end)
            if math.isfinite(value) and 0 < value < duration
        }
    )
    boundaries = [0.0]
    for part in range(1, part_count):
        target = duration * part / part_count
        available = [value for value in candidates if value > boundaries[-1]]
        remaining = part_count - part - 1
        reservable = available[: len(available) - remaining] if remaining else available
        boundary = min(reservable, key=lambda value: abs(value - target)) if reservable else target
        boundaries.append(boundary)
    boundaries.append(duration)

    def title_at(start: float, index: int) -> str:
        segment = next(
            (item for item in segments if item.end > start and item.text.strip()),
            None,
        )
        if segment is None:
            return f"Topic {index + 1}"
        words = re.findall(r"[\w'’-]+", segment.text, re.UNICODE)[:8]
        return " ".join(words).strip() or f"Topic {index + 1}"

    return [
        Topic(title_at(boundaries[index], index), boundaries[index], boundaries[index + 1])
        for index in range(part_count)
    ]


def topics_from_chapters(chapters: list[dict[str, Any]], duration: float) -> list[Topic] | None:
    if not chapters or not math.isfinite(duration) or duration <= 0:
        return None
    parsed: list[tuple[str, float]] = []
    for chapter in chapters:
        title = chapter.get("title")
        start_value = chapter.get("start_time")
        if not isinstance(title, str) or not title.strip() or isinstance(start_value, bool):
            return None
        try:
            start = float(start_value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(start) or start < 0 or start >= duration:
            return None
        parsed.append((title.strip(), start))
    starts = [start for _, start in parsed]
    if any(current <= previous for previous, current in zip(starts, starts[1:], strict=False)):
        return None
    starts[0] = 0.0
    boundaries = [*starts, duration]
    return [
        Topic(title, boundaries[index], boundaries[index + 1])
        for index, (title, _) in enumerate(parsed)
    ]


def _duration_penalty(duration: float, minimum: float, maximum: float) -> float:
    if duration < minimum:
        return (minimum - duration) ** 2
    if duration > maximum:
        return 4 * (duration - maximum) ** 2
    return 0.0


def split_oversized_topics(
    topics: list[Topic],
    segments: list[TranscriptSegment],
    minimum: float = 44.0,
    maximum: float = 66.0,
) -> list[Topic]:
    if minimum <= 0 or maximum < minimum:
        raise ValueError("Output duration range must be positive and increasing")

    transcript_boundaries = {
        boundary
        for segment in segments
        for boundary in (segment.start, segment.end)
        if math.isfinite(boundary)
    }
    word_boundaries = sorted(
        {
            boundary
            for segment in segments
            for word in segment.words
            for boundary in (word.start, word.end)
            if math.isfinite(boundary)
        }
    )
    result: list[Topic] = []
    for topic in topics:
        duration = topic.end - topic.start
        if duration <= maximum:
            result.append(topic)
            continue

        minimum_parts = math.ceil(duration / maximum)
        maximum_parts = math.floor(duration / minimum)
        if minimum_parts > maximum_parts:
            result.append(topic)
            continue
        part_count = minimum_parts
        target = duration / part_count
        ideal_boundaries = {
            topic.start + target * index for index in range(1, part_count)
        }
        internal_segments = {
            boundary
            for boundary in transcript_boundaries
            if topic.start < boundary < topic.end
        }
        internal_words = [
            boundary for boundary in word_boundaries if topic.start < boundary < topic.end
        ]
        nearest_words = (
            {
                min(internal_words, key=lambda boundary: abs(boundary - ideal))
                for ideal in ideal_boundaries
            }
            if internal_words
            else set()
        )
        candidates = [
            topic.start,
            *sorted(internal_segments | nearest_words | ideal_boundaries),
            topic.end,
        ]
        states: dict[int, tuple[tuple[int, float], list[float]]] = {
            0: ((0, 0.0), [topic.start])
        }
        for part_index in range(1, part_count + 1):
            endpoints = (
                [len(candidates) - 1]
                if part_index == part_count
                else range(1, len(candidates) - 1)
            )
            next_states: dict[int, tuple[tuple[int, float], list[float]]] = {}
            for endpoint in endpoints:
                for previous, (cost, path) in states.items():
                    if endpoint <= previous:
                        continue
                    part_duration = candidates[endpoint] - candidates[previous]
                    if part_duration < minimum - 0.01 or part_duration > maximum + 0.01:
                        continue
                    endpoint_value = candidates[endpoint]
                    if endpoint_value in internal_segments:
                        boundary_cost = 0
                    elif endpoint_value in nearest_words:
                        boundary_cost = 1
                    else:
                        boundary_cost = 2
                    candidate = (
                        (
                            cost[0] + boundary_cost,
                            cost[1] + (part_duration - target) ** 2,
                        ),
                        [*path, candidates[endpoint]],
                    )
                    current = next_states.get(endpoint)
                    if current is None or candidate[0] < current[0]:
                        next_states[endpoint] = candidate
            states = next_states
        boundaries = states.get(len(candidates) - 1, ((0, 0.0), []))[1]
        if not boundaries:
            boundaries = [
                topic.start + duration * index / part_count
                for index in range(part_count + 1)
            ]

        total_parts = len(boundaries) - 1
        result.extend(
            Topic(
                f"{topic.title} (Part {index + 1}/{total_parts})",
                boundaries[index],
                boundaries[index + 1],
            )
            for index in range(total_parts)
        )
    return result


def _partition_short_run(
    topics: list[Topic], minimum: float, maximum: float, max_topics: int | None = None
) -> list[list[Topic]]:
    count = len(topics)
    topic_limit = max_topics if max_topics is not None else count
    durations = [topic.end - topic.start for topic in topics]
    prefix = [0.0]
    for duration in durations:
        prefix.append(prefix[-1] + duration)

    best: list[tuple[float, int, list[list[Topic]]] | None] = [None] * (count + 1)
    best[count] = (0.0, 0, [])
    for start in range(count - 1, -1, -1):
        for end in range(start + 1, min(count, start + topic_limit) + 1):
            remainder = best[end]
            if remainder is None:
                continue
            duration = prefix[end] - prefix[start]
            candidate = (
                _duration_penalty(duration, minimum, maximum) + remainder[0],
                1 + remainder[1],
                [topics[start:end], *remainder[2]],
            )
            current = best[start]
            if current is None or candidate[:2] < current[:2]:
                best[start] = candidate
    return best[0][2] if best[0] is not None else []


def partition_topic_groups(
    topics: list[Topic], minimum: float = 44.0, maximum: float = 66.0
) -> list[list[Topic]]:
    if minimum <= 0 or maximum < minimum:
        raise ValueError("Output duration range must be positive and increasing")

    groups: list[list[Topic]] = []
    eligible_run: list[Topic] = []

    def flush() -> None:
        groups.extend(_partition_short_run(eligible_run, minimum, maximum))
        eligible_run.clear()

    for topic in topics:
        if topic.end - topic.start > maximum:
            flush()
            groups.append([topic])
        else:
            eligible_run.append(topic)
    flush()
    return groups


def combine_topics_for_output(
    topics: list[Topic], minimum: float = 44.0, maximum: float = 66.0
) -> list[Topic]:
    return [
        Topic(" + ".join(topic.title for topic in group), group[0].start, group[-1].end)
        for group in partition_topic_groups(topics, minimum, maximum)
    ]


def plan_reel_topics(
    topics: list[Topic],
    segments: list[TranscriptSegment],
    minimum: float = 44.0,
    maximum: float = 66.0,
) -> list[Topic]:
    if not topics:
        raise TopicValidationError("At least one topic is required to plan reels")
    if minimum <= 0 or maximum < minimum:
        raise ValueError("Output duration range must be positive and increasing")

    ordered = sorted(topics, key=lambda topic: topic.start)
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if not math.isclose(previous.end, current.start, abs_tol=0.01):
            raise TopicValidationError("Topics must cover the source without gaps or overlap")

    editorial = [topic for topic in ordered if not _is_sponsor_only_title(topic.title)]
    descriptive_junk_maximum = 10.0
    while editorial and _is_leading_junk(editorial[0], descriptive_junk_maximum):
        editorial.pop(0)
    while editorial and _is_trailing_junk(editorial[-1], descriptive_junk_maximum):
        editorial.pop()
    if not editorial:
        raise TopicValidationError("Source contains no editorial content after cleanup")

    runs: list[list[Topic]] = []
    for topic in editorial:
        if not runs or not math.isclose(runs[-1][-1].end, topic.start, abs_tol=0.01):
            runs.append([])
        runs[-1].append(topic)

    planned: list[Topic] = []
    for run in runs:
        split = split_oversized_topics(run, segments, minimum, maximum)
        planned.extend(combine_topics_for_output(split, minimum, maximum))
    return planned
