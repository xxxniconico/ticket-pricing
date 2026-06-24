"""Fetch Elo ratings + historical international results from eloratings.net.

Each team's page TSV contains both the current Elo rating (last line) and the
full match history. This script fetches each of the 48 World Cup 2026 teams
once and emits two artifacts:

  data/raw/elo/elo_ratings_20260620.json
  data/raw/historical/intl_results_2022_2026.json

Research only. No real betting. See docs/plans/wc-betting-strategy-20260620.md.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from collections import Counter, OrderedDict
from datetime import date
from pathlib import Path

BASE = "https://www.eloratings.net"
UA = "Mozilla/5.0 (research; wc-betting-strategy)"
PROJECT_ROOT = Path(__file__).resolve().parents[3]
ELO_OUT = PROJECT_ROOT / "data/raw/elo/elo_ratings_20260620.json"
HIST_OUT = PROJECT_ROOT / "data/raw/historical/intl_results_2022_2026.json"
CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "elo_cache"

# Canonical WC 2026 team name -> eloratings.net URL slug.
# "men's" suffixes dropped (men's NT is the default on eloratings.net).
# "Czech Republic" -> Czechia, "Curaçao" -> Curacao (ASCII slug).
TEAM_SLUGS: "OrderedDict[str, str]" = OrderedDict([
    # Group A
    ("Mexico", "Mexico"),
    ("South Africa", "South_Africa"),
    ("South Korea", "South_Korea"),
    ("Czech Republic", "Czechia"),
    # Group B
    ("Canada", "Canada"),
    ("Bosnia and Herzegovina", "Bosnia_and_Herzegovina"),
    ("Qatar", "Qatar"),
    ("Switzerland", "Switzerland"),
    # Group C
    ("Brazil", "Brazil"),
    ("Morocco", "Morocco"),
    ("Haiti", "Haiti"),
    ("Scotland", "Scotland"),
    # Group D
    ("United States", "United_States"),
    ("Paraguay", "Paraguay"),
    ("Australia", "Australia"),
    ("Turkey", "Turkey"),
    # Group E
    ("Germany", "Germany"),
    ("Curacao", "Curacao"),
    ("Ivory Coast", "Ivory_Coast"),
    ("Ecuador", "Ecuador"),
    # Group F
    ("Netherlands", "Netherlands"),
    ("Japan", "Japan"),
    ("Sweden", "Sweden"),
    ("Tunisia", "Tunisia"),
    # Group G
    ("Belgium", "Belgium"),
    ("Egypt", "Egypt"),
    ("Iran", "Iran"),
    ("New Zealand", "New_Zealand"),
    # Group H
    ("Spain", "Spain"),
    ("Cape Verde", "Cape_Verde"),
    ("Saudi Arabia", "Saudi_Arabia"),
    ("Uruguay", "Uruguay"),
    # Group I
    ("France", "France"),
    ("Senegal", "Senegal"),
    ("Iraq", "Iraq"),
    ("Norway", "Norway"),
    # Group J
    ("Argentina", "Argentina"),
    ("Algeria", "Algeria"),
    ("Austria", "Austria"),
    ("Jordan", "Jordan"),
    # Group K
    ("Portugal", "Portugal"),
    ("DR Congo", "DR_Congo"),
    ("Uzbekistan", "Uzbekistan"),
    ("Colombia", "Colombia"),
    # Group L
    ("England", "England"),
    ("Croatia", "Croatia"),
    ("Ghana", "Ghana"),
    ("Panama", "Panama"),
])

HISTORY_SINCE = date(2022, 1, 1)


def fetch(url: str, cache: Path | None = None, delay: float = 0.5) -> str:
    """Fetch URL as text. If cache path given and exists, read from disk."""
    if cache is not None and cache.exists():
        return cache.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        text = resp.read().decode("utf-8")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    time.sleep(delay)
    return text


def parse_int(s: str) -> int | None:
    s = s.strip().replace("\u2212", "-")  # unicode minus -> ascii
    if s in ("", "-", "−"):
        return None
    try:
        return int(s)
    except ValueError:
        return None


def load_code_names() -> dict[str, str]:
    """2-letter code -> English team name from en.teams.tsv."""
    text = fetch(f"{BASE}/en.teams.tsv", cache=CACHE_DIR / "en.teams.tsv", delay=0)
    code_names: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2 and len(parts[0]) == 2:
            code_names[parts[0]] = parts[1]
    return code_names


def parse_team_tsv(text: str, team_code: str) -> tuple[int | None, int | None, list[dict]]:
    """Parse one team's TSV. Returns (current_elo, current_rank, history)."""
    history: list[dict] = []
    current_elo: int | None = None
    current_rank: int | None = None
    last_line: str = ""
    for line in text.splitlines():
        if not line.strip():
            continue
        last_line = line
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            yr = int(parts[0]); mo = int(parts[1]); dy = int(parts[2])
        except ValueError:
            continue
        t1, t2 = parts[3], parts[4]
        g1 = parse_int(parts[5]); g2 = parse_int(parts[6])
        tournament = parts[7]
        venue = parts[8] if len(parts) > 8 else ""
        rchg1 = parse_int(parts[9]) if len(parts) > 9 else None
        r1 = parse_int(parts[10]) if len(parts) > 10 else None
        r2 = parse_int(parts[11]) if len(parts) > 11 else None
        rank1 = parse_int(parts[14]) if len(parts) > 14 else None
        rank2 = parse_int(parts[15]) if len(parts) > 15 else None

        if r1 is not None and r2 is not None:
            history.append({
                "date": f"{yr:04d}-{mo:02d}-{dy:02d}",
                "team1_code": t1, "team2_code": t2,
                "team1_goals": g1, "team2_goals": g2,
                "tournament": tournament, "venue": venue,
                "team1_elo_after": r1, "team2_elo_after": r2,
                "team1_rank_after": rank1, "team2_rank_after": rank2,
                "team1_rating_change": rchg1,
            })

    # Current rating = rating of `team_code` in the LAST line.
    parts = last_line.split("\t") if last_line else []
    if len(parts) >= 16:
        t1, t2 = parts[3], parts[4]
        r1 = parse_int(parts[10]); r2 = parse_int(parts[11])
        rank1 = parse_int(parts[14]); rank2 = parse_int(parts[15])
        if t1 == team_code:
            current_elo, current_rank = r1, rank1
        elif t2 == team_code:
            current_elo, current_rank = r2, rank2
    return current_elo, current_rank, history


def main() -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    code_names = load_code_names()
    print(f"[info] loaded {len(code_names)} team code->name mappings")

    ratings: dict[str, dict] = {}
    all_matches: list[dict] = []
    team_code_lookup: dict[str, str] = {}  # team_name -> code (from last line)

    failures: list[str] = []
    for name, slug in TEAM_SLUGS.items():
        cache = CACHE_DIR / f"{slug}.tsv"
        url = f"{BASE}/{slug}.tsv"
        try:
            text = fetch(url, cache=cache)
        except Exception as exc:  # noqa: BLE001
            print(f"[fail] {name} ({slug}): {exc}")
            failures.append(name)
            continue

        # Detect team code: the team's own code appears in (almost) every
        # line. Take the two codes from the LAST match and pick the one with
        # higher global frequency. This handles successor states (e.g.
        # Czechia inherits Czechoslovakia's CS history but plays as CZ now).
        lines = [l for l in text.splitlines() if l.strip()]
        code_counts: Counter[str] = Counter()
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 5:
                code_counts[parts[3]] += 1
                code_counts[parts[4]] += 1
        team_code: str | None = None
        if lines:
            last_parts = lines[-1].split("\t")
            if len(last_parts) >= 5:
                candidates = {last_parts[3], last_parts[4]}
                team_code = max(candidates, key=lambda c: code_counts.get(c, 0))
        if team_code is None:
            print(f"[fail] {name}: could not detect team code")
            failures.append(name)
            continue

        elo, rank, history = parse_team_tsv(text, team_code)
        if elo is None:
            print(f"[fail] {name}: no current rating parsed")
            failures.append(name)
            continue

        ratings[name] = {
            "code": team_code,
            "slug": slug,
            "elo": elo,
            "rank": rank,
            "last_match_date": history[-1]["date"] if history else None,
            "matches_total": len(history),
        }
        team_code_lookup[name] = team_code
        all_matches.extend(history)
        print(f"[ok] {name:30s} code={team_code} elo={elo:4d} rank={rank} hist={len(history)}")

    # Dedupe matches: same match appears in both teams' TSVs.
    # Key = (date, frozenset({team1_code, team2_code}), scores).
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for m in all_matches:
        key = (m["date"], frozenset({m["team1_code"], m["team2_code"]}),
               m["team1_goals"], m["team2_goals"])
        if key in seen:
            continue
        seen.add(key)
        # Resolve names
        m["team1_name"] = code_names.get(m["team1_code"], m["team1_code"])
        m["team2_name"] = code_names.get(m["team2_code"], m["team2_code"])
        deduped.append(m)

    # Filter to history window (2022-01-01 onwards).
    since_str = HISTORY_SINCE.isoformat()
    recent = [m for m in deduped if m["date"] >= since_str]
    recent.sort(key=lambda m: m["date"])

    # Write outputs.
    ELO_OUT.parent.mkdir(parents=True, exist_ok=True)
    HIST_OUT.parent.mkdir(parents=True, exist_ok=True)
    payload_ratings = {
        "as_of": "2026-06-20",
        "source": "eloratings.net",
        "teams": ratings,
    }
    ELO_OUT.write_text(json.dumps(payload_ratings, indent=2, ensure_ascii=False), encoding="utf-8")
    payload_hist = {
        "window": "2022-01-01..2026-06-20",
        "source": "eloratings.net",
        "matches_total_deduped_alltime": len(deduped),
        "matches_in_window": len(recent),
        "matches": recent,
    }
    HIST_OUT.write_text(json.dumps(payload_hist, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print(f"=== Summary ===")
    print(f"teams fetched OK : {len(ratings)}/{len(TEAM_SLUGS)}")
    print(f"teams failed    : {len(failures)} {failures if failures else ''}")
    print(f"matches deduped : {len(deduped)} (all-time)")
    print(f"matches window  : {len(recent)} ({since_str}..2026-06-20)")
    print(f"elo file        : {ELO_OUT}")
    print(f"history file    : {HIST_OUT}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
