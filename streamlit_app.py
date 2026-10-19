"""Streamlit app for Eric Morris play-selection analysis."""

from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import analysis
from app.refresh import render_update_control

st.set_page_config(page_title="Morris Playbook", page_icon="🏈", layout="wide")

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.4rem; }
      h1 { font-weight: 800; letter-spacing: 0.02em; }
      div[data-testid="stMetricValue"] { font-size: 1.6rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


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
        margin=dict(l=40, r=10, t=10, b=40),
        height=420,
        xaxis_title="Yards to go",
        yaxis_title="Down",
        plot_bgcolor="#0a100c",
        paper_bgcolor="#0a100c",
        font=dict(color="#e7f0e4"),
    )
    return fig


def field_bar(start_yte, yards, result: str) -> str:
    try:
        start = float(start_yte if start_yte is not None else 75)
        gained = float(yards if yards is not None else 0)
    except (TypeError, ValueError):
        start, gained = 75.0, 0.0
    left = max(0.0, min(100.0, 100.0 - start))
    width = max(2.0, min(100.0 - left, abs(gained)))
    color = analysis.RESULT_COLORS.get(result, "#6d7c70")
    return (
        "<div style='height:18px;border-radius:4px;background:#17321c;"
        "position:relative;overflow:hidden;margin:4px 0 8px'>"
        f"<div style='position:absolute;top:3px;height:12px;left:{left}%;"
        f"width:{width}%;background:{color};border-radius:2px'></div></div>"
    )


def game_option_label(row: pd.Series) -> str:
    abbrev = row.get("opponent_abbrev") or row.get("opponent") or "OPP"
    try:
        score_us = int(row["team_score"])
        score_them = int(row["opp_score"])
    except (TypeError, ValueError):
        score_us, score_them = 0, 0
    result = row.get("result") or ""
    return f"{row['date']} {result} {score_us}-{score_them} {abbrev} {row['game_id']}"


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


def rate_table(rows: list[dict], columns: list[tuple[str, str]], percent: set[str], alt: str) -> None:
    frame = pd.DataFrame(rows)
    if frame.empty:
        st.info("No plays in this slice.")
        return
    rename = {src: label for src, label in columns}
    show = frame.rename(columns=rename)[[label for _, label in columns]]
    config = {}
    for label in rename.values():
        if label in percent:
            config[label] = st.column_config.NumberColumn(format="percent", step=0.01)
        elif label in {"Yds/play", "Pts/trip"}:
            config[label] = st.column_config.NumberColumn(format="%.1f")
    st.dataframe(show, width="stretch", hide_index=True, column_config=config, alt=alt)


def render_red_zone(era: str | None, season: str | None, drop_garbage: bool) -> None:
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
    cards = st.columns(6)
    values = [
        ("Trips", f"{report['trips']:,}", "Drives that reached the red zone"),
        ("TD rate", pct(trip["td_rate"]), "Trips that ended in a touchdown"),
        ("Score rate", pct(trip["score_rate"]), "Trips that ended in a touchdown or a made field goal"),
        ("Points / trip", num(trip["points_per_trip"]), "Six for a touchdown, three for a field goal"),
        ("Pass rate", pct(summary["pass_rate"]), "Share of scrimmage snaps that were passes"),
        ("Success", pct(summary["success_rate"]), "Down-and-distance success rate on those snaps"),
    ]
    for col, (label, value, help_text) in zip(cards, values):
        col.metric(label, value, help=help_text, border=True, height="stretch")
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
            alt="Red-zone trips by how the drive ended",
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
            alt="Red-zone pass rate by yards to the end zone",
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
        alt="Red-zone pass rate by down and distance",
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

    st.subheader("Score")
    rate_table(
        report["score"],
        [
            ("situation", "Score"),
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
            ("score_rate", "Score"),
            ("points_per_trip", "Pts/trip"),
            ("n", "Plays"),
            ("pass_rate", "Pass"),
            ("first_down_pass_rate", "1st-down pass"),
            ("inside5_pass_rate", "Inside the 5"),
            ("goal_pass_rate", "Goal to go"),
            ("success_rate", "Success"),
        ],
        {"TD trips", "Score", "Pass", "1st-down pass", "Inside the 5", "Goal to go", "Success"},
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
        alt="Red-zone snaps by play type",
    )

    gun = report["shotgun"]
    if gun:
        st.subheader("Shotgun")
        st.caption(
            "Shotgun is read from the ESPN play text. In this dataset that tag shows up for "
            + " and ".join(gun["eras"])
            + ", not for the earlier stops. Plays without the word are grouped as under center, which can include shotgun snaps ESPN did not label."
        )
        gun_cards = st.columns(2)
        gun_cards[0].metric("Shotgun snaps", f"{gun['shotgun_n']:,}", help=f"Of {gun['n']:,} snaps in tagged seasons")
        gun_cards[1].metric("Pass rate from shotgun", pct(gun["from_gun"]["pass_rate"]))
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
    st.dataframe(show.tail(300), width="stretch", hide_index=True, alt="Red-zone scrimmage plays")
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
    f"Eric Morris offensive play selection · {info['n_games']} games · "
    f"{info['n_drives']:,} drives · {info['n_scrimmage']:,} scrimmage plays · 2013–2026. "
    "The percentage on down-and-distance tiles is **pass rate**. "
    "Open **Live game** in the sidebar to poll ESPN and predict the next snap."
)
render_update_control()

era_labels = ["All eras"] + [f"{e['era']} ({e['role']})" for e in info["eras"]]
season_labels = ["All seasons"] + [str(s) for s in info["seasons"]]

left, mid, right = st.columns([2, 1, 1])
with left:
    era_label = st.radio("Era", era_labels, horizontal=True)
with mid:
    season_label = st.selectbox("Season", season_labels)
with right:
    drop_garbage = st.checkbox("Drop garbage time", value=True)

era = era_arg(era_label, info)
season = None if season_label == "All seasons" else season_label
ov = analysis.overview(era=era, season=season, exclude_garbage=drop_garbage)

k1, k2, k3, k4, k5, k6, k7, k8 = st.columns(8)
k1.metric("Plays", f"{ov['plays']:,}")
k2.metric("Pass rate", pct(ov["pass_rate"]))
k3.metric("Success", pct(ov["success_rate"]))
k4.metric("Explosive", pct(ov["explosive_rate"]))
k5.metric("Yds / play", num(ov["yards_per_play"]))
k6.metric("1st-down pass", pct(ov["first_down_pass_rate"]))
k7.metric("Pts / drive", num(ov["points_per_drive"]))
k8.metric("3-and-out", pct(ov["three_and_out_rate"]))

tab_labels = [
    "Down & distance",
    "Red zone",
    "Drive charts",
    "Sequencing",
    "Situations",
    "By era",
    "Where it went",
]
# A shared ?game= link should land on the drive chart. The tab widget
# still prefers an explicit ?view= value on first load.
if url_has_query_key("game") and "view" not in st.session_state:
    st.session_state["view"] = "Drive charts"
tab_heat, tab_rz, tab_drives, tab_seq, tab_sit, tab_eras, tab_dir = st.tabs(
    tab_labels,
    key="view",
    bind="query-params",
    default="Down & distance",
)

with tab_heat:
    st.write(
        "Each tile is **pass rate** for that down and distance. "
        "Green = more run, orange = more pass. Sacks and scrambles count as pass calls."
    )
    heat = analysis.down_distance(era=era, season=season, exclude_garbage=drop_garbage)
    st.plotly_chart(heatmap(heat), width="stretch")
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
    st.dataframe(play_table(plays.head(250)), width="stretch", hide_index=True)
    st.download_button(
        "Download matching plays (CSV)",
        play_table(plays).to_csv(index=False).encode("utf-8"),
        file_name="morris_plays.csv",
        mime="text/csv",
    )

with tab_rz:
    if tab_rz.open:
        render_red_zone(era, season, drop_garbage)

with tab_drives:
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
        if st.session_state.get("game") not in ids:
            st.session_state["game"] = ids[-1]
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
            for _, drv in drives.iterrows():
                with st.expander(
                    f"Drive {int(drv['drive_number'])} · {drv.get('start_text') or ''} → {drv.get('result')} · "
                    f"{drv.get('scrimmage_plays') or drv.get('offensive_plays') or 0} plays · "
                    f"{drv.get('yards') or 0} yds · {drv.get('time_elapsed') or ''}",
                    expanded=False,
                ):
                    st.markdown(
                        field_bar(drv.get("start_yards_to_endzone"), drv.get("yards"), drv.get("result")),
                        unsafe_allow_html=True,
                    )
                    d_plays = plays[plays["drive_id"].astype(str) == str(drv["drive_id"])]
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
                        st.dataframe(show, width="stretch", hide_index=True)

with tab_seq:
    seq = analysis.sequencing(era=era, season=season, exclude_garbage=drop_garbage)
    cols = st.columns(4)
    for i, (label, block) in enumerate(seq.items()):
        with cols[i % 4]:
            st.metric(label, pct(block["pass_rate"]), help=f"{block['n']} plays")
            st.caption(f"{block['n']} plays · run {pct(block['run_rate'])} · success {pct(block['success_rate'])}")

with tab_sit:
    sit = analysis.situations(era=era, season=season, exclude_garbage=drop_garbage)
    pretty = sit.copy()
    for col in ["Pass %", "Success %", "Explosive %"]:
        pretty[col] = pretty[col].map(lambda v: pct(v))
    pretty["Yds/play"] = pretty["Yds/play"].map(lambda v: num(v))
    st.dataframe(pretty, width="stretch", hide_index=True)

with tab_eras:
    eras = analysis.era_table(exclude_garbage=drop_garbage)
    pretty = eras.copy()
    for col in ["Pass %", "1st-down pass %", "Success %", "TD drive %", "3-and-out %"]:
        pretty[col] = pretty[col].map(lambda v: pct(v))
    for col in ["Yds/play", "Pts/drive"]:
        pretty[col] = pretty[col].map(lambda v: num(v))
    st.dataframe(pretty, width="stretch", hide_index=True)

with tab_dir:
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
                height=320,
                margin=dict(l=20, r=20, t=20, b=40),
                yaxis_title="Plays",
                plot_bgcolor="#0a100c",
                paper_bgcolor="#0a100c",
                font=dict(color="#e7f0e4"),
                showlegend=False,
            )
            st.plotly_chart(fig, width="stretch")
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
            st.dataframe(show, width="stretch", hide_index=True)
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
                height=320,
                margin=dict(l=40, r=10, t=20, b=40),
                plot_bgcolor="#0a100c",
                paper_bgcolor="#0a100c",
                font=dict(color="#e7f0e4"),
            )
            st.plotly_chart(fig, width="stretch")
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
            st.dataframe(show, width="stretch", hide_index=True)

st.divider()
st.caption(
    "Source: ESPN play-by-play. Pass calls include sacks and scrambles. "
    "2013 Texas Tech is co-OC. Spring 2021 UIW is stored as 2020."
)
