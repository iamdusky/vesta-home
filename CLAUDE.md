# VESTA — Claude Code Context

## What this project is
A local family chatbot that displays LLM answers on a physical **Vestaboard Note** (15 columns × 3 rows = 45 characters). Voice input, scheduled family messages, Plex recommendations, weather.

## Stack
- **LLM**: Any OpenAI-compatible backend — Ollama (default), OpenAI API, or vLLM. Configured via `LLM_BASE_URL` / `LLM_API_KEY` / `MODEL` env vars.
- **Backend**: Python FastAPI (`backend/`), async, streaming SSE
- **Frontend**: Vanilla JS + Web Speech API (`frontend/index.html`), single file, no build step
- **Board**: Vestaboard Read/Write API — `POST https://rw.vestaboard.com/` with `X-Vestaboard-Read-Write-Key` header
- **Scheduler**: APScheduler 3.x (`AsyncIOScheduler`) with pytz timezones
- **Plex**: Local API at `http://localhost:32400`, `Accept: application/json`

## Key constraints
- Vestaboard Note is **15×3 = 45 chars max**. Every message sent to the board must go through the LLM formatter first (`messages.py` or `/api/board-format`).
- Board API rate limit: **1 message per 15 seconds**. Always use `board.enqueue()` — never call `vesta.send()` directly from endpoints or scheduler jobs.
- Full chat history is sent with every request. If very long sessions become an issue, add a sliding window in `main.py`.

## Module responsibilities
| File | Owns |
|---|---|
| `main.py` | FastAPI app, startup wiring, all API endpoints |
| `board.py` | Queue singleton, rate-limited worker, `enqueue()` |
| `vestaboard.py` | HTTP client for the Vestaboard API |
| `messages.py` | LLM-generated board messages (pre-formatted 3×15) |
| `scheduler.py` | APScheduler jobs, `rebuild_jobs()`, `upcoming()` |
| `family.py` | Load/save `family.json`, birthday helpers |
| `tools.py` | LLM tool definitions + dispatch (weather, time, Plex) |

## Singleton wiring
`board.client`, `messages.llm_client`, and `messages.model` are set at startup in `main.py::startup()`. They are `None` at import time — don't call message generation or board sends before startup completes.

## Adding a new scheduled message
1. Add a config block to `family.json` under `schedule`
2. Add the job to `scheduler.py::rebuild_jobs()` following the existing pattern
3. Add a message function to `messages.py` if needed
4. Optionally add a quick-send button in `frontend/index.html`

## Adding a new LLM tool
1. Add a definition to `TOOL_DEFINITIONS` in `tools.py`
2. Write an async `_your_tool()` implementation
3. Register it in `dispatch_tool()`
That's it — the chat loop in `main.py` handles tool execution automatically.

## Family config
`family.json` lives at the **project root** (not inside `backend/`). Loaded by `family.py`. Editable at runtime via `PUT /api/family` — triggers `scheduler.rebuild_jobs()` immediately.

## Environment variables
All in `.env` at project root. See `.env.example`.
- `VESTABOARD_TOKEN` — required for board sends
- `LLM_BASE_URL` — LLM endpoint, defaults to `http://localhost:11434/v1` (Ollama)
- `LLM_API_KEY` — defaults to `none`
- `MODEL` — defaults to `NousResearch/Hermes-4.3-36B`
- `PLEX_TOKEN` + `PLEX_URL` — required for Plex tools
- `VESTABOARD_API_URL` — defaults to `https://rw.vestaboard.com/`

## Running locally
```bash
# Terminal 1 — start your LLM (Ollama example)
ollama serve

# Terminal 2 — backend (serves frontend too)
cd backend
uvicorn main:app --host 0.0.0.0 --port 3000 --reload
```

## Git workflow
`main` is protected — never push directly. All changes go through PRs.

```
feature branch → PR → develop → (when ready) PR → main
```

```bash
# Start a new feature
git checkout develop
git checkout -b feature/my-feature

# Push and open a PR into develop
git push -u origin feature/my-feature
gh pr create --base develop

# When ready to release, PR develop into main
gh pr create --base main --head develop
```

`develop` is the active working branch and is always up to date.
`main` only moves forward intentionally as a release.

## Frontend
Single file: `frontend/index.html`. No framework, no build step. The FastAPI app serves it as static files. Edit and reload — uvicorn's `--reload` picks up Python changes; browser refresh picks up HTML/JS changes.
