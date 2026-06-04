"""
赛季滚动预测引擎

每轮比赛是一个预测节点：
  赛前 → 基于历史+本赛季已累积规则预测
  赛后 → 更新参数, 滚动到下一轮

优化目标: 全赛季累积MAE最小化
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.classify import classify_opponent_tier, DERBY_RIVALS

# ── 规则基值 ──
TIER_BASE: dict[str, float] = {"S": 11100, "A": 10100, "B": 8600, "C1": 5100, "C2": 6500}
DEFAULT_MULTIPLIERS = {
    "derby": 1.25, "lost_bottom": 0.55, "heavy_home_loss": 0.70,
    "away_winless": 0.78, "saturday": 1.12,
    "late_season": 0.60, "big_win_prev": 0.82,
}
PENALTY_FLOOR = 0.35
CAL_ALPHA = 0.20

# ── 赛季状态 ──
_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "season_state.json")


class SeasonEngine:
    """赛季滚动预测引擎。

    用法:
        engine = SeasonEngine(season="2026")
        engine.init_from_prior_season("2025")  # 从历史赛季初始化

        for match in season_schedule:
            pred = engine.predict(match)        # 赛前预测
            # ... 比赛结束 ...
            engine.update(match, actual)        # 赛后更新
    """

    def __init__(self, season: str = "2026"):
        self.season = season
        self.multipliers = dict(DEFAULT_MULTIPLIERS)
        self.tier_base = dict(TIER_BASE)
        self.tier_cal = {"S": 1.0, "A": 1.0, "B": 1.0, "C1": 1.0, "C2": 1.0}
        self.history: list[dict] = []
        self.completed = 0
        self.cumulative_mae = 0.0
        self._form_buffer: list[dict] = []  # 本赛季已赛结果

    # ── 初始化 ──
    def init_from_prior_season(self, prior_season: str):
        """从历史赛季数据学习初始参数。"""
        parquet = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "all_unified.parquet")
        if not os.path.exists(parquet):
            return

        all_data = pd.read_parquet(parquet)
        csl = all_data[
            (all_data["competition"] == "CSL") & (all_data["is_home"])
            & (~all_data["is_bundle"]) & (~all_data["is_partial"])
            & (all_data["match_date"].str.startswith(prior_season))
        ]

        if csl.empty:
            return

        # 学习级别基准
        for t in ["S", "A", "B", "C"]:
            sub = csl[csl["match_id"].apply(lambda m: classify_opponent_tier(m.split(" ")[-1]) == t)]
            if len(sub) > 0:
                self.tier_base[t] = round(sub.groupby("match_id")["数量"].sum().median(), -2)

        # 学习乘数 (简化: 用回归残差)
        # 此处保留默认值作为先验，后续赛季运行中自适应

    # ── 情境检测 ──
    def detect_context(self, match_date, opponent: str) -> dict:
        """从CSL Dashboard检测赛前情境（V4规则）。"""
        import urllib.request

        md = pd.Timestamp(match_date)
        ctx = {
            "derby": opponent in DERBY_RIVALS,
            "saturday": md.weekday() == 5,
            "late_season": md.month >= 10,
            "lost_bottom": False, "heavy_home_loss": False,
            "away_winless": False, "returning_home": False,
            "big_win_prev": False,
        }

        try:
            url = "https://xxxniconico.github.io/csl-dashboard-2026/dashboard_embed.json"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))

            # 提取国安赛果
            guoan_matches = []
            for lg in data.get("raw_data", {}).get("leagues", []):
                for m in lg.get("matches", []):
                    h = m.get("home_club", ""); a = m.get("away_club", "")
                    if "国安" not in h and "国安" not in a: continue
                    score = m.get("score", {})
                    if not isinstance(score, dict) or score.get("home") is None: continue
                    dt = str(m.get("date", ""))[:10]
                    is_home = "国安" in h
                    guoan_matches.append({
                        "date": dt, "is_home": is_home,
                        "opponent": a if is_home else h,
                        "gf": int(score["home"]) if is_home else int(score["away"]),
                        "ga": int(score["away"]) if is_home else int(score["home"]),
                    })

            df_g = pd.DataFrame(guoan_matches).sort_values("date")
            df_g["md"] = pd.to_datetime(df_g["date"])
            df_g["result"] = df_g.apply(
                lambda r: "W" if r["gf"] > r["ga"] else "D" if r["gf"] == r["ga"] else "L", axis=1)

            # 赛前已完赛结果
            prev = df_g[df_g["md"] < md]
            last3 = prev.tail(3)
            last5 = prev.tail(5)

            # lost_bottom / heavy_home_loss
            st_path = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "standings_2026_by_round.parquet")
            st26 = pd.read_parquet(st_path) if os.path.exists(st_path) else None
            if st26 is not None:
                st26["md"] = pd.to_datetime(st26["date"])

            for _, r in last3.iterrows():
                if r["result"] != "L": continue
                opp_rank = 8
                if st26 is not None:
                    before = st26[st26["md"] <= pd.Timestamp(r["date"])]
                    if not before.empty:
                        target = before["round"].max()
                        row = st26[(st26["round"] == target) & (st26["team"].str.contains(str(r["opponent"])[:4], na=False))]
                        if not row.empty: opp_rank = int(row["rank"].iloc[0])
                if opp_rank >= 12: ctx["lost_bottom"] = True
                # V4: heavy_home_loss 仅对手≤B级
                if r["is_home"] and (r["ga"] - r["gf"]) >= 2:
                    from src.classify import classify_opponent_tier
                    if classify_opponent_tier(r["opponent"]) != "S":
                        ctx["heavy_home_loss"] = True

            # 国安自身排名（保留但不在predict中使用，仅记录）
            if st26 is not None and not prev.empty:
                last_date = pd.Timestamp(prev.iloc[-1]["date"])
                before = st26[st26["md"] <= last_date]
                if not before.empty:
                    target = before["round"].max()
                    gr = st26[(st26["round"] == target) & (st26["team"] == "北京国安")]
                    if not gr.empty:
                        ctx["guoan_rank"] = int(gr["rank"].iloc[0])

            # away_winless: 近3场中2+客场且全不胜
            away3 = last3[last3["is_home"] == False]
            if len(away3) >= 2 and (away3["result"] == "W").sum() == 0:
                ctx["away_winless"] = True

            # returning_home: 上一场是客场
            if len(last3) > 0 and not last3.iloc[-1]["is_home"]:
                ctx["returning_home"] = True

            # big_win_prev: 上场净胜3+
            if len(prev) > 0 and prev.iloc[-1]["result"] == "W":
                last = prev.iloc[-1]
                if (last["gf"] - last["ga"]) >= 3:
                    ctx["big_win_prev"] = True

        except Exception:
            pass

        return ctx

    # ── 预测 ──
    def predict(self, opponent: str, match_date, **override_ctx) -> float:
        """赛前预测单场上座（乘法叠加 + EMA校准）。"""
        md = pd.Timestamp(match_date)
        ctx = self.detect_context(match_date, opponent)
        ctx.update(override_ctx)

        tier = classify_opponent_tier(opponent)
        base = self.tier_base[tier]
        mult = 1.0

        if ctx.get("derby") and tier != "S":
            mult *= self.multipliers["derby"]
        if ctx.get("lost_bottom"):
            mult *= self.multipliers["lost_bottom"]
        elif ctx.get("heavy_home_loss"):
            mult *= self.multipliers["heavy_home_loss"]
        if ctx.get("away_winless"):
            mult *= self.multipliers["away_winless"]
        if ctx.get("big_win_prev"):
            mult *= self.multipliers["big_win_prev"]
        if ctx.get("saturday"):
            mult *= self.multipliers["saturday"]
        if ctx.get("late_season"):
            mult *= self.multipliers["late_season"]

        if mult < PENALTY_FLOOR:
            mult = PENALTY_FLOOR

        cal = self.tier_cal.get(tier, 1.0)
        return min(base * mult * cal, 20000.0)

    # ── 赛后更新 ──
    def update(self, opponent: str, match_date, actual: int, **override_ctx):
        """赛后更新校准因子和累积指标。"""
        md = pd.Timestamp(match_date)
        ctx = self.detect_context(match_date, opponent)
        ctx.update(override_ctx)

        pred = self.predict(opponent, match_date, **ctx)
        tier = classify_opponent_tier(opponent)
        ratio = actual / pred if pred > 0 else 1.0

        # EMA 更新分级校准
        alpha = CAL_ALPHA
        old_cal = self.tier_cal[tier]
        new_cal = alpha * ratio + (1 - alpha) * old_cal
        self.tier_cal[tier] = round(max(0.3, min(2.0, new_cal)), 4)

        # 记录
        err = abs(pred - actual)
        self.completed += 1
        self.cumulative_mae = (self.cumulative_mae * (self.completed - 1) + err) / self.completed

        record = {
            "round": self.completed, "date": str(md)[:10],
            "opponent": opponent, "tier": tier,
            "actual": actual, "predicted": round(pred, 0),
            "error": round(err, 0), "error_pct": round(err / actual * 100, 1),
            "cumulative_mae": round(self.cumulative_mae, 0),
            "cal_factors": dict(self.tier_cal),
            "context": {k: v for k, v in ctx.items() if v},
        }
        self.history.append(record)

        # 保存状态
        self._save()

        return record

    # ── 回测 ──
    def backtest(self, matches: list[dict]) -> pd.DataFrame:
        """在历史赛程上跑完整回测。

        Args:
            matches: [{opponent, date, actual}, ...] 按日期排序

        Returns:
            DataFrame with round-by-round predictions and errors
        """
        # 重置
        self.tier_cal = {"S": 1.0, "A": 1.0, "B": 1.0, "C1": 1.0, "C2": 1.0}
        self.history = []
        self.completed = 0
        self.cumulative_mae = 0.0

        for m in sorted(matches, key=lambda x: x["date"]):
            rec = self.update(m["opponent"], m["date"], m["actual"])
            rec["opponent"] = m["opponent"]

        return pd.DataFrame(self.history)

    # ── 持久化 ──
    def _save(self):
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w") as f:
            json.dump({
                "season": self.season, "completed": self.completed,
                "cumulative_mae": self.cumulative_mae,
                "tier_cal": self.tier_cal,
                "tier_base": self.tier_base,
                "multipliers": self.multipliers,
                "history": self.history[-20:],  # 只保留最近20场
            }, f, indent=2, ensure_ascii=False)

    def load(self):
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE) as f:
                state = json.load(f)
            self.season = state.get("season", self.season)
            self.completed = state.get("completed", 0)
            self.cumulative_mae = state.get("cumulative_mae", 0)
            self.tier_cal = state.get("tier_cal", self.tier_cal)
            self.tier_base = state.get("tier_base", self.tier_base)
            self.multipliers = state.get("multipliers", self.multipliers)
            self.history = state.get("history", [])

    def summary(self) -> str:
        if not self.history:
            return "暂无数据"
        df = pd.DataFrame(self.history)
        last = df.iloc[-1]
        return (
            f"赛季{self.season} | 已完成{self.completed}场 | "
            f"累积MAE={self.cumulative_mae:.0f}张 | "
            f"最新单场误差={last['error']:.0f}张({last['error_pct']:.1f}%) | "
            f"校准: {self.tier_cal}"
        )
