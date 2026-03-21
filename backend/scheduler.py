"""
APScheduler jobs for family board messages.
Jobs are rebuilt whenever the family config changes.
"""

from __future__ import annotations

import logging
from datetime import datetime

import pytz
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

import board
import family as fam
import messages
from tools import _get_plex_recently_added

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def _tz(family: dict) -> pytz.BaseTzInfo:
    return pytz.timezone(family.get("timezone", "UTC"))


def _is_birthday_active() -> bool:
    return bool(fam.birthdays_today(fam.load()))


async def _run(msg_fn, *args):
    """Generate a message and enqueue it on the board. Handles text or character arrays."""
    if _is_birthday_active():
        logger.info("Skipping %s — birthday mode active", msg_fn.__name__)
        return
    logger.info("Scheduler firing: %s", msg_fn.__name__)
    result = await msg_fn(*args)
    if isinstance(result, list):
        await board.enqueue_characters(result)
    else:
        await board.enqueue(result)


def _cron(time_str: str, tz, weekdays_only: bool = False, days: list[str] | None = None) -> CronTrigger:
    hour, minute = map(int, time_str.split(":"))
    if days:
        dow = ",".join(days)
    elif weekdays_only:
        dow = "mon-fri"
    else:
        dow = "*"
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
            _run, _cron(cfg["time"], tz, days=cfg.get("days")),
            args=[messages.morning, data],
            id="family_morning", replace_existing=True,
            name=f"Good morning · {cfg['time']}",
        )

    # Homework
    cfg = schedule.get("homework", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _run, _cron(cfg["time"], tz, weekdays_only=cfg.get("weekdays_only", True), days=cfg.get("days")),
            args=[messages.homework, data],
            id="family_homework", replace_existing=True,
            name=f"Homework reminder · {cfg['time']} (weekdays)",
        )

    # Dinner
    cfg = schedule.get("dinner", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _run, _cron(cfg["time"], tz, days=cfg.get("days")),
            args=[messages.dinner, data],
            id="family_dinner", replace_existing=True,
            name=f"Dinner idea · {cfg['time']}",
        )

    # Bedtime
    cfg = schedule.get("bedtime", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _run, _cron(cfg["time"], tz, days=cfg.get("days")),
            args=[messages.bedtime, data],
            id="family_bedtime", replace_existing=True,
            name=f"Bedtime · {cfg['time']}",
        )

    # Plex recommendation
    cfg = schedule.get("plex", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _plex_recommendation, _cron(cfg["time"], tz, weekdays_only=cfg.get("weekdays_only", True), days=cfg.get("days")),
            id="family_plex", replace_existing=True,
            name=f"Plex pick · {cfg['time']}{'  (weekdays)' if cfg.get('weekdays_only') else ''}",
        )

    # Weather cities
    cfg = schedule.get("weather", {})
    if cfg.get("enabled"):
        cities = data.get("weather_cities", [])
        if cities:
            scheduler.add_job(
                _run, _cron(cfg["time"], tz, days=cfg.get("days")),
                args=[messages.weather_board, cities],
                id="family_weather", replace_existing=True,
                name=f"Weather · {cfg['time']}",
            )

    # Word of the day
    cfg = schedule.get("word_of_the_day", {})
    if cfg.get("enabled"):
        language = data.get("word_of_the_day_language", "Tagalog")
        colors   = cfg.get("colors", False)
        scheduler.add_job(
            _run, _cron(cfg["time"], tz, days=cfg.get("days")),
            args=[messages.word_of_the_day, language, colors],
            id="family_word_of_the_day", replace_existing=True,
            name=f"Word of the day · {cfg['time']}",
        )

    # Board art — fixed schedule (from schedule block)
    cfg = schedule.get("board_art", {})
    if cfg.get("enabled"):
        scheduler.add_job(
            _board_art,
            _cron(cfg["time"], tz, weekdays_only=cfg.get("weekdays_only", False)),
            id="family_board_art_scheduled", replace_existing=True,
            name=f"Board art · {cfg['time']}{'  (weekdays)' if cfg.get('weekdays_only') else ''}",
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
            args=[entry["prompt"], entry.get("window"), tz, entry.get("days")],
            id=f"family_random_{msg_id}", replace_existing=True,
            name=f"{entry.get('name', msg_id)} · every ~{interval_h}h",
        )

    # Birthday messages — interval throughout the day (07:00–21:30 enforced inside handler)
    bday_cfg   = schedule.get("birthday", {})
    interval_h = bday_cfg.get("interval_hours", 2)
    scheduler.add_job(
        _check_birthdays,
        IntervalTrigger(hours=interval_h, jitter=300, timezone=tz),
        id="family_birthday_check", replace_existing=True,
        name=f"Birthday check · every ~{interval_h}h",
    )


async def _from_prompt(prompt: str, window=None, tz=None, days=None):
    if _is_birthday_active():
        logger.info("Skipping random message — birthday mode active")
        return
    now     = datetime.now(tz or pytz.utc)
    now_str = now.strftime("%H:%M")
    dow     = now.strftime("%a").lower()  # mon, tue, wed...

    # Per-entry day-of-week check
    if days and dow not in [d.lower() for d in days]:
        logger.info("Skipping random message — not in days %s (today %s)", days, dow)
        return

    # Per-entry window check
    if window:
        if not (window[0] <= now_str < window[1]):
            logger.info("Skipping random message — outside window %s–%s (now %s)", window[0], window[1], now_str)
            return

    # Global quiet hours check
    data  = fam.load()
    quiet = data.get("quiet_hours")
    if quiet and quiet.get("enabled"):
        start, end = quiet["start"], quiet["end"]
        if start <= end:
            in_quiet = start <= now_str < end
        else:
            in_quiet = now_str >= start or now_str < end
        if in_quiet:
            logger.info("Skipping random message — quiet hours %s–%s (now %s)", start, end, now_str)
            return

    text = await messages.from_prompt(prompt)
    await board.enqueue(text)


async def _board_art():
    if _is_birthday_active():
        logger.info("Skipping board art — birthday mode active")
        return
    rows = messages.board_art()
    await board.enqueue_characters(rows)


async def _plex_recommendation():
    if _is_birthday_active():
        logger.info("Skipping Plex recommendation — birthday mode active")
        return
    import json as _json
    raw   = await _get_plex_recently_added(limit=5)
    items = _json.loads(raw).get("recently_added", [])
    text  = await messages.plex_pick(items)
    await board.enqueue(text)


async def _check_birthdays():
    data = fam.load()
    tz   = _tz(data)
    now  = datetime.now(tz)
    now_str = now.strftime("%H:%M")

    bday_cfg = data.get("schedule", {}).get("birthday", {})
    start    = bday_cfg.get("start", "07:00")
    end      = bday_cfg.get("end", "21:30")
    if not (start <= now_str < end):
        logger.info("Birthday check — outside window %s–%s (now %s)", start, end, now_str)
        return

    today_bdays = fam.birthdays_today(data)
    if not today_bdays:
        return

    logger.info("Birthday mode active: %s", today_bdays)
    for name in today_bdays:
        chars = await messages.birthday(name, data)
        await board.enqueue_characters(chars)


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
