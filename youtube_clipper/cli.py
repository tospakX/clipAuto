from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .config import (
    ALLOWED_SPEEDS,
    DEFAULT_OLLAMA_URL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_WHISPER_COMPUTE_TYPE,
    DEFAULT_WHISPER_DEVICE,
    DEFAULT_WHISPER_MODEL,
    DEFAULT_WORK_DIR,
)
from .dependencies import DependencyError, check_dependencies
from .pipeline import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-clipper",
        description="Split a multi-topic YouTube video into local short-form clips.",
    )
    parser.add_argument("urls", nargs="*", metavar="URL", help="one or more YouTube video URLs")
    parser.add_argument("--speed", type=float, choices=ALLOWED_SPEEDS, default=1.0)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--whisper-model", default=DEFAULT_WHISPER_MODEL)
    parser.add_argument(
        "--whisper-device", choices=("auto", "cpu", "cuda"), default=DEFAULT_WHISPER_DEVICE
    )
    parser.add_argument("--whisper-compute-type", default=DEFAULT_WHISPER_COMPUTE_TYPE)
    parser.add_argument("--ollama-url", default=DEFAULT_OLLAMA_URL)
    parser.add_argument("--check", action="store_true", help="Only verify local dependencies")
    parser.add_argument("--ui", action="store_true", help="Launch the local graphical interface")
    parser.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)
    parser.add_argument("--port", type=int, default=8787, help=argparse.SUPPRESS)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser for --ui")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    try:
        if args.check:
            report = check_dependencies(args.ollama_url)
            logging.info(
                "All dependencies are available. Ollama models: %s", ", ".join(report.ollama_models)
            )
            for warning in report.warnings:
                logging.warning("%s", warning)
            return 0
        if args.ui:
            from .ui_server import serve_ui

            serve_ui(
                args.host,
                args.port,
                args.output_dir,
                args.work_dir,
                args.ollama_url,
                open_browser=not args.no_browser,
            )
            return 0
        if not args.urls:
            raise ValueError("a YouTube URL is required (or use --check)")
        failures = 0
        for index, url in enumerate(args.urls, start=1):
            logging.info("Processing video %d of %d", index, len(args.urls))
            try:
                run_pipeline(
                    url,
                    args.output_dir,
                    args.work_dir,
                    args.speed,
                    args.whisper_model,
                    args.whisper_device,
                    args.whisper_compute_type,
                    args.ollama_url,
                )
            except (DependencyError, OSError, RuntimeError, ValueError) as exc:
                failures += 1
                logging.error("Video %d failed: %s", index, exc)
        return 1 if failures else 0
    except (DependencyError, OSError, RuntimeError, ValueError) as exc:
        logging.error("%s", exc)
        return 1
    except KeyboardInterrupt:
        logging.info("Stopped")
        return 130


if __name__ == "__main__":
    sys.exit(main())
