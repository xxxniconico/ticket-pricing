# Q 统一质量评分规则

## 架构

Q(永久质量) + Scenario(阶段场景) = 最终决策

Q > 5% => 自动推荐，否则 => 需人工审核。

## Q 公式

Q = ev_calibrated
  + tier_adjustment      (球队分级)
  + pool_discount        (玩法类型)
  + draw_penalty         (平局风险)
  + hcap_penalty         (让球大小)
  + mismatch_penalty     (模型冷偏差)
  + longshot_penalty     (超高赔率)

### tier_adjustment
| 对战 | Q调整 | 原因 |
|------|:--:|------|
| T1vT1 | 0 | 顶级对决 |
| T2vT3 | +0.01 | 最均衡 |
| T1vT4 | -0.05 | 强弱悬殊 |
| T4vT4 | -0.03 | 菜鸡互啄 |

Tier从Elo动态计算: T1=前8, T2=9-20, T3=21-36, T4=37-48

### pool_discount
| 玩法 | Q调整 | 回测 |
|------|:--:|------|
| hhad | 0 | ROI +18% |
| had | -0.05 | ROI -25% |
| crs/ttg | 全量manual | 回测0/2 |

### draw_penalty
had平局: -0.08; p<25%: 额外-0.01; 非模型#1: 额外-0.01

### hcap_penalty
|hcap|=1: 0; |hcap|>=2: -0.05*(hcap-1) 且全量manual

### mismatch_penalty
冷偏差: -0.02

### longshot_penalty
odds>25: -0.02

## Scenario层
| 场景 | 调整 |
|------|:--:|
| CRITICAL(赢=晋级) | +15% |
| BOOST(需抢分) | +10% |
| GROUP_WINNER(赢=小组第一) | +5% |
| PENALTY(已晋级) | -5% |

淘汰赛: Scenario归零

## 硬性过滤
- EV<=0: 丢弃
- CRS/TTG: 全量manual
- |hcap|>=2: 全量manual


## 待办：淘汰赛场景

进入淘汰赛时，需要新增以下场景：

### 对阵优势
- 小组第一 vs 第二：胜者 +5%（对手更弱）
- 休息天数差 > 1天：多休息方 +3%

### 加时赛影响
- 淘汰赛平局概率打折（因为会踢加时，0:0 不再算平局）
- had 平局 penalty 需要调整

### 中立场地
- 所有比赛在中立场地 → HFA = 0
- 动力因素变为「历史交锋」「淘汰赛经验」

---
*最后更新：2026-06-26 小组赛第三轮*
*提醒：淘汰赛开始后更新此文档*
