from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from clipauto.models import TranscriptSegment, TranscriptWord
from clipauto.transcriber import TranscriptionResult

_CACHE_VERSION = 1


def _finite_number(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("timestamp must be finite")
    return number


def save_transcript(path: Path, source: Path, result: TranscriptionResult) -> None:
    source_stat = source.stat()
    payload = {
        "version": _CACHE_VERSION,
        "source": {"name": source.name, "size": source_stat.st_size},
        "transcription": {
            "duration": result.duration,
            "language": result.language,
            "device": result.device,
            "segments": [
                {
                    "start": segment.start,
                    "end": segment.end,
                    "text": segment.text,
                    "words": [
                        {"start": word.start, "end": word.end, "text": word.text}
                        for word in segment.words
                    ],
                }
                for segment in result.segments
            ],
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def load_transcript(path: Path, source: Path) -> TranscriptionResult | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        source_stat = source.stat()
        identity = payload["source"]
        if (
            payload["version"] != _CACHE_VERSION
            or identity["name"] != source.name
            or int(identity["size"]) != source_stat.st_size
        ):
            return None
        raw = payload["transcription"]
        duration = _finite_number(raw["duration"])
        if (
            duration <= 0
            or not isinstance(raw["language"], str)
            or not isinstance(raw["device"], str)
        ):
            return None
        segments = []
        for item in raw["segments"]:
            start = _finite_number(item["start"])
            end = _finite_number(item["end"])
            text = item["text"]
            if start < 0 or end <= start or not isinstance(text, str):
                return None
            words = []
            for word in item.get("words", []):
                word_start = _finite_number(word["start"])
                word_end = _finite_number(word["end"])
                word_text = word["text"]
                if word_start < 0 or word_end <= word_start or not isinstance(word_text, str):
                    return None
                words.append(TranscriptWord(word_start, word_end, word_text))
            segments.append(TranscriptSegment(start, end, text, words))
        if not segments:
            return None
        return TranscriptionResult(
            segments,
            duration,
            raw["language"],
            raw["device"],
        )
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None
