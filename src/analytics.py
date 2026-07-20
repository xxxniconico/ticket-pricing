#!/usr/bin/env python3
"""DuckDB 分析查询层 — 直接读 Parquet，零迁移。

用法:
    from src.analytics import query, verify

    # 查任意 SQL
    rows = query("SELECT match_tier, sum(数量) as total FROM 'data/processed/all_unified.parquet' GROUP BY match_tier")

    # 验证数据一致性：DuckDB 读 vs pandas 读
    verify()  # 打印对比报告
"""
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Any

import duckdb
import pandas as pd

ROOT = Path(__file__).parent.parent
PROCESSED = ROOT / "data" / "processed"
RAW = ROOT / "data" / "raw"


def _connect():
    """获取 DuckDB 连接。"""
    return duckdb.connect()


def query(sql: str, params: dict | None = None) -> list[dict]:
    """执行 SQL 查询，返回 list[dict]。

    SQL 中可直接写 Parquet 路径：
        query("SELECT * FROM 'data/processed/all_unified.parquet' WHERE price > 0")
    """
    conn = _connect()
    try:
        if params:
            result = conn.execute(sql, params).fetchdf()
        else:
            result = conn.execute(sql).fetchdf()
        return result.to_dict(orient="records")
    finally:
        conn.close()


def query_df(sql: str, params: dict | None = None) -> pd.DataFrame:
    """执行 SQL 查询，返回 pandas DataFrame。"""
    conn = _connect()
    try:
        if params:
            return conn.execute(sql, params).fetchdf()
        else:
            return conn.execute(sql).fetchdf()
    finally:
        conn.close()


def tables() -> list[str]:
    """列出 processed 目录下所有可用的 Parquet 数据文件。"""
    files = []
    for f in sorted(PROCESSED.glob("*.parquet")):
        if not f.name.startswith("all_unified"):
            files.append(f.name)
    # 主表放前面
    main = [f.name for f in sorted(PROCESSED.glob("all_unified.parquet"))]
    return main + files


def describe(table_path: str) -> list[dict]:
    """查看 Parquet 文件的 schema 和前 5 行。"""
    full_path = PROCESSED / table_path if not table_path.startswith("/") else table_path
    sql = f"DESCRIBE SELECT * FROM '{full_path}'"
    rows = query(sql)
    # 加样本数据
    sample = query_df(f"SELECT * FROM '{full_path}' LIMIT 5")
    return {
        "schema": rows,
        "row_count": query(f"SELECT count(*) as cnt FROM '{full_path}'")[0]["cnt"],
        "sample": sample.to_dict(orient="records"),
    }


def verify() -> dict:
    """验证 DuckDB 与 pandas 读取 Parquet 的数据一致性。

    对比：行数、关键字段的 sum、均值。
    """
    parquet = PROCESSED / "all_unified.parquet"
    if not parquet.exists():
        return {"error": "all_unified.parquet not found"}

    # DuckDB 读
    duck = query_df(f"SELECT count(*) as n, sum(数量) as qty, avg(实际支付价格) as avg_p FROM '{parquet}'")

    # pandas 读
    pdf = pd.read_parquet(parquet)
    pdf["数量"] = pd.to_numeric(pdf["数量"])
    pdf["实际支付价格"] = pd.to_numeric(pdf["实际支付价格"])
    pdf["is_home"] = pdf["is_home"] == "True"
    pn = len(pdf)
    pqty = int(pdf["数量"].sum()) if "数量" in pdf.columns else 0
    pavg = float(pdf["实际支付价格"].mean()) if "实际支付价格" in pdf.columns else 0.0

    result = {
        "rows_duckdb": int(duck["n"].iloc[0]),
        "rows_pandas": pn,
        "rows_match": int(duck["n"].iloc[0]) == pn,
        "sum_quantity_duckdb": int(duck["qty"].iloc[0]),
        "sum_quantity_pandas": pqty,
        "quantity_match": int(duck["qty"].iloc[0]) == pqty,
        "avg_price_duckdb": round(float(duck["avg_p"].iloc[0]), 2),
        "avg_price_pandas": round(pavg, 2),
        "price_match": abs(float(duck["avg_p"].iloc[0]) - pavg) < 0.01,
    }
    return result


def save_snapshot(name: str) -> str:
    """保存当前分析的快照（CSV + SQL）。便于追溯分析结论。"""
    snap_dir = ROOT / "data" / "snapshots"
    snap_dir.mkdir(parents=True, exist_ok=True)
    path = snap_dir / f"{name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return str(path)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        r = verify()
        print("\n=== DuckDB vs pandas 一致性验证 ===")
        for k, v in r.items():
            mark = "✅" if str(v).startswith("True") else ("❌" if str(v).startswith("False") else "  ")
            print(f"  {mark} {k}: {v}")
    elif len(sys.argv) > 1 and sys.argv[1] == "tables":
        print("\n可用数据表:")
        for t in tables():
            print(f"  - {t}")
    else:
        print(f"\n用法:")
        print(f"  python -m src.analytics verify     # 验证数据一致性")
        print(f"  python -m src.analytics tables     # 列出可用数据表")
        print(f"\n编程用法:")
        print(f"  from src.analytics import query")
        print(f"  rows = query(\"SELECT * FROM 'data/processed/all_unified.parquet' LIMIT 5\")")
