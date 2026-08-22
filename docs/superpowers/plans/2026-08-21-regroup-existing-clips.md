# Regroup Existing Clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce approximately 45–60 second complete-topic outputs for future and already-completed videos.

**Architecture:** A deterministic dynamic-programming partition groups adjacent short topics while minimizing duration outside 45–60 seconds. A separate migration module concatenates existing MP4s with FFmpeg into per-video staging files, validates them, atomically replaces clip records, and cleans superseded files only after database success.

**Tech Stack:** Python 3.12, SQLite, FFmpeg/ffprobe, pytest.

**Spec:** `docs/specs/2026-08-21-regroup-existing-clips.md`

## Global Constraints

- Never split a topic.
- Preserve chronological ordering and full content.
- Do not touch queued or running jobs.
- Commit migration per completed video only after every output validates.
- Process one completed video at a time and do not restart the live server.

---

### Task 1: Duration-aware topic partition

**Files:**
- Modify: `clipauto/topics.py`
- Modify: `tests/test_topics.py`
- Modify: `tests/test_pipeline.py`

**Interfaces:**
- Produces: `group_topics_for_output(topics, minimum=45.0, maximum=60.0) -> list[list[Topic]]` and combined `list[Topic]` for the pipeline.

- [ ] Write literal tests for exact-range groups, unavoidable remainder balancing, long-topic isolation, and order/title preservation.
- [ ] Run focused tests and confirm failure against exact-triples behavior.
- [ ] Implement the minimum-penalty contiguous partition and pipeline integration.
- [ ] Run focused topic and pipeline tests.

### Task 2: Transactional existing-media migration

**Files:**
- Create: `clipauto/regroup.py`
- Create: `tests/test_regroup.py`
- Modify: `clipauto/store.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: completed `JobRecord` clip records and duration groups.
- Produces: `regroup_completed_jobs(store, data_dir, progress) -> RegroupSummary` and a `clipauto-regroup` command.

- [ ] Write a real-media integration test for chronological FFmpeg concatenation and database replacement.
- [ ] Write failure tests proving original records/files survive an incomplete replacement.
- [ ] Run tests and confirm failure because migration is absent.
- [ ] Implement one-video staging, stream-copy concatenation, ffprobe validation, atomic database replacement, and post-commit cleanup.
- [ ] Run migration tests and the full suite.

### Task 3: Existing library migration and verification

**Files:**
- Modify: `README.md`

**Interfaces:**
- Runs the `clipauto-regroup` command against `data/clipauto.db` without interacting with the active queue.

- [ ] Snapshot completed-job/clip counts and available disk space.
- [ ] Run the migration and retain its per-video success/failure report.
- [ ] Verify every migrated DB path exists and probe representative outputs.
- [ ] Verify queued/running counts and the live server PID are unchanged.
- [ ] Run format, lint, all tests, compilation, and patch checks.
- [ ] Document the new grouping and migration command.
