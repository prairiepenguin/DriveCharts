"""Live (and replay) next-snap predictions for Oklahoma State."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.analysis import load_tables
from app.predict import WINDOWS, fit, score_game
from pipeline.classify import is_garbage_time
from pipeline.live import fetch_schedule, fetch_summary, next_snap, parse_live, pick_default_game

st.set_page_config(page_title="Live · Morris Playbook", page_icon="📡", layout="wide")
st.title("Live next snap")
st.caption(
    "Polls ESPN during an Oklahoma State game and predicts **pass vs run** for the upcoming snap "
    "from Morris's recent play-calling. This is a situation model, not the play on the call sheet. "
    "No-huddle can beat the ESPN delay."
)


def pct(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:.0%}"


def num(v, digits: int = 1) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:.{digits}f}"


@st.cache_data(ttl=20, show_spinner=False)
def cached_schedule():
    return fetch_schedule()


@st.cache_data(ttl=4, show_spinner=False)
def cached_summary(game_id: str):
    return fetch_summary(game_id)


@st.cache_resource
def cached_predictor(window: str):
    return fit(window)


def render_prediction(pred: dict) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Predicted call", pred["call"])
    c2.metric("P(pass)", pct(pred["p_pass"]))
    c3.metric("P(run)", pct(pred["p_run"]))
    st.caption(
        f"{pred['situation']} · based on {pred['n']:,} similar snaps ({pred['level']}) · {pred['window']}"
    )
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("If pass, yds", num(pred["pass_ypp"]))
    k2.metric("If run, yds", num(pred["run_ypp"]))
    k3.metric("Pass success", pct(pred["success_if_pass"]))
    k4.metric("Run success", pct(pred["success_if_run"]))


def last_plays_table(plays: list[dict] | pd.DataFrame, n: int = 8) -> None:
    if isinstance(plays, list):
        df = pd.DataFrame(plays)
    else:
        df = plays
    if df.empty:
        st.write("No plays yet.")
        return
    df = df[df["scrimmage"] == True] if "scrimmage" in df.columns else df  # noqa: E712
    df = df.tail(n)
    cols = [
        c
        for c in ["period", "clock", "down", "distance", "play_call", "yards", "description"]
        if c in df.columns
    ]
    st.dataframe(df[cols], width="stretch", hide_index=True)


window_key = st.selectbox(
    "Predict from",
    list(WINDOWS.keys()),
    format_func=lambda k: WINDOWS[k],
    index=0,
    help="Current Morris is North Texas 2023–25 plus Oklahoma State 2026. Use that for live OSU games.",
)
predictor = cached_predictor(window_key)

mode = st.radio("Mode", ["Live ESPN", "Replay a completed game"], horizontal=True)

if mode == "Live ESPN":
    try:
        schedule = cached_schedule()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load ESPN schedule: {exc}")
        st.stop()

    labels = {
        f"{r['date']} · {r['short'] or r['name']} · {r['detail'] or r['status']}": r["game_id"]
        for r in schedule
    }
    default = pick_default_game(schedule)
    default_label = next(
        (k for k, gid in labels.items() if default and gid == default["game_id"]),
        list(labels)[-1] if labels else None,
    )
    if not labels:
        st.warning("No Oklahoma State games found on the ESPN schedule.")
        st.stop()
    choice = st.selectbox(
        "Game",
        list(labels),
        index=list(labels).index(default_label) if default_label in labels else 0,
    )
    game_id = labels[choice]
    in_progress = bool(default and default["game_id"] == game_id and default.get("state") == "in")
    refresh = 5 if in_progress else 25

    @st.fragment(run_every=refresh)
    def live_panel() -> None:
        try:
            summary = cached_summary(game_id)
            game, drives, plays, status = parse_live(summary)
        except Exception as exc:  # noqa: BLE001
            st.error(f"ESPN poll failed: {exc}")
            return
        st.subheader(
            f"{game.get('team_abbrev')} {game.get('team_score')}–{game.get('opp_score')} {game.get('opponent_abbrev')}"
        )
        st.caption(status.get("detail") or status.get("phase") or "")
        nxt = next_snap(summary, game, plays)
        st.info(nxt.get("note") or nxt["phase"])
        if nxt.get("last_text"):
            st.write(f"Last play: {nxt['last_text']}")
        if nxt.get("phase") == "offense" and nxt.get("situation"):
            sit = nxt["situation"]
            if is_garbage_time(sit.get("period"), sit.get("score_diff"), sit.get("clock")):
                st.warning("Garbage time — Morris often runs here. The model was trained without these snaps.")
            pred = predictor.predict(sit, exclude_game_id=None)
            render_prediction(pred)
        last_plays_table(plays)
        if drives:
            st.caption(f"{len(drives)} Oklahoma State drives so far")

    live_panel()

else:
    tables = load_tables()
    games = tables["games"]
    games = games[games["era_id"] == "osu"].sort_values("date")
    if games.empty:
        games = tables["games"].sort_values("date").tail(12)
    games = games.copy()
    games["label"] = games.apply(
        lambda r: f"{r['date']} {r.get('result','')} {r.get('team_score')}–{r.get('opp_score')} vs {r.get('opponent_abbrev') or r.get('opponent')}",
        axis=1,
    )
    pick = st.selectbox("Replay game", games["label"].tolist(), index=len(games) - 1)
    game_id = str(games.loc[games["label"] == pick, "game_id"].iloc[0])

    @st.cache_data(show_spinner="Scoring snaps…")
    def cached_replay(gid: str, window: str) -> pd.DataFrame:
        return score_game(gid, window)

    scored = cached_replay(game_id, window_key)
    if scored.empty:
        st.warning("No scrimmage plays for that game.")
        st.stop()
    n_snaps = int(len(scored))

    if st.session_state.get("replay_gid") != game_id:
        st.session_state.replay_gid = game_id
        st.session_state.replay_snap = 1
        st.session_state.replay_playing = False
        st.session_state.replay_phase = "predict"
    st.session_state.setdefault("replay_snap", 1)
    st.session_state.setdefault("replay_playing", False)
    st.session_state.setdefault("replay_phase", "predict")
    st.session_state.replay_snap = min(max(int(st.session_state.replay_snap), 1), n_snaps)

    speed = st.select_slider("Playback speed", options=["0.5x", "1x", "2x", "4x"], value="1x")
    delay = {"0.5x": 3.0, "1x": 1.8, "2x": 1.0, "4x": 0.55}[speed]

    b1, b2, b3, b4, b5 = st.columns(5)
    with b1:
        if st.button("Play", type="primary", disabled=st.session_state.replay_playing, width="stretch"):
            st.session_state.replay_playing = True
            st.session_state.replay_phase = "predict"
            st.rerun()
    with b2:
        if st.button("Pause", disabled=not st.session_state.replay_playing, width="stretch"):
            st.session_state.replay_playing = False
            st.rerun()
    with b3:
        if st.button("Restart", width="stretch"):
            st.session_state.replay_snap = 1
            st.session_state.replay_playing = False
            st.session_state.replay_phase = "predict"
            st.rerun()
    with b4:
        if st.button("Back", disabled=st.session_state.replay_snap <= 1, width="stretch"):
            st.session_state.replay_snap -= 1
            st.session_state.replay_playing = False
            st.session_state.replay_phase = "reveal"
            st.rerun()
    with b5:
        if st.button("Next", disabled=st.session_state.replay_snap >= n_snaps, width="stretch"):
            st.session_state.replay_snap += 1
            st.session_state.replay_playing = False
            st.session_state.replay_phase = "reveal"
            st.rerun()

    @st.fragment(run_every=delay if st.session_state.replay_playing else None)
    def replay_player() -> None:
        snap = int(st.session_state.replay_snap)
        row = scored.iloc[snap - 1]
        playing = bool(st.session_state.replay_playing)
        phase = st.session_state.replay_phase if playing else "reveal"
        st.progress((snap - 1) / max(n_snaps - 1, 1), text=f"Snap {snap} of {n_snaps}")
        st.subheader(f"Snap {snap} of {n_snaps}")
        st.caption(f"Q{row.get('period')} {row.get('clock') or ''} · {row.get('yardline_text') or ''}")
        pred = {
            "call": row["predicted"],
            "p_pass": row["p_pass"],
            "p_run": row["p_run"],
            "n": row["n"],
            "level": row["level"],
            "window": row["window"],
            "situation": row["situation"],
            "pass_ypp": row["pass_ypp"],
            "run_ypp": row["run_ypp"],
            "success_if_pass": row["success_if_pass"],
            "success_if_run": row["success_if_run"],
        }
        render_prediction(pred)
        if phase == "predict":
            st.info("Waiting for the snap…")
        else:
            actual = row["actual"]
            yards = int(row["yards"] or 0)
            if row["hit"]:
                st.success(f"Actual call: **{actual}** · {yards} yards")
            else:
                st.error(f"Actual call: **{actual}** · {yards} yards")
            st.write(row.get("description") or "")

        through = scored.iloc[:snap]
        core = through[through["garbage_time"] != True]  # noqa: E712
        if core.empty:
            core = through
        full = scored[scored["garbage_time"] != True]  # noqa: E712
        if full.empty:
            full = scored
        a1, a2, a3 = st.columns(3)
        a1.metric("Accuracy so far", pct(float(core["hit"].mean())), help="Predicted pass if P(pass) ≥ 50%.")
        a2.metric("Brier so far", num(float(core["brier"].mean()), 3), help="0 is perfect. 0.25 is a coin flip.")
        a3.metric("Full-game accuracy", pct(float(full["hit"].mean())))
        shown = scored.iloc[:snap].copy()
        shown["play_call"] = shown["actual"]
        last_plays_table(shown, n=12)

        if playing:
            if phase == "predict":
                st.session_state.replay_phase = "reveal"
            elif snap < n_snaps:
                st.session_state.replay_snap = snap + 1
                st.session_state.replay_phase = "predict"
            else:
                st.session_state.replay_playing = False
                st.session_state.replay_phase = "reveal"
                st.rerun()

    replay_player()
