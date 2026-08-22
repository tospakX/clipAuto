# Regroup Existing Clips Spec

ClipAuto must target 45–60 second outputs while preserving complete topic boundaries. Adjacent topics shorter than 45 seconds may be grouped; no topic is split. A duration-aware partition must minimize distance outside the 45–60 second range, so unavoidable edge cases use the closest complete-topic grouping rather than an arbitrary cut.

The same rule applies to future pipeline output and every already-completed video. Existing MP4s must be combined in chronological order with FFmpeg stream copy when compatible. Migration is atomic per video: create and validate every replacement first, then replace that video's clip records, then remove superseded media. A failure leaves the video's original records and files usable and must not stop other completed videos from being attempted.

Queued and running jobs are outside migration scope. The active application process must not be restarted or stopped. Migration must process one completed video at a time to cap temporary disk usage and must report real per-video results.
