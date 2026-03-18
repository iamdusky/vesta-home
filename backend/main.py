import asyncio
import json
import os
import pathlib

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from openai import AsyncOpenAI
from pydantic import BaseModel

import board
import family as fam
import messages
import scheduler as sched
from tools import TOOL_DEFINITIONS, dispatch_tool, _get_plex_recently_added
from vestaboard import VestaboardClient

load_dotenv()

VLLM_BASE_URL    = os.getenv("LLM_BASE_URL", os.getenv("VLLM_BASE_URL", "http://localhost:11434/v1"))
VLLM_API_KEY     = os.getenv("LLM_API_KEY",  os.getenv("VLLM_API_KEY",  "none"))
MODEL            = os.getenv("MODEL", "NousResearch/Hermes-4.3-36B")
VESTABOARD_TOKEN   = os.getenv("VESTABOARD_TOKEN", "")
VESTABOARD_API_URL = os.getenv("VESTABOARD_API_URL", "https://rw.vestaboard.com/")

def _build_system_prompt() -> str:
    try:
        data     = fam.load()
        location = data.get("location", "")
        tz       = data.get("timezone", "")
        location_line = f"\nThe family is located in {location} ({tz}). Use this as the default location for weather unless the user specifies otherwise." if location else ""
    except Exception:
        location_line = ""
    return f"""You are a concise, helpful family assistant. You have access to tools for weather, time, and Plex.{location_line}

Respond naturally in plain conversational text. Do not use markdown, bullet points, or emoji.
Do not describe, preview, or explain Vestaboard formatting — the UI handles that separately.
Do not pretend to send anything to the board. If the user wants to send something, they will use the Send to Board button."""


# ── App setup ──────────────────────────────────────────────────────────────
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

llm_client = AsyncOpenAI(base_url=VLLM_BASE_URL, api_key=VLLM_API_KEY)


@app.on_event("startup")
async def startup():
    # Wire up singletons
    board.client      = VestaboardClient(token=VESTABOARD_TOKEN, api_url=VESTABOARD_API_URL)
    messages.llm_client = llm_client
    messages.model      = MODEL

    # Start board worker
    asyncio.create_task(board.worker())

    # Start scheduler
    sched.scheduler.start()
    sched.rebuild_jobs()


# ── Models ─────────────────────────────────────────────────────────────────
class ChatMessage(BaseModel):
    role: str
    content: str

class ChatRequest(BaseModel):
    messages: list[ChatMessage]

class BoardRequest(BaseModel):
    text: str

class BoardFormatRequest(BaseModel):
    text: str

class QuickSendRequest(BaseModel):
    type: str          # morning | homework | dinner | bedtime | birthday
    name: str = ""     # for birthday


# ── Health ─────────────────────────────────────────────────────────────────
@app.get("/api/health")
async def health():
    try:
        async with httpx.AsyncClient(timeout=3.0) as http:
            r = await http.get(f"{VLLM_BASE_URL}/models")
        active = r.json().get("data", [{}])[0].get("id", MODEL)
    except Exception:
        active = MODEL
    return {"status": "ok", "model": active}


# ── Board status & queue ───────────────────────────────────────────────────
@app.get("/api/board-status")
async def board_status():
    return board.queue_status()

@app.get("/api/board-status/{job_id}")
async def board_job_status(job_id: str):
    status = board.get_job_status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return status


# ── Format & send ──────────────────────────────────────────────────────────
@app.post("/api/board-format")
async def board_format(request: BoardFormatRequest):
    formatted = await messages.custom(request.text)
    return {"formatted": formatted}

@app.post("/api/send-to-board")
async def send_to_board(request: BoardRequest):
    if not VESTABOARD_TOKEN:
        raise HTTPException(status_code=500, detail="VESTABOARD_TOKEN not configured")
    return await board.enqueue(request.text)


# ── Quick send ─────────────────────────────────────────────────────────────
@app.post("/api/quick-send")
async def quick_send(request: QuickSendRequest):
    data = fam.load()
    async def _plex_pick():
        import json as _json
        raw    = await _get_plex_recently_added(limit=5)
        items  = _json.loads(raw).get("recently_added", [])
        return await messages.plex_pick(items)

    # board_art enqueues characters directly and returns a sentinel
    if request.type == "board_art":
        rows   = messages.board_art()
        result = await board.enqueue_characters(rows)
        return {**result, "preview": "[color pattern]"}

    handlers = {
        "morning":  lambda: messages.morning(data),
        "homework": lambda: messages.homework(data),
        "dinner":   lambda: messages.dinner(data),
        "bedtime":  lambda: messages.bedtime(data),
        "birthday": lambda: messages.birthday(request.name, data),
        "plex":     _plex_pick,
    }

    # Built-in handler
    fn = handlers.get(request.type)

    # Fall back to random_messages entries by id
    if fn is None:
        entry = next((e for e in data.get("random_messages", []) if e["id"] == request.type), None)
        if entry:
            fn = lambda: messages.from_prompt(entry["prompt"])

    if fn is None:
        raise HTTPException(status_code=400, detail=f"Unknown type: {request.type}")
    result = await fn()
    if isinstance(result, list):
        return {**(await board.enqueue_characters(result)), "preview": "[decorated]"}
    return {**(await board.enqueue(result)), "preview": result}


# ── Family config ──────────────────────────────────────────────────────────
@app.get("/api/family")
async def get_family():
    data = fam.load()
    data["upcoming_birthdays"] = fam.upcoming_birthdays(data)
    return data

@app.put("/api/family")
async def update_family(data: dict):
    fam.save(data)
    sched.rebuild_jobs()   # apply new schedule times immediately
    return {"ok": True}


# ── Schedule ───────────────────────────────────────────────────────────────
@app.get("/api/schedule")
async def get_schedule():
    return {"jobs": sched.upcoming()}


# ── Chat ───────────────────────────────────────────────────────────────────
@app.post("/api/chat")
async def chat(request: ChatRequest):
    msgs = [{"role": "system", "content": _build_system_prompt()}]
    msgs += [{"role": m.role if m.role != "ai" else "assistant", "content": m.content}
             for m in request.messages]

    async def generate():
        loop_msgs = list(msgs)
        while True:
            resp = await llm_client.chat.completions.create(
                model=MODEL,
                messages=loop_msgs,
                tools=TOOL_DEFINITIONS,
                tool_choice="auto",
                stream=False,
            )
            choice = resp.choices[0]

            if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
                loop_msgs.append(choice.message)
                for tc in choice.message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments)
                    except json.JSONDecodeError:
                        args = {}
                    result = await dispatch_tool(tc.function.name, args)
                    loop_msgs.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                continue

            stream = await llm_client.chat.completions.create(
                model=MODEL, messages=loop_msgs, stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta
                if delta.content:
                    yield f"data: {json.dumps({'content': delta.content})}\n\n"
            yield "data: [DONE]\n\n"
            break

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Frontend ───────────────────────────────────────────────────────────────
_FRONTEND = pathlib.Path(__file__).parent.parent / "frontend"
app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")
