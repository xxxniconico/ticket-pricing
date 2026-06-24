-- 价格弹性分析数据准备：按场次+价格聚合
SELECT 
    match_id,
    match_tier,
    实际支付价格,
    sum(数量) as quantity
FROM 'data/processed/all_unified.parquet'
WHERE 实际支付价格 > 0
GROUP BY match_id, match_tier, 实际支付价格
ORDER BY match_id, 实际支付价格
