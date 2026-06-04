"""比赛分级：4级（V4.6 最优）"""
import math
from dataclasses import dataclass

S_TIER = {"上海申花"}
A_TIER = {"成都蓉城", "山东泰山", "天津津门虎"}
B_TIER = {"长春亚泰", "深圳新鹏城", "云南玉昆", "武汉三镇",
           "浙江", "浙江队", "浙江俱乐部绿城",
           "上海海港", "河南", "河南队", "河南俱乐部酒祖杜康", "河南队俱乐部彩陶坊",
           "梅州客家", "青岛西海岸"}
C_TIER = {"大连英博", "大连英博海发",
           "辽宁铁人", "重庆铜梁龙", "青岛海牛",
           "沧州雄狮", "南通支云"}

A_TIER_OPPONENTS = S_TIER | A_TIER
DERBY_RIVALS = {"上海申花", "山东泰山"}

def classify_opponent_tier(opponent: str) -> str:
    o = str(opponent).strip()
    if any(t in o or o in t for t in S_TIER): return "S"
    if any(t in o or o in t for t in A_TIER): return "A"
    if any(t in o or o in t for t in B_TIER): return "B"
    if any(t in o or o in t for t in C_TIER): return "C"
    return "B"

# ── 向后兼容代码同前 ──
def classify_match_v4(opponent: str, **kwargs) -> tuple[str, float]:
    tier = classify_opponent_tier(opponent)
    mult = get_demand_multiplier(opponent=opponent, **kwargs)
    return tier, mult

@dataclass
class MatchContext:
    opponent: str; is_weekend: bool = True; is_holiday: bool = False
    season_stage: str = "mid"; home_form: float = 0.5
    opponent_standing: int = 8; temperature_c: float = 20.0
    precipitation_mm: float = 0.0

def compute_demand_multiplier(ctx: MatchContext) -> float:
    mult = 1.0
    if ctx.opponent in DERBY_RIVALS: mult *= 1.35
    elif ctx.opponent in A_TIER_OPPONENTS: mult *= 1.25
    if ctx.is_weekend: mult *= 1.10
    if ctx.opponent_standing <= 3: mult *= 1.15
    elif ctx.opponent_standing >= 14: mult *= 0.90
    if ctx.season_stage in ("crucial","title_race","relegation"): mult *= 1.20
    if ctx.home_form > 0.6: mult *= 1.08
    elif ctx.home_form < 0.3: mult *= 0.92
    if ctx.is_holiday: mult *= 1.12
    if ctx.temperature_c < 5 or ctx.precipitation_mm > 25: mult *= 0.85
    return round(mult, 3)

def classify_match(opponent: str, **kwargs) -> tuple[str, float]:
    ctx = MatchContext(opponent=opponent, **kwargs)
    t = classify_opponent_tier(opponent)
    tier = "A" if t in ("S","A") else "B"
    return tier, compute_demand_multiplier(ctx)

def build_base_multiplier_lookup(seat_data_path="data/raw/2025散票数据.xlsx") -> dict:
    from src.ingest import load_seat_data
    df = load_seat_data(seat_data_path)
    by_match = df.groupby("match_id").agg(attendance=("match_id","size"), opponent=("opponent","first")).reset_index()
    a_opps = set(by_match[by_match["opponent"].isin(A_TIER_OPPONENTS)]["opponent"].astype(str))
    a_avg = float(by_match[by_match["opponent"].astype(str).isin(a_opps)]["attendance"].mean()) if a_opps else 1.0
    b_mask = ~by_match["opponent"].astype(str).isin(a_opps)
    b_avg = float(by_match.loc[b_mask,"attendance"].mean()) if b_mask.any() else 1.0
    if not math.isfinite(a_avg) or a_avg<=0: a_avg=1.0
    if not math.isfinite(b_avg) or b_avg<=0: b_avg=1.0
    by_opp = by_match.groupby("opponent")["attendance"].mean()
    result = {}
    for opp, att in by_opp.items():
        opp_s = str(opp); baseline = a_avg if opp_s in a_opps else b_avg
        result[opp_s] = round(float(att)/baseline,3) if baseline>0 else 1.0
    return result

def get_demand_multiplier(opponent, opponent_standing=None, base_lookup=None, is_weekend=True, is_holiday=False, season_stage="mid", home_form=0.5, temperature_c=20.0, precipitation_mm=0.0, calibrated_weights=None, second_half=False) -> float:
    if base_lookup and opponent in base_lookup: base = base_lookup[opponent]
    elif opponent_standing is not None and opponent_standing<=4: base=1.25
    elif opponent_standing is not None and opponent_standing>=13: base=0.75
    else: base=1.0
    if calibrated_weights:
        ctx_mult=1.0
        if is_weekend: ctx_mult*=float(calibrated_weights.get("weekend",1.05))
        if opponent_standing is not None and opponent_standing<=3: ctx_mult*=float(calibrated_weights.get("top3_opponent",1.08))
        elif opponent_standing is not None and opponent_standing>=14: ctx_mult*=float(calibrated_weights.get("bottom3_opponent",0.95))
        hfb=calibrated_weights.get("home_form_bonus")
        if hfb is not None: ctx_mult*=max(0.15,1.0+float(hfb)*float(home_form))
        if second_half: ctx_mult*=float(calibrated_weights.get("second_half_penalty",1.0))
        if opponent in DERBY_RIVALS: ctx_mult*=float(calibrated_weights.get("derby_bonus",1.35))
        if is_holiday: ctx_mult*=1.06
        if season_stage in ("crucial","title_race","relegation"): ctx_mult*=1.10
        if temperature_c<5 or precipitation_mm>25: ctx_mult*=0.90
        return round(base*ctx_mult,3)
    ctx_mult=1.0
    if is_weekend: ctx_mult*=1.05
    if is_holiday: ctx_mult*=1.06
    if opponent_standing is not None and opponent_standing<=3: ctx_mult*=1.08
    elif opponent_standing is not None and opponent_standing>=14: ctx_mult*=0.95
    if season_stage in ("crucial","title_race","relegation"): ctx_mult*=1.10
    if home_form>0.6: ctx_mult*=1.05
    elif home_form<0.3: ctx_mult*=0.95
    if temperature_c<5 or precipitation_mm>25: ctx_mult*=0.90
    return round(base*ctx_mult,3)

def classify_match_hybrid(opponent, base_lookup=None, opponent_standing=8, is_weekend=True, is_holiday=False, season_stage="mid", home_form=0.5, temperature_c=20.0, precipitation_mm=0.0, calibrated_weights=None, second_half=False) -> tuple:
    tier = "A" if opponent in A_TIER_OPPONENTS else "B"
    mult = get_demand_multiplier(opponent, opponent_standing=opponent_standing, base_lookup=base_lookup, is_weekend=is_weekend, is_holiday=is_holiday, season_stage=season_stage, home_form=home_form, temperature_c=temperature_c, precipitation_mm=precipitation_mm, calibrated_weights=calibrated_weights, second_half=second_half)
    return tier, mult

build_demand_multiplier_lookup = build_base_multiplier_lookup