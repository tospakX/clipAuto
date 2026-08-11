"""Local YouTube topic clipper."""

import os

# Hugging Face's optional Xet transport can stall indefinitely on unstable connections. The
# standard HTTP downloader supports resume and is more predictable for one-time Whisper models.
# Respect an explicit user override while selecting the stable default before Hub is imported.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DOWNLOAD_TIMEOUT", "60")

__version__ = "0.1.0"
