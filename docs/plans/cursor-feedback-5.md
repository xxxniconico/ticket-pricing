# Cursor 修复反馈 #5 v2 — demand_multiplier 校准（混合模型）

> 纯查表太死：海牛 2025=0.55× 不等于 2026 永远是 0.55×。
> 用「base × context」混合模型。

---

## 模型结构

```
final_multiplier = base_multiplier(opponent) × context_adjustment(standing, form, stage, weather)
```

- **base_multiplier**: 从 2025 数据查表，捕获对手品牌吸引力（申花永远比海牛强）
- **context_adjustment**: 情境因子积，从 classify.py 现有逻辑取，但**降低权重**（base 已做主力区分）

---

## 修改: classify.py

### 追加函数

```python
def build_base_multiplier_lookup(
    seat_data_path: str = "data/raw/2025散票数据.xlsx",
) -> dict[str, float]:
    """从2025数据计算每个对手的基础需求乘数
    
    乘数 = 该对手场均散票 / 同级对手场均散票
    返回: {opponent_name: base_multiplier}
    """
    import pandas as pd
    from src.ingest import load_seat_data
    
    df = load_seat_data(seat_data_path)
    
    by_match = df.groupby("match_id").agg(
        attendance=("match_id", "size"),
        opponent=("opponent", "first"),
    ).reset_index()
    
    a_opps = set(by_match[by_match["opponent"].isin(A_TIER_OPPONENTS)]["opponent"])
    a_avg = by_match[by_match["opponent"].isin(a_opps)]["attendance"].mean()
    b_avg = by_match[~by_match["opponent"].isin(a_opps)]["attendance"].mean()
    
    by_opp = by_match.groupby("opponent")["attendance"].mean()
    
    result = {}
    for opp, att in by_opp.items():
        baseline = a_avg if opp in a_opps else b_avg
        result[opp] = round(att / baseline, 3) if baseline > 0 else 1.0
    
    return result


def get_demand_multiplier(
    opponent: str,
    opponent_standing: int | None = None,
    base_lookup: dict[str, float] | None = None,
    is_weekend: bool = True,
    is_holiday: bool = False,
    season_stage: str = "mid",
    home_form: float = 0.5,
    temperature_c: float = 20.0,
    precipitation_mm: float = 0.0,
) -> float:
    """混合乘数 = base × context
    
    base: 从历史数据查表（对手品牌效应）
    context: 情境调节（降权版，因为 base 已做主力区分）
    """
    # base
    if base_lookup and opponent in base_lookup:
        base = base_lookup[opponent]
    elif opponent_standing and opponent_standing <= 4:
        base = 1.25
    elif opponent_standing and opponent_standing >= 13:
        base = 0.75
    else:
        base = 1.0
    
    # context（降权：原 classify.py 因子的 50% 权重，避免重复计算对手效应）
    ctx_mult = 1.0
    
    # 周末（保留，时序相关）
    if is_weekend:
        ctx_mult *= 1.05  # 原 1.10 → 1.05
    
    # 节假日
    if is_holiday:
        ctx_mult *= 1.06  # 原 1.12 → 1.06
    
    # 排名调节（降权，base 已经含对手强弱）
    if opponent_standing and opponent_standing <= 3:
        ctx_mult *= 1.08  # 原 1.15 → 1.08
    elif opponent_standing and opponent_standing >= 14:
        ctx_mult *= 0.95  # 原 0.90 → 0.95
    
    # 赛程阶段（保留，与对手无关）
    if season_stage in ("crucial", "title_race", "relegation"):
        ctx_mult *= 1.10  # 原 1.20 → 1.10
    
    # 主场战绩
    if home_form > 0.6:
        ctx_mult *= 1.05  # 原 1.08 → 1.05
    elif home_form < 0.3:
        ctx_mult *= 0.95  # 原 0.92 → 0.95
    
    # 极端天气
    if temperature_c < 5 or precipitation_mm > 25:
        ctx_mult *= 0.90  # 原 0.85 → 0.90
    
    return round(base * ctx_mult, 3)
```

### 保留原 classify_match()

原 `classify_match()` 保留不动（其他模块可能引用），新增重载版本：

```python
def classify_match_hybrid(
    opponent: str,
    base_lookup: dict[str, float] | None = None,
    opponent_standing: int = 8,
    is_weekend: bool = True,
    is_holiday: bool = False,
    season_stage: str = "mid",
    home_form: float = 0.5,
    temperature_c: float = 20.0,
    precipitation_mm: float = 0.0,
) -> tuple[str, float]:
    """混合模型版本：base × context"""
    tier = "A" if opponent in A_TIER_OPPONENTS else "B"
    mult = get_demand_multiplier(
        opponent=opponent,
        opponent_standing=opponent_standing,
        base_lookup=base_lookup,
        is_weekend=is_weekend,
        is_holiday=is_holiday,
        season_stage=season_stage,
        home_form=home_form,
        temperature_c=temperature_c,
        precipitation_mm=precipitation_mm,
    )
    return tier, mult
```

---

## 修改: cli.py

### import 改为
```python
from src.classify import classify_match_hybrid, build_base_multiplier_lookup
```

### main() 中替换 classify_match 调用
```python
    # 加载基础乘数查表
    base_lookup = None
    try:
        base_lookup = build_base_multiplier_lookup(
            f"{args.data_dir}/2025散票数据.xlsx"
        )
    except (OSError, FileNotFoundError):
        pass

    tier, mult = classify_match_hybrid(
        args.opponent,
        base_lookup=base_lookup,
        opponent_standing=args.opponent_standing,
        is_weekend=is_weekend,
        is_holiday=args.holiday,
        season_stage=args.season_stage,
        home_form=args.home_form,
        temperature_c=args.temperature,
        precipitation_mm=args.precipitation,
    )
```

---

## 效果对比

| 场景 | 旧(理论) | 纯查表 | 混合模型 |
|------|---------|--------|---------|
| 申花,周末,争冠 | 1.71× | 1.23× | 1.23×1.21=**1.49×** |
| 海牛,周中,普通 | 0.90× | 0.55× | 0.55×1.0=**0.55×** |
| 海牛,周末,保级战 | 0.90× | 0.55× | 0.55×1.10=**0.61×** |
| 海港,周末,争冠 | 1.38× | 0.74× | 0.74×1.21=**0.90×** |
| 天津,周末,普通 | 1.49× | 1.49× | 1.49×1.10=**1.64×** |

---

## 验证

```bash
# 申花周末争冠
python src/cli.py --opponent "上海申花" --weekend --home-form 0.7 --opponent-standing 1 --season-stage title_race

# 海牛周中普通
python src/cli.py --opponent "青岛海牛" --no-weekend --home-form 0.3 --opponent-standing 14

# 海牛周末保级关键战（情境改善）
python src/cli.py --opponent "青岛海牛" --weekend --home-form 0.5 --opponent-standing 14 --season-stage relegation
```

预期:
- 申花争冠: ~1.49×, 上座率接近售罄
- 海牛普通: ~0.55×, 上座率 40-50%（大幅低于之前的 82%）
- 海牛保级战: ~0.61×, 上座率 45-55%
