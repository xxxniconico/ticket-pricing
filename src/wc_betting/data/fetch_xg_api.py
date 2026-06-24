"""Fetch xG data from API-Football (api-sports.io) for international matches.

FBref does NOT publish xG for national team matches (only clubs). API-Football
v3 provides xG for major international competitions via the
``/fixtures/statistics`` endpoint (field name ``Expected Goals (xG)``).

Free plan: 100 requests/day. Each match costs 1 API call (``/fixtures/statistics``)
plus 1 call per league+season for fixture discovery. With 13 leagues x 4 seasons
= 52 discovery calls, the first day processes ~48 matches; subsequent days
process ~100/day. A 300-500 match dataset typically takes 4-6 days.

Output format is identical to ``fetch_xg.py`` (FBref-compatible) so the
existing merge pipeline works unchanged::

    {"date": "2024-06-14", "team": "Germany", "opponent": "Scotland",
     "xg_for": 2.15, "xg_again": 0.82, "goals_for": 5, "goals_again": 1,
     "venue": "N", "comp": "Euro"}

Auth
----
Set the API key via env var ``API_FOOTBALL_KEY`` or add it to the project
``.env`` file (already gitignored)::

    echo 'API_FOOTBALL_KEY=your_key' >> .env
    PYTHONPATH=src python -m wc_betting.data.fetch_xg_api

Rate limit strategy
-------------------
- Every API response is cached to ``/tmp/api_football_cache/`` so re-runs
  don't re-fetch (discovery calls are free on day 2+).
- A progress file (``data/raw/xg/.api_progress.json``) tracks fetched/pending
  fixture IDs and the current day's request count.
- If the daily limit is hit, run again the next day — it resumes from the
  last checkpoint.
- The ``/status`` endpoint is checked at startup for the authoritative
  remaining quota.

See docs/plans/wc-betting-strategy-20260620.md §P0 (xG integration).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "api_football_cache"
RAW_OUT = PROJECT_ROOT / "data/raw/xg/apifootball_xg_2022_2026.json"
PROGRESS_FILE = PROJECT_ROOT / "data/raw/xg/.api_progress.json"

API_BASE = "https://v3.football.api-sports.io"
UA = "Mozilla/5.0 (research; wc-betting-strategy)"
REQUEST_DELAY = 0.5  # polite delay between live API calls
SAVE_EVERY = 10  # save RAW_OUT + progress every N processed fixtures
DAILY_LIMIT_MARGIN = 5  # stop when this many requests remain (safety buffer)

# National team competition league IDs in API-Football v3.
# Confirmed via /leagues?search=World%20Cup and /leagues?search=Euro.
# Only major tournaments have xG (Opta coverage). Friendlies (league=9)
# and some older qualifiers may not have xG.
NATIONAL_LEAGUES: dict[int, str] = {
    1:  "World Cup",
    4:  "Euro",
    5:  "UEFA Nations League",
    9:  "Friendlies",
    13: "Copa America",
    16: "African Cup of Nations",
    17: "AFC Asian Cup",
    29: "WC Qualification Africa",
    30: "WC Qualification Asia",
    31: "WC Qualification CONCACAF",
    32: "WC Qualification Europe",
    33: "WC Qualification Oceania",
    34: "WC Qualification South America",
}

SEASONS = [2022, 2023, 2024, 2025]

# Date range filter — matches our historical data coverage.
DATE_MIN = "2022-01-01"
DATE_MAX = "2026-12-31"


# ---- API key management ---------------------------------------------------

def _get_api_key() -> str:
    """Resolve the API-Football API key from env var or ``.env`` file.

    Resolution order:
      1. ``API_FOOTBALL_KEY`` environment variable.
      2. ``API_FOOTBALL_KEY=...`` line in ``PROJECT_ROOT/.env`` (gitignored).
      3. Raise ``RuntimeError``.
    """
    key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if key:
        return key

    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("#") or not line:
                continue
            if line.startswith("API_FOOTBALL_KEY="):
                key = line.split("=", 1)[1].strip().strip('"').strip("'")
                if key:
                    return key

    raise RuntimeError(
        "API_FOOTBALL_KEY not found. Set it via the API_FOOTBALL_KEY env var "
        "or add 'API_FOOTBALL_KEY=your_key' to "
        f"{env_path.relative_to(PROJECT_ROOT)}"
    )


# ---- HTTP client ----------------------------------------------------------

def _cache_key(endpoint: str, params: dict) -> Path:
    """Build a cache file path for an endpoint + sorted params."""
    query = urllib.parse.urlencode(sorted(params.items()))
    safe = endpoint.replace("/", "_").strip("_")
    return CACHE_DIR / f"{safe}_{query}.json"


def _api_get(endpoint: str, params: dict | None = None,
             cache: bool = True) -> dict | list | None:
    """GET an API-Football endpoint with caching and error handling.

    Sets the ``x-apisports-key`` header from ``_get_api_key()``. On HTTP 429
    (rate limit) prints a warning and returns ``None`` so the caller can stop.
    All successful responses are cached to disk so re-runs don't consume the
    daily quota.
    """
    params = params or {}
    cache_path = _cache_key(endpoint, params)
    if cache and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    api_key = _get_api_key()
    url = f"{API_BASE}{endpoint}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "application/json",
        "x-apisports-key": api_key,
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            print("[api-football] RATE LIMIT HIT (429). Come back tomorrow.",
                  file=sys.stderr)
        else:
            body = exc.read().decode("utf-8", errors="replace")[:200]
            print(f"[api-football] HTTP {exc.code} on {endpoint}: {body}",
                  file=sys.stderr)
        return None
    except Exception as exc:  # noqa: BLE001 — network errors are non-fatal
        print(f"[api-football] {type(exc).__name__} on {endpoint}: {exc}",
              file=sys.stderr)
        return None

    data = json.loads(text)
    if cache:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    time.sleep(REQUEST_DELAY)
    return data


# ---- Status / quota -------------------------------------------------------

def fetch_status() -> dict:
    """Check ``/status`` for the current daily quota usage.

    Returns ``{plan, current, limit_day, remaining}``. The ``/status``
    endpoint is not cached (always live) so we get the authoritative count.
    """
    data = _api_get("/status", cache=False)
    if not data or "response" not in data:
        return {"plan": "?", "current": 0, "limit_day": 100, "remaining": 100}
    resp = data["response"]
    current = resp.get("requests", {}).get("current", 0)
    limit_day = resp.get("requests", {}).get("limit_day", 100)
    return {
        "plan": resp.get("subscription", {}).get("plan", "Unknown"),
        "current": current,
        "limit_day": limit_day,
        "remaining": max(0, limit_day - current),
    }


# ---- Name normalization ---------------------------------------------------

def _norm_name(name: str) -> str:
    """Normalize an API-Football team name to canonical WC 2026 name.

    Reuses ``fetch_xg._norm_fbref_name()`` so both sources share the same
    alias table (poisson ``_NAME_ALIASES`` + FBref-specific overrides).
    API-Football-specific aliases (Cabo Verde, Türkiye, etc.) are added
    to ``_FBREF_NAME_ALIASES`` in ``fetch_xg.py``.
    """
    from wc_betting.data.fetch_xg import _norm_fbref_name
    return _norm_fbref_name(name)


# ---- Fixture list fetching ------------------------------------------------

def fetch_fixtures(league_id: int, season: int) -> list[dict]:
    """Fetch all fixtures for one league + season (1 API call).

    Returns the raw API response list. Each item has:
    ``fixture.{id, date, timestamp}``, ``teams.home.{name, winner}``,
    ``teams.away.{name, winner}``, ``goals.{home, away}``,
    ``league.{id, name, season}``.
    """
    data = _api_get("/fixtures", {"league": league_id, "season": season})
    if not data or "response" not in data:
        return []
    fixtures = data["response"]
    print(f"[api-football] league={league_id} "
          f"({NATIONAL_LEAGUES.get(league_id, '?')}) season={season}: "
          f"{len(fixtures)} fixtures")
    return fixtures


# ---- Single-fixture xG extraction -----------------------------------------

def _extract_xg_from_stats(stats_response: list) -> dict[str, float | None]:
    """Parse ``/fixtures/statistics`` response → ``{team_name: xg_value}``.

    The xG statistic type name varies by competition:
    ``"Expected Goals (xG)"``, ``"xG"``, ``"expected_goals"``.
    Returns ``None`` for teams with no xG entry (old matches).
    """
    result: dict[str, float | None] = {}
    for entry in stats_response:
        team_name = _norm_name(entry.get("team", {}).get("name", ""))
        xg_val: float | None = None
        for stat in entry.get("statistics", []):
            stat_type = (stat.get("type") or "").lower()
            if "expected goals" in stat_type or stat_type in ("xg", "expected_goals"):
                val = stat.get("value")
                if val is not None:
                    try:
                        xg_val = float(val)
                    except (ValueError, TypeError):
                        pass
                break
        result[team_name] = xg_val
    return result


def fetch_fixture_xg(fixture_id: int, fixture_meta: dict | None = None) -> dict | None:
    """Fetch xG for a single fixture. Returns FBref-compatible dict or ``None``.

    Calls ``/fixtures/statistics?fixture={fixture_id}`` (1 API call). If
    ``fixture_meta`` is provided (from a prior ``fetch_fixtures`` call), uses
    it for date/teams/goals; otherwise fetches ``/fixtures?id={fixture_id}``
    (cached, 1 extra call on first run).

    Output format (identical to ``fetch_xg.py``)::

        {"date": "2024-06-14", "team": "Germany", "opponent": "Scotland",
         "xg_for": 2.15, "xg_again": 0.82, "goals_for": 5, "goals_again": 1,
         "venue": "N", "comp": "Euro", "fixture_id": 1145509}

    Returns ``None`` when:
      - The statistics endpoint fails (network/rate limit).
      - The response is empty (match not yet played or no stats).
      - Neither team has an xG value (old matches without Opta coverage).
    """
    stats_data = _api_get("/fixtures/statistics", {"fixture": fixture_id})
    if not stats_data or "response" not in stats_data:
        return None

    stats_response = stats_data["response"]
    if not stats_response:
        return None  # no statistics available (match not played / no coverage)

    xg_by_team = _extract_xg_from_stats(stats_response)

    # Get fixture metadata (date, teams, goals) — from parameter or API.
    if fixture_meta is None:
        fx_data = _api_get("/fixtures", {"id": fixture_id})
        if not fx_data or not fx_data.get("response"):
            return None
        fixture_meta = fx_data["response"][0]

    date_s = (fixture_meta.get("fixture", {}).get("date", "") or "")[:10]
    home_raw = fixture_meta.get("teams", {}).get("home", {}).get("name", "")
    away_raw = fixture_meta.get("teams", {}).get("away", {}).get("name", "")
    home = _norm_name(home_raw)
    away = _norm_name(away_raw)
    home_goals = fixture_meta.get("goals", {}).get("home")
    away_goals = fixture_meta.get("goals", {}).get("away")

    if not home or not away:
        return None

    # Match xG values to teams (keys in xg_by_team are normalized names).
    home_xg = xg_by_team.get(home)
    away_xg = xg_by_team.get(away)
    # Fallback: try matching via raw name in case normalization differed.
    if home_xg is None:
        for key, val in xg_by_team.items():
            if _norm_name(key) == home or key == home_raw:
                home_xg = val
                break
    if away_xg is None:
        for key, val in xg_by_team.items():
            if _norm_name(key) == away or key == away_raw:
                away_xg = val
                break

    if home_xg is None and away_xg is None:
        return None  # no xG for this fixture (old match without Opta coverage)

    league_id = fixture_meta.get("league", {}).get("id")
    comp = NATIONAL_LEAGUES.get(league_id,
                                fixture_meta.get("league", {}).get("name", ""))

    return {
        "date": date_s,
        "team": home,
        "opponent": away,
        "xg_for": home_xg if home_xg is not None else 0.0,
        "xg_again": away_xg if away_xg is not None else 0.0,
        "goals_for": home_goals,
        "goals_again": away_goals,
        "venue": "N",  # international matches are neutral unless WCQ
        "comp": comp,
        "fixture_id": fixture_id,
    }


# ---- Progress tracking (resume support) -----------------------------------

def _load_progress() -> dict:
    """Load the progress file, resetting the daily count if the date changed.

    The progress file schema::

        {
          "date": "2026-06-22",
          "requests_today": 45,
          "discovery_done": true,
          "fetched_ids": [1145509, ...],
          "pending_ids": [1145520, ...],
          "fixture_meta": {"1145520": {...raw fixture dict...}, ...}
        }

    On a new day, ``requests_today`` resets to 0 but ``fetched_ids`` and
    ``pending_ids`` persist (so we don't re-process fixtures).
    """
    if PROGRESS_FILE.exists():
        try:
            prog = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            prog = {}
    else:
        prog = {}

    today = str(date.today())
    if prog.get("date") != today:
        prog["date"] = today
        prog["requests_today"] = 0
    return prog


def _save_progress(prog: dict) -> None:
    """Persist the progress file (atomic write to .api_progress.json)."""
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(
        json.dumps(prog, indent=2, ensure_ascii=False),
        encoding="utf-8")


def _save_raw(matches: list[dict], extra: dict | None = None) -> None:
    """Write the current match list to ``RAW_OUT`` (sorted by date)."""
    sorted_matches = sorted(matches, key=lambda r: r["date"])
    payload: dict = {
        "source": "api-football.com",
        "matches_total": len(sorted_matches),
        "matches": sorted_matches,
    }
    if extra:
        payload.update(extra)
    RAW_OUT.parent.mkdir(parents=True, exist_ok=True)
    RAW_OUT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8")


# ---- Batch fetch with rate management -------------------------------------

def fetch_all_xg_api(seasons: list[int] | None = None) -> dict:
    """Fetch xG for all international matches (rate-limited, resumable).

    Pipeline:
      1. Load progress file (fetched_ids, pending_ids, fixture_meta).
      2. Check ``/status`` for the authoritative remaining daily quota.
      3. If discovery not done: fetch fixture lists for all leagues x seasons
         (13 leagues x 4 seasons = 52 calls on day 1; cached afterward).
      4. For each pending fixture: call ``fetch_fixture_xg()`` (1 call each).
      5. Save ``RAW_OUT`` + progress every ``SAVE_EVERY`` matches.
      6. Stop when ``remaining <= DAILY_LIMIT_MARGIN``.
      7. Dedupe and write final ``RAW_OUT``.

    Multi-day resume: run again the next day to continue from the checkpoint.
    """
    seasons = seasons or SEASONS
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # --- Step 1: check daily quota via /status (authoritative) ---
    status = fetch_status()
    remaining = status["remaining"]
    print(f"[api-football] Status: plan={status['plan']}, "
          f"used={status['current']}/{status['limit_day']}, "
          f"remaining={remaining}")

    if remaining <= DAILY_LIMIT_MARGIN:
        print(f"[api-football] Daily limit nearly reached ({remaining} left). "
              "Come back tomorrow.")
        return {"matches": [], "remaining": remaining, "status": "limit_reached"}

    # --- Step 2: load progress ---
    prog = _load_progress()
    fetched_ids: set[int] = set(prog.get("fetched_ids", []))

    # --- Step 3: discovery (fetch fixture lists if not done) ---
    if not prog.get("discovery_done"):
        print(f"[api-football] Discovering fixtures: "
              f"{len(NATIONAL_LEAGUES)} leagues x {len(seasons)} seasons")
        fixture_meta: dict[str, dict] = {}
        pending_ids: list[int] = []
        discovery_interrupted = False

        for league_id, league_name in NATIONAL_LEAGUES.items():
            if remaining <= DAILY_LIMIT_MARGIN:
                print(f"[api-football] Approaching daily limit during "
                      f"discovery ({remaining} left). Will continue tomorrow.")
                discovery_interrupted = True
                break
            for season in seasons:
                if remaining <= DAILY_LIMIT_MARGIN:
                    discovery_interrupted = True
                    break
                fixtures = fetch_fixtures(league_id, season)
                remaining -= 1  # one /fixtures call consumed

                for fx in fixtures:
                    fid = fx.get("fixture", {}).get("id")
                    if fid is None:
                        continue
                    date_s = (fx.get("fixture", {}).get("date", "") or "")[:10]
                    if date_s < DATE_MIN or date_s > DATE_MAX:
                        continue
                    if fid in fetched_ids:
                        continue
                    fixture_meta[str(fid)] = fx
                    pending_ids.append(fid)

            # Save progress after each league (so interrupt is recoverable).
            prog["pending_ids"] = pending_ids
            prog["fixture_meta"] = fixture_meta
            prog["discovery_done"] = not discovery_interrupted
            _save_progress(prog)

        print(f"[api-football] Discovery: {len(pending_ids)} pending fixtures, "
              f"{remaining} requests remaining today")
    else:
        pending_ids: list[int] = prog.get("pending_ids", [])
        fixture_meta: dict[str, dict] = prog.get("fixture_meta", {})
        print(f"[api-football] Resuming: {len(pending_ids)} pending, "
              f"{len(fetched_ids)} already fetched")

    if not pending_ids:
        print("[api-football] All fixtures processed!")
        if RAW_OUT.exists():
            data = json.loads(RAW_OUT.read_text(encoding="utf-8"))
            return data
        return {"matches": [], "status": "complete"}

    # --- Step 4: fetch xG for pending fixtures ---
    # Load existing matches from RAW_OUT (from prior run).
    existing_matches: list[dict] = []
    seen_keys: set[tuple] = set()
    if RAW_OUT.exists():
        try:
            raw = json.loads(RAW_OUT.read_text(encoding="utf-8"))
            rows = raw.get("matches", []) if isinstance(raw, dict) else raw
            for m in rows:
                key = (m["date"], frozenset({m["team"], m["opponent"]}))
                if key not in seen_keys:
                    seen_keys.add(key)
                    existing_matches.append(m)
        except (json.JSONDecodeError, OSError, KeyError):
            pass

    batch_matches = list(existing_matches)
    n_new = 0
    n_no_xg = 0
    n_failures = 0
    n_processed_this_run = 0

    while pending_ids and remaining > DAILY_LIMIT_MARGIN:
        fid = pending_ids.pop(0)
        meta = fixture_meta.get(str(fid))

        try:
            result = fetch_fixture_xg(fid, fixture_meta=meta)
            remaining -= 1  # /fixtures/statistics call consumed
            prog["requests_today"] = prog.get("requests_today", 0) + 1
            n_processed_this_run += 1

            if result is None:
                n_no_xg += 1
            else:
                key = (result["date"],
                       frozenset({result["team"], result["opponent"]}))
                if key not in seen_keys:
                    seen_keys.add(key)
                    batch_matches.append(result)
                    n_new += 1
        except Exception as exc:  # noqa: BLE001 — keep going on per-fixture errors
            n_failures += 1
            print(f"[api-football] Error on fixture {fid}: {exc}",
                  file=sys.stderr)
            remaining -= 1
            prog["requests_today"] = prog.get("requests_today", 0) + 1

        fetched_ids.add(fid)
        prog["fetched_ids"] = list(fetched_ids)
        prog["pending_ids"] = pending_ids

        # Save every SAVE_EVERY processed fixtures.
        if n_processed_this_run % SAVE_EVERY == 0:
            _save_raw(batch_matches)
            _save_progress(prog)
            print(f"[api-football] Progress: +{n_new} xG, {n_no_xg} no-xG, "
                  f"{remaining} requests left, {len(pending_ids)} pending")

    # --- Step 5: final save ---
    _save_raw(batch_matches, extra={
        "seasons": seasons,
        "leagues_scanned": {str(k): v for k, v in NATIONAL_LEAGUES.items()},
        "fixtures_processed": len(fetched_ids),
        "fixtures_with_xg": sum(
            1 for m in batch_matches if m.get("xg_for") is not None),
    })
    _save_progress(prog)

    # --- Summary ---
    print(f"\n[api-football] === Summary ===")
    print(f"  new with xG     : {n_new}")
    print(f"  without xG      : {n_no_xg}")
    print(f"  failures        : {n_failures}")
    print(f"  total matches   : {len(batch_matches)}")
    print(f"  remaining today : {remaining}")
    print(f"  pending         : {len(pending_ids)}")
    if pending_ids:
        print(f"  -> Run again tomorrow to continue "
              f"({len(pending_ids)} fixtures left)")
    else:
        print(f"  -> All fixtures processed!")
    print(f"  output          : {RAW_OUT}")

    return {
        "matches": batch_matches,
        "remaining": remaining,
        "pending": len(pending_ids),
        "new_with_xg": n_new,
        "no_xg": n_no_xg,
        "failures": n_failures,
    }


# ---- Coverage stats -------------------------------------------------------

def coverage_stats() -> dict:
    """Print coverage statistics for the API-FOOTBALL xG data."""
    if not RAW_OUT.exists():
        return {"total": 0, "with_xg": 0, "pct": 0.0}
    data = json.loads(RAW_OUT.read_text(encoding="utf-8"))
    matches = data.get("matches", []) if isinstance(data, dict) else data
    total = len(matches)
    with_xg = sum(1 for m in matches if m.get("xg_for") is not None)
    return {
        "total": total,
        "with_xg": with_xg,
        "pct": round(100.0 * with_xg / max(1, total), 1),
    }


# ---- CLI ------------------------------------------------------------------

def main() -> int:
    """Fetch xG from API-Football. Rate-limited; may need multiple days."""
    try:
        api_key = _get_api_key()
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print("\nUsage: API_FOOTBALL_KEY=xxx "
              "PYTHONPATH=src python -m wc_betting.data.fetch_xg_api")
        print("   or: add 'API_FOOTBALL_KEY=your_key' to .env")
        return 1

    print(f"[api-football] API key found (prefix: {api_key[:8]}...)")
    payload = fetch_all_xg_api()

    # Coverage stats
    cov = coverage_stats()
    print(f"\n[api-football] Coverage: {cov['with_xg']}/{cov['total']} "
          f"= {cov['pct']}% matches with xG")

    # Prompt to merge
    if cov["with_xg"] > 0:
        print(f"\n[api-football] To merge xG with historical data, run:")
        print(f'  PYTHONPATH=src python -c "from wc_betting.data.fetch_xg '
              f'import merge_xg_with_historical; merge_xg_with_historical()"')
        print(f"\nThen verify the model gate:")
        print(f"  PYTHONPATH=src python -m wc_betting.backtest.calibrate compare")
    return 0


if __name__ == "__main__":
    sys.exit(main())
