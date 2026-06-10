"""게임원 URL 빌더.

핵심: 실제 데이터 테이블은 페이지에 직접 없고 iframe(#subFrame) 안의
`/league/.../content/...` 경로에 서버렌더된다. content_* 함수가 그 실데이터 URL을,
parent_* 함수가 iframe을 감싸는 부모 페이지 URL(=Referer용)을 만든다.

식별자: lig_idx(리그), club_idx(팀), group_code(조 구분), season(시즌),
order(정렬 키), page(페이지).
"""
from __future__ import annotations

from urllib.parse import urlencode

from .. import config

BASE = config.BASE_URL


def _u(path: str, **params) -> str:
    params = {k: v for k, v in params.items() if v is not None and v != ""}
    q = urlencode(params)
    return f"{BASE}{path}?{q}" if q else f"{BASE}{path}"


# ── 실데이터 (iframe content) ────────────────────────────────────────
def record_content(kind: str, *, lig_idx=None, season=None, group_code=None,
                   order=None, page=None) -> str:
    """kind ∈ {batter, pitcher, rank, offense, defense, top}"""
    return _u(f"/league/record/content/{kind}",
              lig_idx=lig_idx or config.LIG_IDX,
              season=season, group_code=group_code, order=order, page=page)


def schedule_content(kind: str, *, lig_idx=None, season=None, group_code=None,
                     page=None) -> str:
    """kind ∈ {schedule, result, all, match, playoff}. page로 페이지네이션."""
    return _u(f"/league/schedule/content/{kind}",
              lig_idx=lig_idx or config.LIG_IDX,
              season=season, group_code=group_code, page=page)


def state_content(kind: str = "regist", *, lig_idx=None, group_code=None,
                  club_idx=None) -> str:
    """등록현황(명단). kind ∈ {regist, search}"""
    return _u(f"/league/state/content/{kind}",
              lig_idx=lig_idx or config.LIG_IDX,
              group_code=group_code, club_idx=club_idx)


def boxscore_content(game_idx: int, *, lig_idx=None, group_code=None) -> str:
    """경기 단위 박스스코어 (타순·타석결과·투수라인)."""
    return _u("/league/schedule/content/boxscore",
              lig_idx=lig_idx or config.LIG_IDX,
              game_idx=game_idx, group_code=group_code or config.OUR_GROUP_CODE)


def player_popup(*, lig_idx=None, club_idx=None, mem_idx=None, season=None) -> str:
    """선수 상세(경기별 기록) 팝업."""
    return _u("/league/pop/player",
              lig_idx=lig_idx or config.LIG_IDX,
              club_idx=club_idx, mem_idx=mem_idx, season=season)


def orderpaper(*, lig_idx=None) -> str:
    return _u("/league/pop/orderpaper", lig_idx=lig_idx or config.LIG_IDX)


def locker_career(token: str, *, season=None, game_type=None) -> str:
    """선수 라커룸 통합기록(통산/시즌, **모든 리그 합산**). token=locker group_code,
    game_type 2=공식 4=원외. season 미지정 시 현재 시즌."""
    return _u("/locker/record/sum", group_code=token, season=season, game_type=game_type)


def locker_games(token: str, *, season=None, game_type=2, lig_idx=None) -> str:
    """선수 라커룸 게임별기록. lig_idx로 리그 스코프(85=사이언스리그). 경기별 raw 행."""
    return _u("/locker/record/game", group_code=token,
              season=season, game_type=game_type, lig_idx=lig_idx)


LOCKER_BASE = f"{BASE}/locker/"


# ── 부모 페이지 (Referer 용) ─────────────────────────────────────────
def record_parent(kind: str, *, lig_idx=None) -> str:
    return _u(f"/league/record/{kind}", lig_idx=lig_idx or config.LIG_IDX)


def schedule_parent(kind: str, *, lig_idx=None) -> str:
    return _u(f"/league/schedule/{kind}", lig_idx=lig_idx or config.LIG_IDX)


def state_parent(kind: str = "regist", *, lig_idx=None) -> str:
    return _u(f"/league/state/{kind}", lig_idx=lig_idx or config.LIG_IDX)


LOGIN_PAGE_URL = f"{BASE}/member/login"
LOGIN_EXEC_URL = f"{BASE}/member/exec/login"
