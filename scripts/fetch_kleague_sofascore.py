"""Fetch K League 1 fixtures for 2025/2026 from sofascore public API.

API-Football free plan only allows 2022-2024, so 2025/2026 comes from
api.sofascore.com (unique-tournament id=410, public, no key needed).

Output: data/raw/kleague_YYYY_all_matches.json  (same format as fetch_kleague.py)

Cleanup rules:
- Drop promotion/relegation playoff matches vs K League 2 teams
  (identified by the K2-team set for that season).
- Normalize mid-season/rebrand team names to the latest canonical name.

Season ids: 2025=70830, 2026=88606 (verified via /unique-tournament/410/seasons).
"""

import json
import time
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "data" / "raw"
SEASONS = {2025: 70830, 2026: 88606}

# Teams that only appear in K League 2 (playoff opponents) per season.
K2_TEAMS = {
    2025: {"Bucheon FC 1995", "Seongnam FC", "Suwon Samsung Bluewings", "Seoul E-Land FC"},
    2026: set(),
}

# Rebrand/renamed teams -> latest canonical name (2026).
TEAM_ALIASES = {
    "Ulsan Hyundai FC": "Ulsan HD",
    "Jeonbuk Motors": "Jeonbuk Hyundai Motors",
    "Daejeon Citizen": "Daejeon Hana Citizen",
    "Jeju United FC": "Jeju SK",
    "Suwon City FC": "Suwon FC",
    "Suwon Bluewings": "Suwon Samsung Bluewings",
}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def fetch_season(season_id: int) -> list[dict]:
    events, page = [], 0
    while True:
        url = (
            f"https://api.sofascore.com/api/v1/unique-tournament/410/"
            f"season/{season_id}/events/last/{page}"
        )
        batch = _get(url).get("events", [])
        if not batch:
            break
        events.extend(batch)
        page += 1
        if len(batch) < 30:
            break
        time.sleep(0.3)
    return events


def convert(events: list[dict], season: int) -> list[dict]:
    k2 = K2_TEAMS.get(season, set())
    out = []
    for e in events:
        if e.get("status", {}).get("type") != "finished":
            continue
        home = e["homeTeam"]["name"]
        away = e["awayTeam"]["name"]
        if home in k2 or away in k2:
            continue  # promotion/relegation playoff vs K League 2
        home = TEAM_ALIASES.get(home, home)
        away = TEAM_ALIASES.get(away, away)
        hs = (e.get("homeScore") or {}).get("current")
        as_ = (e.get("awayScore") or {}).get("current")
        if hs is None or as_ is None:
            continue
        out.append({
            "round": (e.get("roundInfo") or {}).get("round", 0),
            "date": time.strftime("%Y-%m-%d", time.gmtime(e["startTimestamp"])),
            "home": home,
            "away": away,
            "home_goals": hs,
            "away_goals": as_,
        })
    out.sort(key=lambda x: (x["date"], x["round"]))
    return out


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for season, season_id in SEASONS.items():
        events = fetch_season(season_id)
        rows = convert(events, season)
        out_file = OUT_DIR / f"kleague_{season}_all_matches.json"
        out_file.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        teams = {m["home"] for m in rows} | {m["away"] for m in rows}
        print(f"season {season}: {len(events)} events -> {len(rows)} matches, {len(teams)} teams")
        print(f"  -> {out_file.name}")


if __name__ == "__main__":
    main()
