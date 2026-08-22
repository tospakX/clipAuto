# Topic-First Reel Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Preserve natural topic clips first, then remove micro intro/outro sections, split only oversized topics, and combine useful short neighbors.

**Architecture:** Keep chapter/Ollama normalization as the source of semantic boundaries. Replace whole-source duration partitioning in `plan_reel_topics` with an ordered cleanup pass: trim disposable edge sections, split only oversized individual topics, then group adjacent short useful topics without moving natural boundaries unnecessarily.

**Tech Stack:** Python 3.12, pytest, FFmpeg-backed existing renderer.

**Spec:** `docs/specs/2026-08-22-topic-first-reel-cleanup.md`

## Global Constraints

- Do not start ClipAuto or render production media during implementation.
- Natural chapter/Ollama boundaries are authoritative before cleanup.
- Remove only generic leading/trailing sections under 10 source seconds.
- Never discard short meaningful content; merge it with an adjacent topic when possible.
- Split only an individual oversized topic, never repartition the entire source globally.
- Keep existing staged-render validation and atomic database publication unchanged.

---

### Task 1: Express topic-first cleanup behavior

**Files:**
- Modify: `tests/test_topics.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: normalized natural `list[Topic]` and timestamped `list[TranscriptSegment]`.
- Produces: observable renderer input that retains natural topic boundaries after cleanup.

- [ ] Add a failing test where a 2-second Introduction is removed, two useful short topics are merged, and a suitable natural topic remains unchanged.
- [ ] Add failing tests proving a substantial generic section and a lone meaningful short source remain clips.
- [ ] Run the focused tests and confirm failure comes from whole-source repartitioning.

### Task 2: Implement ordered cleanup

**Files:**
- Modify: `clipauto/topics.py`
- Test: `tests/test_topics.py`

**Interfaces:**
- Consumes: `plan_reel_topics(topics, segments, minimum=44.0, maximum=66.0)`.
- Produces: cleaned `list[Topic]` in original chronological order.

- [ ] Add edge-only generic-section filtering with a 10-second maximum.
- [ ] Update oversized-topic splitting to keep indivisible coherent topics and use transcript/word/balanced fallback boundaries.
- [ ] Apply adjacent short-topic grouping only after filtering and per-topic splitting.
- [ ] Run focused topic tests and confirm the new behavior passes.

### Task 3: Correct operator documentation and verify

**Files:**
- Modify: `README.md`
- Modify: `docs/specs/2026-08-22-zero-broken-reels.md`

**Interfaces:**
- Produces: documentation that describes semantic-first cleanup rather than whole-video equal partitioning.

- [ ] Replace the whole-video planning description with the ordered cleanup workflow.
- [ ] Run `uv run pytest -q` and require zero failures.
- [ ] Run `uv run ruff check .` and require zero errors.
- [ ] Run `uv run python -m compileall -q clipauto tests` and require exit 0.
- [ ] Run `git diff --check` and verify no ClipAuto or production FFmpeg process is running.
