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
import math

from src.rule_engine import predict_calibrated as predict_attendance
from src.pricing_v5 import (
    ZONE_TIERS, ZONE_SECTIONS,
    classify_opponent, get_pricing_tier, build_price_matrix, build_elasticity_matrix, get_dynamic_elasticity,
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
    calibration: dict | None = None  # 实时校准信息（LiveCalibrator 填充）
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
        # T4 扩容后手动覆盖 (山东赛后, 1509座)
        self.capacities["T4"] = max(self.capacities.get("T4", 0), 1509)

        # 动态份额：基于 total_predicted 线性回归，每 tier 独立拟合
        # V5.5: 基于 2026 KMeans zone 重映射后 2025-2026 数据重拟合 (n=26)
        # T1 share 随总上座↓（低价区在弱队场次占比更高）
        # T2/T3 share 随总上座↑（中档在强队场次更受欢迎）
        # T4-T6 share 近似常数（区段少，波动小）
        # V8.0: 按对手级别分表 (山东回测修正)
        self._tier_share_baseline = {
            "S": {"T1":0.273,"T2":0.248,"T3":0.320,"T4":0.029,"T5":0.122,"T6":0.008},
            "A": {"T1":0.350,"T2":0.220,"T3":0.270,"T4":0.090,"T5":0.065,"T6":0.005},
            "B": {"T1":0.506,"T2":0.119,"T3":0.253,"T4":0.020,"T5":0.095,"T6":0.006},
            "C": {"T1":0.545,"T2":0.091,"T3":0.249,"T4":0.016,"T5":0.091,"T6":0.008},
        }

        # 同对手2025实际份额（用于反事实，优先于通用基线）
        self._opponent_share_baseline = {
            "成都蓉城": {"T1":0.225,"T2":0.262,"T3":0.349,"T4":0.102,"T5":0.053,"T6":0.008},
            "浙江俱乐部绿城": {"T1":0.352,"T2":0.233,"T3":0.297,"T4":0.019,"T5":0.090,"T6":0.008},
            "浙江": {"T1":0.352,"T2":0.233,"T3":0.297,"T4":0.019,"T5":0.090,"T6":0.008},
            "山东泰山": {"T1":0.262,"T2":0.294,"T3":0.294,"T4":0.054,"T5":0.084,"T6":0.010},
            "河南俱乐部酒祖杜康": {"T1":0.378,"T2":0.222,"T3":0.301,"T4":0.015,"T5":0.078,"T6":0.005},
            "河南": {"T1":0.378,"T2":0.222,"T3":0.301,"T4":0.015,"T5":0.078,"T6":0.005},
            "河南队": {"T1":0.378,"T2":0.222,"T3":0.301,"T4":0.015,"T5":0.078,"T6":0.005},
            "深圳新鹏城": {"T1":0.292,"T2":0.278,"T3":0.286,"T4":0.020,"T5":0.116,"T6":0.008},
            "长春亚泰": {"T1":0.281,"T2":0.279,"T3":0.303,"T4":0.018,"T5":0.111,"T6":0.008},
            "青岛西海岸": {"T1":0.485,"T2":0.122,"T3":0.271,"T4":0.012,"T5":0.101,"T6":0.009},
            "上海申花": {"T1":0.227,"T2":0.308,"T3":0.344,"T4":0.016,"T5":0.100,"T6":0.005},
            "天津津门虎": {"T1":0.221,"T2":0.269,"T3":0.324,"T4":0.049,"T5":0.127,"T6":0.010},
            "武汉三镇": {"T1":0.362,"T2":0.204,"T3":0.308,"T4":0.012,"T5":0.109,"T6":0.005},
            "上海海港": {"T1":0.424,"T2":0.176,"T3":0.271,"T4":0.026,"T5":0.095,"T6":0.007},
            "大连英博海发": {"T1":0.551,"T2":0.091,"T3":0.241,"T4":0.010,"T5":0.102,"T6":0.006},
            "大连英博": {"T1":0.551,"T2":0.091,"T3":0.241,"T4":0.010,"T5":0.102,"T6":0.006},
            "青岛海牛": {"T1":0.518,"T2":0.095,"T3":0.259,"T4":0.011,"T5":0.112,"T6":0.005},
            "梅州客家": {"T1":0.469,"T2":0.174,"T3":0.255,"T4":0.010,"T5":0.087,"T6":0.005},
        }

        self._share_total_adj = {
            "T1": -0.000010, "T2": 0.000010, "T3": 0.000005,
            "T4": 0.000002, "T5": 0.000001, "T6": 0.000000,
        }

        # Reference price for attendance-to-revenue conversion (per-tier, not global)
        # 每档用自身基准价衡量上座价值，使高端区降价也有动力
        self.p_ref = {zt: BASE_PRICES_B[zt] for zt in ZONE_TIERS}

    def _estimate_capacities(self) -> dict[str, float]:
        """估计每zone tier的容量上限（基于2026申花售罄场次 + 2% buffer）。
        
        V5.5: ZONE_SECTIONS改为KMeans按赛季聚类后，旧峰值失效。
        申花2026-03-21为售罄场（~98%上座率），各区销量接近物理上限。
        """
        sellout = {"T1": 3718, "T2": 3914, "T3": 5203, "T4": 453, "T5": 2070, "T6": 115}
        return {zt: int(v / 0.98) + 1 for zt, v in sellout.items()}

    def optimize(self, opponent: str, match_date: str | None = None,
                 min_revenue: float = 0.0, strategy: str = 'auto',
                 pricing_tier_override: str | None = None,
                 opponent_tier_override: str | None = None,
                 capacity_overrides: dict | None = None,
                 **context) -> OptimizeResult:
        """
        为一场比赛优化6档定价。

        Args:
            opponent: 对手名称
            match_date: 比赛日期（用于情境检测）
            min_revenue: 收入底线（默认0=不设限）。低于此值时回退到基准价。
            strategy: 'auto'(默认), 'balanced'(平衡: T1-T3降价拉量, T4-T6涨价补收入)
            **context: 传给 rule_engine.predict() 的情境参数
        """
        # ── 对手级别（动态评分，优先于所有后续计算）──
        from src.classify import classify_opponent_tier
        opp_tier = opponent_tier_override or classify_opponent_tier(opponent, match_date=match_date)

        # 1. 规则引擎预测总量（硬编码基值，MAE=549）
        ctx_with_tier = dict(context)
        ctx_with_tier['opponent_tier_override'] = opp_tier
        # AP 分位浮动：同一级别内按吸引力差异化（2026-08-03 用户确认加入）
        # 用全联赛对手 AP 分布算分位（compute_ap_percentiles 内部按国安主场对手）
        try:
            from dashboard.common.data_cache import compute_ap_percentiles
            from src.csl_context import load_csl_data, get_guoan_matches
            _m, _r, _ = load_csl_data()
            _g = get_guoan_matches(_m)
            _ap_pcts = compute_ap_percentiles(_g, _r)
            ctx_with_tier['ap_pct'] = _ap_pcts.get(opponent)
        except Exception:
            pass
        predicted_total = predict_attendance(opponent, **ctx_with_tier)

        # 动态目标权重：四级分档 (V8.2: 门槛下调, 更平滑过渡)
        if predicted_total >= 10000:
            rw = 0.80  # 收入优先
        elif predicted_total >= 8000:
            rw = 0.55  # 收入倾向
        elif predicted_total >= 6000:
            rw = 0.35  # 上座倾向
        else:
            rw = 0.20  # 上座优先

        # ── 对手级别约束：非德比场次涨价空间受限 ──
        # S级德比可以激进涨价，A级适度，B/C级保守
        # 防止 上海海港 类 case：预测上座高但实际价格弹性大 → 涨价驱客
        tier_rw_cap = {"S": 1.0, "A": 0.75, "B": 0.50, "C": 0.35}
        if rw > tier_rw_cap.get(opp_tier, 1.0):
            rw = tier_rw_cap[opp_tier]
        aw = 1.0 - rw

        # 策略模式：rw≤0.4时自动切换平衡策略（T1-T3降价拉量）
        if strategy == 'balanced' or (strategy == 'auto' and rw <= 0.4):
            strategy_mode = 'balanced'
        else:
            strategy_mode = 'revenue'

        # 反事实场景：覆盖库存容量（用于原库存 vs 新库存对比）
        if capacity_overrides:
            for zt, cap in capacity_overrides.items():
                if zt in self.capacities:
                    self.capacities[zt] = cap

        # 2. 对手定价级别（含derby提升/A-/C-降价）。pricing_tier_override 用于升班马B级模拟
        opp_level = pricing_tier_override or get_pricing_tier(opponent, match_date=match_date)

        # 3. 获取该级别的基准价
        base_prices = self.price_matrix[opp_level]

        # 4. 份额分配（V10: 单一事实源 src/pricing_v5.v10_volume_shares，
        #   含暑期 t45=0.15 分支 + T4 内部占比三点分段；2026-08-23 云南样本落地）
        P = predicted_total
        from src.pricing_v5 import v10_volume_shares
        volume_shares = v10_volume_shares(P, summer=context.get("summer", False))

        base_demand = {}
        for zt in ZONE_TIERS:
            base_demand[zt] = predicted_total * volume_shares[zt]

        # 容量约束 + 溢出重分配（V8.1：防止高需求时份额超容量）
        for _ in range(3):
            overflow = 0.0
            remaining_tiers = []
            for zt in ZONE_TIERS:
                if base_demand[zt] > self.capacities[zt]:
                    overflow += base_demand[zt] - self.capacities[zt]
                    base_demand[zt] = self.capacities[zt]
                else:
                    remaining_tiers.append(zt)
            if overflow <= 1 or not remaining_tiers:
                break
            total_rem_cap = sum(self.capacities[zt] - base_demand[zt] for zt in remaining_tiers)
            if total_rem_cap <= 0:
                break
            for zt in remaining_tiers:
                share = (self.capacities[zt] - base_demand[zt]) / total_rem_cap
                base_demand[zt] += overflow * share

        # 5. 逐档优化
        tier_results = {}
        total_revenue = 0.0
        total_attendance = 0.0
        base_revenue = 0.0
        base_attendance = 0.0

        # H2 强需求信号: 允许 volume tier 微涨 + T5/T6 更激进
        strong_demand = context.get("midseason_restart", False) or context.get("summer", False)

        for zt in ZONE_TIERS:
            p0 = base_prices[zt]
            q0 = base_demand[zt]
            eps = get_dynamic_elasticity(zt, p0) if zt == "T5" else self.elasticity[opp_level][zt]
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

                # T3→T4 间距：T3 不能太接近 T4，至少留 18% 间距
                upper_bound_hint = None
                if zt == "T3" and "T4" in base_prices:
                    upper_bound_hint = base_prices["T4"] / 1.18

                p_opt, q_opt = self._optimize_tier(
                    p0, q0, eps, cap, opp_level, zt, lower_price, rw, aw, upper_bound_hint, strategy_mode, strong_demand
                )

            rev = p_opt * q_opt
            rev_base = p0 * min(q0, cap)  # optimized baseline (capped for realistic comparison)

            tier_results[zt] = TierResult(
                zone_tier=zt,
                base_price=p0,
                optimal_price=p_opt,
                predicted_qty=q_opt,
                base_qty=q0,  # uncapped demand, matches predict_calibrated total
                revenue=rev,
                is_frozen=frozen,
            )
            total_revenue += rev
            total_attendance += q_opt
            base_revenue += rev_base
            base_attendance += min(q0, cap)  # capped baseline (realistic comparison)

        # 6. 收入策略安全阀：预测偏低或掉量>3% → 降级均衡
        # V5.4: pred_floor 基于实际数据中位数重标定 (B~9000, C~5500)
        # 情境修正: midseason_restart×0.80, summer×0.85 (暑假需求置信度高)
        if strategy_mode == 'revenue':
            att_loss_pct = (base_attendance - total_attendance) / base_attendance if base_attendance > 0 else 0
            tier_pred_floor = {"S": 11000, "A": 10500, "B": 9000, "C": 6000}
            pred_floor = tier_pred_floor.get(opp_tier, 10000)
            if context.get("midseason_restart"):
                pred_floor = int(pred_floor * 0.80)
            elif context.get("summer"):
                pred_floor = int(pred_floor * 0.85)
            if predicted_total < pred_floor or att_loss_pct > 0.03:
                return self.optimize(opponent, match_date=match_date,
                                     min_revenue=min_revenue, strategy='balanced', **context)

        # 7. 平衡策略跨档补贴检查：收入低于基准90%时，T4-T6涨价补偿
        if strategy_mode == 'balanced' and total_revenue < base_revenue * 0.90:
            shortfall = base_revenue * 0.90 - total_revenue
            revenue_tiers = ['T4', 'T5', 'T6']
            rev_sum = sum(tier_results[zt].revenue for zt in revenue_tiers)
            if rev_sum > 0:
                tier_eps = {zt: self.elasticity[opp_level][zt] for zt in revenue_tiers}
                for zt in revenue_tiers:
                    tr = tier_results[zt]
                    if tr.is_frozen:
                        continue
                    share = tr.revenue / rev_sum
                    extra_needed = shortfall * share
                    eps_z = tier_eps[zt]
                    for _ in range(10):
                        if extra_needed <= 0:
                            break
                        p_try = round(tr.optimal_price * 1.05 / 10) * 10
                        if p_try > tr.base_price * 1.25:
                            p_try = round(tr.base_price * 1.25 / 10) * 10
                        if p_try <= tr.optimal_price:
                            break
                        q_try = tr.base_qty * (p_try / tr.base_price) ** (-eps_z) if abs(eps_z) >= 0.001 else tr.base_qty
                        q_try = min(q_try, self.capacities[zt])
                        rev_try = p_try * q_try
                        extra = rev_try - tr.revenue
                        if extra > 0:
                            tr.optimal_price = p_try
                            tr.predicted_qty = q_try
                            tr.revenue = rev_try
                            total_revenue += extra
                            extra_needed -= extra
                        else:
                            break

        # 7. 收入影响约束：增收/减收不足 ¥5,000 或 0.5% → 不调，维持价格稳定形象
        rev_impact = total_revenue - base_revenue
        if abs(rev_impact) < max(base_revenue * 0.005, 5000):
            for zt in ZONE_TIERS:
                tr = tier_results[zt]
                if tr.optimal_price != tr.base_price:
                    tr.optimal_price = tr.base_price
                    tr.predicted_qty = tr.base_qty
                    tr.revenue = tr.base_price * tr.base_qty
            total_revenue = base_revenue
            total_attendance = base_attendance

        # 7. 收入底线：仅收入优先场（rw>0.7）保收入
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
        rw: float = 0.6, aw: float = 0.4, upper_bound_hint: float | None = None,
        strategy_mode: str = 'revenue', strong_demand: bool = False
    ) -> tuple[float, float]:
        """对单个zone tier搜索最优价格（动态权重）。"""
        # Zone差异化边界
        min_mult, max_mult = get_zone_bounds(zt, opp_level)

        p_min = max(p0 * min_mult, 50)
        p_max = p0 * max_mult

        # 档位间距保护：不低于低一级优化价的1.10倍
        if lower_price is not None:
            p_min = max(p_min, lower_price * 1.10)

        # T3→T4 间距：T3 不能太接近 T4
        if upper_bound_hint is not None:
            p_max = min(p_max, upper_bound_hint)

        # 跨级约束：不超过上一级基准价的 95%（至少留 5% 级差）
        level_order = {"S_Cminus": "S_C", "S_C": "S_B", "S_B": "S_A", "S_A": "S_S", "S_S": None,
                       "S_Aminus": "S_A"}
        upper_level = level_order.get(opp_level)
        if upper_level and upper_level in self.price_matrix:
            upper_price = self.price_matrix[upper_level].get(zt, p_max)
            p_max = min(p_max, upper_price / 1.05)  # 5% 级差底线
        if p_min > p_max:
            p_min = p_max - 10

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

        # ── 分层组合策略 ──
        # revenue模式: T1/T2量价锚, T3/T4弹性区, T5/T6收入锚
        # balanced模式: T1-T3降价拉量, T4-T6涨价补收入（跨档补贴）
        if not (min_mult == 1.0 and max_mult == 1.0):  # 非完全锁价
            tier_role = {
                'T1': 'volume', 'T2': 'volume', 'T3': 'elastic',
                'T4': 'elastic', 'T5': 'revenue', 'T6': 'revenue',
            }.get(zt, 'elastic')

            if strategy_mode == 'balanced':
                # 平衡策略：降幅与弹性挂钩，高弹性多降、低弹性少降
                # V5.4: 最大降幅从22%收紧至15% (22%=清仓逻辑, 偏离"平衡"本意)
                if tier_role == 'volume':
                    # T1,T2: 弹性驱动降价 (eps越大越敏感,降越多)
                    cut_pct = min(0.15, abs(eps) * 0.85)  # eps=0.25→21%→cap@15%, eps=0.10→8.5%
                    p_opt = max(p_min, p0 * (1 - cut_pct))
                    p_opt = min(p_opt, p0)  # 不涨
                elif tier_role == 'elastic' and zt == 'T3':
                    # T3: 弹性驱动,降幅略小于volume
                    cut_pct = min(0.12, abs(eps) * 0.65)
                    p_opt = max(p_min, p0 * (1 - cut_pct))
                    p_opt = min(p_opt, p0)
                elif tier_role == 'elastic' and zt == 'T4':
                    # T4: 低弹性可涨,高弹性微降
                    if abs(eps) < 0.15:
                        cap_up = min(1.10, 1 + (0.15 - abs(eps)) * 1.2)
                        p_opt = min(p0 * cap_up, p_max)
                        p_opt = max(p_opt, p0)  # 不降
                    else:
                        cut_pct = min(0.10, abs(eps) * 0.50)
                        p_opt = max(p_min, p0 * (1 - cut_pct))
                        p_opt = min(p_opt, p0)
                elif tier_role == 'revenue':
                    # T5,T6: 弹性驱动涨价 (低弹性可多涨)
                    cap_up = 1.08 + max(0, (0.25 - abs(eps))) * 0.70  # eps=0.10→1.18, eps=0.25→1.08
                    cap_up = min(cap_up, 1.22)
                    p_opt = min(p0 * cap_up, p_max)
                    p_opt = max(p_opt, p0)  # 不降
            else:
                # revenue模式（默认）：低预测降量价、高预测涨收入
                if tier_role == 'volume':
                    if rw <= 0.3:
                        target = max(p0 * 0.80, p_min)
                    elif rw <= 0.6:
                        target = max(p0 * 0.90, p_min)
                    else:
                        target = p0  # 强队不降
                    rev_min = p0 * (0.93 ** (1.0 / max(1.0 - max(eps, 0.05), 0.01)))
                    # V8.1: 基于容量紧张度允许涨价（原: p_opt = max(target, rev_min) + min(p_opt, p0) 双重锁定）
                    demand_ratio = q0 / max(cap, 1)
                    if demand_ratio > 0.85 and rw >= 0.6:
                        # 供需紧张 + 收入倾向 → scipy结果驱动，target为底，动态cap_up为顶
                        cap_up = min(1.05 + (demand_ratio - 0.85) * 0.40, 1.12)
                        p_opt = max(p_opt, target)  # floor: 不降
                        p_opt = min(p_opt, round(p0 * cap_up / 10) * 10)  # ceiling: 动态上限
                    else:
                        # V5.4 H2: 保留scipy结果，target为底，vol_cap为顶
                        vol_cap = p0 * 1.05 if strong_demand else p0
                        p_opt = max(p_opt, max(target, rev_min))  # floor
                        p_opt = min(p_opt, vol_cap)                # ceiling

                elif tier_role == 'revenue':
                    if eps >= 0.30:
                        cap_up = 1.20
                    elif eps >= 0.20:
                        cap_up = 1.15
                    else:
                        cap_up = 1.12
                    if rw >= 0.7:
                        target = min(p0 * cap_up, p_max)
                    elif rw >= 0.4:
                        # V5.4 H2: 强需求场次 T5/T6 涨价上限放宽
                        tier_ceil = 1.15 if strong_demand else 1.10
                        target_mult = cap_up if strong_demand else cap_up - 0.05
                        target = min(p0 * min(target_mult, tier_ceil), p_max)
                    else:
                        target = p0  # 弱队不涨
                    p_opt = max(target, p0)  # 不降

                elif tier_role == 'elastic':
                    soft_cap = 1.15 if rw >= 0.7 else (1.08 if rw >= 0.4 else 1.05)
                    if zt == 'T4':
                        soft_cap = min(soft_cap, 1.087)
                    p_opt = min(p_opt, round(p0 * soft_cap / 10) * 10)

        # 先夹紧边界，再取整到10元（边界也取整以杜绝夹紧后跳出）
        p_min = math.ceil(p_min / 10) * 10
        p_max = math.floor(p_max / 10) * 10
        if p_min > p_max:
            p_min = p_max
        p_opt = max(p_min, min(p_max, p_opt))
        p_opt = round(p_opt / 10) * 10
        p_opt = max(p_min, min(p_max, p_opt))

        # 最小调整阈值：变化<3%则保持基准价
        if abs(p_opt / p0 - 1) < 0.03 and max_mult > 1.0:
            p_opt = p0
            q_opt = min(q0, cap)

        # 档位级调价意义约束
        # 涨价：该档增量收入 ≥ ¥10,000 才值得调（维持价格稳定形象）
        # 降价：该档增量数量 ≥ 100 人才值得调（牺牲收入换量必须有实际效果）
        if p_opt != p0:
            q_test = q0 * (p_opt / p0) ** (-eps) if abs(eps) >= 0.001 else q0
            q_test = min(q_test, cap)
            q_test = max(q_test, 0)
            if p_opt < p0:
                q_test = max(q_test, q0)
            rev_old = p0 * min(q0, cap)
            rev_new = p_opt * q_test
            if p_opt > p0:
                # 涨价：增量收入不足¥10,000 → 不调
                if rev_new - rev_old < 10000:
                    p_opt = p0
                    q_opt = min(q0, cap)
            elif p_opt < p0:
                # 降价：增量不足100人 且 增幅不足2% → 不调
                delta_q = q_test - min(q0, cap)
                delta_pct = delta_q / max(q0, 1)
                if delta_q < 100 and delta_pct < 0.02:
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
