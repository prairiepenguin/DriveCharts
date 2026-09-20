"""Download every Morris offensive play and write local parquet tables."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

from pipeline.classify import (
    distance_bucket,
    infer_play,
    is_explosive,
    is_garbage_time,
    is_scrimmage,
    is_success,
    normalize_drive_result,
)
from pipeline.espn import EspnClient
from pipeline.stints import STINTS

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"


def _nested(obj: dict | None, *keys: str, default=None):
    cur = obj
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def _clock_seconds(clock: str | None, period: int | None) -> int | None:
    if not clock or ":" not in str(clock):
        return None
    try:
        mins, secs = str(clock).split(":")[:2]
        remaining = int(mins) * 60 + int(secs)
        q = int(period or 1)
        prior = max(q - 1, 0) * 15 * 60
        # seconds remaining in game, assuming 15-min quarters
        return max(0, 4 * 15 * 60 - prior - (15 * 60 - remaining))
    except (TypeError, ValueError):
        return None


def parse_header(summary: dict, team_id: int) -> dict:
    header = summary.get("header") or {}
    competitions = header.get("competitions") or []
    comp = competitions[0] if competitions else {}
    competitors = comp.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if not home or not away:
        raise ValueError("summary missing home/away competitors")

    def side(comp_side: dict) -> dict:
        team = comp_side.get("team") or {}
        return {
            "id": int(team.get("id") or 0),
            "name": team.get("displayName") or team.get("location") or "",
            "abbrev": team.get("abbreviation") or "",
            "score": int(comp_side.get("score") or 0),
            "winner": bool(comp_side.get("winner")),
        }

    h, a = side(home), side(away)
    morris_home = h["id"] == int(team_id)
    morris = h if morris_home else a
    opp = a if morris_home else h
    date = (comp.get("date") or header.get("competitions", [{}])[0].get("date") or header.get("season", {}))
    if isinstance(date, dict):
        date = None
    week = _nested(header, "week", "number")
    season = _nested(header, "season", "year")
    season_type = _nested(header, "season", "type")
    return {
        "game_id": str(header.get("id") or comp.get("id") or ""),
        "date": str(comp.get("date") or "")[:10],
        "season": int(season or 0),
        "week": int(week or 0),
        "season_type": int(season_type or 2),
        "neutral": bool(comp.get("neutralSite")),
        "home_away": "home" if morris_home else "away",
        "team_id": morris["id"],
        "team": morris["name"],
        "team_abbrev": morris["abbrev"],
        "team_score": morris["score"],
        "opponent_id": opp["id"],
        "opponent": opp["name"],
        "opponent_abbrev": opp["abbrev"],
        "opp_score": opp["score"],
        "won": bool(morris["winner"]),
        "result": "W" if morris["winner"] else "L" if (h["score"] != a["score"] or True) else "T",
    }


def _yard_text(play: dict, which: str) -> str | None:
    block = play.get(which) or {}
    return block.get("possessionText") or block.get("downDistanceText")


def parse_game(summary: dict, stint: dict, extra: dict | None = None) -> tuple[dict, list[dict], list[dict]]:
    team_id = int(stint["team_id"])
    game = parse_header(summary, team_id)
    if extra:
        game["season"] = extra.get("season") or game["season"]
        if extra.get("week"):
            game["week"] = extra["week"]
    team_l = (game.get("team") or "").lower()
    expected = stint["team"].lower()
    if expected not in team_l and (game.get("team_abbrev") or "").upper() != stint["abbrev"]:
        raise ValueError(
            f"team mismatch for {game.get('game_id')}: expected {stint['team']} "
            f"got {game.get('team')} ({game.get('team_abbrev')})"
        )
    game.update(
        {
            "era": stint["era"],
            "era_id": stint["era_id"],
            "role": stint["role"],
            "team_canon": stint["team"],
        }
    )
    if game["team_score"] == game["opp_score"]:
        game["result"] = "T"
        game["won"] = False

    drives_out: list[dict] = []
    plays_out: list[dict] = []
    raw_drives = (summary.get("drives") or {}).get("previous") or []
    off_n = 0
    for raw in raw_drives:
        team = raw.get("team") or {}
        if str(team.get("id")) != str(team_id):
            continue
        off_n += 1
        start = raw.get("start") or {}
        end = raw.get("end") or {}
        drive_id = str(raw.get("id") or f"{game['game_id']}-{off_n}")
        result_raw = raw.get("result") or raw.get("displayResult") or ""
        drive = {
            "drive_id": drive_id,
            "game_id": game["game_id"],
            "season": game["season"],
            "week": game["week"],
            "era": game["era"],
            "era_id": game["era_id"],
            "role": game["role"],
            "team": stint["team"],
            "opponent": game["opponent"],
            "home_away": game["home_away"],
            "date": game["date"],
            "drive_number": off_n,
            "description": raw.get("description"),
            "start_period": _nested(start, "period", "number"),
            "start_clock": _nested(start, "clock", "displayValue"),
            "start_text": start.get("text"),
            "start_yard_line": start.get("yardLine"),
            "end_period": _nested(end, "period", "number"),
            "end_clock": _nested(end, "clock", "displayValue"),
            "end_text": end.get("text"),
            "end_yard_line": end.get("yardLine"),
            "time_elapsed": _nested(raw, "timeElapsed", "displayValue"),
            "yards": raw.get("yards"),
            "offensive_plays": raw.get("offensivePlays"),
            "is_score": bool(raw.get("isScore")),
            "result_raw": result_raw,
            "result": normalize_drive_result(result_raw),
        }
        drive_plays = []
        prev_call = None
        prev_yards = None
        prev_success = None
        play_n = 0
        for raw_play in raw.get("plays") or []:
            start_p = raw_play.get("start") or {}
            end_p = raw_play.get("end") or {}
            type_obj = raw_play.get("type") or {}
            type_text = type_obj.get("text")
            desc = raw_play.get("text") or ""
            inferred = infer_play(type_text, desc)
            down = start_p.get("down")
            dist = start_p.get("distance")
            yte = start_p.get("yardsToEndzone")
            yards = raw_play.get("statYardage")
            period = _nested(raw_play, "period", "number")
            clock = _nested(raw_play, "clock", "displayValue")
            home_score = raw_play.get("homeScore")
            away_score = raw_play.get("awayScore")
            if game["home_away"] == "home":
                off_score, def_score = home_score, away_score
            else:
                off_score, def_score = away_score, home_score
            try:
                score_diff = int(off_score) - int(def_score)
            except (TypeError, ValueError):
                score_diff = None
            td = bool(raw_play.get("scoringPlay")) and (
                "touchdown" in (type_text or "").lower() or "touchdown" in desc.lower()
            )
            first_down = False
            try:
                if down and dist is not None and yards is not None and int(yards) >= int(dist):
                    first_down = True
            except (TypeError, ValueError):
                first_down = False
            success = is_success(down, dist, yards, first_down, td)
            row = {
                "play_id": str(raw_play.get("id") or ""),
                "game_id": game["game_id"],
                "drive_id": drive_id,
                "season": game["season"],
                "week": game["week"],
                "date": game["date"],
                "era": game["era"],
                "era_id": game["era_id"],
                "role": game["role"],
                "team": stint["team"],
                "opponent": game["opponent"],
                "home_away": game["home_away"],
                "drive_number": off_n,
                "sequence_number": raw_play.get("sequenceNumber"),
                "period": period,
                "clock": clock,
                "sec_remaining": _clock_seconds(clock, period),
                "down": down,
                "distance": dist,
                "distance_bucket": distance_bucket(dist),
                "yards_to_endzone": yte,
                "yardline_text": start_p.get("possessionText") or _yard_text(raw_play, "start"),
                "end_yards_to_endzone": end_p.get("yardsToEndzone"),
                "play_type_raw": type_text,
                "play_type_abbr": type_obj.get("abbreviation"),
                "description": desc,
                "yards": yards,
                "scoring_play": bool(raw_play.get("scoringPlay")),
                "is_turnover": bool(raw_play.get("isTurnover")),
                "offense_score": off_score,
                "defense_score": def_score,
                "score_diff": score_diff,
                "touchdown": td,
                "first_down": first_down,
                "success": success,
                "prev_play_call": prev_call,
                "prev_yards": prev_yards,
                "prev_success": prev_success,
            }
            row.update({k: v for k, v in inferred.items() if k != "text_blob"})
            row["scrimmage"] = is_scrimmage(row)
            row["explosive"] = is_explosive(row.get("play_call"), yards) if row["scrimmage"] else False
            row["red_zone"] = isinstance(yte, (int, float)) and 0 < int(yte) <= 20
            row["goal_to_go"] = isinstance(yte, (int, float)) and isinstance(dist, (int, float)) and int(yte) <= int(dist)
            row["early_down"] = down in (1, 2)
            try:
                row["passing_down"] = (int(down) == 2 and int(dist) >= 8) or (
                    int(down) in (3, 4) and int(dist) >= 5
                )
            except (TypeError, ValueError):
                row["passing_down"] = False
            row["backed_up"] = isinstance(yte, (int, float)) and int(yte) >= 80
            row["plus_territory"] = isinstance(yte, (int, float)) and int(yte) <= 50
            row["garbage_time"] = is_garbage_time(period, score_diff, clock)
            if row["scrimmage"]:
                play_n += 1
                row["drive_play_number"] = play_n
                prev_call = row.get("play_call")
                prev_yards = yards
                prev_success = success
            else:
                row["drive_play_number"] = None
            drive_plays.append(row)
            plays_out.append(row)

        drive["scrimmage_plays"] = play_n
        drive["start_yards_to_endzone"] = next(
            (p["yards_to_endzone"] for p in drive_plays if p.get("scrimmage") and p.get("yards_to_endzone") is not None),
            None,
        )
        if drive["start_yards_to_endzone"] is None:
            # kickoff-only / special start: use first play end field position
            for p in drive_plays:
                if p.get("end_yards_to_endzone") is not None:
                    drive["start_yards_to_endzone"] = p["end_yards_to_endzone"]
                    break
        three_and_out = (
            play_n <= 3
            and drive["result"] == "PUNT"
            and not drive["is_score"]
        )
        drive["three_and_out"] = three_and_out
        drive["points"] = 6 if drive["result"] == "TD" else 3 if drive["result"] == "FG" else 0
        drives_out.append(drive)

    game["n_drives"] = len(drives_out)
    game["n_plays"] = sum(1 for p in plays_out if p.get("scrimmage"))
    game["n_raw_plays"] = len(plays_out)
    return game, drives_out, plays_out


def _cache_path(game_id: str) -> Path:
    return RAW / f"{game_id}.json"


def load_or_fetch(client: EspnClient, game_id: str, refresh: bool) -> dict:
    path = _cache_path(game_id)
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    data = client.summary(game_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return data


def collect_schedule_games(client: EspnClient, stint: dict) -> list[dict]:
    seen: set[str] = set()
    games: list[dict] = []
    for season in stint["seasons"]:
        for season_type in (2, 3):
            for event in client.schedule(stint["team_id"], season, season_type):
                gid = str(event.get("id"))
                comp = (event.get("competitions") or [{}])[0]
                status = (comp.get("status") or {}).get("type") or {}
                if not status.get("completed"):
                    continue
                if gid in seen:
                    continue
                seen.add(gid)
                games.append(
                    {
                        "game_id": gid,
                        "season": season,
                        "week": _nested(event, "week", "number") or _nested(event, "season", "type"),
                        "season_type": season_type,
                        "date": str(event.get("date") or "")[:10],
                    }
                )
    for extra in stint.get("extra_games") or []:
        gid = str(extra["game_id"])
        if gid in seen:
            continue
        seen.add(gid)
        games.append(dict(extra))
    return games


def ingest(refresh: bool = False) -> dict:
    DATA.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    games: list[dict] = []
    drives: list[dict] = []
    plays: list[dict] = []
    skipped: list[str] = []

    with EspnClient() as client:
        for stint in STINTS:
            scheduled = collect_schedule_games(client, stint)
            print(f"{stint['era']}: {len(scheduled)} completed games", flush=True)
            for i, meta in enumerate(scheduled, 1):
                gid = str(meta["game_id"])
                try:
                    summary = load_or_fetch(client, gid, refresh=refresh)
                    if not (summary.get("drives") or {}).get("previous"):
                        skipped.append(f"{gid} no drives")
                        print(f"  skip {gid} (no drives)", flush=True)
                        continue
                    game, g_drives, g_plays = parse_game(summary, stint, extra=meta)
                    games.append(game)
                    drives.extend(g_drives)
                    plays.extend(g_plays)
                    if i % 8 == 0 or i == len(scheduled):
                        print(
                            f"  {i}/{len(scheduled)} {game['date']} vs {game['opponent_abbrev']} "
                            f"{game['n_drives']} drives / {game['n_plays']} scrimmage",
                            flush=True,
                        )
                except Exception as exc:  # noqa: BLE001
                    skipped.append(f"{gid} {exc}")
                    print(f"  FAIL {gid}: {exc}", flush=True)

    games_df = pd.DataFrame(games)
    drives_df = pd.DataFrame(drives)
    plays_df = pd.DataFrame(plays)
    if not games_df.empty:
        games_df = games_df.sort_values(["date", "game_id"]).reset_index(drop=True)
    if not drives_df.empty:
        drives_df = drives_df.sort_values(["date", "drive_number"]).reset_index(drop=True)
    if not plays_df.empty:
        plays_df = plays_df.sort_values(["date", "drive_number", "sequence_number"]).reset_index(drop=True)

    games_path = DATA / "games.parquet"
    drives_path = DATA / "drives.parquet"
    plays_path = DATA / "plays.parquet"
    games_df.to_parquet(games_path, index=False)
    drives_df.to_parquet(drives_path, index=False)
    plays_df.to_parquet(plays_path, index=False)

    meta = {
        "n_games": int(len(games_df)),
        "n_drives": int(len(drives_df)),
        "n_plays": int(len(plays_df)),
        "n_scrimmage": int(plays_df["scrimmage"].sum()) if not plays_df.empty else 0,
        "seasons": sorted({int(s) for s in games_df["season"].dropna().unique()}) if not games_df.empty else [],
        "eras": (
            games_df.groupby(["era_id", "era", "role"], dropna=False)
            .size()
            .reset_index(name="games")
            .to_dict("records")
            if not games_df.empty
            else []
        ),
        "skipped": skipped,
        "paths": {
            "games": str(games_path),
            "drives": str(drives_path),
            "plays": str(plays_path),
        },
    }
    (DATA / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("n_games", "n_drives", "n_plays", "n_scrimmage", "seasons")}, indent=2))
    if skipped:
        print(f"skipped {len(skipped)} games")
    return meta


def main() -> int:
    refresh = "--refresh" in sys.argv
    ingest(refresh=refresh)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
