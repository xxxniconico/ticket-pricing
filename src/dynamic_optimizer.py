"""
P2 动态定价优化器 — 规则引擎 × 弹性矩阵 × 约束优化

流程:
  对手/日期/情境 → rule_engine.predict() → 预测总量
  → 按历史份额分配到6档 → 弹性调整 → 优化每档价格
  目标: 0.6×收入 + 0.4×上座量×参考均价

用法:
  opt = DynamicPricingOptimizer()
  result = opt.optimize(opponent="天津津门虎", match_date="2026-08-15",
                        lost_bottom=False, saturday=True, ...)
  print(result.recommended_prices)  # {"T1": 170, "T2": 230, ...}
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from src.rule_engine import predict_calibrated as predict_attendance
from src.classify import classify_opponent_tier as _classify_v3

# ── 2025学习基值（MAE最优，2026-05-19更新）──
# 硬编码基值(MAE=1377) → 学习基值(MAE=1292, MAPE=17.9%)
_LEARNED_BASES = {"S": 12734, "A": 12010, "B": 8882, "C1": 10616, "C2": 4795}

def predict_learned(opponent: str, **context) -> float:
    """使用2025学习基值的规则引擎预测（替代硬编码基值）。"""
    tier = _classify_v3(opponent)
    base = _LEARNED_BASES.get(tier, 9000)
    # Same multiplier logic as rule_engine.predict()
    mult = 1.0
    derby = context.get('derby', False)
    if derby and tier != 'S':
        mult *= 1.12 if tier == 'B' else 1.25
    if context.get('lost_bottom'): mult *= 0.55
    elif context.get('heavy_home_loss'): mult *= 0.70
    if context.get('away_winless'): mult *= 0.78
    if context.get('saturday'): mult *= 1.12
    if context.get('late_season'): mult *= 0.60
    if context.get('season_opener'): mult *= 1.12
    if context.get('midweek'): mult *= 0.85
    if context.get('short_rest'): mult *= 0.82
    mult = max(mult, 0.35)
    return min(base * mult, 20000.0)
from src.pricing_v5 import (
    ZONE_TIERS, ZONE_SECTIONS,
    classify_opponent, get_pricing_tier, build_price_matrix, build_elasticity_matrix,
    is_tier_frozen, FROZEN_TIERS, get_zone_bounds,
    BASE_PRICES_A, BASE_PRICES_B,
)


@dataclass
class TierResult:
    zone_tier: str
    base_price: float          # 基准价
    optimal_price: float       # 优化后价格
    predicted_qty: float        # 优化后预测销量
    base_qty: float            # 基准价下的销量
    revenue: float             # 该档收入
    is_frozen: bool            # 是否锁价


@dataclass
class OptimizeResult:
    opponent: str
    opponent_level: str        # S/A/B/C
    predicted_total: float      # 规则引擎预测总量
    total_revenue: float        # 优化后总收入
    total_attendance: float     # 优化后总上座
    base_revenue: float         # 基准价下的收入（对比用）
    base_attendance: float      # 基准价下的上座（对比用）
    objective_value: float      # 目标函数值
    revenue_weight: float = 0.6  # 本场收入权重
    attendance_weight: float = 0.4  # 本场上座权重
    tiers: dict[str, TierResult] = field(default_factory=dict)
    recommended_prices: dict[str, float] = field(default_factory=dict)


class DynamicPricingOptimizer:
    """动态定价优化器。

    输入: 对手 + 规则引擎情境参数
    输出: 6档推荐价格 + 收入/上座预估
    """

    def __init__(self, revenue_weight: float = 0.6):
        """
        Args:
            revenue_weight: 收入权重 (0~1)，剩余为上座权重
        """
        self.revenue_weight = revenue_weight
        self.attendance_weight = 1.0 - revenue_weight

        # 加载弹性矩阵和价格矩阵
        self.elasticity = build_elasticity_matrix()
        self.price_matrix = build_price_matrix()

        # Zone tier capacities (estimated from section counts)
        self.capacities = self._estimate_capacities()

        # Zone tier volume shares (from 2025 B-tier data, used for initial allocation)
        self.volume_shares = {
            "T1": 0.337, "T2": 0.217, "T3": 0.308,
            "T4": 0.027, "T5": 0.104, "T6": 0.008,
        }

        # Reference price for attendance-to-revenue conversion (per-tier, not global)
        # 每档用自身基准价衡量上座价值，使高端区降价也有动力
        self.p_ref = {zt: BASE_PRICES_B[zt] for zt in ZONE_TIERS}

    def _estimate_capacities(self) -> dict[str, float]:
        """估计每zone tier的容量上限（基于历史峰值销量+缓冲）。"""
        # 2024-2025各zone tier历史单场峰值（来自all_unified.parquet）
        peak = {"T1": 3754, "T2": 3938, "T3": 5246, "T4": 1291, "T5": 2057, "T6": 152}
        # 加10%缓冲
        return {zt: int(v * 1.1) for zt, v in peak.items()}

    def optimize(self, opponent: str, match_date: str | None = None,
                 min_revenue: float = 0.0, **context) -> OptimizeResult:
        """
        为一场比赛优化6档定价。

        Args:
            opponent: 对手名称
            match_date: 比赛日期（用于情境检测）
            min_revenue: 收入底线（默认0=不设限）。低于此值时回退到基准价。
            **context: 传给 rule_engine.predict() 的情境参数
              (derby, lost_bottom, heavy_home_loss, away_winless,
               saturday, late_season, season_opener, short_rest, midweek)
        """
        # 1. 规则引擎预测总量（硬编码基值，MAE=549）
        predicted_total = predict_attendance(opponent, **context)

        # 动态目标权重：高预测→追收入，低预测→追上座
        # 阈值来自2024-2025数据：P25≈7500, P75≈11000
        if predicted_total >= 11000:
            rw = 0.80  # 收入优先
        elif predicted_total <= 7500:
            rw = 0.20  # 上座优先
        else:
            rw = 0.20 + 0.60 * (predicted_total - 7500) / 3500  # 线性过渡
        aw = 1.0 - rw

        # 2. 对手定价级别（含derby提升/A-/C-降价）
        opp_level = get_pricing_tier(opponent)

        # 3. 获取该级别的基准价
        base_prices = self.price_matrix[opp_level]

        # 4. 按历史份额分配到各zone tier（作为基准需求）
        base_demand = {}
        for zt in ZONE_TIERS:
            base_demand[zt] = predicted_total * self.volume_shares[zt]

        # 5. 逐档优化
        tier_results = {}
        total_revenue = 0.0
        total_attendance = 0.0
        base_revenue = 0.0
        base_attendance = 0.0

        for zt in ZONE_TIERS:
            p0 = base_prices[zt]
            q0 = base_demand[zt]
            eps = self.elasticity[opp_level][zt]
            cap = self.capacities[zt]
            frozen = is_tier_frozen(zt, opp_level)

            if frozen:
                # 锁价：使用基准价
                p_opt = p0
                q_opt = min(q0, cap)
            else:
                # 档位间距：低一级优化价作为下限参考
                lower_price = None
                tier_gap = {"T2":"T1","T3":"T2","T4":"T3","T5":"T4","T6":"T5"}
                if zt in tier_gap:
                    lower_zt = tier_gap[zt]
                    lower_price = tier_results[lower_zt].optimal_price if lower_zt in tier_results else None
                p_opt, q_opt = self._optimize_tier(
                    p0, q0, eps, cap, opp_level, zt, lower_price, rw, aw
                )

            rev = p_opt * q_opt
            rev_base = p0 * min(q0, cap)  # 基准价下的收入

            tier_results[zt] = TierResult(
                zone_tier=zt,
                base_price=p0,
                optimal_price=p_opt,
                predicted_qty=q_opt,
                base_qty=min(q0, cap),
                revenue=rev,
                is_frozen=frozen,
            )
            total_revenue += rev
            total_attendance += q_opt
            base_revenue += rev_base
            base_attendance += min(q0, cap)

        # 6. 收入底线：仅收入优先场（rw>0.7）保收入
        floor = max(base_revenue, min_revenue)
        if total_revenue < floor and rw > 0.7:
            # 回退：至少不低于底线（仅收入优先场）
            total_revenue = floor
            total_attendance = base_attendance
            for zt in ZONE_TIERS:
                tr = tier_results[zt]
                if not tr.is_frozen and tr.optimal_price != tr.base_price:
                    tr.optimal_price = tr.base_price
                    tr.predicted_qty = tr.base_qty
                    tr.revenue = tr.base_price * tr.base_qty

        # 7. 计算目标函数（动态权重 × 按档位加权上座价值）
        attendance_value = sum(
            tr.predicted_qty * self.p_ref.get(zt, tr.base_price)
            for zt, tr in tier_results.items()
        )
        objective = rw * total_revenue + aw * attendance_value

        recommended = {zt: tr.optimal_price for zt, tr in tier_results.items()}

        return OptimizeResult(
            opponent=opponent,
            opponent_level=opp_level,
            predicted_total=predicted_total,
            total_revenue=total_revenue,
            total_attendance=total_attendance,
            base_revenue=base_revenue,
            base_attendance=base_attendance,
            objective_value=objective,
            revenue_weight=rw,
            attendance_weight=aw,
            tiers=tier_results,
            recommended_prices=recommended,
        )

    def _optimize_tier(
        self, p0: float, q0: float, eps: float, cap: float,
        opp_level: str, zt: str, lower_price: float | None = None,
        rw: float = 0.6, aw: float = 0.4
    ) -> tuple[float, float]:
        """对单个zone tier搜索最优价格（动态权重）。"""
        # Zone差异化边界
        min_mult, max_mult = get_zone_bounds(zt, opp_level)

        p_min = max(p0 * min_mult, 50)
        p_max = p0 * max_mult

        # 档位间距保护：不低于低一级优化价的1.10倍
        if lower_price is not None:
            p_min = max(p_min, lower_price * 1.10)

        # 附加约束：不超过上一级对手的基准价
        level_order = {"C": "B", "B": "A", "A": "S", "S": None}
        upper_level = level_order.get(opp_level)
        if upper_level and upper_level in self.price_matrix:
            upper_price = self.price_matrix[upper_level].get(zt, p_max)
            p_max = min(p_max, upper_price)
        if p_min > p_max:
            p_min = p_max - 10  # 保证至少¥10搜索空间

        # 所有档位参与优化（含低弹性档位）
        def objective(p):
            p = float(p[0])
            # 需求函数（恒定弹性）
            if abs(eps) < 0.001:
                q = q0
            else:
                q = q0 * (p / p0) ** (-eps)
            q = min(q, cap)
            q = max(q, 0)

            revenue = p * q
            attendance_value = q * self.p_ref.get(zt, p0)

            # 目标：最大化加权组合
            obj = rw * revenue + aw * attendance_value
            return -obj  # minimize → maximize

        # 从基准价开始搜索
        result = minimize(
            objective,
            x0=[p0],
            bounds=[(p_min, p_max)],
            method='L-BFGS-B',
        )

        p_opt = float(np.clip(result.x[0], p_min, p_max))

        # ── 分层组合策略：低价抢量、高价保收 ──
        # T1=量价锚, T2/T3=弹性区, T4=锁, T5/T6=收入锚
        if not (min_mult == 1.0 and max_mult == 1.0):  # 非完全锁价
            tier_role = {
                'T1': 'volume', 'T2': 'volume', 'T3': 'elastic',
                'T4': 'locked', 'T5': 'revenue', 'T6': 'revenue',
            }.get(zt, 'elastic')

            if tier_role == 'volume':
                # 量价锚：低价抢量（弱队大降，强队微降）
                if rw <= 0.3:
                    target = max(p0 * 0.80, p_min)
                elif rw <= 0.6:
                    target = max(p0 * 0.90, p_min)
                else:
                    target = p0  # 强队不降
                # 保证收入不低于93%
                rev_min = p0 * (0.93 ** (1.0 / max(1.0 - max(eps, 0.05), 0.01)))
                p_opt = max(target, rev_min)
                p_opt = min(p_opt, p0)  # 不涨

            elif tier_role == 'revenue':
                # 高价保收：弱队微涨，强队大涨
                if rw >= 0.7:
                    target = min(p0 * 1.20, p_max)
                elif rw >= 0.4:
                    target = min(p0 * 1.10, p_max)
                else:
                    target = p0  # 弱队不涨
                p_opt = max(target, p0)  # 不降

            elif tier_role == 'elastic':
                # 弹性区：跟随rw线性
                if rw <= 0.3:
                    target = max(p0 * 0.85, p_min)
                elif rw >= 0.7:
                    target = min(p0 * 1.15, p_max)
                else:
                    ratio = 0.85 + 0.30 * (rw - 0.3) / 0.4
                    target = p0 * ratio
                rev_min = p0 * (0.92 ** (1.0 / max(1.0 - max(eps, 0.05), 0.01)))
                p_opt = max(target, rev_min) if target < p0 else target
                p_opt = max(p_min, min(p_max, p_opt))

        # 取整到10元
        p_opt = round(p_opt / 10) * 10
        p_opt = max(p_min, min(p_max, p_opt))

        # 最小调整阈值：变化<5%则保持基准价（降档已绕过此检查的不受影响）
        if abs(p_opt / p0 - 1) < 0.05 and max_mult > 1.0:
            p_opt = p0
            q_opt = min(q0, cap)

        # 计算最优价下的需求
        if abs(eps) < 0.001:
            q_opt = q0
        else:
            q_opt = q0 * (p_opt / p0) ** (-eps)
        q_opt = min(q_opt, cap)
        q_opt = max(q_opt, 0)

        # 降价保护：降价不能减量
        if p_opt < p0:
            q_opt = max(q_opt, q0)

        return p_opt, q_opt

    def print_result(self, result: OptimizeResult):
        """格式化打印优化结果。"""
        print(f"\n{'='*60}")
        print(f"  {result.opponent} ({result.opponent_level}级)")
        print(f"  规则引擎预测: {result.predicted_total:.0f}张")
        print(f"{'='*60}")
        print(f"  {'档位':>6} {'基准价':>8} {'优化价':>8} {'基准量':>8} {'优化量':>8} {'收入':>10} {'状态'}")
        print(f"  {'-'*54}")
        for zt in ZONE_TIERS:
            tr = result.tiers[zt]
            status = "🔒锁" if tr.is_frozen else "🔓"
            print(f"  {zt:>6} ¥{tr.base_price:>7.0f} ¥{tr.optimal_price:>7.0f} "
                  f"{tr.base_qty:>8.0f} {tr.predicted_qty:>8.0f} "
                  f"¥{tr.revenue:>9.0f} {status}")
        print(f"  {'-'*54}")
        print(f"  {'合计':>6} {'':>8} {'':>8} {result.base_attendance:>8.0f} "
              f"{result.total_attendance:>8.0f} ¥{result.total_revenue:>9.0f}")
        print(f"\n  基准收入: ¥{result.base_revenue:,.0f}")
        print(f"  优化收入: ¥{result.total_revenue:,.0f} "
              f"({(result.total_revenue/result.base_revenue - 1)*100:+.1%})")
        print(f"  基准上座: {result.base_attendance:,.0f}张")
        print(f"  优化上座: {result.total_attendance:,.0f}张 "
              f"({(result.total_attendance/result.base_attendance - 1)*100:+.1%})")


# ── 快捷函数 ──

_default_optimizer = DynamicPricingOptimizer(revenue_weight=0.6)


def quick_optimize(opponent: str, **context) -> OptimizeResult:
    """快捷优化：用默认权重(60%收入+40%上座)。"""
    return _default_optimizer.optimize(opponent, **context)


# ── 测试 ──

if __name__ == "__main__":
    opt = DynamicPricingOptimizer(revenue_weight=0.6)

    print("=" * 60)
    print("  测试: 2025赛季典型场景")
    print("=" * 60)

    # S级：申花德比
    r = opt.optimize("上海申花", derby=True, saturday=True)
    opt.print_result(r)

    # A级：山东泰山 周末
    r = opt.optimize("山东泰山", saturday=True)
    opt.print_result(r)

    # B级：天津津门虎 工作日
    r = opt.optimize("天津津门虎", midweek=True)
    opt.print_result(r)

    # C级：大连 赛季末
    r = opt.optimize("大连英博海发", late_season=True, midweek=True)
    opt.print_result(r)
