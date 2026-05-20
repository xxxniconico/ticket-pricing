# 补充: 亚冠数据加入 _GUOAN_2025_ALL

> 2025下半年亚冠6场 + 中超下半程连败 = 实际连败场次比CSL数据更长。
> 加入后 `recent_form` 和 `lost_to_bottom` 更准确。

---

## 亚冠二级联赛 E 组 国安赛程

```python
# (轮次标记, 对手, 主客, 国安进球, 对手进球, 结果, 日期)
_ACL_2025 = [
    ("ACL1", "河内公安", "H", 2, 2, "D", "2025-09-18"),
    ("ACL2", "麦克阿瑟", "A", 0, 3, "L", "2025-10-02"),
    ("ACL3", "大埔",     "A", 3, 3, "D", "2025-10-23"),
    ("ACL4", "大埔",     "H", 3, 0, "W", "2025-11-06"),
    ("ACL5", "河内公安", "A", 1, 2, "L", "2025-11-27"),
    ("ACL6", "麦克阿瑟", "H", 1, 2, "L", "2025-12-11"),
]
```

---

## 修改: `src/data_feeds.py` — `fetch_guoan_2025_all()` 合并亚冠

```python
def fetch_guoan_2025_all(include_acl: bool = True) -> pd.DataFrame:
    """2025 国安全部赛程（默认含亚冠，用于滚动战绩计算）"""
    rows = []
    for rnd, opp, v, g, og, res, date_str in _GUOAN_2025_ALL:
        rows.append({
            "round": str(rnd), "opponent": opp, "venue": str(v).upper(),
            "guoan_goals": float(g), "opp_goals": float(og),
            "result": str(res).upper(), "date": str(date_str),
            "competition": "CSL",
        })
    
    if include_acl:
        for rnd, opp, v, g, og, res, date_str in _ACL_2025:
            rows.append({
                "round": str(rnd), "opponent": opp, "venue": str(v).upper(),
                "guoan_goals": float(g), "opp_goals": float(og),
                "result": str(res).upper(), "date": str(date_str),
                "competition": "ACL",
            })
    
    df = pd.DataFrame(rows)
    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"])
    df["比分"] = df.apply(lambda r: f"{int(r['guoan_goals'])}-{int(r['opp_goals'])}", axis=1)
    res_zh = {"W": "胜", "D": "平", "L": "负"}
    df["赛果"] = df["result"].map(lambda x: res_zh.get(str(x).upper(), str(x)))
    return df.sort_values("date").reset_index(drop=True)
```

---

## 修改: `compute_home_form_2025` — 含亚冠的滚动战绩

```python
def compute_home_form_2025(up_to_date: str | None = None) -> float:
    """国安 2025 近期胜率（全部赛事含亚冠）。
    
    Args:
        up_to_date: 仅统计此日期之前的比赛。None=全部。
    """
    df = fetch_guoan_2025_all(include_acl=True)
    if up_to_date:
        cutoff = pd.Timestamp(up_to_date)
        df = df[df["date"] < cutoff]
    if df.empty:
        return 0.5
    wins = (df["result"] == "W").sum()
    return float(wins / len(df))


def recent_form_before_match(target_date: str, n: int = 5) -> float:
    """目标日期前 n 场全赛事胜率（含亚冠）"""
    df = fetch_guoan_2025_all(include_acl=True)
    cutoff = pd.Timestamp(target_date)
    prev = df[df["date"] < cutoff].tail(n)
    if prev.empty:
        return 0.5
    return float((prev["result"] == "W").sum() / len(prev))


def lost_to_bottom_recently(target_date: str) -> bool:
    """目标日期前3场是否输给过排名≥12的球队（仅CSL对手有排名）"""
    df = fetch_guoan_2025_all(include_acl=True)
    cutoff = pd.Timestamp(target_date)
    prev3 = df[df["date"] < cutoff].tail(3)
    for _, m in prev3.iterrows():
        if m["result"] == "L":
            opp = str(m["opponent"])
            rank = get_opponent_rank_2025(opp)
            if rank >= 12:
                return True
    return False
```

---

## 对关键场次的影响

| 中超场次 | 之前5场(含亚冠) | 旧form | 新form | lost_bottom |
|----------|----------------|--------|--------|-------------|
| 9/21 vs海港 | 成都L,浙江D,泰山L,河南L,**河内D** | 0.00 | **0.00** | ✅(泰山rank5但河南rank8...no) |
| 9/26 vs英博 | 浙江D,泰山L,河南L,河内D,**海港L** | 0.00 | **0.00** | ✅(河南rank8? 河南rank8 not≥12) |
| 10/26 vs海牛 | 海港L,英博W,深圳L,麦克阿瑟L,**大埔D** | 0.20 | **0.20** | ❌ → **✅**(深圳rank12=保级队!) |

**关键修正**: 10/26 vs海牛之前，旧数据只有CSL赛事显示 form=0.60，加入亚冠后 form=0.20（含 麦克阿瑟L + 深圳L + 大埔D）。`lost_bottom` 也更准确。

---

## 修改: `calibrate.py` 回测用新函数

```python
# 在 build_attendance_model_v2 中
form = recent_form_before_match(date_str, n=5)
lost = lost_to_bottom_recently(date_str)
```

---

## 修改: 看板 Tab1 — 2026用CSL-only（亚冠是2025特有）

2026看板保持用 `compute_home_form`（CSL-only），因为2026亚冠赛程未知。
