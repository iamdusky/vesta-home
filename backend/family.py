"""
Loads and saves family.json. Provides birthday helpers.
"""

import json
import pathlib
from datetime import date

FAMILY_FILE = pathlib.Path(__file__).parent.parent / "family.json"


def load() -> dict:
    with open(FAMILY_FILE) as f:
        return json.load(f)


def save(data: dict):
    with open(FAMILY_FILE, "w") as f:
        json.dump(data, f, indent=2)


def birthdays_today(data: dict) -> list[str]:
    today = date.today().strftime("%m-%d")
    return [m["name"] for m in data["members"] if m.get("birthday") == today]


def upcoming_birthdays(data: dict, days: int = 7) -> list[dict]:
    """Returns members with birthdays in the next `days` days."""
    today  = date.today()
    result = []
    for m in data.get("members", []):
        bday_str = m.get("birthday")
        if not bday_str:
            continue
        month, day = map(int, bday_str.split("-"))
        try:
            bday = date(today.year, month, day)
        except ValueError:
            continue
        if bday < today:
            bday = date(today.year + 1, month, day)
        delta = (bday - today).days
        if 0 <= delta <= days:
            result.append({"name": m["name"], "birthday": bday_str, "days_away": delta})
    return sorted(result, key=lambda x: x["days_away"])
