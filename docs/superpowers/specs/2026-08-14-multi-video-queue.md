# Multi-video Queue Specification

## Queue behavior

- Accept one or more YouTube video URLs from the local web interface and CLI.
- Normalize supported `youtube.com` and `youtu.be` video URLs and reject URLs without a video ID.
- Prevent duplicates within a submission and while the same video is waiting or processing.
- Process one video at a time with visible `waiting`, `downloading`, `analyzing`, `clipping`,
  `completed`, and `failed` states.
- Continue processing later items after any individual item fails.
- Permit removal only while an item is still waiting.
- Preserve progress history, clip previews/downloads, playback-speed selection, transcription-quality
  selection, setup health, and browser restoration.

## Files and output

- Keep each video's source, metadata, transcript cache, and clips separate.
- Store work under `.clipper-work/<youtube-id>/`.
- Store deliverables under `output/<safe-title>-<youtube-id>/clips/`.
- Use deterministic Windows/Linux-safe path components, reserved-name protection, bounded lengths,
  and the video ID to distinguish equal or similar titles.
- Name clips `01_<topic-name>.mp4`, `02_<topic-name>.mp4`, and so on, selecting topic names from
  creator chapters, semantic suggestions, or nearby transcript text.
- Keep clip-title text in result cards compact.

## Reliability and compatibility

- Keep single-video UI and CLI usage working.
- Do not let queue threads overlap pipeline execution.
- Do not expose arbitrary filesystem paths through clip download routes.
- Bound retained event history and avoid holding media content in memory.
- Preserve transactional FFmpeg publication so a failed encode does not publish a partial set.
- Do not commit generated media, caches, environments, packages, or secrets.

## Verification

- Cover single and multiple videos, invalid URLs, duplicates, a failure between successful items,
  waiting-item removal, similar titles, safe paths, and topic filenames with automated tests.
- Run the complete unit suite, Ruff, package build, CLI parser tests, and a local HTTP queue flow.
- Review the final diff and ignored artifacts before publishing a feature branch and draft PR.
