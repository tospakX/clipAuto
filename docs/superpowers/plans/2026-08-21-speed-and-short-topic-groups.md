# Speed and Short-Topic Groups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce end-to-end processing time, merge excessive consecutive short topics in exact groups of three, and keep the large-batch UI responsive.

**Architecture:** Topic grouping is a deterministic post-processing step after chapter/Ollama normalization and before rendering, so complete topic boundaries remain intact. Rendering keeps the current one-output-per-result contract but builds the blurred layer at 270×480 and upscales it, then uses x264 `veryfast`. The frontend defers creation of preview video elements until a completed job is expanded.

**Tech Stack:** Python 3.12, FastAPI, faster-whisper, FFmpeg/libx264, vanilla JavaScript/CSS, pytest, Playwright.

**Spec:** `docs/specs/2026-08-21-speed-and-short-topic-groups.md`

## Global Constraints

- Keep complete topics; never cut a topic to meet a duration.
- Merge only complete groups of three consecutive topics where each duration is at most 20 seconds.
- Preserve 1080×1920 H.264/AAC MP4 output and synchronized subtitles.
- Keep one queue worker by default and do not interrupt the currently running application.
- Do not load full videos into RAM.

---

### Task 1: Deterministic short-topic grouping

**Files:**
- Modify: `clipauto/topics.py`
- Modify: `clipauto/pipeline.py`
- Test: `tests/test_topics.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: normalized `list[Topic]` with ordered, contiguous boundaries.
- Produces: `combine_short_topic_groups(topics: list[Topic], max_duration: float = 20.0, group_size: int = 3) -> list[Topic]`.

- [ ] Write tests proving three consecutive short topics merge, one/two remainders stay separate, long topics break runs, titles remain specific, and pipeline planned/output clips use grouped topics.
- [ ] Run focused tests and confirm failures because `combine_short_topic_groups` is absent and pipeline still renders every topic.
- [ ] Implement a single-pass grouping function. For each complete group, return `Topic("Title 1 + Title 2 + Title 3", first.start, third.end)`; emit remainders unchanged.
- [ ] Call grouping after chapter/Ollama normalization and before `planned_clips` and rendering.
- [ ] Run topic and pipeline tests.

### Task 2: Measured rendering acceleration

**Files:**
- Modify: `clipauto/renderer.py`
- Test: `tests/test_renderer.py`

**Interfaces:**
- Consumes: existing `build_ffmpeg_command(...)` inputs.
- Produces: the same command contract and delivery codecs with a cheaper filter graph and `veryfast` x264 preset.

- [ ] Add a failing command-contract test for a 270×480 blurred background upscaled to 1080×1920 and `-preset veryfast`.
- [ ] Confirm the test fails against the current full-resolution blur and `medium` preset.
- [ ] Change only the background branch to `scale=270:480...crop=270:480,gblur=sigma=8,scale=1080:1920:flags=bilinear`; keep the foreground and subtitles at delivery resolution.
- [ ] Switch x264 from `medium` to `veryfast`, retaining CRF 20, yuv420p, AAC, and faststart.
- [ ] Run renderer tests and an actual short FFmpeg render; validate with ffprobe.

### Task 3: Faster timestamped transcription

**Files:**
- Modify: `clipauto/transcriber.py`
- Test: `tests/test_transcriber.py`

**Interfaces:**
- Consumes: faster-whisper `WhisperModel.transcribe`.
- Produces: the existing `TranscriptionResult` with segment and word timestamps.

- [ ] Extend the fake-model test to require `beam_size=1`, `vad_filter=True`, and `word_timestamps=True` while retaining GPU then CPU fallback coverage.
- [ ] Confirm failure because the current code uses beam size 5.
- [ ] Set greedy beam size 1. Keep VAD, word timestamps, prior-text conditioning, cancellation behavior, and device fallback unchanged.
- [ ] Run transcriber and pipeline tests.

### Task 4: Large-batch UI virtualization and clearer status

**Files:**
- Modify: `clipauto/static/index.html`
- Modify: `clipauto/static/app.js`
- Modify: `clipauto/static/app.css`
- Modify: `scripts/browser_smoke.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Consumes: unchanged batch/job API JSON.
- Produces: one `.clips-toggle` per job and lazily populated `.clips` containers.

- [ ] Add a failing HTML contract test for a clip toggle in the job template.
- [ ] Add the toggle control, hidden when no clips exist.
- [ ] Store the latest job data on its card; collapsed completed cards show `Show N clips`, create no video elements, and expanded cards show `Hide clips` and render previews.
- [ ] Increase active polling from 1.2 to 2 seconds to reduce serialization/DOM churn without faking progress.
- [ ] Tighten card spacing and give completed jobs a compact summary row while retaining accessible focus and mobile layout.
- [ ] Update Playwright smoke coverage to expand one job, verify previews are lazy, and exercise export/removal/history actions without console errors.

### Task 5: Documentation and final verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Documents: grouping threshold, renderer tradeoff, lazy previews, restart requirement.

- [ ] Update README with the exact grouping rule and performance behavior.
- [ ] Run `uv run ruff format --check .`, `uv run ruff check .`, `uv run pytest`, `uv run python -m compileall -q clipauto tests`, `node --check clipauto/static/app.js`, and `git diff --check`.
- [ ] Run isolated Playwright smoke coverage and inspect desktop/mobile screenshots.
- [ ] Confirm the live queue was not restarted or mutated and tell the user changes require a manual restart after current processing.
