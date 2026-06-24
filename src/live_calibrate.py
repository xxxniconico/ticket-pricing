"""
实时预售校准模块 — 融合规则引擎预测与预售数据

核心思路:
  规则引擎预测 (t-7天准确) → 预售数据 (t-1天准确) → 加权融合

用法:
  from src.live_calibrate import LiveCalibrator
  cal = LiveCalibrator()
  
  # 记录预售快照
  cal.snapshot(opponent="河南", partial_qty=7200, hours_remaining=24)
  
  # 获取校准后预测
  adjusted = cal.blend_prediction(rule_pred=10640, partial_qty=7200, hours_remaining=24)
  # → ~8,310（规则10,640 × 30% + 节奏推算7,310 × 70%）
  
  # 一站式：规则引擎 + 校准 + 优化
  result = cal.calibrated_optimize(opponent="河南", partial_qty=7200, 
                                    hours_remaining=24, saturday=True)

快照存储: data/processed/sales_snapshots.json
  积累3+场数据后自动学习 pace_ratio 曲线
"""

from __future__ import annotations
import sys, json, os, math
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field
import numpy as np

# Ensure ticket-pricing root is on path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.rule_engine import predict_calibrated as rule_predict
from src.dynamic_optimizer import DynamicPricingOptimizer, OptimizeResult

# ── 默认 pace_ratio: 距截止时间 → 预计已完成销售比例 ──
# 无历史数据时使用保守默认值
DEFAULT_PACE = {
    168: 0.25,  # T-7天: 25%
    120: 0.35,  # T-5天: 35%
    72:  0.50,  # T-3天: 50%
    48:  0.65,  # T-2天: 65%
    36:  0.72,  # T-1.5天: 72%
    24:  0.82,  # T-1天: 82%
    18:  0.87,  # T-0.75天: 87%
    12:  0.91,  # T-0.5天: 91%
    6:   0.95,  # T-6h: 95%
    3:   0.97,  # T-3h: 97%
    0:   1.00,  # 截止
}

SNAPSHOT_PATH = ROOT / "data" / "processed" / "sales_snapshots.json"

# 校准基值计算时剥离的乘数（timing + 战绩情境）
_CALIB_STRIP_KEYS = frozenset({
    "saturday", "midweek", "late_season", "season_opener", "short_rest", "summer",
    "away_winless", "away_winless_losses", "consecutive_home_losses", "heavy_home_loss", "derby",
    "midseason_restart", "top3_form",
})

# 最小数据量才能用学习曲线
MIN_SNAPSHOTS_FOR_LEARNING = 3


def _load_snapshots() -> list[dict]:
    if not SNAPSHOT_PATH.exists():
        return []
    with open(SNAPSHOT_PATH) as f:
        return json.load(f)


def _save_snapshots(data: list[dict]):
    SNAPSHOT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(SNAPSHOT_PATH, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


class LiveCalibrator:
    """实时预售校准器。

    两个关键函数:
      - pace_ratio(hours):  距截止 → 已完成比例
      - blend_prediction():  规则引擎 × α + 预售推算 × (1-α)
    """

    def __init__(self, pace_curve: dict[int, float] | None = None):
        self.pace = pace_curve or DEFAULT_PACE.copy()
        self._learned = False
        self._try_learn()

    # ── 公开 API ──

    def snapshot(self, opponent: str, partial_qty: int, hours_remaining: float,
                 match_date: str = "", final_qty: int | None = None):
        """记录预售快照。比赛结束后传入 final_qty 补全。"""
        snapshots = _load_snapshots()
        # 查找是否已有同场比赛+同一时间点的快照
        existing = None
        for s in snapshots:
            if (s.get("opponent") == opponent and s.get("match_date") == match_date
                and abs(s.get("hours_remaining", 0) - hours_remaining) < 1):
                existing = s
                break

        entry = {
            "opponent": opponent,
            "match_date": match_date,
            "recorded_at": datetime.now().isoformat(),
            "partial_qty": partial_qty,
            "hours_remaining": hours_remaining,
        }
        if final_qty is not None:
            entry["final_qty"] = final_qty
            entry["pace_ratio"] = partial_qty / final_qty if final_qty > 0 else 1.0

        if existing:
            existing.update(entry)
        else:
            snapshots.append(entry)

        _save_snapshots(snapshots)
        self._try_learn()

    def estimate_final(self, partial_qty: int, hours_remaining: float) -> float:
        """从预售量推算最终销量。"""
        ratio = self.pace_ratio(hours_remaining)
        if ratio <= 0:
            return partial_qty
        return partial_qty / ratio

    def blend_prediction(self, rule_pred: float, partial_qty: int,
                         hours_remaining: float) -> float:
        """融合规则引擎预测和预售推算。

        α = 规则引擎权重，随比赛临近递减:
          T-168h: α=1.0  (全部依赖规则)
          T-72h:  α=0.7
          T-24h:  α=0.3
          T-0h:   α=0.0  (全部依赖预售)
        """
        live_est = self.estimate_final(partial_qty, hours_remaining)
        alpha = self._blend_alpha(hours_remaining)
        blended = alpha * rule_pred + (1 - alpha) * live_est
        return max(blended, partial_qty)  # 不能低于已售

    def calibrated_optimize(self, opponent: str,
                            partial_qty: int | None = None,
                            hours_remaining: float = 168,
                            min_revenue: float = 0.0,
                            **context) -> OptimizeResult:
        """一站式：规则引擎预测 → 预售校准 → 动态权重优化。

        Args:
            opponent: 对手名
            partial_qty: 当前预售量（None=不使用校准）
            hours_remaining: 距销售截止小时数
            min_revenue: 收入底线
            **context: 传给 rule_engine 的情境参数
        """
        # 1. 规则引擎预测
        rule_pred = rule_predict(opponent, **context)

        # 2. 预售校准（如果有预售数据）
        live_est = None
        cal_factor = 1.0
        alpha = 1.0
        if partial_qty is not None and partial_qty > 0:
            # 用不带 Saturday 乘数的纯基值来做校准修正
            context_no_cal = {k: v for k, v in context.items()
                             if k not in _CALIB_STRIP_KEYS}
            base_only = rule_predict(opponent, **context_no_cal)
            
            live_est = self.estimate_final(partial_qty, hours_remaining)
            
            # 校准因子 = 预售推算 / 基值预测
            if base_only > 0:
                cal_factor = live_est / base_only
                # 限制校准幅度（不超过 ±40%）
                cal_factor = max(0.6, min(1.4, cal_factor))
            else:
                cal_factor = 1.0
            
            # 融合预测
            alpha = self._blend_alpha(hours_remaining)
            blended_pred = alpha * rule_pred + (1 - alpha) * live_est
            blended_pred = max(blended_pred, partial_qty)
        else:
            blended_pred = rule_pred
            cal_factor = 1.0

        # 3. 动态目标权重（基于校准后预测）
        if blended_pred >= 11000:
            rw = 0.80
        elif blended_pred <= 7500:
            rw = 0.20
        else:
            rw = 0.20 + 0.60 * (blended_pred - 7500) / 3500

        # 4. 优化
        opt = DynamicPricingOptimizer(revenue_weight=rw)
        result = opt.optimize(opponent, min_revenue=min_revenue, **context)

        # 附加校准信息
        result.revenue_weight = rw
        result.attendance_weight = 1.0 - rw
        result.calibration = {
            "rule_pred": rule_pred,
            "live_estimate": live_est if partial_qty else None,
            "blended_pred": blended_pred,
            "cal_factor": cal_factor,
            "blend_alpha": alpha,
            "partial_qty": partial_qty,
            "hours_remaining": hours_remaining,
        }

        return result

    # ── 内部 ──

    def pace_ratio(self, hours_remaining: float) -> float:
        """距截止小时数 → 预计已完成销售比例。"""
        hours = sorted(self.pace.keys())
        if hours_remaining <= hours[0]:
            return self.pace[hours[0]]
        if hours_remaining >= hours[-1]:
            return self.pace[hours[-1]]
        # 线性插值
        for i in range(len(hours) - 1):
            if hours[i] <= hours_remaining <= hours[i + 1]:
                t = (hours_remaining - hours[i]) / (hours[i + 1] - hours[i])
                return self.pace[hours[i]] + t * (self.pace[hours[i + 1]] - self.pace[hours[i]])
        return 1.0

    def _blend_alpha(self, hours_remaining: float) -> float:
        """规则引擎权重 α: 随比赛临近从 1.0 降到 0.0。"""
        if hours_remaining >= 168:
            return 1.0
        if hours_remaining <= 0:
            return 0.0
        # 指数衰减: α = exp(-k * (168 - hours))
        # 168h→1.0, 72h→0.7, 24h→0.3, 0h→0.0
        k = -math.log(0.3) / (168 - 24)  # 24h时α=0.3
        alpha = math.exp(-k * (168 - hours_remaining))
        return max(0.0, min(1.0, alpha))

    def _try_learn(self):
        """尝试从历史快照学习 pace_ratio 曲线。"""
        snapshots = _load_snapshots()
        # 只使用有 final_qty 的快照
        complete = [s for s in snapshots if s.get("final_qty") and s.get("hours_remaining") is not None]
        if len(complete) < MIN_SNAPSHOTS_FOR_LEARNING:
            return

        # 按 hours_remaining 分组取中位数
        from collections import defaultdict
        by_hour = defaultdict(list)
        for s in complete:
            hr = s["hours_remaining"]
            ratio = s["partial_qty"] / s["final_qty"]
            by_hour[round(hr / 6) * 6].append(ratio)  # 按6小时间隔分组

        learned = {}
        for hr in sorted(by_hour.keys()):
            ratios = by_hour[hr]
            learned[hr] = float(np.median(ratios))

        if learned:
            # 确保 0→1.0, 最大值→合理值
            learned[0] = 1.0
            self.pace = learned
            self._learned = True


# ── 便捷函数 ──

_default_cal = LiveCalibrator()


def quick_calibrate(opponent: str, partial_qty: int | None = None,
                    hours_remaining: float = 168, **context) -> OptimizeResult:
    """快捷校准优化。"""
    return _default_cal.calibrated_optimize(
        opponent, partial_qty=partial_qty,
        hours_remaining=hours_remaining, **context
    )


def record_snapshot(opponent: str, partial_qty: int, hours_remaining: float,
                    match_date: str = "", final_qty: int | None = None):
    """记录预售快照。"""
    _default_cal.snapshot(opponent, partial_qty, hours_remaining,
                          match_date, final_qty)


# ── 测试 ──
if __name__ == "__main__":
    cal = LiveCalibrator()

    # 模拟：河南 vs 国安，周六，T-24h 预售 7,200
    result = cal.calibrated_optimize(
        "河南", partial_qty=7200, hours_remaining=24,
        saturday=True
    )

    print("=" * 60)
    print("  河南 (C1级) | 周六 | T-24h预售 7,200")
    print("=" * 60)
    print(f"  规则引擎预测: {result.calibration['rule_pred']:.0f}")
    print(f"  预售推算最终: {result.calibration['live_estimate']:.0f}")
    print(f"  融合预测:     {result.calibration['blended_pred']:.0f}")
    print(f"  校准因子:     {result.calibration['cal_factor']:.2f}")
    print(f"  混合权重α:    {result.calibration['blend_alpha']:.2f}")
    print(f"  收入权重rw:   {result.revenue_weight:.2f}")
    print(f"  优化收入:     ¥{result.total_revenue/10000:.1f}万")
    print(f"  基准收入:     ¥{result.base_revenue/10000:.1f}万")
    print(f"  收入变化:     {(result.total_revenue/result.base_revenue-1)*100:+.1f}%")
