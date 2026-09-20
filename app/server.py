"""FastAPI app for Eric Morris play-selection analysis."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import analysis

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="Morris Playbook")
if STATIC.exists():
    app.mount("/static", StaticFiles(directory=STATIC), name="static")


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "item"):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


def _records(df: pd.DataFrame) -> list[dict]:
    if df.empty:
        return []
    return [{k: _jsonable(v) for k, v in row.items()} for row in df.to_dict(orient="records")]


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health() -> dict:
    try:
        tables = analysis.load_tables()
        return {"ok": True, "games": int(len(tables["games"])), "plays": int(len(tables["plays"]))}
    except FileNotFoundError as exc:
        return {"ok": False, "error": str(exc)}


@app.get("/api/meta")
def meta() -> dict:
    return analysis.meta()


@app.get("/api/overview")
def overview(era: str | None = None, season: str | None = None, exclude_garbage: bool = True) -> dict:
    return analysis.overview(era=era, season=season, exclude_garbage=exclude_garbage)


@app.get("/api/down-distance")
def down_distance(era: str | None = None, season: str | None = None, exclude_garbage: bool = True) -> dict:
    df = analysis.down_distance(era=era, season=season, exclude_garbage=exclude_garbage)
    return {"rows": _records(df)}


@app.get("/api/sequencing")
def sequencing(era: str | None = None, season: str | None = None, exclude_garbage: bool = True) -> dict:
    raw = analysis.sequencing(era=era, season=season, exclude_garbage=exclude_garbage)
    return {
        "after_run": raw["After a run"],
        "after_pass": raw["After a pass"],
        "after_success": raw["After success"],
        "after_fail": raw["After failure"],
        "after_explosive": raw["After explosive (15+)"],
        "after_run_stuffed": raw["After stuffed run (≤1)"],
        "after_incompletion": raw["After incompletion"],
    }


@app.get("/api/situations")
def situations(era: str | None = None, season: str | None = None, exclude_garbage: bool = True) -> dict:
    df = analysis.situations(era=era, season=season, exclude_garbage=exclude_garbage)
    rows = []
    for rec in df.to_dict(orient="records"):
        rows.append(
            {
                "label": rec["Situation"],
                "n": rec["n"],
                "pass_rate": rec["Pass %"],
                "success_rate": rec["Success %"],
                "explosive_rate": rec["Explosive %"],
                "yards_per_play": rec["Yds/play"],
            }
        )
    return {"rows": rows}


@app.get("/api/eras")
def eras(exclude_garbage: bool = True) -> dict:
    df = analysis.era_table(exclude_garbage=exclude_garbage)
    rows = []
    for rec in df.to_dict(orient="records"):
        rows.append(
            {
                "era": rec["Era"],
                "role": rec["Role"],
                "seasons": rec["Seasons"],
                "games": rec["Games"],
                "plays": rec["Plays"],
                "pass_rate": rec["Pass %"],
                "first_down_pass_rate": rec["1st-down pass %"],
                "success_rate": rec["Success %"],
                "yards_per_play": rec["Yds/play"],
                "points_per_drive": rec["Pts/drive"],
                "td_drive_rate": rec["TD drive %"],
                "three_and_out_rate": rec["3-and-out %"],
            }
        )
    return {"rows": rows}


@app.get("/api/games")
def games(era: str | None = None, season: str | None = None) -> dict:
    df = analysis.game_list(era=era, season=season)
    cols = [
        "game_id", "date", "season", "week", "era", "era_id", "role", "team",
        "opponent", "opponent_abbrev", "home_away", "team_score", "opp_score",
        "result", "n_drives", "n_plays", "pass_rate", "yards",
    ]
    cols = [c for c in cols if c in df.columns]
    return {"games": _records(df[cols])}


@app.get("/api/game/{game_id}")
def game_detail(game_id: str) -> dict:
    try:
        game, drives, plays = analysis.game_drives(game_id)
    except KeyError:
        raise HTTPException(404, "Game not found") from None
    drive_payload = []
    for rec in _records(drives):
        d_plays = plays[plays["drive_id"].astype(str) == str(rec["drive_id"])]
        d_plays = d_plays.sort_values(["drive_play_number", "sequence_number"], na_position="last")
        keep = [
            c for c in [
                "play_id", "drive_play_number", "period", "clock", "down", "distance",
                "yardline_text", "yards_to_endzone", "play_call", "play_detail",
                "play_type_raw", "description", "yards", "success", "explosive",
                "scrimmage", "scoring_play",
            ]
            if c in d_plays.columns
        ]
        rec["plays"] = _records(d_plays[keep])
        drive_payload.append(rec)
    return {"game": {k: _jsonable(v) for k, v in game.to_dict().items()}, "drives": drive_payload}


@app.get("/api/plays")
def plays(
    era: str | None = None,
    season: str | None = None,
    down: str | None = None,
    distance_bucket: str | None = None,
    play_call: str | None = None,
    exclude_garbage: bool = True,
    red_zone: bool | None = Query(default=None),
    passing_down: bool | None = Query(default=None),
    period: str | None = None,
    opponent: str | None = None,
    game_id: str | None = None,
    limit: int = 80,
) -> dict:
    df = analysis.filter_plays(
        analysis.load_tables()["plays"],
        era=era,
        season=season,
        down=down,
        distance_bucket=distance_bucket,
        play_call=play_call,
        exclude_garbage=exclude_garbage,
        red_zone=red_zone,
        passing_down=passing_down,
        period=period,
        opponent=opponent,
        game_id=game_id,
    )
    total = int(len(df))
    cols = [
        c for c in [
            "date", "season", "era", "opponent", "drive_number", "drive_play_number",
            "period", "clock", "down", "distance", "yardline_text", "play_call",
            "play_detail", "description", "yards", "success", "explosive", "game_id",
        ]
        if c in df.columns
    ]
    sample = df.sort_values(["date", "drive_number", "drive_play_number"]).head(max(1, min(limit, 250)))
    return {"total": total, "plays": _records(sample[cols])}


def main() -> None:
    import uvicorn

    uvicorn.run("app.server:app", host="127.0.0.1", port=8765, reload=False)


if __name__ == "__main__":
    main()
