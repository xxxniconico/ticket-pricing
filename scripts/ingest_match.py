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
                "md": date
            })
    
    new_df = pd.DataFrame(rows)
    # 历史 parquet 全列 large_string（NaN 存 null）；新数据必须同风格，否则
    # object 列 str+float 混排导致 pyarrow ArrowTypeError
    new_df = new_df.astype("string")
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
    
    # Rebuild match_features（用数值化副本计算，原 merged 保持字符串风格供 parquet）
    num = merged.copy()
    for col in ["实际支付价格", "数量", "section", "floor", "row_num"]:
        if col in num.columns:
            num[col] = pd.to_numeric(num[col], errors="coerce")
    mf = num.groupby("match_id").agg(
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
    us = num.groupby("大麦用户id").agg(
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
    
    # 赛后自动校准（2026-08-03）：导入完成后补齐所有已赛未校准场次。
    # 校准不再依赖打开"历史定价"tab（原惰性触发导致浙江8/1等场次漏校准）
    try:
        import sys as _sys
        _sys.path.insert(0, str(ROOT))  # python scripts/ingest_match.py 时 scripts/ 在 path[0]，需根目录才能 import scripts.*
        from scripts.update_calibration import main as _calib_main
        _orig_argv = _sys.argv
        _sys.argv = ["update_calibration.py"]
        try:
            _calib_main()
        finally:
            _sys.argv = _orig_argv
    except Exception as e:
        print(f"  ⚠️ 赛后校准失败（不影响导入）: {e}")

    # 赛后动态分级自动刷新（2026-08-05）：整轮完成后重算 ELO/ST/AP/tier。
    # 16 队单循环每轮 8 场，最新轮已赛满 8 场才触发（延期轮不算）。
    # 兜底：cron 每天 03:15 也会跑 sync_csl_data.py。
    try:
        _refresh_tiers_after_round()
    except Exception as e:
        print(f"  ⚠️ 分级刷新失败（不影响导入）: {e}")

    return match_id


def _refresh_tiers_after_round():
    """检测最新轮是否完整（8场），完整则调 sync_csl_data.py 重算分级快照。"""
    import re as _re
    from collections import Counter as _Counter
    import subprocess as _sp

    cfl_path = Path("/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2/data/csl_final_production_ready.json")
    if not cfl_path.exists():
        print("  ℹ️ 分级刷新跳过: CFL 源不存在")
        return

    data = json.load(open(cfl_path))
    per_round = _Counter()
    for lg in data.get("leagues", []):
        if "中超" not in lg.get("name", ""):
            continue
        for m in lg.get("matches", []):
            s = m.get("score", {}) or {}
            if s.get("home") is None:
                continue
            r = m.get("round", "")
            if r.startswith("第"):
                per_round[r] += 1

    def _rn(r):
        mm = _re.search(r"(\d+)", r)
        return int(mm.group(1)) if mm else 0

    complete = [r for r, c in per_round.items() if c >= 8]
    if not complete:
        print("  ℹ️ 分级刷新跳过: 无完整轮")
        return
    latest_complete = max(complete, key=_rn)

    # 快照已覆盖轮次: 用最新快照的 as_of 日期 vs 该轮比赛最大日期
    snap_dir = Path("/home/xxxsuli/ticket-pricing/data/processed")
    snaps = sorted(snap_dir.glob("rating_snapshot_*.json"))
    if snaps:
        d = json.load(open(snaps[-1]))
        as_of = d.get("as_of", "")
        # 该轮最大比赛日期
        round_dates = [m["date"][:10] for lg in data.get("leagues", [])
                       if "中超" in lg.get("name", "")
                       for m in lg.get("matches", [])
                       if m.get("round") == latest_complete and (m.get("score") or {}).get("home") is not None]
        max_date = max(round_dates) if round_dates else ""
        if as_of >= max_date:
            print(f"  ℹ️ 分级已最新 (快照 {as_of} >= 轮末 {max_date})")
            return

    print(f"  🔄 最新完整轮 {latest_complete} 结束 → 刷新动态分级...")
    _sp.run(
        [sys.executable, "scripts/sync_csl_data.py"],
        cwd="/home/xxxsuli/ticket-pricing",
        timeout=300,
    )
    print(f"  ✅ 分级刷新完成: {latest_complete}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python scripts/ingest_match.py <excel_path> [CSL|ACL]")
        sys.exit(1)
    comp = sys.argv[2] if len(sys.argv) > 2 else "CSL"
    ingest_match(sys.argv[1], competition=comp)
