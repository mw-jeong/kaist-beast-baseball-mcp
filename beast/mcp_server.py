"""Beast MCP 서버 — Claude Desktop 연동.

게임원 B조 데이터를 '도구'로 노출. 분석(라인업/전략)은 Claude Desktop이 추론하고,
서버는 신뢰할 수 있는 데이터·계산(소표본 보정·파생지표·집계)을 제공한다. API 키 불필요.

실행(보통 Claude Desktop이 자동 기동):  python -m beast.mcp_server
설정 자동 등록:                        python -m beast.cli setup-desktop
"""
from __future__ import annotations

import pandas as pd
from mcp.server.fastmcp import FastMCP

from beast import config
from beast.analysis import report, stats
from beast.storage import db

mcp = FastMCP("kaist-beast-mcp")
_session = None


def _get_session(force: bool = False):
    global _session
    from beast.crawler.session import GameOneSession
    if _session is None or force:
        s = GameOneSession()
        s.login()
        _session = s
    return _session


def _ensure_data() -> None:
    if db.latest_snapshot_id(season=config.CURRENT_SEASON, jo=config.OUR_JO) is None:
        from beast.crawler.crawl import crawl
        db.save_snapshot(crawl(_get_session()), note="mcp auto")
    if not db.stored_game_idxs():
        from beast.crawler.crawl import crawl_boxscores
        crawl_boxscores(_get_session())


def _safe(fn):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return f"⚠️ 오류: {type(e).__name__}: {e}"


def _md(df, cols=None) -> str:
    return report._md_table(df, cols)


# ── 수집/상태 ─────────────────────────────────────────────────────────
@mcp.tool()
def refresh_data(season: int | None = None) -> str:
    """게임원에서 우리 리그(사이언스리그 B조) 최신 데이터를 새로 수집·저장한다.
    시즌 누적 기록 + 경기별 박스스코어(게임 로그)까지 갱신. 최신 분석 전에 호출."""
    def run():
        from beast.crawler.crawl import crawl, crawl_boxscores
        s = _get_session(force=True)
        data = crawl(s, season=season)
        sid = db.save_snapshot(data, note="mcp refresh")
        box = crawl_boxscores(s, season=season)
        counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
        return (f"✓ snapshot #{sid}: " + ", ".join(f"{k} {v}" for k, v in counts.items())
                + f" | 박스스코어 {box}")
    return _safe(run)


@mcp.tool()
def guide() -> str:
    """이 리그/게임원 데이터의 배경·해석상 함정·도구 사용법을 담은 도메인 가이드.
    분석을 시작하기 전, 또는 데이터 해석이 헷갈릴 때 먼저 읽어라(소표본·ERA 7이닝·
    상대 등번호 0·player_career는 전체리그 합산 등)."""
    def run():
        path = config.PROJECT_ROOT / "docs" / "GAMEONE.md"
        return path.read_text(encoding="utf-8") if path.exists() else "가이드 문서를 찾을 수 없습니다."
    return _safe(run)


@mcp.tool()
def data_status() -> str:
    """현재 저장된 데이터 신선도 — 최근 수집 시각, 스냅샷 수, 박스스코어 경기 수."""
    def run():
        snaps = db.list_snapshots()
        games = db.boxscore_games()
        last = snaps.iloc[0]["created_at"] if not snaps.empty else "없음"
        return (f"최근 수집: {last} | 스냅샷 {len(snaps)}개 | "
                f"박스스코어 경기 {len(games)}개. 더 최신이 필요하면 refresh_data 호출.")
    return _safe(run)


@mcp.tool()
def list_teams() -> str:
    """B조 전체 팀 이름 목록."""
    return _safe(lambda: (_ensure_data(), "B조 팀: " + ", ".join(stats.teams()))[1])


@mcp.tool()
def standings() -> str:
    """B조 순위표 (순위/승/패/무/승률/승점)."""
    def run():
        _ensure_data()
        s = stats.standings().drop(columns=["조", "club_idx"], errors="ignore")
        return "## B조 순위표\n" + _md(s)
    return _safe(run)


# ── 팀/선수 기록 ──────────────────────────────────────────────────────
@mcp.tool()
def team_batters(team: str) -> str:
    """팀 타자 기록 (게임원 raw 그대로) — 타율/출루율/장타율/OPS/타석/홈런/타점/도루 + 규정타석 표시.
    OPS 순 정렬. 표본이 작은 선수(타석 적음)는 '규정' 컬럼·타석 수로 판단할 것.
    소표본을 리그평균으로 보정해 비교하려면 regressed_batting 도구를 따로 쓴다.
    team 예: 'The Beasts', '대전 리드오프'."""
    def run():
        _ensure_data()
        b = stats.batters(team)
        if b.empty:
            return f"'{team}' 타자 데이터 없음. list_teams로 이름 확인."
        b = b.assign(_s=pd.to_numeric(b["OPS"], errors="coerce")).sort_values("_s", ascending=False)
        return f"## {team} 타자 (raw · OPS순)\n" + _md(b, report.BATTER_COLS)
    return _safe(run)


@mcp.tool()
def regressed_batting(team: str, k_pa: int = 15) -> str:
    """[보정 도구] 소표본 empirical Bayes shrinkage — '1타석 OPS 2.0' 같은 허수를
    리그 평균 쪽으로 수축한 AVG/OBP/SLG/OPS_adj + BB%/K%/ISO를 반환한다.
    타석이 적은 선수끼리 '진짜 실력'을 공정 비교할 때만 사용(기본 team_batters는 raw).
    k_pa = 가상 타석(prior strength, 클수록 강하게 수축, 기본 15)."""
    def run():
        _ensure_data()
        b = stats.batting_metrics(stats.batters(team), k_pa=k_pa)
        if b.empty:
            return f"'{team}' 타자 데이터 없음."
        b = b.sort_values("OPS_adj", ascending=False)
        cols = ["선수명", "타석", "타율", "OPS", "OPS_adj", "AVG_adj", "OBP_adj",
                "SLG_adj", "BB%", "K%", "ISO", "규정"]
        return (f"## {team} 타자 — 소표본 보정(k_pa={k_pa})\n"
                f"_raw OPS와 보정 OPS_adj를 함께 표기. adj는 리그평균으로 수축한 추정._\n"
                + _md(b, cols))
    return _safe(run)


@mcp.tool()
def team_pitchers(team: str) -> str:
    """팀 투수 기록 (방어율/WHIP/이닝/탈삼진/볼넷/피안타율) — 방어율 순."""
    def run():
        _ensure_data()
        p = stats.pitchers(team)
        if p.empty:
            return f"'{team}' 투수 데이터 없음."
        return f"## {team} 투수\n" + _md(p.sort_values("방어율"), report.PITCHER_COLS)
    return _safe(run)


@mcp.tool()
def team_summary(team: str) -> str:
    """팀 한눈 요약 — 정체성 한 줄(타율/출루/OPS/BB%/K%/ISO/도루/득실) + 핵심 타자·투수.
    '이 팀이 무엇으로 굴러가는지' 빠르게 파악할 때."""
    def run():
        _ensure_data()
        b = stats.batters(team)
        b = b.assign(_s=pd.to_numeric(b["OPS"], errors="coerce")).sort_values("_s", ascending=False)
        p = stats.pitchers(team).sort_values("방어율")
        return (f"## {team} 요약\n{report.team_identity(team)}\n\n"
                f"### 핵심 타자 (OPS순, raw)\n" + _md(b.head(6),
                    ["선수명", "타율", "출루율", "OPS", "타석", "홈런", "타점", "도루"])
                + "\n\n### 투수\n" + _md(p, ["선수명", "방어율", "WHIP", "이닝", "탈삼진", "볼넷"]))
    return _safe(run)


@mcp.tool()
def league_leaders(category: str = "OPS", top: int = 10, min_pa: int = 10) -> str:
    """B조 리더보드 (raw). category: OPS/AVG/OBP/RBI/SB/HR (타격) 또는 ERA/WHIP/K (투수).
    타격은 min_pa(기본 10타석) 이상만 포함해 1타석 허수를 거른다. 위협 타자·에이스 파악용."""
    def run():
        _ensure_data()
        df = stats.league_leaders(category, top=top, min_pa=min_pa)
        if df.empty:
            return f"'{category}' 리더보드 산출 불가."
        return f"## B조 {category} 리더 (raw, 타격 min {min_pa}타석)\n" + _md(df)
    return _safe(run)


# ── 경기 단위(게임 로그) ──────────────────────────────────────────────
@mcp.tool()
def game_log(team: str, last_n: int = 5) -> str:
    """팀의 최근 N경기 — 결과 + **실제 타순**(타순/포지션/선수) + 선발투수.
    상대 실제 타순·선발 로테이션 파악(시즌 누적 추정보다 정확)."""
    def run():
        _ensure_data()
        games = stats.game_log(team, n=last_n)
        if not games:
            return f"'{team}' 경기 로그 없음."
        blocks = []
        for g in games:
            lu = " / ".join(f"{x['타순']}{x['포지션']} {x['선수명']}" for x in g["타순"])
            blocks.append(f"**{g['date']}** vs {g['상대']} {g['스코어']} ({g['결과']}) "
                          f"· 선발 {g['선발투수']}\n  타순: {lu}")
        return f"## {team} 최근 {len(games)}경기\n" + "\n\n".join(blocks)
    return _safe(run)


@mcp.tool()
def recent_form(team: str, last_n: int = 3) -> str:
    """팀의 최근 N경기 선수별 타격 합산 — 시즌 누적과 비교용(폼 점검)."""
    def run():
        _ensure_data()
        df = stats.recent_form(team, n=last_n)
        if df.empty:
            return f"'{team}' 최근 경기 데이터 없음."
        return f"## {team} 최근 {last_n}경기 타격\n" + _md(df)
    return _safe(run)


@mcp.tool()
def pitcher_usage(team: str) -> str:
    """팀 투수 운용/부하 — 등판수·선발수·누적이닝·볼넷·탈삼진·최근등판. 로테이션·피로 판단."""
    def run():
        _ensure_data()
        df = stats.pitcher_usage(team)
        if df.empty:
            return f"'{team}' 투수 등판 데이터 없음 (박스스코어 필요)."
        return (f"## {team} 투수 운용\n" + _md(df,
                ["선수명", "등판", "선발", "이닝", "타자", "볼넷", "탈삼진", "자책점", "최근등판"]))
    return _safe(run)


# ── 상대/맞대결 ───────────────────────────────────────────────────────
@mcp.tool()
def scout_report(opponent: str, sections: str = "all") -> str:
    """상대 전략용 종합 — 순위표 + 우리팀 + 상대팀(소표본 보정) + 맞대결(없으면 공통상대).
    상대 전략·라인업을 짤 때 이 도구 하나로 충분. sections: 'all' 또는
    콤마구분('standings,our,opponent,h2h')으로 일부만(토큰 절약)."""
    def run():
        _ensure_data()
        sec = None if sections in ("all", "", None) else [s.strip() for s in sections.split(",")]
        return report.strategy_report(opponent=opponent, sections=sec)
    return _safe(run)


@mcp.tool()
def head_to_head(opponent: str) -> str:
    """우리 팀 vs 상대 맞대결. 맞대결이 없으면 공통상대 비교(스케줄 강도 신호)로 대체."""
    def run():
        _ensure_data()
        h = stats.head_to_head(stats.OUR_TEAM, opponent)
        if not h.empty:
            cols = ["date", "team1", "score1", "team2", "score2", "winner"]
            return f"## {stats.OUR_TEAM} vs {opponent} 맞대결\n" + _md(h, cols)
        co = stats.common_opponents(opponent)
        return (f"## 맞대결 없음 → 공통상대 비교\n" + _md(co))
    return _safe(run)


@mcp.tool()
def common_opponents(team: str) -> str:
    """우리 팀과 상대팀이 공통으로 만난 팀들에 대한 각자 전적 — 스케줄 강도 비교."""
    def run():
        _ensure_data()
        return f"## 공통상대 ({stats.OUR_TEAM} vs {team})\n" + _md(stats.common_opponents(team))
    return _safe(run)


# ── 명단 ──────────────────────────────────────────────────────────────
@mcp.tool()
def our_roster() -> str:
    """우리 팀(The Beasts) 등록 명단 (이름/등번호/포지션/생년월일/출전)."""
    def run():
        _ensure_data()
        df = db.load("roster", season=config.CURRENT_SEASON, jo=config.OUR_JO)
        return "## The Beasts 명단\n" + _md(df, ["선수명", "등번호", "포지션", "생년월일", "출전", "팀경기수", "구분"])
    return _safe(run)


@mcp.tool()
def opponent_roster(team: str) -> str:
    """상대팀 등록 명단을 라이브 수집(이름/포지션/생년월일). 등번호는 타팀 비공개일 수 있음."""
    def run():
        cid = stats.club_idx_for(team)
        if not cid:
            return f"'{team}'의 club_idx를 찾지 못함. list_teams 확인."
        from beast.crawler.crawl import crawl_roster
        ros = crawl_roster(_get_session(), cid)
        df = pd.DataFrame(ros)
        return (f"## {team} 명단 ({len(ros)}명)\n"
                + _md(df, ["선수명", "등번호", "포지션", "생년월일", "출신고", "출전", "팀경기수"]))
    return _safe(run)


def _resolve_club(team: str):
    """team(빈값=우리팀) → club_idx. 못 찾으면 None."""
    if not team or team == stats.OUR_TEAM:
        return config.CLUB_IDX
    return stats.club_idx_for(team)


@mcp.tool()
def player_gamelog(name: str, team: str = "", season: int = 0) -> str:
    """선수의 **경기별 raw 기록 (사이언스리그)**. 우리/상대 선수 모두 가능.
    현재 시즌은 박스스코어 기반(타석결과·도루까지, 상대 선수 포함), 과거 시즌은 라커룸 기반
    (우리 팀 선수만 — 타팀 과거 게임별은 게임원이 비공개). team 미지정=우리팀, 상대면 그 팀명.
    season 미지정(0)=현재 시즌."""
    def run():
        _ensure_data()
        yr = season or config.CURRENT_SEASON
        t = team or stats.OUR_TEAM
        # 1) 현재 시즌 → 박스스코어 (우리/상대 모두, 풍부)
        if yr == config.CURRENT_SEASON:
            df = stats.player_box_gamelog(name, t)
            if not df.empty:
                return f"## {name} ({t}) {yr} 사이언스리그 경기별 (박스스코어)\n" + _md(df)
        # 2) 과거 시즌(또는 박스 없음) → 라커룸 (우리 팀 선수만)
        from beast.crawler.crawl import crawl_player_gamelog
        cidx = _resolve_club(team)
        if cidx is None:
            return f"'{team}' 팀을 찾지 못함. list_teams로 확인."
        r = crawl_player_gamelog(_get_session(), name, season=yr, club_idx=cidx)
        if r.get("error"):
            return f"{r['error']}. 해당 팀 선수: {', '.join(r.get('available', []))[:300]}"
        games = r["games"]
        if not games:
            note = " (타팀 과거 게임별은 비공개)" if team and team != stats.OUR_TEAM else ""
            return f"'{name}' {yr}시즌 사이언스리그 경기 기록이 없습니다{note}."
        df = pd.DataFrame(games)[["date", "상대", "구분", "타석", "타수", "안타", "득점", "타점"]]
        return f"## {name} ({t}) {yr} 사이언스리그 경기별 (라커룸)\n" + _md(df)
    return _safe(run)


@mcp.tool()
def player_career(name: str, team: str = "", official: bool = True) -> str:
    """선수의 시즌별 + 통산 기록(라커룸). ⚠️ **이 선수가 뛴 모든 리그·팀 합산 전체 커리어**
    (사이언스리그 한정 아님 — 게임원이 리그 분리를 안 해줌). 선수의 전반적 수준·다년 추세 파악용.
    우리/상대 선수 모두 가능 — team 미지정=우리팀, 상대 선수면 그 팀명.
    사이언스리그 단위 경기 기록은 player_gamelog를 쓸 것."""
    def run():
        from beast.crawler.crawl import crawl_player_career
        cidx = _resolve_club(team)
        if cidx is None:
            return f"'{team}' 팀을 찾지 못함. list_teams로 확인."
        career = crawl_player_career(_get_session(), name, club_idx=cidx, official=official)
        if career.get("error"):
            return f"{career['error']}. 해당 팀 선수: {', '.join(career.get('available', []))[:300]}"
        bdf, pdf = stats.career_tables(career)
        if bdf.empty and pdf.empty:
            return f"'{name}' 통산 기록이 없습니다(공식경기 기준)."
        out = [f"## {name} 통산/시즌별 ({'공식' if official else '원외'})"]
        if not bdf.empty:
            out.append("### 타자\n" + _md(bdf))
        if not pdf.empty:
            out.append("### 투수 (ERA 7이닝 기준)\n" + _md(pdf))
        return "\n\n".join(out)
    return _safe(run)


# ── 전력관리(write) ───────────────────────────────────────────────────
@mcp.tool()
def save_lineup(body: str, label: str = "", opponent: str = "", note: str = "") -> str:
    """짜낸 라인업(타순·수비·투수 운용 등)을 저장해 다음에 다시 볼 수 있게 한다.
    body=라인업 내용(표/텍스트), label=이름(예 '리드오프전 1안'), opponent=상대팀, note=메모.
    대화로 설계한 라인업이 휘발되지 않게 보관하는 용도."""
    def run():
        lid = db.save_lineup(body, label=label, opponent=opponent, note=note)
        return f"✓ 라인업 저장됨 (#{lid}) — list_lineups로 다시 볼 수 있음."
    return _safe(run)


@mcp.tool()
def list_lineups(limit: int = 10) -> str:
    """저장된 라인업 목록(최신순) — id/날짜/이름/상대/메모 + 내용."""
    def run():
        df = db.list_lineups(limit=limit)
        if df.empty:
            return "저장된 라인업이 없습니다. save_lineup으로 저장하세요."
        blocks = []
        for _, r in df.iterrows():
            head = f"### #{r['id']} {r['label'] or ''} (상대: {r['opponent'] or '-'}, {r['created_at']})"
            if r["note"]:
                head += f"\n_{r['note']}_"
            blocks.append(head + "\n" + (r["body"] or ""))
        return "## 저장된 라인업\n" + "\n\n".join(blocks)
    return _safe(run)


def main() -> None:
    """기본 stdio(Claude Desktop). --http [--port N] 면 Streamable HTTP(원격/claude.ai용)."""
    import sys
    if "--http" in sys.argv:
        if "--port" in sys.argv:
            try:
                mcp.settings.port = int(sys.argv[sys.argv.index("--port") + 1])
            except (ValueError, IndexError):
                pass
        mcp.settings.host = "127.0.0.1"
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
