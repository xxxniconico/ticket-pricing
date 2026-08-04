"""K League 预测快照赛后验证：结算 8/8 预测 vs 实际结果，评估 gap 策略

用法: python scripts/kleague_verify_prediction.py [snapshot.json]
流程:
1. 读快照 (含 pinnacle 赔率 + 模型概率)
2. 从 sofascore 拉实际赛果
3. 对比: 模型校准 (Brier) + gap 方向正确率 + 假设下注盈亏
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "data/raw/kleague_predictions_20260808.json"


def fetch_result(home, away, commence_date):
    """从 sofascore 找两队某天的赛果 (返回 home_goals, away_goals 或 None)"""
    ts = int(time.mktime(time.strptime(commence_date, "%Y-%m-%dT%H:%M:%SZ"))) + 8 * 3600
    day = time.strftime("%Y%m%d", time.localtime(ts))
    # sofascore 按日期取赛事
    url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{day}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=20))
    except Exception:
        return None
    for e in d.get("events", []):
        ht = (e.get("homeTeam") or {}).get("name", "")
        at = (e.get("awayTeam") or {}).get("name", "")
        if ht == home and at == away and e.get("status", {}).get("type") == "finished":
            hs = (e.get("homeScore") or {}).get("current")
            as_ = (e.get("awayScore") or {}).get("current")
            return (hs, as_)
    return None


def main():
    snap = json.load(open(SNAPSHOT, encoding="utf-8"))
    print(f"验证快照: {SNAPSHOT.name} (创建于 {snap['created'][:16]})\n")

    brier_sum, n = 0.0, 0
    gap_ok = 0
    for m in snap["matches"]:
        res = fetch_result(m["home"], m["away"], m["commence"])
        if res is None:
            print(f"{m['home']} vs {m['away']}: 未找到赛果 (可能未开赛)")
            continue
        hg, ag = res
        actual = "H" if hg > ag else ("A" if hg < ag else "D")
        probs = m["model_probs"]
        brier_sum += sum((probs[k] - (1 if actual == k else 0)) ** 2 for k in "HDA")
        n += 1
        # gap 方向: 模型概率 > 市场概率的最大 gap 方向
        inv = {k2: 1 / v for k2, v in m["pinnacle_odds"].items()}
        tot = sum(inv.values())
        home_raw, away_raw = m["home_odds_raw"], m["away_odds_raw"]
        market = {
            "H": inv.get(home_raw, 0) / tot,
            "A": inv.get(away_raw, 0) / tot,
            "D": inv.get("Draw", 0) / tot,
        }
        gaps = {k: probs[k] - market[k] for k in "HDA"}
        best_gap_dir = max(gaps, key=gaps.get)
        if gaps[best_gap_dir] > 0.03:
            gap_ok += (best_gap_dir == actual)
            gap_note = f"  → gap方向{'✅命中' if best_gap_dir == actual else '❌未中'} ({best_gap_dir} {gaps[best_gap_dir]:+.1%})"
        else:
            gap_note = "  (无显著gap)"
        print(f"{m['home']} {hg}-{ag} {m['away']} | 实际{actual} | 模型H{probs['H']:.0%}D{probs['D']:.0%}A{probs['A']:.0%}{gap_note}")

    if n:
        print(f"\n验证 {n} 场, Brier = {brier_sum / n:.4f}")


if __name__ == "__main__":
    main()
