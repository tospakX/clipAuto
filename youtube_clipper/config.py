"""Central defaults and tuning knobs for the clipping pipeline.

Keep product-level settings here so upgrades do not require hunting through processing
modules. CLI flags may override user-facing defaults at runtime.
"""

from pathlib import Path

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_TIMEOUT = 300.0
DEFAULT_WHISPER_MODEL = "small"
DEFAULT_WHISPER_DEVICE = "auto"
DEFAULT_WHISPER_COMPUTE_TYPE = "default"
DEFAULT_OUTPUT_DIR = Path("output")
DEFAULT_WORK_DIR = Path(".clipper-work")

ALLOWED_SPEEDS = (0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0)
SCENE_DETECTION_THRESHOLD = 27.0
MIN_CLIP_DURATION = 8.0
BOUNDARY_MATCH_TOLERANCE = 4.0
MAX_TRANSCRIPT_CHARACTERS = 80_000
WHISPER_MODEL_DOWNLOAD_MB = {
    "tiny": 75,
    "base": 145,
    "small": 466,
    "medium": 1_500,
    "large-v3": 3_100,
}

OUTPUT_WIDTH = 1080
OUTPUT_HEIGHT = 1920
OUTPUT_VIDEO_CODEC = "libx264"
OUTPUT_AUDIO_CODEC = "aac"
OUTPUT_AUDIO_BITRATE = "192k"
OUTPUT_CRF = 20
