-- 用户购买行为分析（需 user_stats.parquet）
SELECT 
    count(DISTINCT 大麦用户id) as total_users,
    avg(total_spend) as avg_spent,
    avg(total_tickets) as avg_tickets,
    max(total_tickets) as max_tickets
FROM 'data/processed/user_stats.parquet'
