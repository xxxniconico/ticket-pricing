#!/usr/bin/env python3
"""场次备注管理: 添加/查看/删除修正"""
import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.match_notes import load_adjustments, add_adjustment, _ADJ_FILE

def list_all():
    adj = load_adjustments()
    if not adj:
        print("无修正记录\n")
        return
    print(f"{'场次':<25} {'修正':>8} {'调整后':>8}  备注")
    print("-" * 70)
    for mid, info in sorted(adj.items()):
        print(f"{mid:<25} {info['adjustment']:>+8} {info['adjusted_total']:>8}   {info['note']}")
    print(f"\n共 {len(adj)} 条")

def add(match_id, adjustment, note, adjusted_total=None):
    if adjusted_total is None:
        # auto-compute: need parquet data
        import pandas as pd
        ROOT = Path(__file__).parent.parent
        df = pd.read_parquet(ROOT/'data/processed/all_unified.parquet')
        raw = int(df[df['match_id']==match_id]['数量'].sum())
        adjusted_total = raw + adjustment
    add_adjustment(match_id, note, adjustment, adjusted_total)
    print(f"已添加: {match_id}")
    print(f"  修正: {adjustment:+d}")
    print(f"  调整后: {adjusted_total}")
    print(f"  备注: {note}")

def remove(match_id):
    adj = load_adjustments()
    if match_id in adj:
        del adj[match_id]
        import os
        data = {"_schema":"v1","matches":adj}
        os.makedirs(Path(_ADJ_FILE).parent, exist_ok=True)
        with open(_ADJ_FILE,'w') as f: json.dump(data,f,indent=2,ensure_ascii=False)
        print(f"已删除: {match_id}")
    else:
        print(f"未找到: {match_id}")

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法:")
        print("  python scripts/manage_notes.py list")
        print("  python scripts/manage_notes.py add <match_id> <adjustment> <备注>")
        print("  python scripts/manage_notes.py rm <match_id>")
        print("\n示例:")
        print("  python scripts/manage_notes.py add '2024-04-05 上海海港' 2000 '代理商票未计入'")
        sys.exit(0)
    
    cmd = sys.argv[1]
    if cmd == 'list':
        list_all()
    elif cmd == 'add':
        if len(sys.argv) < 5:
            print("用法: add <match_id> <adjustment> <备注>")
            sys.exit(1)
        mid = sys.argv[2]
        adj_val = int(sys.argv[3])
        note = sys.argv[4]
        add(mid, adj_val, note)
    elif cmd == 'rm':
        if len(sys.argv) < 3:
            print("用法: rm <match_id>")
            sys.exit(1)
        remove(sys.argv[2])
    else:
        print(f"未知命令: {cmd}")