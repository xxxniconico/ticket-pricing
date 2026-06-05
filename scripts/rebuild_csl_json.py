#!/usr/bin/env python3
"""Rebuild csl_final_production_ready.json from all available seasons."""
import json, re, sys
from pathlib import Path
from collections import defaultdict

ROOT = Path('/home/xxxsuli/ticket-pricing')
CSL_PROJECT = Path('/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2')

def parse_2025_txt(path):
    """Parse 2025赛季中超联赛完整比分.txt"""
    with open(path) as f:
        text = f.read()
    
    # Chinese month/day mapping
    cn_num = {'一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,'十一':11,'十二':12}
    
    def parse_cn_date(ds):
        """Parse '2025年2月22日' or '2025年4月1-2日' -> '2025-02-22'"""
        m = re.match(r'(\d{4})年(\S+?)月(\d+)', ds)
        if not m: return None
        year = m.group(1)
        month_str = m.group(2)
        day = m.group(3)
        month = cn_num.get(month_str, int(month_str) if month_str.isdigit() else 1)
        return f'{year}-{int(month):02d}-{int(day):02d}'
    
    matches = []
    blocks = re.split(r'## 第(\d+)轮\s*\(([^)]+)\)', text)
    
    i = 0
    while i < len(blocks) and not (blocks[i].strip().isdigit() and len(blocks[i].strip()) <= 2):
        i += 1
    
    while i + 2 < len(blocks):
        try:
            rnd_num = int(blocks[i].strip())
            date_range = blocks[i+1].strip()
            block = blocks[i+2]
            i += 3
        except (ValueError, IndexError):
            i += 1
            continue
        
        # Extract date: "2025年4月1-2日" -> "2025-04-01"
        date_iso = parse_cn_date(date_range)
        if not date_iso:
            continue
        
        # Parse match lines
        for line in block.split('\n'):
            line = line.strip()
            if not line.startswith('|') or '主队' in line or '---' in line or '比分' in line:
                continue
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) < 3:
                continue
            home = parts[0]; score = parts[1]; away = parts[2]
            sm = re.match(r'(\d+)\s*[-:：]\s*(\d+)', score)
            if not sm: continue
            hg, ag = int(sm.group(1)), int(sm.group(2))
            
            matches.append({
                'date': f'{date_iso} 19:35:00',
                'home_club': home, 'away_club': away,
                'score': {'home': hg, 'away': ag},
                'status': 'finished',
                'round': f'第{rnd_num}轮',
                'source': 'txt_2025_complete',
            })
    return matches

def parse_2024_json(path):
    """Convert 2024 flat JSON to standard format. Fill missing dates by round interpolation."""
    data = json.load(open(path))
    
    # Build known dates from matches that have them
    known_dates = {}
    for m in data:
        if m.get('date') and m['date'].strip():
            known_dates[m['round']] = m['date']
    
    # Interpolate missing round dates (R1=2024-03-01, +7d per round)
    from datetime import datetime as dt, timedelta
    def get_round_date(rnd):
        if rnd in known_dates:
            return known_dates[rnd]
        # Find closest known rounds
        known = sorted(known_dates.keys())
        if known:
            # Linear interpolation
            for i in range(len(known)-1):
                if known[i] < rnd < known[i+1]:
                    d1 = dt.strptime(known_dates[known[i]], '%Y-%m-%d')
                    d2 = dt.strptime(known_dates[known[i+1]], '%Y-%m-%d')
                    days = (d2-d1).days / (known[i+1]-known[i]) * (rnd-known[i])
                    return (d1 + timedelta(days=int(days))).strftime('%Y-%m-%d')
        # Fallback: R1 = March 1
        base = dt(2024, 3, 1) + timedelta(days=(rnd-1)*7)
        return base.strftime('%Y-%m-%d')
    
    matches = []
    for m in data:
        d = m.get('date', '').strip() if m.get('date') else ''
        if not d:
            d = get_round_date(m['round'])
        matches.append({
            'date': f"{d} 19:35:00",
            'home_club': m['home'],
            'away_club': m['away'],
            'score': {'home': m['home_goals'], 'away': m['away_goals']},
            'status': 'finished' if m['home_goals'] is not None else 'scheduled',
            'round': f"第{m['round']}轮",
            'source': 'json_2024',
        })
    return matches

def extract_2026_matches(path):
    """Extract ALL 2026 CSL matches (completed + scheduled), deduplicating."""
    data = json.load(open(path))
    seen = set()
    matches = []
    for lg in data.get('leagues', []):
        if lg.get('name') != '中超联赛':
            continue
        for m in lg.get('matches', []):
            s = m.get('score', {})
            hg = s.get('home') if isinstance(s, dict) else None
            ag = s.get('away') if isinstance(s, dict) else None
            key = (m['date'][:10], m.get('home_club', ''), m.get('away_club', ''))
            if key not in seen:
                seen.add(key)
                m['status'] = 'finished' if (hg is not None and ag is not None) else 'scheduled'
                matches.append(m)
    return matches

# --- Main ---
print("Parsing 2025 TXT...")
m2025 = parse_2025_txt('/mnt/c/Users/xxxsu/OneDrive/文档/2025赛季中超联赛完整比分.txt')
print(f"  2025: {len(m2025)} matches")

print("Parsing 2024 JSON...")
m2024 = parse_2024_json(ROOT / 'data/raw/csl_2024_all_matches.json')
print(f"  2024: {len(m2024)} matches")

print("Extracting 2026 from JSON...")
# Use clean backup with all 30 rounds
m2026 = extract_2026_matches(CSL_PROJECT / 'data/csl_final_production_ready.json.bak.20260525')
print(f"  2026: {len(m2026)} matches")

# Deduplicate within each season
def dedup(matches):
    seen = set()
    result = []
    for m in matches:
        key = (m['date'][:10], m['home_club'], m['away_club'])
        if key not in seen:
            seen.add(key)
            result.append(m)
    return result

m2024 = dedup(m2024)
m2025 = dedup(m2025)
m2026 = dedup(m2026)

all_matches = m2024 + m2025 + m2026
all_matches.sort(key=lambda x: x['date'])

# Assign unique match_ids
for i, m in enumerate(all_matches):
    m['match_id'] = 1000000 + i

# Build unified JSON
output = {
    'season': '2024-2026',
    'leagues': [{
        'name': '中超联赛',
        'matches': all_matches,
    }],
    'meta': {
        'description': 'Cross-season CSL data (2024+2025+2026)',
        'seasons': {'2024': len(m2024), '2025': len(m2025), '2026': len(m2026)},
    }
}

# Backup current
import shutil
current = CSL_PROJECT / 'data/csl_final_production_ready.json'
backup = CSL_PROJECT / f'data/csl_final_production_ready.json.bak.{__import__("datetime").datetime.now().strftime("%Y%m%d_%H%M")}'
shutil.copy(current, backup)
print(f"\nBacked up to {backup.name}")

# Write
with open(current, 'w') as f:
    json.dump(output, f, ensure_ascii=False)

# Verify
data = json.load(open(current))
all_teams = set()
for m in data['leagues'][0]['matches']:
    all_teams.add(m['home_club'])
    all_teams.add(m['away_club'])

from collections import Counter
seasons = Counter(m['date'][:4] for m in data['leagues'][0]['matches'])
print(f"\nWritten: {len(data['leagues'][0]['matches'])} matches")
print(f"Seasons: {dict(seasons)}")
print(f"Unique teams: {len(all_teams)}")

# Quick verify with csl_context
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(CSL_PROJECT))
from src.csl_context import load_csl_data
_, rounds, _ = load_csl_data()
round_teams = set()
for rnd in rounds.values():
    round_teams.update(rnd.keys())
print(f"rounds unique teams: {len(round_teams)}")
print("DONE")
