from pathlib import Path

from clipauto.models import TranscriptSegment, TranscriptWord
from clipauto.transcriber import TranscriptionResult
from clipauto.transcript_cache import load_transcript, save_transcript


def sample_result() -> TranscriptionResult:
    return TranscriptionResult(
        [
            TranscriptSegment(
                1.25,
                3.5,
                "A complete sentence.",
                [TranscriptWord(1.25, 1.7, "A"), TranscriptWord(1.7, 3.5, "sentence")],
            )
        ],
        4.0,
        "en",
        "cuda",
    )


def test_transcript_cache_round_trips_complete_timestamp_data(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video bytes")
    cache = tmp_path / "transcript.json"

    save_transcript(cache, source, sample_result())
    loaded = load_transcript(cache, source)

    assert loaded == sample_result()


def test_transcript_cache_rejects_a_different_source(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"first")
    cache = tmp_path / "transcript.json"
    save_transcript(cache, source, sample_result())
    source.write_bytes(b"replacement with another size")

    assert load_transcript(cache, source) is None


def test_transcript_cache_ignores_malformed_json(tmp_path: Path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"video")
    cache = tmp_path / "transcript.json"
    cache.write_text("not json", encoding="utf-8")

    assert load_transcript(cache, source) is None
