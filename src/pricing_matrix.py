"""
[DEPRECATED — 2026-05-19 P0.3] 10档 × S/A/B/C 调价系数矩阵。

此模块基于 KMeans 聚类生成的10档体系，与国安真实的6档×2级 zone 结构不匹配。
国安实际票价体系见 data/processed/zone_tier_map.json。

P1 将重建基于真实6档×4级对手的定价矩阵。
当前保留此模块仅用于看板向后兼容，新功能请勿依赖。
"""
from __future__ import annotations

import json
import os
import statistics
import warnings
from functools import lru_cache

TIER_ORDER_10: list[str] = [f"T{i}" for i in range(1, 11)]

PRICING_MATRIX: dict[str, dict[str, float]] = {
    "S": {
        "T1": 1.05,
        "T2": 1.05,
        "T3": 1.05,
        "T4": 1.10,
        "T5": 1.10,
        "T6": 1.10,
        "T7": 1.10,
        "T8": 1.05,
        "T9": 1.03,
        "T10": 1.03,
    },
    "A": {
        "T1": 1.03,
        "T2": 1.03,
        "T3": 1.03,
        "T4": 1.05,
        "T5": 1.05,
        "T6": 1.05,
        "T7": 1.05,
        "T8": 1.03,
        "T9": 1.00,
        "T10": 1.00,
    },
    "B": {t: 1.0 for t in TIER_ORDER_10},
    "C": {
        "T1": 1.00,
        "T2": 1.00,
        "T3": 1.00,
        "T4": 0.95,
        "T5": 0.95,
        "T6": 0.95,
        "T7": 0.95,
        "T8": 0.90,
        "T9": 0.90,
        "T10": 0.90,
    },
}


def _section_map_path() -> str:
    return os.path.join(
        os.path.dirname(__file__), "..", "data", "processed", "section_tier_map.json"
    )


@lru_cache(maxsize=1)
def load_section_tier_map() -> dict:
    """读 ``data/processed/section_tier_map.json``（区段 → 档位等）。"""
    path = _section_map_path()
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def get_multiplier(tier: str, opponent_level: str) -> float:
    """查 10档×对手级 调价系数。"""
    level = str(opponent_level).strip().upper()[:1] or "B"
    t = str(tier).strip().upper()
    if not t.startswith("T"):
        t = f"T{t}" if t.isdigit() else t
    return float(PRICING_MATRIX.get(level, PRICING_MATRIX["B"]).get(t, 1.0))


def get_section_multiplier(section: str, opponent_level: str) -> float:
    """区段 → 档位 → 系数。"""
    m = load_section_tier_map()
    key = str(section).strip()
    info = m.get(key) or m.get(key.lstrip("0"))
    if not info:
        return 1.0
    tier = info.get("tier", "T10")
    return get_multiplier(tier, opponent_level)


def sections_for_tier(tier: str) -> list[str]:
    """列出映射到某档位的区段号。"""
    m = load_section_tier_map()
    t = str(tier).strip().upper()
    return sorted(k for k, v in m.items() if str(v.get("tier", "")).upper() == t)


def build_matrix_adjusted_prices(opponent_level: str) -> dict[str, float]:
    """基准价 × 对手级矩阵系数。"""
    base = load_tier_base_prices()
    return {t: round(base[t] * get_multiplier(t, opponent_level), 0) for t in TIER_ORDER_10}


def load_tier_base_prices() -> dict[str, float]:
    """各区段均价按档位聚合。"""
    m = load_section_tier_map()
    buckets: dict[str, list[float]] = {}
    for info in m.values():
        tier = str(info.get("tier", "T10"))
        price = float(info.get("avg_price", 0) or 0)
        if price > 0:
            buckets.setdefault(tier, []).append(price)
    defaults = {
        "T1": 2160.0,
        "T2": 1600.0,
        "T3": 1288.0,
        "T4": 1129.0,
        "T5": 982.0,
        "T6": 722.0,
        "T7": 660.0,
        "T8": 604.0,
        "T9": 482.0,
        "T10": 292.0,
    }
    out: dict[str, float] = {}
    for t in TIER_ORDER_10:
        if t in buckets and buckets[t]:
            out[t] = round(float(statistics.mean(buckets[t])), 0)
        else:
            out[t] = defaults[t]
    return out
