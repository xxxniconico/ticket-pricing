#!/usr/bin/env python3
"""MCP 数据自动化加载 — 替代手动 JSON

从 MCP guoan-football 服务拉取历史比赛数据并合并到 ELO 引擎。
运行时自动检测是否有新数据。
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

MCP_HISTORY_PATH = Path("data/processed/mcp_history_full.json")

def load_mcp_history():
    """加载已缓存的 MCP 历史数据。"""
    if MCP_HISTORY_PATH.exists():
        with open(MCP_HISTORY_PATH) as f:
            return json.load(f)
    return []

def merge_into_elo(mcp_matches):
    """将 MCP 历史比赛合并到 ELO 引擎。"""
    from src.csl_context import load_csl_data
    from src.opponent_rating import compute_elo_history, save_elo_history
    
    matches, _, _ = load_csl_data()
    existing = {(m["date"], m["home"], m["away"]) for m in matches}
    
    added = 0
    for mcp in mcp_matches:
        key = (mcp["date"], mcp["home"], mcp["away"])
        if key not in existing:
            matches.append({
                "date": mcp["date"], "round": f"MCP-{mcp['date'][:4]}",
                "home": mcp["home"], "away": mcp["away"],
                "hg": mcp["hg"], "ag": mcp["ag"],
                "completed": True, "source": "mcp_history",
            })
            existing.add(key)
            added += 1
    
    elo = compute_elo_history(matches)
    save_elo_history(elo)
    return added

if __name__ == "__main__":
    mcp_data = load_mcp_history()
    added = merge_into_elo(mcp_data)
    print(f"MCP auto-load: {added} new matches merged")
