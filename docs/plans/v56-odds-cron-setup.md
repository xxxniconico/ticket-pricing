# V5.6 赔率周拉 cron — 部署文档

**日期**: 2026-06-20
**作者**: Hermes Agent

---

## 部署

| 项 | 值 |
|---|---|
| cron 表达式 | `0 9 * * 1` |
| 触发时间 | 每周一上午 9:00 |
| 脚本 | `scripts/fetch_csl_odds.sh` |
| 输出目录 | `data/raw/odds/csl_odds_YYYYMMDD.json` |
| 日志 | `logs/odds_cron.log` |
| API 配额消耗 | 4 次/月(免费档 500 次/月足够) |

## 安全

- API key 存 `.env`(gitignored)
- `.env` 已加入 `.gitignore` 第 32 行
- 验证:`git check-ignore -v .env` 返回 `.gitignore:32:.env`

## 脚本行为

```bash
bash scripts/fetch_csl_odds.sh
# 1. 读 .env 的 ODDS_API_KEY
# 2. curl The Odds API soccer_china_superleague
# 3. 保存为 csl_odds_$(date +%Y%m%d).json
# 4. 清理旧文件,保留最近 8 份
# 5. HTTP 200 + 无 error_code 才算成功
```

## 失败处理

- HTTP 非 200 → 删 tmp 文件,exit 2
- API 返 error_code → 删 tmp 文件,exit 3
- 缺 ODDS_API_KEY → exit 1
- log 写在 `logs/odds_cron.log`

## 路径 3 边界(再次声明)

- 不动 rule_engine / csl_context / dynamic_optimizer
- 不动 H2 目标
- 只: 拉数据 → 看板 tab_odds 展示
- 等 8 月大场样本到 5+ 场后再决定是否进 rule_engine

---

**Status**: cron 已部署, 下次执行时间 2026-06-22 (周一) 09:00