"""content 엔드포인트 수집 + 원시 HTML 덤프.

snapshot()은 핵심 엔드포인트들을 인증 세션으로 떠서 data/raw/*.html 로 저장한다.
실제(로그인된) 테이블 구조를 확인해 파서를 작성하기 위한 1차 수집 단계.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .. import config
from . import endpoints
from .session import GameOneSession, is_guest_page


@dataclass
class Target:
    name: str                 # 저장 파일명 (data/raw/<name>.html)
    url_fn: Callable[[], str]
    referer_fn: Callable[[], str]


def default_targets(season: int | None = None,
                    group_code: int | None = None) -> list[Target]:
    """우리 리그/팀 기준 핵심 수집 대상."""
    gc = group_code if group_code is not None else config.OUR_GROUP_CODE
    R, S, ST = endpoints.record_content, endpoints.schedule_content, endpoints.state_content
    RP, SP, STP = endpoints.record_parent, endpoints.schedule_parent, endpoints.state_parent

    return [
        # 우리 팀 명단/등록현황
        Target("state_regist",
               lambda: ST("regist", group_code=gc, club_idx=config.CLUB_IDX),
               lambda: STP("regist")),
        # 팀 랭킹 / 공격 / 수비 (조 전체)
        Target("record_rank",    lambda: R("rank", group_code=gc, season=season),    lambda: RP("rank")),
        Target("record_offense", lambda: R("offense", group_code=gc, season=season), lambda: RP("offense")),
        Target("record_defense", lambda: R("defense", group_code=gc, season=season), lambda: RP("defense")),
        # 개인 기록
        Target("record_batter",  lambda: R("batter", group_code=gc, season=season),  lambda: RP("batter")),
        Target("record_pitcher", lambda: R("pitcher", group_code=gc, season=season), lambda: RP("pitcher")),
        Target("record_top",     lambda: R("top", group_code=gc, season=season),     lambda: RP("top")),
        # 일정 / 결과 / 대진
        Target("schedule_result",   lambda: S("result", season=season),   lambda: SP("result")),
        Target("schedule_all",      lambda: S("all", season=season),      lambda: SP("all")),
        Target("schedule_schedule", lambda: S("schedule", season=season), lambda: SP("schedule")),
        Target("schedule_match",    lambda: S("match", season=season),    lambda: SP("match")),
    ]


def snapshot(session: GameOneSession, targets: list[Target] | None = None,
             season: int | None = None, bujo_idx: int | None = None) -> list[dict]:
    """대상들을 떠서 raw 디렉토리에 저장. 결과 메타 리스트 반환.

    bujo_idx: 조 선택 (기본=우리 조 B). 기록/랭킹이 이 조 기준으로 렌더된다.
    """
    session.ensure_login()
    # 기록·랭킹을 우리 조(B) 기준으로 받기 위해 기본 부리그 설정 (핵심!)
    session.set_bujo(bujo_idx if bujo_idx is not None else config.OUR_BUJO_IDX)
    targets = targets or default_targets(season=season)
    results = []
    for t in targets:
        url = t.url_fn()
        try:
            html = session.get_html(url, referer=t.referer_fn())
            path = config.RAW_DIR / f"{t.name}.html"
            path.write_text(html, encoding="utf-8")
            results.append({
                "name": t.name, "url": url, "bytes": len(html),
                "guest": is_guest_page(html), "saved": str(path), "ok": True,
            })
        except Exception as e:  # 한 대상 실패해도 나머지 계속
            results.append({"name": t.name, "url": url, "ok": False, "error": str(e)})
    return results
