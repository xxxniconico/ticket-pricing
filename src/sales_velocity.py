"""销速交叉验证 + 赛中修正乘数 V1.0

基于 D4 销速曲线对评级预测做交叉验证，>20% 偏差触发人工审查。
赛中修正乘数：D7 最终销速偏离预测时调整下场上座预测。

Tasks: 1.5 (Cross Validation), 1.6 (Mid-game Correction)
"""
from __future__ import annotations

import json, os
from pathlib import Path

import numpy as np, pandas as pd

_DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "processed"
_VELOCITY_ALERTS_PATH = _DATA_DIR / "velocity_alerts.json"

# ── 销速标定（2026-10-20 重标，依据原始大麦导出的支付时间；勿用旧值 0.60/0.85）──
# 口径：Dk = 第 k 个销售日累计占比（整天近似），D7/末日 = 比赛日 = 100%。
# 样本：CSL 主场 4 场非德比（浙江 8/1、深圳 8/7、云南 8/22、青岛西海岸 10/18，均 7 天窗口），
#       取中位数；山东 7/4 为德比爆炸型（D1 68.5%）、浦项 9/15 为亚冠后置型（D1 6.4%），排除。
#   场次         D1     D2     D3     D4     D5     D6    D7
#   浙江         35.8   50.0   61.0   70.3   82.8   95.2  100
#   深圳新鹏城    20.5   34.7   50.3   62.4   76.7   95.0  100
#   云南玉昆      29.9   41.1   53.3   67.5   78.6   94.6  100
#   青岛西海岸    43.8   55.1   65.3   74.3   84.0   94.7  100
#   中位         32.9   45.2   57.5   68.9   80.7   94.9  100
VELOCITY_CURVE = {
    1: 0.329, 2: 0.452, 3: 0.575, 4: 0.689, 5: 0.807, 6: 0.949, 7: 1.000,
}
# D1 的场间离散极大（20.5%-43.8%），单点值只作先验，必须用当日实测覆盖：
VELOCITY_D1_RANGE = (0.20, 0.44)
# D4 累计占比（原 0.60 偏低 8.9pp；4 场实测 62.4-74.3，中位 68.9）
D4_RATIO_DEFAULT = 0.69
# D-1（赛前一天）累计占比 ≈ 94.9%（原 0.85 与实际不符：比赛日当天即 100%）
D1_TO_MATCHDAY_RATIO = 0.949
# 预警阈值：偏差 > 20% 触发
ALERT_THRESHOLD = 0.20


def expected_cum_ratio(day, ratio=None):
    """第 day 个销售日的经验累计占比（无实测时的先验值）。

    Args:
        day: 第几个销售日（1 = 开票首日）；超出手表范围时按末日封顶 1.0。
        ratio: 可选覆盖（如按 D4 标定值反推）。
    """
    if ratio is not None:
        return ratio
    if day <= 0:
        return 0.0
    return VELOCITY_CURVE.get(min(int(day), 7), 1.0)


# ============================================================
# Task 1.5 - Sales Velocity Cross Validation
# ============================================================

def predict_final_from_d4(d4_tickets, d4_ratio=D4_RATIO_DEFAULT):
    """基于 D4 累计销量预测最终销量。

    最终销量 = D4 / d4_ratio
    """
    if d4_ratio <= 0:
        return int(d4_tickets)
    return int(d4_tickets / d4_ratio)


def check_velocity_alert(predict, d4_tickets, d4_ratio=D4_RATIO_DEFAULT,
                         threshold=ALERT_THRESHOLD):
    """检查销速与评级预测的偏差，返回预警信息。

    Returns:
        {
            'alert': bool,
            'direction': 'overestimate' | 'underestimate',
            'predict': int,
            'd4_predicted': int,
            'deviation_pct': float,
            'action': str,
        }
    """
    d4_predicted = predict_final_from_d4(d4_tickets, d4_ratio)
    if d4_predicted <= 0:
        return {"alert": False, "direction": "", "predict": predict,
                "d4_predicted": d4_predicted, "deviation_pct": 0.0, "action": ""}

    deviation = (predict - d4_predicted) / d4_predicted

    alert = abs(deviation) > threshold
    direction = "overestimate" if deviation > 0 else "underestimate"

    if deviation > threshold:
        action = "倾向降级：高估风险大，建议下调对手档位"
    elif deviation < -threshold:
        action = "倾向保持：低估可接受，低价风险小"
    else:
        action = "无偏差，维持当前档位"

    return {
        "alert": alert,
        "direction": direction,
        "predict": predict,
        "d4_predicted": d4_predicted,
        "deviation_pct": round(deviation * 100, 1),
        "action": action,
    }


def save_velocity_alert(match_id, alert_info):
    """保存销速预警到日志文件。"""
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    alerts = []
    if _VELOCITY_ALERTS_PATH.exists():
        with open(_VELOCITY_ALERTS_PATH, "r") as f:
            alerts = json.load(f)
    alerts.append({"match_id": match_id, **alert_info})
    with open(_VELOCITY_ALERTS_PATH, "w") as f:
        json.dump(alerts, f, ensure_ascii=False, indent=2)


# ============================================================
# Task 1.6 - Mid-game Sales Velocity Correction Multiplier
# ============================================================

def compute_velocity_correction(predict, d7_actual, d7_ratio=D1_TO_MATCHDAY_RATIO):
    """赛中修正乘数：赛前节点实际销量偏离预期时调整下场上座预测（threshold 见 docstring 下方逻辑）。

    若 实际 / 预期 > 1.15 → 下场上修；< 0.85 → 下场下修。

    Args:
        predict: 评级模型预测值
        d7_actual: D7 实际销量
        d7_ratio: 该节点累计销量占最终的比例。默认取「赛前一天 ≈ 94.9%」
                  （2026-10-20 重标；原 85% 与实际不符——比赛日当天销售即到 100%）

    Returns:
        correction_multiplier: 修正乘数 (0.80-1.20)，1.0 表示无修正
    """
    d7_expected = predict * d7_ratio
    if d7_expected <= 0:
        return 1.0

    ratio = d7_actual / d7_expected
    # 平滑修正：每偏离 10%，修正 5%
    correction = 1.0 + (ratio - 1.0) * 0.5
    return max(0.80, min(1.20, correction))


def apply_velocity_correction(base_predict, velocity_multiplier):
    """应用销速修正乘数到基础预测。

    Args:
        base_predict: 基础预测值（来自评级模型）
        velocity_multiplier: compute_velocity_correction 的输出

    Returns:
        corrected_predict: 修正后的预测值
    """
    return base_predict * velocity_multiplier
