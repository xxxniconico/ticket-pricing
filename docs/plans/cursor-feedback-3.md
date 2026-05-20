# Cursor 修复反馈 #3 — 容量模型校准

> 用户确认：总可售票 ~52,500（已扣除客队看台+分离区+赠票），年票 ~25,000，散票池 ~27,500。
> 2025 数据验证：散票最大值 23,878（vs申花），均值 15,805。

---

## 修改: cli.py — 容量默认值 + 各档位分配

### 1. --capacity 默认值

```python
# 改这一行：
p.add_argument("--capacity", type=int, default=27500,  # 原 40000 → 散票池 27,500
               help="散票池总容量（默认扣除年票/客队/分离区/赠票后）")
```

### 2. 各档位容量分配（替换 TIER_ZONE_SHARE）

当前按区段数量等比分配，但 tier1（球门后）年票占比极高，散票容量远低于区段数量暗示的比例。

根据 2025 数据中各档位实际散票出票量反推容量：

```python
# 各档位散票容量（基于2025赛季实际最大值+合理上浮）
TIER_CAPACITIES: dict[str, int] = {
    "tier1":  3000,   # 球门后6区，年票为主，散票极少
    "tier2":  9500,   # 39区，主力散票区
    "tier3":  7000,   # 15区，中档主力
    "tier4":  3000,   # 6区，上层中线
    "tier5":  4200,   # 18区，前排黄金
    "vip":     800,   # 2区，贵宾
}
# 合计: 27,500
```

删除 `_tier_capacities()` 函数和 `TIER_ZONE_SHARE`，直接用 `TIER_CAPACITIES`。

### 3. cli.py 中引用改为

```python
# 删除 _tier_capacities 调用，改为：
caps = dict(TIER_CAPACITIES)

# 传给 optimize_multi_tier 时验证总容量
# optimize_multi_tier 已使用 capacities[t] 作为各档位上限
```

---

## 验证

```bash
python src/cli.py --opponent "上海申花" --weekend --home-form 0.6 --opponent-standing 1
```

预期:
- 总需求接近或达到 27,500（申花接近售罄）
- 上座率 > 85%
- tier1 接近满（球迷组织惯性）+ 价格涨幅小

```bash
python src/cli.py --opponent "青岛海牛" --no-weekend --home-form 0.3 --opponent-standing 14
```

预期:
- 总需求 ~10,000-12,000
- 上座率 ~40-45%
- tier1/tier2 降价促销
