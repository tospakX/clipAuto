# Zero-Broken Instagram Reels Spec

ClipAuto must publish complete generations of Instagram-ready reels rather than individual best-effort files.

For the default 1.10× playback speed, 44–66 source seconds is a cleanup preference, corresponding to approximately 40–60 delivered seconds. Natural description-chapter or Ollama topic boundaries are established first. The planner removes sponsor-only topics, exact generic intro/outro edge sections, and descriptive edge junk at or below 10 seconds. Removed intervals divide content into independent runs. It then splits an individually oversized topic when it can form full reels and combines adjacent useful short topics only within a run. It never globally repartitions the source or crosses removed content just to equalize durations. Suitable natural topics remain separate, and unavoidable short or long meaningful topics remain valid.

Rendering is generation-based. Every attempt writes to a unique staging directory and cannot overwrite media referenced by the database. The generated output count must exactly match the plan and every output path must be unique and contained by the staging directory.

Before publication, each MP4 must exist, be non-empty, contain a decodable H.264 1080×1920 yuv420p video stream, have a duration matching the planned 1.10× output within a narrow tolerance, and survive a full FFmpeg decode pass without errors. Audio is AAC when present; silent sources may remain silent.

Only after every output passes validation may ClipAuto atomically replace the job's clip records and mark the job completed. Any download, transcription, segmentation, render, validation, cancellation, database, or cleanup failure must leave the previous completed generation and its referenced files intact. Superseded managed media is removed only after the replacement transaction commits.
