from pathlib import Path

from clipauto.models import TranscriptSegment
from clipauto.subtitles import write_ass


def test_writes_clip_relative_ass_and_escapes_control_characters(tmp_path: Path):
    segments = [
        TranscriptSegment(8.0, 11.0, "Before"),
        TranscriptSegment(11.0, 14.5, "A {brace}\\path"),
        TranscriptSegment(17.0, 22.0, "Final words"),
        TranscriptSegment(23.0, 25.0, "After"),
    ]

    target = write_ass(tmp_path / "captions.ass", segments, clip_start=10.0, clip_end=23.0)
    content = target.read_text()

    assert "Dialogue: 0,0:00:00.00,0:00:01.00" in content
    assert "Dialogue: 0,0:00:01.00,0:00:04.50" in content
    assert r"A \{brace\}\\path" in content
    assert "Dialogue: 0,0:00:07.00,0:00:12.00" in content
    assert "After" not in content
