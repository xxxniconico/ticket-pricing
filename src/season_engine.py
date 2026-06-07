"""
赛季滚动预测引擎 — V5.4 同步

委托 rule_engine.predict() 做基预测, 自身维护 EMA 分级校准 + 赛季状态持久化。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

from src.classify import classify_opponent_tier, DERBY_RIVALS

# ── 赛季状态 ──
_STATE_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "season_state.json")

CAL_ALPHA = 0.20


class SeasonEngine:
    """赛季滚动预测引擎 — 委托 rule_engine 做基预测, 自身维护 EMA 校准。

    用法:
        engine = SeasonEngine(season="2026")
        engine.init_from_prior_season("2025")  # 从历史赛季初始化校准因子

        for match in season_schedule:
            pred = engine.predict(match)        # 赛前预测
            # ... 比赛结束 ...
            engine.update(match, actual)        # 赛后更新
    """

    def __init__(self, season: str = "2026"):
        self.season = season
        self.tier_cal = {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}
        self.history: list[dict] = []
        self.completed = 0
        self.cumulative_mae = 0.0

    # ── 初始化 ──
    def init_from_prior_season(self, prior_season: str):
        """从历史赛季数据学习初始 EMA 校准因子。"""
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

        from src.rule_engine import predict as rule_predict
        for t in ["S", "A", "B", "C"]:
            sub = csl[csl["match_id"].apply(lambda m: classify_opponent_tier(m.split(" ")[-1]) == t)]
            if len(sub) == 0:
                continue
            ratios = []
            for mid in sub["match_id"].unique():
                m = sub[sub["match_id"] == mid]
                actual = m["数量"].sum()
                opp = m["opponent"].iloc[0]
                raw = rule_predict(opp, match_year=prior_season)
                if raw > 0:
                    ratios.append(actual / raw)
            if ratios:
                self.tier_cal[t] = round(np.mean(ratios), 4)

    # ── 情境检测 ──
    def detect_context(self, match_date, opponent: str) -> dict:
        """从CSL Dashboard检测赛前情境（V4规则）。"""
        import urllib.request

        md = pd.Timestamp(match_date)
        ctx = {
            "derby": opponent in DERBY_RIVALS,
            "saturday": md.weekday() == 5,
            "midweek": md.weekday() in (1, 2, 3),
            "summer": md.month in (7, 8),
            "midseason_restart": False,
            "season_opener": False,
            "lost_bottom": False, "heavy_home_loss": False,
            "away_winless": False,
            "short_rest": False,
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

            # short_rest: ≤4 days since last home match
            hp = prev[prev["is_home"] == True]
            if not hp.empty and (md - hp["md"].max()).days <= 4:
                ctx["short_rest"] = True

            # midseason_restart: >=28 days since last match, months 6-7
            if not prev.empty and md.month in (6, 7):
                if (md - prev["md"].max()).days >= 28:
                    ctx["midseason_restart"] = True

            # season_opener: first HOME match of calendar year
            same_year_home = prev[(prev["md"].dt.year == md.year) & (prev["is_home"] == True)]
            if same_year_home.empty:
                ctx["season_opener"] = True

        except Exception:
            pass

        return ctx

    # ── 预测 ──
    def predict(self, opponent: str, match_date, **override_ctx) -> float:
        """赛前预测：委托 rule_engine 做基预测, 叠加自身 EMA 校准。"""
        from src.rule_engine import predict as rule_predict

        ctx = self.detect_context(match_date, opponent)
        ctx.update(override_ctx)

        raw = rule_predict(opponent, **ctx)
        tier = classify_opponent_tier(opponent)
        cal = self.tier_cal.get(tier, 1.0)
        return min(raw * cal, 20000.0)

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
        self.tier_cal = {"S": 1.0, "A": 1.0, "B": 1.0, "C": 1.0}
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
                "history": self.history[-20:],
            }, f, indent=2, ensure_ascii=False)

    def load(self):
        if os.path.exists(_STATE_FILE):
            with open(_STATE_FILE) as f:
                state = json.load(f)
            self.season = state.get("season", self.season)
            self.completed = state.get("completed", 0)
            self.cumulative_mae = state.get("cumulative_mae", 0)
            self.tier_cal = state.get("tier_cal", self.tier_cal)
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
