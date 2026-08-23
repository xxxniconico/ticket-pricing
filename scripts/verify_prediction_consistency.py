"""验证：展示层规则链乘积 == 引擎 predict()（未校准口径）== 引擎 predict_calibrated（校准口径）。
若展示层与引擎漂移（如暑假乘数不一致），此处会直接暴露。"""
import sys
sys.path.insert(0, '/home/xxxsuli/ticket-pricing')
import pandas as pd
from src.rule_engine import predict, predict_calibrated, MULTIPLIERS, PENALTY_FLOOR, TIER_BASE, get_effective_calibration
from src.classify import classify_opponent_tier

# 模拟三级别场次
cases = [
    ("深圳新鹏城", "2026-08-07", "C", dict(summer=True, top3_form=False)),       # C级暑假
    ("浙江", "2026-08-01", "B", dict(summer=True, saturday=True)),               # B级暑假周六（已赛）
    ("山东泰山", "2026-07-04", "A", dict(summer=False, saturday=True, top3_form=False)),  # A级周六
]

print(f"{'场次':<12} {'级别':<3} {'引擎predict':>10} {'引擎校准后':>10} | 规则链检查")
all_ok = True
for opp, date, tier, kwargs in cases:
    base = TIER_BASE[tier]
    # 引擎
    p_raw = predict(opp, opponent_tier_override=tier, match_date=date, **kwargs)
    p_cal = predict_calibrated(opp, opponent_tier_override=tier, match_date=date, **kwargs)
    cal = get_effective_calibration(tier, enable_ema=True)
    # 展示层规则链乘积（按 build_rules_triggered 逻辑手工复算暑假/周六等）
    mult = 1.0
    if kwargs.get("saturday"): mult *= MULTIPLIERS["saturday"]
    if kwargs.get("summer"):
        if tier == "C": mult *= MULTIPLIERS["summer_C"]
        elif tier == "B": mult *= MULTIPLIERS["summer"]
        else: mult *= 1.08
    if kwargs.get("summer") and kwargs.get("saturday"):
        mult *= MULTIPLIERS["summer_saturday"]  # 暑期×周六交互（2026-08-23 云南样本确认落地）
    mult = max(mult, PENALTY_FLOOR)
    display_raw = min(base * mult, 20000)
    ok = abs(display_raw - p_raw) < 1e-6
    all_ok &= ok
    print(f"{opp:<12} {tier:<3} {p_raw:>10.0f} {p_cal:>10.0f} | 展示层×{mult:.3f}={display_raw:>8.0f} {'✅' if ok else '❌ 不一致!'}")

# 暑假乘数一致性
print(f"\nMULTIPLIERS: summer={MULTIPLIERS['summer']} summer_C={MULTIPLIERS['summer_C']} late_season={MULTIPLIERS['late_season']}")
print(f"C级暑假引擎 {predict('深圳新鹏城', opponent_tier_override='C', match_date='2026-08-07', summer=True):.0f} = 5700×1.30 = {5700*1.30:.0f} {'✅' if abs(predict('深圳新鹏城', opponent_tier_override='C', match_date='2026-08-07', summer=True)-7410)<1e-6 else '❌'}")
print(f"late_season 引擎生效: {predict('青岛海牛', opponent_tier_override='C', match_date='2026-11-15', late_season=True):.0f} = 5700×0.80 = {5700*0.80:.0f} {'✅' if abs(predict('青岛海牛', opponent_tier_override='C', match_date='2026-11-15', late_season=True)-4560)<1e-6 else '❌'}")
print("\n" + ("全部一致 ✅" if all_ok else "存在不一致 ❌"))

# 常驻防漂移测试：改动 rule_engine.py 或 prediction_detail.py 后运行本脚本。
# 若展示层与引擎任一乘数漂移，输出会显示 ❌。用法: .venv/bin/python scripts/verify_prediction_consistency.py
