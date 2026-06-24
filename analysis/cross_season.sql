-- 跨赛季对比：按年份聚合
SELECT 
    strftime(match_date::date, '%Y') as season,
    count(*) as transactions,
    sum(数量) as total_tickets,
    round(avg(实际支付价格), 2) as avg_price,
    round(sum(数量 * 实际支付价格) / 10000, 1) as revenue_wan
FROM 'data/processed/all_unified.parquet'
GROUP BY season
ORDER BY season
