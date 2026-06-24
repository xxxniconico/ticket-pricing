"""Fetch expected-goals (xG) match logs from FBref for WC 2026 teams.

FBref (Opta-driven) publishes per-match xG / xGA for national teams. We use
xG instead of goals to fit the Poisson attack/defense parameters — xG is a
less noisy signal of underlying chance quality (a 0:0 may be 2.5 vs 2.3 xG,
i.e. good chances well saved, not a defensive stalemate). Research suggests
xG-based params reduce prediction error 30-40% vs goals.

Each team has a unique 8-hex squad ID and a match-logs page::

    https://fbref.com/en/squads/{squad_id}/{season}/matchlogs/all_comps/

This module emits three artifacts:

  data/raw/xg/fbref_xg_2022_2026.json        — raw per-team match logs (deduped)
  data/processed/historical_with_xg.json      — intl_results_2022_2026 + xG columns

Network note
------------
FBref is NOT reachable from the dev sandbox (HTTP 403 / rate-limit). This
module is designed to run on the user's China machine, mirroring the
fetch_elo / fetch_sporttery pattern: /tmp cache + polite delay + manual
fallback for when scraping fails.

Manual fallback
---------------
``load_manual_xg(path)`` reads a hand-typed JSON the user fills in by
viewing FBref match logs in a browser. ``save_manual_xg_template(path)``
generates an empty template from the WC 2026 match list.

See docs/plans/wc-betting-strategy-20260620.md §P0 (xG integration).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.request
from datetime import date
from html import unescape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "fbref_cache"
RAW_OUT = PROJECT_ROOT / "data/raw/xg/fbref_xg_2022_2026.json"
API_RAW_OUT = PROJECT_ROOT / "data/raw/xg/apifootball_xg_2022_2026.json"
MERGED_OUT = PROJECT_ROOT / "data/processed/historical_with_xg.json"
HIST_FILE = PROJECT_ROOT / "data/raw/historical/intl_results_2022_2026.json"
MODEL_INPUT = PROJECT_ROOT / "data/processed/wc_2026_model_input.json"

BASE = "https://fbref.com"
UA = "Mozilla/5.0 (research; wc-betting-strategy)"
REQUEST_DELAY = 0.5  # polite delay between page fetches

# Seasons to scan (FBref uses "YYYY-YYYY" for cross-year seasons).
SEASONS = ["2022-2023", "2023-2024", "2024-2025", "2025-2026"]

# Hardcoded squad IDs for the 48 WC 2026 teams. Filled in after a successful
# discovery run; used as fallback when the national-teams index page is
# unreachable. FBref squad IDs are 8-hex strings.
FBREF_SQUAD_IDS: dict[str, str] = {
    # Group A
    "Mexico": "2a8183b8",
    # The rest are populated by discover_squad_ids() on first successful run.
}


# ---- Name normalization ---------------------------------------------------

# FBref-specific aliases (applied after _NAME_ALIASES from poisson.py).
# FBref uses accented / formal names that differ from our canonical set.
# Also covers API-Football name variants since ``fetch_xg_api`` reuses
# ``_norm_fbref_name`` for its normalization.
_FBREF_NAME_ALIASES: dict[str, str] = {
    "Côte d'Ivoire": "Ivory Coast",
    "Cote d'Ivoire": "Ivory Coast",
    "Czechia": "Czech Republic",
    "Korea Republic": "South Korea",
    "IR Iran": "Iran",
    "Bosnia and Herzegovina": "Bosnia and Herzegovina",
    "United States": "United States",
    # API-Football specific variants
    "Cabo Verde": "Cape Verde",
    "Türkiye": "Turkey",
    "Turkiye": "Turkey",
    "Congo DR": "DR Congo",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Iran (Islamic Republic of)": "Iran",
}


def _norm_fbref_name(name: str) -> str:
    """Normalize an FBref team name to our canonical WC 2026 name.

    Reuses poisson._NAME_ALIASES so the same alias table covers both Elo
    and FBref sources, then applies FBref-specific overrides.
    """
    if not name:
        return ""
    s = unescape(name).strip()
    # Strip " men's" suffix (FBref labels men's NTs explicitly).
    for suffix in (" men's", " mens", " Men"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    # Apply poisson's aliases first (USA, Czechia, etc.).
    try:
        from wc_betting.models.poisson import _NAME_ALIASES
        s = _NAME_ALIASES.get(s, s)
    except Exception:  # noqa: BLE001 — poisson import may fail in isolation
        pass
    # FBref-specific overrides.
    s = _FBREF_NAME_ALIASES.get(s, s)
    return s


# ---- HTTP fetch (reuses fetch_elo pattern) --------------------------------

def _fetch_text(url: str, cache: Path | None = None,
                delay: float = REQUEST_DELAY, timeout: int = 30) -> str:
    """Fetch URL as text, caching to disk. Reuses fetch_elo pattern."""
    if cache is not None and cache.exists():
        return cache.read_text(encoding="utf-8")
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(text, encoding="utf-8")
    time.sleep(delay)
    return text


# ---- Squad ID discovery ---------------------------------------------------

# National-team squad links on the FBref index look like:
#   /en/squads/{8-hex-id}/National-Team-Name-Stats
_SQUAD_LINK_RE = re.compile(r"/en/squads/([0-9a-f]{8})/([^\"'/]+)")


def discover_squad_ids() -> dict[str, str]:
    """Scrape the FBref national-teams index → {canonical_team_name: squad_id}.

    Caches to /tmp/fbref_cache/squad_ids.json so repeat runs are offline.
    """
    cache = CACHE_DIR / "squad_ids.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))

    url = f"{BASE}/en/national-teams/"
    text = _fetch_text(url, cache=CACHE_DIR / "national_teams.html")

    raw: dict[str, str] = {}
    for squad_id, slug in _SQUAD_LINK_RE.findall(text):
        # slug is like "Brazil-Men-Stats" or "Brazil-Stats"; strip suffixes.
        name = slug.replace("-Stats", "").replace("-Men", "").replace("-", " ")
        name = unescape(name).strip()
        if not name:
            continue
        canon = _norm_fbref_name(name)
        if canon:
            raw.setdefault(canon, squad_id)

    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(raw, indent=2, ensure_ascii=False), encoding="utf-8")
    return raw


# ---- Match-logs parsing ---------------------------------------------------

def _parse_matchlogs(html: str, team_canonical: str) -> list[dict]:
    """Parse one team's match-logs HTML → list of per-match xG dicts.

    FBref stores the match logs in ``<table id="matchlogs_for">``. Columns we
    extract: Date, Opponent, Venue, Comp, xG (for), xGA (against), GF, GA.
    Rows where xG is empty (some friendlies) are skipped.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="matchlogs_for")
    if table is None:
        return []

    # Column index lookup from the header row.
    header = table.find("thead")
    col_idx: dict[str, int] = {}
    if header:
        ths = header.find_all("th")
        for i, th in enumerate(ths):
            # FBref wraps some headers in <th> with data-stat attr (more reliable).
            stat = th.get("data-stat") or th.get_text(strip=True).lower()
            col_idx[stat] = i
    # Fallback header names (data-stat values are lowercase, no spaces).
    def col_of(*keys: str) -> int | None:
        for k in keys:
            if k in col_idx:
                return col_idx[k]
        return None

    i_date = col_of("date")
    i_opp = col_of("opponent")
    i_venue = col_of("venue")
    i_comp = col_of("comp", "competition")
    i_xg = col_of("xg")
    i_xga = col_of("xga")
    i_gf = col_of("gf")
    i_ga = col_of("ga")
    if i_date is None or i_opp is None:
        return []

    out: list[dict] = []
    body = table.find("tbody") or table
    for tr in body.find_all("tr"):
        # Skip section-separator rows (FBref inserts <tr class="spacer">).
        if "spacer" in (tr.get("class") or []):
            continue
        tds = tr.find_all("td")
        if len(tds) <= max(filter(None, [i_date, i_opp, i_xg, i_xga])):
            continue

        def cell(idx: int | None) -> str:
            if idx is None or idx >= len(tds):
                return ""
            return tds[idx].get_text(strip=True)

        date_s = cell(i_date)
        opp = cell(i_opp)
        xg_s = cell(i_xg)
        xga_s = cell(i_xga)
        if not date_s or not opp or not xg_s:
            continue  # no xG → skip (partial friendlies)

        try:
            xg_for = float(xg_s)
            xg_again = float(xga_s) if xga_s else None
        except ValueError:
            continue
        if xg_again is None:
            continue

        gf = cell(i_gf)
        ga = cell(i_ga)
        try:
            goals_for = int(gf) if gf != "" else None
            goals_again = int(ga) if ga != "" else None
        except ValueError:
            goals_for = goals_again = None

        venue = cell(i_venue)
        venue_code = {"Home": "H", "Away": "A", "Neutral": "N"}.get(
            venue, venue[:1] if venue else "")
        comp = cell(i_comp)

        out.append({
            "date": date_s,
            "team": team_canonical,
            "opponent": _norm_fbref_name(opp),
            "xg_for": xg_for,
            "xg_again": xg_again,
            "goals_for": goals_for,
            "goals_again": goals_again,
            "venue": venue_code,
            "comp": comp,
        })
    return out


def fetch_team_matchlogs(squad_id: str, seasons: list[str],
                         team_canonical: str) -> list[dict]:
    """Fetch all seasons of match logs for one team. Returns per-match dicts."""
    all_rows: list[dict] = []
    for season in seasons:
        url = f"{BASE}/en/squads/{squad_id}/{season}/matchlogs/all_comps/"
        cache = CACHE_DIR / f"{squad_id}_{season}.html"
        try:
            html = _fetch_text(url, cache=cache)
        except Exception as exc:  # noqa: BLE001
            print(f"[fetch_xg] {team_canonical} {season} failed: {exc}",
                  file=sys.stderr)
            continue
        rows = _parse_matchlogs(html, team_canonical)
        all_rows.extend(rows)
        print(f"[fetch_xg] {team_canonical:30s} {season}: {len(rows)} matches")
    return all_rows


# ---- Aggregate + dedupe ---------------------------------------------------

def fetch_all_xg(team_names: list[str] | None = None,
                 seasons: list[str] | None = None) -> dict:
    """Fetch xG match logs for all WC 2026 teams, dedupe, write to RAW_OUT.

    Each match appears in both teams' logs; we dedupe by
    ``(date, frozenset({team, opponent}))``. The two teams' xG values are
    complementary (team_xg_for == opponent_xg_again), so we keep one view.

    Returns the payload dict (also written to RAW_OUT).
    """
    seasons = seasons or SEASONS
    squad_ids = discover_squad_ids()
    # Merge hardcoded fallbacks (e.g. Mexico) over discovered IDs.
    squad_ids = {**squad_ids, **FBREF_SQUAD_IDS}

    if team_names is None:
        # Default: the 48 WC 2026 teams we have Elo ratings for.
        from wc_betting.models.poisson import FEDERATIONS
        team_names = list(FEDERATIONS.keys())

    all_rows: list[dict] = []
    missing: list[str] = []
    for name in team_names:
        sid = squad_ids.get(name)
        if not sid:
            # Try a few alias variants before giving up.
            sid = squad_ids.get(_norm_fbref_name(name))
        if not sid:
            missing.append(name)
            continue
        rows = fetch_team_matchlogs(sid, seasons, name)
        all_rows.extend(rows)

    if missing:
        print(f"[fetch_xg] {len(missing)} teams missing squad ID: {missing}",
              file=sys.stderr)

    # Dedupe: key = (date, frozenset({team, opponent})). xG is symmetric so
    # we can take either team's view (they should agree).
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in all_rows:
        pair = frozenset({r["team"], r["opponent"]})
        key = (r["date"], pair)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    deduped.sort(key=lambda r: r["date"])

    payload = {
        "source": "fbref.com",
        "seasons": seasons,
        "teams_requested": len(team_names),
        "teams_with_squad_id": len(team_names) - len(missing),
        "matches_total_raw": len(all_rows),
        "matches_deduped": len(deduped),
        "missing_squad_ids": missing,
        "matches": deduped,
    }
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    print(f"[fetch_xg] wrote {RAW_OUT} ({len(deduped)} deduped matches)")
    return payload


# ---- Merge with historical -----------------------------------------------

def _load_one_xg_file(p: Path) -> list[dict]:
    """Load matches from a single xG JSON file (FBref or API-FOOTBALL format)."""
    if not p.exists():
        return []
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "matches" in data:
        return data["matches"]
    if isinstance(data, list):
        return data
    return []


def load_xg_matches(path: Path | None = None) -> list[dict]:
    """Load xG matches from FBref + API-FOOTBALL (dual source, deduped).

    When ``path`` is given, loads only that file (backward compatibility for
    tests / manual single-source use). Otherwise loads both:

      1. ``API_RAW_OUT`` (apifootball_xg_2022_2026.json) — **preferred**
      2. ``RAW_OUT`` (fbref_xg_2022_2026.json) — fallback

    On conflict (same date + team pair) the API-FOOTBALL entry wins because
    it's an official API vs a web scrape. Dedup key is
    ``(date, frozenset({team, opponent}))``.
    """
    if path is not None:
        return _load_one_xg_file(path)

    matches: list[dict] = []
    seen: set[tuple] = set()
    # API-FOOTBALL first — wins on conflict (official API > web scrape).
    for f in [API_RAW_OUT, RAW_OUT]:
        for m in _load_one_xg_file(f):
            key = (m["date"], frozenset({m["team"], m["opponent"]}))
            if key not in seen:
                matches.append(m)
                seen.add(key)
    return matches


def _build_xg_lookup(xg_matches: list[dict]) -> dict[tuple, tuple[float, float]]:
    """Build {(date, frozenset({team1, team2})): (xg_team1, xg_team2)}.

    The xG values are stored from one team's perspective (xg_for = team's xG,
    xg_again = opponent's xG). We canonicalize so the returned tuple is keyed
    to the frozenset, with team1_xg first when team1 matches the stored
    "team" field.
    """
    lookup: dict[tuple, tuple[float, float]] = {}
    for r in xg_matches:
        pair = frozenset({r["team"], r["opponent"]})
        key = (r["date"], pair)
        # (xg_for_team, xg_for_opponent) — team's perspective.
        lookup[key] = (r["xg_for"], r["xg_again"])
    return lookup


def merge_xg_with_historical(xg_matches: list[dict] | None = None,
                             hist_path: Path | None = None) -> list[dict]:
    """Read intl_results_2022_2026.json, attach team1_xg / team2_xg per match.

    Matching: first by (date, team1_name) exact against the xG lookup (using
    the frozenset pair as key so team order doesn't matter). Falls back to
    name normalization if the raw names differ. Matches without xG get None.

    Returns the merged match list (also written to MERGED_OUT).
    """
    xg_matches = xg_matches if xg_matches is not None else load_xg_matches()
    hist_path = hist_path or HIST_FILE
    hist = json.loads(hist_path.read_text(encoding="utf-8"))
    matches = hist["matches"] if isinstance(hist, dict) else hist

    lookup = _build_xg_lookup(xg_matches)

    merged: list[dict] = []
    n_with_xg = 0
    for m in matches:
        m = dict(m)  # shallow copy; don't mutate the source dict
        t1 = _norm_fbref_name(m.get("team1_name", ""))
        t2 = _norm_fbref_name(m.get("team2_name", ""))
        pair = frozenset({t1, t2}) - {""}
        key = (m.get("date", ""), pair)
        xg_pair = lookup.get(key)
        if xg_pair is None:
            # Fallback: try unnormalized names in case FBref used a different
            # spelling that _norm_fbref_name collapsed differently.
            for r_date, r_pair in lookup:
                if r_date != m.get("date", ""):
                    continue
                if r_pair == pair:
                    xg_pair = lookup[(r_date, r_pair)]
                    break
        if xg_pair is not None:
            # xg_pair is (xg_for_team_stored, xg_for_opponent_stored).
            # We need to align it to (team1, team2). Re-fetch the original
            # row to know which team was the "team" perspective.
            # The lookup collapsed perspective; rebuild by searching xg_matches.
            # This is O(N) but only on matched rows; acceptable for 2k matches.
            for r in xg_matches:
                if r["date"] == m.get("date", "") and (
                        {r["team"], r["opponent"]} == pair):
                    if r["team"] == t1:
                        m["team1_xg"], m["team2_xg"] = r["xg_for"], r["xg_again"]
                    elif r["team"] == t2:
                        m["team1_xg"], m["team2_xg"] = r["xg_again"], r["xg_for"]
                    else:
                        # Team names normalized to something else; assume
                        # stored team maps to team1 by position.
                        m["team1_xg"], m["team2_xg"] = r["xg_for"], r["xg_again"]
                    break
            else:
                m["team1_xg"] = None
                m["team2_xg"] = None
        else:
            m["team1_xg"] = None
            m["team2_xg"] = None
        if m["team1_xg"] is not None:
            n_with_xg += 1
        merged.append(m)

    out_payload = {
        "source": "intl_results_2022_2026 + fbref_xg + apifootball_xg",
        "matches_total": len(merged),
        "matches_with_xg": n_with_xg,
        "xg_coverage_pct": round(100.0 * n_with_xg / max(1, len(merged)), 1),
        "matches": merged,
    }
    MERGED_OUT.parent.mkdir(parents=True, exist_ok=True)
    MERGED_OUT.write_text(json.dumps(out_payload, indent=2, ensure_ascii=False),
                          encoding="utf-8")
    print(f"[fetch_xg] wrote {MERGED_OUT} "
          f"({n_with_xg}/{len(merged)} = {out_payload['xg_coverage_pct']}% with xG)")
    return merged


def load_historical_with_xg() -> list[dict] | None:
    """Load data/processed/historical_with_xg.json → match list, or None.

    Returns None (not []) when the file is missing, so callers can
    distinguish "xG pipeline not run yet" from "ran but 0 matches merged".
    """
    if not MERGED_OUT.exists():
        return None
    data = json.loads(MERGED_OUT.read_text(encoding="utf-8"))
    matches = data["matches"] if isinstance(data, dict) else data
    return matches if matches else None


def xg_coverage(matches: list[dict]) -> dict:
    """Compute {total, with_xg, pct} for a match list with team1_xg fields."""
    total = len(matches)
    with_xg = sum(1 for m in matches if m.get("team1_xg") is not None)
    return {"total": total, "with_xg": with_xg,
            "pct": round(100.0 * with_xg / max(1, total), 1)}


# ---- Manual xG fallback ---------------------------------------------------

def save_manual_xg_template(path: str | Path,
                            matches: list[dict] | None = None) -> None:
    """Write a stub template the user can fill in by hand.

    ``matches`` defaults to the WC 2026 match list from MODEL_INPUT. The
    template has one entry per match with empty xG/goals fields.
    """
    if matches is None:
        mi = json.loads(MODEL_INPUT.read_text(encoding="utf-8"))
        matches = mi.get("matches", [])
    out: list[dict] = []
    for m in matches:
        out.append({
            "date": m.get("date", ""),
            "home": m.get("home", ""),
            "away": m.get("away", ""),
            "home_xg": None,
            "away_xg": None,
            "home_goals": None,
            "away_goals": None,
        })
    Path(path).write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def load_manual_xg(path: str | Path) -> list[dict]:
    """Load manually-typed xG from a JSON file.

    Expected schema::

        [
          {"date": "2026-06-15", "home": "Brazil", "away": "Argentina",
           "home_xg": 1.5, "away_xg": 0.8, "home_goals": 2, "away_goals": 1},
          ...
        ]

    Returns a list normalized to the same shape as FBref match-log rows
    (``team``/``opponent``/``xg_for``/``xg_again``/...) so downstream merge
    logic can treat both sources uniformly.
    """
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "matches" in data:
        data = data["matches"]
    if not isinstance(data, list):
        raise ValueError("manual xG file must be a list or {matches: [...]}")
    out: list[dict] = []
    for row in data:
        if not isinstance(row, dict):
            continue
        home = row.get("home") or row.get("team")
        away = row.get("away") or row.get("opponent")
        if not home or not away:
            continue
        out.append({
            "date": row.get("date", ""),
            "team": _norm_fbref_name(home),
            "opponent": _norm_fbref_name(away),
            "xg_for": _to_float(row.get("home_xg") or row.get("xg_for")),
            "xg_again": _to_float(row.get("away_xg") or row.get("xg_again")),
            "goals_for": row.get("home_goals") or row.get("goals_for"),
            "goals_again": row.get("away_goals") or row.get("goals_again"),
            "venue": row.get("venue", ""),
            "comp": row.get("comp", "Manual"),
        })
    return [r for r in out if r["xg_for"] is not None and r["xg_again"] is not None]


def _to_float(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s or s in ("-", "—", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---- CLI ------------------------------------------------------------------

def main() -> int:
    """Fetch FBref xG for all WC 2026 teams, merge with historical."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    payload = fetch_all_xg()
    print()
    print(f"=== FBref xG fetch summary ===")
    print(f"teams with squad ID : {payload['teams_with_squad_id']}/{payload['teams_requested']}")
    print(f"matches raw         : {payload['matches_total_raw']}")
    print(f"matches deduped     : {payload['matches_deduped']}")
    if payload["missing_squad_ids"]:
        print(f"missing squad IDs   : {payload['missing_squad_ids']}")
    print(f"raw file            : {RAW_OUT}")
    print()
    # Merge with historical.
    merged = merge_xg_with_historical(payload["matches"])
    cov = xg_coverage(merged)
    print(f"xG coverage: {cov['with_xg']}/{cov['total']} = {cov['pct']}%")
    print(f"merged file : {MERGED_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
