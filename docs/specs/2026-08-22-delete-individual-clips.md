# Delete Individual Clips Spec

A completed video must allow one published clip to be deleted without changing any sibling clip. Deletion removes the clip record, updates the job's planned clip count, and makes the deleted media unavailable while preserving the video's completed status.

The final remaining clip of a video cannot be deleted through this action because a completed video must retain at least one published clip. Unknown clips return not found. The browser must show a Delete clip action on every clip card, ask for confirmation, refresh the batch after success, and display API failures without hiding the existing clips.

Managed media deletion is clip-scoped. Files outside the managed jobs directory are never removed. A clip's subtitle sidecar may be removed with its MP4; sibling media and database records must remain unchanged.
