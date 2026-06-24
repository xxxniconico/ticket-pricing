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

# 历史标定：7天销售周期 D4 ≈ 60% 最终销量
D4_RATIO_DEFAULT = 0.60
# 预警阈值：偏差 > 20% 触发
ALERT_THRESHOLD = 0.20


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

def compute_velocity_correction(predict, d7_actual, d7_ratio=0.85):
    """赛中修正乘数：D7 销速偏离预测时调整下场上座预测。

    如果 D7 实际 / D7 预期 > 1.15，下场比赛上修
    如果 D7 实际 / D7 预期 < 0.85，下场比赛下修

    Args:
        predict: 评级模型预测值
        d7_actual: D7 实际销量
        d7_ratio: D7 通常占最终销量的比例（默认 85%）

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
