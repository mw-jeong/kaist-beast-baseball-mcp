"""HTML 파싱 — 게임원 content 페이지 → 구조화 데이터.

실제 인증 HTML 구조 기준으로 작성. 컬럼명은 한국어 그대로 보존하되(사용자·Claude
친화적), 이름/번호/팀/조 같은 파생 필드를 더하고 숫자는 형변환한다.

핵심 메모:
- 기록/랭킹은 group_code(=bucode 25)로 조를 못 가른다. 세션 favorite(bujo_idx)로
  조가 정해진다 → session.set_bujo(B조) 후 수집한 HTML이어야 B조 데이터.
- batter/pitcher 페이지는 <table> 2개(규정타석 충족/미달)로 나뉜다 → 병합.
"""
from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup


# ── 공통 유틸 ─────────────────────────────────────────────────────────
def _clean(text: str) -> str:
    return " ".join(text.split()).strip()


def _num(s: str) -> Any:
    """숫자 문자열 → int/float, 아니면 원본 문자열."""
    s = s.strip()
    if not s or s in ("-", "."):
        return s
    # 0.875 / 1.000 / .500 같은 비율
    if re.fullmatch(r"-?\d+", s):
        try:
            return int(s)
        except ValueError:
            return s
    if re.fullmatch(r"-?\d*\.\d+", s):
        try:
            return float(s)
        except ValueError:
            return s
    return s


_NAME_RE = re.compile(r"^(.+?)\s*\((\d*)\)\s*(.*)$")


def _split_name(s: str) -> tuple[str, int | None, str]:
    """이름/등번호/포지션 분리.

    '김한슬(7)' → (김한슬, 7, '')
    '구전서 (27) 코치 포수' → (구전서, 27, '코치 포수')
    '김도현 () 미지정' → (김도현, None, '미지정')  # 타팀은 등번호 비공개
    """
    s = _clean(s)
    m = _NAME_RE.match(s)
    if not m:
        return s, None, ""
    name = m.group(1).strip()
    num = int(m.group(2)) if m.group(2) else None
    rest = m.group(3).strip()
    return name, num, rest


def extract_tables(html: str, min_rows: int = 1) -> list[dict[str, Any]]:
    """문서 내 모든 <table>을 범용 추출 (헤더 + 행). 디버깅/탐색용."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    for ti, table in enumerate(soup.find_all("table")):
        headers: list[str] = []
        thead = table.find("thead")
        if thead:
            headers = [_clean(th.get_text()) for th in thead.find_all(["th", "td"])]
        body = table.find("tbody") or table
        rows: list[list[str]] = []
        for tr in body.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells:
                continue
            if not headers and all(c.name == "th" for c in cells):
                headers = [_clean(c.get_text()) for c in cells]
                continue
            rows.append([_clean(c.get_text()) for c in cells])
        rows = [r for r in rows if any(r)]
        if len(rows) < min_rows and not headers:
            continue
        out.append({"index": ti, "headers": headers, "rows": rows,
                    "n_rows": len(rows), "n_cols": max((len(r) for r in rows), default=len(headers))})
    return out


def _rows_as_dicts(html: str) -> list[tuple[list[str], list[list[str]]]]:
    """각 테이블을 (headers, rows)로 반환."""
    return [(t["headers"], t["rows"]) for t in extract_tables(html)]


# ── 개인 기록 (타자/투수) ─────────────────────────────────────────────
def _parse_player_records(html: str, jo: str | None, *,
                          name_col: str = "이름") -> list[dict[str, Any]]:
    """batter/pitcher 공통: 모든 테이블 병합, 이름/번호 분리, 숫자 형변환."""
    records: list[dict[str, Any]] = []
    for headers, rows in _rows_as_dicts(html):
        if name_col not in headers:
            continue
        qualified = (len(records) == 0)  # 첫 테이블=규정타석 충족
        ni = headers.index(name_col)
        for row in rows:
            if len(row) != len(headers):
                continue
            rec: dict[str, Any] = {}
            for h, v in zip(headers, row):
                rec[h] = _num(v)
            name, num, _ = _split_name(row[ni])
            rec["선수명"] = name
            rec["등번호"] = num
            rec["조"] = jo
            rec["규정"] = qualified
            rec.pop("랭킹", None)  # 조별 랭킹은 재계산 가능 — 제거
            records.append(rec)
    return records


def parse_batters(html: str, jo: str | None = None) -> list[dict[str, Any]]:
    return _parse_player_records(html, jo)


def parse_pitchers(html: str, jo: str | None = None) -> list[dict[str, Any]]:
    return _parse_player_records(html, jo)


def team_club_map(html: str) -> dict[str, int]:
    """content 페이지의 club_idx 링크에서 {팀명: club_idx} 추출.

    랭킹/공격/수비/타자/투수 페이지의 팀명 셀은 club_idx 링크를 가진다.
    선수명은 club_idx로 링크되지 않으므로 팀명만 안전하게 잡힌다.
    """
    soup = BeautifulSoup(html, "lxml")
    out: dict[str, int] = {}
    for a in soup.find_all("a", href=re.compile(r"club_idx=\d+")):
        m = re.search(r"club_idx=(\d+)", a["href"])
        name = _clean(a.get_text())
        if m and name and name not in out:
            out[name] = int(m.group(1))
    return out


# ── 팀 랭킹 / 공격 / 수비 ─────────────────────────────────────────────
def _parse_team_table(html: str, jo: str | None, key_col: str = "팀명") -> list[dict[str, Any]]:
    club_map = team_club_map(html)
    out: list[dict[str, Any]] = []
    for headers, rows in _rows_as_dicts(html):
        if key_col not in headers:
            continue
        for row in rows:
            if len(row) != len(headers):
                continue
            rec = {h: _num(v) for h, v in zip(headers, row)}
            rec["조"] = jo
            rec["club_idx"] = club_map.get(rec.get(key_col))
            out.append(rec)
        break  # 팀 표는 보통 1개
    return out


def parse_team_rank(html: str, jo: str | None = None) -> list[dict[str, Any]]:
    return _parse_team_table(html, jo)


def parse_team_offense(html: str, jo: str | None = None) -> list[dict[str, Any]]:
    return _parse_team_table(html, jo)


def parse_team_defense(html: str, jo: str | None = None) -> list[dict[str, Any]]:
    return _parse_team_table(html, jo)


# ── 일정 / 결과 ───────────────────────────────────────────────────────
_GAME_RE = re.compile(r"^(.+?)\s+(\d+)\s+(.+?)\s+(\d+)$")
_GAMEIDX_RE = re.compile(r"game_idx=(\d+)")


def parse_schedule(html: str) -> list[dict[str, Any]]:
    """일정/결과 표 → 경기 리스트. '게임' 칼럼의 'A 13 B 7'을 팀/점수로 분해하고,
    결과(BOX SCORE) 링크에서 game_idx를 추출한다(박스스코어 수집의 키)."""
    soup = BeautifulSoup(html, "lxml")
    out: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        # 헤더: thead 우선, 없으면 첫 all-th 행
        headers: list[str] = []
        thead = table.find("thead")
        if thead:
            headers = [_clean(th.get_text()) for th in thead.find_all(["th", "td"])]
        if not headers:
            for tr in table.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if cells and all(c.name == "th" for c in cells):
                    headers = [_clean(c.get_text()) for c in cells]
                    break
        if "게임" not in headers:
            continue
        gi = headers.index("게임")
        body = table.find("tbody") or table
        for tr in body.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if not cells or len(cells) != len(headers) or all(c.name == "th" for c in cells):
                continue
            vals = [_clean(c.get_text()) for c in cells]
            rec = dict(zip(headers, vals))
            # game_idx: 행 안의 boxscore 링크에서
            link = tr.find("a", href=_GAMEIDX_RE)
            if link:
                rec["game_idx"] = int(_GAMEIDX_RE.search(link["href"]).group(1))
            m = _GAME_RE.match(vals[gi])
            if m:
                t1, s1, t2, s2 = m.group(1).strip(), int(m.group(2)), m.group(3).strip(), int(m.group(4))
                rec["team1"], rec["score1"], rec["team2"], rec["score2"] = t1, s1, t2, s2
                rec["played"] = True
                if s1 != s2:
                    rec["winner"], rec["loser"] = (t1, t2) if s1 > s2 else (t2, t1)
                else:
                    rec["winner"] = rec["loser"] = None
            else:
                rec["played"] = False
            out.append(rec)
    return out


# ── 박스스코어 (경기 단위 로그) ───────────────────────────────────────
_BAT_CELL_RE = re.compile(r"^(\d+)\s+(\S+)\s+(.+?)\((\d*)\)\s*$")


def _is_lineup_table(h: list[str]) -> bool:
    return h[:1] == ["선수"] and "도루" in h and "시즌" in h


def _is_pitch_table(h: list[str]) -> bool:
    return h[:1] == ["선수"] and "자책점" in h


def parse_boxscore(html: str, game_idx: int | None = None) -> dict[str, Any]:
    """단일 경기 박스스코어 → {teams, line_score, batting[], pitching[]}.

    batting: 타순·포지션·이름·번호 + 타석별 결과(pa) + 당경기 타수/안타/타점/득점/도루.
    pitching: 선발여부·결과·이닝·타자·피안타·볼넷·삼진·실점·자책 등 (투구수는 보통 0/미기록).
    팀 매핑은 라인스코어 순서(테이블0) 기준.
    """
    tables = extract_tables(html, min_rows=1)
    line = next((t for t in tables if t["headers"][:1] == ["Team"]), None)
    teams = [r[0] for r in line["rows"]] if line else []

    out: dict[str, Any] = {"game_idx": game_idx, "teams": teams,
                           "line_score": [], "batting": [], "pitching": []}
    if line:
        for r in line["rows"]:
            d = dict(zip(line["headers"], r))
            out["line_score"].append({"team": d.get("Team"),
                                      "R": _num(d.get("R", "")), "H": _num(d.get("H", "")),
                                      "E": _num(d.get("E", ""))})

    bat_tables = [t for t in tables if _is_lineup_table(t["headers"])]
    pit_tables = [t for t in tables if _is_pitch_table(t["headers"])]

    def team_for(i: int) -> str | None:
        return teams[i] if i < len(teams) else None

    for ti, t in enumerate(bat_tables):
        team = team_for(ti)
        h = t["headers"]
        innings = [c for c in h if c.isdigit()]
        for row in t["rows"]:
            d = dict(zip(h, row))
            order, pos, name, num = (None, None, d.get("선수", ""), None)
            m = _BAT_CELL_RE.match(_clean(d.get("선수", "")))
            if m:
                order, pos, name, num = int(m.group(1)), m.group(2), m.group(3).strip(), \
                    (int(m.group(4)) if m.group(4) else None)
            pa = [d[i] for i in innings if d.get(i)]
            out["batting"].append({
                "game_idx": game_idx, "team": team, "타순": order, "포지션": pos,
                "선수명": name, "등번호": num,
                "타수": _num(d.get("타수", "")), "안타": _num(d.get("안타", "")),
                "타점": _num(d.get("타점", "")), "득점": _num(d.get("득점", "")),
                "도루": _num(d.get("도루", "")), "타석결과": pa,
            })

    for ti, t in enumerate(pit_tables):
        team = team_for(ti)
        h = t["headers"]
        for i, row in enumerate(t["rows"]):
            d = dict(zip(h, row))
            name, num, _ = _split_name(d.get("선수", ""))
            out["pitching"].append({
                "game_idx": game_idx, "team": team, "선수명": name, "등번호": num,
                "선발": i == 0, "결과": d.get("결과"),
                "이닝": d.get("이닝"), "타자": _num(d.get("타자", "")),
                "피안타": _num(d.get("피안타", "")), "피홈런": _num(d.get("피홈런", "")),
                "볼넷": _num(d.get("볼넷", "")), "사구": _num(d.get("사구", "")),
                "탈삼진": _num(d.get("삼진", "")), "실점": _num(d.get("실점", "")),
                "자책점": _num(d.get("자책점", "")), "투구수": _num(d.get("투구수", "")),
            })
    return out


# ── 등록현황(명단) ────────────────────────────────────────────────────
def parse_roster(html: str) -> list[dict[str, Any]]:
    """state/regist content → 선수 명단. 5개 표(포지션 그룹)를 병합."""
    out: list[dict[str, Any]] = []
    for headers, rows in _rows_as_dicts(html):
        if "팀 원" not in headers and "팀원" not in headers:
            continue
        name_key = "팀 원" if "팀 원" in headers else "팀원"
        ni = headers.index(name_key)
        for row in rows:
            if len(row) != len(headers):
                continue
            rec = {h: _clean(v) for h, v in zip(headers, row)}
            name, num, pos = _split_name(row[ni])
            rec["선수명"] = name
            rec["등번호"] = num
            rec["포지션"] = pos
            # 선수등록일: '팀 2018.03.19 리그 2026.02.19'
            reg = rec.get(name_key.replace(name_key, "선수등록일"), "") or rec.get("선수등록일", "")
            mt = re.search(r"팀\s*([\d.]+)", reg)
            ml = re.search(r"리그\s*([\d.]+)", reg)
            if mt:
                rec["팀등록일"] = mt.group(1)
            if ml:
                rec["리그등록일"] = ml.group(1)
            # 참여/게임수: '2 / 5'
            pg = rec.get("참여/게임수", "")
            mp = re.match(r"(\d+)\s*/\s*(\d+)", pg)
            if mp:
                rec["출전"], rec["팀경기수"] = int(mp.group(1)), int(mp.group(2))
            out.append(rec)
    return out
