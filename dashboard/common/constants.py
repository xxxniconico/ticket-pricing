"""看板常量。"""
from src.rule_engine import MULTIPLIERS

# ── Constants ───────────────────────────────────────────
PT_LABELS = {
    "S_S": "S·德比定价", "S_A": "A·标准定价", "S_Aminus": "A·降价",
    "S_B": "B·标准定价", "S_C": "C·标准定价", "S_Cminus": "C·降价",
}
DEDUCTIONS = {
    "北京国安": 5, "上海申花": 10, "天津津门虎": 10, "山东泰山": 6,
    "上海海港": 5, "武汉三镇": 5, "浙江": 5, "河南": 6, "青岛海牛": 7,
}
WHATIF_SCENARIOS = {
    "基准（模型推荐）": 1.0,
    "悲观（-20%）": 0.80,
    "乐观（+15%）": 1.15,
    f"德比溢价 ×{MULTIPLIERS['derby']}": MULTIPLIERS["derby"],
    f"暑假活动 ×{MULTIPLIERS['summer']}": MULTIPLIERS["summer"],
    f"工作日 ×{MULTIPLIERS['midweek']}": MULTIPLIERS["midweek"],
    f"揭幕战 ×{MULTIPLIERS['season_opener']}": MULTIPLIERS["season_opener"],
    f"双赛周 ×{MULTIPLIERS['short_rest']}": MULTIPLIERS["short_rest"],
    "自定义": None,
}
TIER_COLORS = {"S": "#ff6b6b", "A": "#f0c040", "B": "#8a8f98", "C": "#51cf66"}
TIER_LABELS = {"S": "S·德比", "A": "A·强队", "B": "B·常规", "C": "C·普通"}
WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
