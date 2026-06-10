"""수집 오케스트레이터 — 로그인 → 조 설정 → fetch → parse → 구조화 dict.

snapshot()이 원시 HTML을 저장하는 디버그용이라면, crawl()은 파싱까지 끝낸
구조화 데이터를 돌려준다(저장/분석용).
"""
from __future__ import annotations

from typing import Any

from .. import config
from . import endpoints as E
from . import parse
from .session import GameOneSession


def crawl(session: GameOneSession, *, season: int | None = None,
          jo: str | None = None) -> dict[str, Any]:
    """우리 조(기본 B) 기준 전체 데이터 수집 + 파싱."""
    jo = jo or config.OUR_JO
    season = season or config.CURRENT_SEASON
    session.ensure_login()
    session.set_bujo(config.BUJO_IDX[jo])  # 조 설정 (핵심)

    def g(url: str, ref: str) -> str:
        return session.get_html(url, referer=ref)

    data: dict[str, Any] = {"season": season, "jo": jo}

    data["batters"] = parse.parse_batters(
        g(E.record_content("batter", season=season, group_code=config.OUR_GROUP_CODE),
          E.record_parent("batter")), jo)
    data["pitchers"] = parse.parse_pitchers(
        g(E.record_content("pitcher", season=season, group_code=config.OUR_GROUP_CODE),
          E.record_parent("pitcher")), jo)
    data["team_rank"] = parse.parse_team_rank(
        g(E.record_content("rank", season=season, group_code=config.OUR_GROUP_CODE),
          E.record_parent("rank")), jo)
    data["team_offense"] = parse.parse_team_offense(
        g(E.record_content("offense", season=season, group_code=config.OUR_GROUP_CODE),
          E.record_parent("offense")), jo)
    data["team_defense"] = parse.parse_team_defense(
        g(E.record_content("defense", season=season, group_code=config.OUR_GROUP_CODE),
          E.record_parent("defense")), jo)
    data["games"] = parse.parse_schedule(
        g(E.schedule_content("result", season=season), E.schedule_parent("result")))
    data["roster"] = parse.parse_roster(
        g(E.state_content("regist", group_code=config.OUR_GROUP_CODE, club_idx=config.CLUB_IDX),
          E.state_parent("regist")))
    return data


def crawl_roster(session: GameOneSession, club_idx: int, *,
                 group_code: int | None = None) -> list[dict]:
    """특정 팀(club_idx)의 등록 명단만 수집."""
    session.ensure_login()
    gc = group_code or config.OUR_GROUP_CODE
    html = session.get_html(
        E.state_content("regist", group_code=gc, club_idx=club_idx),
        referer=E.state_parent("regist"))
    return parse.parse_roster(html)


def crawl_player_career(session: GameOneSession, name: str, *, club_idx: int | None = None,
                        official: bool = True, stop_empty: int = 3,
                        earliest: int = 2006) -> dict:
    """선수의 시즌별 통산 기록 수집 (라커룸). 명단에서 locker 토큰을 찾아
    현재 시즌부터 거슬러 올라가며 비어있는 시즌이 연속 stop_empty번 나올 때까지 수집."""
    club_idx = club_idx or config.CLUB_IDX
    session.ensure_login()
    session.set_bujo(config.OUR_BUJO_IDX)
    roster_html = session.get_html(
        E.state_content("regist", group_code=config.OUR_GROUP_CODE, club_idx=club_idx),
        referer=E.state_parent("regist"))
    tokmap = parse.roster_locker_map(roster_html)
    token = tokmap.get(name) or next((t for n, t in tokmap.items() if name in n), None)
    if not token:
        return {"name": name, "error": "명단에서 선수를 찾지 못함", "available": sorted(tokmap)}

    gt = 2 if official else 4
    seasons, empty = [], 0
    for yr in range(config.CURRENT_SEASON, earliest - 1, -1):
        rec = parse.parse_locker_career(session.get_html(
            E.locker_career(token, season=yr, game_type=gt), referer=E.LOCKER_BASE))
        games = (rec["batting"].get("경기수") or 0) + (rec["pitching"].get("경기수") or 0)
        if games:
            seasons.append({"season": yr, **rec})
            empty = 0
        elif seasons:
            empty += 1
            if empty >= stop_empty:
                break
    seasons.sort(key=lambda x: x["season"])
    return {"name": name, "token": token, "official": official, "seasons": seasons}


def crawl_player_gamelog(session: GameOneSession, name: str, *, season: int | None = None,
                         club_idx: int | None = None, lig_idx: int | None = None,
                         official: bool = True) -> dict:
    """선수의 경기별 raw 기록 수집 (기본 사이언스리그=lig_idx 85 스코프)."""
    season = season or config.CURRENT_SEASON
    club_idx = club_idx or config.CLUB_IDX
    lig_idx = lig_idx if lig_idx is not None else config.LIG_IDX
    session.ensure_login()
    session.set_bujo(config.OUR_BUJO_IDX)
    roster_html = session.get_html(
        E.state_content("regist", group_code=config.OUR_GROUP_CODE, club_idx=club_idx),
        referer=E.state_parent("regist"))
    tokmap = parse.roster_locker_map(roster_html)
    token = tokmap.get(name) or next((t for n, t in tokmap.items() if name in n), None)
    if not token:
        return {"name": name, "error": "명단에서 선수를 찾지 못함", "available": sorted(tokmap)}
    gt = 2 if official else 4
    html = session.get_html(
        E.locker_games(token, season=season, game_type=gt, lig_idx=lig_idx), referer=E.LOCKER_BASE)
    return {"name": name, "season": season, "lig_idx": lig_idx,
            "games": parse.parse_locker_games(html, season)}


def collect_games(session: GameOneSession, *, season: int | None = None,
                  jo: str | None = None, max_pages: int = 15) -> list[dict]:
    """전체 일정(schedule/all)에서 우리 조의 '완료된' 경기 목록 — 전 페이지 순회.

    schedule/all은 페이지당 ~20경기라 page를 끝까지(새 경기 없을 때까지) 돈다.
    """
    jo = jo or config.OUR_JO
    season = season or config.CURRENT_SEASON
    session.ensure_login()
    session.set_bujo(config.BUJO_IDX[jo])
    seen: dict[int, dict] = {}
    for page in range(1, max_pages + 1):
        html = session.get_html(
            E.schedule_content("all", season=season, page=page),
            referer=E.schedule_parent("all"))
        games = [g for g in parse.parse_schedule(html)
                 if g.get("played") and g.get("game_idx")]
        new = [g for g in games if g["game_idx"] not in seen]
        if not new:           # 새 경기 없음 → 마지막 페이지
            break
        for g in new:
            seen[g["game_idx"]] = g
    return list(seen.values())


def crawl_boxscores(session: GameOneSession, *, season: int | None = None,
                    jo: str | None = None, skip_existing: bool = True,
                    limit: int | None = None) -> dict:
    """우리 조 완료 경기들의 박스스코어를 증분 수집·저장. {fetched, skipped, total} 반환."""
    from ..storage import db
    games = collect_games(session, season=season, jo=jo)
    have = db.stored_game_idxs() if skip_existing else set()
    todo = [g for g in games if g["game_idx"] not in have]
    if limit:
        todo = todo[:limit]
    fetched = 0
    for g in todo:
        gid = g["game_idx"]
        html = session.get_html(
            E.boxscore_content(gid), referer=E.schedule_parent("result"))
        bs = parse.parse_boxscore(html, game_idx=gid)
        db.save_boxscore(bs, date=g.get("일시"), jo=g.get("분류"))
        fetched += 1
    return {"fetched": fetched, "skipped": len(games) - len(todo), "total": len(games)}
