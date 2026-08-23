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

def get_pricing_tier(opponent_name: str, match_date: str | None = None) -> str:
    """返回实际定价级别（含derby提升、A-/C-降价）。

    规则（基于2026赛季票务公告校准）：
    - B级德比(津门虎) → 使用A级定价(S_A)
    - A级降价(海港) → 使用A-级定价(S_Aminus)
    - C级深降(英博) → 使用C-级定价(S_Cminus)
    - 其余按对手分级正常映射

    Args:
        opponent_name: 对手队名
        match_date: 比赛日期 (YYYY-MM-DD)，提供后启用动态评分
    """
    name = str(opponent_name).strip()
    level = classify_opponent(name, match_date=match_date)

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
    "T5": 0.24,   # 高端区同样敏感（SA→BC份额-10.8%）【暂不回退0.43: 无干净实测数据】
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
    "S_C": 1.78,      # C级弱队：武汉6/27实测修正, 弹性为B级1.78x (原2.00)
    "S_Cminus": 2.50, # C级深降：无直接数据, C级2.0x基础上外推
}

# 实测弹性覆盖 (山东A级/武汉C级, 2026-06/07)
# 格式: {(opponent_level, zone_tier): epsilon}
_MANUAL_ELASTICITY_OVERRIDE = {
    ("S_A", "T3"): 0.20,   # 山东实测, T4分流轻微混杂
    ("S_A", "T5"): 0.42,   # 山东实测, 库存修正后 (迁移区弹性0.84, 比赛质量效应分离)
    ("S_C", "T5"): 0.43,   # 武汉实测+逻辑保留(用户确认)
}

_DYNAMIC_EPS_EXPONENT = 1.73  # T5专用, 待浙江实验后校准 (目前无干净数据点)

def get_dynamic_elasticity(zone_tier, price):
    """动态弹性：T5 幂律公式（待验证）。
    
    eps(p) = 0.24 * (p / 780)^1.73  [注意: 指数和参考点均未校准]
    
    ⚠ T5 价格弹性目前没有干净的实测数据:
    - 武汉 ¥540 vs ¥620: 同区不同排, 含质量溢价
    - 申花 vs 山东: 对手级别不同 (S vs A), 测的是级别效应不是价格效应
    - 迁移区: 价格+标签同时变, 混合信号
    
    浙江(8/1)后可设计 T5 弹性实验。在此之前用静态弹性 S_A=0.20。
    T1-T4/T6 返回 None, fallback 到 get_elasticity()。
    """
    if zone_tier != "T5":
        return None
    pref, epsref = 540, 0.43
    eps = epsref * (price / pref) ** _DYNAMIC_EPS_EXPONENT
    return round(max(0.01, eps), 2)

def get_t5_elasticity(price, level="S_A"):
    # 保留旧接口兼容
    return get_dynamic_elasticity("T5", price)

_OLD_MANUAL_ELASTICITY_OVERRIDE = {
    ("S_A", "T3"): 0.20,   # 山东实测, T4分流轻微混杂
    ("S_A", "T5"): 0.42,   # 山东实测, 库存修正后
    ("S_C", "T5"): 0.43,   # 武汉实测+逻辑保留(用户确认)
}

def get_elasticity(zone_tier: str, opponent_level: str) -> float:
    """
    返回 zone_tier × opponent_level 的需求价格弹性。

    弧弹性定义：ε = (ΔQ/Q̄) / (ΔP/P̄)
    负值表示价格上升→需求下降。
    绝对值>1 = 有弹性（降价增收），<1 = 无弹性（涨价增收）。
    """
    override = _MANUAL_ELASTICITY_OVERRIDE.get((opponent_level, zone_tier))
    if override is not None:
        return override
    base_eps = _OBSERVED_ELASTICITY_AB.get(zone_tier, 1.0)
    mult = TIER_ELASTICITY_MULTIPLIER.get(opponent_level, 1.0)
    return round(base_eps * mult, 2)


# 保留旧接口兼容性: 无价格时返回基准弹性(用于显示)
def get_elasticity_static(zone_tier: str, opponent_level: str) -> float:
    """静态弹性(兼容旧代码, 无价格参数时使用)"""
    override = _MANUAL_ELASTICITY_OVERRIDE.get((opponent_level, zone_tier))
    if override is not None:
        return override
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



def v10_volume_shares(predicted_total: float, summer: bool = False) -> dict:
    """V10 档位份额模型（单一事实源，dynamic_optimizer 与 rule_engine 共用）。

    T1-T3: 按预测上座 P 分段 (2025+2026 25场票名称校准)
    T4+T5 合并 = 13.4% (山东13.6% + 辽宁13.2% 平均, 2026-07结构调整后)
    ⚠️ 暑期(7-8月)场 t45=0.15（3样本: 浙江15.2%/深圳14.9%/云南16.2%，2026-08-23 云南确认落地）
    T4 内部占比: 三点分段线性（辽宁P=7362→0.508 / 云南P=11179→0.535 / 山东P=12956→0.662，
       相邻两点插值+端点封顶保守外推；原两点线性在 P=9-12k 高估 ~5-8pp）
    返回归一化份额（各档占比合计=1）。
    """
    P = float(predicted_total)
    if P >= 11000:
        t1, t2, t3 = 0.260, 0.270, 0.320
    elif P >= 8000:
        t1, t2, t3 = 0.370, 0.220, 0.290
    elif P >= 5000:
        t1, t2, t3 = 0.480, 0.130, 0.270
    else:
        t1, t2, t3 = 0.530, 0.080, 0.260
    t45 = 0.15 if summer else 0.134  # 暑期场 T4+T5 合并份额（非暑期 13.4%）
    # T4 内部占比: 三点分段线性（相邻两点插值，端点外保守封顶）
    if P <= 7362:
        t4_ratio = 0.508
    elif P <= 11179:
        t4_ratio = 0.508 + (P - 7362) * (0.535 - 0.508) / (11179 - 7362)
    elif P <= 12956:
        t4_ratio = 0.535 + (P - 11179) * (0.662 - 0.535) / (12956 - 11179)
    else:
        t4_ratio = 0.662
    t4_ratio = max(0.45, min(0.70, t4_ratio))
    raw = {
        "T1": t1, "T2": t2, "T3": t3,
        "T4": t45 * t4_ratio,
        "T5": t45 * (1 - t4_ratio),
        "T6": 0.006,
    }
    s = sum(raw.values())
    return {zt: raw[zt] / s for zt in ZONE_TIERS}

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

# ═══════════════════════════════════════════
# P1.1b 动态弹性表 — 赛后迭代更新
# ═══════════════════════════════════════════

import json as _json
from pathlib import Path as _Path

_ELASTICITY_TABLE_PATH = _Path(__file__).resolve().parent.parent / "data" / "processed" / "elasticity_table.json"

def load_elasticity_table() -> dict:
    """加载动态弹性表。无文件时从代码初始化。"""
    if _ELASTICITY_TABLE_PATH.exists():
        with open(_ELASTICITY_TABLE_PATH) as f:
            return _json.load(f)
    return _init_elasticity_table()

def _init_elasticity_table() -> dict:
    """从代码静态参数初始化弹性表。"""
    table = {
        'version': 1,
        'updated_at': 'init',
        'method': 'Initialized from pricing_v5 static parameters',
        'elasticity': {}
    }
    for lvl in ["S_S", "S_A", "S_Aminus", "S_B", "S_C", "S_Cminus"]:
        table['elasticity'][lvl] = {}
        for zt in ZONE_TIERS:
            table['elasticity'][lvl][zt] = round(get_elasticity(zt, lvl), 3)
    table['observations'] = []
    return table

def save_elasticity_table(table: dict):
    """持久化动态弹性表。"""
    _ELASTICITY_TABLE_PATH.parent.mkdir(parents=True, exist_ok=True)
    from datetime import datetime
    table['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
    table['version'] = table.get('version', 1) + 1
    with open(_ELASTICITY_TABLE_PATH, 'w') as f:
        _json.dump(table, f, ensure_ascii=False, indent=2)

def compute_observed_elasticity(confirmed_price: float, baseline_price: float,
                                 actual_qty: float, baseline_qty: float) -> float | None:
    """计算弧弹性: ε = (ΔQ/Q_avg) / (ΔP/P_avg)。价格不变时返回 None。"""
    dp = confirmed_price - baseline_price
    if abs(dp) < 1:
        return None  # No price change, no elasticity observation
    dq = actual_qty - baseline_qty
    p_avg = (confirmed_price + baseline_price) / 2
    q_avg = (actual_qty + baseline_qty) / 2
    if p_avg <= 0 or q_avg <= 0:
        return None
    return round(abs((dq / q_avg) / (dp / p_avg)), 4)

def update_elasticity_from_match(match_date: str, opponent: str, pricing_level: str,
                                  confirmed_prices: dict, baseline_prices: dict,
                                  actual_qtys: dict, baseline_qtys: dict):
    """赛后记录弹性观测（待审批模式）。
    
    观测写入 pending_observations，不自动更新弹性值。
    需调用 approve_elasticity_observation() 手动确认后才生效。
    
    原因：弧弹性会被库存重组/样本噪声污染，需要人工判断哪些观测有效。
    """
    table = load_elasticity_table()
    from datetime import datetime
    
    for zt in ZONE_TIERS:
        cp = confirmed_prices.get(zt, 0)
        bp = baseline_prices.get(zt, 0)
        aq = actual_qtys.get(zt, 0)
        bq = baseline_qtys.get(zt, 0)
        
        obs_eps = compute_observed_elasticity(cp, bp, aq, bq)
        if obs_eps is None:
            continue
        
        # 质量标记：数量变化方向与价格变化方向一致（涨价→减量, 降价→增量）
        dp = cp - bp
        dq = actual_qtys.get(zt, 0) - baseline_qtys.get(zt, 0)
        direction_ok = (dp > 0 and dq < 0) or (dp < 0 and dq > 0)
        
        # 异常标记：弹性>3.0 或数量偏差>80% 通常是库存效应
        is_anomaly = obs_eps > 3.0 or (bq > 50 and abs(dq) / bq > 0.8)
        
        obs = {
            'match': f'{match_date}_{opponent}',
            'level': pricing_level,
            'tier': zt,
            'confirmed_price': cp,
            'baseline_price': bp,
            'actual_qty': aq,
            'baseline_qty': bq,
            'observed_eps': obs_eps,
            'direction_ok': direction_ok,
            'likely_anomaly': is_anomaly,
            'recorded_at': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'status': 'pending',
        }
        table.setdefault('pending_observations', []).append(obs)
    
    save_elasticity_table(table)
    return table

def approve_elasticity_observation(match_key: str, tier: str, approved: bool = True, manual_eps: float | None = None):
    """审批弹性观测。approved=True 时 EMA 更新到弹性表。
    
    Args:
        match_key: 如 '2026-07-04_山东泰山'
        tier: 如 'T5'
        approved: 是否批准
        manual_eps: 手动指定弹性值（不批准时忽略，批准时覆盖观测值）
    """
    table = load_elasticity_table()
    
    for obs in table.get('pending_observations', []):
        if obs['match'] == match_key and obs['tier'] == tier and obs['status'] == 'pending':
            obs['status'] = 'approved' if approved else 'rejected'
            
            if approved:
                eps_value = manual_eps if manual_eps is not None else obs['observed_eps']
                level = obs['level']
                old_eps = table['elasticity'].get(level, {}).get(tier, 1.0)
                alpha = 0.3
                new_eps = round(alpha * eps_value + (1 - alpha) * old_eps, 4)
                new_eps = max(0.01, min(5.0, new_eps))
                
                if level not in table['elasticity']:
                    table['elasticity'][level] = {}
                table['elasticity'][level][tier] = new_eps
                
                obs['approved_eps'] = eps_value
                obs['new_eps'] = new_eps
                obs['old_eps'] = old_eps
            
            table.setdefault('approved_observations', []).append(obs)
            # Remove from pending
            table['pending_observations'] = [o for o in table['pending_observations'] if not (o['match'] == match_key and o['tier'] == tier)]
            
            save_elasticity_table(table)
            return True
    
    return False

def get_dynamic_elasticity_value(pricing_level: str, zone_tier: str) -> float:
    """从动态弹性表读取当前最佳估计值。"""
    table = load_elasticity_table()
    return table.get('elasticity', {}).get(pricing_level, {}).get(zone_tier, 1.0)
