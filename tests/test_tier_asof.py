"""回归测试：分级/AP 的历史分位必须「as-of」，不随新数据入库漂移。

背景（2026-10-18 青岛西海岸复盘）：
  `_attendance_percentile` 原用全量历史，本场 5,751 张入库后
  西海岸 HIST_ATT_pct 40.0 → 25.0、AP 24.81 → 19.6、分级 B → C，
  即「赛后回看会改写赛前分级」，回测不可复现。
  修复：`as_of=match_date` 只统计 match_date 之前的场次。
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.opponent_rating import _attendance_percentile, get_opponent_scorecard, load_elo_history


# ── 合成数据：验证"未来行不影响 as_of 结果" ──────────────
def _synthetic_hist():
    rows = [
        # 对手 X：as_of 前两场
        {"match_date": "2024-04-21", "opponent": "X队", "attendance": 8000, "match_tier": ""},
        {"match_date": "2025-06-17", "opponent": "X队", "attendance": 6000, "match_tier": ""},
        # 对手 Y / Z：对照组
        {"match_date": "2024-05-01", "opponent": "Y队", "attendance": 12000, "match_tier": ""},
        {"match_date": "2024-06-01", "opponent": "Z队", "attendance": 4000, "match_tier": ""},
        # X 的"本场"（as_of 当天）与"未来场"
        {"match_date": "2026-10-18", "opponent": "X队", "attendance": 1000, "match_tier": ""},
        {"match_date": "2027-05-01", "opponent": "X队", "attendance": 500, "match_tier": ""},
    ]
    df = pd.DataFrame(rows)
    df["match_date"] = pd.to_datetime(df["match_date"])
    return df


class TestPercentileAsOf:
    def test_future_rows_ignored(self):
        """把 as_of 之后的场次翻倍，分位必须不变（最直接的 look-ahead 检测）。"""
        hist = _synthetic_hist()
        base = _attendance_percentile("X队", hist, as_of="2026-10-18")

        future = hist[hist["match_date"] >= "2026-10-18"]
        polluted = pd.concat([hist, future, future], ignore_index=True)
        after = _attendance_percentile("X队", polluted, as_of="2026-10-18")
        assert base == after

    def test_as_of_equals_manual_filter(self):
        """带 as_of 的结果 == 手工先过滤再调用（不带 as_of）。"""
        hist = _synthetic_hist()
        asof = "2026-10-18"
        manual = hist[hist["match_date"] < pd.Timestamp(asof)]
        assert _attendance_percentile("X队", hist, as_of=asof) == _attendance_percentile("X队", manual)
        assert _attendance_percentile("Y队", hist, as_of=asof) == _attendance_percentile("Y队", manual)

    def test_no_as_of_keeps_legacy_behaviour(self):
        """as_of=None 时保持全量口径（向后兼容）。"""
        hist = _synthetic_hist()
        assert _attendance_percentile("X队", hist) == _attendance_percentile("X队", hist, as_of=None)

    def test_empty_after_filter(self):
        """as_of 早于所有历史 → 退回默认低分位，不报错。"""
        hist = _synthetic_hist()
        assert _attendance_percentile("X队", hist, as_of="2020-01-01") == 15.0


# ── 真实数据：复现本次 bug 的防护 ──────────────
class TestScorecardStable:
    @pytest.fixture(scope="class")
    def hist(self):
        from src.opponent_rating import _load_guoan_home_attendance
        h = _load_guoan_home_attendance()
        if h.empty:
            pytest.skip("all_unified.parquet 不可用")
        h = h.copy()
        h["match_date"] = pd.to_datetime(h["match_date"])
        return h

    def test_hist_component_ignores_same_day_result(self, hist):
        """scorecard 的 HIST 分项：注入「含本场」与「不含本场」的历史，结果必须一致。

        青岛西海岸 10/18 本场 5,751 张若被算进历史，HIST 会从 40.0 掉到 25.0。
        """
        md = "2026-10-18"
        truncated = hist[hist["match_date"] < pd.Timestamp(md)]
        elo = load_elo_history()
        a = get_opponent_scorecard("青岛西海岸", md, elo_history=elo, guoan_home_history=truncated)
        b = get_opponent_scorecard("青岛西海岸", md, elo_history=elo, guoan_home_history=hist)
        assert float(a["components"]["AP_sub"]["HIST_ATT_pct"]) == float(b["components"]["AP_sub"]["HIST_ATT_pct"])
        assert a["AP"] == b["AP"]
        assert a["tier"] == b["tier"]

    def test_ap_drift_guard(self, hist):
        """西海岸 10/18 口径复现决策卡：HIST=40.0 / AP=24.81。

        AP 还含 PERF（按 matches 里的已赛比分自算排名分），所以 matches 也要截到
        出卡时点（第26轮后、10/11 之前）。历史票房一侧由 as_of 自动截断。
        """
        from src.csl_context import load_csl_data
        matches, _, _ = load_csl_data()
        matches_asof = [m for m in matches if str(m.get("date"))[:10] < "2026-10-11"]
        md = "2026-10-18"
        card = get_opponent_scorecard("青岛西海岸", md, elo_history=load_elo_history(),
                                      matches=matches_asof, guoan_home_history=hist)
        assert float(card["components"]["AP_sub"]["HIST_ATT_pct"]) == 40.0
        # 容差 1.0：AP 的 PERF 项依赖并列排名（38 分三队同分，官方榜与自算榜的
        # 第 4/第 5 差 6.7 分 → AP 差 0.67），HIST 才是 as-of 不变量（断言精确值）。
        assert abs(float(card["AP"]) - 24.81) < 1.0

    def test_ap_moves_only_with_perf_window(self, hist):
        """开票日（10/11 第27轮已踢）口径 AP ≈ 23.5：变化的只能是 PERF，不是 HIST。"""
        from src.csl_context import load_csl_data
        matches, _, _ = load_csl_data()
        md = "2026-10-18"
        card = get_opponent_scorecard("青岛西海岸", md, elo_history=load_elo_history(),
                                      matches=matches, guoan_home_history=hist)
        assert float(card["components"]["AP_sub"]["HIST_ATT_pct"]) == 40.0
        assert 22.5 <= float(card["AP"]) <= 24.5


class TestBoundaryZoneFlag:
    def test_zone_independent_of_soft_prefer(self):
        """ap_boundary_zone 只反映"AP 落在 ±3 带内 + ST≥35"，与 soft_prefer 无关。"""
        from src.opponent_rating import get_effective_tier, _load_guoan_home_attendance
        hist = _load_guoan_home_attendance()
        if hist.empty:
            pytest.skip("all_unified.parquet 不可用")
        hist = hist.copy()
        hist["match_date"] = pd.to_datetime(hist["match_date"])
        md = "2026-10-18"
        hist = hist[hist["match_date"] < pd.Timestamp(md)]
        elo = load_elo_history()

        card_lower = get_opponent_scorecard("青岛西海岸", md, elo_history=elo, guoan_home_history=hist)
        # 构造 higher 判定：直接调 get_effective_tier 两档
        t_lower = get_effective_tier("青岛西海岸", md, elo_history=elo, guoan_home_history=hist,
                                     soft_band=3.0, soft_prefer="lower")
        t_higher = get_effective_tier("青岛西海岸", md, elo_history=elo, guoan_home_history=hist,
                                      soft_band=3.0, soft_prefer="higher")
        assert card_lower["ap_boundary_zone"] is True
        # 两队制在边界场必然分歧，但 zone 标记始终为 True
        assert t_lower == "C" and t_higher == "B"
        assert card_lower["tier"] == t_lower
        assert card_lower["ap_soft_band"] is False  # lower 下 tier==tier_hard，软边界不再改判
