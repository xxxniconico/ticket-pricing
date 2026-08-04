"""Fetch K League 1 fixtures from API-Football and convert to CSL-compatible format.

Output: data/raw/kleague_YYYY_all_matches.json
Format (same as csl_*_all_matches.json):
    [{"round": int, "date": "YYYY-MM-DD", "home": str, "away": str,
      "home_goals": int, "away_goals": int}, ...]

API-Football free plan: seasons 2022-2024 only (per API error message).
K League 1 league id = 292 (confirmed via /leagues?search=K League).
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LEAGUE_ID = 292
OUT_DIR = PROJECT_ROOT / "data" / "raw"


def get_key() -> str:
    env = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if env:
        return env
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            if line.startswith("API_FOOTBALL_KEY="):
                return line.split("=", 1)[1].strip()
    sys.exit("API_FOOTBALL_KEY not found in env or .env")


def fetch_fixtures(key: str, season: int) -> list[dict]:
    url = f"https://v3.football.api-sports.io/fixtures?league={LEAGUE_ID}&season={season}"
    req = urllib.request.Request(url, headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.load(resp)
    if data.get("errors"):
        sys.exit(f"season {season}: API errors: {data['errors']}")
    return data["response"]


def parse_round(raw: str) -> int:
    """'Regular Season - 1' -> 1, 'Championship Round - N' -> 34+N, 'Relegation Round - N' -> 39+N.
    Bare 'Relegation Round' (no number) = K League 2 promotion/relegation playoff -> None (exclude)."""
    raw = raw or ""
    m = re.search(r"(\d+)$", raw)
    if not m:
        return None  # playoff fixtures vs K League 2 teams are dropped
    n = int(m.group(1))
    if "Championship" in raw:
        return 34 + n
    if "Relegation" in raw:
        return 39 + n
    return n


def convert(fixtures: list[dict]) -> list[dict]:
    out = []
    for f in fixtures:
        status = f.get("fixture", {}).get("status", {}).get("short", "")
        if status not in ("FT", "AET", "PEN"):
            continue  # only finished matches
        teams, goals = f["teams"], f["goals"]
        if goals.get("home") is None or goals.get("away") is None:
            continue
        rnd = parse_round(f["league"].get("round", ""))
        if rnd is None:
            continue  # promotion/relegation playoff vs K League 2 teams
        home, away = teams["home"]["name"], teams["away"]["name"]
        # Sangju Sangmu FC renamed to Gimcheon Sangmu FC mid-2022 (Oct); normalize.
        if home == "Sangju Sangmu FC": home = "Gimcheon Sangmu FC"
        if away == "Sangju Sangmu FC": away = "Gimcheon Sangmu FC"
        out.append({
            "round": rnd,
            "date": f["fixture"]["date"][:10],
            "home": home,
            "away": away,
            "home_goals": goals["home"],
            "away_goals": goals["away"],
        })
    out.sort(key=lambda x: (x["date"], x["round"]))
    return out


def main():
    key = get_key()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for season in (2022, 2023, 2024):
        fixtures = fetch_fixtures(key, season)
        rows = convert(fixtures)
        out_file = OUT_DIR / f"kleague_{season}_all_matches.json"
        out_file.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"season {season}: {len(fixtures)} fixtures -> {len(rows)} finished matches -> {out_file.name}")


if __name__ == "__main__":
    main()
