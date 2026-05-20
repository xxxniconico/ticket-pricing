# 快捷修复 — 回测和Tab1接上v2上座率模型

> v2 模型(`predict_attendance_v2`)已实现在 calibrate.py，但看板还在用旧 multiplier。
> 修复: run_backtest 和 Tab1 替换为 v2 直接预测。

---

## 修改: `dashboard/app.py` — `run_backtest()` 用 v2

替换第118-160行附近的旧回测逻辑：

```python
    from src.calibrate import build_attendance_model_v2, predict_attendance_v2
    from src.data_feeds import fetch_guoan_2025_all, recent_form_before_match, lost_to_bottom_recently

    att_v2 = build_attendance_model_v2(_data_dir)
    all25 = fetch_guoan_2025_all(include_acl=True)
    
    seats = load_seat_data(...)
    out = []
    for match_id in seats['match_id'].unique():
        md = seats[seats['match_id'] == match_id]
        ...
        actual = len(md)
        date_str = str(md['match_date'].iloc[0])
        match_date = pd.Timestamp(date_str)
        opp = str(md['opponent'].iloc[0])
        
        # === v2 特征 ===
        form = recent_form_before_match(date_str, n=5)
        lost = lost_to_bottom_recently(date_str)
        rank = get_opponent_rank_2025(opp)
        derby = 1 if opp in {'上海申花','天津津门虎','山东泰山'} else 0
        dow = match_date.weekday()
        
        prev_home = all25[(all25['date'] < match_date) & (all25['venue']=='H') & (all25['competition']=='CSL')]
        days_since = int((match_date - prev_home['date'].iloc[-1]).days) if not prev_home.empty else 14
        
        nearby = all25[(all25['date'] != match_date)]
        diffs = abs((pd.to_datetime(nearby['date']) - match_date).dt.days)
        double = int((diffs <= 4).any())
        
        pred = predict_attendance_v2(form, lost, rank, derby, dow, days_since, double, model=att_v2)
        
        # 用 pred 做 demand_multiplier
        tier = 'A' if opp in {'成都蓉城','山东泰山','上海海港','上海申花'} else 'B'
        avg_total = demand_df.groupby('match_id')['quantity'].sum().mean()
        mult = pred / avg_total if avg_total > 0 else 1.0
        
        models_bt = _build_tier_models(demand_df, tier, txn_el)
        opt = optimize_multi_tier(models_bt, dict(TIER_CAPACITIES), demand_multiplier=mult)
        
        out.append({
            'match_id': match_id, 'opponent': opp, 'tier': tier,
            'actual': actual, 'predicted': opt.total_attendance,
            'revenue_pred': opt.total_revenue,
        })
```

删除旧的 `classify_match_hybrid` 调用和 `attendance_v2_features_for_2025_home_round` 引用。

---

## 验证

```bash
cd ~/ticket-pricing && pkill -f streamlit && bash dashboard/serve.sh
```

打开 Tab2 看回测 MAE 是否下降。预期海牛从 18,916 降到 ~12,000。
