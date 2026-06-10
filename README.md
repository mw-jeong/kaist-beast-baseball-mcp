# kaist-beast-mcp ⚾ — 사회인야구 전력분석 (게임원 × Claude)

[게임원(gameone.kr)](https://www.gameone.kr) 의 우리 리그 데이터를 자동 수집해서,
**Claude Desktop에서 자연어로** 팀 분석·라인업·상대 전략을 받아보는 MCP 서버입니다.

> 예) Claude Desktop에 *"리드오프 상대 전략 짜줘"* / *"우리 팀 라인업 추천해줘"* /
> *"최신 데이터로 B조 순위 보여줘"* 라고 말하면, Claude가 알아서 데이터를 불러와 분석합니다.

- 리그: 사이언스리그 B조 (`lig_idx=85`)
- 우리 팀: **The Beasts** (`club_idx=22098`)

---

## 🧠 어떻게 동작하나
```
게임원(로그인) ──크롤링──▶ 파싱 ──▶ SQLite 저장
                                      │
                       MCP 서버(데이터·관리 도구 21개)
                                      │  stdio
                              Claude Desktop  ← 여기서 자연어로 분석 요청
```
- 데이터 수집/정리는 이 프로그램이, **분석(라인업·전략)은 Claude Desktop이** 직접 합니다.
- 그래서 **별도 API 키가 필요 없습니다** (Claude Desktop 구독으로 동작).

---

## ✅ 사전 요구사항
1. **macOS** (Windows도 가능, 경로만 다름) + **Claude Desktop** 설치
2. **Python 3.10 이상** (아래 설치 단계에서 `uv`로 3.12 자동 설치 가능)
3. **본인의 게임원 계정** — 우리 리그(사이언스리그)에 **리그 회원으로 가입**되어 있어야 함
   (기록/일정은 비회원에겐 안 보입니다. 각자 자기 계정을 씁니다.)

---

## 📦 설치

### 1) 클론
```bash
git clone https://github.com/mw-jeong/kaist-beast-baseball-mcp.git
cd kaist-beast-baseball-mcp
```

### 2) 가상환경 + 의존성  ―  `uv` 권장 (빠름)
```bash
# uv 없으면 먼저 설치:  curl -LsSf https://astral.sh/uv/install.sh | sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```
<details><summary>uv 없이 표준 파이썬으로 (Python 3.10+ 필요)</summary>

```bash
python3.12 -m venv .venv          # 또는 python3.11
.venv/bin/pip install -r requirements.txt
```
</details>

### 3) 게임원 계정 입력 (`.env`)
```bash
cp .env.example .env
```
`.env` 파일을 열어 **본인** 게임원 아이디/비밀번호를 채웁니다:
```
GAMEONE_USER_ID=본인_아이디
GAMEONE_PASSWD=본인_비밀번호
```
> 🔒 `.env` 는 깃에 올라가지 않습니다(`.gitignore`). **절대 공유하지 마세요. 각자 자기 계정.**

### 4) 로그인 확인
```bash
.venv/bin/python -m beast.cli login-test
# → ✓ 로그인 성공 ... 이 나오면 OK
```

### 5) Claude Desktop 연동 (자동)
```bash
.venv/bin/python -m beast.cli setup-desktop
```
이 명령이 **본인 PC 경로에 맞게** Claude Desktop 설정을 자동 등록합니다.
그 다음 **Claude Desktop을 완전히 종료 후 다시 실행**하세요.

> Windows는 `.venv\Scripts\python.exe -m beast.cli ...` 형태로 실행하세요.
> setup-desktop이 OS별 설정 경로(`%APPDATA%\Claude\...`)도 자동 처리합니다.

---

## 🚀 사용법 (Claude Desktop)
재시작 후, Claude Desktop 채팅에 자연어로:
- *"B조 순위 보여줘"*
- *"우리 팀(The Beasts) 타자·투수 기록 정리해줘"*
- *"대전 리드오프 상대 전략이랑 라인업 짜줘"*
- *"중앙 비글스 야구단 명단 가져와"*
- *"최신 데이터로 새로고침해줘"* (경기 후 기록 갱신)

Claude가 아래 도구들을 알아서 호출합니다.

### MCP 도구 (21개)
| 분류 | 도구 | 설명 |
|---|---|---|
| 수집/상태 | `refresh_data` · `data_status` | 최신 데이터(기록+박스스코어) 재수집 / 신선도 확인 |
| 기록 | `standings` · `list_teams` | B조 순위표 / 팀 목록 |
| 타격·투구 | `team_batters` · `team_pitchers` | **raw** 기록(OPS순, 규정 표시) / 방어율순 |
| 보정 | `regressed_batting` | (필요시) 소표본 empirical Bayes shrinkage — `OPS_adj` 등 |
| 요약 | `team_summary` · `league_leaders` | 팀 정체성 한 줄 / 조 리더보드(raw, min 타석) |
| **게임 로그** | `game_log` · `recent_form` · `pitcher_usage` | **실제 타순·선발** / 최근 폼 / 투수 부하·로테이션 |
| 선수 다년 | `player_gamelog` · `player_career` | 경기별 raw(사이언스리그 한정) / 시즌별+통산(⚠️전체 리그 합산) |
| 상대 | `scout_report` · `head_to_head` · `common_opponents` | 종합(sections 선택) / 맞대결(없으면 공통상대 대체) / 스케줄 강도 |
| 명단 | `our_roster` · `opponent_roster` | 우리/상대 등록 명단 |
| 관리(write) | `save_lineup` · `list_lineups` | 짜낸 라인업 저장·재조회(휘발 방지) |

> 설계: **데이터 도구는 게임원 raw 그대로** 반환한다. 소표본 보정(1타석 OPS 2.0 같은 허수를
> 리그평균으로 수축)이 필요할 때만 `regressed_batting`을 명시적으로 호출 — 보정 여부는 에이전트가 판단.
> **경기별 박스스코어** 수집으로 실제 타순·선발 로테이션·최근 폼 제공.

---

## 🛠 (선택) CLI 직접 사용
```bash
.venv/bin/python -m beast.cli crawl --save                 # 수집+저장
.venv/bin/python -m beast.cli export --opponent "대전 리드오프"  # 분석용 Markdown 리포트 생성
```

---

## 🧯 트러블슈팅
- **Claude Desktop에 beast가 안 보임** → 완전 종료 후 재실행. 그래도 안 되면
  `setup-desktop` 다시 실행 + `login-test`로 계정 확인. Claude Desktop > Settings > Developer에서 서버 상태 확인.
- **`DH_KEY_TOO_SMALL` SSL 오류** → 게임원 서버의 약한 암호 설정 때문. 코드에 우회 어댑터가 포함돼 있으니
  최신 코드인지 확인(`git pull`).
- **`mcp` 설치 실패 / 버전 오류** → Python이 3.10 미만입니다. 3.12로 venv를 다시 만드세요(설치 2단계).
- **로그인 실패** → 아이디/비번 확인, 그리고 그 계정이 사이언스리그 **리그 회원**인지 확인.

---

## 🗂 프로젝트 구조
```
beast/
  config.py          설정(.env, 리그/팀 식별자, 조 bujo_idx)
  crawler/           로그인·수집·파싱 (session/endpoints/crawl/parse)
  storage/db.py      SQLite 적재(스냅샷 시계열)
  analysis/          지표·리포트 (stats, report)
  mcp_server.py      ★ MCP 서버 (Claude Desktop 연동)
  desktop.py         Claude Desktop 설정 자동 구성
  cli.py             CLI
data/                수집 데이터(.gitignore)
```

## ⚙️ 다른 팀/리그로 바꾸려면
`.env` 에서 식별자를 덮어쓰면 됩니다(우리 팀원은 그대로 두세요):
`LIG_IDX`, `CLUB_IDX`, `OUR_JO`(A/B), `OUR_BUJO_IDX`(조 코드), `CURRENT_SEASON`.

---

🔒 **보안:** `.env`(계정)와 `*.bak`, 수집 데이터는 커밋되지 않습니다. 계정은 절대 공유 금지.
🤖 Generated with [Claude Code](https://claude.com/claude-code)
