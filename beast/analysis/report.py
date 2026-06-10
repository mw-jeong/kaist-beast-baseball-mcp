"""전략용 데이터 export — 정리된 Markdown 묶음 생성.

크롤링한 데이터를 사람이 읽기 좋고 Claude에게 그대로 물어보기 좋은 Markdown으로.
소표본 보정(OPS_adj)·팀 정체성 한 줄·공통상대 fallback 포함. sections로 분량 제어.
"""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .. import config
from . import stats

OUR = stats.OUR_TEAM

BATTER_COLS = ["선수명", "등번호", "타율", "출루율", "장타율", "OPS",
               "타석", "타수", "총안타", "홈런", "타점", "도루", "볼넷", "삼진", "규정"]
PITCHER_COLS = ["선수명", "등번호", "방어율", "WHIP", "이닝", "승", "패", "세이브",
                "홀드", "탈삼진", "볼넷", "피안타율", "피홈런"]


def _md_table(df: pd.DataFrame, cols: list[str] | None = None) -> str:
    if df is None or df.empty:
        return "_(데이터 없음)_"
    if cols:
        cols = [c for c in cols if c in df.columns]
        df = df[cols]
    header = "| " + " | ".join(map(str, df.columns)) + " |"
    sep = "| " + " | ".join("---" for _ in df.columns) + " |"
    rows = ["| " + " | ".join("" if pd.isna(v) else str(v) for v in r) + " |"
            for r in df.itertuples(index=False)]
    return "\n".join([header, sep, *rows])


def team_identity(team: str, *, season=None, jo=None) -> str:
    """팀 정체성 한 줄 (집계 수치 — LLM이 해석)."""
    a = stats.team_aggregate(team, season=season, jo=jo)
    return (f"**{team}** — {a['경기']}경기 | 타율 {a['타율']} 출루 {a['출루율']} OPS {a['OPS']} "
            f"| BB% {a['BB%']} K% {a['K%']} ISO {a['ISO']} "
            f"| 홈런 {a['홈런']} 도루 {a['도루']}({a['도루/경기']}/g) "
            f"| 득점 {a['득점/경기']}/g 실점 {a['실점/경기']}/g")


def _team_block(team: str, *, season=None, jo=None) -> str:
    b = stats.batters(team, season=season, jo=jo)
    if not b.empty and "OPS" in b.columns:
        b = b.assign(_s=pd.to_numeric(b["OPS"], errors="coerce")).sort_values("_s", ascending=False)
    p = stats.pitchers(team, season=season, jo=jo)
    if not p.empty and "방어율" in p.columns:
        p = p.sort_values("방어율")
    return (
        f"{team_identity(team, season=season, jo=jo)}\n\n"
        f"### 타자 ({len(b)}명) — OPS 순 (raw · 표본은 타석/규정 참고)\n{_md_table(b, BATTER_COLS)}\n\n"
        f"### 투수 ({len(p)}명) — 방어율 순\n{_md_table(p, PITCHER_COLS)}\n"
    )


def strategy_report(opponent: str | None = None, *, sections: list[str] | None = None,
                    season=None, jo=None) -> str:
    """우리 팀 + (옵션)상대팀 전략용 Markdown.

    sections: 포함 블록 선택 — {"standings","our","opponent","h2h"}. 기본 전체.
    """
    season = season or config.CURRENT_SEASON
    jo = jo or config.OUR_JO
    sec = set(sections or ["standings", "our", "opponent", "h2h"])
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    out = [f"# Beast 전력분석 데이터 — {season}시즌 {jo}조 (수집 {now})\n"]

    if "standings" in sec:
        out.append("## B조 순위표\n" + _md_table(
            stats.standings(season=season, jo=jo).drop(columns=["조", "club_idx"], errors="ignore")) + "\n")

    if "our" in sec:
        out.append(f"## 🐯 우리 팀 — {OUR}\n" + _team_block(OUR, season=season, jo=jo))

    if opponent and "opponent" in sec:
        out.append(f"\n## 🔴 상대 — {opponent}\n" + _team_block(opponent, season=season, jo=jo))

    if opponent and "h2h" in sec:
        h2h = stats.head_to_head(OUR, opponent, season=season, jo=jo)
        cols = ["일시" if "일시" in h2h.columns else "date", "team1", "score1", "team2", "score2", "winner"]
        if not h2h.empty:
            out.append(f"\n### {OUR} vs {opponent} 맞대결\n" + _md_table(h2h, cols))
        else:  # 맞대결 없으면 공통상대로 비교
            co = stats.common_opponents(opponent, season=season, jo=jo)
            out.append(f"\n### 맞대결 없음 → 공통상대 비교\n" + _md_table(co))

    return "\n".join(out)
