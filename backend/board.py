"""
Board queue singleton — shared between main.py and scheduler.py.
Owns the VestaboardClient, the asyncio queue, and the background worker.
"""

import asyncio
import logging
import time
import uuid

from vestaboard import VestaboardClient

logger = logging.getLogger(__name__)

RATE_LIMIT = 15  # seconds between sends

_queue: asyncio.Queue  = asyncio.Queue()
_jobs:  dict[str, dict] = {}
_last_send: float       = 0.0

# Initialized by main.py at startup
client: VestaboardClient | None = None


async def worker():
    global _last_send
    while True:
        job = await _queue.get()
        try:
            elapsed = time.monotonic() - _last_send
            wait    = RATE_LIMIT - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            if "characters" in job:
                await client.send_characters(job["characters"])
            else:
                await client.send(job["text"])
            _last_send = time.monotonic()
            job["status"] = "sent"
            logger.info("Board send OK — %s", job.get("text", "[characters]")[:40])
        except Exception as e:
            job["status"] = "failed"
            job["error"]  = str(e)
            logger.error("Board send FAILED — %s", e)
        finally:
            _queue.task_done()


async def enqueue_characters(rows: list[list[int]]) -> dict:
    """Queue a raw character-code art frame."""
    job_id = str(uuid.uuid4())
    job    = {"id": job_id, "characters": rows, "status": "pending", "error": None}
    _jobs[job_id] = job
    await _queue.put(job)

    elapsed  = time.monotonic() - _last_send
    next_in  = max(0.0, RATE_LIMIT - elapsed)
    position = _queue.qsize() - 1
    wait     = round(next_in + position * RATE_LIMIT, 1)
    return {"job_id": job_id, "position": position, "wait_seconds": wait}


async def enqueue(text: str) -> dict:
    job_id = str(uuid.uuid4())
    job    = {"id": job_id, "text": text, "status": "pending", "error": None}
    _jobs[job_id] = job
    await _queue.put(job)

    elapsed  = time.monotonic() - _last_send
    next_in  = max(0.0, RATE_LIMIT - elapsed)
    position = _queue.qsize() - 1
    wait     = round(next_in + position * RATE_LIMIT, 1)
    return {"job_id": job_id, "position": position, "wait_seconds": wait}


def get_job_status(job_id: str) -> dict | None:
    job = _jobs.get(job_id)
    if not job:
        return None

    pending  = [j for j in _jobs.values() if j["status"] == "pending"]
    try:
        position = next(i for i, j in enumerate(pending) if j["id"] == job_id)
    except StopIteration:
        position = 0

    elapsed  = time.monotonic() - _last_send
    next_in  = max(0.0, RATE_LIMIT - elapsed)
    wait     = round(next_in + position * RATE_LIMIT, 1)
    return {
        "status":       job["status"],
        "position":     position,
        "wait_seconds": wait if job["status"] == "pending" else 0,
        "error":        job.get("error"),
    }


def queue_status() -> dict:
    elapsed = time.monotonic() - _last_send
    return {
        "queue_length": _queue.qsize(),
        "next_send_in": round(max(0.0, RATE_LIMIT - elapsed), 1),
    }
