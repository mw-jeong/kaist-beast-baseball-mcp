"""분석 지표 — 최신 스냅샷에서 팀/선수/상대 데이터를 뽑아 가공.

게임원이 이미 타율·출루율·OPS·방어율·WHIP 등을 계산해 주므로 재계산은 최소화하고,
필터링·정렬·상대전적·요약에 집중한다.
"""
from __future__ import annotations

import re

import pandas as pd

from .. import config
from ..storage import db

OUR_TEAM = "The Beasts"


# ── 유틸 ──────────────────────────────────────────────────────────────
def innings_to_float(x) -> float:
    """'18 ⅔' / '8' / '2 ⅓' → 18.667 등. 사회인 기록의 이닝 표기 처리."""
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip()
    frac = {"⅓": 1 / 3, "⅔": 2 / 3, "1/3": 1 / 3, "2/3": 2 / 3}
    total = 0.0
    m = re.match(r"(\d+)", s)
    if m:
        total += int(m.group(1))
    for k, v in frac.items():
        if k in s:
            total += v
            break
    return round(total, 3)


def _our(df: pd.DataFrame, team: str = OUR_TEAM) -> pd.DataFrame:
    if df.empty or "팀명" not in df.columns:
        return df
    return df[df["팀명"] == team].copy()


# ── 팀 단위 ──────────────────────────────────────────────────────────
def standings(season=None, jo=None) -> pd.DataFrame:
    """B조 팀 순위."""
    return db.load("team_rank", season=season, jo=jo)


def team_offense(season=None, jo=None) -> pd.DataFrame:
    return db.load("team_offense", season=season, jo=jo)


def team_defense(season=None, jo=None) -> pd.DataFrame:
    return db.load("team_defense", season=season, jo=jo)


def teams(season=None, jo=None) -> list[str]:
    """조 내 팀 목록 (랭킹 기준)."""
    s = standings(season=season, jo=jo)
    return sorted(s["팀명"].tolist()) if not s.empty else list(config.B_JO_TEAMS)


def club_map(season=None, jo=None) -> dict[str, int]:
    """팀명 → club_idx. 최신 랭킹 스냅샷 우선, 없으면 config 정적 맵."""
    s = standings(season=season, jo=jo)
    m: dict[str, int] = {}
    if not s.empty and "club_idx" in s.columns:
        for _, r in s.iterrows():
            cid = r.get("club_idx")
            if pd.notna(cid):
                m[r["팀명"]] = int(cid)
    # config 맵으로 보강
    for name, cid in config.B_JO_CLUB_IDX.items():
        m.setdefault(name, cid)
    return m


def club_idx_for(team: str, season=None, jo=None) -> int | None:
    return club_map(season=season, jo=jo).get(team)


# ── 선수 단위 ────────────────────────────────────────────────────────
def batters(team: str | None = None, *, min_pa: int = 0,
            season=None, jo=None) -> pd.DataFrame:
    df = db.load("batters", season=season, jo=jo)
    if df.empty:
        return df
    if team:
        df = df[df["팀명"] == team]
    if min_pa and "타석" in df.columns:
        df = df[pd.to_numeric(df["타석"], errors="coerce").fillna(0) >= min_pa]
    return df.copy()


def pitchers(team: str | None = None, *, min_ip: float = 0,
             season=None, jo=None) -> pd.DataFrame:
    df = db.load("pitchers", season=season, jo=jo)
    if df.empty:
        return df
    if team:
        df = df[df["팀명"] == team]
    if "이닝" in df.columns:
        df = df.assign(이닝수=df["이닝"].map(innings_to_float))
        if min_ip:
            df = df[df["이닝수"] >= min_ip]
    return df.copy()


def our_batters(*, min_pa: int = 0, **kw) -> pd.DataFrame:
    return batters(OUR_TEAM, min_pa=min_pa, **kw)


def our_pitchers(*, min_ip: float = 0, **kw) -> pd.DataFrame:
    return pitchers(OUR_TEAM, min_ip=min_ip, **kw)


def leaders(stat: str = "OPS", *, top: int = 10, ascending: bool = False,
            min_pa: int = 10, season=None, jo=None) -> pd.DataFrame:
    """조 전체 타자 리더보드 (기본 OPS 상위). 방어율 등은 ascending=True."""
    df = batters(min_pa=min_pa, season=season, jo=jo)
    if df.empty or stat not in df.columns:
        return pd.DataFrame()
    df = df.assign(_s=pd.to_numeric(df[stat], errors="coerce"))
    df = df.dropna(subset=["_s"]).sort_values("_s", ascending=ascending)
    # stat이 기본 컬럼과 겹쳐도 중복되지 않도록 순서 유지 dedupe
    wanted = ["선수명", "팀명", stat, "타율", "출루율", "OPS", "타석", "홈런", "타점"]
    cols, seen = [], set()
    for c in wanted:
        if c in df.columns and c not in seen:
            cols.append(c); seen.add(c)
    return df[cols].head(top).reset_index(drop=True)


# ── 상대 분석 ────────────────────────────────────────────────────────
def games(season=None, jo=None) -> pd.DataFrame:
    return db.load("games", season=season, jo=jo)


def head_to_head(team_a: str, team_b: str, season=None, jo=None) -> pd.DataFrame:
    """두 팀 간 맞대결 경기들 (박스스코어 기반 전체)."""
    g = games_df(season=season, jo=jo)
    if g.empty:
        return g
    pair = {team_a, team_b}
    mask = g.apply(lambda r: {r.get("team1"), r.get("team2")} == pair, axis=1)
    return g[mask].copy()


def team_record(team: str, season=None, jo=None) -> dict:
    """경기 결과로부터 팀 전적(승/패/무, 득실) 집계 (박스스코어 기반 전체)."""
    g = games_df(season=season, jo=jo)
    w = l = d = rs = ra = 0
    if not g.empty:
        for _, r in g.iterrows():
            t1, t2, s1, s2 = r.get("team1"), r.get("team2"), r.get("score1"), r.get("score2")
            if team not in (t1, t2):
                continue
            for_, against = (s1, s2) if team == t1 else (s2, s1)
            for_, against = for_ or 0, against or 0
            rs += for_; ra += against
            if for_ > against: w += 1
            elif for_ < against: l += 1
            else: d += 1
    return {"팀": team, "승": w, "패": l, "무": d,
            "득점": rs, "실점": ra, "득실차": rs - ra}


# ── 파생지표 + 소표본 보정(empirical Bayes shrinkage) ────────────────
def batting_metrics(df: pd.DataFrame, *, k_pa: int = 15) -> pd.DataFrame:
    """타자 DF에 BB%/K%/ISO + 리그평균으로 수축한 AVG/OBP/SLG/OPS(_adj) 추가.

    소표본(예: 1타석 .800)을 리그 평균 쪽으로 당겨 '진짜 실력' 추정치를 만든다.
    k_pa = 가상 타석(prior strength) — 클수록 강하게 수축. 아마추어 소표본 기본 15.
    """
    if df.empty:
        return df
    df = df.copy()
    num = lambda c: pd.to_numeric(df.get(c, 0), errors="coerce").fillna(0)
    AB, PA, H, BB = num("타수"), num("타석"), num("총안타"), num("볼넷")
    HBP, K, TB = num("사구"), num("삼진"), num("루타")
    OB = H + BB + HBP
    lg_avg = H.sum() / AB.sum() if AB.sum() else 0.0
    lg_obp = OB.sum() / PA.sum() if PA.sum() else 0.0
    lg_slg = TB.sum() / AB.sum() if AB.sum() else 0.0
    PAd, ABd = PA.where(PA != 0), AB.where(AB != 0)   # 0 → NaN(float)
    df["BB%"] = (BB / PAd * 100).round(1)
    df["K%"] = (K / PAd * 100).round(1)
    df["ISO"] = ((TB - H) / ABd).round(3)
    df["AVG_adj"] = ((H + k_pa * lg_avg) / (AB + k_pa)).round(3)
    df["OBP_adj"] = ((OB + k_pa * lg_obp) / (PA + k_pa)).round(3)
    df["SLG_adj"] = ((TB + k_pa * lg_slg) / (AB + k_pa)).round(3)
    df["OPS_adj"] = (df["OBP_adj"] + df["SLG_adj"]).round(3)
    return df


# ── 경기 결과(전체) — 박스스코어 기반(없으면 스냅샷 일정) ─────────────
def _date_key(s) -> int:
    m = re.findall(r"\d+", str(s or ""))
    mm = int(m[0]) if len(m) > 0 else 0
    dd = int(m[1]) if len(m) > 1 else 0
    hh = int(m[2]) if len(m) > 2 else 0
    mi = int(m[3]) if len(m) > 3 else 0
    return ((mm * 100 + dd) * 100 + hh) * 100 + mi


def games_df(season=None, jo=None) -> pd.DataFrame:
    """완료 경기 전체(팀/점수/승자). 박스스코어 라인스코어 우선, 없으면 일정 스냅샷."""
    g = db.boxscore_games()
    if not g.empty:
        rows = []
        for _, r in g.iterrows():
            ls = r["line_score"] or []
            if len(ls) >= 2:
                t1, t2 = ls[0], ls[1]
                s1, s2 = t1.get("R"), t2.get("R")
                win = t1["team"] if (s1 or 0) > (s2 or 0) else (t2["team"] if (s2 or 0) > (s1 or 0) else None)
                rows.append({"game_idx": r["game_idx"], "date": r["date"], "분류": r["jo"],
                             "team1": t1["team"], "score1": s1, "team2": t2["team"],
                             "score2": s2, "winner": win, "played": True})
        if rows:
            return pd.DataFrame(rows)
    return games(season=season, jo=jo)


def recent_form(team: str, n: int = 3) -> pd.DataFrame:
    """최근 N경기 선수별 타격(박스스코어 합산) — 시즌 누적과 비교용."""
    bat = db.load_game_lines("batting", team=team)
    if bat.empty:
        return bat
    bat = bat.assign(_k=bat["_date"].map(_date_key))
    order = bat.groupby("game_idx")["_k"].first().sort_values()
    last = list(order.index)[-n:]
    r = bat[bat["game_idx"].isin(last)].copy()
    for c in ["타수", "안타", "타점", "득점", "도루"]:
        r[c] = pd.to_numeric(r[c], errors="coerce").fillna(0)
    agg = r.groupby("선수명").agg(경기=("game_idx", "nunique"), 타수=("타수", "sum"),
                                 안타=("안타", "sum"), 타점=("타점", "sum"),
                                 득점=("득점", "sum"), 도루=("도루", "sum")).reset_index()
    agg["타율"] = (agg["안타"] / agg["타수"].where(agg["타수"] != 0)).round(3)
    return agg.sort_values(["타점", "타율"], ascending=False).reset_index(drop=True)


def pitcher_usage(team: str) -> pd.DataFrame:
    """투수별 등판 이력/부하(박스스코어 합산) — 등판수·선발·이닝·최근등판."""
    pit = db.load_game_lines("pitching", team=team)
    if pit.empty:
        return pit
    pit = pit.assign(_k=pit["_date"].map(_date_key), 이닝수=pit["이닝"].map(innings_to_float))
    for c in ["타자", "볼넷", "탈삼진", "실점", "자책점"]:
        pit[c] = pd.to_numeric(pit[c], errors="coerce").fillna(0)
    agg = pit.groupby("선수명").agg(
        등판=("game_idx", "nunique"), 선발=("선발", "sum"), 이닝=("이닝수", "sum"),
        타자=("타자", "sum"), 볼넷=("볼넷", "sum"), 탈삼진=("탈삼진", "sum"),
        실점=("실점", "sum"), 자책점=("자책점", "sum")).reset_index()
    last = pit.sort_values("_k").groupby("선수명")["_date"].last()
    agg["최근등판"] = agg["선수명"].map(last)
    agg["이닝"] = agg["이닝"].round(2)
    return agg.sort_values("이닝", ascending=False).reset_index(drop=True)


def game_log(team: str, n: int = 5) -> list[dict]:
    """팀의 최근 N경기 — 결과 + 실제 타순(타순/포지션/선수) + 선발투수."""
    g = games_df()
    if g.empty:
        return []
    g = g[(g["team1"] == team) | (g["team2"] == team)].copy()
    g = g.assign(_k=g["date"].map(_date_key)).sort_values("_k").tail(n)
    bat = db.load_game_lines("batting", team=team)
    pit = db.load_game_lines("pitching", team=team)
    out = []
    for _, r in g.iterrows():
        gid = r["game_idx"]
        opp = r["team2"] if r["team1"] == team else r["team1"]
        f, a = (r["score1"], r["score2"]) if r["team1"] == team else (r["score2"], r["score1"])
        f, a = f or 0, a or 0
        res = "승" if f > a else ("패" if f < a else "무")
        lineup = []
        if not bat.empty:
            gb = bat[bat["game_idx"] == gid].sort_values("타순")
            lineup = [{"타순": b["타순"], "포지션": b["포지션"], "선수명": b["선수명"]}
                      for _, b in gb.iterrows()]
        starter = None
        if not pit.empty:
            ps = pit[(pit["game_idx"] == gid) & (pit["선발"] == True)]  # noqa: E712
            if not ps.empty:
                starter = ps.iloc[0]["선수명"]
        out.append({"game_idx": gid, "date": r["date"], "상대": opp,
                    "스코어": f"{f}:{a}", "결과": res, "선발투수": starter, "타순": lineup})
    return out


def _records_vs(team: str, g: pd.DataFrame) -> dict:
    """team이 상대한 각 팀별 [승,패,득,실]."""
    rec: dict[str, list[int]] = {}
    for _, r in g.iterrows():
        if team not in (r.get("team1"), r.get("team2")):
            continue
        opp = r["team2"] if r["team1"] == team else r["team1"]
        f, a = (r["score1"], r["score2"]) if r["team1"] == team else (r["score2"], r["score1"])
        d = rec.setdefault(opp, [0, 0, 0, 0])
        d[2] += f or 0; d[3] += a or 0
        if (f or 0) > (a or 0): d[0] += 1
        elif (f or 0) < (a or 0): d[1] += 1
    return rec


def common_opponents(team: str, vs: str = OUR_TEAM, season=None, jo=None) -> pd.DataFrame:
    """두 팀이 공통으로 만난 상대들에 대한 각자 전적 비교(맞대결 없을 때의 대체 신호)."""
    g = games_df(season=season, jo=jo)
    ra, rb = _records_vs(vs, g), _records_vs(team, g)
    common = sorted(set(ra) & set(rb) - {team, vs})
    rows = []
    for opp in common:
        a, b = ra[opp], rb[opp]
        rows.append({"공통상대": opp,
                     f"{vs}": f"{a[0]}승{a[1]}패 ({a[2]-a[3]:+d})",
                     f"{team}": f"{b[0]}승{b[1]}패 ({b[2]-b[3]:+d})"})
    return pd.DataFrame(rows)


def career_tables(career: dict):
    """crawl_player_career 결과 → (batting_df, pitching_df). 각 시즌행 + '통산' 합계행.
    합계의 비율은 카운팅 합으로 재계산(타율=Σ안타/Σ타수 등). ERA는 사회인 7이닝 기준."""
    seasons = career.get("seasons", [])
    g = lambda d, k: (d.get(k) if isinstance(d.get(k), (int, float)) else 0) or 0

    brows, bs = [], {k: 0 for k in ["경기수", "타석", "타수", "총안타", "루타", "홈런", "타점", "볼넷", "사구", "삼진", "득점", "도루"]}
    for s in seasons:
        b = s.get("batting") or {}
        if not (b.get("경기수") or 0):
            continue
        PA = g(b, "타석")
        brows.append({"시즌": s["season"], "경기": b.get("경기수"), "타율": b.get("타율"),
                      "출루율": b.get("출루율"), "장타율": b.get("장타율"), "OPS": b.get("OPS"),
                      "타석": PA, "안타": b.get("총안타"), "홈런": b.get("홈런"), "타점": b.get("타점"),
                      "볼넷": b.get("볼넷"), "삼진": b.get("삼진"),
                      "BB%": round(g(b, "볼넷") / PA * 100, 1) if PA else None,
                      "K%": round(g(b, "삼진") / PA * 100, 1) if PA else None})
        for k in bs:
            bs[k] += g(b, k)
    if brows:
        AB, PA, H, TB = bs["타수"], bs["타석"], bs["총안타"], bs["루타"]
        OB = H + bs["볼넷"] + bs["사구"]
        obp = OB / PA if PA else 0
        slg = TB / AB if AB else 0
        brows.append({"시즌": "통산", "경기": bs["경기수"],
                      "타율": round(H / AB, 3) if AB else None, "출루율": round(obp, 3),
                      "장타율": round(slg, 3), "OPS": round(obp + slg, 3), "타석": PA, "안타": H,
                      "홈런": bs["홈런"], "타점": bs["타점"], "볼넷": bs["볼넷"], "삼진": bs["삼진"],
                      "BB%": round(bs["볼넷"] / PA * 100, 1) if PA else None,
                      "K%": round(bs["삼진"] / PA * 100, 1) if PA else None})

    prows, ps = [], {k: 0 for k in ["경기수", "타자", "피안타", "볼넷", "탈삼진", "실점", "자책점"]}
    ip_total = 0.0
    for s in seasons:
        p = s.get("pitching") or {}
        if not (p.get("경기수") or 0):
            continue
        prows.append({"시즌": s["season"], "경기": p.get("경기수"), "방어율": p.get("방어율"),
                      "이닝": p.get("이닝"), "탈삼진": p.get("탈삼진"), "볼넷": p.get("볼넷"),
                      "자책점": p.get("자책점"), "WHIP": p.get("WHIP")})
        ip_total += innings_to_float(p.get("이닝"))
        for k in ps:
            ps[k] += g(p, k)
    if prows:
        prows.append({"시즌": "통산", "경기": ps["경기수"],
                      "방어율": round(ps["자책점"] / ip_total * 7, 2) if ip_total else None,
                      "이닝": round(ip_total, 2), "탈삼진": ps["탈삼진"], "볼넷": ps["볼넷"],
                      "자책점": ps["자책점"],
                      "WHIP": round((ps["피안타"] + ps["볼넷"]) / ip_total, 2) if ip_total else None})
    return pd.DataFrame(brows), pd.DataFrame(prows)


def team_aggregate(team: str, season=None, jo=None) -> dict:
    """팀 단위 타격 집계 + 득실 — '이 팀이 무엇으로 굴러가는지' 판단용."""
    b = batters(team, season=season, jo=jo)
    num = lambda c: pd.to_numeric(b.get(c, 0), errors="coerce").fillna(0)
    AB, PA, H, BB, HBP, K, TB, SB, HR = (num("타수").sum(), num("타석").sum(),
        num("총안타").sum(), num("볼넷").sum(), num("사구").sum(), num("삼진").sum(),
        num("루타").sum(), num("도루").sum(), num("홈런").sum())
    OB = H + BB + HBP
    rec = team_record(team, season=season, jo=jo)
    G = max(rec["승"] + rec["패"] + rec["무"], 1)
    return {
        "팀": team, "경기": G,
        "타율": round(H / AB, 3) if AB else 0, "출루율": round(OB / PA, 3) if PA else 0,
        "장타율": round(TB / AB, 3) if AB else 0,
        "OPS": round((OB / PA if PA else 0) + (TB / AB if AB else 0), 3),
        "BB%": round(BB / PA * 100, 1) if PA else 0, "K%": round(K / PA * 100, 1) if PA else 0,
        "ISO": round((TB - H) / AB, 3) if AB else 0,
        "홈런": int(HR), "도루": int(SB), "도루/경기": round(SB / G, 1),
        "득점/경기": round(rec["득점"] / G, 1), "실점/경기": round(rec["실점"] / G, 1),
    }


def league_leaders(category: str = "OPS", *, top: int = 10, min_pa: int = 10,
                   min_ip: float = 3, season=None, jo=None) -> pd.DataFrame:
    """조 전체 리더보드. 타격은 shrinkage(OPS_adj 등) 기준, 투수는 ERA/WHIP/K."""
    cat = category.upper()
    pitch = {"ERA": "방어율", "방어율": "방어율", "WHIP": "WHIP", "K": "탈삼진", "탈삼진": "탈삼진"}
    if cat in pitch:
        p = pitchers(season=season, jo=jo)
        if p.empty:
            return p
        p = p.assign(이닝수=p["이닝"].map(innings_to_float))
        p = p[p["이닝수"] >= min_ip]
        col = pitch[cat]
        asc = col in ("방어율", "WHIP")
        p = p.assign(_s=pd.to_numeric(p[col], errors="coerce")).dropna(subset=["_s"]).sort_values("_s", ascending=asc)
        cols = [c for c in ["선수명", "팀명", "방어율", "WHIP", "이닝", "탈삼진", "볼넷", "피안타율"] if c in p.columns]
        return p[cols].head(top).reset_index(drop=True)
    # 타격 — raw 기준 (소표본 허수는 min_pa로 거른다; 보정은 regressed_batting 도구로)
    b = batters(season=season, jo=jo)
    if b.empty:
        return b
    b = b[pd.to_numeric(b["타석"], errors="coerce").fillna(0) >= min_pa]
    keymap = {"OPS": "OPS", "AVG": "타율", "OBP": "출루율", "타율": "타율", "출루율": "출루율",
              "RBI": "타점", "타점": "타점", "SB": "도루", "도루": "도루", "HR": "홈런", "홈런": "홈런"}
    key = keymap.get(cat, "OPS")
    b = b.assign(_s=pd.to_numeric(b[key], errors="coerce")).dropna(subset=["_s"]).sort_values("_s", ascending=False)
    cols = [c for c in ["선수명", "팀명", "OPS", "타율", "출루율", "장타율", "타석", "홈런", "타점", "도루"] if c in b.columns]
    return b[cols].head(top).reset_index(drop=True)


def opponent_pack(opponent: str, *, season=None, jo=None) -> dict:
    """상대팀 스카우팅용 데이터 묶음 (Claude 전략 입력으로 사용)."""
    return {
        "상대팀": opponent,
        "순위표": standings(season=season, jo=jo).to_dict("records"),
        "상대_전적": team_record(opponent, season=season, jo=jo),
        "상대_타자": batters(opponent, season=season, jo=jo).to_dict("records"),
        "상대_투수": pitchers(opponent, season=season, jo=jo).to_dict("records"),
        "맞대결": head_to_head(OUR_TEAM, opponent, season=season, jo=jo).to_dict("records"),
    }
