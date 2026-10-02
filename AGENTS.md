# Repository Guidelines

## Project Structure & Module Organization

The installable Python package lives in `jpjobs/`. Core orchestration, schema,
normalization, filtering, persistence, and output code are top-level modules;
board-specific adapters belong in `jpjobs/sources/`, and shared HTTP or browser
helpers belong in `jpjobs/util/`. Add new adapters by copying
`jpjobs/sources/_template.py` and registering them in `aggregate.py`.

Tests live in `tests/` and generally mirror a module or behavior
(`tests/test_pagination.py`, for example). Use `experiments/` for reproducible
analysis utilities, `docs/` for design and audit notes, and `deploy/` for the
scheduled container workflow. Curated comparison outputs may be committed under
`artifacts/`; local databases, checkpoints, HTML captures, and screenshots are
ignored.

## Build, Test, and Development Commands

```bash
python -m venv .venv && source .venv/bin/activate
python -m pip install -e ".[dev]"
playwright install chromium
ruff check jpjobs tests experiments
ruff format --check jpjobs tests experiments
pytest -q
jpjobs --list-sources
docker compose build
```

The editable install provides the CLI and test tools. Chromium is only required
for browser-backed sources such as HelloWork. Run the Ruff checks and full test
suite before opening a pull request; `docker compose build` validates the
deployment image.

## Coding Style & Naming Conventions

Target Python 3.10 or newer, use four-space indentation and type annotations for
new public interfaces, and keep lines within Ruff's 88-character limit. Use
`snake_case` for modules, functions, variables, and source slugs; `PascalCase`
for classes and dataclasses; and `UPPER_SNAKE_CASE` for constants. Format with
`ruff format` and fix lint findings rather than suppressing them without a
specific reason.

## Testing Guidelines

Pytest (with `pytest-asyncio`) is the test framework. Name files `test_*.py` and
tests `test_<behavior>`. Keep tests deterministic: mock network and browser
boundaries instead of relying on live job boards. There is no numeric coverage
threshold, but changes should exercise success, empty, partial, and failure
paths where applicable. CI runs linting, formatting, and tests on Python 3.10
and 3.12.

## Commit & Pull Request Guidelines

Follow the history's short, imperative commit style: `Add resumable pagination`
or `Stabilize Ruff CI`. Keep each commit focused. Pull requests should explain
the user-visible effect, identify affected sources or schema fields, link the
relevant issue, and list exact verification commands. Include representative
before/after output for parser or schema changes, and screenshots for generated
HTML reports. Never commit `.env`, resumes, local databases, or scraped
diagnostic captures.
