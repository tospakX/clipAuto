# ClipAuto

ClipAuto is a local web app that turns YouTube videos into complete vertical Instagram reels. It downloads with yt-dlp, prefers timestamps already published as YouTube description chapters, uses a local Ollama model when chapters are unavailable, transcribes with faster-whisper, and renders subtitled 1080×1920 MP4 clips with FFmpeg.

## Requirements

- Linux with `ffmpeg`, `ffprobe`, `yt-dlp`, and `ollama` on `PATH`
- Brave only if a video needs browser authentication or age/access cookies
- One or more Ollama text-generation models already installed
- NVIDIA GPU recommended; CPU transcription is supported automatically
- About 1–2 GB free for the default Whisper model, plus space for source videos and rendered clips

The project uses Python 3.12 in an isolated `uv` environment. The system Python is not modified.

## Start

```bash
cd /home/tospak/Desktop/Code/clipAuto
uv sync
ollama list
uv run clipauto
```

Open <http://127.0.0.1:8765>. Paste one URL per line (mixed whitespace and commas also work), then select **Create clips**. A single request accepts up to 200 unique URLs.

yt-dlp parses timestamp lists in the video description into chapter metadata. When that metadata has valid titles and ordered start times, ClipAuto uses those exact starts and makes the topics contiguous through the full video. Malformed or missing chapter metadata falls back to Ollama. ClipAuto checks Ollama through its local API and automatically chooses the installed completion model with the smallest parameter count; it never downloads an Ollama model. The default faster-whisper model is `small`, and its weights are downloaded by faster-whisper on first use if they are not already cached.

After segmentation, ClipAuto keeps the natural chapter/Ollama topic boundaries and cleans them up in order. Sponsor-only topics are removed wherever they occur, including common labels such as Sponsor, Sponsored message, Advertisement, Ad read/break, Commercial break, Paid promotion, Partner message, or “a word from our sponsor”; a topic combining sponsor and real content with ` + ` is preserved. Exact leading Intro/Introduction/Opening/Video Intro/Channel Intro sections and exact trailing Outro/Conclusion/Ending/Closing/Thanks for watching/End screen/Subscribe/Call to action sections are removed. Descriptive edge sections are removed only when they are 10 seconds or shorter. Removed internal ads create hard gaps that later grouping cannot cross. ClipAuto then splits an individually oversized topic at transcript or word boundaries when it can form full reels and combines adjacent useful short topics within each uninterrupted content run toward the preferred 44–66 source-second range.

Every finished clip plays at 1.10× speed. Video, audio, burned-in subtitles, progress reporting, and the duration shown in the interface stay synchronized; the source topic boundaries remain unchanged.

Code changes apply to the running server after a restart:

```bash
# In the terminal currently running ClipAuto
Ctrl+C

cd /home/tospak/Desktop/Code/clipAuto
uv sync
uv run clipauto
```

Queued and interrupted jobs resume automatically from SQLite after the restart.

## Queue and recovery

The default is one full pipeline worker, so only one video moves through the pipeline at a time. ClipAuto keeps the loaded Whisper model available between sequential videos and renders up to two clips from the current video concurrently. This avoids repeated model startup and improves FFmpeg throughput without allowing different videos' Whisper, Ollama, and rendering stages to collide. Waiting jobs live in SQLite and a clean application restart resumes interrupted or queued work in input order. A user-cancelled job stays cancelled. Model reuse is disabled automatically when `CLIPAUTO_WORKER_COUNT` is above one so separate worker threads do not share one inference instance.

Advanced users can change concurrency, model, storage, and bind address with environment variables:

```bash
CLIPAUTO_WORKER_COUNT=2 CLIPAUTO_WHISPER_MODEL=medium uv run clipauto
CLIPAUTO_DATA_DIR=/mnt/media/clipauto CLIPAUTO_PORT=9000 uv run clipauto
```

Use a worker count above one only when the machine has enough GPU memory and disk throughput for overlapping stages.

## YouTube access fallback

Every download first runs without browser data. If yt-dlp reports an access-related error such as HTTP 403, an age/sign-in gate, bot confirmation, or cookie requirement, ClipAuto retries using yt-dlp's native Brave integration:

```bash
yt-dlp --cookies-from-browser brave URL
```

There is no custom cookie storage. Close Brave if its cookie database is locked, make sure the desired profile is signed in, and retry the URL as a new job. Unsupported URLs, deleted/private videos without account access, full disks, and unrelated errors do not trigger a cookie retry and appear on that video's queue card without stopping the rest of the batch.

## Outputs and downloads

Persistent state and media live under `data/` by default:

```text
data/
├── clipauto.db
└── jobs/<job-id>/
    └── renders/<generation-id>/
        ├── clip_01.ass
        ├── clip_01.mp4
        └── ...
```

Individual preview/download responses stream files from disk. Preview players start collapsed and are created only after selecting **Show clips**, keeping batches with hundreds of clips responsive. **Download all** creates a temporary ZIP on the backend with every clip from every completed video in the batch; failed, cancelled, and still-running videos are excluded. The temporary ZIP is deleted after the response finishes.

**Export MP4s** copies every completed clip into one new flat `ClipAuto-*` folder under `~/Downloads`, with video and topic numbers in each filename. It does not create a ZIP and does not load the files into memory. Set `CLIPAUTO_EXPORT_DIR` to use a different destination.

Downloads are capped at 1080p because the final vertical output is 1080 pixels wide. Each attempt renders into a new hidden staging generation and cannot overwrite clips already referenced by SQLite. ClipAuto requires the exact planned output count, unique managed paths, H.264 1080×1920 yuv420p video, AAC audio when audio exists, the expected 1.10× duration, complete packet coverage, and a full error-free FFmpeg decode for every MP4. Only after every clip passes does one database transaction replace the generation and mark the job completed. Failed or cancelled attempts remove their staging files and retain the previous generation.

After that atomic commit, ClipAuto removes superseded media and the downloaded source file. Sources for failed or cancelled jobs remain available until their history is cleared.

Rendering builds the decorative blurred background at low resolution before scaling it to the 1080×1920 delivery frame, while the foreground and subtitles remain full resolution. FFmpeg uses the faster x264 preset, and Whisper uses greedy timestamped decoding; these favor throughput while preserving the output format and topic boundaries.

Queue polling skips unchanged video cards. This keeps large 200-video batches responsive instead of rebuilding every card on each status refresh.

ClipAuto never loads a complete video or ZIP into memory. Use **Clear history** in the queue header to remove completed, failed, cancelled, and waiting records plus their generated files. A video that is actively processing is preserved.

Each video card has its own controls. **Delete video** removes a waiting, completed, failed, or cancelled video and its generated files without changing its batch siblings. **Cancel** safely stops active work, **Retry** resets failed or cancelled work and queues it again, and **Copy link** copies that video's source URL.

The regroup command is only a lossless compatibility migration for older completed clips; it cannot split an already-rendered oversized clip at transcript boundaries. For the strict reel contract, let queued legacy jobs reprocess through the current pipeline. To perform only the older lossless fusion migration, keep the app running and use a second terminal:

```bash
cd /home/tospak/Desktop/Code/clipAuto
uv run clipauto-regroup
```

The command considers completed videos only, combines compatible MP4s with lossless FFmpeg stream copy, and processes one video at a time. Each video's new files are created and validated before its database records change. Running the command again is safe; videos that no longer benefit from regrouping are skipped. This migration preserves the speed of existing MP4s; it does not re-encode older 1.00× files to 1.10×.

## Verification

```bash
uv run pytest
uv run ruff check .
uv run python -m compileall -q clipauto tests
```
