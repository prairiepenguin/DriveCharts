"""Situation-based pass/run predictions from Morris play-by-play."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.analysis import filter_plays, load_tables, mean, rate
from pipeline.classify import distance_bucket

WINDOWS = {
    "current": "Current Morris (UNT 2023–25 + OSU 2026)",
    "osu": "Oklahoma State 2026",
    "career": "All Morris years (2013–2026)",
}

MIN_N = {"current": 12, "osu": 8, "career": 20}


def _to_int(value: Any) -> int | None:
    try:
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def field_zone(yards_to_endzone: Any, red_zone: Any = None, backed_up: Any = None, plus_territory: Any = None) -> str:
    if red_zone is True:
        return "red"
    if backed_up is True:
        return "backed"
    if plus_territory is True:
        return "plus"
    yte = _to_int(yards_to_endzone)
    if yte is None:
        return "other"
    if 0 < yte <= 20:
        return "red"
    if yte >= 80:
        return "backed"
    if yte <= 50:
        return "plus"
    return "other"


def score_bucket(score_diff: Any) -> str:
    diff = _to_int(score_diff)
    if diff is None:
        return "close"
    if diff <= -8:
        return "trail"
    if diff >= 8:
        return "lead"
    return "close"


def situation_from_play(row: pd.Series | dict) -> dict:
    get = row.get if hasattr(row, "get") else lambda k, d=None: row[k] if k in row else d
    down = _to_int(get("down"))
    dist = _to_int(get("distance"))
    yte = _to_int(get("yards_to_endzone"))
    prev = get("prev_play_call")
    if prev not in {"Run", "Pass"}:
        prev = None
    return {
        "down": down,
        "distance": dist,
        "distance_bucket": get("distance_bucket") or distance_bucket(dist),
        "yards_to_endzone": yte,
        "field_zone": field_zone(yte, get("red_zone"), get("backed_up"), get("plus_territory")),
        "passing_down": bool(get("passing_down")) if get("passing_down") is not None else _passing_down(down, dist),
        "prev_play_call": prev,
        "period": _to_int(get("period")),
        "score_diff": _to_int(get("score_diff")),
        "score_bucket": score_bucket(get("score_diff")),
        "yardline_text": get("yardline_text"),
        "clock": get("clock"),
    }


def _passing_down(down: int | None, dist: int | None) -> bool:
    if down is None or dist is None:
        return False
    return (down == 2 and dist >= 8) or (down in (3, 4) and dist >= 5)


def situation_label(sit: dict) -> str:
    down = sit.get("down")
    dist = sit.get("distance")
    spot = sit.get("yardline_text") or (
        f"{sit.get('yards_to_endzone')} yards to go" if sit.get("yards_to_endzone") else ""
    )
    down_s = f"{down} & {dist}" if down and dist is not None else "Unknown down"
    prev = sit.get("prev_play_call")
    prev_s = f" after {prev.lower()}" if prev else " (drive start)"
    return f"{down_s} · {spot}{prev_s}".strip(" ·")


def _window_mask(plays: pd.DataFrame, window: str) -> pd.Series:
    season = pd.to_numeric(plays["season"], errors="coerce")
    if window == "osu":
        return plays["era_id"].eq("osu")
    if window == "current":
        return season.ge(2023)
    return pd.Series(True, index=plays.index)


def training_plays(window: str = "current") -> pd.DataFrame:
    plays = filter_plays(load_tables()["plays"], exclude_garbage=True)
    plays = plays[plays["play_call"].isin(["Run", "Pass"])].copy()
    plays = plays[_window_mask(plays, window)]
    return plays


class Predictor:
    def __init__(self, plays: pd.DataFrame, window: str) -> None:
        plays = plays.copy()
        yte = pd.to_numeric(plays.get("yards_to_endzone"), errors="coerce")
        zone = pd.Series("other", index=plays.index)
        zone = zone.mask(plays.get("plus_territory") == True, "plus")  # noqa: E712
        zone = zone.mask(plays.get("backed_up") == True, "backed")  # noqa: E712
        zone = zone.mask(plays.get("red_zone") == True, "red")  # noqa: E712
        zone = zone.mask(yte.fillna(99).le(20) & yte.fillna(99).gt(0), "red")
        plays["_zone"] = zone
        plays["_score_b"] = pd.to_numeric(plays.get("score_diff"), errors="coerce").map(score_bucket)
        self.plays = plays
        self.window = window
        self.window_label = WINDOWS[window]
        self.min_n = MIN_N[window]
        self.n = int(len(plays))
        self.base_pass = rate((plays["play_call"] == "Pass").sum(), len(plays)) if len(plays) else None

    def predict(self, sit: dict, exclude_game_id: str | None = None) -> dict:
        pool = self.plays
        if exclude_game_id:
            pool = pool[pool["game_id"].astype(str) != str(exclude_game_id)]
        down = sit.get("down")
        bucket = sit.get("distance_bucket")
        prev = sit.get("prev_play_call")
        zone = sit.get("field_zone")
        passing = sit.get("passing_down")
        score = sit.get("score_bucket")

        def col_eq(frame: pd.DataFrame, name: str, value: Any) -> pd.Series:
            if value is None or name not in frame.columns:
                return pd.Series(True, index=frame.index)
            if name == "distance_bucket":
                return frame[name].astype(str) == str(value)
            if name == "prev_play_call":
                return frame[name].fillna("").astype(str) == str(value)
            return frame[name] == value

        levels: list[tuple[str, pd.Series]] = []
        if down is not None and bucket and prev and zone:
            levels.append(
                (
                    "down + distance + previous call + field",
                    col_eq(pool, "down", down)
                    & col_eq(pool, "distance_bucket", bucket)
                    & col_eq(pool, "prev_play_call", prev)
                    & pool["_zone"].eq(zone),
                )
            )
        if down is not None and bucket and passing is not None:
            levels.append(
                (
                    "down + distance + passing down",
                    col_eq(pool, "down", down)
                    & col_eq(pool, "distance_bucket", bucket)
                    & pool["passing_down"].eq(bool(passing)),
                )
            )
        if down is not None and bucket and score:
            levels.append(
                (
                    "down + distance + score",
                    col_eq(pool, "down", down)
                    & col_eq(pool, "distance_bucket", bucket)
                    & pool["_score_b"].eq(score),
                )
            )
        if down is not None and bucket:
            levels.append(
                (
                    "down + distance",
                    col_eq(pool, "down", down) & col_eq(pool, "distance_bucket", bucket),
                )
            )
        if down is not None:
            levels.append(("down", col_eq(pool, "down", down)))
        levels.append(("all training plays", pd.Series(True, index=pool.index)))

        chosen_name = "all training plays"
        sub = pool
        for name, mask in levels:
            candidate = pool[mask]
            if len(candidate) >= self.min_n:
                chosen_name = name
                sub = candidate
                break

        n = int(len(sub))
        pass_n = int((sub["play_call"] == "Pass").sum()) if n else 0
        run_n = int((sub["play_call"] == "Run").sum()) if n else 0
        p_pass = rate(pass_n + 1, n + 2) if n else self.base_pass
        pred = "Pass" if (p_pass or 0) >= 0.5 else "Run"
        return {
            "p_pass": p_pass,
            "p_run": None if p_pass is None else round(1 - p_pass, 4),
            "call": pred,
            "n": n,
            "level": chosen_name,
            "window": self.window_label,
            "pass_ypp": mean(sub.loc[sub["play_call"] == "Pass", "yards"]) if pass_n else None,
            "run_ypp": mean(sub.loc[sub["play_call"] == "Run", "yards"]) if run_n else None,
            "success_if_pass": rate(sub.loc[sub["play_call"] == "Pass", "success"].fillna(False).sum(), pass_n) if pass_n else None,
            "success_if_run": rate(sub.loc[sub["play_call"] == "Run", "success"].fillna(False).sum(), run_n) if run_n else None,
            "situation": situation_label(sit),
        }


def fit(window: str = "current") -> Predictor:
    if window not in WINDOWS:
        window = "current"
    return Predictor(training_plays(window), window)
