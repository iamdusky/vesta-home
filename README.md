# VESTA

A local family chatbot connected to a **Vestaboard Note** flip-board display. Chat with an LLM, send answers to the board, get daily scheduled messages, Plex recommendations, and weather — all on your local network.

```
┌───────────────────────────────┐
│  GOOD MORNING!                │
│  HAPPY FRIDAY                 │
│  SUSHI TONIGHT?               │
└───────────────────────────────┘
        Vestaboard Note (15×3)
```

## Features

- **Chat** — streaming LLM responses with tool use (weather, time, Plex)
- **Voice input** — Web Speech API, works on mobile and desktop
- **Send to board** — any AI response can be formatted and sent to the Vestaboard in one tap
- **Scheduled messages** — good morning, homework reminders, dinner ideas, bedtime, Plex picks
- **Random messages** — dad jokes, fun facts, creativity boosts on randomized intervals with jitter
- **Color tiles** — birthday messages and board art use Vestaboard's color character codes
- **Birthday detection** — posts a message to the board on family members' birthdays
- **Family panel** — quick-send buttons and upcoming schedule at a glance
- **Multi-user queue** — multiple people can send to the board; messages are queued and rate-limited automatically

## Requirements

- Python 3.11+
- An LLM backend (Ollama, OpenAI API, or vLLM — see below)
- Vestaboard Note with a [Read/Write API token](https://web.vestaboard.com)
- Plex Media Server (optional, for Plex recommendations)

## Quick start

### 1. Get a Vestaboard Read/Write API token

Log in at [web.vestaboard.com](https://web.vestaboard.com) → Settings → API → Create token.

### 2. Set up an LLM

**Ollama** (recommended — runs on any Mac, Linux, or Windows machine):

```bash
# Install from https://ollama.com, then:
ollama serve
ollama pull llama3.2
```

**OpenAI API** — no local setup needed, just add your API key to `.env`.

**vLLM** — for local GPUs with larger models. See [Advanced setup](#advanced-vllm-setup).

### 3. Configure

```bash
cp family.example.json family.json   # edit with your family's details
cp .env.example .env                 # edit with your tokens and LLM choice
```

Edit `family.json` — set your family members, birthdays, timezone, dinner preferences, and schedule times. All fields are documented in the example file.

Edit `.env` — set `VESTABOARD_TOKEN` and your LLM backend. Ollama is pre-configured as the default.

### 4. Run

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 3000 --reload
```

Open `http://localhost:3000` — or `http://<your-machine-ip>:3000` from any device on your local network.

## Family config (`family.json`)

Copy `family.example.json` to `family.json` and edit it. The file is excluded from git (it may contain personal information).

```json
{
  "family_name": "The Smiths",
  "location": "San Francisco",
  "timezone": "America/Los_Angeles",
  "members": [
    { "name": "Mom",  "birthday": "04-15" },
    { "name": "Dad",  "birthday": "10-01" }
  ],
  "dinner_preferences": ["sushi", "tacos", "pasta", "pizza"],
  "schedule": {
    "morning":  { "enabled": true, "time": "07:30" },
    "homework": { "enabled": true, "time": "16:00", "weekdays_only": true },
    "dinner":   { "enabled": true, "time": "17:30" },
    "bedtime":  { "enabled": true, "time": "20:30" },
    "plex":     { "enabled": false, "time": "20:00", "weekdays_only": true }
  },
  "board_art": { "enabled": true, "interval_hours": 3, "jitter_hours": 2 },
  "random_messages": [
    {
      "id": "dad_joke",
      "name": "Dad joke",
      "enabled": true,
      "interval_hours": 4,
      "jitter_hours": 2,
      "prompt": "Write a dad joke..."
    }
  ]
}
```

Changes to `family.json` take effect immediately — no restart needed (the UI's Save button calls `PUT /api/family`).

### Adding custom random messages

Add an entry to `random_messages` in `family.json`. No code changes needed:

```json
{
  "id": "trivia",
  "name": "Trivia question",
  "enabled": true,
  "interval_hours": 8,
  "jitter_hours": 3,
  "prompt": "Write a trivia question for a family flip-board. Short words only, max 15 chars per line."
}
```

## Scheduled messages

| Message | Default time | Days |
|---|---|---|
| Good morning | 7:30 AM | Daily |
| Homework reminder | 4:00 PM | Weekdays |
| Dinner idea | 5:30 PM | Daily |
| Bedtime | 8:30 PM | Daily |
| Plex pick | 8:00 PM | Weekdays (if enabled) |
| Birthday check | Midnight | Daily |

Interval messages (board art, dad jokes, fun facts) fire on randomized schedules with jitter to keep things surprising.

The LLM generates each message fresh — they're never the same twice.

## LLM tools

The chatbot can call these automatically during a conversation:

| Tool | Trigger example |
|---|---|
| `get_weather` | "What's the weather today?" |
| `get_current_time` | "What time is it?" |
| `get_plex_recently_added` | "What's new on Plex?" |
| `get_plex_on_deck` | "What were we watching?" |

Weather uses [wttr.in](https://wttr.in) — no API key required. The family's `location` field is used as the default.

## API endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/health` | Backend + LLM status |
| `POST` | `/api/chat` | Streaming chat (SSE) |
| `POST` | `/api/send-to-board` | Queue text for the board |
| `POST` | `/api/board-format` | Format text for 15×3 display |
| `GET` | `/api/board-status` | Queue length + next send ETA |
| `GET` | `/api/board-status/{job_id}` | Poll individual job |
| `POST` | `/api/quick-send` | Send a preset family message |
| `GET` | `/api/family` | Get family config + upcoming birthdays |
| `PUT` | `/api/family` | Update family config |
| `GET` | `/api/schedule` | Upcoming scheduled messages |

## Project structure

```
vestaboard/
├── family.json           # your family config — edit this (excluded from git)
├── family.example.json   # template to copy from
├── .env                  # secrets — excluded from git
├── .env.example          # template to copy from
├── docker-compose.yml    # optional: runs vLLM + backend in containers
├── backend/
│   ├── main.py           # FastAPI app + all endpoints
│   ├── board.py          # queue, rate limiter, board worker
│   ├── vestaboard.py     # Vestaboard API client
│   ├── messages.py       # LLM message generation (formats to 15×3)
│   ├── scheduler.py      # APScheduler jobs
│   ├── family.py         # family config + birthday helpers
│   ├── tools.py          # LLM tools (weather, time, Plex)
│   ├── requirements.txt
│   └── Dockerfile
└── frontend/
    └── index.html        # full UI — single file, no build step
```

## Adding a new LLM tool

Edit `backend/tools.py`:

1. Add a definition to `TOOL_DEFINITIONS`
2. Write an `async _your_tool()` function
3. Register it in `dispatch_tool()`

The chat loop handles execution automatically.

## Getting your Plex token

In the Plex web UI: Settings → Troubleshooting → Show Plex token. Or:

```bash
grep -o 'PlexOnlineToken="[^"]*"' \
  "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Preferences.xml"
```

## Advanced: vLLM setup

vLLM gives the best tool-call accuracy with larger models, but requires a GPU.

```bash
# Install vLLM and serve a model
pip install vllm
vllm serve NousResearch/Hermes-4.3-36B \
  --port 8000 \
  --enable-auto-tool-choice \
  --tool-call-parser hermes

# Or use Docker Compose (downloads model automatically):
docker compose --profile llm --profile backend up
```

Set in `.env`:
```env
LLM_BASE_URL=http://localhost:8000/v1
LLM_API_KEY=none
MODEL=NousResearch/Hermes-4.3-36B
```

**Model recommendations by hardware:**

| Model | VRAM | Notes |
|---|---|---|
| `llama3.2` (via Ollama) | 4 GB | Great for most uses |
| `NousResearch/Hermes-4.3-36B` | ~72 GB | Best tool use, requires large GPU |
| `Qwen/Qwen2.5-32B-Instruct` | ~65 GB | Strong tool use, good alternative |
| `hugging-quants/Meta-Llama-3.3-70B-Instruct-AWQ-INT4` | ~38 GB | Quantized 70B |

For Llama models, change `--tool-call-parser hermes` to `--tool-call-parser llama3_json` in the vLLM command.
