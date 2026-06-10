"""게임원 인증 세션.

로그인 흐름 (역설계 결과):
  1) GET /member/login  → 숨은 CSRF 필드 login_token 추출 + PHPSESSID 쿠키 획득
  2) POST /member/exec/login  (login_token, user_id, passwd, ...) → 세션 인증
  3) 이후 같은 세션으로 content 엔드포인트 호출 (+ Referer 헤더)

비로그인 상태로 content를 치면 "회원님은 현재 손님(비로그인)입니다 …" 권한 안내가
내려오므로, 그 문구 유무로 로그인 성공/세션 유효성을 검증한다.
"""
from __future__ import annotations

import ssl
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from .. import config
from . import endpoints

GUEST_MARKERS = ("비로그인", "손님", "권한안내")


class _LegacyTLSAdapter(HTTPAdapter):
    """게임원 서버가 약한 DH 키를 써서 OpenSSL 3.x가 'DH_KEY_TOO_SMALL'로 거부한다.
    이 호스트에 한해 SSL 보안레벨을 1로 낮춘다(인증서 검증은 유지)."""

    def _ctx(self) -> ssl.SSLContext:
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT@SECLEVEL=1")
        return ctx

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = self._ctx()
        return super().proxy_manager_for(*args, **kwargs)


class LoginError(RuntimeError):
    pass


class GameOneSession:
    def __init__(self):
        self.s = requests.Session()
        # macOS fork-safety: requests의 시스템 프록시 자동조회(_scproxy→SystemConfiguration
        # →Network.framework)가 프레임워크 전역을 초기화하면, 이후 멀티스레드 상태에서
        # fork(subprocess) 시 자식이 atfork 핸들러에서 SIGSEGV로 죽는다(Streamlit 등).
        # trust_env=False로 프록시/환경 자동조회를 끊어 Network.framework 초기화를 회피.
        self.s.trust_env = False
        # 약한 DH 키 호스트 대응 (OpenSSL 3.x)
        self.s.mount("https://", _LegacyTLSAdapter())
        self.s.headers.update({
            "User-Agent": config.USER_AGENT,
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        self.logged_in = False
        self.current_bujo: int | None = None
        self._last_request = 0.0

    # ── 저수준 GET (요청 간격 + 인코딩 처리) ──────────────────────────
    def get_html(self, url: str, referer: str | None = None) -> str:
        delay = config.REQUEST_DELAY - (time.monotonic() - self._last_request)
        if delay > 0:
            time.sleep(delay)
        headers = {"Referer": referer} if referer else {}
        r = self.s.get(url, headers=headers, timeout=config.REQUEST_TIMEOUT)
        self._last_request = time.monotonic()
        r.raise_for_status()
        if not r.encoding or r.encoding.lower() == "iso-8859-1":
            r.encoding = r.apparent_encoding or "utf-8"
        return r.text

    # ── 로그인 ────────────────────────────────────────────────────────
    def _fetch_login_token(self) -> str:
        r = self.s.get(endpoints.LOGIN_PAGE_URL, timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        el = soup.find("input", attrs={"name": "login_token"})
        if not el or not el.get("value"):
            raise LoginError("login_token(CSRF)을 찾지 못했습니다. 로그인 페이지 구조가 바뀌었을 수 있습니다.")
        return el["value"]

    def login(self, user_id: str | None = None, passwd: str | None = None) -> bool:
        user_id = user_id or config.GAMEONE_USER_ID
        passwd = passwd or config.GAMEONE_PASSWD
        if not user_id or not passwd:
            raise LoginError(
                "계정 정보가 없습니다. .env 에 GAMEONE_USER_ID / GAMEONE_PASSWD 를 설정하세요."
            )
        token = self._fetch_login_token()
        payload = {
            "login_token": token,
            "return_url": "",
            "isPop": "",
            "user_id": user_id,
            "passwd": passwd,
            "save_id": "N",
        }
        r = self.s.post(
            endpoints.LOGIN_EXEC_URL, data=payload,
            headers={"Referer": endpoints.LOGIN_PAGE_URL},
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        self.logged_in = self.verify()
        if not self.logged_in:
            raise LoginError(
                "로그인 실패. 아이디/비밀번호를 확인하세요. "
                "(응답에 인증 세션이 잡히지 않았습니다.)"
            )
        return True

    def verify(self) -> bool:
        """우리 팀 등록현황 content를 떠서 권한안내(비로그인) 문구가 없으면 OK."""
        url = endpoints.state_content(
            "regist", group_code=config.OUR_GROUP_CODE, club_idx=config.CLUB_IDX
        )
        ref = endpoints.state_parent("regist")
        html = self.get_html(url, referer=ref)
        return not any(m in html for m in GUEST_MARKERS)

    # ── 조(A/B) 선택 ─────────────────────────────────────────────────
    def set_bujo(self, bujo_idx: int | None = None, lig_idx: int | None = None) -> bool:
        """세션의 '기본 부리그(조)'를 설정한다.

        기록/랭킹 content 엔드포인트는 group_code로 조를 못 가른다. 대신 이
        favorite 설정이 어느 조 데이터를 렌더할지 결정한다. B조 데이터를 받으려면
        호출 전에 반드시 OUR_BUJO_IDX(=B조)로 세팅해야 한다.
        """
        bujo_idx = bujo_idx if bujo_idx is not None else config.OUR_BUJO_IDX
        lig_idx = lig_idx or config.LIG_IDX
        r = self.s.post(
            f"{config.BASE_URL}/league/exec/favorite",
            data={"lig_idx": str(lig_idx), "bujo_idx": str(bujo_idx)},
            headers={"Referer": endpoints.record_parent("batter", lig_idx=lig_idx)},
            timeout=config.REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        self._last_request = time.monotonic()
        ok = '"result":true' in r.text
        if ok:
            self.current_bujo = bujo_idx
        return ok

    # ── 세션 보장 ────────────────────────────────────────────────────
    def ensure_login(self) -> "GameOneSession":
        if not self.logged_in:
            self.login()
        return self


def is_guest_page(html: str) -> bool:
    return any(m in html for m in GUEST_MARKERS)
