-- 按比赛等级统计销量与均价
SELECT 
    match_tier,
    count(*) as transactions,
    sum(数量) as total_tickets,
    round(avg(实际支付价格), 2) as avg_price,
    round(sum(数量 * 实际支付价格) / 10000, 1) as revenue_wan
FROM 'data/processed/all_unified.parquet'
GROUP BY match_tier
ORDER BY match_tier
