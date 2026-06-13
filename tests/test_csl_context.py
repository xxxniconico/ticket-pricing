"""csl_context.detect_ctx 一致性测试。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.csl_context import detect_ctx, finalize_guoan_schedule, get_guoan_matches, load_csl_data

DEPRECATED = {"lost_bottom", "unbeaten_3"}


@pytest.fixture(scope="module")
def guoan_bundle():
    matches, rounds, _ = load_csl_data()
    guoan = get_guoan_matches(matches)
    guoan = [
        m for m in guoan
        if m.get("completed")
        or "cfl_fixtures_api" in m.get("source", "")
        or "wikipedia" in m.get("source", "")
    ]
    guoan = finalize_guoan_schedule(guoan)
    return guoan, rounds


def test_detect_ctx_no_deprecated_keys(guoan_bundle):
    guoan, rounds = guoan_bundle
    target = next(m for m in guoan if m["date"] == "2026-05-06" and m.get("is_home"))
    ctx = detect_ctx(target, guoan, rounds)
    assert not DEPRECATED & set(ctx.keys())


def test_consecutive_home_losses_dalian(guoan_bundle):
    guoan, rounds = guoan_bundle
    target = next(m for m in guoan if m["date"] == "2026-05-06" and m.get("is_home"))
    ctx = detect_ctx(target, guoan, rounds)
    assert ctx.get("consecutive_home_losses") is True


def test_ctx_builder_matches_csl_context(guoan_bundle):
    from dashboard.components.ctx_builder import ctx_kwargs

    guoan, rounds = guoan_bundle
    target = next(m for m in guoan if m["date"] == "2026-05-06" and m.get("is_home"))
    ctx = detect_ctx(target, guoan, rounds)
    kw = ctx_kwargs(ctx)
    assert kw.get("consecutive_home_losses") is True
    assert "lost_bottom" not in kw
    assert "unbeaten_3" not in kw


def test_away_winless_losses_chengdu(guoan_bundle):
    guoan, rounds = guoan_bundle
    target = next(m for m in guoan if m["date"] == "2026-04-12" and m.get("is_home"))
    ctx = detect_ctx(target, guoan, rounds)
    assert ctx.get("away_winless_losses") is True
    assert ctx.get("away_winless") is not True


def test_dalian_match_single_completed(guoan_bundle):
    guoan, _ = guoan_bundle
    dalian = [m for m in guoan if m["date"] == "2026-05-06" and m.get("is_home")]
    assert len(dalian) == 1
    assert dalian[0]["completed"] is True
    assert dalian[0]["hg"] == 3 and dalian[0]["ag"] == 0


def test_next_home_is_wuhan(guoan_bundle):
    from src.csl_context import get_next_guoan_match

    guoan, _ = guoan_bundle
    n = get_next_guoan_match(guoan, home_only=True)
    assert n is not None, "应有未来主场"
    assert n["date"] == "2026-06-27", f"下一场应为 6/27 武汉，实际 {n['date']} vs {n['opponent']}"
    assert "武汉" in n["opponent"]


def test_chengdu_prediction_near_actual(guoan_bundle):
    from dashboard.components.ctx_builder import build_pred_args
    from src.rule_engine import predict

    guoan, rounds = guoan_bundle
    target = next(m for m in guoan if m["date"] == "2026-04-12" and m.get("is_home"))
    ctx = detect_ctx(target, guoan, rounds)
    pred_args = build_pred_args(target, ctx)
    pred = predict(target["opponent"], **pred_args)
    assert 8200 <= pred <= 8500, f"成都场预测 {pred} 应在 8200–8500"
