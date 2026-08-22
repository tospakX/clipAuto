# Delete Individual Clips Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let users safely delete one completed clip at a time and remove the identified pure intro, outro, and sponsor clips without touching mixed-content or unrelated clips.

**Architecture:** Add one atomic store operation that deletes a selected clip and recalculates its completed job's clip count while refusing the last clip. Expose it through a clip DELETE endpoint that removes only managed media, then add a confirmed Delete clip button to each rendered clip card.

**Tech Stack:** Python 3.12, SQLite, FastAPI, browser JavaScript/CSS, pytest, Playwright.

**Spec:** `docs/specs/2026-08-22-delete-individual-clips.md`

## Global Constraints

- Preserve both mixed sponsor/content clips.
- Preserve every clip not explicitly selected for deletion.
- Refuse deletion of the final clip belonging to a completed video.
- Never remove files outside `data/jobs`.
- Do not re-render or reprocess production videos.
- Back up the production database and selected media before production cleanup.

---

### Task 1: Atomic clip-record deletion

**Files:**
- Modify: `clipauto/store.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Consumes: `JobStore.delete_clip(clip_id: str)`.
- Produces: the deleted `ClipRecord`, with `jobs.planned_clips` updated in the same transaction.

- [ ] Add a test with two clips that deletes one literal clip ID and asserts the sibling, completed status, and planned count remain correct.
- [ ] Add tests proving an unknown clip raises `KeyError` and the final clip raises `ValueError` without changing state.
- [ ] Run those tests and confirm they fail because `delete_clip` is absent.
- [ ] Implement the transaction using a clip/job join, a remaining-count check, one clip delete, and one job update.
- [ ] Run the focused store tests and require all to pass.

### Task 2: Clip deletion API and UI

**Files:**
- Modify: `clipauto/api.py`
- Modify: `clipauto/static/app.js`
- Modify: `clipauto/static/app.css`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: `DELETE /api/clips/{clip_id}`.
- Produces: `{\"deleted_clip\": clip_id}` and a refreshed clip list.

- [ ] Add an API test that creates two real managed clip files, deletes one, and asserts the other record/file is untouched.
- [ ] Add API tests for unknown and final-clip deletion responses.
- [ ] Run the focused API tests and confirm the endpoint returns 405 before implementation.
- [ ] Add the endpoint, restrict file removal through the existing managed-path boundary, and map store errors to 404/409.
- [ ] Add a `.delete-clip` button per card that confirms, calls the endpoint, and refreshes the batch.
- [ ] Style the clip action row and run API/UI tests.

### Task 3: Production cleanup and verification

**Files:**
- Create: a SQLite backup under `data/backups/`.
- Create: a recoverable media backup under `data/deleted-clips/`.

**Interfaces:**
- Consumes: the audited exact intro/outro/sponsor selection, excluding mixed-content clips.
- Produces: 41 fewer production clip records while all non-selected IDs and files remain intact.

- [ ] Snapshot all production clip IDs and the database before cleanup.
- [ ] Copy selected media into a dated recovery directory, then call the store deletion operation for each selected clip.
- [ ] Compare before/after IDs and prove only the selected set disappeared and both mixed clips remain.
- [ ] Run the full pytest, Ruff, compile, and diff checks.
- [ ] Use Playwright against the running app to verify a clip card exposes the confirmed Delete clip control without invoking it.
