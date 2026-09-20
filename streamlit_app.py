"""Streamlit app for Eric Morris play-selection analysis."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from app import analysis

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

tab_heat, tab_drives, tab_seq, tab_sit, tab_eras, tab_dir = st.tabs(
    ["Down & distance", "Drive charts", "Sequencing", "Situations", "By era", "Where it went"]
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

with tab_drives:
    games = analysis.game_list(era=era, season=season)
    if games.empty:
        st.info("No games in this filter.")
    else:
        games = games.copy()
        games["label"] = games.apply(
            lambda r: f"{r['date']}  {r.get('result','')} {r.get('team_score','')}-{r.get('opp_score','')} vs {r.get('opponent_abbrev') or r.get('opponent')}",
            axis=1,
        )
        pick = st.selectbox("Game", games["label"].tolist(), index=len(games) - 1)
        game_id = games.loc[games["label"] == pick, "game_id"].iloc[0]
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
