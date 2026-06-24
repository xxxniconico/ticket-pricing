"""Monte Carlo correlation handling for same-group simultaneous matches (plan §6).

Round 3 of the WC group stage has two same-group matches played simultaneously
(to prevent match-fixing). Results are not independent in reality (tactical
adjustments, group-standings incentives). This module:

  1. Builds current group standings from played matches.
  2. Monte Carlo (N=10000): simulates both round-3 matches via DC-corrected
     Poisson, records joint result distribution + final standings.
  3. Computes the 3×3 joint probability matrix and bet-outcome covariance.
  4. Keep/drop decision for same-group bet pairs: if covariance ≈ 0 (model
     independence), keep both (diversification); if strongly positive, drop
     the lower-EV bet.

Limitation (plan §11.5): the Poisson model generates matches independently,
so tactical/psychological correlation is NOT captured. The Monte Carlo
quantifies the model's implied joint distribution, not the real-world one.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[3]
UNIFIED_FILE = PROJECT_ROOT / "data/processed/wc_2026_unified.json"
MODEL_INPUT = PROJECT_ROOT / "data/processed/wc_2026_model_input.json"
VALUE_FILE = PROJECT_ROOT / "output/wc_value_opportunities.json"
OUT_FILE = PROJECT_ROOT / "output/wc_correlation_analysis.json"

N_SIM = 10000
MAX_GOALS = 8
SEL_IDX = {"H": 0, "D": 1, "A": 2}


def _group_standings(played: list[dict]) -> dict[str, dict]:
    """Compute {team: {pts, gf, ga, gd, played}} from played group matches."""
    st: dict[str, dict] = defaultdict(lambda: {"pts": 0, "gf": 0, "ga": 0, "played": 0})
    for m in played:
        h, a = m["home"], m["away"]
        gh, ga = m["gh"], m["ga"]
        st[h]["gf"] += gh; st[h]["ga"] += ga; st[h]["played"] += 1
        st[a]["gf"] += ga; st[a]["ga"] += gh; st[a]["played"] += 1
        if gh > ga:
            st[h]["pts"] += 3
        elif gh == ga:
            st[h]["pts"] += 1; st[a]["pts"] += 1
        else:
            st[a]["pts"] += 3
    for t in st:
        st[t]["gd"] = st[t]["gf"] - st[t]["ga"]
    return dict(st)


def _standings_after(standings: dict, match_results: list[tuple]) -> dict:
    """Clone standings and apply round-3 results [(home, away, gh, ga), ...]."""
    st = {t: dict(v) for t, v in standings.items()}
    for h, a, gh, ga in match_results:
        if h not in st:
            st[h] = {"pts": 0, "gf": 0, "ga": 0, "played": 0}
        if a not in st:
            st[a] = {"pts": 0, "gf": 0, "ga": 0, "played": 0}
        st[h]["gf"] += gh; st[h]["ga"] += ga; st[h]["played"] += 1
        st[a]["gf"] += ga; st[a]["ga"] += gh; st[a]["played"] += 1
        if gh > ga:
            st[h]["pts"] += 3
        elif gh == ga:
            st[h]["pts"] += 1; st[a]["pts"] += 1
        else:
            st[a]["pts"] += 3
    for t in st:
        st[t]["gd"] = st[t]["gf"] - st[t]["ga"]
    return st


def _rank_teams(standings: dict) -> list[str]:
    """Rank by pts, GD, GF."""
    return sorted(standings.keys(),
                  key=lambda t: (standings[t]["pts"], standings[t]["gd"], standings[t]["gf"]),
                  reverse=True)


def _result_label(gh: int, ga: int) -> str:
    return "H" if gh > ga else ("D" if gh == ga else "A")


@dataclass
class GroupMC:
    group: str
    matches: list[dict]                     # the 2 round-3 matches (from model_input)
    joint_matrix: np.ndarray                # 3x3: [match1_result][match2_result]
    bet_covariance: float | None            # cov between bet1 outcome, bet2 outcome
    bet_joint_win: float | None             # P(both bets win)
    advancement_prob: dict[str, float] = field(default_factory=dict)
    keep_both: bool = True
    drop: str | None = None                 # which match to drop if not keep_both
    reason: str = ""


def simulate_group(group: str, matches: list[dict], params, n_sim: int = N_SIM) -> GroupMC:
    """Monte Carlo for one group's 2 simultaneous matches."""
    from wc_betting.models.poisson import score_matrix, host_rho, RHO_NEUTRAL

    # Precompute score matrices (10x10) for each match.
    sm_list = []
    for m in matches:
        home = m["home"]; away = m["away"]
        h_code = params.name_to_code.get(home, home) if hasattr(params, "name_to_code") else home
        # params here is a PoissonModel; use its code map
        pass

    # We need the PoissonModel for code lookup + host_rho.
    # matches carry home/away as canonical names; resolve to codes.
    name_to_code = params.name_to_code
    matrices = []
    bet_selections = []
    for m in matches:
        hc = name_to_code[m["home"]]
        ac = name_to_code[m["away"]]
        rho = host_rho(params.params, m["home"])
        sm = score_matrix(params.params, hc, ac, rho=rho, max_goals=MAX_GOALS)
        matrices.append(sm)
        bet_selections.append(m.get("bet_selection"))  # "H"/"D"/"A" or None

    # Flatten for sampling.
    flat = [sm.flatten() for sm in matrices]
    n_cells = MAX_GOALS * MAX_GOALS
    cell_idx = np.arange(n_cells)

    # Joint simulation (independent under Poisson).
    rng = np.random.default_rng(42)
    joint = np.zeros((3, 3))
    bet_outcomes = []
    advancement_counts: dict[str, int] = defaultdict(int)

    # Current standings from played matches in this group.
    played = _load_group_played(group)

    for _ in range(n_sim):
        # Sample scores for both matches independently.
        results = []
        for i, (f, sm) in enumerate(zip(flat, matrices)):
            c = rng.choice(n_cells, p=f)
            gh, ga = divmod(c, MAX_GOALS)
            results.append((matches[i]["home"], matches[i]["away"], gh, ga))
        r1 = _result_label(results[0][2], results[0][3])
        r2 = _result_label(results[1][2], results[1][3])
        joint[SEL_IDX[r1], SEL_IDX[r2]] += 1

        # Advancement.
        st = _standings_after(played, results)
        ranked = _rank_teams(st)
        for t in ranked[:2]:
            advancement_counts[t] += 1

        # Bet outcomes (1 if bet selection matches result, 0 else).
        row = []
        for i, sel in enumerate(bet_selections):
            if sel is None:
                row.append(None)
            else:
                r = r1 if i == 0 else r2
                row.append(1.0 if r == sel else 0.0)
        bet_outcomes.append(row)

    joint /= n_sim
    advancement_prob = {t: c / n_sim for t, c in advancement_counts.items()}

    # Bet covariance.
    bet_cov = None
    bet_joint_win = None
    if bet_selections[0] and bet_selections[1]:
        b0 = np.array([r[0] for r in bet_outcomes])
        b1 = np.array([r[1] for r in bet_outcomes])
        bet_cov = float(np.cov(b0, b1)[0, 1])
        bet_joint_win = float(np.mean(b0 * b1))

    return GroupMC(
        group=group, matches=matches, joint_matrix=joint,
        bet_covariance=bet_cov, bet_joint_win=bet_joint_win,
        advancement_prob=advancement_prob,
    )


def _load_group_played(group: str) -> dict:
    """Load played matches for a group from unified data, return standings dict."""
    unified = json.loads(UNIFIED_FILE.read_text(encoding="utf-8"))
    norm = _normalizer()
    played = []
    for m in unified:
        if m.get("group") != group or not m.get("finished") or not m.get("score"):
            continue
        s = m["score"].replace("–", "-").split("-")
        played.append({
            "home": norm.get(m["home_en"], m["home_en"]),
            "away": norm.get(m["away_en"], m["away_en"]),
            "gh": int(s[0]), "ga": int(s[1]),
        })
    return _group_standings(played)


def _normalizer():
    return {
        "Canada men&#39;s": "Canada", "United States men&#39;s": "United States",
        "USA": "United States", "Australia men&#39;s": "Australia",
        "Sweden men&#39;s": "Sweden", "New Zealand men&#39;s": "New Zealand",
        "Curaçao": "Curacao", "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    }


def find_same_group_bet_pairs(value_data: dict) -> list[tuple[str, list[dict]]]:
    """Find groups where 2 bets share the same date (true simultaneous pairs)."""
    bets = [r for r in value_data["opportunities"] if r["status"] == "bet"]
    by_date_group = defaultdict(list)
    for b in bets:
        by_date_group[(b["date"], b["group"])].append(b)
    pairs = []
    for (date, group), bs in by_date_group.items():
        if len(bs) == 2:
            pairs.append((group, bs))
    return pairs


def decide_keep_drop(mc: GroupMC, bets: list[dict]) -> GroupMC:
    """Decide whether to keep both same-group bets or drop one.

    Under Poisson independence, covariance ≈ 0 → keep both (diversification).
    Drop the lower-EV bet only if covariance is strongly positive (> 0.05),
    meaning both tend to win/lose together (concentration risk).
    """
    if mc.bet_covariance is None:
        mc.keep_both = True
        mc.reason = "no bet on one or both matches"
        return mc
    if mc.bet_covariance <= 0.05:
        mc.keep_both = True
        mc.reason = (f"covariance {mc.bet_covariance:+.4f} ≈ 0 (model independence); "
                     "keep both for diversification")
    else:
        # Strongly positive: concentration risk. Drop lower-EV bet.
        evs = [b["ev"] for b in bets]
        drop_idx = 0 if evs[0] < evs[1] else 1
        mc.keep_both = False
        mc.drop = bets[drop_idx]["match"]
        mc.reason = (f"covariance {mc.bet_covariance:+.4f} strongly positive; "
                     f"drop {mc.drop} (lower EV) to avoid concentration")
    return mc


def run(verbose: bool = True) -> dict:
    from wc_betting.models.poisson import PoissonModel
    from wc_betting.strategy.value import screen

    # Refit Poisson on ALL history (production model for prediction).
    hist_path = PROJECT_ROOT / "data/raw/historical/intl_results_2022_2026.json"
    history = json.loads(hist_path.read_text(encoding="utf-8"))["matches"]
    poisson = PoissonModel.fit(matches=history)

    value_data = json.loads(VALUE_FILE.read_text(encoding="utf-8"))
    pairs = find_same_group_bet_pairs(value_data)

    model_input = json.loads(MODEL_INPUT.read_text(encoding="utf-8"))
    mi_by_match = {(m["home"], m["away"]): m for m in model_input["matches"]}

    results = []
    for group, bet_pair in pairs:
        date = bet_pair[0]["date"]
        # Find the 2 matches in this group on this date from model_input.
        group_date_matches = [
            mi for mi in model_input["matches"]
            if mi["group"] == group and mi["date"] == date
        ]
        # Attach bet selection info.
        bet_by_match = {b["match"]: b for b in bet_pair}
        for m in group_date_matches:
            key = f"{m['home']} vs {m['away']}"
            b = bet_by_match.get(key)
            m["bet_selection"] = b["selection"] if b else None

        mc = simulate_group(group, group_date_matches, poisson)
        mc = decide_keep_drop(mc, bet_pair)
        results.append(mc)

        if verbose:
            _print_group(mc, bet_pair)

    # Build adjusted bet list.
    all_bets = [r for r in value_data["opportunities"] if r["status"] == "bet"]
    dropped = {mc.drop for mc in results if not mc.keep_both}
    adjusted = []
    for b in all_bets:
        b2 = dict(b)
        if b["match"] in dropped:
            b2["status"] = "dropped_correlation"
            b2["note"] = f"dropped: same-group concentration risk"
        adjusted.append(b2)

    out = {
        "as_of": value_data.get("as_of"),
        "n_sim": N_SIM,
        "same_group_pairs_analyzed": len(pairs),
        "groups": [
            {
                "group": mc.group,
                "matches": [m["match"] if "match" in m else f"{m['home']} vs {m['away']}"
                            for m in mc.matches],
                "joint_matrix": mc.joint_matrix.tolist(),
                "bet_covariance": mc.bet_covariance,
                "bet_joint_win_prob": mc.bet_joint_win,
                "advancement_prob": mc.advancement_prob,
                "keep_both": mc.keep_both,
                "dropped": mc.drop,
                "reason": mc.reason,
            }
            for mc in results
        ],
        "adjusted_bets": adjusted,
        "n_kept": sum(1 for b in adjusted if b["status"] == "bet"),
        "n_dropped": sum(1 for b in adjusted if b["status"] == "dropped_correlation"),
    }
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    if verbose:
        print()
        print(f"=== Summary ===")
        print(f"same-group pairs analyzed: {len(pairs)}")
        print(f"bets kept:    {out['n_kept']}")
        print(f"bets dropped: {out['n_dropped']}")
        print(f"output: {OUT_FILE}")
    return out


def _print_group(mc: GroupMC, bets: list[dict]) -> None:
    print(f"\n=== Group {mc.group} Monte Carlo (N={N_SIM}) ===")
    print(f"matches: {bets[0]['match']} ({bets[0]['selection']}) + {bets[1]['match']} ({bets[1]['selection']})")
    print(f"joint result matrix (rows=match1 H/D/A, cols=match2 H/D/A):")
    labels = ["H", "D", "A"]
    print(f"       {'  '.join(f'{l:>6s}' for l in labels)}")
    for i, l in enumerate(labels):
        print(f"  {l}  {'  '.join(f'{mc.joint_matrix[i,j]:.3f}' for j in range(3))}")
    print(f"bet covariance:     {mc.bet_covariance:+.4f}" if mc.bet_covariance is not None else "bet covariance: N/A")
    print(f"P(both bets win):   {mc.bet_joint_win:.3f}" if mc.bet_joint_win is not None else "")
    print(f"advancement prob:   {', '.join(f'{t}={p:.1%}' for t, p in sorted(mc.advancement_prob.items(), key=lambda x: -x[1]))}")
    print(f"decision: {'KEEP BOTH' if mc.keep_both else 'DROP ' + str(mc.drop)}")
    print(f"  reason: {mc.reason}")


if __name__ == "__main__":
    run()
