# ClipAuto Speed and Short-Topic Grouping Spec

This grouping rule was superseded by `2026-08-21-regroup-existing-clips.md`, which targets 45–60 second outputs using duration-aware contiguous grouping while preserving complete topics.

Rendering must remain 1080×1920 H.264/AAC MP4 with readable subtitles and an unstretched foreground. The blurred background may be generated at a lower resolution before upscaling when this materially improves throughput. Transcription must retain word timestamps and GPU/CPU fallback.

The web UI must stay compact with large batches. Completed clip previews start collapsed and are built only when requested. Queue status remains visible and polling continues to report measured backend state.

Performance work must be benchmarked or traced before implementation. Changes must not interrupt or mutate the currently running batch; they apply after the user manually restarts ClipAuto.
