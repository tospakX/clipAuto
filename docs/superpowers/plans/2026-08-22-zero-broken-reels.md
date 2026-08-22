# Zero-Broken Instagram Reels Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make ClipAuto publish only complete, validated Instagram-ready reels, with no short remainder clips, standalone micro intros/outros, oversized unsplit sources, missing renders, or corrupt MP4s.

**Architecture:** Replace the two-stage split/merge decision in the live pipeline with one deterministic whole-video reel planner that partitions contiguous content into the fewest balanced 44–66 source-second spans (about 40–60 delivered seconds at 1.10×), preferring topic boundaries and falling back to transcript boundaries. Render each job into a unique staging generation, fully validate every MP4, atomically commit the complete generation to SQLite, and only then remove superseded media.

**Tech Stack:** Python 3.12, SQLite, FFmpeg/ffprobe, pytest.

**Spec:** `docs/specs/2026-08-22-zero-broken-reels.md`

## Global Constraints

- Do not run ClipAuto or render production batch media while implementing this plan.
- Preserve every source interval in chronological order with no gaps or overlap.
- Never produce a delivered clip under 40 seconds when the source video is at least 44 seconds.
- Prefer one approximately one-minute clip over a valid clip plus a short remainder.
- Never publish a standalone micro intro, outro, or conclusion.
- Never expose staged, partial, missing, corrupt, wrongly sized, or wrong-codec media in SQLite.
- Keep the previous completed generation intact unless the entire replacement generation validates and commits.
- A source video shorter than the minimum reel duration fails clearly instead of publishing an unwanted short clip.

---

### Task 1: Whole-video reel planning

**Files:**
- Create: `docs/specs/2026-08-22-zero-broken-reels.md`
- Modify: `clipauto/topics.py`
- Test: `tests/test_topics.py`

**Interfaces:**
- Consumes: normalized `list[Topic]`, `list[TranscriptSegment]`, minimum 44 seconds, maximum 66 seconds.
- Produces: `plan_reel_topics(topics, segments, minimum=44.0, maximum=66.0) -> list[Topic]`.

- [ ] Write failing literal tests for 40+20 fusion, 40+40 fusion, balanced 120-second splitting, short intro/outro absorption, too-short source rejection, contiguous coverage, and no feasible transcript-boundary rejection.
- [ ] Run the focused tests and confirm failures against the current split-then-merge behavior.
- [ ] Implement a deterministic minimum-clip partition over topic and transcript boundaries, enforcing exact coverage and the duration contract.
- [ ] Run focused topic tests and confirm every planned multi-clip output is within 44–66 source seconds.

### Task 2: Complete media validation

**Files:**
- Create: `clipauto/validation.py`
- Create: `tests/test_validation.py`

**Interfaces:**
- Consumes: rendered MP4 path and expected delivered duration.
- Produces: `validate_reel(path, expected_duration) -> None`, raising `MediaValidationError` on any violation.

- [ ] Write failing tests using real tiny FFmpeg fixtures for missing files, wrong dimensions, wrong codec/format metadata, wrong duration, and truncated/corrupt media.
- [ ] Run the tests and confirm the validator is absent.
- [ ] Implement ffprobe metadata validation plus a full FFmpeg decode pass.
- [ ] Run validation tests and confirm valid H.264/AAC 1080×1920 MP4 passes while every bad fixture fails.

### Task 3: Atomic generation publication

**Files:**
- Modify: `clipauto/store.py`
- Modify: `clipauto/pipeline.py`
- Test: `tests/test_store.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: a complete validated list of `ClipRecord` objects for a running job.
- Produces: `JobStore.complete_job(job_id, clips) -> None`, atomically replacing clips, planned count, progress, status, and stage.

- [ ] Write a failing store test proving clip replacement and completion are one transaction.
- [ ] Write failing pipeline tests proving missing/duplicate/invalid outputs never replace previous completed media and staged files are cleaned.
- [ ] Implement unique per-attempt staging and injectable validation in `Pipeline`.
- [ ] Move the validated staging generation to a permanent unique directory, commit once, then remove superseded managed files.
- [ ] Run store and pipeline tests, including cancellation and failure preservation.

### Task 4: Operator documentation and full verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Produces: exact restart/resume instructions and a documented output contract.

- [ ] Document planning, validation, atomic replacement, and too-short source behavior.
- [ ] Run `uv run pytest -q` and require zero failures.
- [ ] Run `uv run ruff check .` and require zero errors.
- [ ] Run `uv run python -m compileall -q clipauto tests` and require exit 0.
- [ ] Run `git diff --check` and inspect the final diff against every global constraint.
- [ ] Verify no ClipAuto or production FFmpeg process was started.
