# Multi-video Queue Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a reliable sequential multi-YouTube queue with isolated per-video files, descriptive clip names, clear UI states, and failure isolation.

**Architecture:** Keep `run_pipeline` as the single-video processing unit and put sequencing in a thread-safe `JobManager` worker. The downloader creates an ID-scoped work directory; the pipeline derives a safe title-plus-ID output directory and passes deterministic topic filenames to the transactional exporter. The HTTP API exposes queue snapshots and waiting-item deletion, while the browser renders all queue items from those snapshots.

**Tech Stack:** Python 3.10+, standard-library HTTP/threading, vanilla HTML/CSS/JavaScript, yt-dlp, FFmpeg, `unittest`, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-14-multi-video-queue.md`

## Global Constraints

- Process only one heavyweight media pipeline at a time.
- A failed item must not stop later queued items.
- Output and work paths must remain safe on Linux and Windows.
- Preserve existing speed, quality, health, progress, preview, download, and single-video behavior.
- Never commit media, model caches, build products, environments, or secrets.

---

### Task 1: Safe video identity and paths

**Files:**
- Create: `youtube_clipper/naming.py`
- Modify: `youtube_clipper/downloader.py`
- Test: `tests/test_naming.py`
- Test: `tests/test_downloader.py`

**Interfaces:**
- Produces: `safe_component(value: str, fallback: str, max_length: int = 80) -> str`
- Produces: `video_directory_name(title: str, video_id: str) -> str`
- Produces: `DownloadedVideo(path, timestamps, title, video_id)` with `work_dir` available as `path.parent`

- [ ] **Step 1: Write failing tests for unsafe/reserved/duplicate-looking titles**

```python
def test_video_directory_names_are_cross_platform_safe_and_unique():
    first = video_directory_name('CON: a/b?*', 'abc123')
    second = video_directory_name('CON: a/b?*', 'xyz789')
    self.assertRegex(first, r'^[a-z0-9._-]+$')
    self.assertNotEqual(first, second)
```

- [ ] **Step 2: Run `tests.test_naming` and confirm import/behavior failure**
- [ ] **Step 3: Implement bounded Unicode normalization, reserved-name protection, and ID suffixes**
- [ ] **Step 4: Extend downloader tests to require `work/<id>/source.*` plus title/ID metadata**
- [ ] **Step 5: Run downloader/naming tests and confirm pass**

### Task 2: Per-video outputs and topic filenames

**Files:**
- Modify: `youtube_clipper/pipeline.py`
- Modify: `youtube_clipper/exporter.py`
- Create: `youtube_clipper/topics.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_exporter.py`
- Test: `tests/test_topics.py`

**Interfaces:**
- Produces: `topic_names(starts, timestamps, suggestions, segments) -> list[str]`
- Changes: `export_clips(..., clip_names: list[str] | None = None, progress_callback=...)`
- Preserves: `run_pipeline(...) -> list[Path]`

- [ ] **Step 1: Write failing tests for chapter, semantic, transcript, and fallback topic names**
- [ ] **Step 2: Run topic tests and confirm the missing module fails**
- [ ] **Step 3: Implement deterministic topic selection and safe filename components**
- [ ] **Step 4: Write failing exporter tests requiring `01_topic-name.mp4` transactional publication**
- [ ] **Step 5: Implement optional descriptive filenames without weakening validation or cleanup safety**
- [ ] **Step 6: Write failing pipeline test requiring `output/<title>-<id>/clips/` and ID-scoped cache**
- [ ] **Step 7: Wire downloader metadata, topic naming, per-video paths, and exporter together**
- [ ] **Step 8: Run focused pipeline/export/topic tests and confirm pass**

### Task 3: Batch CLI failure isolation

**Files:**
- Modify: `youtube_clipper/cli.py`
- Create: `tests/test_cli.py`

**Interfaces:**
- Changes: positional `url` to `urls`, accepting zero or more values
- Preserves: one URL invokes `run_pipeline` once and exit code `0` on success

- [ ] **Step 1: Write a failing test where success, failure, success URLs all invoke the pipeline**
- [ ] **Step 2: Run CLI tests and confirm only the first/current contract is insufficient**
- [ ] **Step 3: Implement sequential URL processing with per-item logging and aggregate exit status**
- [ ] **Step 4: Run CLI tests and existing pipeline tests**

### Task 4: Thread-safe sequential queue

**Files:**
- Modify: `youtube_clipper/ui_server.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: `JobManager.enqueue(urls, speed, whisper_model) -> QueueSubmission`
- Produces: `JobManager.list() -> list[dict[str, object]]`
- Produces: `JobManager.remove(job_id) -> bool`
- Preserves: `JobManager.start(url, speed, whisper_model)` as a single-item compatibility wrapper

- [ ] **Step 1: Replace the busy-job test with a failing ordered two-item queue test**
- [ ] **Step 2: Add a failing success/failure/success test proving the worker continues**
- [ ] **Step 3: Add failing duplicate and waiting-removal tests**
- [ ] **Step 4: Implement one daemon worker, condition-protected waiting IDs, and atomic snapshots**
- [ ] **Step 5: Map pipeline progress to downloading/analyzing/clipping while keeping bounded events**
- [ ] **Step 6: Run all JobManager tests and inspect for timing/race failures**

### Task 5: Queue HTTP API and browser UI

**Files:**
- Modify: `youtube_clipper/ui_server.py`
- Modify: `youtube_clipper/ui/index.html`
- Modify: `youtube_clipper/ui/app.js`
- Modify: `youtube_clipper/ui/app.css`
- Test: `tests/test_ui.py`

**Interfaces:**
- `POST /api/jobs` consumes `{urls: [...], speed, whisper_model}` and returns queue submission
- `GET /api/jobs` returns the ordered queue snapshot
- `DELETE /api/jobs/<id>` removes a waiting item
- `GET /api/jobs/<id>` and `/clips/<id>/<name>` remain available

- [ ] **Step 1: Write failing HTTP tests for multi-add, list, duplicate reporting, and deletion**
- [ ] **Step 2: Implement API routing and bounded JSON validation**
- [ ] **Step 3: Replace the URL input with a multiline composer and queue-list markup**
- [ ] **Step 4: Rewrite browser state/polling to render all statuses, active progress, grouped results, and removable waiting items**
- [ ] **Step 5: Keep result-card title typography compact and responsive**
- [ ] **Step 6: Run HTTP/UI tests and validate static asset assertions**

### Task 6: Documentation and release hygiene

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `CHANGELOG.md`
- Modify: `.gitignore` if the final artifact scan finds a missing generated path

**Interfaces:**
- Documents UI/CLI queue usage and `output/<safe-title>-<id>/clips/`

- [ ] **Step 1: Update quick start and CLI examples for multiple links**
- [ ] **Step 2: Document queue/failure isolation and per-video workspace ownership**
- [ ] **Step 3: Record user-visible changes under Unreleased**
- [ ] **Step 4: Audit ignored/generated files with `git status --ignored`**

### Task 7: Full verification and GitHub delivery

**Files:**
- Review: all changed files

**Interfaces:**
- Produces: pushed `agent/multi-video-queue` commit and draft PR to `main`

- [ ] **Step 1: Run `.venv/bin/python -m unittest discover -v`**
- [ ] **Step 2: Run `.venv/bin/ruff check .`**
- [ ] **Step 3: Run `.venv/bin/python -m build`**
- [ ] **Step 4: Run focused repeated queue tests to expose timing races**
- [ ] **Step 5: Review `git diff --check`, `git diff`, and `git status --ignored`**
- [ ] **Step 6: Stage only intended source, test, and documentation files**
- [ ] **Step 7: Commit with `feat: add multi-video processing queue`**
- [ ] **Step 8: Push and open a draft PR against `main` with verification evidence**
