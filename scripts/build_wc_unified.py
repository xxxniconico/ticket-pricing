"""整合 Wikipedia 已赛 + Odds API 未赛, 输出统一格式
支持命令行 --wiki-dir 参数 (默认用 /tmp/wc_groups/)
"""
import json, re, statistics, sys, argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')


def parse_group_html(html_path, group):
    """从 Wikipedia Group 子页面 HTML 抽出比赛"""
    with open(html_path) as f:
        html = f.read()

    home_iter = re.finditer(r'itemprop="homeTeam".*?title="([^"]+national [^"]+ team)"', html, re.DOTALL)
    away_iter = re.finditer(r'itemprop="awayTeam".*?title="([^"]+national [^"]+ team)"', html, re.DOTALL)
    score_iter = re.finditer(r'class="fscore"[^>]*>([^<]+)<', html)

    homes = list(home_iter)
    aways = list(away_iter)
    scores = list(score_iter)

    items = []
    for h in homes:
        items.append((h.start(), 'home', h.group(1)))
    for a in aways:
        items.append((a.start(), 'away', a.group(1)))
    for s in scores:
        items.append((s.start(), 'score', s.group(1).strip()))
    items.sort()

    matches = []
    i = 0
    while i < len(items) - 2:
        if items[i][1] == 'home' and items[i+1][1] == 'score' and items[i+2][1] == 'away':
            home_team = items[i][2].replace(' national football team', '').replace(' national soccer team', '')
            score = items[i+1][2]
            away_team = items[i+2][2].replace(' national football team', '').replace(' national soccer team', '')
            has_score = score and score not in ('–', '-', '') and not score.startswith('Match')
            matches.append({
                'date': '2026-06 (Wikipedia)',
                'home_en': home_team,
                'away_en': away_team,
                'score': score if has_score else None,
                'finished': has_score,
                'group': group,
            })
            i += 3
        else:
            i += 1
    return matches


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--wiki-dir', default='/tmp/wc_groups', help='Wikipedia HTML 目录')
    parser.add_argument('--odds-file', default=None, help='Odds API JSON (默认 latest)')
    args = parser.parse_args()

    wiki_dir = Path(args.wiki_dir)
    if not wiki_dir.exists():
        print(f'Wiki dir not found: {wiki_dir}', file=sys.stderr)
        sys.exit(1)

    # === 1. Wikipedia 已赛 ===
    groups_data = []
    for grp in 'ABCDEFGHIJKL':
        path = wiki_dir / f'grp_{grp}.html'
        if path.exists():
            matches = parse_group_html(str(path), grp)
            groups_data.extend(matches)
            print(f'  Group {grp}: {len(matches)} matches', file=sys.stderr)

    # === 2. 队名归一化 ===
    NAME_FIX = {
        "Canada men's": "Canada",
        "United States men's": "USA",
        "Sweden men's": "Sweden",
        "Australia men's": "Australia",
        "New Zealand men's": "New Zealand",
    }

    team_to_group = {}
    for m in groups_data:
        h = NAME_FIX.get(m['home_en'], m['home_en'])
        a = NAME_FIX.get(m['away_en'], m['away_en'])
        team_to_group[h] = m['group']
        team_to_group[a] = m['group']
    team_to_group['Bosnia & Herzegovina'] = team_to_group.get('Bosnia and Herzegovina', 'B')

    # === 3. Odds API 未赛 ===
    if args.odds_file:
        odds_path = Path(args.odds_file)
    else:
        odds_files = sorted((ROOT / 'data/raw/odds').glob('fifa_wc_*.json'))
        odds_path = odds_files[-1] if odds_files else None

    odds_data = []
    if odds_path and odds_path.exists():
        odds_data = json.loads(odds_path.read_text())
        print(f'Odds data: {len(odds_data)} matches from {odds_path.name}', file=sys.stderr)

    # === 4. 计算 metrics ===
    def match_metrics(match):
        rows = []
        for bm in match.get('bookmakers', []):
            outcomes = bm['markets'][0].get('outcomes', [])
            odds_h = odds_d = odds_a = None
            for o in outcomes:
                if o['name'] == match['home_team']: odds_h = o['price']
                elif o['name'] == match['away_team']: odds_a = o['price']
                elif o['name'] == 'Draw': odds_d = o['price']
            if not (odds_h and odds_d and odds_a):
                continue
            raw = 1/odds_h + 1/odds_d + 1/odds_a
            rows.append({
                'h': odds_h, 'd': odds_d, 'a': odds_a,
                'p_h': (1/odds_h)/raw, 'p_d': (1/odds_d)/raw, 'p_a': (1/odds_a)/raw,
                'vig': raw - 1,
            })
        if not rows:
            return {}
        p_h_list = [r['p_h'] for r in rows]
        if len(p_h_list) >= 5:
            med = statistics.median(p_h_list)
            mad = statistics.median([abs(p - med) for p in p_h_list]) or 0.001
            filtered = [r for r, p in zip(rows, p_h_list) if abs(p - med) < 3 * mad]
            if len(filtered) >= 5:
                rows = filtered
                p_h_list = [r['p_h'] for r in rows]
        return {
            'n_bookmakers': len(rows),
            'avg_h': statistics.mean(r['h'] for r in rows),
            'avg_d': statistics.mean(r['d'] for r in rows),
            'avg_a': statistics.mean(r['a'] for r in rows),
            'p_h_mean': statistics.mean(p_h_list),
            'p_h_std': statistics.stdev(p_h_list) if len(p_h_list) > 1 else 0,
            'avg_vig': statistics.mean(r['vig'] for r in rows),
        }

    # === 5. 整合 ===
    unified = []

    # 已赛
    for m in groups_data:
        if not m['finished']:
            continue
        h = NAME_FIX.get(m['home_en'], m['home_en'])
        a = NAME_FIX.get(m['away_en'], m['away_en'])
        unified.append({
            'group': m['group'],
            'home_en': h,
            'away_en': a,
            'score': m['score'],
            'finished': True,
            'commence_time': None,
        })

    # 未赛
    now = datetime(2026, 6, 20, 14, 0, tzinfo=timezone.utc)
    for m in odds_data:
        utc = datetime.fromisoformat(m['commence_time'].replace('Z','')).replace(tzinfo=timezone.utc)
        if utc < now:
            continue
        h = m['home_team']
        a = m['away_team']
        grp = team_to_group.get(h) or team_to_group.get(a, '?')
        metrics = match_metrics(m)
        bj_dt = utc + timedelta(hours=8)
        unified.append({
            'group': grp,
            'commence_time': m['commence_time'],
            'date_cn': bj_dt.strftime('%m-%d %H:%M'),
            'date': bj_dt.strftime('%Y-%m-%d'),
            'home_en': h,
            'away_en': a,
            'score': None,
            'finished': False,
            'metrics': metrics,
        })

    # 按 group + date 排序
    unified.sort(key=lambda x: (x.get('group', '?'), x.get('date') or x.get('commence_time') or '9999'))

    # === 6. 保存 ===
    out = ROOT / 'data/processed/wc_2026_unified.json'
    with open(out, 'w') as f:
        json.dump(unified, f, indent=2, ensure_ascii=False)

    finished_count = sum(1 for x in unified if x['finished'])
    unfinished_count = sum(1 for x in unified if not x['finished'])
    print(f'✓ Saved {len(unified)} matches to {out}')
    print(f'  Finished: {finished_count}, Unfinished: {unfinished_count}', file=sys.stderr)


if __name__ == '__main__':
    main()