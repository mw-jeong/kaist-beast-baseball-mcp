"""SQLite 저장소 — 스냅샷 단위 적재 + DataFrame 조회.

설계: 컬럼이 종류마다 다르고 한국어라 wide 스키마 대신 (snapshot, kind, 식별자,
data=JSON) 형태로 저장. 조회 시 JSON을 펼쳐 pandas DataFrame으로 복원한다.
스냅샷마다 타임스탬프가 있어 시즌 중 기록 변화를 시계열로 추적할 수 있다.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from typing import Any

import pandas as pd

from .. import config

KINDS = ("batters", "pitchers", "team_rank", "team_offense", "team_defense", "games", "roster")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS snapshots (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                season     INTEGER,
                jo         TEXT,
                note       TEXT
            );
            CREATE TABLE IF NOT EXISTS records (
                snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                kind        TEXT NOT NULL,
                team        TEXT,
                name        TEXT,
                data        TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_records_lookup
                ON records(snapshot_id, kind);

            -- 박스스코어(경기 단위) — 스냅샷과 무관하게 game_idx로 멱등 저장
            CREATE TABLE IF NOT EXISTS bs_games (
                game_idx INTEGER PRIMARY KEY,
                date     TEXT,
                jo       TEXT,
                data     TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS bs_lines (
                game_idx INTEGER NOT NULL,
                kind     TEXT NOT NULL,   -- 'batting' | 'pitching'
                team     TEXT,
                name     TEXT,
                data     TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_bs_lines ON bs_lines(game_idx, kind);

            -- 라인업 저장(전력관리 write) — 대화로 짠 라인업을 휘발 없이 보관
            CREATE TABLE IF NOT EXISTS lineups (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                label      TEXT,
                opponent   TEXT,
                note       TEXT,
                body       TEXT NOT NULL
            );
            """
        )


# ── 라인업 저장/조회 ──────────────────────────────────────────────────
def save_lineup(body: str, *, label: str = "", opponent: str = "", note: str = "") -> int:
    """라인업(타순/수비/투수 등 자유 텍스트)을 저장. id 반환."""
    init_db()
    created = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO lineups (created_at, label, opponent, note, body) VALUES (?,?,?,?,?)",
            (created, label, opponent, note, body))
        return cur.lastrowid


def list_lineups(limit: int = 20) -> pd.DataFrame:
    init_db()
    with _conn() as c:
        rows = c.execute(
            "SELECT id, created_at, label, opponent, note, body FROM lineups "
            "ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


def _identity(kind: str, rec: dict) -> tuple[str | None, str | None]:
    team = rec.get("팀명") or rec.get("team1") or None
    name = rec.get("선수명") or None
    return team, name


def save_snapshot(data: dict[str, Any], *, note: str = "") -> int:
    """crawl() 결과 dict를 한 스냅샷으로 저장. snapshot_id 반환."""
    init_db()
    season = data.get("season", config.CURRENT_SEASON)
    jo = data.get("jo", config.OUR_JO)
    created = datetime.now().isoformat(timespec="seconds")
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO snapshots (created_at, season, jo, note) VALUES (?,?,?,?)",
            (created, season, jo, note),
        )
        sid = cur.lastrowid
        rows = []
        for kind in KINDS:
            for rec in data.get(kind, []):
                team, name = _identity(kind, rec)
                rows.append((sid, kind, team, name, json.dumps(rec, ensure_ascii=False)))
        c.executemany(
            "INSERT INTO records (snapshot_id, kind, team, name, data) VALUES (?,?,?,?,?)",
            rows,
        )
    return sid


def latest_snapshot_id(season: int | None = None, jo: str | None = None) -> int | None:
    q = "SELECT id FROM snapshots WHERE 1=1"
    args: list[Any] = []
    if season is not None:
        q += " AND season=?"; args.append(season)
    if jo is not None:
        q += " AND jo=?"; args.append(jo)
    q += " ORDER BY id DESC LIMIT 1"
    with _conn() as c:
        row = c.execute(q, args).fetchone()
    return row["id"] if row else None


def load(kind: str, *, snapshot_id: int | None = None,
         season: int | None = None, jo: str | None = None) -> pd.DataFrame:
    """한 종류(kind)의 기록을 DataFrame으로. snapshot 미지정 시 최신."""
    if snapshot_id is None:
        snapshot_id = latest_snapshot_id(season=season, jo=jo)
    if snapshot_id is None:
        return pd.DataFrame()
    with _conn() as c:
        rows = c.execute(
            "SELECT data FROM records WHERE snapshot_id=? AND kind=?",
            (snapshot_id, kind),
        ).fetchall()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([json.loads(r["data"]) for r in rows])


def list_snapshots() -> pd.DataFrame:
    with _conn() as c:
        rows = c.execute(
            "SELECT s.id, s.created_at, s.season, s.jo, s.note, COUNT(r.rowid) AS n_records "
            "FROM snapshots s LEFT JOIN records r ON r.snapshot_id=s.id "
            "GROUP BY s.id ORDER BY s.id DESC"
        ).fetchall()
    return pd.DataFrame([dict(r) for r in rows])


# ── 박스스코어(게임 로그) ─────────────────────────────────────────────
def stored_game_idxs() -> set[int]:
    init_db()
    with _conn() as c:
        return {r["game_idx"] for r in c.execute("SELECT game_idx FROM bs_games").fetchall()}


def save_boxscore(bs: dict, *, date: str | None = None, jo: str | None = None) -> None:
    """parse_boxscore 결과 1건을 멱등 저장(같은 game_idx면 교체)."""
    init_db()
    gid = bs.get("game_idx")
    if gid is None:
        return
    with _conn() as c:
        c.execute("INSERT OR REPLACE INTO bs_games (game_idx, date, jo, data) VALUES (?,?,?,?)",
                  (gid, date, jo, json.dumps({"teams": bs.get("teams"),
                                              "line_score": bs.get("line_score")}, ensure_ascii=False)))
        c.execute("DELETE FROM bs_lines WHERE game_idx=?", (gid,))
        rows = []
        for b in bs.get("batting", []):
            rows.append((gid, "batting", b.get("team"), b.get("선수명"),
                         json.dumps(b, ensure_ascii=False)))
        for p in bs.get("pitching", []):
            rows.append((gid, "pitching", p.get("team"), p.get("선수명"),
                         json.dumps(p, ensure_ascii=False)))
        c.executemany("INSERT INTO bs_lines (game_idx, kind, team, name, data) VALUES (?,?,?,?,?)", rows)


def load_game_lines(kind: str, *, team: str | None = None) -> pd.DataFrame:
    """박스스코어 타자/투수 라인 전체(또는 팀 필터) → DataFrame. date/jo 병합."""
    init_db()
    q = ("SELECT l.data, g.date, g.jo, l.game_idx FROM bs_lines l "
         "JOIN bs_games g ON g.game_idx=l.game_idx WHERE l.kind=?")
    args: list[Any] = [kind]
    if team is not None:
        q += " AND l.team=?"; args.append(team)
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    out = []
    for r in rows:
        rec = json.loads(r["data"])
        rec["_date"], rec["_jo"], rec["game_idx"] = r["date"], r["jo"], r["game_idx"]
        out.append(rec)
    return pd.DataFrame(out)


def boxscore_games() -> pd.DataFrame:
    init_db()
    with _conn() as c:
        rows = c.execute("SELECT game_idx, date, jo, data FROM bs_games ORDER BY game_idx").fetchall()
    out = []
    for r in rows:
        d = json.loads(r["data"])
        out.append({"game_idx": r["game_idx"], "date": r["date"], "jo": r["jo"],
                    "teams": d.get("teams"), "line_score": d.get("line_score")})
    return pd.DataFrame(out)


def history(kind: str, *, team: str | None = None, name: str | None = None,
            season: int | None = None, jo: str | None = None) -> pd.DataFrame:
    """특정 선수/팀의 스냅샷별 기록 변화(시계열)."""
    q = ("SELECT s.created_at, s.season, s.jo, r.data "
         "FROM records r JOIN snapshots s ON s.id=r.snapshot_id "
         "WHERE r.kind=?")
    args: list[Any] = [kind]
    if team is not None:
        q += " AND r.team=?"; args.append(team)
    if name is not None:
        q += " AND r.name=?"; args.append(name)
    if season is not None:
        q += " AND s.season=?"; args.append(season)
    if jo is not None:
        q += " AND s.jo=?"; args.append(jo)
    q += " ORDER BY s.id"
    with _conn() as c:
        rows = c.execute(q, args).fetchall()
    out = []
    for r in rows:
        rec = json.loads(r["data"])
        rec["_snapshot_at"] = r["created_at"]
        out.append(rec)
    return pd.DataFrame(out)
