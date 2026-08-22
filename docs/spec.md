# ClipAuto Product Specification

ClipAuto is a local-only web application that accepts one or many YouTube URLs and creates one complete, vertical, subtitled clip for every distinct topic in every successfully processed video.

The processing chain is yt-dlp download and description-chapter extraction, faster-whisper transcription with timestamps, validated chapter boundaries or local Ollama topic segmentation as fallback, and FFmpeg rendering to 1080×1920 H.264/AAC MP4. Horizontal sources use a blurred background and fitted foreground without stretching. The application uses a bounded, persistent queue suitable for batches of 180–200 URLs, reports measured stage progress per video, supports cancellation and failure recovery, and never loads whole media files into memory.

The browser UI accepts newline- or whitespace-separated URLs, lists every queued video and its current stage, previews completed topic clips, downloads clips individually, and requests a backend-created ZIP containing all completed clips in a batch. yt-dlp retries applicable access failures using its native `--cookies-from-browser brave` option. Ollama model selection examines installed models and chooses the smallest suitable text-generation model.
