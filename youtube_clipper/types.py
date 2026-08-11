from dataclasses import dataclass


@dataclass(frozen=True)
class TranscriptWord:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranscriptSegment:
    start: float
    end: float
    text: str
    words: tuple[TranscriptWord, ...] = ()


@dataclass(frozen=True)
class BoundarySuggestion:
    timestamp: float
    confidence: float = 0.7
    reason: str = ""


@dataclass(frozen=True)
class VideoTimestamp:
    timestamp: float
    title: str
    confidence: float = 0.8
