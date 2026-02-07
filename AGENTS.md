# Repository Guidelines

## Project Structure & Module Organization
- `larksync/`: Python CLI, sync engine, FastAPI endpoints; `core/` orchestrates tasks, `storage/` handles metadata, `web/` exposes API.
- `tests/`: mirrors backend modules with `test_*.py`, plus helper scripts for regression datasets and token flows.
- `webui-client/`: Next.js + TypeScript UI; components in `components/`, data hooks in `lib/`, pages under `app/`.
- `docs/` archives architecture notes, while `scripts/` provides bootstrap utilities (`install_dependencies.sh`, `start_dev.sh`).

## Build, Test, and Development Commands
- `python3 -m venv .venv && source .venv/bin/activate`: create/enter backend virtualenv.
- `pip install -e ".[dev]"`: install backend with pytest extras.
- `pytest` or `pytest tests/test_docx_parser.py`: run all or targeted backend tests.
- `./scripts/start_dev.sh`: spin up FastAPI and the web UI with shared ports.
- `npm install && npm run dev` (inside `webui-client/`): install frontend deps and serve Next.js locally.
- `docker build -t larksync:latest .`: build the combined backend/frontend image.

## Coding Style & Naming Conventions
- Use 4-space indentation, rich type hints, and Typer command functions named with verbs (`download`, `sync_space`).
- Keep modules single-purpose; prefer injecting dependencies via `build_runtime` instead of globals.
- Frontend files follow PascalCase components, camelCase hooks, and Next.js file routing; lint with `npm run lint` before merging.

## Testing Guidelines
- Place new cases under `tests/` with descriptive `test_*.py` names that mirror the touched module.
- Reuse fixtures from token refresh suites when hitting Feishu OAuth flows; avoid hard-coding real tokens.
- For long sync scenarios, gate heavy tests behind command-line flags (see `run_download_tests.py`) and document any required data.

## Commit & Pull Request Guidelines
- Start commit messages with a short tag plus summary (`修复: 调整 DocX 图片路径`, `feat: add sheet batching`); keep the first line under 72 chars.
- Note validation steps (`pytest`, `npm run lint`, manual CLI runs) in the commit body or PR description.
- PRs should link issues, list config/env changes, and attach screenshots or CLI snippets for user-visible updates.

## Security & Configuration Tips
- Use `config.sample.toml` as the template; never commit secrets, real tokens, or populated `output/` data.
- When tweaking rate limits or storage paths, update `README.md` and confirm compatibility with `SyncEngine` throttling parameters.
