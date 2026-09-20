"""Play-call classification from ESPN play type + description."""

from __future__ import annotations

import re

DISTANCE_BUCKETS = [
    (1, 2, "1-2"),
    (3, 3, "3"),
    (4, 6, "4-6"),
    (7, 9, "7-9"),
    (10, 10, "10"),
    (11, 15, "11-15"),
    (16, 99, "16+"),
]

PASS_TYPES = {
    "pass reception",
    "pass incompletion",
    "passing touchdown",
    "pass interception return",
    "interception return touchdown",
    "interception",
    "interception return",
    "pass",
    "complete pass",
    "incomplete pass",
    "sack",
    "sack touchdown",
}

RUN_TYPES = {
    "rush",
    "rushing touchdown",
    "scramble",
}

FG_TYPES = {
    "field goal good",
    "field goal missed",
    "blocked field goal",
    "missed field goal return",
    "field goal",
}

PUNT_TYPES = {
    "punt",
    "blocked punt",
    "punt return touchdown",
    "blocked punt touchdown",
}

SPECIAL_SKIP = {
    "kickoff",
    "kickoff return (offense)",
    "kickoff return touchdown",
    "onside kick",
    "timeout",
    "end period",
    "end of half",
    "end of game",
    "end of regulation",
    "coin toss",
    "official timeout",
    "tv timeout",
    "extra point good",
    "extra point missed",
    "blocked pat",
    "two point pass",
    "two point rush",
    "two-point pass",
    "two-point rush",
}


def distance_bucket(distance: int | None) -> str | None:
    if distance is None:
        return None
    try:
        d = int(distance)
    except (TypeError, ValueError):
        return None
    if d <= 0:
        return None
    for lo, hi, label in DISTANCE_BUCKETS:
        if lo <= d <= hi:
            return label
    return "16+"


def _lower(value: object) -> str:
    return str(value or "").strip().lower()


def infer_play(type_text: str | None, description: str | None) -> dict:
    t = _lower(type_text)
    d = _lower(description)
    text = f"{t} {d}"

    is_penalty = "penalty" in t or d.startswith("penalty") or " penalty " in f" {d}"
    no_play = "no play" in d or (is_penalty and "accepted" in d and "no play" in d)
    kneel = "kneel" in d or "takes a knee" in d
    spike = "spike" in d or "spiked the ball" in d
    sack = "sack" in t or "sacked" in d
    scramble = "scramble" in d or t == "scramble"
    interception = "intercept" in t or "intercepted" in d
    fumble = "fumble" in t or "fumble" in d
    shotgun = "shotgun" in d
    no_huddle = "no huddle" in d or "no-huddle" in d
    play_action = "play action" in d or "play-action" in d
    screen = "screen" in d

    result_group = None
    play_call = None
    play_family = "other"
    detail = type_text or "Unknown"

    if t in SPECIAL_SKIP or kneel or spike:
        play_family = "non_scrimmage"
        play_call = None
        if kneel:
            detail = "Kneel"
        elif spike:
            detail = "Spike"
    elif t in FG_TYPES or "field goal" in t:
        play_family = "special"
        play_call = "FG"
        detail = "Field Goal"
    elif t in PUNT_TYPES or t.startswith("punt"):
        play_family = "special"
        play_call = "Punt"
        detail = "Punt"
    elif is_penalty and (no_play or t == "penalty"):
        play_family = "penalty"
        play_call = "Penalty"
        detail = "Penalty"
    elif sack:
        play_family = "pass"
        play_call = "Pass"
        detail = "Sack"
    elif interception:
        play_family = "pass"
        play_call = "Pass"
        detail = "Interception"
    elif t in PASS_TYPES or "pass" in t:
        play_family = "pass"
        play_call = "Pass"
        if "touchdown" in t or "touchdown" in d:
            detail = "Passing TD"
        elif "incomplete" in t or "incompletion" in t:
            detail = "Incomplete"
        else:
            detail = "Complete"
        if screen:
            detail = f"{detail} (screen)"
    elif t in RUN_TYPES or "rush" in t:
        play_family = "run"
        play_call = "Pass" if scramble else "Run"
        detail = "Scramble" if scramble else ("Rushing TD" if "touchdown" in t else "Rush")
    elif "fumble" in t:
        if "sacked" in d or "pass" in d:
            play_family = "pass"
            play_call = "Pass"
            detail = "Fumble (pass)"
        else:
            play_family = "run"
            play_call = "Run"
            detail = "Fumble (run)"
    else:
        play_family = "other"
        play_call = None

    if "touchdown" in t or re.search(r"\bfor a (td|touchdown)\b", d):
        scoring = True
    else:
        scoring = False

    return {
        "play_call": play_call,
        "play_family": play_family,
        "play_detail": detail,
        "is_penalty": bool(is_penalty),
        "no_play": bool(no_play),
        "kneel": kneel,
        "spike": spike,
        "sack": sack,
        "scramble": scramble,
        "interception": interception,
        "fumble": fumble,
        "shotgun": shotgun,
        "no_huddle": no_huddle,
        "play_action": play_action,
        "screen": screen,
        "inferred_score": scoring,
        "text_blob": text[:1],  # unused placeholder kept off the row
    }


def is_scrimmage(row: dict) -> bool:
    if row.get("kneel") or row.get("spike") or row.get("no_play"):
        return False
    if row.get("play_family") not in {"run", "pass"}:
        return False
    down = row.get("down")
    try:
        down_i = int(down)
    except (TypeError, ValueError):
        return False
    return down_i in (1, 2, 3, 4)


def is_success(down: int | None, distance: int | None, yards: int | None, first_down: bool, td: bool) -> bool | None:
    if td:
        return True
    if first_down:
        return True
    if down is None or distance is None or yards is None:
        return None
    try:
        down_i, dist_i, yds = int(down), int(distance), int(yards)
    except (TypeError, ValueError):
        return None
    if dist_i <= 0:
        return None
    if down_i == 1:
        return yds >= 0.5 * dist_i
    if down_i == 2:
        return yds >= 0.7 * dist_i
    return yds >= dist_i


def is_explosive(play_call: str | None, yards: int | None) -> bool:
    if yards is None:
        return False
    try:
        y = int(yards)
    except (TypeError, ValueError):
        return False
    if play_call == "Pass":
        return y >= 15
    if play_call == "Run":
        return y >= 10
    return y >= 15


def is_garbage_time(period: int | None, score_diff: int | None, clock: str | None) -> bool:
    if score_diff is None or period is None:
        return False
    try:
        diff = abs(int(score_diff))
        q = int(period)
    except (TypeError, ValueError):
        return False
    if q < 4:
        return False
    if diff >= 29:
        return True
    minutes = 99
    if clock and ":" in clock:
        try:
            minutes = int(clock.split(":")[0])
        except ValueError:
            minutes = 99
    return diff >= 22 and minutes <= 6


def normalize_drive_result(result: str | None) -> str:
    r = (result or "").upper().strip()
    if not r:
        return "UNKNOWN"
    if "INT" in r or "INTERCEPT" in r:
        return "INT"
    if "FUMBLE" in r:
        return "FUMBLE"
    if "TD" in r or "TOUCHDOWN" in r:
        return "TD"
    if "MISS" in r and ("FG" in r or "FIELD" in r):
        return "MISSED FG"
    if "FG" in r or "FIELD GOAL" in r:
        return "FG"
    if "PUNT" in r:
        return "PUNT"
    if r == "DOWNS" or ("DOWN" in r and "TURNOVER" in r):
        return "DOWNS"
    if r in {"SF", "SAFETY"} or "SAFETY" in r:
        return "SAFETY"
    if "END" in r:
        return "END"
    return r
