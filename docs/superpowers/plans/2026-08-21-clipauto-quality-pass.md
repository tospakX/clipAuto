# ClipAuto Quality Pass Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Make individual video management obvious, render every output at 1.10× speed, improve 40–60-second topic grouping, and remove verified responsiveness and recovery defects.

**Architecture:** Keep media policy in the renderer/topic modules, lifecycle policy in the store/queue/API, and presentation behavior in the existing dependency-free frontend. Extend existing contracts instead of introducing a new service or database table.

**Tech Stack:** Python 3.12, FastAPI, SQLite, FFmpeg, vanilla JavaScript/CSS, pytest, Playwright

**Spec:** User request from 2026-08-21; existing behavior is documented in `README.md`.

## Global Constraints

- Preserve complete topic boundaries; never split a topic to hit the duration range.
- Prefer final clips from 40–60 source seconds and groups of 2–3 short topics.
- Encode video and audio at exactly 1.10× playback speed.
- Keep media deletion confined to `data/jobs`.
- Preserve one-worker defaults and bounded memory usage.
- Use tests first for every behavior change.

---

### Task 1: Better short-topic partitioning

**Files:**
- Modify: `clipauto/topics.py`
- Test: `tests/test_topics.py`

**Interfaces:**
- Consumes: `Topic(title: str, start: float, end: float)`
- Produces: `partition_topic_groups(topics, minimum=40.0, maximum=60.0)` and `combine_topics_for_output(...)`

- [x] **Step 1: Write failing partition tests**

Add literal examples proving that 2–3-topic groups are preferred when they fit, 40–60 seconds wins over topic-count preference when both cannot hold, long topics stay intact, and empty input stays empty.

- [x] **Step 2: Verify the tests fail**

Run: `uv run pytest tests/test_topics.py -q`

- [x] **Step 3: Implement scored dynamic partitioning**

Score contiguous candidates by out-of-range duration first, then excess topics beyond three, distance from 50 seconds, and output count. Keep topics at or above the minimum as standalone boundaries.

- [x] **Step 4: Verify topic and pipeline behavior**

Run: `uv run pytest tests/test_topics.py tests/test_pipeline.py -q`

### Task 2: 1.10× synchronized rendering

**Files:**
- Modify: `clipauto/renderer.py`
- Test: `tests/test_renderer.py`

**Interfaces:**
- Produces: `build_ffmpeg_command(..., speed=1.10)` with `setpts=PTS/1.10` and `atempo=1.10`
- Produces: progress measured against encoded output duration (`source_duration / speed`)

- [x] **Step 1: Write failing renderer tests**

Assert the real FFmpeg command contains synchronized video/audio speed filters, maps filtered audio optionally, preserves faststart, and calculates progress using output duration.

- [x] **Step 2: Verify the tests fail**

Run: `uv run pytest tests/test_renderer.py -q`

- [x] **Step 3: Implement filter and progress changes**

Apply subtitles before `setpts`, use an optional audio filter chain, and keep the input trim in source-time seconds.

- [x] **Step 4: Verify renderer tests**

Run: `uv run pytest tests/test_renderer.py -q`

### Task 3: Individual lifecycle controls and retry

**Files:**
- Modify: `clipauto/store.py`
- Modify: `clipauto/queue.py`
- Modify: `clipauto/api.py`
- Modify: `clipauto/static/index.html`
- Modify: `clipauto/static/app.js`
- Modify: `clipauto/static/app.css`
- Test: `tests/test_store.py`
- Test: `tests/test_queue.py`
- Test: `tests/test_api.py`
- Test: `tests/test_ui.py`

**Interfaces:**
- Produces: `JobStore.delete_job(job_id)` for queued and terminal jobs, still rejecting running jobs
- Produces: `JobStore.retry_job(job_id)` resetting failed/cancelled jobs and clearing stale clips
- Produces: `POST /api/jobs/{job_id}/retry`

- [x] **Step 1: Write failing lifecycle/API/UI tests**

Prove queued jobs can be removed, running jobs cannot, retries reset state and enqueue once, and the template exposes explicit Delete, Retry, and Copy link controls.

- [x] **Step 2: Verify the tests fail**

Run: `uv run pytest tests/test_store.py tests/test_queue.py tests/test_api.py tests/test_ui.py -q`

- [x] **Step 3: Implement backend state transitions**

Reset only failed/cancelled jobs, delete old managed output after the database transition, and enqueue the reset job through the existing deduplicating queue.

- [x] **Step 4: Implement frontend quality-of-life behavior**

Show Delete on every non-running item, Retry on failed/cancelled items, Copy link for all items, inline status messages instead of success alerts, stale-card reconciliation after polling, and output durations adjusted for 1.10×.

- [x] **Step 5: Verify lifecycle tests**

Run: `uv run pytest tests/test_store.py tests/test_queue.py tests/test_api.py tests/test_ui.py -q`

### Task 4: Performance, docs, and end-to-end verification

**Files:**
- Modify: `clipauto/store.py`
- Modify: `clipauto/pipeline.py`
- Modify: `README.md`
- Test: `tests/test_store.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces: SQLite WAL/busy-timeout connections and throttled persisted progress without reducing visible completion accuracy

- [x] **Step 1: Write failing regression tests for excessive progress writes**

Use a recording store and literal progress events to prove small updates are coalesced while stage endpoints still persist.

- [x] **Step 2: Verify the regression tests fail**

Run: `uv run pytest tests/test_pipeline.py tests/test_store.py -q`

- [x] **Step 3: Implement bounded progress writes and SQLite pragmas**

Persist progress only when it advances by at least one percentage point or reaches an endpoint; enable WAL and a 30-second busy timeout on initialized databases.

- [x] **Step 4: Update operator documentation**

Document 1.10× output, 40–60-second grouping, per-video Delete/Retry/Copy link actions, and the existing environment controls.

- [x] **Step 5: Run full verification**

Run: `uv run pytest && uv run ruff check . && uv run python -m compileall -q clipauto tests`

- [x] **Step 6: Browser smoke test**

Run the app through the repository's server helper, open Chromium headlessly, inspect console errors, verify responsive controls and deletion/retry interactions against a temporary database, and capture a screenshot for visual review.
