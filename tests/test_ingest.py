import pathlib

import pandas as pd
import pytest

from src.ingest import (
    aggregate_user_purchases_by_price,
    build_match_price_demand,
    crosscheck_seat_demand_vs_user_purchases,
    load_all,
    load_pricing_table,
    load_user_purchases_by_price,
    parse_price_from_ticket_info,
    parse_section_from_seat,
    parse_user_quantity,
)

_PRICING_XLSX = pathlib.Path("data/raw/座位价格.xlsx")
_SEAT_XLSX = pathlib.Path("data/raw/2025散票数据.xlsx")
_USER_XLSX = pathlib.Path("data/raw/25年散票用户购买记录更新.xlsx")


@pytest.mark.skipif(not _PRICING_XLSX.exists(), reason="缺少 data/raw/座位价格.xlsx")
def test_load_pricing_table():
    df = load_pricing_table("data/raw/座位价格.xlsx")
    assert len(df) == 86
    assert "区域编号" in df.columns
    assert "A类赛事票价（元）" in df.columns
    assert df[df["区域编号"] == 101]["A类赛事票价（元）"].values[0] == 1380


def test_parse_section_standard():
    assert parse_section_from_seat("130区") == "130"
    assert parse_section_from_seat("130区-1排1座") == "130"
    assert parse_section_from_seat("310区-5排10座") == "310"


def test_parse_section_vip():
    assert parse_section_from_seat("10号门-南侧06包厢-1排1座") == "vip"
    assert parse_section_from_seat("18号门-主席台-5排5座") == "vip"


def test_build_match_price_demand():
    # 用模拟数据测试
    seat_data = pd.DataFrame(
        {
            "match": ["2025-03-29 北京国安 VS 成都蓉城"] * 3,
            "section": ["130", "310", "vip"],
            "ticket_type": ["散票"] * 3,
            "match_id": ["2025-03-29 成都蓉城"] * 3,
            "match_tier": ["A", "A", "A"],
        }
    )
    pricing = pd.DataFrame(
        {
            "区域编号": [130, 310, 101],
            "A类赛事票价（元）": [780, 340, 1380],
            "B类赛事票价（元）": [540, 220, 1080],
        }
    )
    result = build_match_price_demand(seat_data, pricing)
    assert len(result) == 3
    assert "price" in result.columns
    assert "quantity" in result.columns


def test_parse_user_quantity():
    assert parse_user_quantity("2") == 2.0
    assert parse_user_quantity("1#340.00") == 1.0
    assert parse_user_quantity(3) == 3.0


def test_parse_price_from_ticket_info():
    assert parse_price_from_ticket_info("340") == 340.0
    assert parse_price_from_ticket_info("¥780.00") == 780.0
    assert parse_price_from_ticket_info("散票 1380 元") == 1380.0


def test_aggregate_user_purchases_by_price():
    df = pd.DataFrame(
        {"qty_clean": [1.0, 2.0, 1.0], "unit_price": [340.0, 340.0, 780.0]}
    )
    agg = aggregate_user_purchases_by_price(df)
    row340 = agg.loc[(agg["price"] - 340).abs() < 1e-6, "quantity"].iloc[0]
    row780 = agg.loc[(agg["price"] - 780).abs() < 1e-6, "quantity"].iloc[0]
    assert row340 == 3.0
    assert row780 == 1.0


def test_crosscheck_seat_demand_vs_user_purchases():
    seat_demand = pd.DataFrame(
        {
            "match_id": ["2025-01-01 A", "2025-01-02 B"],
            "match_tier": ["A", "A"],
            "price": [340, 340],
            "quantity": [10, 5],
        }
    )
    user_by_price = pd.DataFrame({"price": [340.0], "quantity": [12.0]})
    cc = crosscheck_seat_demand_vs_user_purchases(seat_demand, user_by_price)
    r = cc.loc[(cc["price"] - 340).abs() < 1e-6].iloc[0]
    assert r["qty_seat"] == 15.0
    assert r["qty_user"] == 12.0
    assert r["abs_diff"] == 3.0


@pytest.mark.skipif(
    not (_PRICING_XLSX.exists() and _SEAT_XLSX.exists() and _USER_XLSX.exists()),
    reason="缺少完整三份 raw xlsx，跳过对账集成测试",
)
def test_crosscheck_integration_three_files():
    demand = load_all("data/raw")
    user = load_user_purchases_by_price(str(_USER_XLSX))
    cc = crosscheck_seat_demand_vs_user_purchases(demand, user)
    assert len(cc) > 0
    # 全季座位出票 vs 用户流水不应完全相等，但应对得上大部分价格点
    assert cc["qty_seat"].sum() > 0 and cc["qty_user"].sum() > 0
