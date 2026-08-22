# Content Junk Detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reliably remove pure sponsor, intro, and outro topics without deleting mixed editorial content or accidentally rendering across removed intervals.

**Architecture:** Classify normalized titles with directional intro/outro rules and a sponsor-only rule. Filter before splitting, divide retained topics into contiguous runs at every removed interval, then run the existing split-and-combine cleanup independently per run.

**Tech Stack:** Python 3.12 and pytest.

**Spec:** `docs/specs/2026-08-22-content-junk-detection.md`

## Global Constraints

- Preserve natural chapter/Ollama topic boundaries before cleanup.
- Preserve sponsor/content titles joined with ` + `.
- Never merge or split across a removed time interval.
- Remove exact generic intros/outros at their relevant edge regardless of duration.
- Remove descriptive “Introduction to” titles only at the leading edge and only at or below 10 seconds.
- Do not reprocess or mutate the existing completed production clips.

---

### Task 1: Lock the classification rules with failing tests

**Files:**
- Modify: `tests/test_topics.py`

**Interfaces:**
- Consumes: natural `Topic` sequences.
- Produces: literal `plan_reel_topics` results with junk ranges absent.

- [ ] Add a failing middle-sponsor test whose retained clips end before and start after the sponsor interval.
- [ ] Add failing tests for chapter-style sponsor variants, exact long edge intro/outro titles, and a 10-second descriptive intro.
- [ ] Add passing-protection expectations for mixed sponsor/content and substantial descriptive introduction titles.
- [ ] Run the focused tests and confirm failures identify exact-title and contiguous-grouping defects.

### Task 2: Implement filtering and contiguous-run planning

**Files:**
- Modify: `clipauto/topics.py`
- Test: `tests/test_topics.py`

**Interfaces:**
- Consumes: `plan_reel_topics(topics, segments, minimum=44.0, maximum=66.0)`.
- Produces: chronologically ordered editorial clips that never span removed junk.

- [ ] Normalize titles by removing part suffixes and punctuation.
- [ ] Implement sponsor-only, leading-intro, and trailing-outro predicates.
- [ ] Filter junk and split retained topics into runs whenever adjacent timestamps are no longer contiguous.
- [ ] Split oversized topics and combine short topics independently within each run.
- [ ] Run all topic and pipeline tests.

### Task 3: Document and verify the finished workflow

**Files:**
- Modify: `README.md`
- Modify: `docs/specs/2026-08-22-topic-first-reel-cleanup.md`

**Interfaces:**
- Produces: operator-facing detection behavior and verification evidence.

- [ ] Document sponsor-only filtering, mixed-content preservation, directional edge cleanup, and gap-safe grouping.
- [ ] Run the full pytest suite, Ruff, compileall, and diff check.
- [ ] Audit the retained production database for missing files, count mismatches, pure junk titles, and preservation of both mixed clips.
