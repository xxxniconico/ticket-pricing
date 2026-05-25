#!/usr/bin/env python3
"""
Backtest: Rule Engine V3 vs actual ticket counts
Compares predict() against match_features.parquet for all completed 国安 home matches (2025+2026 CSL).
"""
from __future__ import annotations

import json
import sys
import os
from pathlib import Path
from datetime import datetime
from itertools import product
from copy import deepcopy

import numpy as np
import pandas as pd

# Ensure ticket-pricing src is on path
sys.path.insert(0, str(Path(__file__).parent))
from src.rule_engine import predict, MULTIPLIERS, OPP_DEVIATION, TIER_BASE, PENALTY_FLOOR
from src.classify import classify_opponent_tier, DERBY_RIVALS


# ── 1. Load data ──────────────────────────────────────────
CSL_JSON = Path("/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2/data/csl_final_production_ready.json")
MATCH_FEATURES = Path("data/processed/match_features.parquet")
ALL_UNIFIED = Path("data/processed/all_unified.parquet")

with open(CSL_JSON) as f:
    csl_data = json.load(f)

mf = pd.read_parquet(MATCH_FEATURES)
au = pd.read_parquet(ALL_UNIFIED)

print(f"match_features: {mf.shape}, columns={list(mf.columns)}")
print(f"all_unified: {au.shape}")

# ── 2. Build 国安 match list from CSL JSON ─────────────────
# The JSON has 'matches' under leagues[0]. Extract all completed 国安 matches.
all_matches_raw = []
for lg in csl_data.get("leagues", []):
    for m in lg.get("matches", []):
        h = m.get("home_club", "")
        a = m.get("away_club", "")
        if "国安" not in h and "国安" not in a:
            continue
        score = m.get("score", {})
        hg = score.get("home")
        ag = score.get("away")
        status = m.get("status", "scheduled")
        all_matches_raw.append({
            "match_id": m.get("match_id", ""),
            "date": m.get("date", "")[:10],
            "home_club": h,
            "away_club": a,
            "is_home": "国安" in h,
            "hg": hg,
            "ag": ag,
            "status": status,
            "round": m.get("round", "?"),
            "venue": m.get("venue", ""),
        })

df_raw = pd.DataFrame(all_matches_raw)
df_raw["date"] = pd.to_datetime(df_raw["date"])
df_raw = df_raw.sort_values("date").reset_index(drop=True)

# Only completed home matches
completed_home = df_raw[(df_raw["is_home"]) & (df_raw["status"] == "finished")].copy()
completed_home["season"] = completed_home["date"].dt.year

print(f"\nTotal 国安 matches in CSL JSON: {len(df_raw)}")
print(f"Completed home matches: {len(completed_home)}")
print(f"  By season: {completed_home['season'].value_counts().to_dict()}")

# ── 3. Build standings by round ────────────────────────────
# For detect_ctx we need standings at each round
# The JSON has a 'standings' array but we need per-round standings
# We'll build it from the completed matches up to each target match
def get_standings_before(all_matches_df, target_date):
    """Simple points-based standings from completed matches before target_date.
    all_matches_df: pd.DataFrame of all matches (must have home_club, away_club, hg, ag, date, status).
    """
    teams = {}
    for _, m in all_matches_df.iterrows():
        if m["status"] != "finished":
            continue
        if pd.Timestamp(m["date"]) >= pd.Timestamp(target_date):
            continue
        h = m["home_club"]; a = m["away_club"]
        hg = m["hg"]; ag = m["ag"]
        if hg is None or ag is None:
            continue
        if pd.isna(hg) or pd.isna(ag):
            continue
        for club in [h, a]:
            if club not in teams:
                teams[club] = {"pts": 0, "gf": 0, "ga": 0, "mp": 0}
        teams[h]["gf"] += int(hg); teams[h]["ga"] += int(ag); teams[h]["mp"] += 1
        teams[a]["gf"] += int(ag); teams[a]["ga"] += int(hg); teams[a]["mp"] += 1
        if hg > ag:
            teams[h]["pts"] += 3
        elif hg == ag:
            teams[h]["pts"] += 1; teams[a]["pts"] += 1
        else:
            teams[a]["pts"] += 3
    table = []
    for club, stats in teams.items():
        table.append({"team": club, "pts": stats["pts"], "gd": stats["gf"] - stats["ga"]})
    table.sort(key=lambda x: (-x["pts"], -x["gd"]))
    return {t["team"]: i+1 for i, t in enumerate(table)}


# ── 4. Detect context (replicating dashboard/app.py detect_ctx + extras) ──
def detect_ctx_match(match, all_matches_df, target_date, season):
    """
    Replicate the dashboard's detect_ctx logic.
    Returns dict with all context flags needed by predict().
    
    all_matches_df: DataFrame of ALL CSL matches (not just 国安), sorted by date.
    """
    ctx = {}
    md = pd.Timestamp(target_date)
    
    # Get all completed matches before target date
    prev_all = all_matches_df[
        (all_matches_df["status"] == "finished") & 
        (all_matches_df["date"] < md)
    ].copy()
    
    # Filter to 国安 matches for context detection
    guoan_all = df_raw[df_raw["date"] < md].copy()
    
    # Build prev list for the dashboard-style detect_ctx
    # The dashboard's detect_ctx uses guoan_matches list with specific keys
    guoan_before = []
    for _, r in guoan_all.iterrows():
        guoan_before.append({
            "date": r["date"],
            "is_home": r["is_home"],
            "opponent": r["away_club"] if r["is_home"] else r["home_club"],
            "hg": r["hg"],
            "ag": r["ag"],
            "completed": r["status"] == "finished",
            "round": r["round"],
        })
    
    # Dashboard detect_ctx logic
    prev = [m for m in guoan_before if m["completed"] and pd.Timestamp(m["date"]) < md]
    last3 = prev[-3:] if len(prev) >= 3 else prev
    
    # away_winless
    away3 = [m for m in last3 if not m["is_home"]]
    if len(away3) >= 2:
        away_wins = sum(1 for m in away3 if (
            (m["is_home"] and m["hg"] > m["ag"]) or 
            (not m["is_home"] and m["ag"] > m["hg"])
        ))
        if away_wins == 0:
            ctx["away_winless"] = True
    
    # lost_bottom & heavy_home_loss
    for m in last3:
        is_loss = (m["is_home"] and m["hg"] < m["ag"]) or (not m["is_home"] and m["ag"] < m["hg"])
        if not is_loss:
            continue
        
        opp = m["opponent"]
        standings = get_standings_before(df_raw, target_date)
        opp_rank = standings.get(opp, 8)
        
        if opp_rank >= 12:
            opp_tier = classify_opponent_tier(opp)
            if opp_tier in ("C1", "C2"):
                ctx["lost_bottom"] = True
        
        if m["is_home"] and abs(m["hg"] - m["ag"]) >= 2:
            # Check if there's a subsequent win to "wash" it
            idx = -1
            for i, pm in enumerate(prev):
                if pm["date"] == m["date"] and pm["opponent"] == m["opponent"]:
                    idx = i; break
            later = prev[idx+1:] if idx >= 0 else []
            has_win = any(
                (lm["is_home"] and lm["hg"] > lm["ag"]) or 
                (not lm["is_home"] and lm["ag"] > lm["hg"])
                for lm in later
            )
            if not has_win:
                ctx["heavy_home_loss"] = True
    
    # short_rest: <=5 days since last home match
    hp = [m for m in prev if m["is_home"]]
    if hp:
        days_since = (md - pd.Timestamp(hp[-1]["date"])).days
        if days_since <= 5:
            ctx["short_rest"] = True
    
    # Additional context from dashboard render_home_card:
    # derby
    opp_name = match.get("away_club", "")
    if opp_name in DERBY_RIVALS:
        ctx["derby"] = True
    else:
        # Also check bidirectional
        for dr in DERBY_RIVALS:
            if dr in opp_name or opp_name in dr:
                ctx["derby"] = True
                break
    
    # saturday, late_season, midweek, season_opener
    ctx["saturday"] = md.weekday() == 5
    ctx["late_season"] = md.month >= 10
    ctx["midweek"] = md.weekday() in (1, 2, 3)
    
    # season_opener: first home match of season
    if season == 2025:
        home_before = [m for m in prev if m["is_home"]]
        ctx["season_opener"] = len(home_before) == 0
    else:
        # For 2026, check if first home of the season
        home_before_26 = [m for m in prev if m["is_home"] and pd.Timestamp(m["date"]).year == 2026]
        ctx["season_opener"] = len(home_before_26) == 0
    
    return ctx


# ── 5. Normalize opponent names for matching ───────────────
def normalize_opp(name):
    """Strip full club names down to short form for lookup."""
    short_map = {
        "北京国安": "北京国安",
        "上海海港": "上海海港",
        "上海申花": "上海申花",
        "山东泰山": "山东泰山",
        "成都蓉城": "成都蓉城",
        "天津津门虎": "天津津门虎",
        "浙江": "浙江",
        "河南队俱乐部彩陶坊": "河南队",
        "河南": "河南队",
        "武汉三镇": "武汉三镇",
        "长春亚泰": "长春亚泰",
        "青岛海牛": "青岛海牛",
        "青岛西海岸": "青岛西海岸",
        "沧州雄狮": "沧州雄狮",
        "深圳新鹏城": "深圳新鹏城",
        "梅州客家": "梅州客家",
        "云南玉昆": "云南玉昆",
        "大连英博": "大连英博",
        "南通支云": "南通支云",
        "辽宁铁人": "辽宁铁人",
        "重庆铜梁龙": "重庆铜梁龙",
    }
    if name in short_map:
        return short_map[name]
    # Try partial match
    for long, short in short_map.items():
        if long in name or name in long:
            return short
    return name

# Also need to handle opponent matching for OPP_DEVIATION
def match_opp_deviation(opp_name):
    """Find OPP_DEVIATION key matching the opponent."""
    short = normalize_opp(opp_name)
    if short in OPP_DEVIATION:
        return OPP_DEVIATION[short]
    # Try substring match
    for key in OPP_DEVIATION:
        if key in short or short in key:
            return OPP_DEVIATION[key]
    return 1.0


# ── 6. Run backtest ─────────────────────────────────────────
print("\n" + "="*80)
print("BACKTEST: Rule Engine V3")
print("="*80)

results = []
for _, match in completed_home.iterrows():
    opp_raw = match["away_club"]
    opp_short = normalize_opp(opp_raw)
    md = match["date"]
    season = match["season"]
    
    # Detect context
    ctx = detect_ctx_match(match, df_raw, md, season)
    
    # Build predict() kwargs
    pred_kwargs = {
        "derby": ctx.get("derby", False),
        "lost_bottom": ctx.get("lost_bottom", False),
        "heavy_home_loss": ctx.get("heavy_home_loss", False),
        "away_winless": ctx.get("away_winless", False),
        "saturday": ctx.get("saturday", False),
        "late_season": ctx.get("late_season", False),
        "season_opener": ctx.get("season_opener", False),
        "short_rest": ctx.get("short_rest", False),
        "midweek": ctx.get("midweek", False),
    }
    
    pred = predict(opp_short, **pred_kwargs)
    tier = classify_opponent_tier(opp_short)
    
    # Get actual from match_features
    mid = match["match_id"]
    mf_row = mf[mf["match_id"] == mid]
    if len(mf_row) > 0:
        actual = int(mf_row["attendance"].iloc[0])
    else:
        # Fallback: try all_unified
        au_row = au[au["match_id"] == mid]
        if len(au_row) > 0:
            actual = int(au_row["数量"].sum())
        else:
            actual = None
            print(f"  WARNING: No actual found for {mid}")
    
    # Get OPP_DEVIATION used
    dev = match_opp_deviation(opp_short)
    
    results.append({
        "season": season,
        "match_id": mid,
        "date": str(md)[:10],
        "opponent_raw": opp_raw,
        "opponent": opp_short,
        "tier": tier,
        "predicted": round(pred, 0),
        "actual": actual,
        "error": round(pred - actual, 0) if actual else None,
        "abs_error": round(abs(pred - actual), 0) if actual else None,
        "ape_pct": round(abs(pred - actual) / actual * 100, 1) if actual and actual > 0 else None,
        "dev_factor": dev,
        **pred_kwargs,
    })

df_results = pd.DataFrame(results)

# ── 7. Print results ────────────────────────────────────────
print("\n📊 Per-Match Predictions vs Actuals:\n")
print(f"{'Season':<6} {'Date':<12} {'Opponent':<14} {'Tier':<4} {'Pred':>8} {'Actual':>8} {'Error':>8} {'APE%':>7} | Context")
print("-" * 130)

for _, r in df_results.iterrows():
    ctx_parts = []
    for flag in ["derby", "lost_bottom", "heavy_home_loss", "away_winless", 
                 "saturday", "late_season", "season_opener", "short_rest", "midweek"]:
        if r.get(flag):
            ctx_parts.append(flag[:4])
    ctx_str = ",".join(ctx_parts) if ctx_parts else "none"
    
    print(f"{r['season']:<6} {r['date']:<12} {r['opponent']:<14} {r['tier']:<4} "
          f"{r['predicted']:>8.0f} {r['actual']:>8.0f} {r['error']:>8.0f} "
          f"{r['ape_pct']:>6.1f}% | {ctx_str}")

# ── 8. Summary stats ────────────────────────────────────────
print("\n" + "="*80)
print("SUMMARY STATISTICS")
print("="*80)

valid = df_results[df_results["actual"].notna() & (df_results["actual"] > 0)]

for season in sorted(valid["season"].unique()):
    s = valid[valid["season"] == season]
    mae = s["abs_error"].mean()
    mape = s["ape_pct"].mean()
    rmse = np.sqrt((s["error"] ** 2).mean())
    n = len(s)
    print(f"\n{season} ({n} matches):")
    print(f"  MAE:  {mae:.0f} tickets")
    print(f"  MAPE: {mape:.1f}%")
    print(f"  RMSE: {rmse:.0f} tickets")

# Overall
mae_all = valid["abs_error"].mean()
mape_all = valid["ape_pct"].mean()
rmse_all = np.sqrt((valid["error"] ** 2).mean())
print(f"\nOverall ({len(valid)} matches):")
print(f"  MAE:  {mae_all:.0f} tickets")
print(f"  MAPE: {mape_all:.1f}%")
print(f"  RMSE: {rmse_all:.0f} tickets")

# ── 9. Top 5 worst predictions ──────────────────────────────
print("\n" + "="*80)
print("TOP 5 WORST PREDICTIONS (by APE)")
print("="*80)

worst = valid.nlargest(5, "ape_pct")
for _, r in worst.iterrows():
    print(f"\n  {r['season']} {r['date']} vs {r['opponent']} (Tier {r['tier']})")
    print(f"    Predicted: {r['predicted']:.0f} | Actual: {r['actual']:.0f} | Error: {r['error']:.0f} ({r['ape_pct']:.1f}%)")
    ctx_active = [k for k in ["derby","lost_bottom","heavy_home_loss","away_winless",
                              "saturday","late_season","season_opener","short_rest","midweek"] 
                  if r.get(k)]
    print(f"    Active context: {ctx_active if ctx_active else 'none'}")
    print(f"    Deviation factor: {r['dev_factor']:.2f}")
    tier = r['tier']
    base = TIER_BASE.get(tier, 9000)
    print(f"    TIER_BASE[{tier}]: {base:.0f}, with dev: {base * r['dev_factor']:.0f}")

# ── 10. ABLATION: Remove OPP_DEVIATION ─────────────────────
print("\n" + "="*80)
print("ABLATION: Remove OPP_DEVIATION (all dev=1.0)")
print("="*80)

# Monkey-patch for ablation
original_dev = deepcopy(OPP_DEVIATION)

def predict_no_dev(opponent, **kwargs):
    """Predict without OPP_DEVIATION."""
    tier = classify_opponent_tier(opponent)
    base = TIER_BASE.get(tier, 9000)
    # SKIP deviation
    mult = 1.0
    
    if kwargs.get("derby") and tier != "S":
        if tier == "B":
            mult *= MULTIPLIERS["derby_B"]
        else:
            mult *= MULTIPLIERS["derby"]
    
    if kwargs.get("lost_bottom"):
        mult *= MULTIPLIERS["lost_bottom"]
    elif kwargs.get("heavy_home_loss"):
        mult *= MULTIPLIERS["heavy_home_loss"]
    
    if kwargs.get("away_winless"):
        mult *= MULTIPLIERS["away_winless"]
    if kwargs.get("saturday"):
        mult *= MULTIPLIERS["saturday"]
    if kwargs.get("late_season"):
        mult *= MULTIPLIERS["late_season"]
    if kwargs.get("season_opener"):
        mult *= MULTIPLIERS["season_opener"]
    if kwargs.get("midweek") and not kwargs.get("lost_bottom") and not kwargs.get("heavy_home_loss"):
        mult *= MULTIPLIERS["midweek"]
    if kwargs.get("short_rest") and not kwargs.get("lost_bottom") and not kwargs.get("heavy_home_loss"):
        mult *= MULTIPLIERS["short_rest"]
    
    if mult < PENALTY_FLOOR:
        mult = PENALTY_FLOOR
    
    return min(base * mult, 20000.0)

no_dev_results = []
for _, match in completed_home.iterrows():
    opp_raw = match["away_club"]
    opp_short = normalize_opp(opp_raw)
    ctx = detect_ctx_match(match, df_raw, match["date"], match["season"])
    
    pred_kwargs = {
        "derby": ctx.get("derby", False),
        "lost_bottom": ctx.get("lost_bottom", False),
        "heavy_home_loss": ctx.get("heavy_home_loss", False),
        "away_winless": ctx.get("away_winless", False),
        "saturday": ctx.get("saturday", False),
        "late_season": ctx.get("late_season", False),
        "season_opener": ctx.get("season_opener", False),
        "short_rest": ctx.get("short_rest", False),
        "midweek": ctx.get("midweek", False),
    }
    
    pred = predict_no_dev(opp_short, **pred_kwargs)
    
    mid = match["match_id"]
    mf_row = mf[mf["match_id"] == mid]
    actual = int(mf_row["attendance"].iloc[0]) if len(mf_row) > 0 else None
    
    if actual:
        no_dev_results.append({
            "season": match["season"],
            "predicted": round(pred, 0),
            "actual": actual,
            "abs_error": abs(pred - actual),
            "ape_pct": abs(pred - actual) / actual * 100,
        })

df_no_dev = pd.DataFrame(no_dev_results)
for season in sorted(df_no_dev["season"].unique()):
    s = df_no_dev[df_no_dev["season"] == season]
    print(f"  {season}: MAE={s['abs_error'].mean():.0f}, MAPE={s['ape_pct'].mean():.1f}%")
print(f"  Overall: MAE={df_no_dev['abs_error'].mean():.0f}, MAPE={df_no_dev['ape_pct'].mean():.1f}%")

mae_diff = df_no_dev["abs_error"].mean() - mae_all
print(f"\n  ΔMAE vs baseline: {mae_diff:+.0f} ({'WORSE' if mae_diff > 0 else 'BETTER'})")

# ── 11. GRID SEARCH on MULTIPLIERS ──────────────────────────
print("\n" + "="*80)
print("GRID SEARCH: Optimize MULTIPLIERS")
print("="*80)

# We'll keep OPP_DEVIATION and grid search key multipliers
# Focus on most impactful ones
param_grid = {
    "derby": [1.15, 1.20, 1.25, 1.30, 1.35],
    "derby_B": [1.05, 1.10, 1.12, 1.15, 1.18],
    "lost_bottom": [0.45, 0.50, 0.55, 0.60, 0.65],
    "heavy_home_loss": [0.60, 0.65, 0.70, 0.75, 0.80],
    "away_winless": [0.70, 0.75, 0.78, 0.82, 0.88],
    "saturday": [1.05, 1.10, 1.12, 1.15, 1.20],
    "late_season": [0.50, 0.55, 0.60, 0.65, 0.70],
    "season_opener": [1.05, 1.10, 1.12, 1.15, 1.20],
    "short_rest": [0.75, 0.80, 0.82, 0.85, 0.90],
    "midweek": [0.78, 0.82, 0.85, 0.88, 0.92],
}

def predict_with_multipliers(opponent, multipliers, **kwargs):
    """Predict with custom multipliers."""
    tier = classify_opponent_tier(opponent)
    base = TIER_BASE.get(tier, 9000)
    dev = match_opp_deviation(opponent)
    base *= dev
    mult = 1.0
    
    if kwargs.get("derby") and tier != "S":
        if tier == "B":
            mult *= multipliers.get("derby_B", MULTIPLIERS["derby_B"])
        else:
            mult *= multipliers.get("derby", MULTIPLIERS["derby"])
    
    if kwargs.get("lost_bottom"):
        mult *= multipliers.get("lost_bottom", MULTIPLIERS["lost_bottom"])
    elif kwargs.get("heavy_home_loss"):
        mult *= multipliers.get("heavy_home_loss", MULTIPLIERS["heavy_home_loss"])
    
    if kwargs.get("away_winless"):
        mult *= multipliers.get("away_winless", MULTIPLIERS["away_winless"])
    if kwargs.get("saturday"):
        mult *= multipliers.get("saturday", MULTIPLIERS["saturday"])
    if kwargs.get("late_season"):
        mult *= multipliers.get("late_season", MULTIPLIERS["late_season"])
    if kwargs.get("season_opener"):
        mult *= multipliers.get("season_opener", MULTIPLIERS["season_opener"])
    if kwargs.get("midweek") and not kwargs.get("lost_bottom") and not kwargs.get("heavy_home_loss"):
        mult *= multipliers.get("midweek", MULTIPLIERS["midweek"])
    if kwargs.get("short_rest") and not kwargs.get("lost_bottom") and not kwargs.get("heavy_home_loss"):
        mult *= multipliers.get("short_rest", MULTIPLIERS["short_rest"])
    
    if mult < PENALTY_FLOOR:
        mult = PENALTY_FLOOR
    
    return min(base * mult, 20000.0)

# Pre-compute all match contexts
match_contexts = []
for _, match in completed_home.iterrows():
    opp_raw = match["away_club"]
    opp_short = normalize_opp(opp_raw)
    ctx = detect_ctx_match(match, df_raw, match["date"], match["season"])
    
    mid = match["match_id"]
    mf_row = mf[mf["match_id"] == mid]
    actual = int(mf_row["attendance"].iloc[0]) if len(mf_row) > 0 else None
    
    match_contexts.append({
        "season": match["season"],
        "opponent": opp_short,
        "actual": actual,
        "ctx": ctx,
    })

def evaluate_multipliers(mults, match_contexts):
    """Compute MAE for given multipliers."""
    errors = []
    for mc in match_contexts:
        if mc["actual"] is None:
            continue
        kwargs = {
            "derby": mc["ctx"].get("derby", False),
            "lost_bottom": mc["ctx"].get("lost_bottom", False),
            "heavy_home_loss": mc["ctx"].get("heavy_home_loss", False),
            "away_winless": mc["ctx"].get("away_winless", False),
            "saturday": mc["ctx"].get("saturday", False),
            "late_season": mc["ctx"].get("late_season", False),
            "season_opener": mc["ctx"].get("season_opener", False),
            "short_rest": mc["ctx"].get("short_rest", False),
            "midweek": mc["ctx"].get("midweek", False),
        }
        pred = predict_with_multipliers(mc["opponent"], mults, **kwargs)
        errors.append(abs(pred - mc["actual"]))
    return np.mean(errors) if errors else float("inf")

# Single-parameter grid search (one at a time, keep others at default)
baseline_mae = mae_all
print(f"Baseline MAE: {baseline_mae:.0f}")

for param, values in param_grid.items():
    best_val = None
    best_mae = float("inf")
    for v in values:
        test_mults = {param: v}
        mae = evaluate_multipliers(test_mults, match_contexts)
        if mae < best_mae:
            best_mae = mae
            best_val = v
    current = MULTIPLIERS[param]
    delta = best_mae - baseline_mae
    marker = "★" if best_val != current else " "
    print(f"  {param:<18} current={current:.2f} best={best_val:.2f} MAE={best_mae:.0f} (Δ={delta:+.0f}) {marker}")

# ── 12. PROPOSE OPTIMIZATIONS ───────────────────────────────
print("\n" + "="*80)
print("OPTIMIZATION PROPOSALS")
print("="*80)

print("""
Proposal 1: Update MULTIPLIERS based on grid search
  - Apply the best single-parameter values found above
  - Expected MAE improvement: see grid search deltas
  - Low risk: only changes existing parameters within reasonable bounds

Proposal 2: Add big_win_prev multiplier
  - The rule_engine.py already has 'big_win_prev=0.82' in docstring but not in MULTIPLIERS dict
  - Add as a positive boost (e.g., 1.08-1.12x) when last match was a big win (3+ goal margin)
  - This counteracts the "lost_bottom" pessimism when team is on a hot streak
  - Expected MAE improvement: 50-150 tickets depending on how many matches trigger

Proposal 3: Tier-specific late_season multipliers
  - Late season penalty should differ by tier: big matches (S/A) stay attractive
  - S/A tier: 0.80-0.85 (less penalty)
  - C1/C2 tier: 0.50-0.55 (more penalty - fans lose interest in meaningless games)
  - Expected MAE improvement: 100-200 tickets

Proposal 4: Recalibrate TIER_BASE from 2025+2026 data
  - Current bases are from 2025 only
  - Including 2026 actuals could improve accuracy for 2026 forecasts
  - Expected MAE improvement: 50-100 tickets (2026 specifically)
""")

# ── 13. Save results ────────────────────────────────────────
out_path = Path("data/processed/backtest_results.json")
out_path.parent.mkdir(parents=True, exist_ok=True)
df_results.to_json(out_path, orient="records", indent=2, force_ascii=False)
print(f"\nResults saved to {out_path}")
