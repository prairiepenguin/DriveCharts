"""Thin ESPN college-football client. No API key required."""

from __future__ import annotations

import time
from typing import Any

import httpx

BASE = "https://site.web.api.espn.com/apis/site/v2/sports/football/college-football"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class EspnClient:
    def __init__(self, pause: float = 0.12, timeout: float = 30.0) -> None:
        self.pause = pause
        self._client = httpx.Client(
            headers={"User-Agent": UA, "Accept": "application/json"},
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EspnClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, url: str, params: dict[str, Any] | None = None) -> dict:
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                time.sleep(self.pause)
                r = self._client.get(url, params=params)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as exc:  # noqa: BLE001 - retry then raise
                last_err = exc
                time.sleep(1.2 * (attempt + 1))
        raise RuntimeError(f"ESPN request failed: {url}") from last_err

    def schedule(self, team_id: int, season: int, season_type: int) -> list[dict]:
        data = self.get(
            f"{BASE}/teams/{team_id}/schedule",
            params={"season": season, "seasontype": season_type},
        )
        return data.get("events") or []

    def summary(self, game_id: str | int) -> dict:
        return self.get(f"{BASE}/summary", params={"event": str(game_id)})
