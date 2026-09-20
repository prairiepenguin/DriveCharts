"""Shared loaders and aggregations for the FastAPI and Streamlit apps."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DISTANCE_BUCKETS = ["1-2", "3", "4-6", "7-9", "10", "11-15", "16+"]
ERA_COLORS = {
    "ttu": "#CC0000",
    "uiw": "#C41E3A",
    "wsu": "#981E32",
    "unt": "#00853E",
    "osu": "#FF7300",
}
RESULT_COLORS = {
    "TD": "#3dcf7a",
    "FG": "#e7c04a",
    "INT": "#e35d4a",
    "FUMBLE": "#e35d4a",
    "DOWNS": "#d9893b",
    "PUNT": "#6d7c70",
    "MISSED FG": "#d9893b",
    "SAFETY": "#e35d4a",
    "END": "#6d7c70",
}

_TABLES: dict[str, pd.DataFrame] | None = None
_TABLES_MTIME: float | None = None


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value if v is not None and str(v) != ""]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def load_tables() -> dict[str, pd.DataFrame]:
    global _TABLES, _TABLES_MTIME
    plays_path = DATA / "plays.parquet"
    if not plays_path.exists():
        raise FileNotFoundError("No play data yet. Run: python -m pipeline.ingest")
    mtime = plays_path.stat().st_mtime
    if _TABLES is not None and _TABLES_MTIME == mtime:
        return _TABLES
    plays = pd.read_parquet(DATA / "plays.parquet")
    drives = pd.read_parquet(DATA / "drives.parquet")
    games = pd.read_parquet(DATA / "games.parquet")
    for frame in (plays, drives, games):
        if "season" in frame.columns:
            frame["season"] = pd.to_numeric(frame["season"], errors="coerce").astype("Int64")
    _TABLES = {"plays": plays, "drives": drives, "games": games}
    _TABLES_MTIME = mtime
    return _TABLES


def filter_plays(
    plays: pd.DataFrame,
    era: Any = None,
    season: Any = None,
    down: Any = None,
    distance_bucket: Any = None,
    play_call: Any = None,
    scrimmage: bool = True,
    exclude_garbage: bool = True,
    red_zone: bool | None = None,
    passing_down: bool | None = None,
    period: Any = None,
    opponent: str | None = None,
    game_id: str | None = None,
) -> pd.DataFrame:
    df = plays
    if scrimmage:
        df = df[df["scrimmage"] == True]  # noqa: E712
    if exclude_garbage and "garbage_time" in df.columns:
        df = df[df["garbage_time"] != True]  # noqa: E712
    eras = _values(era)
    if eras:
        df = df[df["era_id"].isin(eras) | df["era"].isin(eras)]
    seasons = [int(s) for s in _values(season) if str(s).lstrip("-").isdigit()]
    if seasons:
        df = df[df["season"].isin(seasons)]
    downs = [int(s) for s in _values(down) if str(s).lstrip("-").isdigit()]
    if downs:
        df = df[df["down"].isin(downs)]
    buckets = _values(distance_bucket)
    if buckets:
        df = df[df["distance_bucket"].isin(buckets)]
    calls = _values(play_call)
    if calls:
        df = df[df["play_call"].isin(calls)]
    periods = [int(s) for s in _values(period) if str(s).lstrip("-").isdigit()]
    if periods:
        df = df[df["period"].isin(periods)]
    if opponent:
        df = df[df["opponent"].str.contains(opponent, case=False, na=False)]
    if game_id:
        df = df[df["game_id"].astype(str) == str(game_id)]
    if red_zone is True:
        df = df[df["red_zone"] == True]  # noqa: E712
    if passing_down is True:
        df = df[df["passing_down"] == True]  # noqa: E712
    return df


def filter_frame(df: pd.DataFrame, era: Any = None, season: Any = None) -> pd.DataFrame:
    eras = _values(era)
    if eras:
        df = df[df["era_id"].isin(eras) | df["era"].isin(eras)]
    seasons = [int(s) for s in _values(season) if str(s).lstrip("-").isdigit()]
    if seasons:
        df = df[df["season"].isin(seasons)]
    return df


def rate(num: float, den: float) -> float | None:
    if not den:
        return None
    return round(float(num) / float(den), 4)


def mean(series: pd.Series) -> float | None:
    s = pd.to_numeric(series, errors="coerce").dropna()
    if s.empty:
        return None
    return round(float(s.mean()), 3)


def meta() -> dict:
    tables = load_tables()
    games = tables["games"]
    plays = tables["plays"]
    scrim = plays[plays["scrimmage"] == True]  # noqa: E712
    eras = []
    for era_id, grp in games.groupby("era_id", dropna=False):
        era_plays = scrim[scrim["era_id"] == era_id]
        eras.append(
            {
                "era_id": era_id,
                "era": grp["era"].iloc[0],
                "role": grp["role"].iloc[0],
                "seasons": sorted(int(s) for s in grp["season"].dropna().unique()),
                "games": int(len(grp)),
                "plays": int(len(era_plays)),
                "pass_rate": rate((era_plays["play_call"] == "Pass").sum(), len(era_plays)),
            }
        )
    eras.sort(key=lambda e: min(e["seasons"] or [9999]))
    return {
        "n_games": int(len(games)),
        "n_drives": int(len(tables["drives"])),
        "n_plays": int(len(plays)),
        "n_scrimmage": int(len(scrim)),
        "seasons": sorted(int(s) for s in games["season"].dropna().unique()),
        "eras": eras,
        "distance_buckets": DISTANCE_BUCKETS,
        "opponents": sorted(games["opponent"].dropna().unique().tolist()),
    }


def overview(era: Any = None, season: Any = None, exclude_garbage: bool = True) -> dict:
    tables = load_tables()
    plays = filter_plays(tables["plays"], era=era, season=season, exclude_garbage=exclude_garbage)
    drives = filter_frame(tables["drives"], era=era, season=season)
    games = filter_frame(tables["games"], era=era, season=season)
    n = len(plays)
    pass_n = int((plays["play_call"] == "Pass").sum()) if n else 0
    run_n = int((plays["play_call"] == "Run").sum()) if n else 0
    success_n = int(plays["success"].fillna(False).sum()) if n else 0
    explosive_n = int(plays["explosive"].fillna(False).sum()) if n else 0
    third = plays[plays["down"] == 3] if n else plays
    rz = plays[plays["red_zone"] == True] if n else plays  # noqa: E712
    first = plays[plays["down"] == 1] if n else plays
    return {
        "games": int(len(games)),
        "drives": int(len(drives)),
        "plays": n,
        "pass_n": pass_n,
        "run_n": run_n,
        "pass_rate": rate(pass_n, n),
        "run_rate": rate(run_n, n),
        "success_rate": rate(success_n, n),
        "explosive_rate": rate(explosive_n, n),
        "yards_per_play": mean(plays["yards"]) if n else None,
        "yards_per_pass": mean(plays.loc[plays["play_call"] == "Pass", "yards"]) if pass_n else None,
        "yards_per_run": mean(plays.loc[plays["play_call"] == "Run", "yards"]) if run_n else None,
        "first_down_pass_rate": rate((first["play_call"] == "Pass").sum(), len(first)) if len(first) else None,
        "third_down_pass_rate": rate((third["play_call"] == "Pass").sum(), len(third)) if len(third) else None,
        "third_down_success": rate(third["success"].fillna(False).sum(), len(third)) if len(third) else None,
        "red_zone_plays": int(len(rz)),
        "red_zone_pass_rate": rate((rz["play_call"] == "Pass").sum(), len(rz)) if len(rz) else None,
        "points_per_drive": mean(drives["points"]) if len(drives) else None,
        "td_drive_rate": rate((drives["result"] == "TD").sum(), len(drives)) if len(drives) else None,
        "punt_rate": rate((drives["result"] == "PUNT").sum(), len(drives)) if len(drives) else None,
        "three_and_out_rate": rate(drives["three_and_out"].fillna(False).sum(), len(drives)) if len(drives) else None,
        "turnover_rate": rate(drives["result"].isin(["INT", "FUMBLE"]).sum(), len(drives)) if len(drives) else None,
    }


def down_distance(era: Any = None, season: Any = None, exclude_garbage: bool = True) -> pd.DataFrame:
    plays = filter_plays(load_tables()["plays"], era=era, season=season, exclude_garbage=exclude_garbage)
    if plays.empty:
        return pd.DataFrame()
    grouped = (
        plays.groupby(["down", "distance_bucket"], dropna=False)
        .agg(
            n=("play_id", "count"),
            pass_n=("play_call", lambda s: int((s == "Pass").sum())),
            run_n=("play_call", lambda s: int((s == "Run").sum())),
            success_n=("success", lambda s: int(s.fillna(False).sum())),
            yards=("yards", "mean"),
            explosive_n=("explosive", lambda s: int(s.fillna(False).sum())),
        )
        .reset_index()
    )
    grouped["pass_rate"] = grouped.apply(lambda r: rate(r["pass_n"], r["n"]), axis=1)
    grouped["success_rate"] = grouped.apply(lambda r: rate(r["success_n"], r["n"]), axis=1)
    grouped["explosive_rate"] = grouped.apply(lambda r: rate(r["explosive_n"], r["n"]), axis=1)
    grouped["yards_per_play"] = grouped["yards"].round(2)
    grouped["down"] = pd.to_numeric(grouped["down"], errors="coerce")
    return grouped


def sequencing(era: Any = None, season: Any = None, exclude_garbage: bool = True) -> dict:
    plays = filter_plays(load_tables()["plays"], era=era, season=season, exclude_garbage=exclude_garbage)
    plays = plays[plays["prev_play_call"].isin(["Run", "Pass"])]

    def block(mask: pd.Series) -> dict:
        sub = plays[mask]
        n = len(sub)
        return {
            "n": n,
            "pass_rate": rate((sub["play_call"] == "Pass").sum(), n),
            "run_rate": rate((sub["play_call"] == "Run").sum(), n),
            "success_rate": rate(sub["success"].fillna(False).sum(), n),
        }

    return {
        "After a run": block(plays["prev_play_call"] == "Run"),
        "After a pass": block(plays["prev_play_call"] == "Pass"),
        "After success": block(plays["prev_success"] == True),  # noqa: E712
        "After failure": block(plays["prev_success"] == False),  # noqa: E712
        "After explosive (15+)": block(plays["prev_yards"].fillna(0) >= 15),
        "After stuffed run (≤1)": block((plays["prev_play_call"] == "Run") & (plays["prev_yards"].fillna(99) <= 1)),
        "After incompletion": block((plays["prev_play_call"] == "Pass") & (plays["prev_yards"].fillna(1) <= 0)),
    }


def situations(era: Any = None, season: Any = None, exclude_garbage: bool = True) -> pd.DataFrame:
    plays = filter_plays(load_tables()["plays"], era=era, season=season, exclude_garbage=exclude_garbage)

    def block(sub: pd.DataFrame, label: str) -> dict:
        n = len(sub)
        return {
            "Situation": label,
            "n": n,
            "Pass %": rate((sub["play_call"] == "Pass").sum(), n),
            "Success %": rate(sub["success"].fillna(False).sum(), n),
            "Explosive %": rate(sub["explosive"].fillna(False).sum(), n),
            "Yds/play": mean(sub["yards"]),
        }

    rows = [
        block(plays, "All scrimmage"),
        block(plays[plays["down"] == 1], "1st down"),
        block(plays[(plays["down"] == 2) & (plays["distance"].fillna(0) >= 8)], "2nd & long (8+)"),
        block(plays[(plays["down"] == 2) & (plays["distance"].fillna(99) <= 3)], "2nd & short (1-3)"),
        block(plays[plays["down"] == 3], "3rd down"),
        block(plays[(plays["down"] == 3) & (plays["distance"].fillna(99) <= 3)], "3rd & short"),
        block(plays[(plays["down"] == 3) & (plays["distance"].fillna(0) >= 7)], "3rd & long"),
        block(plays[plays["down"] == 4], "4th down"),
        block(plays[plays["red_zone"] == True], "Red zone"),  # noqa: E712
        block(plays[plays["goal_to_go"] == True], "Goal to go"),  # noqa: E712
        block(plays[plays["backed_up"] == True], "Backed up (own 1-20)"),  # noqa: E712
        block(plays[plays["plus_territory"] == True], "Plus territory"),  # noqa: E712
        block(plays[plays["shotgun"] == True], "Shotgun (text)"),  # noqa: E712
        block(plays[plays["no_huddle"] == True], "No-huddle (text)"),  # noqa: E712
        block(plays[plays["period"] == 1], "1st quarter"),
        block(plays[plays["period"] == 2], "2nd quarter"),
        block(plays[plays["period"] == 3], "3rd quarter"),
        block(plays[plays["period"] == 4], "4th quarter"),
    ]
    return pd.DataFrame(rows)


def era_table(exclude_garbage: bool = True) -> pd.DataFrame:
    tables = load_tables()
    plays = filter_plays(tables["plays"], exclude_garbage=exclude_garbage)
    drives = tables["drives"]
    games = tables["games"]
    rows = []
    for era_id, grp in games.groupby("era_id"):
        p = plays[plays["era_id"] == era_id]
        d = drives[drives["era_id"] == era_id]
        rows.append(
            {
                "Era": grp["era"].iloc[0],
                "Role": grp["role"].iloc[0],
                "Seasons": "–".join(str(s) for s in sorted(int(x) for x in grp["season"].dropna().unique())),
                "Games": int(len(grp)),
                "Plays": int(len(p)),
                "Pass %": rate((p["play_call"] == "Pass").sum(), len(p)),
                "1st-down pass %": rate(
                    (p.loc[p["down"] == 1, "play_call"] == "Pass").sum(),
                    int((p["down"] == 1).sum()),
                ),
                "Success %": rate(p["success"].fillna(False).sum(), len(p)),
                "Yds/play": mean(p["yards"]),
                "Pts/drive": mean(d["points"]),
                "TD drive %": rate((d["result"] == "TD").sum(), len(d)),
                "3-and-out %": rate(d["three_and_out"].fillna(False).sum(), len(d)),
            }
        )
    return pd.DataFrame(rows)


def game_list(era: Any = None, season: Any = None) -> pd.DataFrame:
    tables = load_tables()
    g = filter_frame(tables["games"], era=era, season=season)
    scrim = tables["plays"][tables["plays"]["scrimmage"] == True]  # noqa: E712
    stats = (
        scrim.groupby("game_id")
        .agg(
            pass_n=("play_call", lambda s: int((s == "Pass").sum())),
            n=("play_id", "count"),
            yards=("yards", "sum"),
        )
        .reset_index()
    )
    merged = g.merge(stats, on="game_id", how="left")
    merged["pass_rate"] = merged.apply(
        lambda r: rate(r["pass_n"], r["n"]) if pd.notna(r.get("n")) else None, axis=1
    )
    return merged.sort_values(["date", "game_id"]).reset_index(drop=True)


RUN_DIR_RE = re.compile(r"\brush(?:ed)?\s+(left|right|middle)\b", re.I)
PASS_DIR_RE = re.compile(r"\b(short|deep)\s+(left|right|middle)\b", re.I)
SIDE_ORDER = ["Left", "Middle", "Right"]
DEPTH_ORDER = ["Short", "Deep"]


def annotate_location(plays: pd.DataFrame) -> pd.DataFrame:
    out = plays.copy()
    text = out["description"].fillna("").astype(str)
    run_side = text.str.extract(RUN_DIR_RE, expand=False).str.title()
    pass_hit = text.str.extract(PASS_DIR_RE)
    pass_depth = pass_hit.iloc[:, 0].str.title() if pass_hit.shape[1] >= 1 else pd.Series(pd.NA, index=out.index)
    pass_side = pass_hit.iloc[:, 1].str.title() if pass_hit.shape[1] >= 2 else pd.Series(pd.NA, index=out.index)
    is_run = out["play_call"].eq("Run")
    is_pass = out["play_call"].eq("Pass")
    out["side"] = pd.NA
    out["depth"] = pd.NA
    out.loc[is_run, "side"] = run_side[is_run]
    out.loc[is_pass, "side"] = pass_side[is_pass]
    out.loc[is_pass, "depth"] = pass_depth[is_pass]
    out["location"] = pd.NA
    out.loc[is_run & out["side"].notna(), "location"] = "Run " + out["side"]
    out.loc[is_pass & out["side"].notna() & out["depth"].notna(), "location"] = (
        out["depth"] + " " + out["side"]
    )
    out["has_location"] = out["location"].notna()
    return out


def _dir_block(sub: pd.DataFrame) -> dict:
    n = len(sub)
    return {
        "n": n,
        "share": None,
        "yards_per_play": mean(sub["yards"]) if n else None,
        "success_rate": rate(sub["success"].fillna(False).sum(), n) if n else None,
        "explosive_rate": rate(sub["explosive"].fillna(False).sum(), n) if n else None,
    }


def direction_breakdown(era: Any = None, season: Any = None, exclude_garbage: bool = True) -> dict:
    plays = filter_plays(load_tables()["plays"], era=era, season=season, exclude_garbage=exclude_garbage)
    plays = annotate_location(plays)
    located = plays[plays["has_location"] == True]  # noqa: E712
    runs = located[located["play_call"] == "Run"]
    passes = located[located["play_call"] == "Pass"]
    run_rows = []
    for side in SIDE_ORDER:
        block = _dir_block(runs[runs["side"] == side])
        block["side"] = side
        run_rows.append(block)
    run_total = sum(r["n"] for r in run_rows)
    for row in run_rows:
        row["share"] = rate(row["n"], run_total)

    pass_rows = []
    for depth in DEPTH_ORDER:
        for side in SIDE_ORDER:
            block = _dir_block(passes[(passes["depth"] == depth) & (passes["side"] == side)])
            block["depth"] = depth
            block["side"] = side
            pass_rows.append(block)
    pass_total = sum(r["n"] for r in pass_rows)
    for row in pass_rows:
        row["share"] = rate(row["n"], pass_total)

    return {
        "plays": int(len(plays)),
        "located": int(len(located)),
        "coverage": rate(len(located), len(plays)),
        "run_located": int(len(runs)),
        "pass_located": int(len(passes)),
        "runs": run_rows,
        "passes": pass_rows,
    }


def game_drives(game_id: str) -> tuple[pd.Series, pd.DataFrame, pd.DataFrame]:
    tables = load_tables()
    games = tables["games"]
    match = games[games["game_id"].astype(str) == str(game_id)]
    if match.empty:
        raise KeyError(game_id)
    drives = tables["drives"][tables["drives"]["game_id"].astype(str) == str(game_id)].sort_values("drive_number")
    plays = tables["plays"][tables["plays"]["game_id"].astype(str) == str(game_id)].copy()
    return match.iloc[0], drives, plays
