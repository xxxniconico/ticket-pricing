# 北京国安票务动态定价模型

基于25年座位级历史销售数据，为北京国安足球俱乐部构建动态定价优化模型。

## 项目结构

```
ticket-pricing/
├── data/raw/            # 原始Excel（gitignore）
├── src/                 # 核心模块
│   ├── ingest.py        # 数据摄入+清洗
│   ├── elasticity.py    # 需求弹性拟合
│   ├── classify.py      # 比赛分级（增强A/B）
│   ├── optimize.py      # 优化求解器
│   └── cli.py           # CLI入口
├── tests/               # pytest
├── docs/plans/          # 实施计划
└── notebooks/           # 探索性分析
```

## 使用方法

```bash
# 安装依赖
pip install -r requirements.txt

# 放数据到 data/raw/

# 运行定价建议
python src/cli.py --opponent "上海申花" --home-form 0.6 --opponent-standing 1
```

## 核心参数

- **场馆**: 工体（68,000座，年票25,000，散票池43,000）
- **优化目标**: 60%收入 + 40%上座率
- **A级对手**: 成都蓉城、山东泰山、上海海港、上海申花
- **技术栈**: Python 3.11 + pandas + scipy + pytest
