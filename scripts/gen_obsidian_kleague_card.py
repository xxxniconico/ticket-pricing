"""生成带 Obsidian frontmatter 的 K League 决策卡 markdown"""
import subprocess

out = subprocess.run(
    ['python3', 'scripts/kleague_decision_card.py'],
    capture_output=True, text=True, cwd='/home/xxxsuli/ticket-pricing',
).stdout

body = """---
title: K联赛 2026-08-08 五场决策卡
date: 2026-08-04
tags: [K联赛, 投注, 决策卡]
source: ticket-pricing/scripts/kleague_decision_card.py
---

# K联赛 2026-08-08 五场决策卡

> 模型 v2（历史+当前赛季混合）| Pinnacle 赔率快照 2026-08-04
> 赛后验证: `python scripts/kleague_verify_prediction.py`

```text
""" + out + """
```

---
## 赛后记录

- [ ] 8/8 赛后跑 kleague_verify_prediction.py 结算
- [ ] 验证 2 个候选 gap：安养主胜+7.7pp、金泉客胜-7.6pp
"""

p = "/mnt/c/Users/xxxsu/Documents/Obsidian Vault/国安足球/K联赛/2026-08-08_五场决策卡.md"
open(p, 'w', encoding='utf-8').write(body)
print('已写入', p, len(body), '字节')
