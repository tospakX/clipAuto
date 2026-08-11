# Contributing

Thank you for improving Local YouTube Topic Clipper. The project favors a small, understandable
pipeline over framework-heavy abstractions.

## Development setup

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
python -m unittest discover -v
ruff check .
```

Run `youtube-clipper --check` for the local integration prerequisites. Unit tests must not require
Ollama, model downloads, YouTube access, or GPU hardware. Put optional heavyweight integration
checks in local development instructions rather than the default test suite.

## Change workflow

1. Open an issue for behavior changes that affect output or compatibility.
2. Keep processing stages in their existing modules; see `docs/architecture.md`.
3. Add or update tests alongside the change.
4. Update `CHANGELOG.md` under **Unreleased** for user-visible behavior.
5. Run tests, Ruff, a dependency check, and a package build before opening a pull request.

Use conventional, imperative commit subjects such as `fix: detect comma-separated markers` or
`feat: add a framing profile`. Pull requests should explain the user impact and verification.

## Releases

The project uses semantic versioning. Update `youtube_clipper.__version__`, move Unreleased
entries into a dated release section, build with `python -m build`, and tag the commit as `vX.Y.Z`.
