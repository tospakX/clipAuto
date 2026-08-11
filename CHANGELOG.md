# Changelog

Notable changes are documented here. The format follows Keep a Changelog and versions follow
Semantic Versioning.

## Unreleased

No unreleased changes.

## 0.1.0 - 2026-08-12

### Added

- Local YouTube download, faster-whisper transcription, PySceneDetect analysis, Ollama topic
  reasoning, multi-signal boundary fusion, and vertical FFmpeg export.
- Dependency checks, stage logging, documentation, and unit/integration tests.
- Responsive local graphical interface with setup health, progress tracking, job restoration,
  result previews, downloads, and accessible desktop/mobile layouts.
- Background job management and byte-range clip streaming without additional web dependencies.
- GitHub Actions tests and linting.
- Dependabot configuration and contribution templates.
- Architecture and contribution documentation.
- Central configuration for upgradeable processing defaults.
- Playback speeds from 0.50x through 2.00x.
- YouTube description timestamp and structured chapter detection.
- Versioned transcript/scene analysis caching for faster retries.
- Overlapping Ollama reasoning windows for transcripts larger than one model prompt.

### Changed

- Exports now use a 9:16 1080x1920 canvas and center the complete source frame with padding.
- Simplified UI copy, typography, clip labels, and result previews.
- Creator chapter maps now suppress unsupported Ollama subdivisions inside one topic.
- Reduced Ollama prompt size by applying visual scene evidence during fusion instead.
- FFmpeg exports are staged transactionally so encoding failures preserve previous clips.
- Dependency checks now verify OpenCV plus the required H.264 and AAC encoders.
- HTTP video streaming now handles suffix byte ranges correctly.
- README setup and usage are organized as a copy-paste quick start with a product screenshot.
