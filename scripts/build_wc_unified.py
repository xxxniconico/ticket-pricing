"""整合 Wikipedia 已赛 + Odds API SCORES (fallback) + Odds API 未赛, 输出统一格式
支持命令行 --wiki-dir 参数 (默认用 /tmp/wc_groups/)

数据源优先级 (已赛):
  1. Wikipedia (主) — 含 group + date + 比分
  2. The Odds API SCORES (fallback) — wiki 比分缺失/未更新时补 (e.g. Tunisia 0-4 Japan, 6/20)
"""
import json, re, statistics, sys, argparse, urllib.request, urllib.parse
from datetime import datetime, timezone, timedelta
from html import unescape
from pathlib import Path

ROOT = Path('/home/xxxsuli/ticket-pricing')


def fetch_odds_scores(api_key: str, days_from: int = 3) -> list[dict]:
    """拉 The Odds API SCORES endpoint (已赛比分)."""
    url = "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/scores/?" + urllib.parse.urlencode({
        "apiKey": api_key,
        "daysFrom": days_from,
        "dateFormat": "iso",
    })
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  WARNING: SCORES endpoint failed: {e}", file=sys.stderr)
        return []


def parse_group_html(html_path, group):
    """从 Wikipedia Group 子页面 HTML 抽出比赛 (含日期)

    HTML 结构 (microdata):
      <time itemprop="dtstart published updated itvstart">2026-06-11</time>
      ... <th itemprop="homeTeam">...title="Mexico national football team"...</th>
      <th class="fscore">2-0</th>
      <th itemprop="awayTeam">...title="South Africa national football team"...</th>

    按 DOM 位置排序, 四元组配对 (date + home + score + away)
    """
    with open(html_path) as f:
        html = f.read()

    items: list[tuple[int, str, str]] = []

    for m in re.finditer(r'itemprop="homeTeam".*?title="([^"]+national [^\"]+ team)"', html, re.DOTALL):
        items.append((m.start(), 'home', m.group(1)))
    for m in re.finditer(r'itemprop="awayTeam".*?title="([^"]+national [^\"]+ team)"', html, re.DOTALL):
        items.append((m.start(), 'away', m.group(1)))
    for m in re.finditer(r'class="fscore"[^>]*>([^<]+)<', html):
        items.append((m.start(), 'score', m.group(1).strip()))
    for m in re.finditer(r'dtstart[^>]*>(\d{4}-\d{2}-\d{2})<', html):
        items.append((m.start(), 'date', m.group(1)))

    items.sort()

    matches = []
    i = 0
    while i + 3 < len(items):
        if (items[i][1] == 'date'
                and items[i + 1][1] == 'home'
                and items[i + 2][1] == 'score'
                and items[i + 3][1] == 'away'):
            date_iso = items[i][2]
            home_team = unescape(items[i + 1][2]).replace(' national football team', '').replace(' national soccer team', '')
            score = items[i + 2][2]
            away_team = unescape(items[i + 3][2]).replace(' national football team', '').replace(' national soccer team', '')
            has_score = score and score not in ('–', '-', '') and not score.startswith('Match')
            matches.append({
                'date': date_iso,
                'home_en': home_team,
                'away_en': away_team,
                'score': score if has_score else None,
                'finished': has_score,
                'group': group,
            })
            i += 4
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

    # === 2.5. SCORES endpoint fallback: 补 wiki 缺漏的已赛 ===
    # 哪些 (home, away) 已被 wiki 覆盖 (用作 key, 大小写/& 等归一)
    def _norm_name(n: str) -> str:
        return n.lower().replace(" & ", " and ").replace("'", "").strip()

    wiki_done = {(_norm_name(NAME_FIX.get(m['home_en']) or m['home_en']),
                  _norm_name(NAME_FIX.get(m['away_en']) or m['away_en'])): m
                 for m in groups_data if m['finished']}

    env_text = (ROOT / '.env').read_text() if (ROOT / '.env').exists() else ''
    api_key = next((line.split('=', 1)[1].strip() for line in env_text.splitlines()
                    if line.startswith('ODDS_API_KEY=') and '***' not in line), None)

    if api_key:
        scores_data = fetch_odds_scores(api_key, days_from=3)
        added = 0
        for sm in scores_data:
            if not sm.get('completed') or not sm.get('scores'):
                continue
            s = {x['name']: x['score'] for x in sm['scores']}
            h, a = sm['home_team'], sm['away_team']
            if (_norm_name(h), _norm_name(a)) in wiki_done:
                continue
            grp = team_to_group.get(h) or team_to_group.get(a)
            if not grp:
                continue
            # 转换 UTC → BJ date (跟未赛规则一致)
            t = datetime.fromisoformat(sm['commence_time'].replace('Z', '+00:00'))
            bj = t.astimezone(timezone(timedelta(hours=8)))
            groups_data.append({
                'group': grp,
                'home_en': h,
                'away_en': a,
                'score': f"{s[h]}–{s[a]}",
                'finished': True,
                'date': bj.strftime('%Y-%m-%d'),
            })
            added += 1
        print(f'  SCORES fallback: +{added} 场 (wiki 缺漏已补)', file=sys.stderr)
    else:
        print('  ODDS_API_KEY 未在 .env 找到, 跳过 SCORES fallback', file=sys.stderr)

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
            'date': m['date'],          # 2026-06-11 来自 Wikipedia dtstart
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