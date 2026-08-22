from __future__ import annotations

from pathlib import Path

from clipauto.models import TranscriptSegment

ASS_STYLE_FORMAT = (
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
    "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
    "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"
)
ASS_STYLE = (
    "Style: Default,DejaVu Sans,58,&H00FFFFFF,&H000000FF,&H00101018,&H70000000,"
    "-1,0,0,0,100,100,0,0,1,4,1,2,90,90,180,1"
)
ASS_HEADER = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
{ASS_STYLE_FORMAT}
{ASS_STYLE}

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(seconds: float) -> str:
    centiseconds = max(0, round(seconds * 100))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    secs, cents = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cents:02d}"


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def write_ass(
    path: Path, segments: list[TranscriptSegment], clip_start: float, clip_end: float
) -> Path:
    lines = [ASS_HEADER]
    for segment in segments:
        if segment.end <= clip_start or segment.start >= clip_end:
            continue
        start = max(segment.start, clip_start) - clip_start
        end = min(segment.end, clip_end) - clip_start
        text = _escape(segment.text.strip())
        if text and end > start:
            lines.append(
                f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,{text}\n"
            )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(lines), encoding="utf-8")
    return path
