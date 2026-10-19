"""Pull completed games from ESPN into the local parquet tables."""

from __future__ import annotations

import fcntl
import threading
from pathlib import Path

import pandas as pd
import streamlit as st

from pipeline.ingest import ingest

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = Path("/tmp/morris-playbook-ingest.lock")
_LOCK = threading.Lock()


def _brief(row: pd.Series) -> str:
    abbrev = row.get("opponent_abbrev") or row.get("opponent") or "OPP"
    try:
        score_us = int(row["team_score"])
        score_them = int(row["opp_score"])
    except (TypeError, ValueError):
        score_us, score_them = 0, 0
    result = row.get("result") or ""
    return f"{row['date']} {result} {score_us}-{score_them} {abbrev}"


def refresh_games() -> dict:
    """Download newly completed games and rewrite the parquet tables.

    Games already saved under data/raw are not downloaded again.
    """
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("An update is already running.")
    try:
        LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOCK_PATH.open("a+") as lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RuntimeError("An update is already running.") from exc
            games_path = ROOT / "data" / "games.parquet"
            before: set[str] = set()
            if games_path.exists():
                previous = pd.read_parquet(games_path, columns=["game_id"])
                before = set(previous["game_id"].astype(str))
            meta = ingest(refresh=False)
            current = pd.read_parquet(games_path)
            current["game_id"] = current["game_id"].astype(str)
            added_rows = current[~current["game_id"].isin(before)].sort_values(["date", "game_id"])
            return {
                "n_games": int(meta["n_games"]),
                "n_scrimmage": int(meta["n_scrimmage"]),
                "added": [_brief(row) for _, row in added_rows.iterrows()],
            }
    finally:
        _LOCK.release()


def render_update_control() -> None:
    """Sidebar button that refreshes the dataset and reloads the page."""
    note = st.session_state.pop("update_note", None)
    if note:
        st.success(note["body"], title=note["title"], icon=":material/refresh:")
    with st.sidebar:
        clicked = st.button(
            "Update games",
            icon=":material/refresh:",
            width="stretch",
            key="update_games",
            help=(
                "Download completed games from ESPN into this running app. "
                "A restart goes back to the last files pushed to GitHub."
            ),
        )
    if not clicked:
        return
    try:
        with st.spinner("Checking ESPN for completed games…"):
            result = refresh_games()
    except Exception as exc:  # noqa: BLE001 - show the failure on the page
        st.error(str(exc), title="Update failed")
        return
    st.cache_data.clear()
    st.cache_resource.clear()
    added = result["added"]
    if added:
        body = f"Added {len(added)}: {', '.join(added)}."
        title = "Games updated"
    else:
        body = f"{result['n_games']} games. No new completed games on ESPN."
        title = "Already up to date"
    st.session_state["update_note"] = {"title": title, "body": body}
    st.rerun()
