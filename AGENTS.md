# Repository Guidelines

## Project Structure & Module Organization
- `app.py` is the FastAPI entry point for the main server.
- `blueprints/` contains feature modules (auth, chat, memo, prompt_share, admin) and their routes/templates/static assets.
- `services/` holds shared integrations (DB, LLM, email, user helpers).
- `templates/` and `static/` are global HTML/CSS/JS assets; blueprint-specific assets live under each blueprint’s `templates/` and `static/` folders.
- `alembic/versions/` holds the PostgreSQL schema migration history.
- `tests/` contains `unit/` and `integration/` suites (`unittest`) plus shared helpers under `tests/helpers/`.

## Build, Test, and Development Commands
- `docker-compose up --build` builds and runs the full stack (FastAPI + PostgreSQL) via Docker.
- `pip install -r requirements.txt` installs Python dependencies for local dev.
- `python app.py` starts the FastAPI app locally (ensure required env vars are set).
- `python -m unittest` runs the test suite; target a file with `python -m unittest tests.unit.test_edit_default_task`.

## Coding Style & Naming Conventions
- Python: 4-space indentation, `snake_case` for functions/variables, `CapWords` for classes.
- JavaScript: follow existing module pattern in `static/js/` and keep files single-responsibility.
- CSS: follow the repo’s guidance in `static/css/`—base styles in `static/css/base/`, reusable components in `static/css/components/`, and page entrypoints in `static/css/pages/<page>/index.css`. Prefer BEM-style `kebab-case` class names.
- No formatter is enforced; keep changes consistent with surrounding code.

## Testing Guidelines
- Framework: `unittest` (see `tests/unit/test_edit_default_task.py`).
- Naming: place tests in `tests/` and prefix files with `test_`.
- Focus on request/response behavior for FastAPI routes and mock external services/DB connections.

## Commit & Pull Request Guidelines
- Recent commits use short, descriptive summaries (English and Japanese are both present). No strict conventional-commit prefix is used—keep messages concise and action-oriented.
- PRs should include: a clear description, linked issue (if any), test notes (commands + results), and screenshots or screen captures for UI changes.

## Security & Configuration Tips
- Required environment variables include `GROQ_API_KEY`, `Gemini_API_KEY`, `FASTAPI_SECRET_KEY`, email credentials, PostgreSQL settings, and Redis settings (if using Redis auth). (`FLASK_SECRET_KEY` is kept as a legacy fallback.) Keep secrets in environment variables or `.env` and out of git.
- Disable `FASTAPI_DEBUG` in production and review Docker defaults before deploying.
