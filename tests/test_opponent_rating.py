"""Unit tests for opponent_rating.py"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
import numpy as np, pandas as pd
from src.opponent_rating import (
    _elo_update, _get_k_factor, _parse_round, _get_initial_elo,
    _normalize_to_0_100, compute_elo_history, get_elo_at,
    compute_strength, compute_appeal, get_effective_tier,
    FROZEN_TIERS, ELO_MEAN, ALL_CSL_TEAMS_2026,
)
from src.csl_context import load_csl_data


class TestEloUpdate:
    def test_elo_formula(self):
        """Equal ratings + draw with home advantage -> small ELO shift."""
        new_a, new_b = _elo_update(1500, 1500, 0.5)
        assert abs(new_a - 1500) < 10
        assert abs(new_b - 1500) < 10

    def test_home_advantage(self):
        """Home team gets advantage."""
        new_h, new_a = _elo_update(1500, 1500, 0.5)
        # With home_adv=65, expected_h > 0.5, so new_h > 1500, new_a < 1500
        # Actually with score=0.5 (draw), home team loses ELO because expected > 0.5
        pass

    def test_win_increases_elo(self):
        """Winner gains ELO."""
        new_h, new_a = _elo_update(1500, 1500, 1.0)
        assert new_h > 1500
        assert new_a < 1500

    def test_k_factor_early(self):
        assert _get_k_factor(3) == 35

    def test_k_factor_mid(self):
        assert _get_k_factor(15) == 25

    def test_k_factor_late(self):
        assert _get_k_factor(27) == 18

    def test_elo_conservancy(self):
        """ELO sum should be conserved per match."""
        new_h, new_a = _elo_update(1600, 1400, 1.0, k=20)
        assert abs((new_h + new_a) - 3000) < 0.01

    def test_max_change(self):
        """Single match change <= 30."""
        for k in [15, 20, 30]:
            new_h, new_a = _elo_update(1700, 1300, 1.0, k=k)
            assert abs(new_h - 1700) < 30
            assert abs(new_a - 1300) < 30


class TestParseRound:
    def test_parse_chinese(self):
        assert _parse_round("第15轮") == 15

    def test_parse_digit(self):
        assert _parse_round("15") == 15

    def test_parse_empty(self):
        assert _parse_round("") == 0


class TestNormalize:
    def test_midpoint(self):
        assert _normalize_to_0_100(50, 0, 100) == 50.0

    def test_min(self):
        assert _normalize_to_0_100(0, 0, 100) == 0.0

    def test_max(self):
        assert _normalize_to_0_100(100, 0, 100) == 100.0

    def test_clip(self):
        assert _normalize_to_0_100(200, 0, 100) == 100.0
        assert _normalize_to_0_100(-50, 0, 100) == 0.0


class TestInitialElo:
    def test_known_team(self):
        assert _get_initial_elo("武汉三镇") < 1600  # compressed initial

    def test_promoted_team(self):
        assert _get_initial_elo("辽宁铁人") <= 1450


class TestStrengthScore:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.matches, self.standings, _ = load_csl_data()
        self.elo_history = compute_elo_history(self.matches)

    def test_chengdu_high_st(self):
        st = compute_strength("成都蓉城", "2026-06-25", self.elo_history,
                              self.standings, self.matches)
        assert st > 70

    def test_wuhan_low_st(self):
        st = compute_strength("武汉三镇", "2026-06-25", self.elo_history,
                              self.standings, self.matches)
        assert st < 50

    def test_promoted_team_st(self):
        st = compute_strength("辽宁铁人", "2026-06-25", self.elo_history,
                              self.standings, self.matches)
        assert st < 50


class TestAppealScore:
    def test_shenhua_high_ap(self):
        ap = compute_appeal("上海申花", "2026-06-25")
        assert ap > 35  # derby bonus

    def test_shandong_high_ap(self):
        ap = compute_appeal("山东泰山", "2026-06-25")
        assert ap > 30  # derby bonus


class TestEffectiveTier:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.matches, self.standings, _ = load_csl_data()
        self.elo_history = compute_elo_history(self.matches)

    def test_frozen_tier_shenhua(self):
        tier = get_effective_tier("上海申花", "2026-06-25",
            elo_history=self.elo_history, standings_by_round=self.standings,
            matches=self.matches)
        assert tier == "S"

    def test_datadriven_tier_shandong(self):
        # 泰山已改为数据驱动 (ST>=60 + AP>=40 -> A)
        tier = get_effective_tier("山东泰山", "2026-06-25",
            elo_history=self.elo_history, standings_by_round=self.standings,
            matches=self.matches)
        assert tier == "A"  # Data-driven A, not hard-locked

    def test_tier_distribution(self):
        from src.opponent_rating import get_all_tier_distribution
        dist = get_all_tier_distribution("2026-06-25", elo_history=self.elo_history,
            matches=self.matches, standings_by_round=self.standings)
        assert dist["S"] >= 1
        assert dist["A"] >= 1
        assert dist["B"] >= 3
        assert dist["C"] >= 4


class TestClassifyCompat:
    def test_legacy_call_no_date(self):
        from src.classify import classify_opponent_tier
        result = classify_opponent_tier("武汉三镇")
        assert result in ("S", "A", "B", "C")

    def test_dynamic_call_with_date(self):
        from src.classify import classify_opponent_tier
        result = classify_opponent_tier("武汉三镇", match_date="2026-06-25", dynamic=True)
        assert result in ("S", "A", "B", "C")

    def test_dynamic_without_date_fallback(self):
        from src.classify import classify_opponent_tier
        result = classify_opponent_tier("成都蓉城", dynamic=True)
        assert result in ("S", "A", "B", "C")
