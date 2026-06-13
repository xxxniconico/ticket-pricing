"""H1/H2 瀑布图计算与绘制。"""
import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from dashboard.common.data_cache import _get_csl_parquet, get_optimizer
from src.csl_context import detect_ctx
from src.pricing_v5 import build_price_matrix

ROOT = Path(__file__).resolve().parent.parent.parent

def compute_waterfall_decomposition(h2_json_str, guoan_matches_ser, _version=20):
    """动态计算收入缺口瀑布的五/六因子分解。_version递增强制缓存刷新。"""
    h2 = json.loads(h2_json_str)
    guoan_matches = list(guoan_matches_ser)
    matches = h2["matches"]
    summary = h2["summary"]

    REV_2025 = 42_035_000  # 2025 CSL 散票全年收入（15场，剔除足协杯+亚冠）
    rev_2025_wan = REV_2025 / 1e4
    projection_2026 = summary["annual_projection_revenue"]
    total_gap = projection_2026 - REV_2025  # negative = shortfall

    optimizer = get_optimizer()
    pm = build_price_matrix()

    from src.classify import classify_opponent_tier as _ct, DERBY_RIVALS as _dr
    from src.pricing_v5 import get_pricing_tier as _gpt

    # 加载 standings，用 year_round 复合键避免跨赛季覆盖
    _ctx_standings = {}
    for yr in ['2025', '2026']:
        st_path = ROOT / 'data' / 'processed' / f'standings_{yr}_by_round.parquet'
        if st_path.exists():
            st_df = pd.read_parquet(st_path)
            for rnd in st_df['round'].unique():
                rnd_data = st_df[st_df['round'] == rnd]
                key = f'{yr}_{int(rnd):02d}'
                if key not in _ctx_standings:
                    _ctx_standings[key] = {}
                for _, row in rnd_data.iterrows():
                    _ctx_standings[key][row['team']] = int(row['rank'])

    # ── 对手结构：用2025 CSL已知分布 + parquet实际同级收入 ──
    # 2025 CSL 主场比赛15场：S×1(申花) A×3(成都/山东/天津) B×9 C×2
    csl = _get_csl_parquet()
    tier_rev_2025 = {"S": 0.0, "A": 0.0, "B": 0.0, "C": 0.0}
    tier_n_2025 = {"S": 0, "A": 0, "B": 0, "C": 0}
    KNOWN_CSL = {"上海申花","成都蓉城","山东泰山","天津津门虎","上海海港","武汉三镇",
                 "浙江","云南玉昆","深圳新鹏城","青岛西海岸","河南","长春亚泰","梅州客家",
                 "青岛海牛","大连英博","南通支云","沧州雄狮","辽宁铁人","重庆铜梁龙",
                 "浙江俱乐部绿城","河南俱乐部酒祖杜康","大连英博海发","河南队","深圳队","大连人",
                 "浙江队","武汉三镇","成都蓉城","云南玉昆","青岛西海岸","深圳新鹏城","辽宁铁人",
                 "重庆铜梁龙","青岛海牛","大连英博海发","梅州客家","长春亚泰","沧州雄狮","南通支云"}
    tier_n_2026 = {"S": 0, "A": 0, "B": 0, "C": 0}
    # 从parquet取2025实际收入 + 各级别场次
    seen_dates = set()
    if csl is not None:
        for mid in csl["match_id"].unique():
            md = csl[csl["match_id"] == mid]
            opp_name = md["opponent"].iloc[0] if "opponent" in md.columns else ""
            if not opp_name or opp_name not in KNOWN_CSL:
                continue
            yr = str(md["match_date"].iloc[0])[:4]
            dt_str = str(md["match_date"].iloc[0])[:10]
            if dt_str in seen_dates:
                continue
            seen_dates.add(dt_str)
            t = _ct(opp_name)
            if yr == "2025":
                tier_rev_2025[t] += float(md["实际支付价格"].sum())
                tier_n_2025[t] += 1
            elif yr == "2026":
                tier_n_2026[t] += 1

    # H2 8场补入2026各级别
    for m in matches:
        tier_n_2026[_ct(m["opponent"])] += 1

    tier_avg_2025 = {t: tier_rev_2025[t] / tier_n_2025[t] if tier_n_2025[t] > 0 else 0
                     for t in ["S", "A", "B", "C"]}
    cf_2026_tiers = sum(tier_avg_2025[t] * tier_n_2026[t] for t in ["S", "A", "B", "C"])
    opponent_mix = cf_2026_tiers - REV_2025

    # 构建全量比赛列表供 detect_ctx 使用（含比分）
    _all_guoan = [m for m in guoan_matches]
    _existing_dates = {m['date'] for m in _all_guoan}
    _csl2025p = ROOT / 'data' / 'raw' / 'csl_2025_all_matches.json'
    if _csl2025p.exists():
        with open(_csl2025p) as f:
            _csl2025d = json.load(f)
        for m in _csl2025d:
            if '国安' not in m.get('home','') and '国安' not in m.get('away',''):
                continue
            if m['date'] in _existing_dates:
                continue
            _existing_dates.add(m['date'])
            is_h = '国安' in m['home']
            opp = m['away'] if is_h else m['home']
            hg = m.get('home_goals', 0) or 0
            ag = m.get('away_goals', 0) or 0
            _all_guoan.append({
                'date': m['date'], 'opponent': opp, 'is_home': is_h,
                'completed': True,
                'hg': hg if is_h else ag,
                'ag': ag if is_h else hg,
                'round': f'第{m.get("round",0)}轮',
            })

    # ── 模型级分解：2026全年 vs 2025全年 ──
    schedule_2026, schedule_2025 = 0.0, 0.0
    performance_2026, performance_2025 = 0.0, 0.0
    top3_2026, top3_2025 = 0.0, 0.0
    pricing_delta = 0.0
    promoted_delta = 0.0

    def _run_decomposition(match_list, season_year, is_h2_check):
        """对一批比赛跑分解，返回 (schedule, perf, top3, pricing, promoted, total_rev)。"""
        s, p, t3, pr, pm = 0.0, 0.0, 0.0, 0.0, 0.0
        total_model_rev = 0.0
        for m in match_list:
            opp = m["opponent"]
            date = m["date"]
            dt = pd.Timestamp(date)
            mock = {"date": date, "opponent": opp, "is_home": True,
                    "completed": m.get("completed", True)}
            ctx = detect_ctx(mock, _all_guoan, _ctx_standings)
            # H2比赛尚未发生，强制关闭负向表现情境
            if is_h2_check and any(m2["date"] == date and m2["opponent"] == opp for m2 in matches):
                for bad_key in ("heavy_home_loss", "away_winless", "consecutive_home_losses"):
                    ctx.pop(bad_key, None)
            args = dict(
                derby=opp in _dr, saturday=dt.weekday() == 5,
                midweek=dt.weekday() in (1, 2, 3), summer=dt.month in (7, 8),
                late_season=dt.month >= 10,
                midseason_restart=ctx.get("midseason_restart", False),
                away_winless=ctx.get("away_winless", False),
                consecutive_home_losses=ctx.get("consecutive_home_losses", False),
                heavy_home_loss=ctx.get("heavy_home_loss", False),
                short_rest=ctx.get("short_rest", False),
                season_opener=ctx.get("season_opener", False),
                top3_form=ctx.get("top3_form", False),
                match_year=season_year,
            )
            try:
                opt_actual = optimizer.optimize(opp, **args)
                total_model_rev += opt_actual.total_revenue
            except Exception:
                continue
            # 赛程效应
            try:
                opt_sched = optimizer.optimize(opp, **{**args,
                    "saturday": False, "midweek": False,
                    "summer": False, "midseason_restart": False})
                s += opt_actual.total_revenue - opt_sched.total_revenue
            except Exception:
                pass
            # 表现效应
            try:
                opt_perf = optimizer.optimize(opp, **{**args,
                    "away_winless": False,
                    "consecutive_home_losses": False,
                    "heavy_home_loss": False})
                p += opt_actual.total_revenue - opt_perf.total_revenue
            except Exception:
                pass
            # 榜首效应：国安排名前3 → B/C级溢价
            if args.get("top3_form"):
                try:
                    opt_no_top3 = optimizer.optimize(opp, **{**args, "top3_form": False})
                    t3 += opt_actual.total_revenue - opt_no_top3.total_revenue
                except Exception:
                    pass
            # 定价优化（仅H2）
            if is_h2_check and any(m2["date"] == date and m2["opponent"] == opp for m2 in matches):
                pr += opt_actual.total_revenue - opt_actual.base_revenue
            # 升班马（仅H2）
            if is_h2_check and opp in ("辽宁铁人", "重庆铜梁龙"):
                try:
                    opt_b = optimizer.optimize(opp, pricing_tier_override="S_B",
                                               opponent_tier_override="B", **args)
                    pm += opt_actual.total_revenue - opt_b.total_revenue
                except Exception:
                    pass
        return s, p, t3, pr, pm, total_model_rev

    # 2025 H1 主场（同期对比2026 H1）：取前7场，6月底前
    h_2025 = []
    h_2025_full = []  # 全年保留给对手结构用
    _csl2025_path = ROOT / 'data' / 'raw' / 'csl_2025_all_matches.json'
    if _csl2025_path.exists():
        with open(_csl2025_path) as f:
            _csl2025 = json.load(f)
        for m in _csl2025:
            if '国安' not in m.get('home','') and '国安' not in m.get('away',''):
                continue
            is_home = '国安' in m['home']
            if not is_home:
                continue  # 仅主场
            opp = m['away']
            hg = m.get('home_goals', 0) or 0
            ag = m.get('away_goals', 0) or 0
            h_2025.append({
                'date': m['date'], 'opponent': opp, 'is_home': is_home,
                'completed': True,
                'hg': hg if is_home else ag,
                'ag': ag if is_home else hg,
                'round': f'第{m.get("round",0)}轮',
            })
    h_2025.sort(key=lambda x: x['date'])

    h1_home = [m for m in guoan_matches if m.get("is_home") and m.get("completed") and m["date"].startswith("2026")]
    # 2026 H1 + H2
    all_2026_home = sorted(h1_home + [{"date": m["date"], "opponent": m["opponent"],
        "is_home": True, "completed": False} for m in matches], key=lambda x: x["date"])
    schedule_2026, _, top3_2026, pricing_delta, promoted_delta, model_rev_2026 = _run_decomposition(all_2026_home, "2026", True)

    # 球队表现：同一对手2026 vs 2025实际收入差，折算全年
    # 构建2025对手→收入映射（精确到队，不算级别均值）
    opp_rev_2025 = {}
    if csl is not None:
        for mid in csl['match_id'].unique():
            md = csl[csl['match_id'] == mid]
            if not str(md['match_date'].iloc[0]).startswith('2025'):
                continue
            opp = md['opponent'].iloc[0] if 'opponent' in md.columns else ''
            dt = str(md['match_date'].iloc[0])[:10]
            if opp in KNOWN_CSL and dt not in opp_rev_2025:
                opp_rev_2025[opp] = float(md['实际支付价格'].sum())
    h1_perf_gap = 0.0; perf_n = 0
    for m in h1_home:
        opp = m['opponent']
        rev26 = 0.0
        if csl is not None:
            for mid in csl['match_id'].unique():
                md = csl[csl['match_id'] == mid]
                if len(md) > 0 and str(md['match_date'].iloc[0])[:10] == m['date']:
                    rev26 = float(md['实际支付价格'].sum())
                    break
        rev25 = opp_rev_2025.get(opp)
        if rev25 and rev25 > 0:
            h1_perf_gap += rev26 - rev25
            perf_n += 1
    team_perf = h1_perf_gap / perf_n * 15 if perf_n > 0 else 0.0

    # ── 组装 bars：四因子 + 残差补齐 ──
    bars = [
        ("2025\n实际", round(REV_2025 / 1e4), "#5b9bd5"),
        ("对手\n结构", round(opponent_mix / 1e4), "#ff6b6b"),
        ("球队\n表现", round(team_perf / 1e4), "#ff6b6b"),
        ("定价\n优化", round(pricing_delta / 1e4), "#51cf66"),
        ("升班马\n保守", round(promoted_delta / 1e4), "#ff6b6b"),
    ]
    modeled = opponent_mix + team_perf + pricing_delta + promoted_delta
    residual = total_gap - modeled
    bars.append(("其他\n因素", round(residual / 1e4), "#8a8f98"))

    bars.append(("2026\n预估", round(projection_2026 / 1e4),
        "#51cf66" if projection_2026 >= REV_2025 else "#ff6b6b"))

    captions = {
        "对手结构": f"2025: S/A/B/C = {tier_n_2025['S']}/{tier_n_2025['A']}/{tier_n_2025['B']}/{tier_n_2025['C']}场 → 2026: {tier_n_2026['S']}/{tier_n_2026['A']}/{tier_n_2026['B']}/{tier_n_2026['C']}场。按2025各级别场均收入折算。",
        "球队表现": f"同一对手2026 vs 2025 H1收入差（{perf_n}队可比）：少收¥{abs(h1_perf_gap)/1e4:.0f}万，折算全年15场。控制对手后的纯成绩效应。",
        "定价优化": f"优化器V8.2调价 vs 基准价，仅H2八场。{'正值=策略增收' if pricing_delta>0 else '负值=降价拉量'}。",
        "升班马保守": f"辽宁铁人/重庆铜梁龙按C级(S_C)定价，升级B级(S_B)可增收约¥{abs(promoted_delta)/1e4:.0f}万。",
        "其他因素": f"含赛程时间差异、球队表现差异、票价水平变化、宏观因素等。跨赛季因素不可直接对比（2025有榜首加持），不单独列出。残差=总缺口-三因子之和。",
    }

    return {
        "bars": bars,
        "captions": captions,
        "rev_2025": REV_2025,
        "projection_2026": projection_2026,
    }


def compute_h1_waterfall(guoan_matches_ser, _version=1):
    """H1收入缺口瀑布 — 纯实际数据，无预估。

    2025 H1 vs 2026 H1，按对手分级（S/A/B/C）分解缺口。
    所有数据来自已完场比赛。
    """
    from src.classify import classify_opponent_tier as _ct, DERBY_RIVALS as _dr
    from src.classify import B_TIER as _B_TIER_LIST

    csl = _get_csl_parquet()

    # ── 收集 H1 主场比赛（≤6月30日）──
    h1_2025 = {}  # date → {opponent, revenue, tier}
    h1_2026 = {}
    if csl is not None:
        for mid in csl["match_id"].unique():
            md = csl[csl["match_id"] == mid]
            if "is_home" not in md.columns or not md["is_home"].iloc[0]:
                continue
            opp = str(md["opponent"].iloc[0]) if "opponent" in md.columns else ""
            if not opp:
                continue
            d = str(md["match_date"].iloc[0])[:10]
            yr = d[:4]
            rev = float(md["实际支付价格"].sum())
            tier = _ct(opp)
            if yr == "2025" and d < "2025-07-01":
                if d not in h1_2025:
                    h1_2025[d] = {"opponent": opp, "revenue": rev, "tier": tier}
            elif yr == "2026" and d < "2026-07-01":
                if d not in h1_2026:
                    h1_2026[d] = {"opponent": opp, "revenue": rev, "tier": tier}

    rev_2025_h1 = sum(m["revenue"] for m in h1_2025.values())
    rev_2026_h1 = sum(m["revenue"] for m in h1_2026.values())
    n_2025 = len(h1_2025)
    n_2026 = len(h1_2026)
    total_gap = rev_2026_h1 - rev_2025_h1

    # ── 2025 各级别均价（仅主场，排除非CSL对手+杯赛重复）──
    tier_rev = {"S": 0.0, "A": 0.0, "B": 0.0, "C": 0.0}
    tier_n = {"S": 0, "A": 0, "B": 0, "C": 0}
    seen_dates = set()
    seen_opponents_2025 = set()
    if csl is not None:
        for mid in csl["match_id"].unique():
            md = csl[csl["match_id"] == mid]
            if "is_home" not in md.columns or not md["is_home"].iloc[0]:
                continue
            opp = str(md["opponent"].iloc[0]) if "opponent" in md.columns else ""
            if not opp:
                continue
            d = str(md["match_date"].iloc[0])[:10]
            if not d.startswith("2025") or d in seen_dates:
                continue
            if opp in seen_opponents_2025:
                continue
            t = _ct(opp)
            if t == "B" and not any(x in opp or opp in x for x in _B_TIER_LIST):
                continue
            seen_dates.add(d)
            seen_opponents_2025.add(opp)
            tier_rev[t] += float(md["实际支付价格"].sum())
            tier_n[t] += 1

    tier_avg = {t: tier_rev[t] / tier_n[t] if tier_n[t] > 0 else 0
                for t in ["S", "A", "B", "C"]}

    # ── 对手结构 ──
    tier_n_2026 = {"S": 0, "A": 0, "B": 0, "C": 0}
    expected_2026 = 0.0
    for d, m in sorted(h1_2026.items()):
        t = m["tier"]
        tier_n_2026[t] += 1
        expected_2026 += tier_avg[t]

    tier_n_2025 = {"S": 0, "A": 0, "B": 0, "C": 0}
    for m in h1_2025.values():
        tier_n_2025[m["tier"]] += 1

    per_match_2025 = rev_2025_h1 / n_2025 if n_2025 > 0 else 0
    match_count_effect = per_match_2025 * (n_2026 - n_2025)
    opponent_mix = expected_2026 - per_match_2025 * n_2026
    performance = rev_2026_h1 - expected_2026

    # ── 拆分战绩效应 ──
    # 用 optimizer 估算 top3_form / away_winless / consecutive_home_losses / heavy_home_loss 的收入影响
    PERF_FLAGS = ("top3_form", "away_winless", "consecutive_home_losses", "heavy_home_loss")
    optimizer = get_optimizer()

    # 构建 standings 和 all_guoan 供 detect_ctx 使用
    _ctx_standings = {}
    for yr in ['2025', '2026']:
        st_path = ROOT / 'data' / 'processed' / f'standings_{yr}_by_round.parquet'
        if st_path.exists():
            st_df = pd.read_parquet(st_path)
            for rnd in st_df['round'].unique():
                rnd_data = st_df[st_df['round'] == rnd]
                key = f'{yr}_{int(rnd):02d}'
                if key not in _ctx_standings:
                    _ctx_standings[key] = {}
                for _, row in rnd_data.iterrows():
                    _ctx_standings[key][row['team']] = int(row['rank'])

    guoan_matches = list(guoan_matches_ser)
    _all_guoan = [m for m in guoan_matches]
    _existing_dates = {m['date'] for m in _all_guoan}
    _csl2025p = ROOT / 'data' / 'raw' / 'csl_2025_all_matches.json'
    if _csl2025p.exists():
        with open(_csl2025p) as f:
            _csl2025d = json.load(f)
        for m in _csl2025d:
            if '国安' not in m.get('home', '') and '国安' not in m.get('away', ''):
                continue
            if m['date'] in _existing_dates:
                continue
            _existing_dates.add(m['date'])
            is_h = '国安' in m['home']
            opp = m['away'] if is_h else m['home']
            hg = m.get('home_goals', 0) or 0
            ag = m.get('away_goals', 0) or 0
            _all_guoan.append({
                'date': m['date'], 'opponent': opp, 'is_home': is_h,
                'completed': True,
                'hg': hg if is_h else ag,
                'ag': ag if is_h else hg,
                'round': f'第{m.get("round",0)}轮',
            })

    def _perf_effect(d, opp, yr):
        """单场战绩效应：optimizer(with perf flags) - optimizer(without perf flags)"""
        dt = pd.Timestamp(d)
        mock = {"date": d, "opponent": opp, "is_home": True, "completed": True}
        ctx = detect_ctx(mock, _all_guoan, _ctx_standings)
        # 清除跨赛季污染：detect_ctx 不区分赛季，2025末的主场大败会污染2026初
        # 检测 heavy_home_loss 触发源是否来自上一赛季
        if ctx.get("heavy_home_loss") and yr == "2026":
            prev_home_2026 = [g for g in _all_guoan
                              if g.get("is_home") and g["date"] < d and g["date"][:4] == "2026"]
            has_2026_loss = any(g["hg"] - g["ag"] <= -2 for g in prev_home_2026)
            if not has_2026_loss:
                ctx.pop("heavy_home_loss")
        base_args = dict(
            derby=opp in _dr, saturday=dt.weekday() == 5,
            midweek=dt.weekday() in (1, 2, 3), summer=dt.month in (7, 8),
            late_season=dt.month >= 10,
            midseason_restart=ctx.get("midseason_restart", False),
            short_rest=ctx.get("short_rest", False),
            season_opener=ctx.get("season_opener", False),
            match_year=yr,
        )
        # 带战绩 flag
        perf_on = {f: ctx.get(f, False) for f in PERF_FLAGS}
        try:
            rev_with = optimizer.optimize(opp, **{**base_args, **perf_on}).total_revenue
            rev_without = optimizer.optimize(opp, **{**base_args,
                "top3_form": False,
                "away_winless": False,
                "consecutive_home_losses": False,
                "heavy_home_loss": False}).total_revenue
            return rev_with - rev_without
        except Exception:
            return 0.0

    perf_2025 = 0.0
    perf_2026 = 0.0
    perf_detail_2025 = []
    perf_detail_2026 = []
    for d, m in h1_2025.items():
        eff = _perf_effect(d, m["opponent"], "2025")
        perf_2025 += eff
        if abs(eff) > 1000:
            perf_detail_2025.append(f"{m['opponent']}:{eff/1e4:+.0f}万")
    for d, m in h1_2026.items():
        eff = _perf_effect(d, m["opponent"], "2026")
        perf_2026 += eff
        if abs(eff) > 1000:
            perf_detail_2026.append(f"{m['opponent']}:{eff/1e4:+.0f}万")

    record_effect = perf_2026 - perf_2025  # 正值=2026战绩好于2025
    other_perf = performance - record_effect
    residual = total_gap - (match_count_effect + opponent_mix + record_effect + other_perf)

    # ── 组装 bars ──
    bars = [
        ("2025 H1\n实际", round(rev_2025_h1 / 1e4), "#5b9bd5"),
        ("场次\n差异", round(match_count_effect / 1e4), "#8a8f98"),
        ("对手\n结构", round(opponent_mix / 1e4), "#ff6b6b"),
        ("球队\n战绩", round(record_effect / 1e4), "#51cf66" if record_effect >= 0 else "#ff6b6b"),
        ("其他\n表现", round(other_perf / 1e4), "#51cf66" if other_perf >= 0 else "#ff6b6b"),
    ]
    if abs(residual) > 50:
        bars.append(("残差", round(residual / 1e4), "#8a8f98"))
    bars.append(("2026 H1\n实际", round(rev_2026_h1 / 1e4),
                "#51cf66" if rev_2026_h1 >= rev_2025_h1 else "#ff6b6b"))

    # ── 同对手明细 ──
    def _same_opp(a, b):
        if _ct(a) != _ct(b):
            return False
        return (len(a) >= 2 and a in b) or (len(b) >= 2 and b in a)
    same_opp_lines = []
    matched_2025 = set()
    for d26, m26 in sorted(h1_2026.items()):
        opp26 = m26["opponent"]
        rev26 = m26["revenue"]
        for d25, m25 in sorted(h1_2025.items()):
            if d25 in matched_2025:
                continue
            if _same_opp(opp26, m25["opponent"]):
                delta = rev26 - m25["revenue"]
                same_opp_lines.append(
                    f"{opp26}: 2025 ¥{m25['revenue']/1e4:.0f}万 → 2026 ¥{rev26/1e4:.0f}万 "
                    f"({'增收' if delta>=0 else '少收'}¥{abs(delta)/1e4:.0f}万)")
                matched_2025.add(d25)
                break
    same_opp_detail = "；".join(same_opp_lines) if same_opp_lines else "无同对手可比"

    captions = {
        "场次差异": f"H1 2025 {n_2025}场 → H1 2026 {n_2026}场，按2025 H1场均¥{per_match_2025/1e4:.0f}万折算",
        "对手结构": f"2025 H1: S/A/B/C={tier_n_2025['S']}/{tier_n_2025['A']}/{tier_n_2025['B']}/{tier_n_2025['C']} → 2026 H1: {tier_n_2026['S']}/{tier_n_2026['A']}/{tier_n_2026['B']}/{tier_n_2026['C']}。2025各级别均价: S=¥{tier_avg['S']/1e4:.0f}万 A=¥{tier_avg['A']/1e4:.0f}万 B=¥{tier_avg['B']/1e4:.0f}万 C=¥{tier_avg['C']/1e4:.0f}万",
        "球队战绩": f"optimizer估算战绩flag(top3/客场不胜/主场连败/主场大败)的收入效应。2025 H1: ¥{perf_2025/1e4:+.0f}万 ({'; '.join(perf_detail_2025) or '无显著效应'}) → 2026 H1: ¥{perf_2026/1e4:+.0f}万 ({'; '.join(perf_detail_2026) or '无显著效应'})。净值={'正值=2026战绩更好带动增收' if record_effect>=0 else '负值=2026战绩不及2025拖累收入'}。",
        "其他表现": f"扣除战绩效应后的剩余表现差。含票价水平变化、赛程安排、宏观消费力等。同对手对比: {same_opp_detail}",
        "残差": "数值舍入误差，无经济含义。",
    }

    return {
        "bars": bars,
        "captions": captions,
        "rev_2025_h1": rev_2025_h1,
        "rev_2026_h1": rev_2026_h1,
        "tier_avg": tier_avg,
        "tier_n_2025": tier_n_2025,
        "tier_n_2026": tier_n_2026,
    }


def compute_h2_waterfall(h2_json_str, guoan_matches_ser, _version=1):
    """H2收入缺口瀑布 — 2026 H2预测 vs 2025 H2实际。

    H2比赛尚未进行，仅分解对手结构和价格优化效应。
    """
    from src.classify import classify_opponent_tier as _ct, DERBY_RIVALS as _dr
    from src.classify import B_TIER as _B_TIER_LIST

    h2 = json.loads(h2_json_str)
    matches = h2["matches"]
    csl = _get_csl_parquet()

    # ── 收集 2025 H2 主场比赛（≥7月1日）──
    # 注：同个对手一赛季只来一次主场，重复出现的为杯赛（如2025-08-20云南玉昆是足协杯）
    h2_2025 = {}
    h1_opponents_2025 = set()
    if csl is not None:
        # 先收集H1对手名
        for mid in csl["match_id"].unique():
            md = csl[csl["match_id"] == mid]
            if "is_home" not in md.columns or not md["is_home"].iloc[0]:
                continue
            opp = str(md["opponent"].iloc[0]) if "opponent" in md.columns else ""
            d = str(md["match_date"].iloc[0])[:10]
            if d.startswith("2025") and d < "2025-07-01":
                h1_opponents_2025.add(opp)
        # 再收集H2，排除H1已出现的对手（杯赛）
        for mid in csl["match_id"].unique():
            md = csl[csl["match_id"] == mid]
            if "is_home" not in md.columns or not md["is_home"].iloc[0]:
                continue
            opp = str(md["opponent"].iloc[0]) if "opponent" in md.columns else ""
            if not opp:
                continue
            d = str(md["match_date"].iloc[0])[:10]
            if not d.startswith("2025") or d < "2025-07-01":
                continue
            if d in h2_2025:
                continue
            if opp in h1_opponents_2025:
                continue  # 杯赛，非CSL
            t = _ct(opp)
            if t == "B" and not any(x in opp or opp in x for x in _B_TIER_LIST):
                continue
            h2_2025[d] = {"opponent": opp, "revenue": float(md["实际支付价格"].sum()), "tier": t}

    rev_2025_h2 = sum(m["revenue"] for m in h2_2025.values())
    n_2025 = len(h2_2025)
    n_2026 = len(matches)

    # ── 2025 各级别均价（排除杯赛：同对手只取首次主场）──
    tier_rev = {"S": 0.0, "A": 0.0, "B": 0.0, "C": 0.0}
    tier_n = {"S": 0, "A": 0, "B": 0, "C": 0}
    seen_dates = set()
    seen_opponents = set()
    if csl is not None:
        for mid in csl["match_id"].unique():
            md = csl[csl["match_id"] == mid]
            if "is_home" not in md.columns or not md["is_home"].iloc[0]:
                continue
            opp = str(md["opponent"].iloc[0]) if "opponent" in md.columns else ""
            if not opp:
                continue
            d = str(md["match_date"].iloc[0])[:10]
            if not d.startswith("2025") or d in seen_dates:
                continue
            if opp in seen_opponents:
                continue  # 同对手再次出现=杯赛
            t = _ct(opp)
            if t == "B" and not any(x in opp or opp in x for x in _B_TIER_LIST):
                continue
            seen_dates.add(d)
            seen_opponents.add(opp)
            tier_rev[t] += float(md["实际支付价格"].sum())
            tier_n[t] += 1

    tier_avg = {t: tier_rev[t] / tier_n[t] if tier_n[t] > 0 else 0
                for t in ["S", "A", "B", "C"]}

    # ── 对手结构 ──
    tier_n_2025 = {"S": 0, "A": 0, "B": 0, "C": 0}
    for m in h2_2025.values():
        tier_n_2025[m["tier"]] += 1

    tier_n_2026 = {"S": 0, "A": 0, "B": 0, "C": 0}
    expected_2026 = 0.0
    for m in matches:
        t = _ct(m["opponent"])
        tier_n_2026[t] += 1
        expected_2026 += tier_avg[t]

    per_match_2025 = rev_2025_h2 / n_2025 if n_2025 > 0 else 0
    match_count_effect = per_match_2025 * (n_2026 - n_2025)
    opponent_mix = expected_2026 - per_match_2025 * n_2026

    # ── 价格优化 + 升班马效应（用 optimizer 估算）──
    optimizer = get_optimizer()
    guoan_matches = list(guoan_matches_ser)

    # 构建 standings + all_guoan（同 H1）
    _ctx_standings = {}
    for yr in ['2025', '2026']:
        st_path = ROOT / 'data' / 'processed' / f'standings_{yr}_by_round.parquet'
        if st_path.exists():
            st_df = pd.read_parquet(st_path)
            for rnd in st_df['round'].unique():
                rnd_data = st_df[st_df['round'] == rnd]
                key = f'{yr}_{int(rnd):02d}'
                if key not in _ctx_standings:
                    _ctx_standings[key] = {}
                for _, row in rnd_data.iterrows():
                    _ctx_standings[key][row['team']] = int(row['rank'])

    _all_guoan = [m for m in guoan_matches]
    _existing_dates = {m['date'] for m in _all_guoan}
    _csl2025p = ROOT / 'data' / 'raw' / 'csl_2025_all_matches.json'
    if _csl2025p.exists():
        with open(_csl2025p) as f:
            _csl2025d = json.load(f)
        for m in _csl2025d:
            if '国安' not in m.get('home', '') and '国安' not in m.get('away', ''):
                continue
            if m['date'] in _existing_dates:
                continue
            _existing_dates.add(m['date'])
            is_h = '国安' in m['home']
            opp = m['away'] if is_h else m['home']
            hg = m.get('home_goals', 0) or 0
            ag = m.get('away_goals', 0) or 0
            _all_guoan.append({
                'date': m['date'], 'opponent': opp, 'is_home': is_h,
                'completed': True,
                'hg': hg if is_h else ag,
                'ag': ag if is_h else hg,
                'round': f'第{m.get("round",0)}轮',
            })

    pricing_delta = 0.0
    promoted_delta = 0.0
    pricing_details = []
    for m in matches:
        opp = m["opponent"]
        date = m["date"]
        dt = pd.Timestamp(date)
        mock = {"date": date, "opponent": opp, "is_home": True, "completed": False}
        ctx = detect_ctx(mock, _all_guoan, _ctx_standings)
        # H2未赛，清除所有战绩相关flag（不可预测），仅保留赛程类flag
        for perf_key in ("top3_form", "away_winless", "consecutive_home_losses", "heavy_home_loss"):
            ctx.pop(perf_key, None)
        args = dict(
            derby=opp in _dr, saturday=dt.weekday() == 5,
            midweek=dt.weekday() in (1, 2, 3), summer=dt.month in (7, 8),
            late_season=dt.month >= 10,
            midseason_restart=ctx.get("midseason_restart", False),
            short_rest=ctx.get("short_rest", False),
            season_opener=ctx.get("season_opener", False),
            top3_form=False, away_winless=False,
            consecutive_home_losses=False, heavy_home_loss=False,
            match_year="2026",
        )
        try:
            opt = optimizer.optimize(opp, **args)
            pricing_delta += opt.total_revenue - opt.base_revenue
            pricing_details.append(f"{opp}:+{(opt.total_revenue - opt.base_revenue)/1e4:.0f}万")
        except Exception:
            pass

        # 升班马效应
        if opp in ("辽宁铁人", "重庆铜梁龙"):
            try:
                opt_b = optimizer.optimize(opp, pricing_tier_override="S_B",
                                           opponent_tier_override="B", **args)
                promoted_delta += opt.total_revenue - opt_b.total_revenue
            except Exception:
                pass

    total_gap = sum(m["target_revenue"] for m in matches) - rev_2025_h2
    modeled = match_count_effect + opponent_mix + pricing_delta + promoted_delta
    residual = total_gap - modeled

    # ── 组装 bars ──
    bars = [
        ("2025 H2\n实际", round(rev_2025_h2 / 1e4), "#5b9bd5"),
    ]
    if abs(match_count_effect) > 10000:
        bars.append(("场次\n差异", round(match_count_effect / 1e4), "#8a8f98"))
    bars.append(("对手\n结构", round(opponent_mix / 1e4), "#ff6b6b"))
    bars.append(("价格\n优化", round(pricing_delta / 1e4), "#51cf66"))
    if abs(promoted_delta) > 10000:
        bars.append(("升班马\n保守", round(promoted_delta / 1e4), "#ff6b6b"))
    if abs(residual) > 50:
        bars.append(("情景\n效应", round(residual / 1e4),
                    "#51cf66" if residual >= 0 else "#ff6b6b"))
    bars.append(("2026 H2\n预测", round(sum(m["target_revenue"] for m in matches) / 1e4),
                "#51cf66" if sum(m["target_revenue"] for m in matches) >= rev_2025_h2 else "#ff6b6b"))

    captions = {
        "对手结构": f"2025 H2: S/A/B/C={tier_n_2025['S']}/{tier_n_2025['A']}/{tier_n_2025['B']}/{tier_n_2025['C']} → 2026 H2: {tier_n_2026['S']}/{tier_n_2026['A']}/{tier_n_2026['B']}/{tier_n_2026['C']}。2025各级别均价: S=¥{tier_avg['S']/1e4:.0f}万 A=¥{tier_avg['A']/1e4:.0f}万 B=¥{tier_avg['B']/1e4:.0f}万 C=¥{tier_avg['C']/1e4:.0f}万",
        "价格优化": f"Optimizer V8.2调价 vs 基准价，8场合计¥{pricing_delta/1e4:+.0f}万。详情: {'; '.join(pricing_details)}",
        "升班马保守": f"辽宁铁人/重庆铜梁龙按C级(S_C)定价，升级B级(S_B)可增收约¥{abs(promoted_delta)/1e4:.0f}万",
        "情景效应": f"H2 目标值与可解释因子（赛程/定价/对手结构）之间的残差 ¥{abs(residual)/1e4:.0f}万。"
            " 已剔除 unbeaten_3 / lost_bottom 等废弃规则；未赛场次不注入战绩 flag。赛后用实际收入回填。",
    }

    return {
        "bars": bars,
        "captions": captions,
        "rev_2025_h2": rev_2025_h2,
        "rev_2026_h2": sum(m["target_revenue"] for m in matches),
    }


def draw_waterfall(bars):
    """绘制瀑布图 — 修复标签定位bug。返回 matplotlib figure。"""
    import matplotlib.pyplot as plt

    categories = [c for c, _, _ in bars]
    values = [v for _, v, _ in bars]
    colors = [clr for _, _, clr in bars]
    last_idx = len(values) - 1

    fig, ax = plt.subplots(figsize=(5, 3.5))
    fig.patch.set_facecolor("#0c0d0f")
    ax.set_facecolor("#0c0d0f")
    ax.tick_params(colors="#8a8f98", labelsize=7)
    for spine in ax.spines.values():
        spine.set_visible(False)

    # ── 画柱 ──
    running = 0
    for i, (cat, val) in enumerate(zip(categories, values)):
        if i == 0:
            running = val
            bottom, h = 0, val
        elif i == last_idx:
            bottom, h = 0, val
        else:
            h = abs(val)
            if val >= 0:
                bottom = running
            else:
                bottom = running + val
            running += val
        ax.bar(i, h, bottom=bottom, color=colors[i], width=0.5)

    # ── 标数值（每个柱子独立计算位置，修复原 bug）──
    cumulative = 0
    for i, (cat, val) in enumerate(zip(categories, values)):
        if i == 0:
            cumulative = val
            label_y = val
        elif i == last_idx:
            label_y = val  # 总柱从0开始
        else:
            if val >= 0:
                label_y = cumulative + val
            else:
                label_y = cumulative + val
            cumulative += val

        offset = 80 if val >= 0 else -120
        sign = "+" if val > 0 and 0 < i < last_idx else ""
        ax.text(i, label_y + offset,
                f"{sign}{abs(val)}万" if i > 0 and i < last_idx else f"{val}万",
                ha="center", fontsize=7, color="#c8ccd4")

    ax.set_xticks(range(len(categories)))
    ax.set_xticklabels(categories, fontsize=6.5, color="#8a8f98")
    ax.axhline(y=0, color="#ffffff22", linewidth=0.5)
    return fig

