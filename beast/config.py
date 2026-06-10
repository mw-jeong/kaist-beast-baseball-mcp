"""전역 설정 — .env 로딩, 경로, 리그/팀 식별자, 엔드포인트 베이스."""
from __future__ import annotations

import os
import warnings
from pathlib import Path

# macOS 시스템 파이썬(LibreSSL) + urllib3 v2 조합의 무해한 경고 억제
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

from dotenv import load_dotenv

# ── 경로 ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "beast.db"

for _d in (DATA_DIR, RAW_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# .env 로드 (프로젝트 루트)
load_dotenv(PROJECT_ROOT / ".env")

# ── 게임원 식별자 ─────────────────────────────────────────────────────
BASE_URL = "https://www.gameone.kr"
LIG_IDX = int(os.getenv("LIG_IDX", "85"))        # 우리 리그 (사이언스리그)
CLUB_IDX = int(os.getenv("CLUB_IDX", "22098"))   # 우리 팀 (The Beasts)
# group_code = bucode(부 코드). 사이언스리그 = 25. (조 필터 아님!)
OUR_GROUP_CODE = int(os.getenv("OUR_GROUP_CODE", "25"))

# ── 조(A/B) 선택 — 매우 중요 ────────────────────────────────────────
# 기록/랭킹 페이지는 group_code로 조를 못 가른다. 대신 "세션 기본 부리그"를
# POST /league/exec/favorite (bujo_idx) 로 설정해야 해당 조 데이터가 나온다.
# 사이언스리그: A조 bujo_idx=45492, B조 bujo_idx=45493.
BUJO_IDX = {"A": 45492, "B": 45493}
OUR_JO = os.getenv("OUR_JO", "B")                # 우리 조 = B
OUR_BUJO_IDX = int(os.getenv("OUR_BUJO_IDX", str(BUJO_IDX.get(OUR_JO, 45493))))
# B조 팀 → club_idx (랭킹 페이지 링크에서 추출). 명단 수집·식별에 사용.
# 참고용 정적 맵 — 런타임에는 최신 랭킹 스냅샷의 club_idx를 우선 사용한다.
B_JO_CLUB_IDX = {
    "The Beasts": 22098,
    "대전 리드오프": 44714,
    "중앙 비글스 야구단": 1216,
    "KT&G Changers": 30136,
    "한국화학연구원 야구동호회": 26004,
    "K9": 16541,
    "한국조폐공사": 1224,
    "관세청 야구 동호회": 967,
    "표준 Tracerbulls": 7194,
    "KISTI FIGHTERS": 4890,
    "국가철도공단(KR마구조아)": 21762,
}
B_JO_TEAMS = list(B_JO_CLUB_IDX.keys())

# 시즌 (연도). 미지정 시 현재 시즌.
CURRENT_SEASON = int(os.getenv("CURRENT_SEASON", "2026"))

# ── 인증 ──────────────────────────────────────────────────────────────
GAMEONE_USER_ID = os.getenv("GAMEONE_USER_ID", "")
GAMEONE_PASSWD = os.getenv("GAMEONE_PASSWD", "")
# 분석은 Claude(Desktop/웹)가 직접 하므로 별도 LLM API 키는 필요 없다.

# ── HTTP ─────────────────────────────────────────────────────────────
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0 Safari/537.36"
)
REQUEST_TIMEOUT = 20
# 크롤링 예의: 요청 간 최소 간격(초)
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY", "0.8"))


def has_credentials() -> bool:
    return bool(GAMEONE_USER_ID and GAMEONE_PASSWD)
