"""
滚动校准层：每场2026赛后更新校准系数，平滑V4预测偏差。

机制: cal_new = α × (actual/pred) + (1-α) × cal_old
     其中 α=0.3, cal初始=1.0

存储: data/processed/calibration_log.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

_CAL_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "calibration_log.json")
_ALPHA = 0.3  # EMA 平滑系数


def _load_log() -> dict:
    """加载校准日志。"""
    if not os.path.exists(_CAL_FILE):
        return {"factor": 1.0, "alpha": _ALPHA, "history": []}
    with open(_CAL_FILE) as f:
        return json.load(f)


def _save_log(log: dict):
    """保存校准日志。"""
    os.makedirs(os.path.dirname(_CAL_FILE), exist_ok=True)
    with open(_CAL_FILE, "w") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def get_calibration_factor() -> float:
    """获取当前校准系数。"""
    return float(_load_log().get("factor", 1.0))


def update_calibration(match_id: str, v4_pred: float, actual: float) -> float:
    """一场比赛后更新校准系数。

    Args:
        match_id: 比赛标识 (如 "2026-05-15 青岛海牛")
        v4_pred: V4模型预测散票数
        actual: 实际散票销量

    Returns:
        更新后的校准系数
    """
    log = _load_log()
    old_factor = float(log.get("factor", 1.0))

    if actual <= 0 or v4_pred <= 0:
        return old_factor

    match_ratio = actual / v4_pred
    new_factor = _ALPHA * match_ratio + (1 - _ALPHA) * old_factor
    new_factor = round(float(new_factor), 4)

    # 防止极端值
    new_factor = max(0.3, min(3.0, new_factor))

    log["factor"] = new_factor
    log["history"].append({
        "match_id": match_id,
        "v4_pred": round(float(v4_pred), 0),
        "actual": round(float(actual), 0),
        "ratio": round(float(match_ratio), 4),
        "factor_after": new_factor,
        "factor_before": round(float(old_factor), 4),
    })
    _save_log(log)

    return new_factor


def calibrate_prediction(v4_pred: float) -> float:
    """对V4预测应用校准系数。"""
    return v4_pred * get_calibration_factor()


def get_calibration_history() -> pd.DataFrame:
    """返回校准历史 DataFrame。"""
    log = _load_log()
    if not log.get("history"):
        return pd.DataFrame()
    return pd.DataFrame(log["history"])


def reset_calibration():
    """重置校准日志（谨慎使用）。"""
    _save_log({"factor": 1.0, "alpha": _ALPHA, "history": []})


# 用已有2026数据初始化校准
def _init_from_existing():
    """从已有2026数据初始化校准因子。"""
    try:
        base = os.path.dirname(__file__)
        parquet = os.path.join(base, "..", "data", "processed", "all_unified.parquet")
        if not os.path.exists(parquet):
            return

        all_data = pd.read_parquet(parquet)
        all_data["数量"] = pd.to_numeric(all_data["数量"])
        all_data["实际支付价格"] = pd.to_numeric(all_data["实际支付价格"])
        all_data["is_home"] = all_data["is_home"] == "True"
        all_data["match_date_dt"] = pd.to_datetime(all_data["match_date"])

        csl_2026 = all_data[
            (all_data["competition"] == "CSL")
            & (all_data["is_home"] == True)
            & (all_data["is_bundle"] == False)
            & (all_data["is_partial"] == False)
            & (all_data["match_date"].str.startswith("2026"))
        ]

        if csl_2026.empty:
            return

        from src.data_feeds import (
            get_opponent_rank_2025,
            lost_to_bottom_recently,
            recent_form_before_match,
        )
        from src.classify import DERBY_RIVALS
        from src.calibrate import build_attendance_model_v4, predict_attendance_v4

        m4 = build_attendance_model_v4()
        match_ids = sorted(csl_2026["match_id"].unique())

        # Reset
        reset_calibration()

        for mid in match_ids:
            m = csl_2026[csl_2026["match_id"] == mid]
            actual = int(m["数量"].sum())
            md = m["match_date_dt"].iloc[0]
            opp = str(m["opponent"].iloc[0])

            form = recent_form_before_match(md, n=5)
            lost = lost_to_bottom_recently(md)
            rank = int(get_opponent_rank_2025(opp))
            derby = opp in DERBY_RIVALS
            weekend = md.weekday() >= 5

            other = csl_2026[csl_2026["match_id"] != mid]
            diffs = abs((other["match_date_dt"] - md).dt.days)
            is_double = bool((diffs <= 4).any()) if len(other) > 0 else False

            pred = predict_attendance_v4(
                recent_form_5=form,
                lost_to_bottom_recent=lost,
                opponent_rank=rank,
                is_derby=derby,
                is_weekend=weekend,
                is_double_matchweek=is_double,
                model=m4,
            )

            update_calibration(mid, pred, actual)

        factor = get_calibration_factor()
        print(f"✅ 校准层初始化完成: factor={factor:.4f} (基于{len(match_ids)}场2026数据)")
        return factor
    except Exception as e:
        print(f"⚠️ 校准初始化跳过: {e}")
        return 1.0


if __name__ == "__main__":
    _init_from_existing()
