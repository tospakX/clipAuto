# Local YouTube Topic Clipper

A local-only CLI that downloads a multi-topic YouTube video, transcribes it, detects visual
transitions, asks an installed Ollama model to reason about topic changes, fuses those signals,
and exports one 9:16 MP4 per topic. It uses no cloud AI or paid API.

## Project status

Version `0.1.0` is a working alpha with a stable modular pipeline. Processing defaults are kept
in `youtube_clipper/config.py`, and each stage can be upgraded independently. See the
[architecture guide](docs/architecture.md) before extending the pipeline and
[CONTRIBUTING.md](CONTRIBUTING.md) for development and release checks.

## Requirements

- Python 3.10–3.13 (3.11 or 3.12 recommended)
- `yt-dlp`, `ffmpeg`/`ffprobe`, and `ollama` on `PATH`
- A running Ollama server at `http://localhost:11434` with at least one text model installed

Set up an isolated environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
ollama serve  # only if Ollama is not already running
```

Fish shell users can activate with `source .venv/bin/activate.fish`, or skip activation and run
commands directly from `.venv/bin/`.

Check everything before processing a video:

```bash
youtube-clipper --check
```

## Graphical interface

The easiest way to use the project is the local graphical interface:

```text
.venv/bin/youtube-clipper --ui
```

Your browser opens automatically. Paste a YouTube URL, choose playback speed and transcription
quality, then select **Create clips**. The page shows every processing stage and provides
video previews and download buttons when processing finishes. Refreshing the page restores the
current job while the local server is still running.

The interface binds to `127.0.0.1` by default, so it is available only on this computer. Stop it
with `Ctrl+C` in the terminal. If the browser does not open, visit `http://127.0.0.1:8787`.

## Command-line usage

```bash
youtube-clipper "https://www.youtube.com/watch?v=VIDEO_ID"
youtube-clipper "https://www.youtube.com/watch?v=VIDEO_ID" --speed 1.5
```

The result is `output/part_01.mp4`, `output/part_02.mp4`, and so on. Each file uses a 9:16
1080x1920 canvas and keeps the complete source frame centered, adding padding instead of cropping.
Output is H.264 video with AAC audio. Playback speed can be set from 0.50x to 2.00x in 0.25x
steps; FFmpeg preserves audio pitch.

Useful controls:

```bash
youtube-clipper URL --whisper-model medium
youtube-clipper URL --whisper-device cpu --whisper-compute-type int8
youtube-clipper URL --output-dir my-clips --work-dir my-work
```

The default faster-whisper model is `small`; its weights are downloaded once on first use and
then cached locally. The first run shows model-download progress; approximate model downloads are
75 MB (`tiny`), 466 MB (`small`), and 1.5 GB (`medium`). Automatic GPU mode falls back to CPU
`int8` when the required CUDA libraries are unavailable instead of failing after the download.
Ollama models are queried at runtime. The selector favors a capable 7B–14B
text model for a practical quality/speed balance instead of hardcoding a model name.

Completed transcripts and scene detections are cached in `.clipper-work` for the same source video
and Whisper model. Retrying a video reuses that analysis; changing the source or model invalidates
the cache automatically. Long transcripts are processed in overlapping Ollama windows, so middle
topics are not discarded to fit a model prompt.

## How boundaries are chosen

The detector combines four independent signals:

1. Timestamped faster-whisper segments and explicit phrases such as `1`, `number two`, `next
   topic`, and `moving on to`.
2. Creator timestamps and structured chapters from the YouTube description, when available.
3. PySceneDetect content transitions as visual supporting evidence.
4. Local Ollama semantic reasoning about which transcript moments genuinely begin a new topic.

Scene cuts alone never cause a split. Description timestamps are deduplicated against structured
chapters, and isolated time mentions need another supporting signal. A complete creator chapter
map prevents Ollama and ordinary camera cuts from subdividing one named topic without an explicit
spoken marker. Semantic estimates snap to nearby markers and scene cuts, and short edge clips are
suppressed.

## Tests

```bash
python -m unittest discover -v
```

Tests cover marker recognition, multi-signal boundary fusion, dynamic Ollama model choice,
Whisper runtime fallback, AV1 scene compatibility, FFmpeg export arguments, and pipeline-stage
orchestration without downloading a real video.

## Donations

- Bitcoin (BTC): `bc1qrmlkg6r84m83w72c2f5hw3n8j06k7s5phfws67`
- Litecoin (LTC): `La25t2KDaondzHUbrDf64cyQpjZTbo6hyt`

## Development note

Codex was used in a limited supporting role for debugging and frontend work.

## License

No license is granted. The repository has no `LICENSE` file and remains all rights reserved by
default.

For contributor tooling:

```bash
python -m pip install -e '.[dev]'
ruff check .
python -m build
```

GitHub Actions runs unit tests on Python 3.10–3.13 and Ruff on every push and pull request.
