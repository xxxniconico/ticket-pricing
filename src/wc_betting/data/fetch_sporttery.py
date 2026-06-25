"""Fetch live odds from China Sporttery (体彩) for WC 2026 matches.

Sporttery provides 4 bet pool types we care about:
  had  — 胜平负 (1X2, 3 options H/D/A)
  hhad — 让球胜平负 (handicap 1X2, 3 options + goalLine)
  crs  — 比分 (correct score, ~25 options)
  ttg  — 总进球数 (total goals, 8 options: 0..6, 7+)

Return rate ~70% (vig ~30%) — 3-5x international bookmakers.

Network note
------------
sporttery.cn is NOT reachable from the dev sandbox (HTTP 567/000). This
module is designed to run on the user's China machine. It caches every raw
response under /tmp/sporttery_cache/ so a single successful run can be
replayed for offline development.

Manual fallback
---------------
`load_manual_odds(path)` reads a JSON file with the same shape as the API
output, for when the user types in odds observed on sporttery.cn web UI.

See docs/plans/wc-betting-strategy-20260620.md §P8.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
CACHE_DIR = Path(os.environ.get("TMPDIR", "/tmp")) / "sporttery_cache"

API_BASE = "https://webapi.sporttery.cn/gateway/jc/football/getMatchCalculatorV1.qry"
UA = "Mozilla/5.0 (research; wc-betting-strategy)"
REQUEST_DELAY = 2.0  # polite delay between pool requests (avoid 403 rate-limit)

# Pool codes -> (English name, Chinese name)
POOL_CODES: dict[str, tuple[str, str]] = {
    "had":  ("1X2",            "胜平负"),
    "hhad": ("Handicap 1X2",   "让球胜平负"),
    "crs":  ("Correct Score",  "比分"),
    "ttg":  ("Total Goals",    "总进球数"),
}

# Reverse map of dashboard/app_fifa_wc.py:TEAM_CN  {中文 -> English}.
# Built at import time below. Handles sporttery's short-name variants.
_TEAM_CN_OVERRIDE: dict[str, str] = {
    # sporttery sometimes uses alternate short names; map them to TEAM_CN keys.
    "美国": "United States",
    "科特迪瓦": "Ivory Coast",
    "刚果(金)": "DR Congo",
    "刚果民主共和国": "DR Congo",
    "波黑": "Bosnia and Herzegovina",
    "沙特": "Saudi Arabia",
    "沙特阿拉伯": "Saudi Arabia",
    "库拉索": "Curacao",
    "捷克斯洛伐克": "Czech Republic",
    "捷克": "Czech Republic",
    "韩国": "South Korea",
    "伊朗": "Iran",
    "突尼斯": "Tunisia",
    "乌拉圭": "Uruguay",
    "约旦": "Jordan",
    "新西兰": "New Zealand",
    "佛得角": "Cape Verde",
    "阿尔及利亚": "Algeria",
    "塞内加尔": "Senegal",
    "哥伦比亚": "Colombia",
    "刚果金": "DR Congo",
    "克罗地亚": "Croatia",
    "加纳": "Ghana",
    "巴拿马": "Panama",
    "乌兹别克": "Uzbekistan",
    "乌兹别克斯坦": "Uzbekistan",
    "阿尔及利": "Algeria",
    "厄瓜多尔": "Ecuador",
    "卡塔尔": "Qatar",
    "摩洛哥": "Morocco",
    "海地": "Haiti",
    "苏格兰": "Scotland",
    "巴拉圭": "Paraguay",
    "澳大利亚": "Australia",
    "土耳其": "Turkey",
    "德国": "Germany",
    "日本": "Japan",
    "瑞典": "Sweden",
    "比利时": "Belgium",
    "埃及": "Egypt",
    "西班牙": "Spain",
    "法国": "France",
    "伊拉克": "Iraq",
    "挪威": "Norway",
    "阿根廷": "Argentina",
    "奥地利": "Austria",
    "葡萄牙": "Portugal",
    "墨西哥": "Mexico",
    "南非": "South Africa",
    "瑞士": "Switzerland",
    "巴西": "Brazil",
    "荷兰": "Netherlands",
    "英格兰": "England",
    "加拿大": "Canada",
}


def _build_cn_to_en_map() -> dict[str, str]:
    """Reverse TEAM_CN from dashboard/app_fifa_wc.py -> {中文: English}.

    Imported lazily so this module is usable standalone (e.g. inside tests
    that don't have streamlit installed).
    """
    try:
        from dashboard.app_fifa_wc import TEAM_CN  # type: ignore
    except Exception:  # noqa: BLE001
        # Fallback: hard-coded key set (covers all 48 WC 2026 teams).
        # Mirrors dashboard/app_fifa_wc.py:TEAM_CN values.
        TEAM_CN_FALLBACK: dict[str, tuple[str, str]] = {
            "Mexico":               ("墨西哥", "mx"),
            "South Africa":         ("南非", "za"),
            "South Korea":          ("韩国", "kr"),
            "Czech Republic":       ("捷克", "cz"),
            "Canada":               ("加拿大", "ca"),
            "Bosnia and Herzegovina": ("波黑", "ba"),
            "Qatar":                ("卡塔尔", "qa"),
            "Switzerland":          ("瑞士", "ch"),
            "Brazil":               ("巴西", "br"),
            "Morocco":              ("摩洛哥", "ma"),
            "Haiti":                ("海地", "ht"),
            "Scotland":             ("苏格兰", "gb-sct"),
            "United States":        ("美国", "us"),
            "Paraguay":             ("巴拉圭", "py"),
            "Australia":            ("澳大利亚", "au"),
            "Turkey":               ("土耳其", "tr"),
            "Germany":              ("德国", "de"),
            "Curacao":              ("库拉索", "cw"),
            "Ivory Coast":          ("科特迪瓦", "ci"),
            "Ecuador":              ("厄瓜多尔", "ec"),
            "Netherlands":          ("荷兰", "nl"),
            "Japan":                ("日本", "jp"),
            "Sweden":               ("瑞典", "se"),
            "Tunisia":              ("突尼斯", "tn"),
            "Belgium":              ("比利时", "be"),
            "Egypt":                ("埃及", "eg"),
            "Iran":                 ("伊朗", "ir"),
            "New Zealand":          ("新西兰", "nz"),
            "Spain":                ("西班牙", "es"),
            "Cape Verde":           ("佛得角", "cv"),
            "Saudi Arabia":         ("沙特", "sa"),
            "Uruguay":              ("乌拉圭", "uy"),
            "France":               ("法国", "fr"),
            "Senegal":              ("塞内加尔", "sn"),
            "Iraq":                 ("伊拉克", "iq"),
            "Norway":               ("挪威", "no"),
            "Argentina":            ("阿根廷", "ar"),
            "Algeria":              ("阿尔及利亚", "dz"),
            "Austria":              ("奥地利", "at"),
            "Jordan":               ("约旦", "jo"),
            "Portugal":             ("葡萄牙", "pt"),
            "DR Congo":             ("刚果(金)", "cd"),
            "Uzbekistan":           ("乌兹别克斯坦", "uz"),
            "Colombia":             ("哥伦比亚", "co"),
            "England":              ("英格兰", "gb-eng"),
            "Croatia":              ("克罗地亚", "hr"),
            "Ghana":                ("加纳", "gh"),
            "Panama":               ("巴拿马", "pa"),
        }
        TEAM_CN = TEAM_CN_FALLBACK  # type: ignore[assignment]
    cn_to_en: dict[str, str] = {}
    for en_name, (cn_name, _iso) in TEAM_CN.items():
        # First occurrence wins (TEAM_CN has both "USA" and "United States"
        # → "美国"; override below resolves ambiguity to "United States").
        cn_to_en.setdefault(cn_name, en_name)
    # Apply manual overrides (short-name / ambiguous cases).
    cn_to_en.update(_TEAM_CN_OVERRIDE)
    return cn_to_en


CN_TO_EN: dict[str, str] = _build_cn_to_en_map()


def _fetch_text(url: str, cache: Path | None = None,
                delay: float = REQUEST_DELAY, timeout: int = 8) -> str:
    """Fetch URL as text, caching to disk. Tries network first, falls back to
    cache on failure. Pass cache=None to skip caching entirely."""
    # Try network first
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.sporttery.cn/jc/jsq/spfxspf.html",
        "Origin": "https://www.sporttery.cn",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
        time.sleep(delay)
        return text
    except Exception:
        if cache is not None and cache.exists():
            return cache.read_text(encoding="utf-8")
        raise


def _to_float(x) -> float | None:
    if x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    if not s or s in ("-", "—", "null", "None"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(x) -> int | None:
    f = _to_float(x)
    return int(f) if f is not None else None


def _pick(d: dict, *keys: str):
    """Return the first present key from d (case-insensitive)."""
    lower = {k.lower(): k for k in d.keys()} if isinstance(d, dict) else {}
    for k in keys:
        if k in d:
            return d[k]
        if k.lower() in lower:
            return d[lower[k.lower()]]
    return None


def _parse_match_time(raw) -> str | None:
    """Parse sporttery matchTime → 'YYYY-MM-DD'. Returns None on failure."""
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d %H:%M:%S",
                "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # ISO with TZ
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


# ---- Per-pool option normalization ---------------------------------------

def _norm_had_option(opt: str) -> str:
    """had/hhad option → 'H'/'D'/'A'."""
    s = str(opt).strip().upper()
    if s in ("H", "HH", "HOME", "3", "胜", "主胜"):
        return "H"
    if s in ("D", "DRAW", "1", "平", "主平"):
        return "D"
    if s in ("A", "AA", "AWAY", "0", "负", "客胜"):
        return "A"
    return s


def _parse_crs_option(opt, name_hint: str | None = None) -> tuple[int, int] | str:
    """crs option → (home_goals, away_goals) or one of 'H_OTHER'/'D_OTHER'/'A_OTHER'.

    sporttery encodes correct score as either:
      - 4-digit numeric: 'HHAA' where HH = home goals, AA = away goals
        (e.g. '0100' = 0:0, '0101' = 1:0, '0302' = 3:2)
      - special codes for "other": 胜其他/平其他/负其他
      - or a literal score string '1:0' / '1-0' / '10' (2-digit compact)
    """
    if opt is None and name_hint is None:
        return "?"
    s = str(opt if opt is not None else "").strip()
    name = (name_hint or "").strip()

    # Special "other" buckets by Chinese name or code.
    if "胜其他" in name or s in ("0900", "9", "HS"):
        return "H_OTHER"
    if "平其他" in name or s in ("1000", "10", "DS"):
        return "D_OTHER"
    if "负其他" in name or s in ("1100", "11", "AS"):
        return "A_OTHER"

    # 4-digit numeric code HHAA.
    if re.fullmatch(r"\d{4}", s):
        h = int(s[:2]); a = int(s[2:])
        return (h, a)
    # 3-digit code HHA (away < 10) — sporttery sometimes pads left.
    if re.fullmatch(r"\d{3}", s):
        h = int(s[:2]); a = int(s[2])
        return (h, a)

    # Literal score 'H:A' or 'H-A'.
    m = re.fullmatch(r"(\d{1,2})\s*[:-]\s*(\d{1,2})", s)
    if m:
        return (int(m.group(1)), int(m.group(2)))

    # Compact 2-digit 'HA' (e.g. '10' = 1:0, '21' = 2:1, '07' = 0:7).
    if re.fullmatch(r"\d{2}", s):
        return (int(s[0]), int(s[1]))

    # Fall back to name hint.
    m2 = re.fullmatch(r"(\d{1,2})\s*[:-]\s*(\d{1,2})", name)
    if m2:
        return (int(m2.group(1)), int(m2.group(2)))
    return s or "?"


def _norm_ttg_option(opt, name_hint: str | None = None) -> int:
    """ttg option → integer total goals (7 represents '7+')."""
    s = str(opt if opt is not None else "").strip()
    name = (name_hint or "").strip()

    # Direct integer.
    m = re.search(r"\d+", s)
    if m:
        v = int(m.group(0))
        if 0 <= v <= 7:
            return v
    # Name like '7+' or '7球及以上' or '7球或以上'.
    if "7" in s or "7" in name:
        return 7
    m2 = re.search(r"\d+", name)
    if m2:
        v = int(m2.group(0))
        if 0 <= v <= 7:
            return v
    return -1


# ---- Per-pool extraction (sporttery actual API structure) ------------------

# CRS key mapping: sporttery uses 's{HH}s{AA}' (e.g. 's01s00' = 1:0).
# Special keys: s1sh=胜其他, s1sd=平其他, s1sa=负其他.
_CRS_SPECIAL = {"s1sh": "H_OTHER", "s1sd": "D_OTHER", "s1sa": "A_OTHER"}
_CRS_KEY_RE = re.compile(r"^s(\d{2})s(\d{2})$")


def _extract_had_hhad(match: dict, pool: str) -> tuple[float | None, dict[str, float]]:
    """had/hhad: odds in oddsList[0] with fields h/d/a + goalLine (hhad)."""
    odds_list = match.get("oddsList") or []
    # Find the entry matching this pool (poolCode is uppercase like "HAD").
    entry = None
    for item in odds_list:
        if isinstance(item, dict) and item.get("poolCode", "").lower() == pool:
            entry = item
            break
    if entry is None and odds_list and isinstance(odds_list[0], dict):
        entry = odds_list[0]  # fallback: first entry
    if not isinstance(entry, dict):
        return None, {}

    out: dict[str, float] = {}
    for k, sel in (("h", "H"), ("d", "D"), ("a", "A")):
        v = _to_float(entry.get(k))
        if v is not None and v > 1.0:
            out[sel] = v

    handicap = None
    if pool == "hhad":
        gl = entry.get("goalLineValue") or entry.get("goalLine")
        handicap = _to_float(gl)
    return handicap, out


def _extract_crs(match: dict) -> tuple[float | None, dict[str, float]]:
    """crs: odds in match['crs'] dict with keys s{HH}s{AA} + s1sh/s1sd/s1sa."""
    crs = match.get("crs")
    if not isinstance(crs, dict):
        return None, {}
    out: dict[str, float] = {}
    for k, val in crs.items():
        if k in ("updateDate", "updateTime", "goalLine", "goalLineValue"):
            continue
        if k.endswith("f"):
            continue  # sell-status flag, not odds
        v = _to_float(val)
        if v is None or v <= 1.0:
            continue
        if k in _CRS_SPECIAL:
            out[_CRS_SPECIAL[k]] = v
            continue
        m = _CRS_KEY_RE.match(k)
        if m:
            h, a = int(m.group(1)), int(m.group(2))
            out[f"({h},{a})"] = v
    return None, out


def _extract_ttg(match: dict) -> tuple[float | None, dict[str, float]]:
    """ttg: odds in match['ttg'] dict with keys s0..s7 (s7 = 7+)."""
    ttg = match.get("ttg")
    if not isinstance(ttg, dict):
        return None, {}
    out: dict[str, float] = {}
    for k, val in ttg.items():
        if k in ("updateDate", "updateTime", "goalLine", "goalLineValue"):
            continue
        if k.endswith("f"):
            continue  # sell-status flag
        m = re.match(r"^s(\d+)$", k)
        if not m:
            continue
        idx = int(m.group(1))
        if 0 <= idx <= 7:
            v = _to_float(val)
            if v is not None and v > 1.0:
                out[str(idx)] = v
    return None, out


def _extract_options(match: dict, pool: str) -> tuple[float | None, dict[str, float]]:
    """Extract (handicap, {option_key: odds}) from one match dict."""
    if pool in ("had", "hhad"):
        return _extract_had_hhad(match, pool)
    if pool == "crs":
        return _extract_crs(match)
    if pool == "ttg":
        return _extract_ttg(match)
    return None, {}


def _extract_matches(payload: dict, pool: str) -> list[dict]:
    """Flatten value.matchInfoList[].subMatchList[] → flat match list."""
    if not isinstance(payload, dict):
        return []
    value = payload.get("value")
    if not isinstance(value, dict):
        return []
    mil = value.get("matchInfoList")
    if not isinstance(mil, list):
        return []
    matches: list[dict] = []
    for date_group in mil:
        if not isinstance(date_group, dict):
            continue
        sml = date_group.get("subMatchList")
        if isinstance(sml, list):
            matches.extend(m for m in sml if isinstance(m, dict))
    return matches


def fetch_odds(pool_code: str, cache_only: bool = False,
               cache_dir: Path | None = None) -> list[dict]:
    """Fetch one pool's odds for all current matches.

    Returns a list of dicts:
        {match_num, home_cn, away_cn, home_en, away_en, league,
         date, group, pool_code, handicap, odds: {option_key: price}}

    `cache_only=True` → only read from cache, never hit network.
    """
    if pool_code not in POOL_CODES:
        raise ValueError(f"unknown pool_code: {pool_code}")
    cache_dir = cache_dir or CACHE_DIR
    cache_file = cache_dir / f"{pool_code}.json"

    if cache_only:
        if not cache_file.exists():
            return []
        text = cache_file.read_text(encoding="utf-8")
    else:
        url = f"{API_BASE}?poolCode={pool_code}&channel=c_web"
        try:
            text = _fetch_text(url, cache=cache_file)
        except Exception as exc:  # noqa: BLE001
            print(f"[fetch_sporttery] {pool_code} fetch failed: {exc}",
                  file=sys.stderr)
            if cache_file.exists():
                text = cache_file.read_text(encoding="utf-8")
            else:
                return []

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        print(f"[fetch_sporttery] {pool_code} JSON parse failed: {exc}",
              file=sys.stderr)
        return []

    # Check API error envelope.
    if str(payload.get("errorCode", "0")) != "0":
        print(f"[fetch_sporttery] {pool_code} API error: "
              f"{payload.get('errorMessage')}", file=sys.stderr)

    matches_raw = _extract_matches(payload, pool_code)
    results: list[dict] = []
    for m in matches_raw:
        home_cn = (_pick(m, "homeTeamAbbName", "homeTeamAllName",
                          "homeTeamName", "homeName") or "").strip()
        away_cn = (_pick(m, "awayTeamAbbName", "awayTeamAllName",
                          "awayTeamName", "awayName") or "").strip()
        league = (_pick(m, "leagueAbbName", "leagueAllName",
                        "leagueName") or "").strip()
        match_num = _pick(m, "matchNumStr", "matchNum", "matchId") or ""
        date = _parse_match_time(_pick(m, "matchDate", "matchTime",
                                       "businessDate"))
        group = (m.get("groupName") or "").strip()
        handicap, odds = _extract_options(m, pool_code)
        if not odds:
            continue  # match not offered in this pool
        home_en = CN_TO_EN.get(home_cn)
        away_en = CN_TO_EN.get(away_cn)
        results.append({
            "match_num": str(match_num),
            "home_cn": home_cn,
            "away_cn": away_cn,
            "home_en": home_en,
            "away_en": away_en,
            "league": league,
            "date": date,
            "group": group,
            "pool_code": pool_code,
            "handicap": handicap,
            "odds": odds,
        })
    return results


def fetch_all(cache_only: bool = False,
              cache_dir: Path | None = None) -> list[dict]:
    """Fetch all 4 pools (had/hhad/crs/ttg). Returns flat list of match-pool rows."""
    out: list[dict] = []
    for pool in POOL_CODES:
        rows = fetch_odds(pool, cache_only=cache_only, cache_dir=cache_dir)
        out.extend(rows)
        print(f"[fetch_sporttery] {pool}: {len(rows)} match-rows")
    return out


# ---- Manual fallback ------------------------------------------------------

def load_manual_odds(path: str | Path) -> list[dict]:
    """Load manually-typed odds from a JSON file.

    Expected schema (same shape as fetch_odds output):
        [
          {
            "match_num": "1",
            "home_cn": "荷兰", "away_cn": "瑞典",
            "home_en": "Netherlands", "away_en": "Sweden",
            "league": "世界杯",
            "date": "2026-06-21",
            "pool_code": "crs",
            "handicap": null,
            "odds": {"(1,0)": 8.5, "(2,1)": 9.0, "H_OTHER": 60.0, ...}
          },
          ...
        ]

    Missing fields are filled from CN_TO_EN when possible.
    """
    p = Path(path)
    data = json.loads(p.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "matches" in data:
        data = data["matches"]
    if not isinstance(data, list):
        raise ValueError("manual odds file must be a list or {matches: [...]}")
    out: list[dict] = []
    for row in data:
        if not isinstance(row, dict) or "odds" not in row:
            continue
        row = dict(row)  # shallow copy
        if not row.get("home_en") and row.get("home_cn"):
            row["home_en"] = CN_TO_EN.get(row["home_cn"])
        if not row.get("away_en") and row.get("away_cn"):
            row["away_en"] = CN_TO_EN.get(row["away_cn"])
        if row.get("pool_code") not in POOL_CODES:
            print(f"[fetch_sporttery] skip row with unknown pool_code: "
                  f"{row.get('pool_code')}", file=sys.stderr)
            continue
        # Normalize odds keys for had/hhad (help manual entry be lenient).
        if row["pool_code"] in ("had", "hhad"):
            row["odds"] = {_norm_had_option(k): v
                           for k, v in row["odds"].items()
                           if _norm_had_option(k) in ("H", "D", "A")}
        out.append(row)
    return out


def save_manual_template(path: str | Path, matches: list[dict]) -> None:
    """Write a stub template the user can fill in by hand.

    `matches` is typically the upcoming WC match list (from
    data/processed/wc_2026_unified.json or model_input), with home/away/group/date.
    Generates one empty entry per match per pool with odds = {}.
    """
    out: list[dict] = []
    for m in matches:
        home_en = m.get("home") or m.get("home_en") or ""
        away_en = m.get("away") or m.get("away_en") or ""
        home_cn = m.get("home_cn") or _en_to_cn(home_en)
        away_cn = m.get("away_cn") or _en_to_cn(away_en)
        for pool in POOL_CODES:
            out.append({
                "match_num": str(m.get("match_num", "")),
                "home_cn": home_cn, "away_cn": away_cn,
                "home_en": home_en, "away_en": away_en,
                "league": "世界杯",
                "date": m.get("date", ""),
                "group": m.get("group", ""),
                "pool_code": pool,
                "handicap": None if pool != "hhad" else 0,
                "odds": {},
            })
    Path(path).write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")


def _en_to_cn(en: str) -> str:
    """Reverse lookup English → Chinese team name."""
    for cn, e in CN_TO_EN.items():
        if e == en:
            return cn
    return ""


if __name__ == "__main__":
    cache_only = "--cache-only" in sys.argv
    rows = fetch_all(cache_only=cache_only)
    print(f"\n=== Sporttery fetch: {len(rows)} match-pool rows ===")
    by_pool: dict[str, int] = {}
    for r in rows:
        by_pool[r["pool_code"]] = by_pool.get(r["pool_code"], 0) + 1
    for p, n in by_pool.items():
        print(f"  {p}: {n}")
    # Show first 3 rows per pool as a sanity check.
    for p in POOL_CODES:
        subset = [r for r in rows if r["pool_code"] == p][:3]
        if not subset:
            continue
        print(f"\n--- {p} sample ---")
        for r in subset:
            print(f"  {r['home_cn']} vs {r['away_cn']}  "
                  f"handicap={r['handicap']}  odds={r['odds']}")
