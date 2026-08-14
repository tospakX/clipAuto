# Architecture

The application is deliberately a linear pipeline with narrow module boundaries. Each stage
accepts ordinary Python values and returns ordinary values, which keeps components replaceable
and makes unit testing possible without loading models or processing video.

```text
CLI / local web queue
 └─ sequential job worker
     └─ dependency check
         └─ yt-dlp download into .clipper-work/<video-id>/
             ├─ faster-whisper transcript + word timestamps
             ├─ PySceneDetect visual transitions
             ├─ YouTube description and chapter timestamps
             └─ explicit spoken-marker detection
                 └─ Ollama semantic boundary reasoning
                     └─ evidence fusion
                         └─ FFmpeg exports into output/<title>-<video-id>/clips/
```

## Module ownership

| Module | Responsibility | Safe extension point |
| --- | --- | --- |
| `config.py` | Product defaults and tuning constants | Change defaults in one place |
| `analysis_cache.py` | Versioned transcript and scene cache | Change cache schema/invalidation |
| `dependencies.py` | Executable, Python package, and Ollama checks | Add a required local tool |
| `downloader.py` | YouTube acquisition with `yt-dlp` | Add download options |
| `transcriber.py` | Local faster-whisper inference | Add language/model controls |
| `scenes.py` | PySceneDetect visual transitions | Add another scene detector |
| `ollama.py` | Model discovery and semantic reasoning | Revise model policy or prompt |
| `boundaries.py` | Spoken markers and evidence fusion | Add phrases or scoring signals |
| `exporter.py` | FFmpeg filters and encoding | Add framing or encoding profiles |
| `naming.py` | Portable directory and filename components | Revise filesystem naming policy |
| `topics.py` | Descriptive per-boundary clip names | Add another topic-label source |
| `pipeline.py` | Stage orchestration and logging | Add a stage without changing CLI |
| `cli.py` | User-facing arguments and exit codes | Expose a new pipeline option |
| `ui_server.py` | Local HTTP API, job state, and clip streaming | Add UI-facing operations |
| `ui/` | Responsive HTML, CSS, and browser behavior | Improve the graphical experience |

Shared timestamped data structures live in `types.py`. Processing modules should not import the
CLI, and the CLI should not contain processing logic.

The graphical interface uses Python's local threaded HTTP server and packaged static assets, so
it adds no web-framework or JavaScript-build dependency. `JobManager` owns a lock-protected FIFO
of immutable job settings and starts at most one short-lived worker thread. The worker processes
one heavyweight media job at a time and keeps looping after item-level failures. Jobs expose
`waiting`, `downloading`, `analyzing`, `clipping`, `completed`, and `failed` states. Only waiting
items can be removed. The server also supports HTTP byte ranges for browser video previews and
binds to loopback by default.

YouTube URLs are normalized to their video ID before active-queue duplicate checks. Completed and
failed jobs remain visible for the lifetime of the local server, while progress history is capped
per item. Media bytes are streamed from disk rather than held in job state.

## Boundary strategy

Explicit spoken markers, YouTube chapters, description timestamp lists, and Ollama suggestions
create candidate boundaries. Scene changes only support or refine candidates; they never create
topics by themselves. Isolated description time mentions require another signal. Candidates
receive a confidence score, are snapped to nearby word timestamps and visual cuts, and are
filtered by the minimum clip duration.

When a reliable creator topic map starts at zero, it guards against accidental subdivisions from
ordinary visual cuts or narrative progression. Ollama scene timestamps are omitted from the
reasoning prompt and combined later in deterministic fusion, reducing prompt size and visual-cut
bias.

Long transcripts are divided at transcript-segment boundaries into overlapping reasoning windows.
Results are validated, merged, and deduplicated so no middle section is discarded. FFmpeg encodes
to hidden pending files and publishes the numbered set only after every clip succeeds, preserving
the previous complete set when encoding fails. Topic filenames prefer creator chapter titles,
then Ollama's semantic reason, then nearby transcript text, with a deterministic numbered fallback.

## Upgrade guidelines

1. Change central defaults in `config.py`; expose a CLI flag only when users need per-run control.
2. Preserve a module's input/output contract when replacing an implementation.
3. Add a focused unit test for every new marker, scoring rule, model policy, or FFmpeg filter.
4. Keep network AI clients out of the project. Ollama is the only reasoning boundary.
5. Run `ruff check .`, `python -m unittest discover -v`, and `python -m build` before release.
