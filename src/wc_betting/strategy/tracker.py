"""Daily bet tracker: recommendations + settlement (plan §8 operational workflow).

Workflow:
  1. Morning before matches:  run("recommend")  → shows today's bets
  2. After matches end:       run("settle")     → refresh Wikipedia, check results, P/L
  3. Anytime:                 run("status")     → show cumulative stats

Tracker file: output/wc_bet_tracker.json (persistent across runs)

Settlement:
  - Refreshes Wikipedia group pages to get match results
  - Matches bet.match → (home, away, score) from Wikipedia
  - Win if bet.selection matches match result (H/D/A from score)
  - Profit = stake × (odds-1) if won, -stake if lost
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
FINAL_BETS_FILE = PROJECT_ROOT / "output/wc_final_bets.json"
CORR_FILE = PROJECT_ROOT / "output/wc_correlation_analysis.json"
TRACKER_FILE = PROJECT_ROOT / "output/wc_bet_tracker.json"
WIKI_DIR = Path("/tmp/wc_groups")

SELECTION_TO_RESULT = {"H": "H", "D": "D", "A": "A"}


# === Team name normalization ===

_SUFFIX_PATTERNS = [
    re.compile(r"\s+men'?s?\s*$", re.IGNORECASE),
    re.compile(r"\s+national\s+team\s*$", re.IGNORECASE),
    re.compile(r"\s+national\s+football\s+team\s*$", re.IGNORECASE),
]

_NAME_ALIASES = {
    "curaçao": "curacao",
    "czech republic": "czechia",
    "united states": "united states",
    "usa": "united states",
    "bosnia & herzegovina": "bosnia and herzegovina",
    "bosnia and herzegovina": "bosnia and herzegovina",
    "ivory coast": "ivory coast",
    "dr congo": "dr congo",
    "congo dr": "dr congo",
}


def _norm(name: str) -> str:
    """Canonical team name for matching bet records ↔ Wikipedia results."""
    if not name:
        return ""
    s = unescape(name).strip()
    s = s.replace(" & ", " and ")
    for pat in _SUFFIX_PATTERNS:
        s = pat.sub("", s)
    s = s.strip()
    return _NAME_ALIASES.get(s.lower(), s)


# === Wikipedia fetch ===

def _wiki_url(group: str) -> str:
    return f"https://en.wikipedia.org/wiki/2026_FIFA_World_Cup_Group_{group}"


def refresh_wikipedia(groups: list[str], wiki_dir: Path = WIKI_DIR) -> dict[str, int]:
    """Fetch fresh Wikipedia HTML for given groups. Returns {group: bytes_fetched}."""
    wiki_dir.mkdir(parents=True, exist_ok=True)
    results = {}
    for grp in groups:
        url = _wiki_url(grp)
        path = wiki_dir / f"grp_{grp}.html"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            path.write_text(html, encoding="utf-8")
            results[grp] = len(html)
        except Exception as e:
            results[grp] = -1
            print(f"  WARNING: failed to fetch Group {grp}: {e}")
    return results


# === Wikipedia HTML parsing (adapted from build_wc_unified.py) ===

def parse_group_results(html_path: Path, group: str) -> list[dict]:
    """Parse Wikipedia group page HTML → [{home, away, score, finished}]."""
    html = html_path.read_text(encoding="utf-8")
    home_iter = re.finditer(
        r'itemprop="homeTeam".*?title="([^"]+national [^"]+ team)"', html, re.DOTALL)
    away_iter = re.finditer(
        r'itemprop="awayTeam".*?title="([^"]+national [^"]+ team)"', html, re.DOTALL)
    score_iter = re.finditer(r'class="fscore"[^>]*>([^<]+)<', html)

    homes = list(home_iter)
    aways = list(away_iter)
    scores = list(score_iter)

    items = []
    for h in homes:
        items.append((h.start(), "home", h.group(1)))
    for a in aways:
        items.append((a.start(), "away", a.group(1)))
    for s in scores:
        items.append((s.start(), "score", s.group(1).strip()))
    items.sort()

    matches = []
    i = 0
    while i < len(items) - 2:
        if items[i][1] == "home" and items[i + 1][1] == "score" and items[i + 2][1] == "away":
            home_team = items[i][2].replace(" national football team", "").replace(" national soccer team", "")
            score = items[i + 1][2]
            away_team = items[i + 2][2].replace(" national football team", "").replace(" national soccer team", "")
            has_score = bool(score) and score not in ("–", "-", "") and not score.startswith("Match")
            matches.append({
                "home": _norm(home_team),
                "away": _norm(away_team),
                "score": score if has_score else None,
                "finished": has_score,
                "group": group,
            })
            i += 3
        else:
            i += 1
    return matches


def _score_to_result(score: str) -> str | None:
    """'5-1' / '5–1' → 'H'. None if unparseable."""
    if not score:
        return None
    parts = re.split(r"[-–—]", score.replace("−", "-"))
    if len(parts) != 2:
        return None
    try:
        gh, ga = int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None
    if gh > ga:
        return "H"
    elif gh == ga:
        return "D"
    else:
        return "A"


# === Tracker persistence ===

def load_tracker() -> dict:
    if TRACKER_FILE.exists():
        return json.loads(TRACKER_FILE.read_text(encoding="utf-8"))
    return {"created": datetime.now().isoformat(), "bets": [], "cumulative": _fresh_cumulative()}


def save_tracker(tracker: dict) -> None:
    tracker["last_updated"] = datetime.now().isoformat()
    tracker["cumulative"] = _compute_cumulative(tracker["bets"])
    TRACKER_FILE.parent.mkdir(parents=True, exist_ok=True)
    TRACKER_FILE.write_text(json.dumps(tracker, indent=2, ensure_ascii=False), encoding="utf-8")


def _fresh_cumulative() -> dict:
    return {
        "total_bets": 0, "settled": 0, "won": 0, "lost": 0, "pending": 0,
        "total_staked": 0.0, "total_profit": 0.0, "roi": 0.0, "hit_rate": 0.0,
        "bankroll": 1.0,
    }


def _compute_cumulative(bets: list[dict]) -> dict:
    settled = [b for b in bets if b["status"] in ("won", "lost")]
    won = [b for b in settled if b["status"] == "won"]
    lost = [b for b in settled if b["status"] == "lost"]
    pending = [b for b in bets if b["status"] == "pending"]
    total_staked = sum(b["optimal_stake"] for b in settled)
    total_profit = sum(b.get("profit", 0) for b in settled)
    return {
        "total_bets": len(bets),
        "settled": len(settled),
        "won": len(won),
        "lost": len(lost),
        "pending": len(pending),
        "total_staked": round(total_staked, 6),
        "total_profit": round(total_profit, 6),
        "roi": round(total_profit / total_staked, 4) if total_staked > 0 else 0.0,
        "hit_rate": round(len(won) / len(settled), 4) if settled else 0.0,
        "bankroll": round(1.0 + total_profit, 6),
    }


# === Core operations ===

def init_tracker() -> dict:
    """Initialize tracker from final_bets. All bets start as 'pending'."""
    data = json.loads(FINAL_BETS_FILE.read_text(encoding="utf-8"))
    bets = []
    for b in data["final_bets"]:
        bets.append({
            "date": b["date"],
            "group": b["group"],
            "match": b["match"],
            "home": b.get("home", ""),
            "away": b.get("away", ""),
            "selection": b["selection"],
            "p_model": b["p_model"],
            "odds": b["odds"],
            "ev": b["ev"],
            "optimal_stake": b["optimal_stake"],
            "kelly_stake": b.get("kelly_stake", b.get("kelly_fraction", 0)),
            "bet_variance": b.get("bet_variance", 0),
            "status": "pending",
            "score": None,
            "result": None,
            "profit": 0.0,
            "settled_at": None,
        })
    tracker = {"created": datetime.now().isoformat(), "bets": bets, "cumulative": _fresh_cumulative()}
    save_tracker(tracker)
    return tracker


def settle_bets(verbose: bool = True) -> dict:
    """Refresh Wikipedia + settle all pending bets that have results."""
    tracker = load_tracker()
    if not tracker["bets"]:
        tracker = init_tracker()

    pending = [b for b in tracker["bets"] if b["status"] == "pending"]
    if not pending:
        if verbose:
            print("No pending bets to settle.")
        return tracker

    # Collect groups that need refreshing.
    groups_to_refresh = sorted({b["group"] for b in pending})
    if verbose:
        print(f"Refreshing Wikipedia for groups: {', '.join(groups_to_refresh)}")

    fetch_results = refresh_wikipedia(groups_to_refresh)

    # Parse all results from refreshed HTML.
    all_results: dict[str, dict] = {}  # key: f"{norm_home}_{norm_away}"
    for grp in groups_to_refresh:
        html_path = WIKI_DIR / f"grp_{grp}.html"
        if not html_path.exists():
            continue
        for m in parse_group_results(html_path, grp):
            if m["finished"] and m["score"]:
                key = f"{m['home']}_{m['away']}"
                all_results[key] = m

    if verbose:
        print(f"Found {len(all_results)} finished matches from Wikipedia")

    # Fallback: always supplement with unified.json.  Wikipedia is the primary
    # source but may be stale or unreachable; unified.json is the ground truth
    # maintained by the user for this project.
        try:
            unified_path = PROJECT_ROOT / "data" / "processed" / "wc_2026_unified.json"
            if unified_path.exists():
                unified_data = json.loads(unified_path.read_text(encoding="utf-8"))
                unified_count = 0
                for m in unified_data:
                    if m.get("finished") and m.get("score"):
                        key = f"{_norm(m['home_en'])}_{_norm(m['away_en'])}"
                        if key not in all_results:
                            all_results[key] = {
                                "score": m["score"],
                                "home": m["home_en"],
                                "away": m["away_en"],
                            }
                            unified_count += 1
                if verbose and unified_count:
                    print(f"  + {unified_count} results from unified.json (fallback)")
        except Exception:
            pass

    # Settle each pending bet.
    settled_count = 0
    for bet in pending:
        key = f"{_norm(bet['home'])}_{_norm(bet['away'])}"
        result = all_results.get(key)

        # Also try reverse (home/away might be swapped in Wikipedia).
        if not result:
            key_rev = f"{_norm(bet['away'])}_{_norm(bet['home'])}"
            result_rev = all_results.get(key_rev)
            if result_rev:
                # Wikipedia has teams in reverse order; flip the score.
                score_parts = re.split(r"[-–—]", result_rev["score"].replace("−", "-"))
                if len(score_parts) == 2:
                    flipped_score = f"{score_parts[1].strip()}-{score_parts[0].strip()}"
                    result = {"score": flipped_score, "home": bet["home"], "away": bet["away"]}

        if result and result.get("score"):
            match_result = _score_to_result(result["score"])
            if match_result is None:
                continue

            bet["score"] = result["score"]
            bet["result"] = match_result
            bet["settled_at"] = datetime.now().isoformat()

            if match_result == bet["selection"]:
                bet["status"] = "won"
                bet["profit"] = round(bet["optimal_stake"] * (bet["odds"] - 1.0), 6)
            else:
                bet["status"] = "lost"
                bet["profit"] = round(-bet["optimal_stake"], 6)

            settled_count += 1
            if verbose:
                icon = "✅" if bet["status"] == "won" else "❌"
                print(f"  {icon} {bet['match']} [{bet['selection']}] "
                      f"score={bet['score']} result={match_result} "
                      f"stake={bet['optimal_stake']:.1%} P/L={bet['profit']:+.4f}")
        # else: still pending (Wikipedia not updated yet)

    save_tracker(tracker)

    if verbose:
        cum = tracker["cumulative"]
        print(f"\n=== Settlement Summary ===")
        print(f"settled this round: {settled_count}")
        print(f"total settled: {cum['settled']} ({cum['won']}W {cum['lost']}L)")
        print(f"pending: {cum['pending']}")
        print(f"total staked: {cum['total_staked']:.4f}")
        print(f"total P/L:    {cum['total_profit']:+.4f}")
        print(f"ROI:          {cum['roi']:+.1%}")
        print(f"hit rate:     {cum['hit_rate']:.1%}")
        print(f"bankroll:     {cum['bankroll']:.4f}")

    return tracker


def recommend(date: str | None = None, verbose: bool = True) -> list[dict]:
    """Show recommended bets for a given date (default: today Beijing time)."""
    tracker = load_tracker()
    if not tracker["bets"]:
        tracker = init_tracker()
        tracker = load_tracker()

    if date is None:
        now_bj = datetime.now(timezone.utc) + timedelta(hours=8)
        date = now_bj.strftime("%Y-%m-%d")

    today_bets = [b for b in tracker["bets"] if b["date"] == date]

    if verbose:
        print(f"=== Recommendations for {date} ===")
        if not today_bets:
            print("  No bets scheduled for this date.")
            return []

        for b in today_bets:
            status_icon = {"pending": "⏳", "won": "✅", "lost": "❌"}.get(b["status"], "?")
            print(f"  {status_icon} Group {b['group']} {b['match']}")
            print(f"     bet: [{b['selection']}] @ {b['odds']:.2f}  "
                  f"p_model={b['p_model']:.1%}  EV={b['ev']:+.1%}")
            print(f"     stake: {b['optimal_stake']:.1%} (kelly={b['kelly_stake']:.1%})")
            if b["status"] in ("won", "lost"):
                print(f"     result: {b['score']} → {b['result']}  P/L={b['profit']:+.4f}")
            print()

        total_stake = sum(b["optimal_stake"] for b in today_bets)
        total_ev = sum(b["ev"] * b["optimal_stake"] for b in today_bets)
        print(f"  total stake: {total_stake:.1%}  expected EV: {total_ev:+.4f}")

    return today_bets


def status(verbose: bool = True) -> dict:
    """Show current tracker status."""
    tracker = load_tracker()
    if not tracker["bets"]:
        if verbose:
            print("Tracker not initialized. Run init_tracker() first.")
        return tracker

    cum = tracker["cumulative"]
    if verbose:
        print(f"=== Bet Tracker Status (last updated: {tracker.get('last_updated', '?')}) ===")
        print(f"total bets:    {cum['total_bets']}")
        print(f"settled:       {cum['settled']} ({cum['won']}W {cum['lost']}L)")
        print(f"pending:       {cum['pending']}")
        print(f"total staked:  {cum['total_staked']:.4f}")
        print(f"total P/L:     {cum['total_profit']:+.4f}")
        print(f"ROI:           {cum['roi']:+.1%}")
        print(f"hit rate:      {cum['hit_rate']:.1%}")
        print(f"bankroll:      {cum['bankroll']:.4f}")
        print()

        # Show all bets grouped by date.
        by_date: dict[str, list[dict]] = {}
        for b in tracker["bets"]:
            by_date.setdefault(b["date"], []).append(b)

        for date in sorted(by_date):
            bets = by_date[date]
            settled = [b for b in bets if b["status"] in ("won", "lost")]
            day_pl = sum(b.get("profit", 0) for b in settled)
            print(f"--- {date} ({len(bets)} bets, P/L={day_pl:+.4f}) ---")
            for b in bets:
                icon = {"pending": "⏳", "won": "✅", "lost": "❌"}.get(b["status"], "?")
                extra = f" → {b['score']} {b['result']} P/L={b['profit']:+.4f}" if settled else ""
                print(f"  {icon} [{b['selection']}] {b['match']} "
                      f"@{b['odds']:.2f} stake={b['optimal_stake']:.1%}{extra}")

    return tracker


def run(mode: str = "status", date: str | None = None, verbose: bool = True) -> dict | list:
    """Main entry point.

    mode: "recommend" — show bets for a date (default: today)
          "settle" — refresh Wikipedia + settle bets
          "status" — show full tracker status
          "init" — initialize tracker from final_bets
    """
    if mode == "init":
        return init_tracker()
    elif mode == "recommend":
        return recommend(date, verbose)
    elif mode == "settle":
        return settle_bets(verbose)
    else:
        return status(verbose)


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    date = sys.argv[2] if len(sys.argv) > 2 else None
    run(mode, date)
