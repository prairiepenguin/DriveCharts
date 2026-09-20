"""Eric Morris coaching stints used to pull offensive play-by-play."""

from __future__ import annotations

STINTS = [
    {
        "era": "Texas Tech",
        "era_id": "ttu",
        "role": "OC",
        "role_detail": "Co-OC in 2013; OC 2014–2017",
        "team": "Texas Tech",
        "team_id": 2641,
        "abbrev": "TTU",
        "seasons": [2013, 2014, 2015, 2016, 2017],
        "color": "#CC0000",
    },
    {
        "era": "Incarnate Word",
        "era_id": "uiw",
        "role": "HC",
        "role_detail": "Head coach 2018–2021",
        "team": "Incarnate Word",
        "team_id": 2916,
        "abbrev": "UIW",
        "seasons": [2018, 2019, 2021],
        "color": "#C41E3A",
        # COVID year: Southland played spring 2021. ESPN does not attach
        # these to the 2020 or 2021 team schedule, so they are listed here.
        "extra_games": [
            {"game_id": "401279199", "season": 2020, "week": 1},
            {"game_id": "401279202", "season": 2020, "week": 2},
            {"game_id": "401279208", "season": 2020, "week": 3},
            {"game_id": "401279211", "season": 2020, "week": 4},
            {"game_id": "401279215", "season": 2020, "week": 5},
            {"game_id": "401299612", "season": 2020, "week": 6},
        ],
    },
    {
        "era": "Washington State",
        "era_id": "wsu",
        "role": "OC",
        "role_detail": "OC / quarterbacks 2022",
        "team": "Washington State",
        "team_id": 265,
        "abbrev": "WSU",
        "seasons": [2022],
        "color": "#981E32",
    },
    {
        "era": "North Texas",
        "era_id": "unt",
        "role": "HC",
        "role_detail": "Head coach 2023–2025",
        "team": "North Texas",
        "team_id": 249,
        "abbrev": "UNT",
        "seasons": [2023, 2024, 2025],
        "color": "#00853E",
    },
    {
        "era": "Oklahoma State",
        "era_id": "osu",
        "role": "HC",
        "role_detail": "Head coach 2026–present",
        "team": "Oklahoma State",
        "team_id": 197,
        "abbrev": "OKST",
        "seasons": [2026],
        "color": "#FF7300",
    },
]

ERA_BY_ID = {s["era_id"]: s for s in STINTS}


def stint_for_season(season: int) -> dict | None:
    for stint in STINTS:
        if season in stint["seasons"]:
            return stint
        extras = stint.get("extra_games") or []
        if any(g.get("season") == season for g in extras):
            return stint
    return None
