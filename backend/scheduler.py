"""
APScheduler jobs for family board messages.
Jobs are rebuilt whenever the family config changes.
"""

from __future__ import annotations

from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import board
import family as fam
import messages
from tools import _get_plex_recently_added

scheduler = AsyncIOScheduler()


def _tz(family: dict) -> pytz.BaseTzInfo:
    return pytz.timezone(family.get("timezone", "UTC"))


async def _run(msg_fn, *args):
    """Generate a message and enqueue it on the board. Handles text or character arrays."""
    result = await msg_fn(*args)
    if isinstance(result, list):
        await board.enqueue_characters(result)
    else:
        await board.enqueue(result)


def _cron(time_str: str, tz, weekdays_only: bool = False) -> CronTrigger:
    hour, minute = map(int, time_str.split(":"))
    dow = "mon-fri" if weekdays_only else "*"
    return CronTrigger(hour=hour, minute=minute, day_of_week=dow, timezone=tz)


def rebuild_jobs():
    """Remove all family jobs and recreate them from current config."""
    for job in scheduler.get_jobs():
        if job.id.startswith("family_"):
            job.remove()

    data     = fam.load()
    tz       = _tz(data)
    schedule = data.get("schedule", {})

    # Morning
    cfg = schedule.get("morning", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _run, _cron(cfg["time"], tz),
            args=[messages.morning, data],
            id="family_morning", replace_existing=True,
            name=f"Good morning · {cfg['time']}",
        )

    # Homework
    cfg = schedule.get("homework", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _run, _cron(cfg["time"], tz, weekdays_only=cfg.get("weekdays_only", True)),
            args=[messages.homework, data],
            id="family_homework", replace_existing=True,
            name=f"Homework reminder · {cfg['time']} (weekdays)",
        )

    # Dinner
    cfg = schedule.get("dinner", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _run, _cron(cfg["time"], tz),
            args=[messages.dinner, data],
            id="family_dinner", replace_existing=True,
            name=f"Dinner idea · {cfg['time']}",
        )

    # Bedtime
    cfg = schedule.get("bedtime", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _run, _cron(cfg["time"], tz),
            args=[messages.bedtime, data],
            id="family_bedtime", replace_existing=True,
            name=f"Bedtime · {cfg['time']}",
        )

    # Plex recommendation
    cfg = schedule.get("plex", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _plex_recommendation, _cron(cfg["time"], tz, weekdays_only=cfg.get("weekdays_only", True)),
            id="family_plex", replace_existing=True,
            name=f"Plex pick · {cfg['time']}{'  (weekdays)' if cfg.get('weekdays_only') else ''}",
        )

    # Board art — random interval (special: uses character codes, no prompt)
    cfg = data.get("board_art", {})
    if cfg.get("enabled"):
        interval_h = cfg.get("interval_hours", 3)
        jitter_s   = int(cfg.get("jitter_hours", 2) * 3600)
        scheduler.add_job(
            _board_art,
            IntervalTrigger(hours=interval_h, jitter=jitter_s, timezone=tz),
            id="family_board_art", replace_existing=True,
            name=f"Board art · every ~{interval_h}h",
        )

    # Generic random messages — driven entirely by family.json
    for entry in data.get("random_messages", []):
        if not entry.get("enabled", True):
            continue
        msg_id     = entry["id"]
        interval_h = entry.get("interval_hours", 4)
        jitter_s   = int(entry.get("jitter_hours", 2) * 3600)
        scheduler.add_job(
            _from_prompt,
            IntervalTrigger(hours=interval_h, jitter=jitter_s, timezone=tz),
            args=[entry["prompt"], entry.get("window"), tz],
            id=f"family_random_{msg_id}", replace_existing=True,
            name=f"{entry.get('name', msg_id)} · every ~{interval_h}h",
        )

    # Birthday check — runs at midnight daily
    scheduler.add_job(
        _check_birthdays, CronTrigger(hour=0, minute=0, timezone=tz),
        id="family_birthday_check", replace_existing=True,
        name="Birthday check · 00:00",
    )


async def _from_prompt(prompt: str, window=None, tz=None):
    if window:
        now = datetime.now(tz or pytz.utc).strftime("%H:%M")
        if not (window[0] <= now < window[1]):
            return
    text = await messages.from_prompt(prompt)
    await board.enqueue(text)


async def _board_art():
    rows = messages.board_art()
    await board.enqueue_characters(rows)


async def _plex_recommendation():
    import json as _json
    raw   = await _get_plex_recently_added(limit=5)
    items = _json.loads(raw).get("recently_added", [])
    text  = await messages.plex_pick(items)
    await board.enqueue(text)


async def _check_birthdays():
    data     = fam.load()
    today_bdays = fam.birthdays_today(data)
    for name in today_bdays:
        text = await messages.birthday(name, data)
        await board.enqueue(text)


def upcoming(limit: int = 8) -> list[dict]:
    """Return the next `limit` scheduled job fire times."""
    now    = datetime.now(pytz.utc)
    result = []
    for job in scheduler.get_jobs():
        if not job.id.startswith("family_"):
            continue
        next_run = job.next_run_time
        if next_run is None:
            continue
        # Check if this is a windowed job that will skip at next_run
        will_skip = False
        window    = None
        if getattr(job.func, "__name__", "") == "_from_prompt" and len(job.args) > 1:
            window = job.args[1]
            if window:
                next_time = next_run.astimezone(pytz.utc).strftime("%H:%M")
                # Convert to job's timezone for accurate comparison
                tz_info = job.args[2] if len(job.args) > 2 else pytz.utc
                next_time = next_run.astimezone(tz_info).strftime("%H:%M")
                will_skip = not (window[0] <= next_time < window[1])

        result.append({
            "id":        job.id,
            "name":      job.name,
            "next_run":  next_run.isoformat(),
            "will_skip": will_skip,
            "window":    window,
        })
    result.sort(key=lambda x: x["next_run"])
    return result[:limit]
