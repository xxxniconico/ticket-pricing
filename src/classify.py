"""比赛分级：A/B + 多维需求乘数"""
import math
from dataclasses import dataclass

S_TIER = {"上海申花"}
A_TIER = {"山东泰山", "成都蓉城", "上海海港"}
C1_TIER = {  # 新鲜感：升班马/不常见对手 → 溢价
    "云南玉昆", "深圳新鹏城", "南通支云", "沧州雄狮",
    "辽宁铁人", "重庆铜梁龙",
}
C2_TIER = {  # 常客：保级区老面孔 → 无兴趣
    "大连英博", "青岛海牛", "梅州客家", "青岛西海岸",
}
# B_TIER = 其余 (天津津门虎, 浙江, 河南, 武汉三镇, 长春亚泰, …)
A_TIER_OPPONENTS = S_TIER | A_TIER  # 向后兼容：强对手 = S + A
DERBY_RIVALS = {"上海申花", "天津津门虎", "山东泰山"}


def classify_opponent_tier(opponent: str) -> str:
    """返回 S/A/B/C1/C2 五级分类（静态标签）"""
    o = str(opponent).strip()
    if any(t in o or o in t for t in S_TIER):
        return "S"
    if any(t in o or o in t for t in A_TIER):
        return "A"
    if any(t in o or o in t for t in C1_TIER):
        return "C1"
    if any(t in o or o in t for t in C2_TIER):
        return "C2"
    return "B"


def classify_match_v4(opponent: str, **kwargs) -> tuple[str, float]:
    """四级分级 + 情境乘数（与 classify_match_hybrid 参数一致）。"""
    tier = classify_opponent_tier(opponent)
    mult = get_demand_multiplier(
        opponent=opponent,
        opponent_standing=kwargs.get("opponent_standing"),
        base_lookup=kwargs.get("base_lookup"),
        is_weekend=kwargs.get("is_weekend", True),
        is_holiday=kwargs.get("is_holiday", False),
        season_stage=kwargs.get("season_stage", "mid"),
        home_form=kwargs.get("home_form", 0.5),
        temperature_c=kwargs.get("temperature_c", 20.0),
        precipitation_mm=kwargs.get("precipitation_mm", 0.0),
        calibrated_weights=kwargs.get("calibrated_weights"),
        second_half=kwargs.get("second_half", False),
    )
    return tier, mult


@dataclass
class MatchContext:
    opponent: str
    is_weekend: bool = True
    is_holiday: bool = False
    season_stage: str = "mid"
    home_form: float = 0.5
    opponent_standing: int = 8
    temperature_c: float = 20.0
    precipitation_mm: float = 0.0


def compute_demand_multiplier(ctx: MatchContext) -> float:
    mult = 1.0
    if ctx.opponent in DERBY_RIVALS:
        mult *= 1.35
    elif ctx.opponent in A_TIER_OPPONENTS:
        mult *= 1.25
    if ctx.is_weekend:
        mult *= 1.10
    if ctx.opponent_standing <= 3:
        mult *= 1.15
    elif ctx.opponent_standing >= 14:
        mult *= 0.90
    if ctx.season_stage in ("crucial", "title_race", "relegation"):
        mult *= 1.20
    if ctx.home_form > 0.6:
        mult *= 1.08
    elif ctx.home_form < 0.3:
        mult *= 0.92
    if ctx.is_holiday:
        mult *= 1.12
    if ctx.temperature_c < 5 or ctx.precipitation_mm > 25:
        mult *= 0.85
    return round(mult, 3)


def classify_match(opponent: str, **kwargs) -> tuple[str, float]:
    """返回 (A/B, demand_multiplier) — 纯理论情境乘数（其他模块可继续引用）。"""
    ctx = MatchContext(opponent=opponent, **kwargs)
    tier = "A" if classify_opponent_tier(opponent) in ("S", "A") else "B"
    return tier, compute_demand_multiplier(ctx)


def build_base_multiplier_lookup(
    seat_data_path: str = "data/raw/2025散票数据.xlsx",
) -> dict[str, float]:
    """从 2025 数据计算每个对手的基础需求乘数

    乘数 = 该对手场均散票 / 同级对手场均散票
    """
    from src.ingest import load_seat_data

    df = load_seat_data(seat_data_path)

    by_match = (
        df.groupby("match_id")
        .agg(
            attendance=("match_id", "size"),
            opponent=("opponent", "first"),
        )
        .reset_index()
    )

    a_opps = set(
        by_match[by_match["opponent"].isin(A_TIER_OPPONENTS)]["opponent"].astype(str)
    )
    if not a_opps:
        a_avg = 1.0
    else:
        a_avg = float(
            by_match[by_match["opponent"].astype(str).isin(a_opps)]["attendance"].mean()
        )

    b_mask = ~by_match["opponent"].astype(str).isin(a_opps)
    if not b_mask.any():
        b_avg = 1.0
    else:
        b_avg = float(by_match.loc[b_mask, "attendance"].mean())

    if not math.isfinite(a_avg) or a_avg <= 0:
        a_avg = 1.0
    if not math.isfinite(b_avg) or b_avg <= 0:
        b_avg = 1.0

    by_opp = by_match.groupby("opponent")["attendance"].mean()

    result: dict[str, float] = {}
    for opp, att in by_opp.items():
        opp_s = str(opp)
        baseline = a_avg if opp_s in a_opps else b_avg
        result[opp_s] = round(float(att) / baseline, 3) if baseline > 0 else 1.0

    return result


def get_demand_multiplier(
    opponent: str,
    opponent_standing: int | None = None,
    base_lookup: dict[str, float] | None = None,
    is_weekend: bool = True,
    is_holiday: bool = False,
    season_stage: str = "mid",
    home_form: float = 0.5,
    temperature_c: float = 20.0,
    precipitation_mm: float = 0.0,
    calibrated_weights: dict | None = None,
    second_half: bool = False,
) -> float:
    """混合乘数 = base × context（base 历史查表，context 为情境因子）。"""
    if base_lookup and opponent in base_lookup:
        base = base_lookup[opponent]
    elif opponent_standing is not None and opponent_standing <= 4:
        base = 1.25
    elif opponent_standing is not None and opponent_standing >= 13:
        base = 0.75
    else:
        base = 1.0

    if calibrated_weights:
        ctx_mult = 1.0
        if is_weekend:
            ctx_mult *= float(calibrated_weights.get("weekend", 1.05))
        if opponent_standing is not None and opponent_standing <= 3:
            ctx_mult *= float(calibrated_weights.get("top3_opponent", 1.08))
        elif opponent_standing is not None and opponent_standing >= 14:
            ctx_mult *= float(calibrated_weights.get("bottom3_opponent", 0.95))
        hfb = calibrated_weights.get("home_form_bonus")
        if hfb is not None:
            factor = 1.0 + float(hfb) * float(home_form)
            ctx_mult *= max(0.15, factor)
        if second_half:
            ctx_mult *= float(calibrated_weights.get("second_half_penalty", 1.0))
        if opponent in DERBY_RIVALS:
            ctx_mult *= float(calibrated_weights.get("derby_bonus", 1.35))
        if is_holiday:
            ctx_mult *= 1.06
        if season_stage in ("crucial", "title_race", "relegation"):
            ctx_mult *= 1.10
        if temperature_c < 5 or precipitation_mm > 25:
            ctx_mult *= 0.90
        return round(base * ctx_mult, 3)

    ctx_mult = 1.0

    if is_weekend:
        ctx_mult *= 1.05

    if is_holiday:
        ctx_mult *= 1.06

    if opponent_standing is not None and opponent_standing <= 3:
        ctx_mult *= 1.08
    elif opponent_standing is not None and opponent_standing >= 14:
        ctx_mult *= 0.95

    if season_stage in ("crucial", "title_race", "relegation"):
        ctx_mult *= 1.10

    if home_form > 0.6:
        ctx_mult *= 1.05
    elif home_form < 0.3:
        ctx_mult *= 0.95

    if temperature_c < 5 or precipitation_mm > 25:
        ctx_mult *= 0.90

    return round(base * ctx_mult, 3)


def classify_match_hybrid(
    opponent: str,
    base_lookup: dict[str, float] | None = None,
    opponent_standing: int = 8,
    is_weekend: bool = True,
    is_holiday: bool = False,
    season_stage: str = "mid",
    home_form: float = 0.5,
    temperature_c: float = 20.0,
    precipitation_mm: float = 0.0,
    calibrated_weights: dict | None = None,
    second_half: bool = False,
) -> tuple[str, float]:
    """混合模型：base × context"""
    tier = "A" if opponent in A_TIER_OPPONENTS else "B"
    mult = get_demand_multiplier(
        opponent=opponent,
        opponent_standing=opponent_standing,
        base_lookup=base_lookup,
        is_weekend=is_weekend,
        is_holiday=is_holiday,
        season_stage=season_stage,
        home_form=home_form,
        temperature_c=temperature_c,
        precipitation_mm=precipitation_mm,
        calibrated_weights=calibrated_weights,
        second_half=second_half,
    )
    return tier, mult


# 兼容旧名（feedback #5 v1）
build_demand_multiplier_lookup = build_base_multiplier_lookup
