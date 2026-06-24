"""Purchase tracker for China Sporttery (体彩) single-game bets (单关).

Records real purchases of sporttery lottery recommendations, auto-settles from
finished match scores in `wc_2026_unified.json`, and exposes a cumulative
backtest comparison of predicted EV vs realized ROI.

Workflow:
  1. User buys a single-game bet recommended by sporttery_scanner.
  2. `add_purchase(op, stake_cny)` records the purchase (status=pending).
  3. After the match finishes, `settle_purchases(finished_matches)` checks the
     score and marks the purchase won/lost/manual.
  4. `_compute_cumulative` aggregates predicted_ev (weighted) vs realized_ev.

Purchase file: output/wc_sporttery_purchases.json (mirrors wc_bet_tracker.json).

Settlement by pool:
  had  — H/D/A from raw score comparison.
  hhad — virtual_home = home_g + handicap (HANDICAP_SIGN=1, scanner §55),
         then H/D/A vs away_g.
  crs  — exact (h,a) match; H_OTHER/D_OTHER/A_OTHER → None (manual, cannot
         auto-decide which unlisted score bucket the actual result falls into
         without re-deriving the offered score list).
  ttg  — total = home_g + away_g; "7" → total>=7, else total == int(selection).

Research/tracking only for legal state lottery purchases.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PURCHASES_FILE = PROJECT_ROOT / "output/wc_sporttery_purchases.json"
UNIFIED_FILE = PROJECT_ROOT / "data/processed/wc_2026_unified.json"

POOL_NAMES_CN = {
    "had":  "胜平负",
    "hhad": "让球胜平负",
    "crs":  "比分",
    "ttg":  "总进球数",
}

# hhad sign convention (matches sporttery_scanner.HANDICAP_SIGN = 1.0):
# virtual_home = home_g + handicap  (handicap is the sporttery goalLine,
# e.g. -1 means home gives 1 goal → home must win by 2+ to cover).
HANDICAP_SIGN = 1.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# === Persistence (mirrors tracker.load_tracker / save_tracker) ===

def settle_from_unified() -> dict:
    """Settle all pending purchases using unified.json (no network needed)."""
    import json as _json
    from pathlib import Path as _Path
    unified_path = _Path(__file__).resolve().parent.parent.parent.parent / "data" / "processed" / "wc_2026_unified.json"
    if not unified_path.exists():
        return {"error": "unified.json not found"}
    unified = _json.loads(unified_path.read_text(encoding="utf-8"))
    finished = [m for m in unified if m.get("finished") and m.get("score")]
    return settle_purchases(finished)



def load_purchases() -> dict:
    if PURCHASES_FILE.exists():
        return json.loads(PURCHASES_FILE.read_text(encoding="utf-8"))
    return {
        "created": _now_iso(),
        "last_updated": _now_iso(),
        "purchases": [],
        "cumulative": _fresh_cumulative(),
    }


def save_purchases(data: dict) -> None:
    data["last_updated"] = _now_iso()
    data["cumulative"] = _compute_cumulative(data.get("purchases", []))
    PURCHASES_FILE.parent.mkdir(parents=True, exist_ok=True)
    PURCHASES_FILE.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _fresh_cumulative() -> dict:
    return {
        "total_bets": 0, "settled": 0, "won": 0, "lost": 0, "pending": 0,
        "total_staked": 0.0, "total_profit": 0.0, "roi": 0.0, "hit_rate": 0.0,
        "predicted_ev": 0.0, "realized_ev": 0.0,
    }


# === Add purchase ===

def add_purchase(op: dict, stake_cny: float,
                 purchase_date: str | None = None) -> dict:
    """Record a single-game purchase from a scanner opportunity.

    `op` is an opportunity dict from sporttery_scanner (fields: match,
    match_cn, date, group, pool_code, selection, selection_cn, handicap,
    odds, p_model, ev).
    """
    data = load_purchases()
    purchases = data.get("purchases", [])

    home_en, away_en = "", ""
    match_str = op.get("match", "")
    if " vs " in match_str:
        parts = match_str.split(" vs ", 1)
        home_en, away_en = parts[0].strip(), parts[1].strip()

    if purchase_date is None:
        purchase_date = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")

    # Auto-increment id = max existing + 1 (survives deletions without collision).
    max_num = 0
    for p in purchases:
        try:
            max_num = max(max_num, int(p["id"][1:]))
        except (ValueError, KeyError, IndexError):
            pass
    pool = op.get("pool_code", "")
    purchase = {
        "id": f"p{max_num + 1:03d}",
        "purchase_date": purchase_date,
        "home_en": home_en,
        "away_en": away_en,
        "match_cn": op.get("match_cn", ""),
        "date": op.get("date", ""),
        "group": op.get("group", ""),
        "pool_code": pool,
        "pool_name": POOL_NAMES_CN.get(pool, pool),
        "selection": op.get("selection", ""),
        "selection_cn": op.get("selection_cn", ""),
        "handicap": op.get("handicap"),
        "odds": op.get("odds", 0.0),
        "p_model": op.get("p_model", 0.0),
        "ev": op.get("ev", 0.0),
        "stake_cny": float(stake_cny),
        "status": "pending",
        "score": None,
        "won": None,
        "payout_cny": 0.0,
        "profit_cny": 0.0,
        "settled_at": None,
    }
    purchases.append(purchase)
    data["purchases"] = purchases
    save_purchases(data)
    return purchase


def delete_purchase(purchase_id: str) -> bool:
    """Remove a purchase by id. Returns True if found & removed."""
    data = load_purchases()
    before = len(data.get("purchases", []))
    data["purchases"] = [p for p in data.get("purchases", [])
                         if p.get("id") != purchase_id]
    removed = len(data["purchases"]) < before
    if removed:
        save_purchases(data)
    return removed


def update_purchase_stake(purchase_id: str, new_stake: float) -> dict | None:
    """Change a purchase's stake_cny. Recalculates payout/profit if already
    settled. Returns the updated purchase, or None if id not found."""
    data = load_purchases()
    for p in data.get("purchases", []):
        if p.get("id") != purchase_id:
            continue
        p["stake_cny"] = float(new_stake)
        if p["status"] == "won":
            p["payout_cny"] = round(p["stake_cny"] * float(p["odds"]), 2)
            p["profit_cny"] = round(p["payout_cny"] - p["stake_cny"], 2)
        elif p["status"] == "lost":
            p["payout_cny"] = 0.0
            p["profit_cny"] = round(-p["stake_cny"], 2)
        save_purchases(data)
        return p
    return None


# === Settlement ===

def _parse_score(score: str) -> tuple[int, int] | None:
    """Parse '2–0' / '2-0' / '2−0' (en-dash / hyphen / minus) → (2, 0)."""
    if not score:
        return None
    parts = re.split(r"[-–—−]", score.strip())
    if len(parts) != 2:
        return None
    try:
        return int(parts[0].strip()), int(parts[1].strip())
    except ValueError:
        return None


def settle_selection(pool: str, selection: str,
                     handicap: float | None,
                     home_g: int, away_g: int) -> bool | None:
    """Decide whether a selection won given the final score.

    Returns True (won), False (lost), or None (manual — cannot auto-decide,
    e.g. crs OTHER buckets where we don't know the offered score list).
    """
    if pool == "had":
        if home_g > away_g:
            actual = "H"
        elif home_g == away_g:
            actual = "D"
        else:
            actual = "A"
        return selection == actual

    if pool == "hhad":
        g = HANDICAP_SIGN * (float(handicap) if handicap is not None else 0.0)
        vh = home_g + g
        if vh > away_g:
            actual = "H"
        elif vh == away_g:
            actual = "D"
        else:
            actual = "A"
        return selection == actual

    if pool == "crs":
        if selection in ("H_OTHER", "D_OTHER", "A_OTHER"):
            return None  # cannot auto-decide without the offered score list
        k = selection.strip("()").split(",")
        if len(k) != 2:
            return None
        try:
            h, a = int(k[0]), int(k[1])
        except ValueError:
            return None
        return home_g == h and away_g == a

    if pool == "ttg":
        total = home_g + away_g
        try:
            k = int(selection)
        except ValueError:
            return None
        if k == 7:
            return total >= 7
        return total == k

    return None


def settle_purchases(finished_matches: list[dict]) -> dict:
    """Settle all pending purchases against finished match scores.

    `finished_matches` items need: home_en, away_en, score (str like "2–0").
    Writes results back to PURCHASES_FILE. Returns the updated data dict.
    """
    data = load_purchases()
    purchases = data.get("purchases", [])

    # Build (home_en, away_en) -> score lookup. Also try reverse key in case
    # the purchase recorded teams in the opposite order from unified.json.
    by_key: dict[tuple[str, str], str] = {}
    for m in finished_matches:
        h = (m.get("home_en") or "").strip()
        a = (m.get("away_en") or "").strip()
        s = m.get("score")
        if h and a and s:
            by_key[(h, a)] = s

    for p in purchases:
        if p.get("settled"): continue
        h_en = (p.get("home_en") or "").strip()
        a_en = (p.get("away_en") or "").strip()
        score = by_key.get((h_en, a_en))
        if score is None:
            # try reverse
            score = by_key.get((a_en, h_en))
            if score is not None:
                # unified.json had teams swapped vs purchase → flip score
                parsed = _parse_score(score)
                if parsed:
                    score = f"{parsed[1]}-{parsed[0]}"
        if score is None:
            continue  # match not finished yet

        parsed = _parse_score(score)
        if parsed is None:
            continue
        home_g, away_g = parsed

        result = settle_selection(
            p["pool_code"], p["selection"], p.get("handicap"),
            home_g, away_g)

        p["score"] = score
        p["settled_at"] = _now_iso()
        if result is None:
            # crs OTHER bucket — needs user manual confirmation
            p["status"] = "manual"
            p["won"] = None
            continue
        if result:
            p["status"] = "won"
            p["won"] = True
            p["payout_cny"] = round(p["stake_cny"] * float(p["odds"]), 2)
            p["profit_cny"] = round(p["payout_cny"] - p["stake_cny"], 2)
        else:
            p["status"] = "lost"
            p["won"] = False
            p["payout_cny"] = 0.0
            p["profit_cny"] = round(-p["stake_cny"], 2)

    data["purchases"] = purchases
    save_purchases(data)
    return data


def set_manual_result(purchase_id: str, won: bool) -> dict:
    """User manually confirms a `manual`-status purchase as won/lost."""
    data = load_purchases()
    for p in data.get("purchases", []):
        if p["id"] == purchase_id:
            p["status"] = "won" if won else "lost"
            p["won"] = won
            p["settled_at"] = _now_iso()
            if won:
                p["payout_cny"] = round(p["stake_cny"] * float(p["odds"]), 2)
                p["profit_cny"] = round(p["payout_cny"] - p["stake_cny"], 2)
            else:
                p["payout_cny"] = 0.0
                p["profit_cny"] = round(-p["stake_cny"], 2)
            break
    save_purchases(data)
    return data


# === Cumulative stats ===

def _compute_cumulative(purchases: list[dict]) -> dict:
    settled = [p for p in purchases if p["status"] in ("won", "lost")]
    won = [p for p in settled if p["status"] == "won"]
    lost = [p for p in settled if p["status"] == "lost"]
    pending = [p for p in purchases
               if not p.get("settled")]

    total_staked_settled = sum(p["stake_cny"] for p in settled)
    total_profit = sum(p.get("profit_cny", 0) for p in settled)

    # Calibration metrics (predicted_ev vs realized_ev) only over settled
    # purchases that have model data (p_model > 0). Manual entries have
    # p_model=0/ev=0 and would skew the calibration toward zero.
    modeled = [p for p in settled if p.get("p_model", 0) > 0]
    modeled_staked = sum(p["stake_cny"] for p in modeled)
    if modeled_staked > 0:
        predicted_ev = sum(
            p.get("ev", 0) * p["stake_cny"] for p in modeled
        ) / modeled_staked
        realized_ev = sum(
            p.get("profit_cny", 0) for p in modeled) / modeled_staked
    else:
        predicted_ev = 0.0
        realized_ev = 0.0

    return {
        "total_bets": len(purchases),
        "settled": len(settled),
        "won": len(won),
        "lost": len(lost),
        "pending": len(pending),
        "total_staked": round(total_staked_settled, 2),
        "total_profit": round(total_profit, 2),
        "roi": round(total_profit / total_staked_settled, 4) if total_staked_settled > 0 else 0.0,
        "hit_rate": round(len(won) / len(settled), 4) if settled else 0.0,
        "predicted_ev": round(predicted_ev, 4),
        "realized_ev": round(realized_ev, 4),
    }


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "status"
    if mode == "status":
        d = load_purchases()
        print(json.dumps(d["cumulative"], indent=2, ensure_ascii=False))
        print(f"({len(d.get('purchases', []))} purchases on file)")
    elif mode == "settle":
        if not UNIFIED_FILE.exists():
            print(f"unified file not found: {UNIFIED_FILE}")
            sys.exit(1)
        unified = json.loads(UNIFIED_FILE.read_text(encoding="utf-8"))
        finished = [m for m in unified if m.get("finished")]
        d = settle_purchases(finished)
        print(json.dumps(d["cumulative"], indent=2, ensure_ascii=False))
