"""OpenDART REST 클라이언트 (F3·F4). 표준 라이브러리 `urllib`만 쓴다 (N4).

MCP 경로(`dart_mcp.py`)가 죽었을 때의 **폴백**이자, MCP에 도구가 없는 끝점
(`fnlttMultiAcnt.json` — 다중회사 재무, M2)의 **유일한 경로**다.

**키는 URL 쿼리에 실린다** (`crtfc_key=…`). 예외 메시지나 로그에 URL이 통째로 들어가기 쉬우므로,
규율이 아니라 **장치**로 막는다 — `DartError`를 만드는 것만으로 마스킹된다 (N10).
부르는 쪽이 `mask()`를 잊어도 새지 않는다.

| 상태 | 뜻 | 처리 |
|------|-----|------|
| `000` | 정상 | 항목 파싱 |
| `013` | 조회 결과 없음 | **공시 0건 — 오류가 아니다.** 흔한 정상 상태다 |
| `020` | 요청 한도 초과(일 20,000) | 1회 재시도 → `DartRateLimitError` |
| `800` | 시스템 점검 (HTTP 200) | 1회 재시도 → `DartMaintenanceError` |
| `010` `011` 등 | 키 없음·만료 | **재시도 없이** — 다시 불러도 같다 |
| HTTP 5xx · 타임아웃 · 연결 오류 | 일시 장애 | 1회 재시도 → `DartError` |

재시도 판단은 **응답 본문**으로 한다. 경로 이름으로 하면 새 끝점이 조용히 재시도에서 빠진다
(선행이 `list.json`으로만 걸어 두었다).

파싱과 오류 본문 판별은 순수 모듈(`corp.py`·`models.py`)에 있다.
여기는 바이트를 받아 오는 일만 한다.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from time import sleep
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from verify import config
from verify.models import Disclosure

BASE = "https://opendart.fss.or.kr/api"
TIMEOUT = 20.0
PAGE_COUNT = 100
RETRY_WAIT = 2.0  # 1회 재시도 전 대기(초). 020이면 잠깐 쉬는 게 맞다

STATUS_OK = "000"
STATUS_NO_DATA = "013"
STATUS_RATE_LIMIT = "020"
STATUS_MAINTENANCE = "800"
RETRYABLE = (STATUS_RATE_LIMIT, STATUS_MAINTENANCE)


def mask(text: str, secret: str) -> str:
    """문자열에서 비밀값을 가린다. 빈 secret은 아무것도 바꾸지 않는다."""
    return config.mask(text, secret)


class DartError(RuntimeError):
    """OpenDART 호출 실패.

    **메시지는 생성 시점에 마스킹된다** — 키를 그대로 넘겨도 밖으로 나가지 않는다.
    `config.optional`로 읽으므로 키가 없는 환경에서도 안전하다.
    """

    def __init__(self, message: str, status: str | None = None) -> None:
        super().__init__(mask(message, config.optional("DART_API_KEY")))
        self.status = status


class DartRateLimitError(DartError):
    """`020` — 일 한도(20,000) 초과."""


class DartMaintenanceError(DartError):
    """`800` — 시스템 점검. HTTP 200으로 온다."""


def _key() -> str:
    return config.require("DART_API_KEY")


def _get(path: str, params: dict[str, str], key: str) -> bytes:
    """GET 1회. 네트워크 오류는 `DartError`로 바꾼다 (메시지는 자동 마스킹)."""
    url = f"{BASE}/{path}?" + urllib.parse.urlencode({"crtfc_key": key, **params})
    try:
        with urlopen(Request(url), timeout=TIMEOUT) as resp:
            return bytes(resp.read())
    except HTTPError as exc:
        raise DartError(f"{path} HTTP {exc.code} {exc.reason}") from None
    except URLError as exc:
        raise DartError(f"{path} 연결 실패: {exc.reason}") from None
    except OSError as exc:  # TimeoutError 등
        raise DartError(f"{path} {exc}") from None


def _status_of(data: bytes) -> str:
    """응답 본문의 `status`. JSON이 아니면(zip·XML) 빈 문자열 — 재시도 판단에서 빠진다."""
    try:
        payload = json.loads(data)
    except ValueError:
        return ""
    return str(payload.get("status", "")) if isinstance(payload, dict) else ""


def _fetch(path: str, params: dict[str, str], key: str) -> bytes:
    """일시 장애(네트워크·5xx·`020`·`800`)는 1회만 재시도한다."""
    try:
        data = _get(path, params, key)
    except DartError as exc:
        print(f"[dart] {exc} — {RETRY_WAIT}초 후 재시도")
        sleep(RETRY_WAIT)
        return _get(path, params, key)
    status = _status_of(data)
    if status in RETRYABLE:
        print(f"[dart] {path} status={status} — {RETRY_WAIT}초 후 재시도")
        sleep(RETRY_WAIT)
        return _get(path, params, key)
    return data


def _raise_for_status(path: str, payload: dict[str, Any]) -> None:
    """`000`·`013`이 아니면 상태에 맞는 예외를 올린다. 메시지 마스킹은 예외가 알아서 한다."""
    status = str(payload.get("status", ""))
    message = str(payload.get("message", ""))
    if status in (STATUS_OK, STATUS_NO_DATA):
        return
    if status == STATUS_RATE_LIMIT:
        raise DartRateLimitError(f"{path} status=020 한도 초과: {message}", status)
    if status == STATUS_MAINTENANCE:
        raise DartMaintenanceError(f"{path} status=800 점검 중: {message}", status)
    raise DartError(f"{path} status={status}: {message}", status)


def get_json(path: str, params: dict[str, str]) -> dict[str, Any]:
    """JSON 끝점 하나를 부르고 본문을 돌려준다. `013`도 그대로 돌려준다(0건은 오류가 아니다).

    Args:
        path: `list.json` 같은 끝점 이름.
        params: 인증키를 뺀 질의 인자.

    Returns:
        응답 본문 사전. `status`가 들어 있다.

    Raises:
        DartRateLimitError: `020` (1회 재시도 후).
        DartMaintenanceError: `800` (1회 재시도 후).
        DartError: 그 밖의 오류 상태·HTTP 오류·네트워크 오류. **메시지에 키가 없다.**
    """
    data = _fetch(path, params, _key())
    try:
        payload = json.loads(data)
    except ValueError:
        raise DartError(f"{path} 응답이 JSON이 아니다: {data[:120]!r}") from None
    if not isinstance(payload, dict):
        raise DartError(f"{path} 응답이 사전이 아니다: {type(payload).__name__}")
    _raise_for_status(path, payload)
    return payload


def fetch_corp_codes() -> bytes:
    """`corpCode.xml` 응답 바이트 (zip). 파싱·오류 본문 판별은 `corp.parse_corp_codes()`."""
    return _fetch("corpCode.xml", {}, _key())


def fetch_disclosures(corp_code: str, bgn: date, end: date) -> list[Disclosure]:
    """한 회사의 기간 내 공시 목록 (F4). **`013`이면 빈 목록** — 오류가 아니다.

    Args:
        corp_code: DART 고유번호 8자리.
        bgn: 조회 시작일.
        end: 조회 종료일.

    Returns:
        응답 순서 그대로 (DART는 최신순). `PAGE_COUNT`를 넘으면 로그로 알리고 그만큼만 돌려준다.

    Raises:
        DartRateLimitError: `020` (1회 재시도 후).
        DartMaintenanceError: `800` (1회 재시도 후).
        DartError: 그 밖의 오류 상태·HTTP 오류·네트워크 오류. 메시지에 키가 없다.
    """
    payload = get_json(
        "list.json",
        {
            "corp_code": corp_code,
            "bgn_de": bgn.strftime("%Y%m%d"),
            "end_de": end.strftime("%Y%m%d"),
            "page_count": str(PAGE_COUNT),
        },
    )
    # `013`은 여기까지 그냥 흘러온다 — `list` 키가 아예 없고 `.get("list", [])`가 빈 목록을 준다.
    # 따로 분기하면 관측 차이가 없는 죽은 가지가 된다 (변이 검사로 확인, 2026-09-05).
    total = int(payload.get("total_count", 0) or 0)
    if total > PAGE_COUNT:
        print(f"[dart] {corp_code} 공시 {total}건 — {PAGE_COUNT}건만 가져왔다")
    # 매핑은 models 한 곳 — MCP 경로(dart_mcp.py)와 같은 함수를 쓴다
    return [Disclosure.from_dart_item(x) for x in payload.get("list", [])]
