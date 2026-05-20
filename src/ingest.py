"""数据摄入：座位级 + 官方定价 → (场次, 价格, 销量)。

第三份「用户购买记录」无场次，不参与弹性主链；仅提供按票面价的聚合与对账。
"""
import re

import numpy as np
import pandas as pd

# === A级对手列表（2025-2026） ===
A_TIER_OPPONENTS = {"成都蓉城", "山东泰山", "上海海港", "上海申花"}


def load_pricing_table(filepath: str = "data/raw/座位价格.xlsx") -> pd.DataFrame:
    """加载官方定价表"""
    df = pd.read_excel(filepath)
    df["区域编号"] = df["区域编号"].astype(int)
    return df


def parse_section_from_seat(seat_info: str) -> str:
    """从座位信息提取区段编号或特殊类型

    Returns:
        "101"~"340" 表示标准区段
        "vip"        表示包厢/主席台
    """
    if not isinstance(seat_info, str):
        return "unknown"

    # 包厢 / 主席台
    if "包厢" in seat_info or "主席台" in seat_info:
        return "vip"

    # 标准数字区: "130区" 或 "130区-1排1座"
    m = re.search(r"(\d+)区", seat_info)
    if m:
        return m.group(1)

    return "unknown"


def load_seat_data(filepath: str = "data/raw/2025散票数据.xlsx") -> pd.DataFrame:
    """加载座位级出票数据，清洗并提取关键字段"""
    df = pd.read_excel(filepath)

    # 只保留散票（排除年卡、商务年卡、客队票）
    df = df[df["票名称"].isin(["散票", "两场通票"])].copy()

    # 解析比赛信息
    df["match_date"] = df["比赛"].str.extract(r"(\d{4}-\d{2}-\d{2})")[0]
    df["opponent"] = df["比赛"].str.extract(r"VS\s+(.+)$")[0]
    df["match_id"] = df["match_date"] + " " + df["opponent"]

    # 解析区段
    df["section"] = df["座位信息"].apply(parse_section_from_seat)

    # 判断A/B级
    df["match_tier"] = df["opponent"].apply(
        lambda x: "A" if any(o in str(x) for o in A_TIER_OPPONENTS) else "B"
    )

    return df


def build_match_price_demand(
    seat_data: pd.DataFrame,
    pricing: pd.DataFrame,
) -> pd.DataFrame:
    """合并座位数据+定价表 → (场次, 价格, 销量) 聚合

    Returns DataFrame columns:
        match_id, match_tier, price, quantity
    """
    seat_data = seat_data.copy()

    # 构建区段→价格映射
    section_price_a = dict(
        zip(pricing["区域编号"].astype(str), pricing["A类赛事票价（元）"])
    )
    section_price_b = dict(
        zip(pricing["区域编号"].astype(str), pricing["B类赛事票价（元）"])
    )

    # VIP特殊处理
    section_price_a["vip"] = 1380
    section_price_b["vip"] = 1080

    # 给每行分配价格
    prices = []
    for _, row in seat_data.iterrows():
        sec = str(row["section"])
        if row["match_tier"] == "A":
            prices.append(section_price_a.get(sec, 0))
        else:
            prices.append(section_price_b.get(sec, 0))

    seat_data["price"] = prices

    # 过滤掉未匹配价格的记录
    seat_data = seat_data[seat_data["price"] > 0]

    # 按场次+价格聚合销量
    demand = (
        seat_data.groupby(["match_id", "match_tier", "price"])
        .size()
        .reset_index(name="quantity")
    )

    return demand


def load_all(data_dir: str = "data/raw") -> pd.DataFrame:
    """一键加载+合并，返回统一DataFrame"""
    pricing = load_pricing_table(f"{data_dir}/座位价格.xlsx")
    seats = load_seat_data(f"{data_dir}/2025散票数据.xlsx")
    demand = build_match_price_demand(seats, pricing)
    return demand


def parse_user_quantity(raw) -> float:
    """解析用户表「数量」：含少量 ``1#340.00`` 类异常，取 # 前为件数。"""
    if pd.isna(raw):
        return float("nan")
    s = str(raw).strip()
    if "#" in s:
        s = s.split("#", 1)[0].strip()
    s = re.sub(r"[^\d.+-]", "", s)
    if not s or s in "+-.":
        return float("nan")
    try:
        return float(s)
    except ValueError:
        return float("nan")


def parse_price_from_ticket_info(raw) -> float:
    """从「票价信息」中提取票面单价（元），取串中满足 >=100 的最大整数作为票价。"""
    if pd.isna(raw):
        return float("nan")
    nums = [int(m) for m in re.findall(r"\d+", str(raw))]
    if not nums:
        return float("nan")
    big = [n for n in nums if n >= 100]
    return float(max(big) if big else max(nums))


def load_user_purchases(
    filepath: str = "data/raw/25年散票用户购买记录更新.xlsx",
) -> pd.DataFrame:
    """加载用户级购买记录（无场次），增加清洗列 ``qty_clean``、``unit_price``。"""
    df = pd.read_excel(filepath)
    out = df.copy()
    out["qty_clean"] = out["数量"].apply(parse_user_quantity)
    out["unit_price"] = out["票价信息"].apply(parse_price_from_ticket_info)
    return out


def aggregate_user_purchases_by_price(df: pd.DataFrame) -> pd.DataFrame:
    """按票面价聚合用户侧购票张数。列: price, quantity"""
    d = df.dropna(subset=["unit_price", "qty_clean"])
    g = d.groupby("unit_price", as_index=False)["qty_clean"].sum()
    return g.rename(columns={"unit_price": "price", "qty_clean": "quantity"})


def load_user_purchases_by_price(
    filepath: str = "data/raw/25年散票用户购买记录更新.xlsx",
) -> pd.DataFrame:
    """读取用户购买 Excel → 按 price 汇总 quantity。"""
    return aggregate_user_purchases_by_price(load_user_purchases(filepath))


def crosscheck_seat_demand_vs_user_purchases(
    seat_demand: pd.DataFrame,
    user_by_price: pd.DataFrame,
) -> pd.DataFrame:
    """按票面价对账：座位级聚合（全季、跨场次） vs 用户交易汇总。

    返回列: price, qty_seat, qty_user, abs_diff, rel_diff_user
    （二者口径不同，仅作数据质量参考，不用于拟合。）
    """
    seat = seat_demand.groupby("price", as_index=False)["quantity"].sum()
    seat = seat.rename(columns={"quantity": "qty_seat"})
    seat["price"] = seat["price"].astype(float)
    user = user_by_price.rename(columns={"quantity": "qty_user"}).copy()
    user["price"] = user["price"].astype(float)
    merged = seat.merge(user, on="price", how="outer").fillna(0.0)
    merged["abs_diff"] = merged["qty_seat"] - merged["qty_user"]
    merged["rel_diff_user"] = merged["abs_diff"] / merged["qty_user"].replace(0, np.nan)
    return merged.sort_values("price")
