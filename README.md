# kaist-beast-mcp — Amateur Baseball Scouting & Management (gameone x Claude)

[한국어 README](README.ko.md)

An MCP server that auto-collects our league's data from [gameone.kr](https://www.gameone.kr)
and lets you analyze your team, build lineups, and scout opponents **in natural language inside Claude**.

The server only collects and organizes data; **Claude does the analysis**, so no extra API key is needed.

- League: Science League, group B (`lig_idx=85`)
- Our team: The Beasts (`club_idx=22098`)

## How it works
```
gameone (login) --crawl--> parse --> SQLite
                                       |
                        MCP server (22 data/management tools)
                                       |  stdio (Desktop) / HTTP (claude.ai)
                              Claude  <- ask in natural language
```
This program collects/organizes data; **Claude (Desktop or web) performs the reasoning** (lineups, strategy).

## Requirements
1. **macOS or Windows** with a terminal and **git** installed
   (macOS: git is offered by Xcode Command Line Tools on first use; Windows: install "Git for Windows").
2. **Claude** — the Claude Desktop app (recommended), or claude.ai web (Pro/Max/Team/Enterprise).
3. **Python 3.10+** — you do *not* need to install it yourself; the `uv` step below fetches 3.12.
4. **Your own gameone account** that is a registered league member of the Science League
   (records are invisible to non-members; each person uses their own account).

You do **not** need any LLM/Anthropic API key — Claude itself does the analysis.

## Install

### 1) Clone
```bash
git clone https://github.com/mw-jeong/kaist-beast-baseball-mcp.git
cd kaist-beast-baseball-mcp
```

### 2) Virtual env + dependencies (uv recommended)
Install uv if you don't have it: macOS/Linux `curl -LsSf https://astral.sh/uv/install.sh | sh` ·
Windows (PowerShell) `irm https://astral.sh/uv/install.ps1 | iex`

> After installing uv, **open a new terminal** (or run the PATH line the installer prints) so the
> `uv` command is found. `uv venv --python 3.12` will **download Python 3.12 automatically** if needed.
> You don't activate the venv — the commands below call `.venv/...` directly.

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
<details><summary>Without uv (needs Python 3.10+ installed)</summary>

macOS/Linux: `python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`
Windows: `py -3.12 -m venv .venv && .venv\Scripts\pip install -r requirements.txt`
</details>

### 3) gameone account (`.env`)
```bash
cp .env.example .env      # Windows: copy .env.example .env
```
Edit `.env` and fill in **your** gameone id/password:
```
GAMEONE_USER_ID=your_id
GAMEONE_PASSWD=your_password
```
`.env` is gitignored and never committed. Do not share it — each person uses their own account.

### 4) Verify login
```bash
.venv/bin/python -m beast.cli login-test          # Windows: .venv\Scripts\python -m beast.cli login-test
```
You should see "✓ 로그인 성공". **If it fails, fix `.env` (id/password) before continuing** — the
connect step won't work until login succeeds. Run all commands from the project folder.

## Connect to Claude

### Option A — Claude Desktop (local, simplest, recommended)
```bash
.venv/bin/python -m beast.cli setup-desktop       # Windows: .venv\Scripts\python -m beast.cli setup-desktop
```
This auto-registers the server in your Claude Desktop config (handles macOS and Windows paths).
Then **fully quit and reopen Claude Desktop** — on macOS closing the window isn't enough; use Cmd+Q
(or right-click the dock icon > Quit). On Windows, quit from the system tray.

Verify it loaded: in Claude Desktop, **Settings > Developer** should list `kaist-beast-mcp` as running,
and the chat's tools/connector menu should show its tools. (If not, see Troubleshooting.)

> If you later **move or rename the project folder**, the saved paths break — just re-run
> `setup-desktop` and restart Claude Desktop.

### Option B — claude.ai web (remote, advanced / optional)
Most people should use Option A. Use this only if you specifically want the web app. claude.ai only
accepts **remote HTTP** MCP servers reachable from the public internet — a local stdio server cannot be
added directly. You must keep this server running in HTTP mode on your machine and expose it via a tunnel:

1. Run in HTTP mode (leave it running): `.venv/bin/python -m beast.mcp_server --http --port 8765`
   (serves `http://127.0.0.1:8765/mcp`)
2. Install a tunnel tool and expose the port (in another terminal):
   - cloudflared — macOS `brew install cloudflared`, Windows `winget install Cloudflare.cloudflared`,
     then `cloudflared tunnel --url http://127.0.0.1:8765`
   - or ngrok (sign up, install) — `ngrok http 8765`
   You get a public `https://...` URL; the MCP endpoint is that URL + `/mcp`.
3. In claude.ai: **Customize > Connectors > Add custom connector**, paste `https://.../mcp`.
   (Pro/Max; Team/Enterprise admins add it under Organization settings > Connectors.)

**About `.env` for the web path:** the server still runs on **your own machine** and reads the same
local `.env` (your gameone account) — fill it exactly as in install step 3. claude.ai/Anthropic never
see your credentials; they only reach your locally-running server through the tunnel. Each person who
wants web access runs their own server + tunnel + connector (the server logs in as whoever's `.env` it is).

> Security: because the server logs in with your gameone credentials, a public tunnel URL means anyone
> who has that URL can query it. Keep the URL private, shut the tunnel down when unused, or put auth in
> front. Claude Desktop (Option A) needs no tunnel and avoids this entirely.

## Usage
Ask Claude in natural language, for example:
- "Show the group B standings"
- "Summarize The Beasts' batters and pitchers"
- "Scout 대전 리드오프 and suggest a lineup and pitching plan"
- "Show 김현호's game-by-game this season" / "Show 구전서's career trend"
- "Refresh the data" (after games)

Claude calls the tools below automatically. Tip: it can call `guide` first to learn the
domain caveats (small samples, 7-inning ERA, etc.).

> The **first question takes ~1 minute** — it triggers the initial data collection (records + box
> scores) and caches it. Later questions are instant; ask "refresh the data" after new games.

### MCP tools (22)
| Group | Tools | Notes |
|---|---|---|
| Meta/refresh | `guide` · `refresh_data` · `data_status` | domain guide / re-collect (records + box scores) / freshness |
| Standings | `standings` · `list_teams` | group B table / team list |
| Batting/Pitching | `team_batters` · `team_pitchers` | raw stats (OPS order, qualified flag) / by ERA |
| Adjustment | `regressed_batting` | empirical-Bayes shrinkage (`OPS_adj`) for small samples, on demand |
| Summary | `team_summary` · `league_leaders` | team identity line / leaderboards |
| Game logs | `game_log` · `recent_form` · `pitcher_usage` | actual lineups & starters / recent form / pitcher load |
| Player (us/opp) | `player_gamelog` · `player_career` | per-game (current season = box scores, incl. opponents) / season+career (all-league total) |
| Opponent | `scout_report` · `head_to_head` · `common_opponents` | one-stop scout / H2H (falls back to common opponents) / schedule strength |
| Rosters | `our_roster` · `opponent_roster` | registered rosters |
| Management | `save_lineup` · `list_lineups` | persist/recall lineups |

Design: **data tools return gameone's raw numbers**; correction (shrinkage) is a separate opt-in tool.
Per-game box scores enable real lineups, rotations, and recent form. See [docs/GAMEONE.md](docs/GAMEONE.md)
for the full domain guide (also returned by the `guide` tool).

## CLI (optional)
```bash
.venv/bin/python -m beast.cli crawl --save                 # collect + store (records + box scores)
.venv/bin/python -m beast.cli export --opponent "대전 리드오프"  # build a Markdown scouting report
```

## Troubleshooting
- **Server not showing in Claude Desktop** -> fully quit/reopen; re-run `setup-desktop`; verify `login-test`.
  Check Claude Desktop > Settings > Developer.
- **`DH_KEY_TOO_SMALL` SSL error** -> gameone uses a weak DH key; a workaround adapter is included.
  Make sure your code is up to date (`git pull`).
- **`mcp` install/version error** -> your Python is < 3.10. Recreate the venv with 3.12 (install step 2).
- **Windows: command not found** -> use `.venv\Scripts\python` instead of `.venv/bin/python`.
- **Login fails** -> check id/password and that the account is a Science League member.

## Project layout
```
beast/
  config.py        settings (.env, league/team ids, group bujo_idx)
  crawler/         login, fetch, parse (session/endpoints/crawl/parse)
  storage/db.py    SQLite (snapshots + box-score game logs)
  analysis/        metrics & reports (stats, report)
  mcp_server.py    MCP server (Claude)
  desktop.py       auto-config for Claude Desktop
  cli.py           CLI
docs/GAMEONE.md    domain guide for Claude
data/              collected data (gitignored)
```

## Use for another team/league
Override identifiers in `.env` (teammates leave these as-is):
`LIG_IDX`, `CLUB_IDX`, `OUR_JO` (A/B), `OUR_BUJO_IDX`, `CURRENT_SEASON`.

## Security
`.env` (credentials), `*.bak`, and collected data are never committed. Never share your account.
