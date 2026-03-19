"""
LLM-generated board messages — all output is pre-formatted for 15×3.
"""

import json
import random
from datetime import date

from openai import AsyncOpenAI

# Injected by main.py at startup
llm_client: AsyncOpenAI | None = None
model: str = ""

BOARD_RULES = """\
Output EXACTLY 3 lines. Each line is AT MOST 15 characters. ALL CAPS.
No punctuation except spaces, hyphens, and exclamation marks.
Output only the 3 lines — no labels, quotes, or explanation.
Do not add leading or trailing spaces — write only the content.

The ruler below shows exactly 15 characters — never exceed it:
|||||||||||||||
123456789012345"""


# ── Character code map ────────────────────────────────────────────────────
# Letters A-Z: 1-26, Digits 1-9,0: 27-36
# Special chars, colors, and symbols
_CHAR_MAP: dict[str, int] = {
    **{chr(ord('A') + i): i + 1 for i in range(26)},
    **{'1':27,'2':28,'3':29,'4':30,'5':31,'6':32,'7':33,'8':34,'9':35,'0':36},
    '!':37, '-':43, '+':44, '&':45, '=':46, ':':48, '%':51, ',':52, '.':53, '?':55,
    ' ': 0,
}

# Inline tags for color tiles and symbols — use these in LLM prompts
# NOTE: heart code (57) can be verified by testing on your board
_TAG_MAP: dict[str, int] = {
    '[R]': 63,  # red tile
    '[O]': 64,  # orange tile
    '[Y]': 65,  # yellow tile
    '[G]': 66,  # green tile
    '[B]': 67,  # blue tile
    '[V]': 68,  # violet tile
    '[W]': 69,  # white tile
    '[_]':  0,  # blank/black tile
    '[H]': 57,  # heart ♥
}

_BOARD_TAG_RULES = """\
You may use these inline tags for colored tiles and symbols (each tag counts as 1 cell):
[R]=red [O]=orange [Y]=yellow [G]=green [B]=blue [V]=violet [W]=white [_]=blank [H]=heart
Regular letters and spaces work normally. Each line still max 15 cells total."""


def _parse_cells(line: str) -> list[int]:
    """Parse a line with inline tags into a list of character codes."""
    line = line.upper().strip()
    cells: list[int] = []
    j = 0
    while j < len(line):
        matched = False
        for tag, code in _TAG_MAP.items():
            if line[j:j + len(tag)] == tag:
                cells.append(code)
                j += len(tag)
                matched = True
                break
        if not matched:
            cells.append(_CHAR_MAP.get(line[j], 0))
            j += 1
    return cells


def build_chars(lines: list[str]) -> list[list[int]]:
    """Convert up to 3 lines of text (with inline tags) to a centered 3×15 character code array."""
    rows = []
    for i in range(3):
        line  = lines[i] if i < len(lines) else ""
        cells = _parse_cells(line)[:15]
        pad   = (15 - len(cells)) // 2
        row   = [0] * pad + cells + [0] * (15 - pad - len(cells))
        rows.append(row[:15])
    while len(rows) < 3:
        rows.append([0] * 15)
    return rows


def _enforce(raw: str) -> str:
    lines = raw.strip().splitlines()[:3]
    while len(lines) < 3:
        lines.append("")
    return "\n".join(line.upper()[:15] for line in lines)


async def _generate(prompt: str) -> str:
    resp = await llm_client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.8,
        max_tokens=64,
        stream=False,
    )
    return _enforce(resp.choices[0].message.content)


async def morning(family: dict) -> str:
    today     = date.today()
    day_name  = today.strftime("%A").upper()
    birthdays = [m["name"] for m in family["members"]
                 if m.get("birthday") == today.strftime("%m-%d")]

    bday_note = ""
    if birthdays:
        bday_note = f"Today is {birthdays[0]}'s birthday! Include that warmly."

    location = family.get("location", "")
    weather_hint = f"Location: {location}." if location else ""

    prompt = f"""\
Write a warm good morning message for the {family['family_name']} family to display on a flip-board.
Today is {day_name}. {bday_note} {weather_hint}
Be cheerful. Vary the style — sometimes the day name, sometimes motivation, sometimes just warmth.
Use very short words only.

{BOARD_RULES}

Good examples:
GOOD MORNING
HAPPY FRIDAY
MAKE IT COUNT
---
RISE AND SHINE
GREAT DAY AHEAD
YOU GOT THIS"""
    return await _generate(prompt)


async def homework(family: dict) -> str:
    members = family["members"]
    # Use homework flag if present; otherwise fall back to non-parents heuristic
    if any("homework" in m for m in members):
        kids = [m["name"] for m in members if m.get("homework", False)]
    else:
        kids = [m["name"] for m in members[2:]] if len(members) > 2 else [m["name"] for m in members]
    who = " AND ".join(n.upper() for n in kids) if kids else "KIDS"

    prompt = f"""\
Write a short homework reminder for a flip-board. Address: {who}.
Keep it brief and encouraging. Use short words only.

{BOARD_RULES}

Good examples (note how short each line is):
HOMEWORK TIME
{who[:15]}
LETS GO!

HEY {who[:11]}
TIME TO STUDY
YOU GOT THIS!"""
    return await _generate(prompt)


async def dinner(family: dict) -> str:
    prefs = family.get("dinner_preferences", [])
    pick  = random.choice(prefs) if prefs else "something delicious"
    day   = date.today().strftime("%A").upper()

    prompt = f"""\
Write a fun dinner suggestion for tonight on a flip-board. Tonight's idea: {pick}.
Make it sound exciting and appetizing. Today is {day}.
Examples of the vibe: "SUSHI TONIGHT?" / "TACO TUESDAY" / "PIZZA PARTY"
{BOARD_RULES}"""
    return await _generate(prompt)


async def bedtime(family: dict) -> str:
    schedule = family.get("schedule", {}).get("bedtime", {})
    time_str = schedule.get("time", "20:30")

    prompt = f"""\
Write a gentle bedtime message for a family flip-board.
Bedtime is around {time_str}. Keep it calm and warm. Use very short words only.
Sometimes remind the family to do their bedtime routine (brush teeth, wash face, etc).
Vary the style each time.

{BOARD_RULES}

Good examples (short words, fits the board):
LIGHTS OUT
SLEEP WELL
GOOD NIGHT
---
BRUSH YOUR TEETH
WASH YOUR FACE
SWEET DREAMS
---
TIME FOR BED
CLOSE YOUR EYES
DREAM BIG"""
    return await _generate(prompt)


async def word_of_the_day(language: str, colors: bool = False) -> str | list[list[int]]:
    color_rules = f"\n{_BOARD_TAG_RULES}\nUse color tiles to highlight the word or add flair." if colors else ""
    prompt = f"""\
Pick a common, useful {language} word to teach a family today.
Output exactly 3 lines:
  Line 1: the language name (e.g. {language.upper()})
  Line 2: the {language} word (romanized if non-Latin script, e.g. OHAYO not おはよ)
  Line 3: the English translation

Choose short words — each line must fit in 15 characters.
Vary the word each time (greetings, food, family, emotions, nature, numbers).
{color_rules}
{BOARD_RULES}"""
    raw = await _generate(prompt)
    return build_chars(raw.splitlines()) if colors else raw


async def birthday(member_name: str, family: dict) -> list[list[int]]:
    """Returns a decorated character array with colors and hearts."""
    name = member_name.upper()[:13]  # leave room for hearts on sides

    prompt = f"""\
Write a birthday message for {name} using color tiles and hearts for a flip-board display.
{_BOARD_TAG_RULES}

Each line is exactly 15 cells. Use colored tiles and [H] hearts to fill unused space.

Example for "ALEX":
[Y][H][Y][H][Y][H][Y][H][Y][H][Y][H][Y][H][Y]
[R][R][R]HAPPY[R][R][R][R][R][R][R][R][R][R]
[O]ALEX[O][H][O][H][O][H][O][H][O][H][O]

Now write one for {name}. Output only the 3 lines, nothing else."""

    raw   = await _generate(prompt)
    lines = raw.strip().splitlines()[:3]
    while len(lines) < 3:
        lines.append("")
    return build_chars(lines)


async def plex_pick(recently_added: list[dict]) -> str:
    """Pick one item from recently added and format it for the board."""
    if not recently_added:
        return _enforce("NOW SHOWING\nCHECK PLEX\nTONIGHT")

    pick  = recently_added[0]
    title = pick["title"].upper()

    # Strip episode suffix for cleaner display (e.g. "SHOW — S1E3" → "SHOW")
    if " \u2014 " in title:
        title = title.split(" \u2014 ")[0]

    prompt = f"""\
Format a Plex "Now Showing" board message for: {title}

Line 1 must be exactly: NOW SHOWING
Line 2 and 3: fit the title across 2 lines, max 15 characters each, ALL CAPS.
If the title is short enough, put it all on line 2 and leave line 3 blank or add a fun word like TONIGHT or NEW.
Output only 3 lines, nothing else."""
    return await _generate(prompt)


async def from_prompt(user_prompt: str) -> str:
    """Generate a board message from an arbitrary prompt in family.json."""
    prompt = f"""\
{user_prompt}

{BOARD_RULES}

Good examples — notice every line fits within 15 chars:
WHY CANT BIKES
STAND ALONE
THEYRE 2 TIRED

I USED TO HATE
FACIAL HAIR
BUT IT GREW ON ME"""
    return await _generate(prompt)


# ── Vestaboard color codes ─────────────────────────────────────────────────
# 0=blank, 63=red, 64=orange, 65=yellow, 66=green, 67=blue, 68=violet, 69=white
_BLANK  = 0
_COLORS = [63, 64, 65, 66, 67, 68, 69]

def _art_rainbow() -> list[list[int]]:
    row = [_COLORS[i % 7] for i in range(15)]
    return [row[:], row[:], row[:]]

def _art_stripes_h() -> list[list[int]]:
    colors = random.sample(_COLORS, 3)
    return [[c] * 15 for c in colors]

def _art_stripes_v() -> list[list[int]]:
    pattern = [_COLORS[i % 7] for i in range(15)]
    random.shuffle(pattern)
    return [pattern[:] for _ in range(3)]

def _art_checkerboard() -> list[list[int]]:
    c1, c2 = random.sample(_COLORS, 2)
    return [[(c1 if (r + c) % 2 == 0 else c2) for c in range(15)] for r in range(3)]

def _art_diagonal() -> list[list[int]]:
    c1, c2 = random.sample(_COLORS, 2)
    return [[(c1 if (col - row) % 3 < 2 else c2) for col in range(15)] for row in range(3)]

def _art_random_blocks() -> list[list[int]]:
    palette = random.sample(_COLORS, random.randint(2, 4))
    return [[random.choice(palette) for _ in range(15)] for _ in range(3)]

_ART_PATTERNS = [
    _art_rainbow,
    _art_stripes_h,
    _art_stripes_v,
    _art_checkerboard,
    _art_diagonal,
    _art_random_blocks,
]

def board_art() -> list[list[int]]:
    """Return a random 3×15 color pattern as character code rows."""
    return random.choice(_ART_PATTERNS)()


async def custom(text: str) -> list[list[int]]:
    """Format arbitrary text for the board, with optional color tiles."""
    prompt = f"""\
Format the following for a physical flip-board display with 3 rows of 15 characters each.
Be concise — distill the key information.
Use color tiles to make the message more expressive when appropriate.
{_BOARD_TAG_RULES}
{BOARD_RULES}

Text: {text}"""
    raw = await _generate(prompt)
    return build_chars(raw.splitlines())
