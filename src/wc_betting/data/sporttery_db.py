"""
体彩赔率历史数据库 — SQLite 存储，支持反查和历史追踪。
"""

import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "sporttery_history.db"
CACHE_DIR = Path("/tmp/sporttery_cache")
TZ_SHANGHAI = timezone(timedelta(hours=8))
POOL_CODES = ["had", "hhad", "crs", "ttg"]


def _now_iso() -> str:
    return datetime.now(TZ_SHANGHAI).isoformat()


class SportteryDB:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _conn(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        conn = self._conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS snapshots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at  TEXT NOT NULL,
                pool_code   TEXT NOT NULL,
                match_date  TEXT NOT NULL,
                match_num   TEXT NOT NULL,
                match_id    INTEGER NOT NULL,
                home_cn     TEXT NOT NULL,
                away_cn     TEXT NOT NULL,
                match_time  TEXT,
                handicap    REAL,
                raw_json    TEXT NOT NULL,
                UNIQUE(fetched_at, pool_code, match_id)
            );
            CREATE INDEX IF NOT EXISTS idx_snap_match
                ON snapshots(match_date, home_cn, away_cn);
            CREATE INDEX IF NOT EXISTS idx_snap_pool
                ON snapshots(pool_code, fetched_at);
            CREATE TABLE IF NOT EXISTS odds_lines (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                selection    TEXT NOT NULL,
                odds         REAL NOT NULL,
                handicap     REAL
            );
            CREATE INDEX IF NOT EXISTS idx_odds_snapshot
                ON odds_lines(snapshot_id);
            CREATE INDEX IF NOT EXISTS idx_odds_selection
                ON odds_lines(selection, odds);
        """)
        conn.commit()
        conn.close()

    def import_from_cache(self, cache_dir=None):
        cache = Path(cache_dir) if cache_dir else CACHE_DIR
        total = 0
        for pool in POOL_CODES:
            fpath = cache / f"{pool}.json"
            if not fpath.exists():
                print(f"[sporttery_db] cache miss: {fpath}")
                continue
            data = json.loads(fpath.read_text(encoding="utf-8"))
            n = self.import_from_api_response(data, pool)
            total += n
            print(f"[sporttery_db] imported {pool}: {n} snapshots")
        return total

    def import_from_api_response(self, response, pool_code):
        if not response.get("success"):
            return 0
        value = response.get("value", {})
        match_list = value.get("matchInfoList", [])
        if not match_list:
            return 0
        fetched_at = _now_iso()
        snapshots_inserted = 0
        conn = self._conn()
        for date_entry in match_list:
            for m in date_entry.get("subMatchList", []):
                match_date = m.get("matchDate", "")
                match_id = m.get("matchId", 0)
                match_num = m.get("matchNumStr", "")
                home_cn = m.get("homeTeamAllName", "")
                away_cn = m.get("awayTeamAllName", "")
                match_time = m.get("matchTime", "")
                handicap = None
                if pool_code == "hhad":
                    od_list = m.get("oddsList", [])
                    if od_list:
                        gl = od_list[0].get("goalLine", "")
                        try:
                            handicap = float(gl)
                        except (ValueError, TypeError):
                            pass
                raw_json = json.dumps(m, ensure_ascii=False)
                try:
                    cur = conn.execute("""
                        INSERT OR IGNORE INTO snapshots
                            (fetched_at, pool_code, match_date, match_num, match_id,
                             home_cn, away_cn, match_time, handicap, raw_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (fetched_at, pool_code, match_date, match_num, match_id,
                          home_cn, away_cn, match_time, handicap, raw_json))
                    if cur.rowcount == 0:
                        continue
                    snapshot_id = cur.lastrowid
                    snapshots_inserted += 1
                except Exception:
                    continue
                lines = self._parse_odds(m, pool_code)
                for sel, odds_val, hcap in lines:
                    conn.execute("""
                        INSERT INTO odds_lines (snapshot_id, selection, odds, handicap)
                        VALUES (?, ?, ?, ?)
                    """, (snapshot_id, sel, odds_val, hcap))
        conn.commit()
        conn.close()
        return snapshots_inserted

    def _parse_odds(self, match, pool_code):
        results = []
        if pool_code == "had":
            od_list = match.get("oddsList", [])
            if od_list:
                o = od_list[0]
                for sel in ["h", "d", "a"]:
                    try:
                        results.append((sel.upper(), float(o.get(sel, 0)), None))
                    except (ValueError, TypeError):
                        pass
        elif pool_code == "hhad":
            od_list = match.get("oddsList", [])
            if od_list:
                o = od_list[0]
                gl_str = o.get("goalLine", "")
                try:
                    hcap = float(gl_str)
                except (ValueError, TypeError):
                    hcap = 0.0
                for sel in ["h", "d", "a"]:
                    try:
                        results.append((sel.upper(), float(o.get(sel, 0)), hcap))
                    except (ValueError, TypeError):
                        pass
        elif pool_code == "crs":
            crs_data = match.get("crs", {})
            for key, val in crs_data.items():
                if not key.startswith("s"):
                    continue
                try:
                    odds_val = float(val)
                except (ValueError, TypeError):
                    continue
                sel = _crs_key_to_label(key)
                if sel:
                    results.append((sel, odds_val, None))
        elif pool_code == "ttg":
            ttg_data = match.get("ttg", {})
            for key, val in ttg_data.items():
                if not key.startswith("s"):
                    continue
                try:
                    odds_val = float(val)
                except (ValueError, TypeError):
                    continue
                sel = _ttg_key_to_label(key)
                if sel:
                    results.append((sel, odds_val, None))
        return results


    def import_odds_rows(self, odds_rows: list[dict]) -> int:
        """Import from scanner odds_rows format (used by manual + auto paths).
        
        Each row has: home_cn, away_cn, home_en, away_en, date, group,
                      pool_code, handicap, odds: {option: price}
        """
        fetched_at = _now_iso()
        snapshots_inserted = 0
        conn = self._conn()
        # Reconstruct minimal match dict per row for _parse_odds compatibility
        for r in odds_rows:
            pool_code = r.get("pool_code", "")
            match_date = r.get("date", "")
            match_num = r.get("match_num", "")
            match_id = abs(hash(f"{r.get('home_en','')}_{r.get('away_en','')}_{pool_code}")) % (10**9)
            home_cn = r.get("home_cn", "")
            away_cn = r.get("away_cn", "")
            match_time = ""
            handicap = r.get("handicap")
            # Build minimal match dict for _parse_odds
            match = {"oddsList": [], "crs": {}, "ttg": {}}
            if pool_code == "had":
                match["oddsList"] = [{"h": str(r["odds"].get("H","")), 
                                       "d": str(r["odds"].get("D","")),
                                       "a": str(r["odds"].get("A",""))}]
            elif pool_code == "hhad":
                match["oddsList"] = [{"h": str(r["odds"].get("H","")),
                                       "d": str(r["odds"].get("D","")),
                                       "a": str(r["odds"].get("A","")),
                                       "goalLine": str(handicap or 0)}]
            elif pool_code == "crs":
                crs_data = {}
                for sel, price in r.get("odds", {}).items():
                    key = _label_to_crs_key(sel)
                    if key:
                        crs_data[key] = str(price)
                match["crs"] = crs_data
            elif pool_code == "ttg":
                ttg_data = {}
                for sel, price in r.get("odds", {}).items():
                    key = _label_to_ttg_key(sel)
                    if key:
                        ttg_data[key] = str(price)
                match["ttg"] = ttg_data
            raw_json = json.dumps(match, ensure_ascii=False)
            try:
                cur = conn.execute("""
                    INSERT OR IGNORE INTO snapshots
                        (fetched_at, pool_code, match_date, match_num, match_id,
                         home_cn, away_cn, match_time, handicap, raw_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (fetched_at, pool_code, match_date, match_num, match_id,
                      home_cn, away_cn, match_time, handicap, raw_json))
                if cur.rowcount == 0:
                    continue
                snapshot_id = cur.lastrowid
                snapshots_inserted += 1
            except Exception:
                continue
            lines = self._parse_odds(match, pool_code)
            for sel, odds_val, hcap in lines:
                conn.execute("""
                    INSERT INTO odds_lines (snapshot_id, selection, odds, handicap)
                    VALUES (?, ?, ?, ?)
                """, (snapshot_id, sel, odds_val, hcap))
        conn.commit()
        conn.close()
        return snapshots_inserted

    def query(self, match_date=None, home_cn=None, away_cn=None,
              pool_code=None, selection=None, limit=100):
        sql = """
            SELECT s.fetched_at, s.pool_code, s.match_date, s.match_num,
                   s.home_cn, s.away_cn, s.handicap,
                   ol.selection, ol.odds
            FROM snapshots s
            JOIN odds_lines ol ON ol.snapshot_id = s.id
            WHERE 1=1
        """
        params = []
        if match_date:
            sql += " AND s.match_date = ?"; params.append(match_date)
        if home_cn:
            sql += " AND s.home_cn LIKE ?"; params.append(f"%{home_cn}%")
        if away_cn:
            sql += " AND s.away_cn LIKE ?"; params.append(f"%{away_cn}%")
        if pool_code:
            sql += " AND s.pool_code = ?"; params.append(pool_code)
        if selection:
            sql += " AND ol.selection = ?"; params.append(selection)
        sql += " ORDER BY s.fetched_at DESC, s.match_date, ol.selection"
        sql += f" LIMIT {int(limit)}"
        conn = self._conn()
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def query_match_history(self, home_cn, away_cn, pool_code=None):
        return self.query(home_cn=home_cn, away_cn=away_cn,
                          pool_code=pool_code, limit=500)

    def latest_snapshot_date(self):
        conn = self._conn()
        row = conn.execute("SELECT MAX(fetched_at) FROM snapshots").fetchone()
        conn.close()
        return row[0] if row else None

    def stats(self):
        conn = self._conn()
        snap_count = conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0]
        line_count = conn.execute("SELECT COUNT(*) FROM odds_lines").fetchone()[0]
        pools = conn.execute(
            "SELECT pool_code, COUNT(*) FROM snapshots GROUP BY pool_code").fetchall()
        dates = conn.execute(
            "SELECT match_date, COUNT(DISTINCT match_id) FROM snapshots "
            "GROUP BY match_date ORDER BY match_date").fetchall()
        conn.close()
        return {
            "snapshots": snap_count,
            "odds_lines": line_count,
            "by_pool": {r[0]: r[1] for r in pools},
            "by_date": {r[0]: r[1] for r in dates},
        }


def _crs_key_to_label(key):
    if key in ("s1sh", "s1sd", "s1sa"):
        return {"s1sh": "OTHER_H", "s1sd": "OTHER_D", "s1sa": "OTHER_A"}[key]
    if key.startswith("s") and "s" in key[1:]:
        parts = key[1:].split("s")
        if len(parts) == 2:
            try:
                return f"{int(parts[0])}:{int(parts[1])}"
            except ValueError:
                pass
    return None


def _ttg_key_to_label(key):
    if key == "s7":
        return "7+"
    if key.startswith("s") and len(key) >= 2:
        try:
            return str(int(key[1:]))
        except ValueError:
            pass
    return None




def _label_to_crs_key(label: str) -> str | None:
    '''"1:0" -> "s01s00", "OTHER_H" -> "s1sh"'''
    if label in ("OTHER_H", "OTHER_D", "OTHER_A"):
        return {"OTHER_H": "s1sh", "OTHER_D": "s1sd", "OTHER_A": "s1sa"}[label]
    parts = label.split(":")
    if len(parts) == 2:
        try:
            return f"s{int(parts[0]):02d}s{int(parts[1]):02d}"
        except ValueError:
            pass
    return None


def _label_to_ttg_key(label: str) -> str | None:
    '''"7+" -> "s7", "3" -> "s3"'''
    if label == "7+":
        return "s7"
    try:
        return f"s{int(label)}"
    except ValueError:
        return None


if __name__ == "__main__":
    import sys
    db = SportteryDB()
    if len(sys.argv) > 1 and sys.argv[1] == "import":
        n = db.import_from_cache()
        print(f"Total: {n}")
    elif len(sys.argv) > 1 and sys.argv[1] == "stats":
        import json as _json
        print(_json.dumps(db.stats(), indent=2, ensure_ascii=False))
    elif len(sys.argv) > 1 and sys.argv[1] == "query":
        date = sys.argv[2] if len(sys.argv) > 2 else None
        pool = sys.argv[3] if len(sys.argv) > 3 else None
        for row in db.query(match_date=date, pool_code=pool):
            print(f"  {row['match_date']} {row['match_num']} {row['home_cn']} vs {row['away_cn']} | {row['pool_code']}/{row['selection']} @ {row['odds']}")
    else:
        print(f"DB: {db.db_path}")
        print(f"Stats: {db.stats()}")
