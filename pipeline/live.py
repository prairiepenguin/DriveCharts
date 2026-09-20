"""Live ESPN game state for Morris's current team."""

from __future__ import annotations

from typing import Any

from pipeline.classify import distance_bucket, infer_play, is_scrimmage
from pipeline.espn import EspnClient
from pipeline.ingest import parse_game
from pipeline.stints import STINTS
from app.predict import field_zone, score_bucket, situation_label

OSU = next(s for s in STINTS if s["era_id"] == "osu")
LIVE_NAMES = {
    "STATUS_IN_PROGRESS",
    "STATUS_HALFTIME",
    "STATUS_END_PERIOD",
    "STATUS_END_QUARTER",
    "STATUS_DELAYED",
}


def _nested(obj: dict | None, *keys: str, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def _status(summary: dict) -> dict:
    header = summary.get("header") or {}
    comp = (header.get("competitions") or [{}])[0]
    block = comp.get("status") or {}
    typ = block.get("type") or {}
    name = typ.get("name") or ""
    state = typ.get("state") or ""
    completed = bool(typ.get("completed"))
    if completed or state == "post":
        phase = "final"
    elif name in LIVE_NAMES or state == "in":
        phase = "live"
    else:
        phase = "pregame"
    return {
        "name": name,
        "state": state,
        "completed": completed,
        "detail": typ.get("detail") or typ.get("shortDetail") or typ.get("description"),
        "period": block.get("period"),
        "clock": block.get("displayClock"),
        "phase": phase,
    }


def merge_current_drive(summary: dict) -> dict:
    drives = dict(summary.get("drives") or {})
    prev = list(drives.get("previous") or [])
    current = drives.get("current")
    if isinstance(current, dict) and current.get("id"):
        cid = str(current.get("id"))
        if cid not in {str(d.get("id")) for d in prev}:
            prev.append(current)
    drives["previous"] = prev
    out = dict(summary)
    out["drives"] = drives
    return out


def fetch_schedule(season: int | None = None) -> list[dict]:
    season = int(season or OSU["seasons"][-1])
    with EspnClient(pause=0) as client:
        events = []
        for season_type in (2, 3):
            events.extend(client.schedule(OSU["team_id"], season, season_type))
    rows = []
    for event in events:
        comp = (event.get("competitions") or [{}])[0]
        typ = (comp.get("status") or {}).get("type") or {}
        rows.append(
            {
                "game_id": str(event.get("id")),
                "date": str(event.get("date") or "")[:10],
                "name": event.get("name"),
                "short": event.get("shortName"),
                "status": typ.get("name"),
                "detail": typ.get("shortDetail") or typ.get("detail") or typ.get("description"),
                "completed": bool(typ.get("completed")),
                "state": typ.get("state"),
            }
        )
    return rows


def pick_default_game(rows: list[dict]) -> dict | None:
    live = [r for r in rows if r.get("status") in LIVE_NAMES or r.get("state") == "in"]
    if live:
        return live[0]
    done = [r for r in rows if r.get("completed")]
    if done:
        return done[-1]
    upcoming = [r for r in rows if not r.get("completed")]
    return upcoming[0] if upcoming else None


def fetch_summary(game_id: str) -> dict:
    with EspnClient(pause=0) as client:
        return client.summary(game_id)


def parse_live(summary: dict) -> tuple[dict, list[dict], list[dict], dict]:
    merged = merge_current_drive(summary)
    game, drives, plays = parse_game(merged, OSU)
    status = _status(summary)
    game["status"] = status["name"]
    game["status_detail"] = status["detail"]
    game["phase"] = status["phase"]
    return game, drives, plays, status


def _last_scrimmage(plays: list[dict], current: dict | None) -> dict | None:
    if current:
        cid = str(current.get("id"))
        owned = [p for p in plays if str(p.get("drive_id")) == cid and p.get("scrimmage")]
        if owned:
            return owned[-1]
    scrim = [p for p in plays if p.get("scrimmage")]
    return scrim[-1] if scrim else None


def situation_from_espn_end(play: dict, prev_call: str | None, home_away: str) -> dict:
    end = play.get("end") or {}
    start = play.get("start") or {}
    down = end.get("down") or start.get("down")
    dist = end.get("distance") or start.get("distance")
    yte = end.get("yardsToEndzone")
    if yte is None:
        yte = start.get("yardsToEndzone")
    period = _nested(play, "period", "number")
    clock = _nested(play, "clock", "displayValue")
    home = play.get("homeScore")
    away = play.get("awayScore")
    try:
        off = int(home if home_away == "home" else away)
        deff = int(away if home_away == "home" else home)
        score_diff = off - deff
    except (TypeError, ValueError):
        score_diff = None
    sit = {
        "down": int(down) if down not in (None, 0) else None,
        "distance": int(dist) if dist is not None else None,
        "distance_bucket": distance_bucket(dist),
        "yards_to_endzone": yte,
        "field_zone": field_zone(yte),
        "passing_down": False,
        "prev_play_call": prev_call if prev_call in {"Run", "Pass"} else None,
        "period": period,
        "score_diff": score_diff,
        "score_bucket": score_bucket(score_diff),
        "yardline_text": end.get("possessionText") or end.get("downDistanceText") or start.get("possessionText"),
        "clock": clock,
    }
    down_i, dist_i = sit["down"], sit["distance"]
    sit["passing_down"] = bool(
        down_i is not None
        and dist_i is not None
        and ((down_i == 2 and dist_i >= 8) or (down_i in (3, 4) and dist_i >= 5))
    )
    sit["label"] = situation_label(sit)
    return sit


def next_snap(summary: dict, game: dict, plays: list[dict]) -> dict:
    status = _status(summary)
    team_id = str(OSU["team_id"])
    current = (summary.get("drives") or {}).get("current")
    if status["phase"] == "pregame":
        return {"phase": "pregame", "situation": None, "note": "Waiting for kickoff."}
    if status["phase"] == "final":
        return {"phase": "final", "situation": None, "note": "Game is over."}

    current_team = str((current or {}).get("team", {}).get("id") or "")
    if not current or current_team != team_id:
        return {
            "phase": "defense",
            "situation": None,
            "note": f"{game.get('team_abbrev') or 'OKST'} is on defense.",
        }

    last = _last_scrimmage(plays, current)
    raw_plays = current.get("plays") or []
    raw_last = raw_plays[-1] if raw_plays else None
    prev_call = last.get("play_call") if last else None
    if raw_last:
        inferred = infer_play((raw_last.get("type") or {}).get("text"), raw_last.get("text"))
        row = {
            "play_family": inferred.get("play_family"),
            "kneel": inferred.get("kneel"),
            "spike": inferred.get("spike"),
            "no_play": inferred.get("no_play"),
            "down": (raw_last.get("start") or {}).get("down"),
        }
        if is_scrimmage(row) and inferred.get("play_call") in {"Run", "Pass"}:
            prev_call = inferred.get("play_call")
        sit = situation_from_espn_end(raw_last, prev_call, game.get("home_away") or "home")
        if sit.get("down") in (1, 2, 3, 4) and sit.get("distance") is not None:
            return {
                "phase": "offense",
                "situation": sit,
                "note": sit["label"],
                "last_text": raw_last.get("text"),
            }
        return {
            "phase": "special",
            "situation": None,
            "note": "Special teams or incomplete situation — waiting for the next snap.",
            "last_text": raw_last.get("text"),
        }

    return {
        "phase": "offense",
        "situation": {
            "down": 1,
            "distance": 10,
            "distance_bucket": "10",
            "yards_to_endzone": 75,
            "field_zone": "other",
            "passing_down": False,
            "prev_play_call": None,
            "period": status.get("period"),
            "score_diff": (game.get("team_score") or 0) - (game.get("opp_score") or 0),
            "score_bucket": score_bucket((game.get("team_score") or 0) - (game.get("opp_score") or 0)),
            "yardline_text": None,
            "clock": status.get("clock"),
            "label": "1 & 10 (drive starting)",
        },
        "note": "Drive just started.",
    }
