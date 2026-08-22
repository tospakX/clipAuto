# Instagram-Ready Duration Guardrails Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure every generated clip is a coherent, vertical Instagram-ready segment by merging short adjacent topics and splitting oversized topics at transcript boundaries.

**Architecture:** Normalize detected topics against transcript segment boundaries before the existing duration-aware grouping pass. Long topics are divided into balanced contiguous pieces no longer than 60 source seconds; short topics continue through the existing dynamic-programming grouping, producing approximately 40–60 second clips whenever the available content permits. Reprocess completed jobs whose persisted outputs violate the duration contract.

**Tech Stack:** Python 3.12, SQLite, FFmpeg, Whisper, Ollama, pytest.

**Spec:** `docs/specs/2026-08-21-regroup-existing-clips.md` (duration behavior amended by this plan to permit splitting oversized topics at transcript boundaries).

## Global Constraints

- Preserve all source content in chronological order.
- Split only at available transcript segment boundaries, except when no internal boundary exists.
- Merge adjacent short topics before rendering.
- Produce no output longer than 60 source seconds when a legal split boundary exists.
- Back up the live database before requeueing completed jobs.
- Do not claim migrated media is ready until database state, file presence, duration, and the full test suite are freshly verified.

---

### Task 1: Split oversized detected topics

**Files:**
- Modify: `clipauto/topics.py`
- Test: `tests/test_topics.py`

**Interfaces:**
- Consumes: normalized `list[Topic]`, `list[TranscriptSegment]`, and a maximum duration.
- Produces: `split_oversized_topics(...) -> list[Topic]` preserving contiguous coverage and transcript boundaries.

- [ ] Write a failing test proving a single 240-second topic is split into balanced pieces at transcript boundaries.
- [ ] Run the focused test and confirm the existing code lacks the behavior.
- [ ] Implement the smallest balanced boundary partition.
- [ ] Run focused topic tests and confirm they pass.

### Task 2: Enforce the duration contract in the pipeline

**Files:**
- Modify: `clipauto/pipeline.py`
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Consumes: `split_oversized_topics` from Task 1.
- Produces: rendered topics that are split before short-topic grouping.

- [ ] Write a failing pipeline test for a single long model topic.
- [ ] Run it and confirm one oversized render topic is currently produced.
- [ ] Invoke splitting before `combine_topics_for_output`.
- [ ] Run focused pipeline tests and confirm they pass.

### Task 3: Reprocess nonconforming completed jobs

**Files:**
- Modify: `README.md`
- Modify: live `data/clipauto.db` and affected managed job directories.

**Interfaces:**
- Consumes: completed jobs containing clips over 60 seconds.
- Produces: freshly queued/rendered jobs using the corrected pipeline.

- [ ] Snapshot and back up the live database and enumerate exact affected jobs.
- [ ] Requeue affected completed jobs through a safe store operation and restart ClipAuto so the new code is loaded.
- [ ] Wait for processing to finish and verify no clip violates the duration contract.
- [ ] Document restart/apply instructions and the Instagram-ready duration behavior.

### Task 4: Final verification

**Files:**
- Verify all modified production, test, documentation, database, and media artifacts.

**Interfaces:**
- Produces: evidence that code and live outputs satisfy the contract.

- [ ] Run focused tests, then the complete test suite.
- [ ] Validate every persisted MP4 exists and is non-empty.
- [ ] Query clip-duration distribution and inspect extrema with ffprobe.
- [ ] Confirm the running app uses the updated process and report exact user-facing apply steps.
