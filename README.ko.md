# kaist-beast-mcp — 사회인야구 전력분석·관리 (게임원 x Claude)

[English README](README.md)

[게임원(gameone.kr)](https://www.gameone.kr)의 우리 리그 데이터를 자동 수집해서,
**Claude에서 자연어로** 팀 분석·라인업·상대 스카우팅을 받는 MCP 서버입니다.

서버는 데이터 수집·정리만 하고 **분석은 Claude가** 하므로 별도 API 키가 필요 없습니다.

- 리그: 사이언스리그 B조 (`lig_idx=85`)
- 우리 팀: The Beasts (`club_idx=22098`)

## 동작 방식
```
게임원(로그인) --크롤링--> 파싱 --> SQLite
                                    |
                     MCP 서버 (데이터·관리 도구 22개)
                                    |  stdio(Desktop) / HTTP(claude.ai)
                            Claude  <- 자연어로 질문
```
이 프로그램은 데이터를 모으고, **분석(라인업·전략)은 Claude(데스크톱/웹)가** 직접 합니다.

## 사전 요구사항
1. **macOS 또는 Windows** + Claude (Claude Desktop 앱, 또는 Pro/Max/Team/Enterprise의 claude.ai 웹)
2. **Python 3.10 이상** (아래 설치에서 `uv`로 3.12 자동 설치 가능)
3. **본인 게임원 계정** — 사이언스리그에 리그 회원으로 가입되어 있어야 함
   (비회원에겐 기록이 안 보입니다. 각자 자기 계정을 씁니다.)

## 설치

### 1) 클론
```bash
git clone https://github.com/mw-jeong/kaist-beast-baseball-mcp.git
cd kaist-beast-baseball-mcp
```

### 2) 가상환경 + 의존성 (uv 권장)
uv 설치: macOS/Linux `curl -LsSf https://astral.sh/uv/install.sh | sh` ·
Windows(PowerShell) `irm https://astral.sh/uv/install.ps1 | iex`

macOS / Linux:
```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```
Windows (PowerShell):
```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```
<details><summary>uv 없이 (Python 3.10+ 설치 필요)</summary>

macOS/Linux: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`
Windows: `py -3.12 -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
</details>

### 3) 게임원 계정 (`.env`)
```bash
cp .env.example .env      # Windows: copy .env.example .env
```
`.env`를 열어 **본인** 게임원 아이디/비밀번호를 채웁니다:
```
GAMEONE_USER_ID=본인_아이디
GAMEONE_PASSWD=본인_비밀번호
```
`.env`는 깃에 올라가지 않습니다(gitignore). 공유 금지 — 각자 자기 계정.

### 4) 로그인 확인
```bash
.venv/bin/python -m beast.cli login-test          # Windows: .venv\Scripts\python -m beast.cli login-test
```

## Claude 연동

### 방법 A — Claude Desktop (로컬, 가장 간단, 권장)
```bash
.venv/bin/python -m beast.cli setup-desktop       # Windows: .venv\Scripts\python -m beast.cli setup-desktop
```
이 명령이 본인 PC 경로에 맞게 Claude Desktop 설정에 서버를 자동 등록합니다(macOS/Windows 경로 자동).
그 다음 **Claude Desktop을 완전히 종료 후 다시 실행**하세요.

### 방법 B — claude.ai 웹 (원격, 고급)
claude.ai는 **공인 인터넷에서 접근 가능한 원격 HTTP** MCP 서버만 받습니다 — 로컬 stdio 서버는
직접 추가할 수 없습니다. 따라서 이 서버를 HTTP 모드로 실행하고 외부에 노출해야 합니다:

1. HTTP 모드 실행: `.venv/bin/python -m beast.mcp_server --http --port 8765`
   (`http://127.0.0.1:8765/mcp` 제공)
2. 터널로 노출: 예) `cloudflared tunnel --url http://127.0.0.1:8765` 또는 `ngrok http 8765`
   -> 공개 `https://...` URL을 얻습니다.
3. claude.ai에서 **Customize > Connectors > Add custom connector**, `https://.../mcp` 입력.
   (Pro/Max; Team/Enterprise는 관리자가 Organization settings > Connectors에서 추가)

**웹 방식의 `.env` 채우기:** claude.ai를 써도 **서버는 여전히 본인 PC에서** 돌아가며 같은 로컬
`.env`(본인 게임원 계정)를 읽습니다 — 설치 3단계와 동일하게 채우면 됩니다. 계정 정보는
claude.ai/Anthropic으로 가지 않고, claude.ai는 터널을 통해 **본인의 로컬 서버에 접속만** 합니다.
웹으로 쓰려는 사람은 각자 자기 서버 + 터널 + 커넥터를 띄웁니다(서버는 그 `.env`의 계정으로 로그인).

> 보안: 서버가 본인 게임원 계정으로 로그인하므로, 공개 터널 URL을 아는 사람은 누구나 조회할 수 있습니다.
> URL을 비공개로 두고, 안 쓸 때 터널을 끄거나, 앞단에 인증을 두세요. 방법 A(Desktop)는 터널이 필요 없어
> 이 문제가 없습니다.

## 사용법
Claude에 자연어로 물어보세요:
- "B조 순위 보여줘"
- "The Beasts 타자·투수 정리해줘"
- "대전 리드오프 스카우팅하고 라인업·투수 운용 짜줘"
- "김현호 올해 경기별 보여줘" / "구전서 통산 추세 분석해줘"
- "최신 데이터로 새로고침해줘" (경기 후)

Claude가 아래 도구를 알아서 호출합니다. 팁: `guide`를 먼저 호출하면 해석상 함정
(소표본, ERA 7이닝 등)을 먼저 익힐 수 있습니다.

### MCP 도구 (22개)
| 분류 | 도구 | 설명 |
|---|---|---|
| 메타/수집 | `guide` · `refresh_data` · `data_status` | 도메인 가이드 / 재수집(기록+박스스코어) / 신선도 |
| 순위 | `standings` · `list_teams` | B조 순위표 / 팀 목록 |
| 타격·투구 | `team_batters` · `team_pitchers` | raw 기록(OPS순, 규정 표시) / 방어율순 |
| 보정 | `regressed_batting` | (필요시) 소표본 empirical Bayes 보정(`OPS_adj`) |
| 요약 | `team_summary` · `league_leaders` | 팀 정체성 한 줄 / 리더보드 |
| 게임 로그 | `game_log` · `recent_form` · `pitcher_usage` | 실제 타순·선발 / 최근 폼 / 투수 부하 |
| 선수(우리/상대) | `player_gamelog` · `player_career` | 경기별(현재시즌=박스스코어, 상대 포함) / 시즌+통산(전체 리그 합산) |
| 상대 | `scout_report` · `head_to_head` · `common_opponents` | 종합 스카우트 / 맞대결(없으면 공통상대) / 스케줄 강도 |
| 명단 | `our_roster` · `opponent_roster` | 등록 명단 |
| 관리 | `save_lineup` · `list_lineups` | 라인업 저장·재조회 |

설계: **데이터 도구는 게임원 raw 그대로** 반환하고, 보정(shrinkage)은 별도 옵트인 도구입니다.
경기별 박스스코어로 실제 타순·로테이션·최근 폼을 제공합니다. 전체 도메인 가이드는
[docs/GAMEONE.md](docs/GAMEONE.md) (또는 `guide` 도구) 참고.

## CLI (선택)
```bash
.venv/bin/python -m beast.cli crawl --save                 # 수집+저장(기록+박스스코어)
.venv/bin/python -m beast.cli export --opponent "대전 리드오프"  # 분석용 Markdown 리포트
```

## 트러블슈팅
- **Claude Desktop에 서버가 안 보임** -> 완전 종료 후 재실행, `setup-desktop` 재실행, `login-test` 확인.
  Claude Desktop > Settings > Developer에서 상태 확인.
- **`DH_KEY_TOO_SMALL` SSL 오류** -> 게임원의 약한 DH 키 때문. 우회 어댑터가 포함돼 있으니 최신 코드 확인(`git pull`).
- **`mcp` 설치/버전 오류** -> Python이 3.10 미만. 3.12로 venv 재생성(설치 2단계).
- **Windows에서 명령 인식 안 됨** -> `.venv/bin/python` 대신 `.venv\Scripts\python` 사용.
- **로그인 실패** -> 아이디/비번 확인, 그 계정이 사이언스리그 리그 회원인지 확인.

## 프로젝트 구조
```
beast/
  config.py        설정(.env, 리그/팀 식별자, 조 bujo_idx)
  crawler/         로그인·수집·파싱 (session/endpoints/crawl/parse)
  storage/db.py    SQLite(스냅샷 + 박스스코어 게임로그)
  analysis/        지표·리포트 (stats, report)
  mcp_server.py    MCP 서버 (Claude)
  desktop.py       Claude Desktop 설정 자동 구성
  cli.py           CLI
docs/GAMEONE.md    Claude용 도메인 가이드
data/              수집 데이터(gitignore)
```

## 다른 팀/리그로 바꾸려면
`.env`에서 식별자를 덮어쓰세요(우리 팀원은 그대로):
`LIG_IDX`, `CLUB_IDX`, `OUR_JO`(A/B), `OUR_BUJO_IDX`, `CURRENT_SEASON`.

## 보안
`.env`(계정)·`*.bak`·수집 데이터는 커밋되지 않습니다. 계정은 절대 공유하지 마세요.
