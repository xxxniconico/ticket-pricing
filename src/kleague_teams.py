"""K League 1 队名映射（英文→中文），供预测/决策卡展示用。

覆盖 2022-2026 全5季出现过的 16 支球队（含已降级队，用于历史数据展示）。
"""
TEAM_CN = {
    "Bucheon FC 1995": "富川FC 1995",
    "Daegu FC": "大邱FC",
    "Daejeon Hana Citizen": "大田韩亚市民",
    "FC Anyang": "安养FC",
    "FC Seoul": "首尔FC",
    "Gangwon FC": "江原FC",
    "Gimcheon Sangmu FC": "金泉尚武",
    "Gwangju FC": "光州FC",
    "Incheon United": "仁川联",
    "Jeju SK": "济州SK",
    "Jeonbuk Hyundai Motors": "全北现代",
    "Pohang Steelers": "浦项制铁",
    "Seongnam FC": "城南FC",
    "Suwon FC": "水原FC",
    "Suwon Samsung Bluewings": "水原三星蓝翼",
    "Ulsan HD": "蔚山HD",
}


def cn(name: str) -> str:
    return TEAM_CN.get(name, name)


if __name__ == "__main__":
    for en, zh in TEAM_CN.items():
        print(f"{en:<28s} -> {zh}")
