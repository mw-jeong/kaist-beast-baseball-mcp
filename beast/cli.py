"""Beast CLI.

사용 예:
  python -m beast.cli login-test          # 로그인만 검증
  python -m beast.cli snapshot            # 핵심 엔드포인트 인증 HTML 덤프 → data/raw/
  python -m beast.cli snapshot --season 2026
"""
from __future__ import annotations

import argparse
import json
import sys

from . import config
from .crawler.session import GameOneSession, LoginError


def _require_creds() -> None:
    if not config.has_credentials():
        print(
            "✗ 계정 정보가 없습니다.\n"
            "  1) cp .env.example .env\n"
            "  2) .env 에 GAMEONE_USER_ID / GAMEONE_PASSWD 입력\n",
            file=sys.stderr,
        )
        sys.exit(2)


def cmd_login_test(_args) -> None:
    _require_creds()
    sess = GameOneSession()
    try:
        sess.login()
    except LoginError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)
    print(f"✓ 로그인 성공 — 세션 인증됨 (user_id={config.GAMEONE_USER_ID})")
    print(f"  리그={config.LIG_IDX}  우리팀={config.CLUB_IDX}  우리조 group_code={config.OUR_GROUP_CODE}")


def cmd_snapshot(args) -> None:
    _require_creds()
    from .crawler.fetch import snapshot

    sess = GameOneSession()
    try:
        results = snapshot(sess, season=args.season)
    except LoginError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'대상':<20} {'상태':<6} {'크기':>8}  비고")
    print("-" * 60)
    for r in results:
        if not r["ok"]:
            print(f"{r['name']:<20} {'ERROR':<6} {'-':>8}  {r['error'][:30]}")
            continue
        flag = "GUEST🔒" if r["guest"] else "OK✓"
        print(f"{r['name']:<20} {flag:<6} {r['bytes']:>7}B  {r['saved']}")
    guests = [r for r in results if r.get("guest")]
    if guests:
        print(f"\n⚠ {len(guests)}개가 여전히 비로그인(GUEST) 상태입니다 — 권한/세션 확인 필요.")
    else:
        print(f"\n✓ 인증 데이터 수집 완료 → {config.RAW_DIR}")


def cmd_crawl(args) -> None:
    _require_creds()
    from .crawler.crawl import crawl
    from .storage import db

    sess = GameOneSession()
    try:
        data = crawl(sess, season=args.season, jo=args.jo)
    except LoginError as e:
        print(f"✗ {e}", file=sys.stderr)
        sys.exit(1)

    counts = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    print("수집 완료:")
    for k, n in counts.items():
        print(f"  {k:14} {n}")

    if args.save:
        sid = db.save_snapshot(data, note=args.note)
        print(f"\n✓ SQLite 저장됨 — snapshot #{sid} → {config.DB_PATH}")
        if not args.no_boxscore:
            from .crawler.crawl import crawl_boxscores
            box = crawl_boxscores(sess, season=args.season)
            print(f"✓ 박스스코어(게임 로그): {box}")
    else:
        print("\n(--save 미지정: 저장 안 함)")


def cmd_export(args) -> None:
    from .analysis import report
    md = report.strategy_report(opponent=args.opponent, season=args.season)
    out = args.out
    if out is None:
        safe = (args.opponent or "team").replace("/", "_").replace(" ", "_")
        out = str(config.DATA_DIR / f"report_{safe}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    print(md if args.stdout else f"✓ 리포트 저장 → {out}\n  (Claude에게 이 파일 내용을 물어보면 전략 분석 가능)")


def cmd_setup_desktop(_args) -> None:
    from . import desktop
    cfg, entry = desktop.install()
    print(f"✓ Claude Desktop 설정에 'kaist-beast-mcp' 서버 등록 완료\n  {cfg}\n")
    print(json.dumps({"mcpServers": {"beast": entry}}, ensure_ascii=False, indent=2))
    print("\n→ Claude Desktop을 완전히 종료했다가 다시 켜면 활성화됩니다.")
    if not config.has_credentials():
        print("⚠ 아직 .env에 게임원 계정이 없습니다 — 먼저 .env를 채우세요.")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(prog="beast", description="사회인야구 전력분석 플랫폼 CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("login-test", help="로그인 검증")

    sp = sub.add_parser("snapshot", help="핵심 엔드포인트 인증 HTML 덤프")
    sp.add_argument("--season", type=int, default=None, help="시즌(연도). 미지정 시 현재 시즌")

    cp = sub.add_parser("crawl", help="수집+파싱 (+--save 시 SQLite 저장)")
    cp.add_argument("--season", type=int, default=None, help="시즌(연도)")
    cp.add_argument("--jo", default=None, help="조 (A/B). 미지정 시 우리 조(B)")
    cp.add_argument("--save", action="store_true", help="SQLite에 스냅샷 저장")
    cp.add_argument("--note", default="", help="스냅샷 메모")
    cp.add_argument("--no-boxscore", action="store_true", help="박스스코어(게임 로그) 수집 건너뛰기")

    ep = sub.add_parser("export", help="전략용 Markdown 리포트 생성 (우리팀+투수+상대팀)")
    ep.add_argument("--opponent", default=None, help="상대팀 이름 (예: '대전 리드오프')")
    ep.add_argument("--season", type=int, default=None, help="시즌(연도)")
    ep.add_argument("--out", default=None, help="출력 파일 경로 (기본 data/report_*.md)")
    ep.add_argument("--stdout", action="store_true", help="파일 대신 화면 출력")

    sub.add_parser("setup-desktop", help="Claude Desktop에 beast MCP 서버 자동 등록")

    args = p.parse_args(argv)
    {"login-test": cmd_login_test, "snapshot": cmd_snapshot, "crawl": cmd_crawl,
     "export": cmd_export, "setup-desktop": cmd_setup_desktop}[args.cmd](args)


if __name__ == "__main__":
    main()
