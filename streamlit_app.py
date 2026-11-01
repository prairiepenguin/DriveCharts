"""Streamlit app for Eric Morris play-selection analysis."""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import analysis
from app.refresh import render_update_control
from app.ui import metric_row

st.set_page_config(page_title="Morris Playbook", page_icon="🏈", layout="wide")

PLOTLY_CONFIG = {"displayModeBar": False}


def pct(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:.0%}"


def num(v, digits: int = 1) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:.{digits}f}"


@st.cache_data(show_spinner=False)
def cached_meta():
    return analysis.meta()


def era_arg(label: str, info: dict) -> str | None:
    if label == "All eras":
        return None
    for era in info["eras"]:
        if label.startswith(era["era"]):
            return era["era_id"]
    return None


def heatmap(df: pd.DataFrame) -> go.Figure:
    buckets = analysis.DISTANCE_BUCKETS
    downs = [1, 2, 3, 4]
    z, text, hover = [], [], []
    for down in downs:
        zr, tr, hr = [], [], []
        for bucket in buckets:
            hit = df[(df["down"] == down) & (df["distance_bucket"] == bucket)]
            if hit.empty:
                zr.append(None)
                tr.append("")
                hr.append(f"{down} & {bucket}<br>No plays")
            else:
                row = hit.iloc[0]
                zr.append(None if pd.isna(row["pass_rate"]) else row["pass_rate"] * 100)
                tr.append(f"{pct(row['pass_rate'])}<br>n={int(row['n'])}")
                hr.append(
                    f"{down} & {bucket}<br>Pass rate: {pct(row['pass_rate'])}"
                    f"<br>n={int(row['n'])}"
                    f"<br>Success: {pct(row['success_rate'])}"
                    f"<br>Yds/play: {num(row['yards_per_play'])}"
                )
        z.append(zr)
        text.append(tr)
        hover.append(hr)

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=buckets,
            y=["1st", "2nd", "3rd", "4th"],
            text=text,
            texttemplate="%{text}",
            hovertext=hover,
            hoverinfo="text",
            colorscale=[
                [0.0, "#2f9e5f"],
                [0.5, "#c4b44a"],
                [1.0, "#ff6a12"],
            ],
            zmin=30,
            zmax=80,
            colorbar=dict(title="Pass %", ticksuffix="%"),
            xgap=4,
            ygap=4,
        )
    )
    fig.update_yaxes(autorange="reversed")
    fig.update_layout(
        margin=dict(l=32, r=4, t=4, b=32),
        height=340,
        xaxis_title="Yards to go",
        yaxis_title="Down",
        plot_bgcolor="#0a100c",
        paper_bgcolor="#0a100c",
        font=dict(color="#e7f0e4", size=12),
    )
    fig.update_traces(
        textfont_size=11,
        colorbar=dict(title="", ticksuffix="%", thickness=8, len=0.7),
    )
    return fig


def _field_x(yards_to_endzone) -> float | None:
    try:
        yte = float(yards_to_endzone)
    except (TypeError, ValueError):
        return None
    return 100.0 - yte


def drive_summary(row: pd.Series) -> str:
    plays_n = row.get("scrimmage_plays") or row.get("offensive_plays") or 0
    yards = row.get("yards") or 0
    clock = row.get("time_elapsed") or ""
    start = row.get("start_text") or ""
    return (
        f"Drive {int(row['drive_number'])} · {start} → {row.get('result')} · "
        f"{plays_n} plays · {yards} yds · {clock}"
    ).strip()


def drive_field_chart(drives: pd.DataFrame, plays: pd.DataFrame, selected_id: str) -> go.Figure:
    """Each offensive drive as a line from its start spot toward the opponent goal."""
    fig = go.Figure()
    fig.add_vrect(x0=0, x1=20, fillcolor="rgba(61,207,122,0.07)", line_width=0)
    fig.add_vrect(x0=80, x1=100, fillcolor="rgba(255,106,18,0.10)", line_width=0)
    for yard in (0, 20, 50, 80, 100):
        fig.add_vline(x=yard, line_color="#243028", line_width=1)

    ordered = drives.sort_values("drive_number")
    selected = ordered[ordered["drive_id"].astype(str) == str(selected_id)]
    rest = ordered[ordered["drive_id"].astype(str) != str(selected_id)]
    for frame, emphasis in ((rest, False), (selected, True)):
        for _, drv in frame.iterrows():
            start_x = _field_x(drv.get("start_yards_to_endzone"))
            if start_x is None:
                start_x = 25.0
            try:
                gained = float(drv.get("yards") or 0)
            except (TypeError, ValueError):
                gained = 0.0
            end_x = start_x + gained
            number = int(drv["drive_number"])
            color = analysis.RESULT_COLORS.get(drv.get("result"), "#6d7c70")
            label = drive_summary(drv)
            fig.add_trace(
                go.Scatter(
                    x=[start_x, end_x],
                    y=[number, number],
                    mode="lines+markers+text",
                    line=dict(color=color, width=8 if emphasis else 4),
                    marker=dict(size=[7, 12] if emphasis else [5, 8], color=color),
                    text=["", str(drv.get("result") or "")],
                    textposition="middle right",
                    textfont=dict(color="#e7f0e4", size=11),
                    customdata=[[str(drv["drive_id"]), label], [str(drv["drive_id"]), label]],
                    hovertemplate="%{customdata[1]}<extra></extra>",
                    showlegend=False,
                    opacity=1 if emphasis else 0.45,
                )
            )

    chosen = plays[plays["drive_id"].astype(str) == str(selected_id)]
    chosen = chosen[chosen["scrimmage"] == True]  # noqa: E712
    if not chosen.empty and not selected.empty:
        number = int(selected.iloc[0]["drive_number"])
        xs, calls, texts = [], [], []
        for _, play in chosen.sort_values(["drive_play_number", "sequence_number"], na_position="last").iterrows():
            spot = _field_x(play.get("yards_to_endzone"))
            if spot is None:
                continue
            xs.append(spot)
            calls.append("#ff6a12" if play.get("play_call") == "Pass" else "#7eb6ff")
            down = play.get("down")
            dist = play.get("distance")
            texts.append(
                f"{down} & {dist} {play.get('play_call') or ''} {play.get('yards') or 0} yds"
            )
        if xs:
            fig.add_trace(
                go.Scatter(
                    x=xs,
                    y=[number] * len(xs),
                    mode="markers",
                    marker=dict(size=9, color=calls, line=dict(color="#0a100c", width=1)),
                    customdata=[[str(selected_id), text] for text in texts],
                    hovertemplate="%{customdata[1]}<extra></extra>",
                    showlegend=False,
                )
            )

    n_drives = max(int(len(ordered)), 1)
    fig.update_xaxes(
        range=[-4, 112],
        tickmode="array",
        tickvals=[0, 20, 40, 50, 60, 80, 100],
        ticktext=["Own", "20", "40", "50", "40", "20", "Goal"],
        title="Own goal line to opponent goal line",
        gridcolor="#1a241c",
        zeroline=False,
    )
    fig.update_yaxes(
        autorange="reversed",
        dtick=1,
        title="Drive",
        gridcolor="#1a241c",
    )
    fig.update_layout(
        height=max(320, 36 * n_drives + 80),
        margin=dict(l=48, r=48, t=12, b=48),
        plot_bgcolor="#0a100c",
        paper_bgcolor="#0a100c",
        font=dict(color="#e7f0e4", size=12),
        hovermode="closest",
    )
    return fig


def open_logged_game(gid: str) -> None:
    # Bound widgets update their URL parameters from session state.
    st.session_state["view"] = "Drive charts"
    st.session_state["game"] = gid


def chart_drive_id(event, valid: set[str]) -> str | None:
    if not event:
        return None
    selection = event.get("selection") if isinstance(event, dict) else getattr(event, "selection", None)
    points = []
    if selection is not None:
        points = selection.get("points") if isinstance(selection, dict) else getattr(selection, "points", [])
    if not points:
        return None
    custom = points[0].get("customdata")
    if isinstance(custom, (list, tuple)):
        custom = custom[0] if custom else None
    text = "" if custom is None else str(custom)
    return text if text in valid else None


def game_option_label(row: pd.Series) -> str:
    abbrev = row.get("opponent_abbrev") or row.get("opponent") or "OPP"
    try:
        score_us = int(row["team_score"])
        score_them = int(row["opp_score"])
    except (TypeError, ValueError):
        score_us, score_them = 0, 0
    result = row.get("result") or ""
    return f"{row['date']} {result} {score_us}-{score_them} {abbrev} {row['game_id']}"


def linked_game_id(raw: object, ids: list[str]) -> str | None:
    """Match a query value to a game id, including older share-link labels."""
    if isinstance(raw, (list, tuple)):
        raw = raw[0] if raw else None
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    known = set(ids)
    if text in known:
        return text
    for token in reversed(text.split()):
        if token in known:
            return token
    return None


def game_share_url(label: str) -> str:
    """Absolute link when the app knows its host, otherwise just the query."""
    query = urlencode({"view": "Drive charts", "game": label})
    parts = urlsplit(st.context.url or "")
    if not parts.scheme or not parts.netloc:
        return f"?{query}"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def url_has_query_key(key: str) -> bool:
    url = st.context.url or ""
    query = url.split("?", 1)[1] if "?" in url else ""
    return any(part.split("=", 1)[0] == key for part in query.split("&") if part)


def play_table(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    show = df.copy()
    cols = [
        c
        for c in [
            "date", "era", "opponent", "drive_number", "period", "clock",
            "down", "distance", "yardline_text", "play_call", "play_detail",
            "yards", "success", "description",
        ]
        if c in show.columns
    ]
    return show[cols]


def rate_table(
    rows: list[dict],
    columns: list[tuple[str, str]],
    percent: set[str],
    alt: str,
    one_decimal: set[str] | None = None,
) -> None:
    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("No plays in this slice.")
        return
    rename = {src: label for src, label in columns}
    show = frame.rename(columns=rename)[[label for _, label in columns]]
    decimals = {"Yds/play", "Pts/trip"} | (one_decimal or set())
    config = {}
    for label in rename.values():
        if label in percent:
            config[label] = st.column_config.NumberColumn(format="percent", step=0.01)
        elif label in decimals:
            config[label] = st.column_config.NumberColumn(format="%.1f")
    label_col = show.columns[0]
    if label_col not in config:
        config[label_col] = st.column_config.TextColumn(pinned=True)
    st.dataframe(show, width="stretch", hide_index=True, column_config=config)


def show_plays(frame: pd.DataFrame, alt: str) -> None:
    """Play list with the call frozen while the rest of the row scrolls."""
    config = {}
    if "play_call" in frame.columns:
        config["play_call"] = st.column_config.TextColumn("play_call", pinned=True)
    st.dataframe(frame, width="stretch", hide_index=True, column_config=config)


ENOUGH_LABEL = "Enough for the down*"
ENOUGH_NOTE = (
    "* Enough for the down is the share of plays that did what the down asked: "
    "a touchdown, a first down, at least half the yards to go on first down, "
    "70% on second down, or the full distance on third and fourth."
)


def _grouped_chart(frame: pd.DataFrame, x: str, y: str, alt: str, horizontal: bool = False) -> None:
    if frame.empty or frame[y].isna().all():
        return
    st.bar_chart(
        frame,
        x=x,
        y=y,
        color="Side",
        x_label=x,
        y_label=y,
        horizontal=horizontal,
        sort=False,
        stack=False,
    )


def _rate_frame(pairs: list[tuple[str, list[dict]]], key: str, rate_key: str, x_name: str, y_name: str) -> pd.DataFrame:
    order: list = []
    maps = []
    for side, rows in pairs:
        mapping = {}
        for row in rows:
            mapping[row[key]] = row
            if row[key] not in order:
                order.append(row[key])
        maps.append((side, mapping))
    out = []
    for name in order:
        for side, mapping in maps:
            row = mapping.get(name)
            value = None if row is None else row.get(rate_key)
            out.append({x_name: name, "Side": side, y_name: None if value is None else round(float(value) * 100, 1)})
    return pd.DataFrame(out)


def _both_tables(history_rows, osu_rows, columns, percents, alt: str, one_decimal: set[str] | None = None) -> None:
    st.markdown("**History**")
    rate_table(history_rows, columns, percents, f"{alt}, history", one_decimal)
    st.markdown("**Oklahoma State**")
    rate_table(osu_rows, columns, percents, f"{alt}, Oklahoma State", one_decimal)


def _rz_kpis(report: dict) -> None:
    summary = report["summary"]
    trip = report["trip"]
    metric_row(
        [
            ("Trips", f"{report['trips']:,}", "Drives that reached the red zone"),
            ("Trip TD rate", pct(trip["td_rate"]), "Trips that ended in a touchdown"),
            ("Trips scored", pct(trip["score_rate"]), "Trips that ended in a touchdown or a made field goal"),
            ("Points / trip", num(trip["points_per_trip"]), "Six for a touchdown, three for a field goal"),
            ("Pass rate", pct(summary["pass_rate"]), "Share of scrimmage snaps that were passes"),
            (ENOUGH_LABEL, pct(summary["success_rate"]), "A touchdown, a first down, half the yards on first down, 70% on second, or the full distance on third and fourth"),
        ],
        border=True,
    )


def _snap_caption(report: dict, name: str) -> str:
    summary = report["summary"]
    return (
        f"{name}: {summary['n']:,} scrimmage snaps. Pass rate is {pct(summary['pass_rate'])} here and "
        f"{pct(report['rest_pass_rate'])} on the other {report['rest_plays']:,} snaps. "
        f"Snap touchdowns: {summary['rush_td']:,} rushing, {summary['pass_td']:,} passing. "
        f"Turnovers on {pct(summary['turnover_rate'])} of snaps."
    )


CALL_COLUMNS = [
    ("slice", "Slice"),
    ("n", "Plays"),
    ("pass_rate", "Pass"),
    ("success_rate", "Success"),
    ("td_rate", "TD on the snap"),
    ("yards_per_play", "Yds/play"),
]
CALL_PERCENTS = {"Pass", "Success", "TD on the snap"}
BAND_COLUMNS = [
    ("spot", "Spot"),
    ("n", "Plays"),
    ("pass_rate", "Pass"),
    ("first_down_pass_rate", "1st-down pass"),
    ("success_rate", "Success"),
    ("td_rate", "TD on the snap"),
    ("yards_per_play", "Yds/play"),
]
BAND_PERCENTS = {"Pass", "1st-down pass", "Success", "TD on the snap"}
FOURTH_COLUMNS = [
    ("spot", "Spot"),
    ("n", "Snaps"),
    ("kick", "Kick"),
    ("made", "Made"),
    ("go", "Go"),
    ("pass_rate", "Pass when they go"),
    ("success_rate", "Success when they go"),
    ("td_rate", "TD when they go"),
]
FOURTH_PERCENTS = {"Pass when they go", "Success when they go", "TD when they go"}
SPLIT_VALUE_COLUMNS = [
    ("trips", "Trips"),
    ("td_trip_rate", "TD trips"),
    ("score_rate", "Trips scored"),
    ("points_per_trip", "Pts/trip"),
    ("n", "Plays"),
    ("pass_rate", "Pass"),
    ("first_down_pass_rate", "1st-down pass"),
    ("inside5_pass_rate", "Inside the 5"),
    ("goal_pass_rate", "Goal to go"),
    ("success_rate", ENOUGH_LABEL),
]
SPLIT_PERCENTS = {"TD trips", "Trips scored", "Pass", "1st-down pass", "Inside the 5", "Goal to go", ENOUGH_LABEL}


def _split_columns(split_kind: str) -> list[tuple[str, str]]:
    label = "Season" if split_kind == "season" else "Era"
    return [("label", label), *SPLIT_VALUE_COLUMNS]


def _end_note(trip: dict) -> str:
    return (
        f"Made field goals {pct(trip['fg_rate'])}. "
        f"Missed field goals {pct(trip['missed_fg_rate'])}. "
        f"Turnovers {pct(trip['turnover_rate'])}. "
        f"Downs {pct(trip['downs_rate'])}."
    )


def _shotgun_block(report: dict, alt: str) -> None:
    gun = report["shotgun"]
    if not gun:
        st.info("No shotgun tag in this sample.")
        return
    st.caption(
        "Shotgun is read from the ESPN play text for "
        + " and ".join(gun["eras"])
        + ". Plays without the word are grouped as under center, which can include shotgun snaps ESPN did not label."
    )
    metric_row(
        [
            ("Shotgun snaps", f"{gun['shotgun_n']:,}", f"Of {gun['n']:,} snaps in tagged seasons"),
            ("Pass rate from shotgun", pct(gun["from_gun"]["pass_rate"]), None),
        ],
        border=True,
    )
    rate_table(
        [
            {"look": "Shotgun", **gun["from_gun"]},
            {"look": "No shotgun tag", **gun["under_center"]},
        ],
        [
            ("look", "Look"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("success_rate", "Success"),
            ("td_rate", "TD on the snap"),
            ("yards_per_play", "Yds/play"),
        ],
        {"Pass", "Success", "TD on the snap"},
        alt,
    )


def _direction_block(report: dict) -> None:
    direction = report["direction"]
    st.caption(
        f"ESPN tagged a direction on {direction['located']:,} of {direction['plays']:,} snaps "
        f"({pct(direction['coverage'])})."
    )
    if not direction["located"]:
        st.info("No direction tags in this sample.")
        return
    left, right = st.columns(2)
    with left:
        st.markdown("**Runs**")
        rate_table(
            direction["runs"],
            [
                ("side", "Direction"),
                ("n", "Plays"),
                ("share", "Share"),
                ("success_rate", "Success"),
                ("yards_per_play", "Yds/play"),
            ],
            {"Share", "Success"},
            "Red-zone run direction",
        )
    with right:
        st.markdown("**Passes**")
        rate_table(
            direction["passes"],
            [
                ("depth", "Depth"),
                ("side", "Direction"),
                ("n", "Plays"),
                ("share", "Share"),
                ("success_rate", "Success"),
                ("yards_per_play", "Yds/play"),
            ],
            {"Share", "Success"},
            "Red-zone pass depth and direction",
        )


def _plays_block(report: dict, download_key: str, file_name: str) -> None:
    show = play_table(report["plays_frame"].sort_values(["date", "drive_number", "drive_play_number"], na_position="last"))
    st.caption(f"{len(show):,} snaps. The table shows the latest 300.")
    show_plays(show.tail(300), "Red-zone scrimmage plays")
    st.download_button(
        "Download red-zone plays (CSV)",
        show.to_csv(index=False).encode("utf-8"),
        file_name=file_name,
        mime="text/csv",
        key=download_key,
    )


def render_rz_compare(drop_garbage: bool) -> None:
    history = analysis.red_zone_report(exclude_era="osu", exclude_garbage=drop_garbage)
    osu = analysis.red_zone_report(era="osu", exclude_garbage=drop_garbage)
    st.caption(
        "The same red-zone charts as Everything. History is Texas Tech, Incarnate Word, Washington State, and North Texas. "
        "Oklahoma State is the 2026 season. Bars show both samples side by side. "
        "This comparison ignores the era and season filters above. The garbage-time box still applies."
    )
    st.markdown("**History**")
    _rz_kpis(history)
    st.markdown("**Oklahoma State**")
    _rz_kpis(osu)
    st.caption(ENOUGH_NOTE)
    st.caption(_snap_caption(history, "History"))
    st.caption(_snap_caption(osu, "Oklahoma State"))

    st.subheader("How the drive ends")
    _grouped_chart(
        _rate_frame(
            (("History", history["trip"]["results"]), ("Oklahoma State", osu["trip"]["results"])),
            "result",
            "share",
            "Drive result",
            "Share of trips (%)",
        ),
        "Drive result",
        "Share of trips (%)",
        "Share of red-zone trips by drive result, history and Oklahoma State side by side",
        horizontal=True,
    )
    st.markdown("**History**")
    st.caption(_end_note(history["trip"]))
    rate_table(
        history["trip"]["results"],
        [("result", "Result"), ("n", "Trips"), ("share", "Share")],
        {"Share"},
        "Share of history red-zone trips by drive result",
    )
    st.markdown("**Oklahoma State**")
    st.caption(_end_note(osu["trip"]))
    rate_table(
        osu["trip"]["results"],
        [("result", "Result"), ("n", "Trips"), ("share", "Share")],
        {"Share"},
        "Share of Oklahoma State red-zone trips by drive result",
    )

    st.subheader("The call by how close they are")
    st.caption(
        "Inside the 5 he runs more often, and a much larger share of those snaps score. "
        "From 11 to 20 the call is closer to a normal down."
    )
    _grouped_chart(
        _rate_frame(
            (("History", history["bands"]), ("Oklahoma State", osu["bands"])),
            "spot",
            "pass_rate",
            "Yards to the end zone",
            "Pass rate (%)",
        ),
        "Yards to the end zone",
        "Pass rate (%)",
        "Red-zone pass rate by field position, history and Oklahoma State side by side",
    )
    _both_tables(history["bands"], osu["bands"], BAND_COLUMNS, BAND_PERCENTS, "Red-zone call and result by yards to the end zone")

    st.subheader("Down and distance")
    st.caption("Yards to go for a first down, only on snaps already inside the 20. Green is more run, orange is more pass.")
    heat_left, heat_right = st.columns(2)
    with heat_left:
        st.markdown("**History**")
        st.plotly_chart(heatmap(history["down_distance"]), width="stretch", config=PLOTLY_CONFIG)
    with heat_right:
        st.markdown("**Oklahoma State**")
        st.plotly_chart(heatmap(osu["down_distance"]), width="stretch", config=PLOTLY_CONFIG)

    st.subheader("Goal to go")
    st.caption("Goal to go means the line to gain is the goal line, not just that the ball is inside the 20.")
    _both_tables(
        [
            {"slice": "Inside the 20, not goal to go", **history["not_goal"]},
            {"slice": "Goal to go", **history["goal_to_go"]},
            {"slice": "1st and goal", **history["first_and_goal"]},
        ],
        [
            {"slice": "Inside the 20, not goal to go", **osu["not_goal"]},
            {"slice": "Goal to go", **osu["goal_to_go"]},
            {"slice": "1st and goal", **osu["first_and_goal"]},
        ],
        CALL_COLUMNS,
        CALL_PERCENTS,
        "Red-zone calls on goal to go and on 1st and goal",
    )

    st.subheader("Fourth down: kick or go")
    st.caption(
        "A snap counts when it was a run, a pass, or a field goal. "
        "Penalties and timeouts are left out. Made field goals are kicks whose ESPN type says good."
    )
    _both_tables(history["fourth"], osu["fourth"], FOURTH_COLUMNS, FOURTH_PERCENTS, "Fourth-down field goals and go-for-it calls in the red zone")

    st.subheader("The snap that gets them there, and what follows")
    st.caption(
        "The first snap is the first scrimmage play of the drive inside the 20. "
        "Later rows are only snaps after another red-zone play on that same drive."
    )
    _both_tables(
        [{"situation": name, **block} for name, block in history["sequence"].items()],
        [{"situation": name, **block} for name, block in osu["sequence"].items()],
        [
            ("situation", "Situation"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("success_rate", "Success"),
            ("td_rate", "TD on the snap"),
            ("yards_per_play", "Yds/play"),
        ],
        CALL_PERCENTS,
        "Red-zone pass rate on the entry snap and on later snaps",
    )

    st.subheader("Score margin")
    _both_tables(
        history["score"],
        osu["score"],
        [
            ("situation", "Margin"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("success_rate", "Success"),
            ("td_rate", "TD on the snap"),
            ("yards_per_play", "Yds/play"),
        ],
        CALL_PERCENTS,
        "Red-zone pass rate by score margin",
    )

    st.subheader("By era")
    st.markdown("**History**")
    rate_table(
        history["splits"],
        _split_columns(history["split_kind"]),
        SPLIT_PERCENTS,
        "Red-zone trips and pass rate by era before Oklahoma State",
    )
    st.markdown("**Oklahoma State**")
    rate_table(
        osu["splits"],
        _split_columns(osu["split_kind"]),
        SPLIT_PERCENTS,
        "Oklahoma State red-zone trips and pass rate by season",
    )

    st.subheader("What the snap was")
    _grouped_chart(
        _rate_frame(
            (("History", history["details"]), ("Oklahoma State", osu["details"])),
            "detail",
            "share",
            "Play",
            "Share of snaps (%)",
        ),
        "Play",
        "Share of snaps (%)",
        "Red-zone snaps by play type, history and Oklahoma State side by side",
        horizontal=True,
    )

    st.subheader("Shotgun")
    st.markdown("**History**")
    _shotgun_block(history, "History red-zone calls from shotgun and without a shotgun tag")
    st.markdown("**Oklahoma State**")
    _shotgun_block(osu, "Oklahoma State red-zone calls from shotgun and without a shotgun tag")

    st.subheader("Where it went")
    st.caption("Tech, UIW, and Washington State have no direction tags. North Texas late in 2025 and Oklahoma State 2026 are where the tags exist.")
    st.markdown("**History**")
    _direction_block(history)
    st.markdown("**Oklahoma State**")
    _direction_block(osu)

    st.subheader("Plays")
    st.markdown("**History**")
    _plays_block(history, "rz_csv_history", "morris_red_zone_history.csv")
    st.markdown("**Oklahoma State**")
    _plays_block(osu, "rz_csv_osu", "morris_red_zone_osu.csv")


def render_red_zone(era: str | None, season: str | None, drop_garbage: bool) -> None:
    compare = st.segmented_control(
        "Sample",
        ["Everything", "History vs Oklahoma State"],
        default="Everything",
        key="rz_compare",
        required=True,
        width="stretch",
        help="Everything uses the era and season filters above. History vs Oklahoma State shows the same charts for every earlier stop and for the 2026 Oklahoma State season.",
    )
    if compare == "History vs Oklahoma State":
        render_rz_compare(drop_garbage)
        return
    report = analysis.red_zone_report(era=era, season=season, exclude_garbage=drop_garbage)
    st.caption(
        "The red zone is the opponent's 20-yard line through the goal line. "
        "A trip is a drive with at least one scrimmage snap there. "
        "Pass rate counts sacks and scrambles as passes. "
        "Points per trip are 6 for a touchdown and 3 for a field goal, without the extra point."
    )
    if report["plays"] == 0:
        st.info("No red-zone scrimmage plays in this filter.")
        return

    summary = report["summary"]
    trip = report["trip"]
    metric_row(
        [
            ("Trips", f"{report['trips']:,}", "Drives that reached the red zone"),
            ("Trip TD rate", pct(trip["td_rate"]), "Trips that ended in a touchdown"),
            ("Trips scored", pct(trip["score_rate"]), "Trips that ended in a touchdown or a made field goal"),
            ("Points / trip", num(trip["points_per_trip"]), "Six for a touchdown, three for a field goal"),
            ("Pass rate", pct(summary["pass_rate"]), "Share of scrimmage snaps that were passes"),
            (ENOUGH_LABEL, pct(summary["success_rate"]), "A touchdown, a first down, half the yards on first down, 70% on second, or the full distance on third and fourth"),
        ],
        border=True,
    )
    st.caption(ENOUGH_NOTE)
    rest = report["rest_pass_rate"]
    st.caption(
        f"{summary['n']:,} scrimmage snaps. Pass rate is {pct(summary['pass_rate'])} here and "
        f"{pct(rest)} on the other {report['rest_plays']:,} snaps in this filter. "
        f"Snap touchdowns: {summary['rush_td']:,} rushing, {summary['pass_td']:,} passing. "
        f"Turnovers on {pct(summary['turnover_rate'])} of snaps."
    )

    st.subheader("How the drive ends")
    end_chart, end_note = st.columns([1, 1])
    with end_chart:
        results = pd.DataFrame(trip["results"])
        st.bar_chart(
            results,
            x="result",
            y="n",
            x_label="Drive result",
            y_label="Trips",
            horizontal=True,
            sort=False,
            color="#ff6a12",
        )
    with end_note:
        st.caption(
            f"Made field goals {pct(trip['fg_rate'])}. "
            f"Missed field goals {pct(trip['missed_fg_rate'])}. "
            f"Turnovers {pct(trip['turnover_rate'])}. "
            f"Downs {pct(trip['downs_rate'])}."
        )
        rate_table(
            trip["results"],
            [("result", "Result"), ("n", "Trips"), ("share", "Share")],
            {"Share"},
            "Share of red-zone trips by drive result",
        )

    st.subheader("The call by how close they are")
    st.caption(
        "Inside the 5 he runs more often, and a much larger share of those snaps score. "
        "From 11 to 20 the call is closer to a normal down."
    )
    band_rows = [row for row in report["bands"] if row["n"]]
    band_chart = pd.DataFrame(
        {
            "Spot": [row["spot"] for row in band_rows],
            "Pass rate": [round(row["pass_rate"] * 100, 1) for row in band_rows],
        }
    )
    if not band_chart.empty:
        st.bar_chart(
            band_chart,
            x="Spot",
            y="Pass rate",
            x_label="Yards to the end zone",
            y_label="Pass rate (%)",
            sort=False,
            color="#ff6a12",
        )
    rate_table(
        report["bands"],
        [
            ("spot", "Spot"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("first_down_pass_rate", "1st-down pass"),
            ("success_rate", "Success"),
            ("td_rate", "TD on the snap"),
            ("yards_per_play", "Yds/play"),
        ],
        {"Pass", "1st-down pass", "Success", "TD on the snap"},
        "Red-zone call and result by yards to the end zone",
    )

    st.subheader("Down and distance")
    st.caption("Yards to go for a first down, only on snaps already inside the 20. Green is more run, orange is more pass.")
    st.plotly_chart(
        heatmap(report["down_distance"]),
        width="stretch",
        config=PLOTLY_CONFIG,
    )

    st.subheader("Goal to go")
    st.caption("Goal to go means the line to gain is the goal line, not just that the ball is inside the 20.")
    rate_table(
        [
            {"slice": "Inside the 20, not goal to go", **report["not_goal"]},
            {"slice": "Goal to go", **report["goal_to_go"]},
            {"slice": "1st and goal", **report["first_and_goal"]},
        ],
        [
            ("slice", "Slice"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("success_rate", "Success"),
            ("td_rate", "TD on the snap"),
            ("yards_per_play", "Yds/play"),
        ],
        {"Pass", "Success", "TD on the snap"},
        "Red-zone calls on goal to go and on 1st and goal",
    )

    st.subheader("Fourth down: kick or go")
    st.caption(
        "A snap counts when it was a run, a pass, or a field goal. "
        "Penalties and timeouts are left out. Made field goals are kicks whose ESPN type says good."
    )
    rate_table(
        report["fourth"],
        [
            ("spot", "Spot"),
            ("n", "Snaps"),
            ("kick", "Kick"),
            ("made", "Made"),
            ("go", "Go"),
            ("pass_rate", "Pass when they go"),
            ("success_rate", "Success when they go"),
            ("td_rate", "TD when they go"),
        ],
        {"Pass when they go", "Success when they go", "TD when they go"},
        "Fourth-down field goals and go-for-it calls in the red zone",
    )

    st.subheader("The snap that gets them there, and what follows")
    st.caption(
        "The first snap is the first scrimmage play of the drive inside the 20. "
        "Later rows are only snaps after another red-zone play on that same drive."
    )
    rate_table(
        [{"situation": name, **block} for name, block in report["sequence"].items()],
        [
            ("situation", "Situation"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("success_rate", "Success"),
            ("td_rate", "TD on the snap"),
            ("yards_per_play", "Yds/play"),
        ],
        {"Pass", "Success", "TD on the snap"},
        "Red-zone pass rate on the entry snap and on later snaps",
    )

    st.subheader("Score margin")
    rate_table(
        report["score"],
        [
            ("situation", "Margin"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("success_rate", "Success"),
            ("td_rate", "TD on the snap"),
            ("yards_per_play", "Yds/play"),
        ],
        {"Pass", "Success", "TD on the snap"},
        "Red-zone pass rate by score margin",
    )

    split_title = "By season" if report["split_kind"] == "season" else "By era"
    st.subheader(split_title)
    rate_table(
        report["splits"],
        [
            ("label", "Season" if report["split_kind"] == "season" else "Era"),
            ("trips", "Trips"),
            ("td_trip_rate", "TD trips"),
            ("score_rate", "Trips scored"),
            ("points_per_trip", "Pts/trip"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("first_down_pass_rate", "1st-down pass"),
            ("inside5_pass_rate", "Inside the 5"),
            ("goal_pass_rate", "Goal to go"),
            ("success_rate", ENOUGH_LABEL),
        ],
        {"TD trips", "Trips scored", "Pass", "1st-down pass", "Inside the 5", "Goal to go", ENOUGH_LABEL},
        "Red-zone trips and pass rate by era or season",
    )

    st.subheader("What the snap was")
    detail = pd.DataFrame(report["details"])
    st.bar_chart(
        detail,
        x="detail",
        y="n",
        x_label="Play",
        y_label="Snaps",
        horizontal=True,
        sort=False,
        color="#ff6a12",
    )

    gun = report["shotgun"]
    if gun:
        st.subheader("Shotgun")
        st.caption(
            "Shotgun is read from the ESPN play text. In this dataset that tag shows up for "
            + " and ".join(gun["eras"])
            + ", not for the earlier stops. Plays without the word are grouped as under center, which can include shotgun snaps ESPN did not label."
        )
        metric_row(
            [
                ("Shotgun snaps", f"{gun['shotgun_n']:,}", f"Of {gun['n']:,} snaps in tagged seasons"),
                ("Pass rate from shotgun", pct(gun["from_gun"]["pass_rate"]), None),
            ],
            border=True,
        )
        rate_table(
            [
                {"look": "Shotgun", **gun["from_gun"]},
                {"look": "No shotgun tag", **gun["under_center"]},
            ],
            [
                ("look", "Look"),
                ("n", "Plays"),
                ("pass_rate", "Pass"),
                ("success_rate", "Success"),
                ("td_rate", "TD on the snap"),
                ("yards_per_play", "Yds/play"),
            ],
            {"Pass", "Success", "TD on the snap"},
            "Red-zone calls from shotgun and without a shotgun tag",
        )

    direction = report["direction"]
    st.subheader("Where it went")
    st.caption(
        f"ESPN tagged a direction on {direction['located']:,} of {direction['plays']:,} snaps "
        f"({pct(direction['coverage'])}). Tech, UIW, and Washington State have none. "
        "North Texas late in 2025 and Oklahoma State 2026 are where the tags exist."
    )
    if direction["located"]:
        run_rows = direction["runs"]
        pass_rows = direction["passes"]
        left, right = st.columns(2)
        with left:
            st.markdown("**Runs**")
            rate_table(
                run_rows,
                [
                    ("side", "Direction"),
                    ("n", "Plays"),
                    ("share", "Share"),
                    ("success_rate", "Success"),
                    ("yards_per_play", "Yds/play"),
                ],
                {"Share", "Success"},
                "Red-zone run direction",
            )
        with right:
            st.markdown("**Passes**")
            rate_table(
                pass_rows,
                [
                    ("depth", "Depth"),
                    ("side", "Direction"),
                    ("n", "Plays"),
                    ("share", "Share"),
                    ("success_rate", "Success"),
                    ("yards_per_play", "Yds/play"),
                ],
                {"Share", "Success"},
                "Red-zone pass depth and direction",
            )
    else:
        st.info("No direction tags in this filter.")

    st.subheader("Plays")
    show = play_table(report["plays_frame"].sort_values(["date", "drive_number", "drive_play_number"], na_position="last"))
    st.caption(f"{len(show):,} snaps. The table shows the latest 300.")
    show_plays(show.tail(300), "Red-zone scrimmage plays")
    st.download_button(
        "Download red-zone plays (CSV)",
        show.to_csv(index=False).encode("utf-8"),
        file_name="morris_red_zone.csv",
        mime="text/csv",
    )


try:
    info = cached_meta()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()

st.title("Morris Playbook")
st.caption(
    f"{info['n_games']} games · {info['n_drives']:,} drives · "
    f"{info['n_scrimmage']:,} scrimmage plays · 2013–2026. "
    "Live next-snap predictions are on the Live game page in the sidebar."
)
render_update_control()

era_labels = ["All eras"] + [f"{e['era']} ({e['role']})" for e in info["eras"]]
season_labels = ["All seasons"] + [str(s) for s in info["seasons"]]

era_label = st.pills(
    "Era",
    era_labels,
    default=era_labels[0],
    required=True,
    width="stretch",
)
if not era_label:
    era_label = era_labels[0]
season_col, garbage_col = st.columns([2, 1], vertical_alignment="bottom", gap="small")
with season_col:
    season_label = st.selectbox("Season", season_labels)
with garbage_col:
    drop_garbage = st.checkbox("Drop garbage time", value=True)

era = era_arg(era_label, info)
season = None if season_label == "All seasons" else season_label
ov = analysis.overview(era=era, season=season, exclude_garbage=drop_garbage)

tab_labels = [
    "Down & distance",
    "Red zone",
    "Drive charts",
    "Game log",
    "Sequencing",
    "Situations",
    "By era",
    "Where it went",
]
# A shared ?game= link should land on the drive chart. An explicit ?view=
# value still wins when it is already in the address bar.
if url_has_query_key("game") and "view" not in st.session_state:
    st.session_state["view"] = "Drive charts"
view = st.pills(
    "View",
    tab_labels,
    default="Down & distance",
    required=True,
    key="view",
    bind="query-params",
    width="stretch",
)
if view not in tab_labels:
    view = "Down & distance"

metric_row(
    [
        ("Plays", f"{ov['plays']:,}", "Scrimmage snaps in this filter"),
        ("Pass rate", pct(ov["pass_rate"]), "Sacks and scrambles count as passes"),
        ("Success", pct(ov["success_rate"]), "Enough yards for the down, a first down, or a touchdown"),
        ("Explosive", pct(ov["explosive_rate"]), "Runs of 10 or more yards, or passes of 15 or more"),
        ("Yds / play", num(ov["yards_per_play"]), None),
        ("1st-down pass", pct(ov["first_down_pass_rate"]), None),
        ("Pts / drive", num(ov["points_per_drive"]), None),
        ("3-and-out", pct(ov["three_and_out_rate"]), None),
    ],
    border=True,
)

if view == "Down & distance":
    st.write(
        "Each tile is **pass rate** for that down and distance. "
        "Green = more run, orange = more pass. Sacks and scrambles count as pass calls."
    )
    heat = analysis.down_distance(era=era, season=season, exclude_garbage=drop_garbage)
    st.plotly_chart(
        heatmap(heat),
        width="stretch",
        config=PLOTLY_CONFIG,
    )
    c1, c2 = st.columns(2)
    with c1:
        down_filter = st.selectbox("Filter plays by down", ["All"] + ["1", "2", "3", "4"])
    with c2:
        bucket_filter = st.selectbox("Filter plays by distance", ["All"] + analysis.DISTANCE_BUCKETS)
    plays = analysis.filter_plays(
        analysis.load_tables()["plays"],
        era=era,
        season=season,
        down=None if down_filter == "All" else down_filter,
        distance_bucket=None if bucket_filter == "All" else bucket_filter,
        exclude_garbage=drop_garbage,
    )
    st.caption(f"{len(plays):,} matching scrimmage plays")
    show_plays(play_table(plays.head(250)), "Scrimmage plays in this down and distance filter")
    st.download_button(
        "Download matching plays (CSV)",
        play_table(plays).to_csv(index=False).encode("utf-8"),
        file_name="morris_plays.csv",
        mime="text/csv",
    )

elif view == "Red zone":
    render_red_zone(era, season, drop_garbage)

elif view == "Drive charts":
    games = analysis.game_list(era=era, season=season)
    if games.empty:
        st.info("No games in this filter.")
    else:
        games = games.copy()
        games["game_id"] = games["game_id"].astype(str)
        ids = games["game_id"].tolist()
        labels = {
            row["game_id"]: game_option_label(row)
            for _, row in games.iterrows()
        }
        # index 0 is the widget default, so it is omitted from the URL.
        # Any other game, including the newest, stays in ?game= and can be copied.
        # Older share links put the whole label in ?game=, with the ESPN id last.
        raw_game = st.query_params.get("game", st.session_state.get("game"))
        linked = linked_game_id(raw_game, ids)
        if linked is None:
            st.session_state["game"] = ids[-1]
        else:
            st.session_state["game"] = linked
        game_id = st.selectbox(
            "Game",
            ids,
            index=0,
            format_func=lambda gid: labels.get(gid, str(gid)),
            key="game",
            bind="query-params",
            help="Picking a game also updates the address bar.",
        )
        if str(game_id) not in labels:
            st.warning("That game is not in the current era or season filter.")
        else:
            st.caption("Copy this link to open this drive chart.")
            st.code(game_share_url(labels[str(game_id)]), language=None, wrap_lines=True)
            game, drives, plays = analysis.game_drives(str(game_id))
            st.subheader(
                f"{game['result']} {game['team_score']}–{game['opp_score']} vs {game['opponent']}"
            )
            st.caption(f"{game['date']} · {game['era']} · {game['home_away']}")
            picked = games.loc[games["game_id"] == str(game_id)].iloc[0]
            play_n = int(picked["n"]) if pd.notna(picked.get("n")) else 0
            yards = int(picked["yards"]) if pd.notna(picked.get("yards")) else 0
            metric_row(
                [
                    ("Scrimmage plays", f"{play_n:,}", None),
                    ("Pass rate", pct(picked.get("pass_rate")), "Sacks and scrambles count as passes"),
                    ("Yards", f"{yards:,}", None),
                    ("Drives", f"{len(drives):,}", None),
                ],
                border=True,
            )
            if drives.empty:
                st.info("No offensive drives for this game.")
            else:
                st.caption(
                    "Each line runs from the first snap toward the opponent goal line. "
                    "On the selected drive, orange dots are passes and blue dots are runs. "
                    "The line is green for a touchdown, gold for a field goal, red for a turnover, orange for downs, and gray for a punt."
                )
                drive_ids = [str(v) for v in drives["drive_id"].tolist()]
                drive_labels = {
                    str(row["drive_id"]): drive_summary(row) for _, row in drives.iterrows()
                }
                if st.session_state.get("drive_pick") not in drive_ids:
                    st.session_state["drive_pick"] = drive_ids[0]
                chart_event = st.plotly_chart(
                    drive_field_chart(drives, plays, st.session_state["drive_pick"]),
                    width="stretch",
                    config=PLOTLY_CONFIG,
                    on_select="rerun",
                    selection_mode="points",
                    key=f"drive_field_{game_id}",
                )
                clicked = chart_drive_id(chart_event, set(drive_ids))
                click_token = f"{game_id}:{clicked}"
                if clicked and st.session_state.get("drive_click_token") != click_token:
                    st.session_state["drive_click_token"] = click_token
                    st.session_state["drive_pick"] = clicked
                    st.rerun()
                chosen_id = st.selectbox(
                    "Drive",
                    drive_ids,
                    format_func=lambda did: drive_labels.get(did, did),
                    key="drive_pick",
                )
                d_plays = plays[plays["drive_id"].astype(str) == str(chosen_id)]
                d_plays = d_plays[d_plays["scrimmage"] == True]  # noqa: E712
                d_plays = d_plays.sort_values(["drive_play_number", "sequence_number"], na_position="last")
                if d_plays.empty:
                    st.write("No scrimmage plays.")
                else:
                    show = d_plays[
                        [
                            c
                            for c in ["period", "clock", "down", "distance", "play_call", "yards", "description"]
                            if c in d_plays.columns
                        ]
                    ]
                    show_plays(show, "Scrimmage plays on this drive")

elif view == "Game log":
    opponents = analysis.game_list(era=era, season=season)
    names = ["All opponents"]
    if not opponents.empty and "opponent" in opponents.columns:
        names += sorted({str(name) for name in opponents["opponent"].dropna().unique()})
    if st.session_state.get("log_opponent") not in names:
        st.session_state["log_opponent"] = names[0]
    opponent_label = st.selectbox("Opponent", names, key="log_opponent")
    opponent = None if opponent_label == "All opponents" else opponent_label
    log = analysis.game_log(era=era, season=season, opponent=opponent)
    st.caption("One row per game in the era and season filters above. Newest games are first.")
    if log.empty:
        st.info("No games in this filter.")
    else:
        ids = log["game_id"].astype(str).tolist()
        show = pd.DataFrame(
            {
                "Date": log["date"],
                "Opponent": log["opponent"],
                "Site": log["home_away"],
                "Result": log["result"],
                "Score": [
                    f"{int(us)}–{int(them)}"
                    for us, them in zip(log["team_score"], log["opp_score"])
                ],
                "Plays": pd.to_numeric(log["n"], errors="coerce"),
                "Pass": log["pass_rate"],
                "Yds/play": log["yards_per_play"],
                "Pts/drive": log["points_per_drive"],
            }
        )
        picked = st.dataframe(
            show,
            width="stretch",
            hide_index=True,
            on_select="rerun",
            selection_mode="single-row",
            key="game_log_table",
            column_config={
                "Date": st.column_config.TextColumn(pinned=True),
                "Pass": st.column_config.NumberColumn(format="percent"),
                "Yds/play": st.column_config.NumberColumn(format="%.1f"),
                "Pts/drive": st.column_config.NumberColumn(format="%.1f"),
                "Plays": st.column_config.NumberColumn(format="%d"),
            },
        )
        rows = []
        if picked is not None:
            selection = picked.get("selection") if isinstance(picked, dict) else getattr(picked, "selection", None)
            if selection is not None:
                rows = selection.get("rows") if isinstance(selection, dict) else getattr(selection, "rows", [])
        open_id = ids[rows[0]] if rows else None
        st.button(
            "Open drive chart",
            disabled=open_id is None,
            on_click=open_logged_game,
            args=(open_id or "",),
        )

elif view == "Sequencing":
    seq = analysis.sequencing(era=era, season=season, exclude_garbage=drop_garbage)
    st.caption("The next snap after the previous call, using the era and season filters above.")
    rows = [{"Situation": name, "Plays": block["n"], "Pass": block["pass_rate"], "Success": block["success_rate"]} for name, block in seq.items()]
    frame = pd.DataFrame(rows)
    chart_rows = frame[frame["Plays"].fillna(0) > 0]
    if chart_rows.empty:
        st.info("No sequenced snaps in this filter.")
    else:
        long = chart_rows.melt(id_vars=["Situation"], value_vars=["Pass", "Success"], var_name="Rate", value_name="Percent")
        long["Percent"] = (pd.to_numeric(long["Percent"], errors="coerce") * 100).round(1)
        st.bar_chart(
            long,
            x="Situation",
            y="Percent",
            color="Rate",
            x_label="Previous snap",
            y_label="Rate (%)",
            horizontal=True,
            sort=False,
        )
    st.dataframe(
        frame,
        width="stretch",
        hide_index=True,
        column_config={
            "Situation": st.column_config.TextColumn(pinned=True),
            "Pass": st.column_config.NumberColumn("Pass", format="percent"),
            "Success": st.column_config.NumberColumn("Success", format="percent"),
        },
    )

elif view == "Situations":
    sit = analysis.situations(era=era, season=season, exclude_garbage=drop_garbage)
    st.dataframe(
        sit,
        width="stretch",
        hide_index=True,
        column_config={
            "Situation": st.column_config.TextColumn(pinned=True),
            "Pass %": st.column_config.NumberColumn(format="percent"),
            "Success %": st.column_config.NumberColumn(format="percent"),
            "Explosive %": st.column_config.NumberColumn(format="percent"),
            "Yds/play": st.column_config.NumberColumn(format="%.1f"),
        },
    )

elif view == "By era":
    eras = analysis.era_table(exclude_garbage=drop_garbage)
    st.dataframe(
        eras,
        width="stretch",
        hide_index=True,
        column_config={
            "Era": st.column_config.TextColumn(pinned=True),
            "Pass %": st.column_config.NumberColumn(format="percent"),
            "1st-down pass %": st.column_config.NumberColumn(format="percent"),
            "Success %": st.column_config.NumberColumn(format="percent"),
            "Yds/play": st.column_config.NumberColumn(format="%.1f"),
            "Pts/drive": st.column_config.NumberColumn(format="%.1f"),
            "TD drive %": st.column_config.NumberColumn(format="percent"),
            "3-and-out %": st.column_config.NumberColumn(format="percent"),
        },
    )

elif view == "Where it went":
    st.write(
        "ESPN only started putting **left / middle / right** (and short/deep on passes) "
        "in the play text in late 2025. Oklahoma State 2026 is almost fully tagged. "
        "Texas Tech, UIW, WSU, and 2023–24 North Texas have none."
    )
    br = analysis.direction_breakdown(era=era, season=season, exclude_garbage=drop_garbage)
    st.caption(
        f"Direction tagged on {br['located']:,} of {br['plays']:,} scrimmage plays "
        f"({pct(br['coverage'])})."
    )
    if not br["located"]:
        st.info("No direction tags in this filter. Switch the era to Oklahoma State or season to 2025/2026.")
    else:
        if (br["coverage"] or 0) < 0.5:
            st.warning(
                "Most plays in this filter have no direction. "
                "The charts below are only the tagged subset, mostly 2025 week 9 onward and 2026."
            )
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Runs")
            run_df = pd.DataFrame(br["runs"])
            fig = go.Figure(
                go.Bar(
                    x=run_df["side"],
                    y=run_df["n"],
                    marker_color=["#3dcf7a", "#c4b44a", "#2f9e5f"],
                    text=[
                        f"{int(n)} · {pct(s)}<br>{num(y)} yds"
                        for n, s, y in zip(run_df["n"], run_df["share"], run_df["yards_per_play"])
                    ],
                    textposition="outside",
                )
            )
            fig.update_layout(
                height=280,
                margin=dict(l=16, r=12, t=8, b=32),
                yaxis_title="Plays",
                plot_bgcolor="#0a100c",
                paper_bgcolor="#0a100c",
                font=dict(color="#e7f0e4", size=12),
                showlegend=False,
            )
            st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
            show = run_df.rename(columns={
                "side": "Direction",
                "n": "n",
                "share": "Share",
                "yards_per_play": "Yds/play",
                "success_rate": "Success",
                "explosive_rate": "Explosive",
            })
            for col in ["Share", "Success", "Explosive"]:
                show[col] = show[col].map(pct)
            show["Yds/play"] = show["Yds/play"].map(lambda v: num(v))
            st.dataframe(
                show,
                width="stretch",
                hide_index=True,
                column_config={"Direction": st.column_config.TextColumn(pinned=True)},
            )
        with c2:
            st.subheader("Passes")
            pass_df = pd.DataFrame(br["passes"])
            z, text = [], []
            for depth in analysis.DEPTH_ORDER:
                zr, tr = [], []
                for side in analysis.SIDE_ORDER:
                    hit = pass_df[(pass_df["depth"] == depth) & (pass_df["side"] == side)].iloc[0]
                    zr.append(hit["n"])
                    tr.append(f"{int(hit['n'])}<br>{pct(hit['share'])}")
                z.append(zr)
                text.append(tr)
            fig = go.Figure(
                data=go.Heatmap(
                    z=z,
                    x=analysis.SIDE_ORDER,
                    y=analysis.DEPTH_ORDER,
                    text=text,
                    texttemplate="%{text}",
                    colorscale=[[0, "#1a241c"], [1, "#ff6a12"]],
                    hovertemplate="%{y} %{x}<br>n=%{z}<extra></extra>",
                    xgap=4,
                    ygap=4,
                )
            )
            fig.update_layout(
                height=280,
                margin=dict(l=36, r=4, t=8, b=32),
                plot_bgcolor="#0a100c",
                paper_bgcolor="#0a100c",
                font=dict(color="#e7f0e4", size=12),
            )
            st.plotly_chart(fig, width="stretch", config=PLOTLY_CONFIG)
            show = pass_df.rename(columns={
                "depth": "Depth",
                "side": "Side",
                "n": "n",
                "share": "Share",
                "yards_per_play": "Yds/play",
                "success_rate": "Success",
                "explosive_rate": "Explosive",
            })
            for col in ["Share", "Success", "Explosive"]:
                show[col] = show[col].map(pct)
            show["Yds/play"] = show["Yds/play"].map(lambda v: num(v))
            st.dataframe(
                show,
                width="stretch",
                hide_index=True,
                column_config={"Depth": st.column_config.TextColumn(pinned=True)},
            )

st.divider()
st.caption(
    "Source: ESPN play-by-play. Pass calls include sacks and scrambles. "
    "2013 Texas Tech is co-OC. Spring 2021 UIW is stored as 2020."
)
