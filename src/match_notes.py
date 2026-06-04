"""场次备注与数量修正加载器"""
import json, os
from pathlib import Path

_ADJ_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "match_adjustments.json")

def load_adjustments() -> dict:
    """加载场次修正表，返回 {match_id: {note, adjustment, adjusted_total}}"""
    if not os.path.exists(_ADJ_FILE):
        return {}
    with open(_ADJ_FILE) as f:
        data = json.load(f)
    return data.get("matches", {})

def get_adjusted_actual(match_id: str, raw_actual: int) -> int:
    """获取调整后的实际散票数"""
    adj = load_adjustments()
    if match_id in adj:
        return adj[match_id].get("adjusted_total", raw_actual)
    return raw_actual

def get_note(match_id: str) -> str:
    """获取场次备注"""
    adj = load_adjustments()
    if match_id in adj:
        return adj[match_id].get("note", "")
    return ""

def add_adjustment(match_id: str, note: str, adjustment: int, adjusted_total: int):
    """添加/更新一条修正"""
    adj = load_adjustments()
    adj[match_id] = {"note": note, "adjustment": adjustment, "adjusted_total": adjusted_total}
    _save(adj)

def _save(adj: dict):
    data = {"_schema": "v1", "_description": "场次备注与散票数量修正", "matches": adj}
    os.makedirs(os.path.dirname(_ADJ_FILE), exist_ok=True)
    with open(_ADJ_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)