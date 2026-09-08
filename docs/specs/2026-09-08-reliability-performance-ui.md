# ClipAuto reliability, performance, and large-batch UI

ClipAuto must remain useful when a local model returns malformed topic data, when a failed
video is retried, and when a batch contains up to 200 videos and thousands of clips.

## Reliability

- Topic detection must not fail a video only because Ollama returned malformed JSON, duplicate
  boundaries, invalid ranges, or an unavailable response.
- Valid model topics remain the preferred result. Invalid individual topics may be discarded and
  remaining boundaries repaired at transcript segment edges.
- If the model result still cannot form a valid contiguous plan, ClipAuto must create deterministic
  transcript-based topics so rendering can continue.
- Cancellation must continue to stop work and must never be converted into a fallback result.
- Retrying a failed or cancelled job must preserve reusable managed source/transcript artifacts.
- A corrupt or mismatched transcript cache must be ignored safely and replaced after transcription.

## Performance

- Successful transcripts are cached atomically in each job directory and reused on retry when the
  source filename and size still match.
- Queue polling must not transfer clip records for collapsed videos. The compact batch response
  includes `clip_count`, and clip records are fetched only when a user opens that video's clips.
- Existing API responses keep their current full form unless `include_clips=false` is requested.

## Interface

- The primary audience is a creator processing tens or hundreds of source videos. The page's one
  job is to reveal what needs attention now without losing access to completed outputs.
- Large batches expose status filters, search, compact summary counts, and incremental row
  rendering. Active work is the initial filter when a restored batch is still processing.
- Long technical failures are collapsed behind a concise, actionable summary and an optional
  details control.
- Network refresh state is visible, polling pauses in background tabs, and returning to the tab
  refreshes immediately.
- Controls use optimistic busy states and preserve keyboard focus, visible focus styles, mobile
  usability, and reduced-motion preferences.

## Visual direction

- Palette: Slate Canvas `#edf1f4`, Paper `#ffffff`, Ink `#142033`, Signal Coral `#ef654f`,
  Render Mint `#2f9364`, and Rail Blue `#3b68d9`.
- Type: a condensed system display stack for queue headings, a neutral system sans for body copy,
  and a monospace utility stack for positions, durations, and progress.
- Layout: a compact intake panel followed by an operational dashboard. Summary counters double as
  honest filters; the queue remains ordered by source position.
- Signature: each video row is attached to a continuous editing rail whose marker color and motion
  communicate state, borrowing the visual language of a video timeline rather than a generic admin
  dashboard.
