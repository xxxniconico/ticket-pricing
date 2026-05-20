# Cursor 任务单 — 票务定价 v4.2

> Hermes 已完成数据基建，Cursor 按顺序执行以下任务。
> 每个任务完成后 Hermes 会审查验证。
> 
> 关键约定：
> - 先读 `AGENTS.md` 了解项目结构
> - 只改指定文件，不删文件
> - 不改数据文件（data/processed/）
> - 不改 `data_feeds.py`（2026实时数据拉取逻辑不变）

---

## 任务 1: S/A/B/C 四级对手分类

**文件**: `src/classify.py`

**改动**:
1. 扩展 `A_TIER_OPPONENTS` → 新增：
```python
S_TIER = {"上海申花"}
A_TIER = {"上海海港", "山东泰山", "成都蓉城"}
C_TIER = {"大连英博海发", "青岛海牛", "梅州客家", "云南玉昆", 
           "辽宁铁人", "重庆铜梁龙", "深圳新鹏城", "青岛西海岸"}
# B_TIER = 其余 (天津津门虎, 浙江, 河南, 武汉三镇, 长春亚泰)
```

2. 新增函数 `classify_opponent_tier(opponent: str) -> str`:
```python
def classify_opponent_tier(opponent: str) -> str:
    """返回 S/A/B/C 四级分类"""
    o = str(opponent).strip()
    if any(t in o for t in S_TIER): return "S"
    if any(t in o for t in A_TIER): return "A"
    if any(t in o for t in C_TIER): return "C"
    return "B"
```

3. 保持旧 `classify_match()` 向后兼容（仍返回 A/B 二元），新增 `classify_match_v4()` 返回四级。

**验证**: `classify_opponent_tier("上海申花") == "S"`

---

## 任务 2: 2025-Only V4 模型

**文件**: `src/calibrate.py`

**新增函数**: `build_attendance_model_v4()`

**训练逻辑**:
1. 读取 `data/processed/all_unified.parquet`
2. 筛选: `competition=='CSL' & is_home==True & is_bundle==False & is_partial==False & match_date 包含'2025'`
3. 对每场2025主场:
   - `recent_form_5` = `recent_form_before_match(match_date, n=5)` (已有)
   - `lost_to_bottom` = `lost_to_bottom_recently(match_date)` (已有)
   - `opp_rank_live` = 从 `get_opponent_rank_2025(opp)` (暂用终榜，后续升级)
   - `is_derby` = `opp in DERBY_RIVALS`
   - `is_weekend` = `match_date.weekday() >= 5`
   - `is_double` = 前后4天内另有比赛
4. OLS: `ln(total_tickets) ~ 6 features`
5. 返回 dict: `{intercept, form_coef, lost_bottom_coef, rank_coef, derby_coef, weekend_coef, double_coef, r_squared, n_samples, version:'v4'}`

**新增函数**: `predict_attendance_v4(**kwargs) -> float`
- 参数同 predict_attendance_v3 但用6特征
- `max_capacity=27500`

**验证**: `build_attendance_model_v4()['n_samples'] >= 15`

---

## 任务 3: 2026 增量迭代

**文件**: `src/calibrate.py`

**新增函数**: `build_attendance_model_live()`

**逻辑**:
1. 同V4训练逻辑，但数据范围 = 2025全量 + 2026已完赛(is_partial==False)
2. 2026场次的 `opp_rank_live` 从 `fetch_csl_standings()` 获取实时排名
3. 获取方式: `get_opponent_standing(opp, standings_df)`

**提示**: `fetch_csl_standings()` 已在 `data_feeds.py` 实现，返回实时积分榜 DataFrame。

**验证**: 调用后 n_samples > V4.n_samples

---

## 任务 4: 分级弹性估计

**文件**: `src/elasticity.py`

**新增函数**: `estimate_tier_elasticity() -> dict`

**逻辑**:
1. 读取 `data/raw/全量散票用户购买记录_统一.xlsx`
2. 按票面价聚合 (用 `parse_price_from_ticket_info`)
3. 分组拟合: 如果某级数据不足 → 回退到全局弹性

**初始返回** (数据不足时):
```python
{
    "S": ElasticityResult(elasticity=-0.5, r_squared=0.0),  # 文献推测
    "A": ElasticityResult(elasticity=-1.5, r_squared=0.0),
    "B": ElasticityResult(elasticity=-2.5, r_squared=0.0),  # 来自现有拟合
    "C": ElasticityResult(elasticity=-3.0, r_squared=0.0),
    "global": ...  # 全局拟合结果
}
```

**注意**: 我们的交易数据没有场次标签，无法真正按级别分组。先用全局弹性 + 级别偏移量。

---

## 任务 5: 10档定价矩阵

**文件**: `src/pricing_matrix.py` (新建)

**做什么**:
```python
# 10档 × 4级 调价系数矩阵
PRICING_MATRIX = {
    "S": {"T1":1.05,"T2":1.05,"T3":1.05,"T4":1.10,"T5":1.10,
          "T6":1.10,"T7":1.10,"T8":1.05,"T9":1.03,"T10":1.03},
    "A": {"T1":1.03,"T2":1.03,"T3":1.03,"T4":1.05,"T5":1.05,
          "T6":1.05,"T7":1.05,"T8":1.03,"T9":1.00,"T10":1.00},
    "B": {"T1":1.00, ...},  # 全部1.0
    "C": {"T1":1.00,"T2":1.00,"T3":1.00,"T4":0.95,"T5":0.95,
          "T6":0.95,"T7":0.95,"T8":0.90,"T9":0.90,"T10":0.90},
}
```

**函数**:
- `load_section_tier_map() -> dict` — 读 `data/processed/section_tier_map.json`
- `get_multiplier(tier: str, opponent_level: str) -> float` — 查表
- `get_section_multiplier(section: str, opponent_level: str) -> float` — 区段→档位→系数

---

## 任务 6: 10档优化器

**文件**: `src/optimize.py`

**改动**:
1. 新增 `optimize_10tier()` 函数
2. 接收10档（不是6档），每档独立容量 + 独立弹性
3. 参数: `frozen_tiers` = 不调价的档位列表（死忠区）
4. 保留容量约束逻辑

**容量分配**: 总散票池 27,500 按热力图比例分到10档
```python
TIER_CAPACITIES_V4 = {
    "T1": 100, "T2": 50, "T3": 700, "T4": 400, "T5": 400,
    "T6": 600, "T7": 1700, "T8": 1200, "T9": 2800, "T10": 3900,
}
# 总计约 11,850 (考虑实际售出率，总池27,500)
```

---

## 任务 7: 看板 V4 面板

**文件**: `dashboard/app.py`

**改动 Tab1**:
1. 导入新模块:
```python
from src.calibrate import build_attendance_model_v4, predict_attendance_v4
from src.classify import classify_opponent_tier
from src.pricing_matrix import get_section_multiplier, load_section_tier_map
from src.optimize import optimize_10tier
```

2. 对手选完后显示四级标签: `S级·德比` / `A级·强队` / `B级·常规` / `C级·普通`

3. 定价建议表改为10档:
   - 替换原来的6档 HTML 表
   - 显示: 档位 | 区段 | 基准价 | 建议价 | 变动 | 预测需求

4. V4预测替代V2/V3:
   - 显示V4预测上座数 + R²
   - 移除V2/V3双栏

**改动 Tab1 底部**:
1. 热力图保留（已有）
2. 新增: 比赛重要性指标（距降级区分差 / 距亚冠区分差）

**验证**: 看板正常显示，选不同对手显示不同级别标签

---

## 执行顺序

```
任务1 (classify.py)         ← 无依赖
    ↓
任务2 (V4模型)              ← 依赖任务1
    ↓
任务3 (增量迭代)            ← 依赖任务2
    ↓
任务4 (分级弹性)            ← 依赖任务1
    ↓
任务5 (定价矩阵)            ← 依赖任务1, 数据文件已就绪
    ↓
任务6 (10档优化器)          ← 依赖任务4, 5
    ↓
任务7 (看板)                ← 依赖全部
```

---

## 数据文件参考

Cursor 不需要改这些文件，但需要读它们：

| 文件 | 用途 | 格式 |
|------|------|------|
| `data/processed/all_unified.parquet` | 全量统一数据 | Parquet |
| `data/processed/standings_2025_by_round.parquet` | 2025实时排名(代理) | Parquet |
| `data/processed/section_tier_map.json` | 82区段→10档映射 | JSON |
| `data/raw/全量散票用户购买记录_统一.xlsx` | 交易记录 | Excel |

---

## Hermes 审查清单

每个任务完成后 Hermes 检查:
- [ ] 代码能跑通 (`python -c "from src.xxx import yyy"`)
- [ ] 输出符号正确（如 derby_coef > 0）
- [ ] 不破坏现有功能（旧函数仍可调用）
- [ ] 看板渲染正常
