"""Claude Desktop MCP 설정 자동 구성.

팀원마다 클론 경로·OS가 달라 설정의 절대경로를 손으로 고치기 번거롭다.
이 모듈이 현재 파이썬(venv)·프로젝트 경로를 읽어 claude_desktop_config.json 에
beast 서버 항목을 안전하게 병합한다(기존 설정·다른 서버 보존, .bak 백업).
"""
from __future__ import annotations

import json
import platform
import shutil
import sys
from pathlib import Path

from . import config


def claude_config_path() -> Path:
    """OS별 Claude Desktop 설정 파일 경로."""
    sysname = platform.system()
    if sysname == "Darwin":
        return Path.home() / "Library/Application Support/Claude/claude_desktop_config.json"
    if sysname == "Windows":
        import os
        return Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config/Claude/claude_desktop_config.json"  # Linux(비공식)


def server_entry(python_exe: str | None = None) -> dict:
    return {
        "command": python_exe or sys.executable,        # 현재 venv 파이썬
        "args": ["-m", "beast.mcp_server"],
        "env": {"PYTHONPATH": str(config.PROJECT_ROOT)},  # 클론 위치 자동 반영
    }


def install() -> tuple[Path, dict]:
    """beast 항목을 Claude Desktop 설정에 병합. (cfg_path, entry) 반환."""
    cfg = claude_config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if cfg.exists():
        shutil.copy(str(cfg), str(cfg) + ".bak")
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    servers = data.setdefault("mcpServers", {})
    servers.pop("beast", None)            # 구버전 키 정리
    entry = server_entry()
    servers["kaist-beast-mcp"] = entry
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg, entry
