#!/usr/bin/env python3
"""CSL 数据同步 — 全管线编排 (Hermes 维护, Reasonix/Claude Code 不要改 ELO/standings)。

数据源 (双源合并):
  - MCP 历史: data/processed/mcp_history_full.json (2023-25 已赛, source='mcp_history')
  - CFL 实时: csl_project_v2/data/csl_final_production_ready.json
             (当季, source='cfl_fixtures_api', 每日 02:00 由 football-data/csl-dashboard-2026 爬虫产出)

产出:
  - elo_history.parquet              全量重算 (2023→最新)
  - standings_2026_by_round.parquet  当季逐轮排名
  - 动态分级: 每轮结束后自动重算 (cron 每天 03:15 兜底 + ingest_match 整轮完成实时触发, 2026-08-05)
  - rating_snapshot_YYYYMMDD.json    对手评分快照
  - data/processed/sync_csl_data_log.json  执行日志 (最近 30 条)

幂等: 重复执行无副作用, 写盘前自动备份 (保留 5 个)。

用法:
  python scripts/sync_csl_data.py [--dry-run] [--date 2026-07-08] [--skip-standings] [--skip-snapshot]

⚠️ Reasonix / Claude Code: 不要手动改 elo_history.parquet 和 standings_2026_by_round.parquet。
   数据更新统一走本脚本。CI 由 cron 每日 03:15 触发。
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── 路径 ────────────────────────────────────────────────────────
MCP_HISTORY = ROOT / "data/processed/mcp_history_full.json"
LOCAL_CSL_JSON = Path(
    "/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2/data/csl_final_production_ready.json"
)
CSL_DEDUCTIONS = Path(
    "/mnt/c/Users/xxxsu/.openclaw/workspace/csl_project_v2/config/csl_cfa_2026_official_deductions.json"
)
ELO_PATH = ROOT / "data/processed/elo_history.parquet"
STANDINGS_2026 = ROOT / "data/processed/standings_2026_by_round.parquet"
SNAPSHOT_DIR = ROOT / "data/processed"
SYNC_LOG = ROOT / "data/processed/sync_csl_data_log.json"

TZ_CN = timezone(timedelta(hours=8))


def _now() -> datetime:
    return datetime.now(TZ_CN)


def _ts_compact() -> str:
    return _now().strftime("%Y%m%d_%H%M%S")


def _ts_iso() -> str:
    return _now().isoformat(timespec="seconds")


def _log(level: str, msg: str) -> None:
    print(f"[{level}] {msg}", flush=True)


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    ts = _ts_compact()
    bk = path.with_suffix(path.suffix + f".bak_{ts}")
    shutil.copy2(path, bk)
    # 保留最近 5 个 backup
    import glob
    pattern = str(path.parent / f"{path.name}.bak_*")
    old = sorted(glob.glob(pattern))[:-5]
    for o in old:
        Path(o).unlink(missing_ok=True)
    return bk


# ── Step 1: 加载双源 → unified matches ────────────────────────────


def load_unified_matches() -> list[dict]:
    """合并 MCP 历史 + CFL 当季已赛, 返回统一格式的 matches list。

    每条: {date, round, home, away, hg, ag, completed, source}
    冲突规则: (date, home, away) 相同则优先 MCP (历史回填更稳)。
    """
    from src.csl_context import _normalize_club_name

    matches: list[dict] = []

    # ── MCP 历史 (2023-25) ──
    if MCP_HISTORY.exists():
        mcp = json.load(open(MCP_HISTORY))
        for m in mcp:
            hg, ag = m.get("hg"), m.get("ag")
            matches.append({
                "date": m["date"][:10],
                "round": f"MCP-{m['date'][:4]}",
                "home": _normalize_club_name(m["home"]),
                "away": _normalize_club_name(m["away"]),
                "hg": hg, "ag": ag,
                "completed": hg is not None and ag is not None,
                "source": "mcp_history",
            })
        _log("OK", f"MCP 历史: {len(mcp)} 条 "
               f"(年份: {sorted({x['date'][:4] for x in mcp})})")
    else:
        _log("WARN", f"MCP 历史文件不存在: {MCP_HISTORY}")

    # ── CFL 当季已赛 (2026 实时) ──
    if not LOCAL_CSL_JSON.exists():
        _log("WARN", f"CFL JSON 不存在: {LOCAL_CSL_JSON} (跳过 2026 数据)")
    else:
        try:
            data = json.load(open(LOCAL_CSL_JSON))
        except json.JSONDecodeError as e:
            _log("ERROR", f"CFL JSON 解析失败: {e}")
            data = {}
        added = 0
        for lg in data.get("leagues", []):
            if "中超" not in lg.get("name", ""):
                continue
            for m in lg.get("matches", []):
                s = m.get("score", {}) or {}
                hg = s.get("home") if isinstance(s, dict) else None
                ag = s.get("away") if isinstance(s, dict) else None
                # 有比分即视为已赛（CFL 源偶有 status 仍为 scheduled 但已带比分）
                if hg is None or ag is None:
                    continue
                matches.append({
                    "date": m["date"][:10],
                    "round": m.get("round", ""),
                    "home": _normalize_club_name(m["home_club"]),
                    "away": _normalize_club_name(m["away_club"]),
                    "hg": int(hg), "ag": int(ag),
                    "completed": True,
                    "source": m.get("source", "cfl_fixtures_api") or "cfl_fixtures_api",
                })
                added += 1
        _log("OK", f"CFL 当季: 新增 {added} 条已赛")

    # ── 去重 ──
    by_combo = {}
    def _better(new_m, cur_m):
        """版本优先级: MCP 历史 > round 完整(第N轮) > 其余"""
        if new_m["source"] == "mcp_history" and cur_m["source"] != "mcp_history":
            return True
        if new_m["source"] != "mcp_history" and cur_m["source"] == "mcp_history":
            return False
        new_r = str(new_m.get("round", "")).startswith("第")
        cur_r = str(cur_m.get("round", "")).startswith("第")
        if new_r and not cur_r:
            return True
        return False

    for m in matches:
        key = (m["date"], m["home"], m["away"])
        cur = by_combo.get(key)
        if cur is None:
            by_combo[key] = m
        elif _better(m, cur):
            by_combo[key] = m
    dedup = sorted(by_combo.values(), key=lambda x: (x["date"], x["home"]))
    _log("OK", f"去重: {len(matches)} → {len(dedup)} (按 (date,home,away) MCP>完整round 优先)")
    return dedup


# ── Step 2: 全量重算 ELO ────────────────────────────────────────


def rebuild_elo(matches: list[dict]):
    import pandas as pd
    from src.opponent_rating import compute_elo_history

    elo = compute_elo_history(matches)
    if elo.empty:
        raise RuntimeError("compute_elo_history 返回空")
    _log("OK", f"ELO 重算: {len(elo)} 行, {elo['team'].nunique()} 队, "
           f"{elo['date'].min().date()} → {elo['date'].max().date()}")
    return elo


# ── Step 3: 重算 2026 逐轮 standings ──────────────────────────────


def _round_key(rnd: str) -> int:
    """'第7轮' → 7"""
    return int(rnd.replace("第", "").replace("轮", "")) if rnd.startswith("第") else 0


def rebuild_standings(matches: list[dict]):
    """逐轮 standings DataFrame (列: round, date, team, rank, points, match_points,
    deduction, played, goals_for, goals_against, goal_diff)。

    算法: 按 round 累计积分和进球, 用 deductions 扣分后排序。
    """
    import pandas as pd

    if CSL_DEDUCTIONS.exists():
        deductions = json.load(open(CSL_DEDUCTIONS)).get("deductions_by_club", {})
    else:
        _log("WARN", f"扣分表不存在: {CSL_DEDUCTIONS}, 用 0")
        deductions = {}

    # 当季 2026 已赛
    games = [
        m for m in matches
        if m["completed"] and m["date"].startswith("2026") and m.get("hg") is not None
    ]
    # 按 round 分桶
    buckets: dict[str, list[dict]] = {}
    dropped_round_empty = 0
    for m in games:
        rnd = m.get("round", "")
        if not rnd.startswith("第"):
            dropped_round_empty += 1
            continue
        buckets.setdefault(rnd, []).append(m)

    if dropped_round_empty:
        _log("WARN", f"CFL {len(games)} 场中 {dropped_round_empty} 场 round 为空被丢弃 "
                      "(若为前几轮重复记录属正常, 若为完赛场次则数据源异常)")

    if not buckets:
        _log("WARN", "无 2026 已赛数据, standings 跳过")
        return pd.DataFrame()

    rounds_sorted = sorted(buckets.keys(), key=_round_key)
    cum_pts = Counter()        # 扣分后
    cum_match_pts = Counter()  # 扣分前
    cum_gf = Counter()
    cum_ga = Counter()
    played = Counter()
    rows = []

    for rnd in rounds_sorted:
        for m in buckets[rnd]:
            h, a = m["home"], m["away"]
            cum_match_pts[h] += 3 if m["hg"] > m["ag"] else (1 if m["hg"] == m["ag"] else 0)
            cum_match_pts[a] += 3 if m["ag"] > m["hg"] else (1 if m["hg"] == m["ag"] else 0)
            cum_gf[h] += m["hg"]; cum_ga[h] += m["ag"]
            cum_gf[a] += m["ag"]; cum_ga[a] += m["hg"]
        # 应用扣分
        for team in list(cum_match_pts):
            cum_pts[team] = cum_match_pts[team] - deductions.get(team, 0)
        # 累计 played (每个 round 算 1 场)
        this_round_teams = set()
        for m in buckets[rnd]:
            this_round_teams.add(m["home"])
            this_round_teams.add(m["away"])
        for t in this_round_teams:
            played[t] += 1
        # ranking
        rank_data = []
        all_teams = set(cum_pts) | this_round_teams
        for t in all_teams:
            pts = cum_pts.get(t, 0) - deductions.get(t, 0)
            rank_data.append({
                "team": t,
                "points": cum_match_pts.get(t, 0) - deductions.get(t, 0),
                "match_points": cum_match_pts.get(t, 0),
                "deduction": deductions.get(t, 0),
                "played": played.get(t, 0),
                "goals_for": cum_gf.get(t, 0),
                "goals_against": cum_ga.get(t, 0),
                "goal_diff": cum_gf.get(t, 0) - cum_ga.get(t, 0),
            })
        # 按 points desc, gd desc, gf desc
        rank_data.sort(key=lambda r: (-r["points"], -r["goal_diff"], -r["goals_for"]))
        last_date = max(m["date"] for m in buckets[rnd])
        for i, r in enumerate(rank_data):
            rows.append({
                "round": rnd,
                "date": last_date,
                "team": r["team"],
                "rank": i + 1,
                "points": r["points"],
                "match_points": r["match_points"],
                "deduction": r["deduction"],
                "played": r["played"],
                "goals_for": r["goals_for"],
                "goals_against": r["goals_against"],
                "goal_diff": r["goal_diff"],
            })

    df = pd.DataFrame(rows)
    _log("OK", f"standings 重算: {len(df)} 行, "
           f"{df['round'].nunique()} 轮, 最新 {df['date'].max()}")

    # ── 完整性校验（防静默数据丢失, 2026-08-05 加入）────────────────
    issues = _validate_standings(df, buckets)
    if issues:
        _log("ERROR", "standings 完整性校验失败: " + " | ".join(issues))
    else:
        _log("OK", "standings 完整性校验通过")
    return df


# ── 防线2: 独立校验脚本可复用的核心 ──────────────────────────────
def _validate_standings(df, buckets=None):
    """返回问题列表(空=通过)。检查: 每轮场次、round 空残留、played 单调性。
    buckets 可选——由 rebuild_standings 内部传入已分桶比赛; 外部调用时用 None 跳过场次检查。"""
    import re
    issues = []

    # 1) 每轮比赛场次: 16队单循环 → 每轮最多 8 场（延期会少于8, 不算错）
    if buckets is not None:
        for rnd, games in buckets.items():
            n = len(games)
            if n > 8:
                issues.append(f"{rnd} 场次={n} (>8 异常)")

    # 2) round 空残留: 已赛比赛必须都有完整 round
    if buckets is not None:
        empty = [g for g in buckets if not str(g).startswith("第")]
        if empty:
            issues.append(f"round 空残留 {len(empty)} 轮")

    # 3) played 单调性: 每队逐轮 played 必须 +0/+1（跳轮=漏场）
    if not df.empty:
        teams = df["team"].unique()
        for t in teams:
            sub = df[df["team"] == t].sort_values(
                "round", key=lambda s: s.map(lambda r: int(re.search(r"(\d+)", r).group(1)) if re.search(r"(\d+)", r) else 0)
            )
            prev = 0
            for _, r in sub.iterrows():
                if r["played"] < prev:
                    issues.append(f"{t} {r['round']} played 回退 {prev}→{r['played']}")
                if r["played"] > prev + 1:
                    issues.append(f"{t} {r['round']} played 跳变 +{r['played']-prev} (漏场?)")
                prev = r["played"]

    # 4) 最新轮次覆盖队数: 正常16队, 延期轮可少, 但<12 说明大面积缺失
    if not df.empty:
        last_rnd = df["round"].iloc[-1]  # 已按轮排序插入
        n_last = (df["round"] == last_rnd).sum()
        if n_last > 16:
            issues.append(f"最新轮 {last_rnd} 有 {n_last} 队 (>16 异常)")
        if 0 < n_last < 12:
            issues.append(f"最新轮 {last_rnd} 只有 {n_last} 队 (<12, 疑似大面积缺失)")

    return issues


# ── Step 4: 写 snapshot ────────────────────────────────────────


def rebuild_snapshot(matches: list[dict], elo, standings, snapshot_date: str) -> str:
    import pandas as pd
    from src.opponent_rating import build_snapshot as _build_snapshot

    # standings_by_round 期望 dict[round, dict[team, rank]]
    if isinstance(standings, pd.DataFrame) and not standings.empty:
        sbr = {
            rnd: dict(zip(g["team"].tolist(), g["rank"].tolist()))
            for rnd, g in standings.groupby("round")
        }
    else:
        sbr = {}

    cards = _build_snapshot(
        date_str=snapshot_date,
        elo_history=elo,
        matches=matches,
        standings_by_round=sbr,
    )
    clean_date = snapshot_date.replace("-", "")
    snap_path = SNAPSHOT_DIR / f"rating_snapshot_{clean_date}.json"
    with open(snap_path, "w", encoding="utf-8") as f:
        json.dump({"as_of": snapshot_date, "cards": cards}, f,
                  ensure_ascii=False, indent=2)
    _log("OK", f"snapshot 写出: {snap_path} ({len(cards)} 队)")
    return str(snap_path)


# ── Step 5: 写执行日志 ──────────────────────────────────────────


def write_sync_log(entry: dict) -> None:
    SYNC_LOG.parent.mkdir(parents=True, exist_ok=True)
    log: list = []
    if SYNC_LOG.exists():
        try:
            log = json.load(open(SYNC_LOG))
        except Exception:
            log = []
    log.append(entry)
    log = log[-30:]
    with open(SYNC_LOG, "w", encoding="utf-8") as f:
        json.dump(log, f, ensure_ascii=False, indent=2)


# ── main ──────────────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="CSL 数据同步管线 (Hermes 维护)")
    ap.add_argument("--dry-run", action="store_true", help="只打印不写文件")
    ap.add_argument("--date", help="snapshot 日期 (默认今天, 格式 YYYY-MM-DD)")
    ap.add_argument("--skip-standings", action="store_true", help="跳过 standings 重算")
    ap.add_argument("--skip-snapshot", action="store_true", help="跳过 snapshot")
    args = ap.parse_args()

    snapshot_date = args.date or _now().strftime("%Y-%m-%d")
    _log("INFO", f"=== sync_csl_data.py start @ {_ts_iso()} ===")
    _log("INFO", f"snapshot_date={snapshot_date}, dry_run={args.dry_run}")

    entry: dict = {
        "ts": _ts_iso(),
        "snapshot_date": snapshot_date,
        "dry_run": args.dry_run,
        "steps": {},
    }

    try:
        # Step 1: unified matches
        matches = load_unified_matches()
        entry["steps"]["load"] = {
            "total": len(matches),
            "by_source": dict(Counter(m["source"] for m in matches)),
            "years": sorted({m["date"][:4] for m in matches}),
            "teams": len({m["home"] for m in matches} | {m["away"] for m in matches}),
        }
        if not matches:
            raise RuntimeError("无任何比赛数据 (MCP 和 CFL 都空)")

        # Step 2: ELO 全量重算
        elo = rebuild_elo(matches)
        entry["steps"]["elo"] = {
            "rows": len(elo),
            "teams": int(elo["team"].nunique()),
            "min_date": str(elo["date"].min().date()),
            "max_date": str(elo["date"].max().date()),
        }
        if not args.dry_run:
            _backup(ELO_PATH)
            elo.to_parquet(ELO_PATH)
            _log("OK", f"ELO 写盘: {ELO_PATH}")

        # Step 3: standings
        if not args.skip_standings:
            standings = rebuild_standings(matches)
            # ── 写盘前阻断式校验: 数据不完整则拒绝写盘 (2026-08-05) ──
            issues = _validate_standings(standings)  # 外部调用无 buckets, 跳过程次检查
            if issues and not args.dry_run:
                raise RuntimeError(
                    "standings 校验失败, 拒绝写盘: " + " | ".join(issues)
                )
            entry["steps"]["standings"] = {
                "rows": len(standings),
                "rounds": int(standings["round"].nunique()) if not standings.empty else 0,
                "max_date": str(standings["date"].max()) if not standings.empty else None,
                "issues": issues,
            }
            if not args.dry_run and not standings.empty:
                _backup(STANDINGS_2026)
                standings.to_parquet(STANDINGS_2026)
                _log("OK", f"standings 写盘: {STANDINGS_2026}")
        else:
            standings = None

        # Step 4: snapshot
        if not args.skip_snapshot:
            if standings is None:
                import pandas as pd
                standings = pd.read_parquet(STANDINGS_2026) if STANDINGS_2026.exists() else pd.DataFrame()
            snap_path = rebuild_snapshot(matches, elo, standings, snapshot_date)
            entry["steps"]["snapshot"] = snap_path
            if args.dry_run:
                Path(snap_path).unlink(missing_ok=True)

        entry["status"] = "ok"
        _log("INFO", "=== 同步成功 ===")

        # ── 防线3: CFL 源质量 + standings 自洽复核 (2026-08-05) ──
        if not args.dry_run:
            try:
                import subprocess
                r = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/verify_standings.py")],
                    capture_output=True, text=True, timeout=60,
                )
                if r.returncode == 0:
                    _log("OK", "verify_standings 通过")
                else:
                    _log("WARN", "verify_standings 发现问题: " + r.stdout[-1500:])
            except Exception as ve:
                _log("WARN", f"verify_standings 执行失败: {ve!r}")
    except Exception as e:
        entry["status"] = "error"
        entry["error"] = repr(e)
        _log("ERROR", f"失败: {e!r}")
        if not args.dry_run:
            write_sync_log(entry)
        raise

    if not args.dry_run:
        write_sync_log(entry)


if __name__ == "__main__":
    main()
