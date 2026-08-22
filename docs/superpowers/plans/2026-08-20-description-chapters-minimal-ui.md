# Description Chapters and Minimal UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prefer validated YouTube description timestamps for clip boundaries and replace the oversized frontend with a compact processing workspace.

**Architecture:** yt-dlp emits its parsed `chapters` field alongside the downloaded path, title, and duration. The pipeline converts valid chapters to complete contiguous topics and bypasses Ollama only when those chapters are usable; transcription still runs for subtitles. The existing API remains stable while the HTML/CSS presentation is reduced to one compact input surface and a dense queue.

**Tech Stack:** Python 3.12, yt-dlp, FastAPI, vanilla HTML/CSS/JavaScript, pytest, Playwright.

**Spec:** `docs/spec.md`

## Global Constraints

- Description timestamps extracted by yt-dlp are authoritative when valid.
- Ollama remains the fallback when timestamps are absent or malformed.
- Timestamp clips cover the complete video in order with no gaps or overlaps.
- Transcription still runs before rendering so every clip has subtitles.
- Existing batch queue, progress, cancellation, preview, download, and ZIP contracts remain intact.
- The frontend must be compact, responsive, keyboard accessible, and free of ornamental sections.

---

### Task 1: yt-dlp chapter metadata and validation

**Files:** Modify `clipauto/downloader.py`, `clipauto/topics.py`, `tests/test_downloader.py`, `tests/test_topics.py`.

**Interfaces:** `DownloadResult.chapters: list[dict]`; `topics_from_chapters(chapters, duration) -> list[Topic] | None`.

- [ ] Add a failing downloader test proving the command requests `%(chapters)j` and a parsing test using literal yt-dlp chapter JSON.
- [ ] Add failing topic tests proving chapter starts become exact contiguous clip boundaries, malformed chapters return no usable result, and the first/last topics cover `0..duration`.
- [ ] Run the focused tests and confirm failures identify the missing chapter contracts.
- [ ] Parse the yt-dlp JSON field without loading video media, validate finite ordered starts/titles, and construct complete topic ranges.
- [ ] Re-run the focused tests until green.

### Task 2: Chapter-first pipeline selection

**Files:** Modify `clipauto/pipeline.py`, `tests/test_pipeline.py`.

**Interfaces:** Pipeline consumes `DownloadResult.chapters`; Ollama segmentation runs only when `topics_from_chapters` returns `None`.

- [ ] Add a failing pipeline test with description chapters and a segmenter that raises if called; assert clip titles and exact boundaries come from chapters.
- [ ] Run the test and confirm the current unconditional Ollama call fails it.
- [ ] Select validated chapters after transcription, otherwise retain the existing Ollama validation flow.
- [ ] Re-run all pipeline tests, including the Ollama fallback case.

### Task 3: Compact workspace UI and end-to-end checks

**Files:** Modify `clipauto/static/index.html`, `clipauto/static/app.css`, `clipauto/static/app.js`, `scripts/browser_smoke.py`, `README.md`; test `tests/test_ui.py`.

**Interfaces:** Existing DOM IDs and API routes remain stable; browser users receive the same workflow with less visual and textual overhead.

- [ ] Extend the browser contract to require the primary URL workspace and queue while remaining usable at 390px and 1440px.
- [ ] Remove the hero, technology footer, decorative step labels, oversized typography, and excess spacing; keep a quiet graphite/paper/coral palette, compact utility type, and the queue playhead as the one signature detail.
- [ ] Update copy to state that description timestamps are preferred and Ollama fills the gap.
- [ ] Run Playwright against populated desktop/mobile states, inspect screenshots, and correct overflow, focus, empty, active, failed, and completed presentation issues.
- [ ] Run the full pytest suite, Ruff, compileall, a live yt-dlp chapter metadata probe, and the existing synthetic/live media checks affected by the change.
