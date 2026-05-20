"""外部数据源：积分榜 / 国安赛程（CSL Dashboard JSON）、天气（Open-Meteo）"""
from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd
import requests

_DEFAULT_UA = (
    "Mozilla/5.0 (compatible; ticket-pricing-bot/1.0; +https://github.com/)"
)

_CSL_JSON_URL = "https://xxxniconico.github.io/csl-dashboard-2026/dashboard_embed.json"

_SCHEDULE_COLS = ["date", "opponent", "venue", "result", "guoan_goals", "opp_goals"]


def _home_away_names(f: dict) -> tuple[str, str]:
    """兼容文档示例字段与线上 dashboard_embed 的 home_club/away_club。"""
    home = f.get("home_team", f.get("home", f.get("home_club", "")))
    away = f.get("away_team", f.get("away", f.get("away_club", "")))
    return str(home).strip(), str(away).strip()


def _parse_score_and_result(f: dict, is_home: bool) -> tuple[float, float, str]:
    """解析比分 → (国安进球, 对手进球, W/D/L)；未赛或无法解析则 (nan, nan, '')。"""
    score_raw = f.get("score", f.get("result"))
    hg: int | None = None
    ag: int | None = None
    if isinstance(score_raw, dict):
        try:
            if score_raw.get("home") is not None:
                hg = int(score_raw["home"])
            if score_raw.get("away") is not None:
                ag = int(score_raw["away"])
        except (TypeError, ValueError):
            hg = ag = None
    elif score_raw not in (None, "", []):
        parts = str(score_raw).replace(" ", "").split("-")
        if len(parts) == 2:
            try:
                hg, ag = int(parts[0]), int(parts[1])
            except ValueError:
                hg = ag = None
    if hg is None or ag is None:
        return float("nan"), float("nan"), ""
    if is_home:
        gg, og = hg, ag
        res = "W" if hg > ag else "D" if hg == ag else "L"
    else:
        gg, og = ag, hg
        res = "W" if ag > hg else "D" if ag == hg else "L"
    return float(gg), float(og), res


def _fixtures_from_dashboard(data: dict) -> list:
    """从 dashboard JSON 提取赛程列表。

    线上 embed 将 ``matches`` 放在 ``raw_data.leagues[0].matches``；
    旧版/文档可能为 ``raw_data.fixtures`` 或顶层字段，此处按序兼容。
    """
    raw = data.get("raw_data") or {}
    leagues = raw.get("leagues") or []
    for lg in leagues:
        if not isinstance(lg, dict):
            continue
        for key in ("matches", "fixtures", "games"):
            arr = lg.get(key)
            if isinstance(arr, list) and len(arr) > 0:
                return list(arr)
    for key in ("fixtures", "matches", "games"):
        arr = raw.get(key)
        if isinstance(arr, list) and len(arr) > 0:
            return list(arr)
    for key in ("fixtures", "matches", "games"):
        arr = data.get(key)
        if isinstance(arr, list) and len(arr) > 0:
            return list(arr)
    return []


def _fetch_dashboard_json() -> dict:
    """获取 CSL Dashboard JSON 数据（短重试以缓解偶发网络失败）。"""
    last: Exception | None = None
    for _attempt in range(2):
        try:
            resp = requests.get(
                _CSL_JSON_URL, timeout=20, headers={"User-Agent": _DEFAULT_UA}
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            last = e
    if last is not None:
        raise last
    raise RuntimeError("CSL dashboard JSON 请求未返回数据")


def fetch_csl_standings() -> pd.DataFrame:
    """从 dashboard_embed.json 解析积分榜（有效积分 = 赛场积分 - 扣分）。

    Returns DataFrame: rank, team, points (official), match_points, deduction
    """
    empty = pd.DataFrame(columns=["rank", "team", "points", "match_points", "deduction"])
    try:
        data = _fetch_dashboard_json()
        raw = data.get("raw_data", {})
        leagues = raw.get("leagues", [])
        if not leagues:
            return empty

        standings: list = []
        for lg in leagues:
            if isinstance(lg, dict):
                s = lg.get("standings") or []
                if isinstance(s, list) and len(s) > 0:
                    standings = s
                    break
        rows = []
        for i, s in enumerate(standings):
            name = (s.get("club_name") or "").strip()
            if not name:
                continue
            mp = s.get("points", 0) or 0
            pen = s.get("penalty_points", 0) or 0
            eff = s.get("effective_points")
            if eff is not None:
                official_pts = eff
            else:
                official_pts = mp - pen
            rows.append(
                {
                    "rank": i + 1,
                    "team": name,
                    "points": official_pts,
                    "match_points": mp,
                    "deduction": pen,
                }
            )
        if not rows:
            return empty
        df = pd.DataFrame(rows)
        df = df.sort_values("points", ascending=False).reset_index(drop=True)
        df["rank"] = range(1, len(df) + 1)
        return df
    except Exception:
        return empty


def fetch_guoan_2026_season() -> pd.DataFrame:
    """从 dashboard_embed.json 解析国安赛程。

    Returns DataFrame: date, opponent, venue, result, guoan_goals, opp_goals
    """
    empty = pd.DataFrame(columns=_SCHEDULE_COLS)
    try:
        data = _fetch_dashboard_json()
        fixtures = _fixtures_from_dashboard(data)

        if not fixtures:
            return empty

        rows = []
        for f in fixtures:
            home, away = _home_away_names(f)

            if "国安" not in home and "国安" not in away:
                continue

            is_home = "国安" in home
            opponent = away if is_home else home
            venue = "H" if is_home else "A"

            guoan_goals, opp_goals, result = _parse_score_and_result(f, is_home)

            rows.append(
                {
                    "date": f.get("date", f.get("match_date", "")),
                    "opponent": str(opponent).strip(),
                    "venue": venue,
                    "result": result,
                    "guoan_goals": guoan_goals,
                    "opp_goals": opp_goals,
                }
            )

        df = pd.DataFrame(rows)
        if df.empty:
            return empty
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"], errors="coerce")
            df = df.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)
        return df
    except Exception:
        return empty


def compute_home_form(schedule_df: pd.DataFrame, last_n: int = 5) -> float:
    """从赛程计算国安近 N 个主场胜率（result 含 胜/W 视为赢）。"""
    if schedule_df is None or schedule_df.empty:
        return 0.5
    if "venue" not in schedule_df.columns or "result" not in schedule_df.columns:
        return 0.5
    v = schedule_df["venue"].astype(str)
    home = schedule_df[v.str.contains("主", na=False) | v.str.upper().isin(["H", "HOME"])]
    recent = home.tail(last_n)
    if len(recent) == 0:
        return 0.5
    wins = 0
    for _, r in recent.iterrows():
        s = str(r.get("result", ""))
        if "胜" in s or re.search(r"\bW\b", s, re.I):
            wins += 1
        elif re.match(r"^[2-9]\s*[–-]\s*[0-1]\b", s):
            wins += 1
    return wins / len(recent)


def fetch_weather(match_date: str, lat: float = 39.93, lon: float = 116.46) -> dict:
    """Open-Meteo：比赛日气温与降水（mm）。失败返回温和默认。"""
    fallback = {"temperature": 20.0, "precipitation": 0.0}
    try:
        d = datetime.strptime(match_date[:10], "%Y-%m-%d").date()
    except ValueError:
        return fallback
    today = date.today()
    if d < today:
        base = "https://archive-api.open-meteo.com/v1/archive"
    else:
        base = "https://api.open-meteo.com/v1/forecast"
    url = (
        f"{base}?latitude={lat}&longitude={lon}"
        f"&daily=temperature_2m_mean,precipitation_sum"
        f"&start_date={d.isoformat()}&end_date={d.isoformat()}"
        f"&timezone=Asia%2FShanghai"
    )
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": _DEFAULT_UA})
        resp.raise_for_status()
        data = resp.json()
        daily = data.get("daily") or {}
        tlist = daily.get("temperature_2m_mean") or []
        plist = daily.get("precipitation_sum") or []
        t0 = float(tlist[0]) if tlist and tlist[0] is not None else 20.0
        p0 = float(plist[0]) if plist and plist[0] is not None else 0.0
        return {"temperature": t0, "precipitation": p0}
    except Exception:
        return fallback


def get_opponent_standing(team_name: str, standings: pd.DataFrame) -> int:
    """从积分榜查对手排名（模糊匹配队名）。"""
    if standings is None or standings.empty or not team_name:
        return 8
    if "team" not in standings.columns or "rank" not in standings.columns:
        return 8
    teams = standings["team"].astype(str)
    needle = team_name.strip()
    m = teams.str.contains(re.escape(needle[: min(4, len(needle))]), na=False)
    if not m.any() and len(needle) >= 2:
        m = teams.str.contains(re.escape(needle[:2]), na=False)
    if not m.any():
        return 8
    row = standings.loc[m].iloc[0]
    try:
        return int(row["rank"])
    except (ValueError, TypeError):
        return 8


def get_next_match(schedule_df: pd.DataFrame) -> dict | None:
    """下一个未赛国安主场：opponent / date / is_weekend（周六日视为周末）。"""
    if schedule_df is None or schedule_df.empty:
        return None
    need = {"date", "opponent", "venue"}
    if not need.issubset(set(schedule_df.columns)):
        return None
    today = date.today()
    v = schedule_df["venue"].astype(str)
    home = schedule_df[v.str.contains("主", na=False) | v.str.upper().isin(["H", "HOME"])]
    if home.empty:
        home = schedule_df
    for _, row in home.sort_values("date").iterrows():
        md = pd.to_datetime(row["date"], errors="coerce")
        if pd.isna(md):
            continue
        match_date = md.date()
        if match_date >= today:
            wd = match_date.weekday()
            return {
                "opponent": str(row["opponent"]).strip(),
                "date": match_date.isoformat(),
                "is_weekend": wd >= 5,
            }
    return None


# === 2025 赛季：全 30 轮主客场比分（文档）+ 日期（球天下赛程匹配） ===
_GUOAN_2025_ALL: list[tuple[int, str, str, int, int, str]] = [
    (1, "云南玉昆", "A", 2, 0, "W"),
    (2, "上海申花", "A", 1, 1, "D"),
    (3, "成都蓉城", "H", 1, 2, "L"),
    (4, "浙江俱乐部", "H", 2, 0, "W"),
    (5, "长春亚泰", "A", 2, 1, "W"),
    (6, "青岛西海岸", "H", 2, 0, "W"),
    (7, "武汉三镇", "A", 1, 1, "D"),
    (8, "山东泰山", "H", 6, 1, "W"),
    (9, "河南俱乐部", "H", 3, 1, "W"),
    (10, "上海海港", "A", 2, 1, "W"),
    (11, "深圳新鹏城", "H", 2, 0, "W"),
    (12, "大连英博海发", "A", 2, 0, "W"),
    (13, "梅州客家", "A", 2, 2, "D"),
    (14, "长春亚泰", "H", 3, 1, "W"),
    (15, "梅州客家", "H", 5, 1, "W"),
    (16, "云南玉昆", "H", 4, 2, "W"),
    (17, "上海申花", "H", 1, 3, "L"),
    (18, "成都蓉城", "A", 0, 1, "L"),
    (19, "浙江俱乐部", "A", 3, 3, "D"),
    (20, "天津津门虎", "H", 2, 1, "W"),
    (21, "山东泰山", "A", 1, 2, "L"),
    (22, "武汉三镇", "H", 2, 0, "W"),
    (23, "上海海港", "H", 2, 3, "L"),
    (24, "深圳新鹏城", "A", 0, 1, "L"),
    (25, "大连英博海发", "H", 3, 0, "W"),
    (26, "青岛西海岸", "A", 1, 1, "D"),
    (27, "河南俱乐部", "A", 1, 2, "L"),
    (28, "青岛海牛", "H", 2, 1, "W"),
    (29, "天津津门虎", "A", 3, 1, "W"),
    (30, "梅州客家", "H", 5, 1, "W"),
]

# 2025 亚冠二级联赛 E 组（与中超穿插，用于全赛事滚动战绩）
_ACL_2025: list[tuple[str, str, str, int, int, str, str]] = [
    ("ACL1", "河内公安", "H", 2, 2, "D", "2025-09-18"),
    ("ACL2", "麦克阿瑟", "A", 0, 3, "L", "2025-10-02"),
    ("ACL3", "大埔", "A", 3, 3, "D", "2025-10-23"),
    ("ACL4", "大埔", "H", 3, 0, "W", "2025-11-06"),
    ("ACL5", "河内公安", "A", 1, 2, "L", "2025-11-27"),
    ("ACL6", "麦克阿瑟", "H", 1, 2, "L", "2025-12-11"),
]

# 北京国安 2025 中超赛程（球天下，主队列左）
_GUOAN_2025_FIXTURES: list[tuple[str, str, str]] = [
    ("2025-02-22", "云南玉昆", "北京国安"),
    ("2025-03-01", "上海申花", "北京国安"),
    ("2025-03-29", "北京国安", "成都蓉城"),
    ("2025-04-02", "天津津门虎", "北京国安"),
    ("2025-04-06", "北京国安", "浙江队"),
    ("2025-04-11", "北京国安", "青岛西海岸"),
    ("2025-04-15", "武汉三镇", "北京国安"),
    ("2025-04-19", "北京国安", "山东泰山"),
    ("2025-04-25", "北京国安", "河南队"),
    ("2025-05-01", "上海海港", "北京国安"),
    ("2025-05-05", "大连英博", "北京国安"),
    ("2025-05-10", "北京国安", "深圳新鹏城"),
    ("2025-05-17", "青岛海牛", "北京国安"),
    ("2025-06-14", "北京国安", "长春亚泰"),
    ("2025-06-25", "梅州客家", "北京国安"),
    ("2025-06-30", "北京国安", "云南玉昆"),
    ("2025-07-19", "北京国安", "上海申花"),
    ("2025-07-26", "成都蓉城", "北京国安"),
    ("2025-08-03", "北京国安", "天津津门虎"),
    ("2025-08-10", "浙江队", "北京国安"),
    ("2025-08-16", "青岛西海岸", "北京国安"),
    ("2025-08-23", "北京国安", "武汉三镇"),
    ("2025-08-31", "山东泰山", "北京国安"),
    ("2025-09-12", "河南队", "北京国安"),
    ("2025-09-21", "北京国安", "上海海港"),
    ("2025-09-26", "北京国安", "大连英博"),
    ("2025-10-17", "深圳新鹏城", "北京国安"),
    ("2025-10-26", "北京国安", "青岛海牛"),
    ("2025-11-01", "长春亚泰", "北京国安"),
    ("2025-11-22", "北京国安", "梅州客家"),
]


def _normalize_club_name(name: str) -> str:
    s = str(name).strip()
    rep = {
        "浙江队": "浙江俱乐部",
        "河南队": "河南俱乐部",
        "大连英博": "大连英博海发",
    }
    for a, b in rep.items():
        s = s.replace(a, b)
    return s


_OPPONENT_RANK_2025: dict[str, int] = {
    "上海海港": 1,
    "上海申花": 2,
    "成都蓉城": 3,
    "北京国安": 4,
    "山东泰山": 5,
    "天津津门虎": 6,
    "浙江俱乐部": 7,
    "河南俱乐部": 8,
    "长春亚泰": 9,
    "青岛西海岸": 10,
    "武汉三镇": 11,
    "深圳新鹏城": 12,
    "云南玉昆": 13,
    "青岛海牛": 14,
    "大连英博海发": 15,
    "梅州客家": 16,
}


def _merge_guoan_fixture_dates(df: pd.DataFrame) -> pd.DataFrame:
    """按轮次、对手、主客将 30 轮与赛程日期对齐（同场多条取最早赛程日）。"""
    out = df.copy()
    out["date"] = pd.NaT
    guoan = "北京国安"
    for idx, row in out.sort_values("round").iterrows():
        opp = _normalize_club_name(row["opponent"])
        ven = str(row["venue"]).upper()
        cands: list[str] = []
        for d, h, a in _GUOAN_2025_FIXTURES:
            hn, an = _normalize_club_name(h), _normalize_club_name(a)
            if guoan not in hn and guoan not in an:
                continue
            is_home = guoan in hn
            if ven == "H" and not is_home:
                continue
            if ven == "A" and is_home:
                continue
            other = an if is_home else hn
            if opp not in other and other not in opp and not (
                len(opp) >= 2 and (opp[:2] in other or other[:2] in opp)
            ):
                continue
            cands.append(d)
        if cands:
            cands.sort()
            out.at[idx, "date"] = pd.to_datetime(cands[0])
    return out.sort_values(["date", "round"]).reset_index(drop=True)


def fetch_guoan_2025_all(include_acl: bool = True) -> pd.DataFrame:
    """2025 国安全部赛程：中超 30 轮 + 可选亚冠（按日期排序，用于滚动战绩）。"""
    rows = []
    for rnd, opp, v, g, og, res in _GUOAN_2025_ALL:
        rows.append(
            {
                "round": int(rnd),
                "opponent": str(opp).strip(),
                "venue": str(v).strip().upper(),
                "guoan_goals": float(g),
                "opp_goals": float(og),
                "result": str(res).strip().upper(),
                "competition": "CSL",
            }
        )
    df = pd.DataFrame(rows)
    df = _merge_guoan_fixture_dates(df)
    df["round_tag"] = df["round"].astype(int).astype(str)

    if include_acl:
        acl_rows = []
        for tag, opp, v, g, og, res, date_str in _ACL_2025:
            acl_rows.append(
                {
                    "round": pd.NA,
                    "round_tag": str(tag),
                    "opponent": str(opp).strip(),
                    "venue": str(v).strip().upper(),
                    "guoan_goals": float(g),
                    "opp_goals": float(og),
                    "result": str(res).strip().upper(),
                    "date": pd.to_datetime(date_str),
                    "competition": "ACL",
                }
            )
        acl_df = pd.DataFrame(acl_rows)
        df = pd.concat([df, acl_df], ignore_index=True)

    if "date" in df.columns:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values("date").reset_index(drop=True)
    df["比分"] = df.apply(
        lambda r: f"{int(r['guoan_goals'])}-{int(r['opp_goals'])}", axis=1
    )
    res_zh = {"W": "胜", "D": "平", "L": "负"}
    df["赛果"] = df["result"].map(lambda x: res_zh.get(str(x).upper(), str(x)))
    return df


def fetch_guoan_2025_home() -> pd.DataFrame:
    """2025 国安中超主场（散票口径，不含亚冠主场）。"""
    df = fetch_guoan_2025_all(include_acl=True)
    home = df[(df["venue"] == "H") & (df["competition"] == "CSL")].copy()
    home = home.rename(columns={"round": "round_num"})
    return home.reset_index(drop=True)


def compute_home_form_2025(
    up_to_round: int | None = None,
    up_to_date: str | pd.Timestamp | None = None,
    include_acl: bool = True,
) -> float:
    """国安 2025 全赛事（默认含亚冠）总胜率。

    - ``up_to_date``：仅统计该日期 **之前** 的比赛。
    - ``up_to_round``：取该中超 **主场** 轮次开赛日作为截止日，再算此前全赛事胜率（与旧「赛前」语义对齐）。
    - 二者皆空：赛季至今全部场次。
    """
    df = fetch_guoan_2025_all(include_acl=include_acl)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])

    if up_to_date is not None:
        cutoff = pd.Timestamp(up_to_date)
        sub = df[df["date"] < cutoff]
    elif up_to_round is not None:
        csl_home = df[
            (df["competition"] == "CSL")
            & (df["venue"].astype(str).str.upper() == "H")
            & (df["round"].notna())
        ]
        csl_home = csl_home[csl_home["round"].astype(int) == int(up_to_round)]
        if csl_home.empty:
            return 0.5
        cutoff = pd.Timestamp(csl_home.iloc[0]["date"])
        sub = df[df["date"] < cutoff]
    else:
        sub = df

    if sub.empty:
        return 0.5
    wins = (sub["result"].astype(str).str.strip().str.upper() == "W").sum()
    return float(wins / len(sub))


def recent_form_before_match(target_date: str | pd.Timestamp, n: int = 5) -> float:
    """``target_date`` 之前最近 n 场全赛事（含亚冠）胜率。"""
    df = fetch_guoan_2025_all(include_acl=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    cutoff = pd.Timestamp(target_date)
    prev = df[df["date"] < cutoff].sort_values("date").tail(n)
    if prev.empty:
        return 0.5
    return float((prev["result"].astype(str).str.strip().str.upper() == "W").sum() / len(prev))


def lost_to_bottom_recently(target_date: str | pd.Timestamp) -> bool:
    """``target_date`` 之前最近 3 场是否曾输给 CSL 排名 ≥12 的对手（亚冠外援名无排名则不计）。"""
    df = fetch_guoan_2025_all(include_acl=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"])
    cutoff = pd.Timestamp(target_date)
    prev3 = df[df["date"] < cutoff].sort_values("date").tail(3)
    for _, m in prev3.iterrows():
        if str(m["result"]).strip().upper() != "L":
            continue
        opp = str(m["opponent"])
        if get_opponent_rank_2025(opp) >= 12:
            return True
    return False


def get_opponent_rank_2025(opponent: str) -> int:
    """2025 最终积分榜排名（队名模糊匹配）。"""
    o = (opponent or "").strip()
    if not o:
        return 8
    if "申花" in o:
        return _OPPONENT_RANK_2025["上海申花"]
    if "海港" in o:
        return _OPPONENT_RANK_2025["上海海港"]
    for name, rank in sorted(_OPPONENT_RANK_2025.items(), key=lambda x: -len(x[0])):
        if name in o or o in name:
            return rank
    for name, rank in _OPPONENT_RANK_2025.items():
        if len(o) >= 2 and (o[:2] in name or name[:2] in o):
            return rank
    return 8
