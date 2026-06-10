# 게임원 / 사이언스리그 도메인 가이드 (Claude용)

이 문서는 이 MCP 서버가 다루는 데이터의 **배경·함정·해석법**을 Claude에게 알려준다.
(서버를 처음 쓰는 Claude는 게임원 내부 사정을 모르므로, 분석 전에 이 맥락을 참고하라.)

> EN summary at the bottom.

## 1. 무엇을 다루나
- 플랫폼: **게임원(gameone.kr)** — 한국 사회인야구 기록·리그 운영 사이트.
- 우리 리그: **대덕연구단지리그 = 사이언스리그**, `lig_idx=85`, **B조**.
- 우리 팀: **The Beasts** (`club_idx=22098`), KAIST 소속.
- 데이터는 **리그 회원 로그인** 상태에서만 보인다(서버가 처리).

## 2. B조 11개 팀
The Beasts(우리), 대전 리드오프, 중앙 비글스 야구단, KT&G Changers,
한국화학연구원 야구동호회, K9, 한국조폐공사, 관세청 야구 동호회,
표준 Tracerbulls, KISTI FIGHTERS, 국가철도공단(KR마구조아).

## 3. 데이터 해석 시 반드시 알아야 할 함정
1. **소표본(small sample)** — 시즌 초/사회인 특성상 많은 선수가 10~20타석. "1타석 OPS 2.0"
   같은 허수가 흔하다. `team_batters`는 raw이므로 **`규정` 컬럼·타석 수를 함께 보고 판단**하고,
   적은 표본끼리 공정 비교가 필요하면 `regressed_batting`(리그평균 수축 OPS_adj)을 쓴다.
2. **방어율(ERA)은 7이닝 기준** — 사회인 경기가 7이닝이라 게임원 ERA = 자책×7÷이닝.
   9이닝 환산이 아니다.
3. **상대팀 등번호는 비공개(0으로 표기)** — 타팀 선수 등번호 0은 "없음/비공개"이지 실제 0번이 아니다.
4. **`player_career`는 전체 리그·팀 합산** — 그 선수가 뛴 모든 리그(사이언스리그 + 타 리그)와
   모든 팀의 공식경기 통산이다. **사이언스리그 한정이 아니다.** 우리 리그 단위 성적은
   `player_gamelog`(사이언스리그 스코프)를 봐라.
5. **사이언스리그는 시즌마다 다른 lig_idx** — 한 선수의 다년 사이언스리그 기록은 `lig_idx=85`
   한 곳에 다 있지 않다(과거 시즌은 별도 인스턴스).
6. **투구수(pitch count)는 대부분 0/미기록** — 사회인 기록원이 잘 안 적는다. 투수 부하는
   투구수 대신 **이닝·상대타자수·등판 간격**(`pitcher_usage`)으로 추정하라.
7. **타팀 선수의 과거 시즌 '경기별'은 게임원이 비공개** — 통산(sum)은 공개. 현재 시즌 상대 선수
   경기별은 우리가 수집한 박스스코어로 제공된다.

## 4. 이 리그의 야구 성격 (분석 시 고려)
- **스몰볼·발야구 경향** — 홈런이 적고 도루·단타·출루로 득점하는 팀이 많다(예: 대전 리드오프).
  팀 정체성은 `team_summary`의 ISO·도루/경기·BB%로 판단.
- **투수 뎁스 얕음** — 보통 선발 1명 + 짧은 계투. 상대 선발 로테이션은 `pitcher_usage`(선발 수)로 본다.
- **수비 변수 큼** — 박스스코어 타석결과에 실책(유실/좌실 등)이 잦다.
- 7이닝 경기, 더블헤더(체력), 우천·인원 변수.

## 5. 질문 → 도구 매핑 (어떤 걸 부를지)
- "B조 순위/리더" → `standings`, `league_leaders`
- "OO팀 분석/전략" → `scout_report`(한 번에 종합), 보조로 `team_summary`/`team_batters`/`team_pitchers`
- "OO팀 실제 타순·선발 로테이션" → `game_log`, `pitcher_usage`
- "최근 폼" → `recent_form`
- "우리/상대 **선수**의 경기별" → `player_gamelog(name, team)` (현재 시즌, 사이언스리그)
- "선수 다년 추세·통산" → `player_career(name, team)` (단 전체 리그 합산임을 명시)
- "맞대결 없음 → 강도 비교" → `head_to_head`(공통상대 자동 대체), `common_opponents`
- "소표본 보정 비교" → `regressed_batting`
- "라인업 저장/재조회" → `save_lineup`, `list_lineups`
- "최신화" → `refresh_data` (경기 후), 신선도 `data_status`

## 6. 분석 톤
데이터의 숫자를 인용해 구체적으로. 표본이 작으면 신뢰도를 함께 밝혀라. 막연한 일반론 금지.

---

## EN summary
This MCP server exposes **gameone.kr** amateur-baseball data for our league
(Science League / 대덕연구단지리그, `lig_idx=85`, group **B**; our team **The Beasts**, `club_idx=22098`).
Key caveats when analyzing:
- **Small samples** are common (10–20 PA). `team_batters` is raw — judge with the `규정`(qualified) flag /
  PA count; use `regressed_batting` (empirical-Bayes shrinkage) to compare small samples fairly.
- **ERA is on a 7-inning basis** (amateur games are 7 innings), not 9.
- **Opponent jersey numbers show as 0** = hidden, not a real number.
- **`player_career` aggregates ALL leagues/teams** the player ever played (not Science-League-only);
  use `player_gamelog` for Science-League-scoped, game-by-game records.
- **Pitch counts are usually 0/unrecorded** — gauge pitcher load by innings/batters-faced/appearances.
- This league skews **small-ball / speed** (few HR, lots of steals); weigh ISO, SB/game, BB%.
Tool routing: standings/league_leaders, scout_report (one-stop opponent), game_log + pitcher_usage
(actual lineups/rotation), recent_form, player_gamelog/player_career (per-player), regressed_batting
(shrinkage), save_lineup/list_lineups, refresh_data/data_status.
