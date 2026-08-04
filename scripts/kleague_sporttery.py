"""K League 体彩竞彩赔率接入：检查韩K是否开售 → 拉取 SPF/CRS/让球

竞彩韩K通常赛前 1-2 天开售（如 8/8 比赛 8/7 开售）。本脚本在开售后：
1. 检查在售场次是否含韩K联赛
2. 拉取韩K场次 SPF(HAD) + 比分(CRS) 赔率
3. 输出与 Pinnacle 对比（中国竞彩 vs 国际盘）

用法: python scripts/kleague_sporttery.py
"""
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"


def fetch_sporttery(pool="had"):
    url = f"{API}?poolCode={pool}&channel=c_web"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.sporttery.cn/jc/jsq/spfxspf.html",
        "Origin": "https://www.sporttery.cn",
    })
    return json.load(urllib.request.urlopen(req, timeout=20)).get("value", {})


def find_kleague(subs):
    """返回韩K子场次（leagueAllName 含 '韩' 或 leagueAbbName 含 K联）"""
    out = []
    for s in subs:
        name = (s.get("leagueAllName", "") or "") + (s.get("leagueAbbName", "") or "")
        if "韩" in name or "K联" in name:
            out.append(s)
    return out


def main():
    data = fetch_sporttery()
    subs = []
    for m in data.get("matchInfoList", []):
        subs.extend(m.get("subMatchList", []))
    kl = find_kleague(subs)

    if not kl:
        print("⚠️ 竞彩韩K联赛今日未开售（通常赛前 1-2 天开售，比赛日复查）")
        print("   在售场次:", len(subs))
        return

    print(f"✅ 韩K联赛已开售：{len(kl)} 场\n")
    for s in kl:
        had = s.get("had", {})
        crs = s.get("crs", {})
        print(f"{s.get('matchNumStr')} {s.get('homeTeamAbbName')} vs {s.get('awayTeamAbbName')} | {s.get('leagueAllName')}")
        print(f"   SPF: 主{had.get('h')} 平{had.get('d')} 客{had.get('a')}")
        if crs:
            items = sorted(crs.items(), key=lambda x: str(x[0]))
            top = [f"{k}:{v}" for k, v in items if v][:10]
            print(f"   CRS: {'  '.join(top)}")
        print()


if __name__ == "__main__":
    main()
