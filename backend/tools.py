"""
Tool definitions and dispatch for the chatbot.
Add new tools here — they'll automatically be available to the LLM.
"""

import json
import os
from datetime import datetime, timezone

import httpx

def _plex_url()   -> str: return os.getenv("PLEX_URL",   "")
def _plex_token() -> str: return os.getenv("PLEX_TOKEN", "")

# ── Tool definitions (OpenAI function-calling format) ──────────────────────
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": (
                "Get the current weather and short forecast for a location. "
                "Use this when the user asks about weather conditions."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name, e.g. 'San Francisco' or 'London, UK'",
                    },
                    "units": {
                        "type": "string",
                        "enum": ["metric", "imperial"],
                        "description": "Temperature units. Default: metric (Celsius).",
                    },
                },
                "required": ["location"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plex_recently_added",
            "description": (
                "Get recently added movies and TV shows from the local Plex media server. "
                "Use this when the user asks what's new on Plex, wants a watch recommendation, "
                "or asks what was recently added."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Number of items to return. Default: 12.",
                    },
                    "media_type": {
                        "type": "string",
                        "enum": ["all", "movie", "show"],
                        "description": "Filter by type. Default: all.",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_plex_on_deck",
            "description": (
                "Get what's currently in progress / up next on Plex (On Deck). "
                "Use this when the user asks what they were watching or what to continue."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": "Get the current UTC date and time.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
]


# ── Dispatcher ─────────────────────────────────────────────────────────────
async def dispatch_tool(name: str, args: dict) -> str:
    handlers = {
        "get_weather":             _get_weather,
        "get_current_time":        _get_current_time,
        "get_plex_recently_added": _get_plex_recently_added,
        "get_plex_on_deck":        _get_plex_on_deck,
    }
    handler = handlers.get(name)
    if not handler:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return await handler(**args)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ── Tool implementations ───────────────────────────────────────────────────
async def _get_weather(location: str, units: str = "metric") -> str:
    """
    Uses wttr.in JSON API — no API key required.
    Falls back gracefully on network errors.
    """
    fmt = "m" if units == "metric" else "u"
    url = f"https://wttr.in/{httpx.URL(location)}?format=j1&{fmt}"

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        data = r.json()

    current = data["current_condition"][0]
    area    = data["nearest_area"][0]
    city    = area["areaName"][0]["value"]
    country = area["country"][0]["value"]

    temp_c  = int(current["temp_C"])
    temp_f  = int(current["temp_F"])
    feels_c = int(current["FeelsLikeC"])
    feels_f = int(current["FeelsLikeF"])
    desc    = current["weatherDesc"][0]["value"]
    humidity = current["humidity"]
    wind_kmph = current["windspeedKmph"]
    wind_mph  = current["windspeedMiles"]

    if units == "imperial":
        temp_str   = f"{temp_f}°F"
        feels_str  = f"{feels_f}°F"
        wind_str   = f"{wind_mph} mph"
    else:
        temp_str   = f"{temp_c}°C"
        feels_str  = f"{feels_c}°C"
        wind_str   = f"{wind_kmph} km/h"

    # 3-day forecast
    forecast_lines = []
    for day in data.get("weather", [])[:3]:
        date      = day["date"]
        max_c, min_c = int(day["maxtempC"]), int(day["mintempC"])
        max_f, min_f = int(day["maxtempF"]), int(day["mintempF"])
        day_desc  = day["hourly"][4]["weatherDesc"][0]["value"]  # midday
        if units == "imperial":
            forecast_lines.append(f"  {date}: {min_f}–{max_f}°F, {day_desc}")
        else:
            forecast_lines.append(f"  {date}: {min_c}–{max_c}°C, {day_desc}")

    result = {
        "location": f"{city}, {country}",
        "condition": desc,
        "temperature": temp_str,
        "feels_like": feels_str,
        "humidity": f"{humidity}%",
        "wind": wind_str,
        "3_day_forecast": forecast_lines,
    }
    return json.dumps(result)


async def _get_current_time() -> str:
    now = datetime.now(timezone.utc)
    return json.dumps({
        "utc": now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        "iso": now.isoformat(),
    })


def _plex_headers() -> dict:
    return {
        "X-Plex-Token": _plex_token(),
        "Accept": "application/json",
    }


def _extract_item(item: dict) -> dict:
    """Normalize a Plex metadata item into a clean dict."""
    media_type = item.get("type", "")
    if media_type == "episode":
        title    = f"{item.get('grandparentTitle', '')} — {item.get('title', '')}"
        subtitle = f"S{item.get('parentIndex', '?')}E{item.get('index', '?')}"
    elif media_type == "season":
        show     = item.get("parentTitle", item.get("grandparentTitle", ""))
        title    = show if show else item.get("title", "Unknown")
        subtitle = item.get("title", "")  # "Season 2"
    else:
        title    = item.get("title", "Unknown")
        subtitle = str(item.get("year", ""))

    return {
        "type":    media_type,
        "title":   title,
        "detail":  subtitle,
        "summary": item.get("summary", "")[:200],
        "rating":  item.get("rating"),
        "added":   item.get("addedAt"),
    }


async def _get_plex_recently_added(limit: int = 12, media_type: str = "all") -> str:
    if not _plex_token():
        return json.dumps({"error": "PLEX_TOKEN not configured"})

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(
            f"{_plex_url()}/library/recentlyAdded",
            headers=_plex_headers(),
            params={"X-Plex-Container-Size": limit * 2},  # fetch extra to allow filtering
        )
        r.raise_for_status()

    items = r.json().get("MediaContainer", {}).get("Metadata", [])

    if media_type != "all":
        # "show" type in recently added appears as "episode" or "season"
        type_map = {"movie": ["movie"], "show": ["episode", "season", "show"]}
        allowed  = type_map.get(media_type, [])
        items    = [i for i in items if i.get("type") in allowed]

    items = items[:limit]
    return json.dumps({
        "recently_added": [_extract_item(i) for i in items],
        "count": len(items),
    })


async def _get_plex_on_deck() -> str:
    if not _plex_token():
        return json.dumps({"error": "PLEX_TOKEN not configured"})

    async with httpx.AsyncClient(timeout=8.0) as client:
        r = await client.get(
            f"{_plex_url()}/library/onDeck",
            headers=_plex_headers(),
        )
        r.raise_for_status()

    items = r.json().get("MediaContainer", {}).get("Metadata", [])
    return json.dumps({
        "on_deck": [_extract_item(i) for i in items[:8]],
        "count":   len(items),
    })
