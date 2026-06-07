"""
P1.1 弹性矩阵 + P1.2 四级定价 — 基于真实6档×2级zone体系

生成日期: 2026-05-19
数据源: 2025赛季交易数据 (all_unified.parquet) + 线上票务公告
"""

import json
import math
from pathlib import Path

# ═══════════════════════════════════════════
# 6档区域定义（与 zone_tier_map.json 一致）
# ═══════════════════════════════════════════

ZONE_TIERS = ["T1", "T2", "T3", "T4", "T5", "T6"]

# 当前赛季（2026）zone 映射 — 用于优化器和前向预测
ZONE_SECTIONS = {
    "T6": ["101","102"],
    "T5": ["103","104","113","114","115","116","117","118","129","130","207","220","221","222","223","224","219"],
    "T4": ["211","319","320","321","322","323","324"],
    "T3": ["105","106","107","110","111","112","119","120","121","122","123","124","128",
           "208","209","210","212","213","214","215","216","217","226","227","228","229",
           "230","231","232","237","317","318","325","326","337","338"],
    "T2": ["307","308","309","314","315","316","327","328","329"],
    "T1": ["310","311","312","313","330","331","332"],
}

# 历史赛季 zone 映射 — 用于看板历史定价 TAB
ZONE_SECTIONS_BY_YEAR = {
    "2026": ZONE_SECTIONS,  # 同当前
    "2025": {
        "T6": ["101","102"],
        "T5": ["103","104","113","114","115","116","117","118","129","130","219","220","221","222","223","224","225"],
        "T4": ["319","320","321","322","323","324"],
        "T3": ["105","106","107","110","111","119","120","121","122","123","124","128",
               "208","209","210","211","212","213","214","215","216","217","226","227","228","229",
               "230","231","232","237","317","318","325","326","337","338","0"],
        "T2": ["112","308","309","314","315","316","327","328","329"],
        "T1": ["307","310","311","312","313","330","331","332"],
    },
    "2024": {
        "T6": ["101","102"],
        "T5": ["129","130","219","220","224"],
        "T4": ["319","320","321","322","323","324"],
        "T3": ["107","110","111","121","122","123","124","128","208","209","210","237","317","318","325","326","337","338"],
        "T2": ["232","309","314","315","316","327","328","329"],
        "T1": ["310","311","312","313","330","331","332"],
    },
    "2023": {
        "T6": ["101","102"],
        "T5": ["103","104","113","114","115","116","117","118","129","130","205","206","207","219","220","221","222","223","224","238","239","240"],
        "T4": ["301","302","321","322","339","340"],
        "T3": ["105","106","107","108","109","110","111","112","119","121","122","123","124","128",
               "208","209","210","215","216","217","218","226","227","228","229","237",
               "303","304","305","318","319","320","323","324","325","337","338"],
        "T2": ["211","212","213","214","230","231","232","306","307","308","309","314","315","316","317","326","327","328","329"],
        "T1": ["310","311","312","313","330","331","332"],
    },
}

def get_zone_sections(year: str = None) -> dict:
    """返回指定赛季的 zone 映射。None 或 '2026' 返回当前映射。"""
    if year and year in ZONE_SECTIONS_BY_YEAR:
        return ZONE_SECTIONS_BY_YEAR[year]
    return ZONE_SECTIONS

SECTION_TO_TIER = {}
for tier, sections in ZONE_SECTIONS.items():
    for s in sections:
        SECTION_TO_TIER[s] = tier

# ═══════════════════════════════════════════
# 4级对手分类（统一使用 classify.py 的 KMeans 分级）
# ═══════════════════════════════════════════

from src.classify import (
    classify_opponent_tier as classify_opponent,
    S_TIER, A_TIER, B_TIER, C_TIER, DERBY_RIVALS,
)

def get_pricing_tier(opponent_name: str) -> str:
    """返回实际定价级别（含derby提升、A-/C-降价）。

    规则（基于2026赛季票务公告校准）：
    - B级德比(津门虎) → 使用A级定价(S_A)
    - A级降价(海港) → 使用A-级定价(S_Aminus)
    - C级深降(英博) → 使用C-级定价(S_Cminus)
    - 其余按对手分级正常映射
    """
    name = str(opponent_name).strip()
    level = classify_opponent(name)

    # Derby boost: B级德比→A级定价
    if level == "B" and any(t in name or name in t for t in DERBY_PRICE_BOOST):
        return "S_A"  # 使用A级基准价

    # A-minus: A级降价对手
    if level == "A" and any(t in name or name in t for t in A_MINUS_OPPONENTS):
        return "S_Aminus"

    # C-minus: C级深降对手
    if level == "C" and any(t in name or name in t for t in C_MINUS_OPPONENTS):
        return "S_Cminus"

    # Normal mapping
    return f"S_{level}"  # "S_S", "S_A", "S_B", "S_C"

# ═══════════════════════════════════════════
# P1.1 弹性矩阵（4级×6档）— 2024→2025跨年纯价格弹性修正
# ═══════════════════════════════════════════

# 2024→2025 同对手跨年验证 + 分层份额弹性分析：
#   T1 share弹性=0.25, T5 share弹性=0.24 — 低/高端均有中等敏感度
#   T2/T3 有升级效应(越贵越买)，T6 有凡勃伦效应
#   统一使用绝对值，反映价格敏感度排序
_OBSERVED_ELASTICITY_AB = {
    "T1": 0.25,   # 低价买家对涨价值敏感（SA→BC份额-15.5%）
    "T2": 0.20,   # 中档有一定敏感度
    "T3": 0.15,   # 温和敏感
    "T4": 0.15,   # 样本小，保守估计
    "T5": 0.24,   # 高端区同样敏感（SA→BC份额-10.8%）
    "T6": 0.16,   # VIP轻微敏感
}

# V8.1: 价格弹性随对手级别变化 — 基于 2023-2026 交易数据实证 (n=335 match-zones)
# 方法: 同级别内 log-log OLS 回归, ln(Q) = α + β·ln(P), ε = |β|
# B级基准: T1=0.26 T2=0.71 T3=0.60 T4=1.50 (31场/档位, 统计显著)
# C级 vs B: T2=2.08/0.71=2.9x T3=1.66/0.60=2.8x T4=2.42/1.50=1.6x → 综合≈2.0x
# S级: n=4(仅申花), ε=0.32(T1) vs B=0.26 → ratio≈1.2x, 样本不足保守用0.75x
# A级: 仅T1显著 ε=0.20 vs B=0.26 → ratio≈0.77x, 单zone置信度低保守用0.85x
TIER_ELASTICITY_MULTIPLIER = {
    "S_S": 0.75,      # S级德比：n=4, T1 ε=0.32 vs B=0.26 → ratio 1.23 (低置信度)
    "S_A": 0.85,      # A级强队：T1 ε=0.20 vs B=0.26 → ratio 0.77 (仅1zone显著)
    "S_Aminus": 0.90, # A级降价：无直接数据，略低于S_A
    "S_B": 1.00,      # B级：中性基准 (31场/档位, 实证锚定)
    "S_C": 2.00,      # C级弱队：6/6 zones显著, 弹性为B级2.0x+
    "S_Cminus": 2.50, # C级深降：无直接数据, C级2.0x基础上外推
}

def get_elasticity(zone_tier: str, opponent_level: str) -> float:
    """
    返回 zone_tier × opponent_level 的需求价格弹性。

    弧弹性定义：ε = (ΔQ/Q̄) / (ΔP/P̄)
    负值表示价格上升→需求下降。
    绝对值>1 = 有弹性（降价增收），<1 = 无弹性（涨价增收）。
    """
    base_eps = _OBSERVED_ELASTICITY_AB.get(zone_tier, 1.0)
    mult = TIER_ELASTICITY_MULTIPLIER.get(opponent_level, 1.0)
    return round(base_eps * mult, 2)

def build_elasticity_matrix() -> dict:
    """构建完整定价级别×6档弹性矩阵。"""
    matrix = {}
    for opp_level in ["S_S", "S_A", "S_Aminus", "S_B", "S_C", "S_Cminus"]:
        matrix[opp_level] = {}
        for zt in ZONE_TIERS:
            matrix[opp_level][zt] = get_elasticity(zt, opp_level)
    return matrix

# ═══════════════════════════════════════════
# P1.2 基准价矩阵（4级×6档）— 基于2026赛季票务公告校准
# ═══════════════════════════════════════════

# A级基准价 = 申花/成都/津门虎德比 等（260起）
# A-级基准价 = 海港 2026赛季降价（200起）  
# B级基准价 = 河南/深圳等中游（160起）
# C级基准价 = 海牛/西海岸等升班马（160起，同B）
# C-级基准价 = 英博 2026赛季深度降价（140起）
# 
# 数据来源：2026赛季国安官方票务公告（腾讯新闻/懂球帝转载）
#   R3 申花: 260/340/440/580/780/1380
#   R8 津门虎: 260起（德比→A级定价）
#   R10 英博: 140起
#   R11 海港: 200起
#   R12 海牛: 160起  
#   R14 河南: 160/220/300/460/540/1080
BASE_PRICES_A = {"T1": 260, "T2": 340, "T3": 440, "T4": 580, "T5": 780, "T6": 1380}
BASE_PRICES_A_MINUS = {"T1": 200, "T2": 260, "T3": 360, "T4": 500, "T5": 640, "T6": 1200}
BASE_PRICES_B = {"T1": 160, "T2": 220, "T3": 300, "T4": 460, "T5": 540, "T6": 1080}
BASE_PRICES_C_MINUS = {"T1": 140, "T2": 200, "T3": 260, "T4": 400, "T5": 480, "T6": 960}

# 观测到的A级相对B级各档溢价比例（2025真实数据）
_OBSERVED_A_PREMIUM = {
    "T1": 0.625,  # 260/160 - 1 = 62.5%
    "T2": 0.545,
    "T3": 0.467,
    "T4": 0.261,
    "T5": 0.444,
    "T6": 0.278,
}

# Derby对手价格提升规则（B级德比→使用A级基准价）
DERBY_PRICE_BOOST = ["天津津门虎"]

# A级降价对手（俱乐部2026赛季实际定价200起，非260起）
# 注：海港¥200定价经分析为badcase——ε=0.25时降23%仅拉5.7%量，营收净损18%
# 已移除海港，由优化器根据实际情境决定是否降价
A_MINUS_OPPONENTS = []

# C级深度降价对手（俱乐部2026赛季实际定价140起，非160起）
C_MINUS_OPPONENTS = ["大连英博海发", "大连英博"]

# S级在A级基础上的额外溢价（按zone衰减）
# C级在B级基础上的折扣
S_EXTRA_PREMIUM = 0.20    # 德比额外溢价20%（叠加在A级上）
C_DISCOUNT = 0.10         # 弱队折扣10%（相对B级）

# 死忠区/高端区 溢价衰减因子（基于观测到的A/B溢价比例）
# T1全量 → T6仅28%，衰减约55%
def _premium_dampen(zt: str) -> float:
    """将T1的溢价比例归一化到各zone tier。"""
    t1_ratio = _OBSERVED_A_PREMIUM["T1"]  # 0.625
    zt_ratio = _OBSERVED_A_PREMIUM.get(zt, 0.3)
    return zt_ratio / t1_ratio  # T1=1.0, T6=0.445

def build_price_matrix() -> dict:
    """
    构建定价矩阵（含特殊定价级别）。

    级别映射：
    - S_S  = S级标准（申花）= A级 × (1 + 0.20 × dampen)
    - S_A  = A级标准（成都、津门虎德比）= BASE_PRICES_A
    - S_Aminus = A级降价（海港）= BASE_PRICES_A_MINUS
    - S_B  = B级标准（河南、深圳等）= BASE_PRICES_B
    - S_C  = C级标准（海牛、西海岸等）= B级 × (1 - 0.10 × dampen)
    - S_Cminus = C级深降（英博）= BASE_PRICES_C_MINUS
    """
    matrix = {}
    for zt in ZONE_TIERS:
        damp = _premium_dampen(zt)
        a_price = BASE_PRICES_A[zt]
        b_price = BASE_PRICES_B[zt]

        # S: A基础上叠加德比溢价（衰减）
        s_price = round(a_price * (1 + S_EXTRA_PREMIUM * damp) / 10) * 10
        # C: B基础上折扣（衰减）
        c_price = round(b_price * (1 - C_DISCOUNT * damp) / 10) * 10

        for key in ("S_S", "S_A", "S_Aminus", "S_B", "S_C", "S_Cminus"):
            matrix[key] = matrix.get(key, {})

        matrix["S_S"][zt] = s_price
        matrix["S_A"][zt] = a_price
        matrix["S_Aminus"][zt] = BASE_PRICES_A_MINUS[zt]
        matrix["S_B"][zt] = b_price
        matrix["S_C"][zt] = c_price
        matrix["S_Cminus"][zt] = BASE_PRICES_C_MINUS[zt]

    return matrix

# ═══════════════════════════════════════════
# P1.3 死忠区锁定 + Zone差异化调价边界
# ═══════════════════════════════════════════

# 锁价规则
FROZEN_TIERS = {
    "fully_frozen": [],                  # VIP也已放开
    "limited_adjustment": [],           # T5也已放开
}

def is_tier_frozen(zone_tier: str, opponent_level: str) -> bool:
    """检查某档位在某对手级别下是否应锁价。"""
    if zone_tier in FROZEN_TIERS["fully_frozen"]:
        return True
    if zone_tier in FROZEN_TIERS["limited_adjustment"] and opponent_level != "S_S":
        return True
    return False

# ── Zone差异化调价边界 ──
# 每档有不同的角色定位，不能统一±30%
# 定义：{zone_tier: {pricing_tier: (min_mult, max_mult)}}
# min_mult/max_mult = 相对基准价的倍数，如0.80表示可降20%，1.20表示可涨20%

ZONE_ADJUSTMENT_BOUNDS = {
    # T1: 量价锚 — 低价抢量，可降可涨
    "T1": {
        "S_S": (0.90, 1.10),
        "S_A": (0.85, 1.05),
        "S_Aminus": (0.85, 1.05),
        "S_B": (0.80, 1.10),
        "S_C": (0.72, 1.05),
        "S_Cminus": (0.72, 1.05),
    },
    # T2: 量价支撑 — 弹性驱动
    "T2": {
        "S_S": (0.95, 1.25),
        "S_A": (0.85, 1.20),
        "S_Aminus": (0.85, 1.20),
        "S_B": (0.80, 1.20),
        "S_C": (0.85, 1.20),
        "S_Cminus": (0.85, 1.20),
    },
    # T3: 弹性区 — 双向均衡
    "T3": {
        "S_S": (0.95, 1.20),
        "S_A": (0.85, 1.20),
        "S_Aminus": (0.85, 1.20),
        "S_B": (0.80, 1.20),
        "S_C": (0.85, 1.20),
        "S_Cminus": (0.85, 1.20),
    },
    # T4: 四层中间 — 弹性跟随
    "T4": {
        "S_S": (0.95, 1.15),
        "S_A": (0.90, 1.15),
        "S_Aminus": (0.90, 1.15),
        "S_B": (0.85, 1.15),
        "S_C": (0.85, 1.10),
        "S_Cminus": (0.85, 1.10),
    },
    # T5: 收入锚 — 高价创收，可涨可降
    "T5": {
        "S_S": (0.95, 1.25),
        "S_A": (0.90, 1.20),
        "S_Aminus": (0.90, 1.20),
        "S_B": (0.85, 1.15),
        "S_C": (0.85, 1.10),
        "S_Cminus": (0.85, 1.10),
    },
    # T6: 收入锚 — VIP创收
    "T6": {
        "S_S": (0.95, 1.25),
        "S_A": (0.90, 1.20),
        "S_Aminus": (0.90, 1.20),
        "S_B": (0.85, 1.15),
        "S_C": (0.85, 1.10),
        "S_Cminus": (0.85, 1.10),
    },
}

def get_zone_bounds(zone_tier: str, opponent_level: str) -> tuple[float, float]:
    """返回 (min_multiplier, max_multiplier) 相对基准价。"""
    valid_levels = ('S_S','S_A','S_Aminus','S_B','S_C','S_Cminus')
    level = opponent_level if opponent_level in valid_levels else 'S_B'
    return ZONE_ADJUSTMENT_BOUNDS.get(zone_tier, {}).get(level, (0.70, 1.50))

# ═══════════════════════════════════════════
# 汇总输出
# ═══════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("P1.1 弹性矩阵 (6定价级别×6档)")
    print("=" * 60)
    em = build_elasticity_matrix()
    levels = ["S_S","S_A","S_Aminus","S_B","S_C","S_Cminus"]
    header = f"{'':>6}" + "".join(f"{lvl:>10}" for lvl in levels)
    print(header)
    for zt in ZONE_TIERS:
        row = f"{zt:>6}" + "".join(f"{em[lvl][zt]:>10.2f}" for lvl in levels)
        print(row)

    print("\n" + "=" * 60)
    print("P1.2 基准价矩阵 (6定价级别×6档, ¥)")
    print("=" * 60)
    pm = build_price_matrix()
    print(f"{'':>6}" + "".join(f"{lvl:>10}" for lvl in levels))
    for zt in ZONE_TIERS:
        row = f"{zt:>6}" + "".join(f"¥{pm[lvl][zt]:>9.0f}" for lvl in levels)
        print(row)

    print("\n" + "=" * 60)
    print("定价级别映射测试")
    print("=" * 60)
    test_opponents = ["上海申花", "成都蓉城", "上海海港", "天津津门虎", 
                      "河南", "青岛海牛", "大连英博", "大连英博海发",
                      "山东泰山", "武汉三镇", "深圳新鹏城", "浙江"]
    for opp in test_opponents:
        pt = get_pricing_tier(opp)
        lvl = classify_opponent(opp)
        t1 = pm[pt]["T1"]
        print(f"  {opp:12s} 分类={lvl} 定价={pt:10s} T1=¥{t1}")

    print("\n" + "=" * 60)
    print("P1.3 锁价规则")
    print("=" * 60)
    for zt in ZONE_TIERS:
        status = []
        if zt in FROZEN_TIERS["fully_frozen"]:
            status.append("🔒 全锁")
        elif zt in FROZEN_TIERS["limited_adjustment"]:
            status.append("🔐 S级可微调")
        else:
            status.append("🔓 可调")
        print(f"  {zt}: {', '.join(status)}")
