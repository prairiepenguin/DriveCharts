# Morris Playbook

Play-by-play analysis of Eric Morris as an offensive coordinator and head coach, 2013–present.

Each row is one offensive play, with drive IDs and sequence numbers so possessions can be reconstructed and play selection can be sliced by down, distance, field position, previous play, era, and score.

## Coverage

| Years | Team | Role |
| --- | --- | --- |
| 2013–2017 | Texas Tech | OC (co-OC in 2013) |
| 2018–2021 | Incarnate Word | HC |
| 2022 | Washington State | OC |
| 2023–2025 | North Texas | HC |
| 2026– | Oklahoma State | HC |

Source: ESPN game summaries (`site.web.api.espn.com`). No API key. Spring 2021 UIW (COVID Southland season) is stored as 2020.

Pass calls include sacks and scrambles (intended pass). Kneels, spikes, extra points, kickoffs, and accepted no-play penalties are kept on the drive but excluded from selection rates.

## Setup

```powershell
cd C:\DriveCharts
python -m pip install -r requirements.txt
python -m pipeline.ingest
streamlit run streamlit_app.py
```

Opens a local URL (usually http://localhost:8501). Share that link on your LAN, or deploy to Streamlit Community Cloud.

The original FastAPI UI is still available with `python -m app.server` at http://127.0.0.1:8765.

### Share on Streamlit Cloud

1. Push this repo to GitHub, including `data/games.parquet`, `data/drives.parquet`, and `data/plays.parquet` (the raw ESPN cache in `data/raw/` can stay local).
2. Go to [share.streamlit.io](https://share.streamlit.io), sign in with GitHub, and deploy.
3. Main file: `streamlit_app.py`. Python packages come from `requirements.txt`.

Anyone with the Cloud URL can use the app in a browser. After new games, re-run ingest, commit the three parquet files, and push.

## Live next-snap predictions

The Streamlit sidebar has a **Live game** page. During an Oklahoma State game it polls ESPN every few seconds and, when OSU has the ball, predicts pass vs run for the upcoming snap from similar Morris situations (default: UNT 2023–25 + OSU 2026).

It will lag the broadcast, especially in no-huddle. It predicts call type, not the concept. Use **Replay a completed game** to walk snaps and see hit rate on Oregon / Murray State.

Re-run ingest after new games. Cached ESPN summaries live in `data/raw/`. Use `--refresh` to re-download.

Current dataset: **157 games**, **2,118 drives**, **11,988 scrimmage plays** (2013–2026). Three games have no ESPN drive chart and are skipped: UIW vs Stephen F. Austin (2018-09-15), UIW at Montana State (2018-11-24 FCS playoff), and Washington State at Wisconsin (2022-09-10).

## What you can analyze

- Run/pass by down and distance
- 1st-down and 3rd-down tendencies
- Red zone / backed up / plus territory
- After run vs after pass, after stuffed run, after incompletion
- Drive charts with every play in order
- Era comparison (Tech / UIW / WSU / UNT / OSU)
