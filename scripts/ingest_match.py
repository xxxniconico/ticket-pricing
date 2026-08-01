#!/usr/bin/env python3
"""导入单场购买记录到 parquet。

用法:
  python scripts/ingest_match.py <excel_path>

规则（硬编码，每次导入自动执行）：
  1. 排除客队球迷专享（场次名称含「客队」）
  2. 排除退票/退款（订单状态含「退票」或「退款」）
  3. 自动去重（同 match_id 替换旧数据）
  4. 重建 user_stats + match_features

流程:
  1. 解析 Excel（票价信息、座位信息）
  2. 过滤客队 + 退票
  3. 检查是否已存在（去重）
  4. 追加到 all_unified.parquet
  5. 重建 user_stats + match_features
"""
import pandas as pd, numpy as np, re, json, sys, shutil
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data/raw/2026/match_files"
PROCESSED_DIR = ROOT / "data/processed"
PROCESSED_DIR.mkdir(exist_ok=True)

def parse_price_info(price_info: str):
    """解析票价信息: '160.00*1', '300.00*2', '160.00*3#220.00'"""
    s = str(price_info).strip()
    price = 0.0; qty = 1
    m = re.search(r"(\d+\.?\d*)", s)
    if m: price = float(m.group(1))
    if "*" in s:
        after = s.split("*", 1)[1]
        qm = re.search(r"(\d+)", after)
        if qm: qty = int(qm.group(1))
    elif "#" in s:
        before = s.split("#", 1)[0]
        qty = int(float(before))
    return price, qty

def ingest_match(excel_path: str, competition: str = "CSL"):
    """导入单场比赛 Excel

    Args:
        excel_path: 大麦导出的 Excel 路径
        competition: 赛事类型，默认 "CSL"。亚冠等非联赛场次必须显式传入
                     （如 ingest_match(path, "ACL")），否则会污染 CSL 历史统计
    """
    path = Path(excel_path)
    if not path.exists():
        print(f"ERROR: {path} not found")
        sys.exit(1)
    
    df = pd.read_excel(path)
    # Drop unnamed columns
    unnamed_cols = [c for c in df.columns if str(c).startswith("Unnamed")]
    if unnamed_cols:
        df = df.drop(columns=unnamed_cols)
    
    total_rows = len(df)
    
    # ── 过滤规则 ──
    # 1. 排除客队球迷专享
    away_mask = df["场次名称"].astype(str).str.contains("客队")
    away_count = away_mask.sum()
    if away_count > 0:
        print(f"  🚫 排除客队门票: {away_count} 行")
        df = df[~away_mask]
    
    # 2. 排除退票/退款
    if "订单状态" in df.columns:
        refund_mask = df["订单状态"].astype(str).str.contains("退票|退款")
        refund_count = refund_mask.sum()
        if refund_count > 0:
            print(f"  🚫 排除退票/退款: {refund_count} 行")
            df = df[~refund_mask]
    
    print(f"导入: {path.name} ({total_rows} 行 → {len(df)} 行有效)")
    
    # Parse
    rows = []
    for _, r in df.iterrows():
        match_name = str(r["场次名称"])
        uid = str(r["大麦用户id"])
        price_info = str(r["票价信息"])
        payment = float(r["实际支付价格"])
        seat_info = str(r.get("座位信息", "")) if pd.notna(r.get("座位信息")) else ""
        
        price, qty = parse_price_info(price_info)
        
        # Extract date/opponent from match name
        date_m = re.search(r"(\d{4}-\d{2}-\d{2})", match_name)
        date = date_m.group(1) if date_m else ""
        opp_m = re.search(r"VS(.+?)(?:）|\)|$)", match_name)
        opponent_raw = opp_m.group(1).strip() if opp_m else ""
        # Clean opponent name: strip sponsor/club suffixes
        opponent = re.sub(r"(队俱乐部|俱乐部|足球俱乐部|队).*$", "", opponent_raw) if opponent_raw else ""
        if not opponent:
            opponent = opponent_raw  # fallback
        
        seats = [s.strip() for s in seat_info.split("|") if s.strip()] if seat_info else [""]
        
        for seat in seats:
            per_pay = payment / qty if qty > 0 else payment
            
            # Parse seat: floor/section/row/seat
            floor = 0; section = 0; row_num = 0; seat_num = 0
            if seat:
                fm = re.search(r"(\w+)层", seat)
                sm = re.search(r"(\d+)区", seat)
                rm = re.search(r"(\d+)排", seat)
                s2 = re.search(r"(\d+)号", seat)
                floor_map = {"一":1,"二":2,"三":3,"四":4,"五":5}
                if fm:
                    for k,v in floor_map.items():
                        if k in fm.group(1): floor = v; break
                if sm: section = int(sm.group(1))
                if rm: row_num = int(rm.group(1))
                if s2: seat_num = int(s2.group(1))
            
            rows.append({
                "场次名称": match_name, "大麦用户id": uid,
                "票价信息": price_info, "实际支付价格": per_pay,
                "座位信息": seat,
                "match_date": date, "opponent": opponent,
                "is_home": True, "is_bundle": False,
                "match_id": f"{date}_{opponent}",
                "票名称": f"{price:.0f}元", "数量": 1,
                "floor": floor, "section": section,
                "row_num": row_num, "seat_num": seat_num,
                "match_tier": "", "competition": competition,
                "is_partial": False, "比赛": f"北京国安VS{opponent}",
                "md": pd.Timestamp(date)
            })
    
    new_df = pd.DataFrame(rows)
    match_id = new_df["match_id"].iloc[0]
    new_count = len(new_df)
    
    # Load existing parquet
    parquet_path = PROCESSED_DIR / "all_unified.parquet"
    if parquet_path.exists():
        existing = pd.read_parquet(parquet_path)
        existing_match = existing[existing["match_id"] == match_id]
        if len(existing_match) > 0:
            print(f"  ⚠️ {match_id} 已存在 {len(existing_match)} 条，替换为新数据")
            existing = existing[existing["match_id"] != match_id]
        merged = pd.concat([existing, new_df], ignore_index=True)
    else:
        merged = new_df
    
    merged.to_parquet(parquet_path, index=False)
    
    # Rebuild match_features
    mf = merged.groupby("match_id").agg(
        total_tickets=("数量", "sum"),
        unique_users=("大麦用户id", "nunique"),
        avg_spend=("实际支付价格", "mean"),
        section_count=("section", "nunique"),
        competition=("competition", "first"),
        front_row_pct=("row_num", lambda x: (x <= 15).mean()),
        one_floor_pct=("floor", lambda x: (x == 1).mean()),
    ).reset_index()
    mf.to_parquet(PROCESSED_DIR / "match_features.parquet", index=False)
    
    # Rebuild user_stats
    us = merged.groupby("大麦用户id").agg(
        total_tickets=("数量", "sum"), total_spend=("实际支付价格", "sum"),
        matches_attended=("match_id", "nunique"), avg_spend=("实际支付价格", "mean"),
        first_match=("match_date", "min"), last_match=("match_date", "max"),
    ).reset_index()
    us.to_parquet(PROCESSED_DIR / "user_stats.parquet", index=False)
    
    # Stats
    tickets = mf[mf["match_id"] == match_id]["total_tickets"].iloc[0]
    users = mf[mf["match_id"] == match_id]["unique_users"].iloc[0]
    avg = mf[mf["match_id"] == match_id]["avg_spend"].iloc[0]
    
    print(f"  ✅ {match_id}: {tickets:,} 票 · {users:,} 用户 · ¥{avg:,.0f}/人")
    print(f"  Parquet: {len(merged):,} 行 · {mf['match_id'].nunique()} 场")
    
    # Copy to match_files archive
    archive_path = DATA_DIR / f"{date}_{opponent}.xlsx"
    if path != archive_path:
        shutil.copy2(path, archive_path)
    
    return match_id

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_match.py <excel_path>")
        sys.exit(1)
    ingest_match(sys.argv[1], competition=comp)
