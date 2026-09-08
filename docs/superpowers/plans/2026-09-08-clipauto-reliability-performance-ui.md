# ClipAuto Reliability, Performance, and UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ClipAuto recover from topic-model errors, reuse expensive retry work, and keep 200-video batches fast and navigable.

**Architecture:** Keep the existing FastAPI/SQLite/vanilla-JavaScript architecture. Add deterministic topic repair/fallback at the pipeline boundary, an atomic transcript sidecar scoped to each managed job, and a compact batch representation with lazy clip retrieval. Reshape the browser into a filtered operational dashboard without introducing a frontend build system.

**Tech Stack:** Python 3.12, FastAPI, SQLite, httpx/httpx2, pytest, vanilla JavaScript, HTML, CSS, Playwright.

**Spec:** `docs/specs/2026-09-08-reliability-performance-ui.md`

## Global Constraints

- Accept up to 200 unique YouTube URLs per batch.
- Preserve 1080×1920 H.264/AAC output, 1.10× playback speed, queue persistence, cancellation, and atomic clip generation.
- Never load complete media files or ZIP archives into memory.
- Do not add a frontend framework or external font/network dependency.
- Preserve full API response compatibility unless `include_clips=false` is explicitly requested.

---

### Task 1: Restore a reliable test harness

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

**Interfaces:**
- Consumes: Starlette 1.6's documented TestClient compatibility layer.
- Produces: a non-hanging `fastapi.testclient.TestClient` for the existing API/UI suite.

- [x] **Step 1: Reproduce the compatibility failure**

Run: `timeout 15s uv run pytest -vv tests/test_api.py::test_creates_and_enqueues_200_url_batch`
Expected: timeout while entering `TestClient`, with Starlette warning that plain `httpx` is deprecated.

- [x] **Step 2: Add the supported client dependency**

Add `httpx2>=2,<3` to the dev dependency group and refresh `uv.lock`.

- [x] **Step 3: Verify the harness**

Run: `timeout 30s uv run pytest -q tests/test_api.py tests/test_ui.py`
Expected: all API and static UI tests pass without hanging.

- [x] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "fix: restore FastAPI test client compatibility"
```

### Task 2: Make topic detection self-healing

**Files:**
- Modify: `clipauto/topics.py`
- Modify: `clipauto/pipeline.py`
- Modify: `tests/test_topics.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `list[TranscriptSegment]`, source duration, and optional Ollama text.
- Produces: `topics_from_transcript(segments, duration) -> list[Topic]` and a pipeline path that falls back only for model/validation errors, never cancellation.

- [x] **Step 1: Write failing topic repair and fallback tests**

Cover an object envelope containing `topics`, duplicate/invalid model ranges with enough valid
items to repair, and deterministic transcript fallback that covers `[0, duration]` contiguously
with readable non-empty titles.

- [x] **Step 2: Run topic tests to verify RED**

Run: `uv run pytest -q tests/test_topics.py`
Expected: the new envelope, repair, and fallback tests fail because behavior is absent.

- [x] **Step 3: Implement tolerant parsing and deterministic fallback**

Use JSON decoder scanning for the first array or `{ "topics": [...] }` envelope, discard invalid
items, choose strictly increasing transcript boundaries, and generate approximately 55-second
transcript topics when no usable model plan remains.

- [x] **Step 4: Write and run a failing pipeline fallback test**

Make the segmenter raise `OllamaError`; assert the renderer still receives a contiguous non-empty
topic plan. Separately assert `ProcessCancelled` still cancels the job.

Run: `uv run pytest -q tests/test_pipeline.py -k 'fallback or cancellation'`
Expected: the model-error fallback test fails before the pipeline change.

- [x] **Step 5: Implement the pipeline boundary and verify GREEN**

Catch model/validation failures around segmentation, log one concise warning, and call
`topics_from_transcript`; re-raise cancellation.

Run: `uv run pytest -q tests/test_topics.py tests/test_pipeline.py`
Expected: all topic and pipeline tests pass.

- [x] **Step 6: Commit**

```bash
git add clipauto/topics.py clipauto/pipeline.py tests/test_topics.py tests/test_pipeline.py
git commit -m "fix: recover from invalid topic model output"
```

### Task 3: Preserve and reuse expensive retry artifacts

**Files:**
- Create: `clipauto/transcript_cache.py`
- Create: `tests/test_transcript_cache.py`
- Modify: `clipauto/pipeline.py`
- Modify: `clipauto/api.py`
- Modify: `tests/test_pipeline.py`
- Modify: `tests/test_api.py`

**Interfaces:**
- Produces: `load_transcript(path, source) -> TranscriptionResult | None` and `save_transcript(path, source, result) -> None`.
- Consumes: the managed source path and `TranscriptionResult`; cache identity is version + source name + source byte size.

- [x] **Step 1: Write failing cache tests**

Test round-trip preservation of language/device/segments/words, rejection after source-size change,
and safe rejection of malformed JSON.

- [x] **Step 2: Run cache tests to verify RED**

Run: `uv run pytest -q tests/test_transcript_cache.py`
Expected: import failure because the module does not exist.

- [x] **Step 3: Implement atomic transcript sidecars**

Serialize to a sibling temporary file, flush it with `Path.replace`, and return `None` for any
schema, version, source identity, numeric, or JSON mismatch.

- [x] **Step 4: Write failing retry/pipeline reuse tests**

Assert the retry endpoint preserves a managed source and transcript sidecar, and assert a second
pipeline attempt with matching source does not call the transcriber.

- [x] **Step 5: Implement retry preservation and cache integration**

Stop deleting `work_dir` in the retry route. Load before transcription; on a miss transcribe and
save; keep stage/progress/cancellation updates unchanged.

- [x] **Step 6: Verify GREEN**

Run: `uv run pytest -q tests/test_transcript_cache.py tests/test_api.py tests/test_pipeline.py`
Expected: all cache, API, and pipeline tests pass.

- [x] **Step 7: Commit**

```bash
git add clipauto/transcript_cache.py clipauto/pipeline.py clipauto/api.py tests/test_transcript_cache.py tests/test_pipeline.py tests/test_api.py
git commit -m "perf: reuse transcript work when retrying videos"
```

### Task 4: Build a fast large-batch dashboard

**Files:**
- Modify: `clipauto/models.py`
- Modify: `clipauto/store.py`
- Modify: `clipauto/api.py`
- Modify: `clipauto/static/index.html`
- Modify: `clipauto/static/app.js`
- Modify: `clipauto/static/app.css`
- Modify: `tests/test_store.py`
- Modify: `tests/test_api.py`
- Modify: `tests/test_ui.py`
- Modify: `scripts/browser_smoke.py`

**Interfaces:**
- Produces: `GET /api/batches/{batch_id}?include_clips=false`, `GET /api/batches?include_clips=false`, and `GET /api/jobs/{job_id}/clips`.
- Consumes: compact jobs with `clip_count` and no `clips`; lazy endpoint returns the existing clip record shape.

- [x] **Step 1: Write failing compact-response tests**

Assert compact jobs contain `clip_count` but no `clips`, the lazy endpoint returns ordered clips,
and the default batch response still contains full clips.

- [x] **Step 2: Run backend tests to verify RED**

Run: `uv run pytest -q tests/test_store.py tests/test_api.py -k 'compact or lazy or clip_count'`
Expected: failures for the missing query behavior and endpoint.

- [x] **Step 3: Implement compact store/API serialization**

Count clips in the jobs query, parameterize serialization with `include_clips`, and add the lazy
job-clips route without changing media-path behavior.

- [x] **Step 4: Write failing UI structure tests**

Assert accessible summary filter buttons, queue search, visible connection status, a load-more
control, and collapsed error details exist in delivered markup.

- [x] **Step 5: Run UI tests to verify RED**

Run: `uv run pytest -q tests/test_ui.py`
Expected: failures for the new dashboard controls.

- [x] **Step 6: Implement the dashboard**

Use compact polling, fetch clips on first expansion, default restored active batches to the Active
filter, render 30 matching rows at a time, pause polling while hidden, summarize known errors with
actionable copy, and keep technical detail in `<details>`. Apply the palette/type/layout/signature
from the spec, including mobile and reduced-motion behavior.

- [x] **Step 7: Run browser critique and refine once**

Launch ClipAuto against isolated seeded temporary data, capture 1440×1000 and 390×844 screenshots,
exercise filters/search/lazy clips/error details, and assert no console/page errors or horizontal
overflow. Remove one decorative element if it does not communicate queue state.

- [x] **Step 8: Verify GREEN**

Run: `uv run pytest -q tests/test_store.py tests/test_api.py tests/test_ui.py`
Expected: all store, API, and UI tests pass.

- [x] **Step 9: Commit**

```bash
git add clipauto/models.py clipauto/store.py clipauto/api.py clipauto/static tests scripts/browser_smoke.py
git commit -m "feat: streamline the large-batch dashboard"
```

### Task 5: Full verification and documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: the completed reliability, cache, compact API, and dashboard behavior.
- Produces: operator instructions that describe automatic fallback, retry reuse, and queue filters.

- [x] **Step 1: Update operator documentation**

Document that malformed/unavailable local-model output uses deterministic transcript topics,
failed retries retain reusable analysis, and clip metadata is loaded only when expanded.

- [x] **Step 2: Run complete verification**

Run: `uv run pytest -q`
Expected: all tests pass with no hangs.

Run: `uv run ruff check .`
Expected: `All checks passed!`

Run: `uv run python -m compileall -q clipauto tests`
Expected: exit code 0 with no output.

Run: `git diff --check HEAD^`
Expected: exit code 0 with no whitespace errors.

- [x] **Step 3: Commit**

```bash
git add README.md docs/specs/2026-09-08-reliability-performance-ui.md docs/superpowers/plans/2026-09-08-clipauto-reliability-performance-ui.md
git commit -m "docs: explain ClipAuto resilience and queue workflow"
```
