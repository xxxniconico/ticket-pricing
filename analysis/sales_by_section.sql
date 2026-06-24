-- 按区段统计销量与均价
SELECT 
    section,
    count(*) as transactions,
    sum(数量) as total_tickets,
    round(avg(实际支付价格), 2) as avg_price
FROM 'data/processed/all_unified.parquet'
WHERE section IS NOT NULL
GROUP BY section
ORDER BY section
