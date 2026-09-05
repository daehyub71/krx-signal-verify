"""naver-search-mcp `search_news` → NewsItem (증거 세 갈래 중 「왜 그랬나」).

**전 종목에 붙인다.** 등급 `none`인 종목만 부르던 판은 가장 값진 뉴스를 놓쳤다 — 씨피시스템
CB의 자금 용도(「전액 제2공장 시설투자」)는 공시 제목에도 없고 규칙표에도 없다 (선행 실측).

응답 정제가 이 모듈의 일이다 (선행 실호출 확인):
- `title`·`description`에 검색어 강조 **`<b>` 태그**와 HTML 엔티티(`&amp;` `&quot;`)가 섞여 온다
- `pubDate`는 RFC 822 (`Fri, 28 Aug 2026 17:30:00 +0900`)
- `link`(네이버 뉴스)와 `originallink`(언론사 원문)가 따로 온다 — 둘 다 남긴다

**검색어는 종목명만, 정렬은 관련도순** (선행 A/B 실측). `{종목명} 주가` + 최신순은 제목
적합도 **64%**였다 — 매일 자동 생성되는 시세 기사가 상위를 채운다. 종목명만 + 관련도순이 **95%**.

동음이의는 검색어가 아니라 **결과**를 좁혀 막는다 (`about()`) — 검색어를 좁히면 정작 필요한
기사도 빠진다. 실수집에서 적합도 100%(52/52)가 나왔다.
"""

from __future__ import annotations

import html
import re
import threading
import time
from collections.abc import Sequence
from datetime import date
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from verify import mcpc
from verify.models import NewsItem

TIMEOUT = 20.0
DISPLAY = 5  # 종목당 최대 건수. 늘리면 요약 입력과 메일이 길어진다
SORT = "sim"  # 관련도순. 최신순은 매일 쏟아지는 자동 생성 시세 기사가 상위를 채운다

# 네이버는 **초당** 호출을 제한한다 — fan-out이 몰리면 HTTP 429가 난다 (선행 실측).
# 일일 한도(25,000)와는 다른 것이라 간격만 두면 해소된다.
MIN_INTERVAL = 0.35
RETRY_WAIT = 1.5
_pace = threading.Lock()
_last_call = 0.0

# 테스트가 갈아 끼울 수 있게 이름으로 잡아 둔다 (nodes.py와 같은 꼴).
_sleep = time.sleep
_now = time.monotonic

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# 한글 음절·자모. 이름 앞이 한글이면 더 긴 회사 이름의 일부다.
_HANGUL = re.compile(r"[가-힣ㄱ-ㅎㅏ-ㅣ]")


class _Server(Protocol):
    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = ...
    ) -> Any: ...


def clean_text(raw: str) -> str:
    """`<b>` 태그를 떼고 HTML 엔티티를 풀고 공백을 하나로 줄인다."""
    return _WS.sub(" ", html.unescape(_TAG.sub("", raw))).strip()


def parse_pub_date(raw: str) -> date | None:
    """RFC 822 날짜 → date. 파싱할 수 없으면 None — **기사를 버리지는 않는다.**"""
    if not raw.strip():
        return None
    try:
        return parsedate_to_datetime(raw).date()
    except (TypeError, ValueError):
        return None


def parse_news(payload: dict[str, Any]) -> list[NewsItem]:
    """`search_news` 응답 → NewsItem 목록. 제목이나 링크가 없는 항목은 버린다.

    `source`에는 **언론사 원문 링크**(`originallink`)를 넣는다 — 네이버 링크가 만료돼도
    원문은 남는다.
    """
    out: list[NewsItem] = []
    for raw in payload.get("items") or []:
        title, link = clean_text(str(raw.get("title", ""))), str(raw.get("link", "")).strip()
        if not title or not link:
            continue
        out.append(
            NewsItem(
                title=title,
                link=link,
                published=parse_pub_date(str(raw.get("pubDate", ""))),
                summary=clean_text(str(raw.get("description", ""))),
                source=str(raw.get("originallink", "")).strip(),
            )
        )
    return out


def query_for(company_name: str) -> str:
    """종목명 → 검색어. **종목명만** 쓴다.

    `주가`를 붙이던 판은 자동 생성 시세 기사(`… 주가, 8월 24일 장중 5,170원 2.78% 상승`)를
    끌어와 적합도가 64%였다. 종목명만 + 관련도순이 95%다 (선행 A/B 실측).
    """
    return company_name.strip()


def about(items: Sequence[NewsItem], company_name: str) -> list[NewsItem]:
    """제목에 종목명이 없는 기사를 버린다 (동음이의·계열사 차단).

    검색어를 좁히는 대신 **결과를 좁힌다** — 검색어를 좁히면 정작 필요한 기사도 빠진다.

    제목에서 공백을 지우고 비교한다: `한올바이오파마`가 `한올 바이오파마`로 쓰이기도 한다.

    Args:
        items: 파싱된 뉴스.
        company_name: 종목명. 비어 있으면 **아무것도 남기지 않는다** — 전부 통과시키면
            남의 회사 기사가 근거로 붙는다.

    Returns:
        제목이 그 종목을 가리키는 기사만. 0건일 수 있다 — 0건과 「층이 죽었다」는 다르다.
    """
    needle = _WS.sub("", company_name)
    if not needle:
        return []
    return [n for n in items if _names(needle, n.title)]


def _squeeze(text: str) -> tuple[str, list[int]]:
    """공백을 뺀 문자열과, 남은 글자들이 **원문에서 있던 자리**.

    자리를 들고 다니는 이유가 이 모듈의 미묘한 지점이다 — 아래 `_names` 주석 참고.
    """
    kept = [(ch, i) for i, ch in enumerate(text) if not ch.isspace()]
    return "".join(ch for ch, _ in kept), [i for _, i in kept]


def _names(needle: str, title: str) -> bool:
    """제목이 **그 종목**을 가리키는가.

    단순 부분 문자열이면 `아이텍`이 `위세아이텍` 안에서 잡힌다 — 선행 2026-08-30 실호출에서
    다섯 건 전부 다른 회사 기사였다.

    **앞 글자만 본다.** 한국 회사 이름은 앞에 수식어가 붙어 길어지지만(`위세아이텍`),
    뒷글자는 조사나 서술어인 경우가 많아(`아이텍급등`·`제테마는`) 막으면 멀쩡한 기사를 버린다.

    **찾기는 공백을 뺀 문자열에서 하고, 앞 글자는 원문에서 본다.** 둘을 같은 문자열에서 하면
    서로를 망친다 — 공백을 지운 `코스닥아이텍강세`는 앞 글자가 `닥`이라 멀쩡한 기사가 버려지고,
    공백을 안 지우면 `한올 바이오파마`가 `한올바이오파마`와 안 맞는다.
    선행은 지운 문자열 하나로만 봐서 이런 제목을 조용히 놓치고 있었다 — 잰 것이 정밀도(100%)라
    누락은 애초에 보이지 않았다 (2026-09-05 확인).

    그래서 **접두가 아닌 동음이의는 못 거른다** — `LG`로 검색하면 야구단 기사(`부산 LG-롯데전`)와
    계열사 기사(`LG이노텍`)가 둘 다 통과한다. 그 한계는 알고 쓴다.
    """
    packed, at = _squeeze(title)
    start = 0
    while (j := packed.find(needle, start)) != -1:
        i = at[j]
        if i == 0 or not _HANGUL.match(title[i - 1]):
            return True
        start = j + 1
    return False


def _wait_turn() -> None:
    """호출 간 최소 간격을 둔다. fan-out 스레드가 몰려도 초당 제한에 안 걸리게."""
    global _last_call
    with _pace:
        gap = _now() - _last_call
        if gap < MIN_INTERVAL:
            _sleep(MIN_INTERVAL - gap)
        _last_call = _now()


def _ask(srv: _Server, company_name: str) -> list[NewsItem]:
    """한 번 부르고 **제목 필터까지** 건다. 재시도 경로도 이 함수를 쓴다.

    수집과 필터를 붙여 둔다 — 떼어 놓으면 한쪽 경로에서 필터를 빠뜨리게 된다.
    """
    args: dict[str, Any] = {"query": query_for(company_name), "display": DISPLAY, "sort": SORT}
    _wait_turn()
    return about(parse_news(srv.call_json("search_news", args, timeout=TIMEOUT)), company_name)


def fetch_news(company_name: str, *, server: _Server | None = None) -> list[NewsItem]:
    """종목의 뉴스 최대 `DISPLAY`건 — 관련도순, 제목 필터를 거친 것만.

    HTTP 429(초당 제한)면 한 번 쉬었다 다시 부른다 — 일일 한도가 아니라 속도 문제다.

    Args:
        company_name: 종목명. 검색어이자 제목 필터의 기준이다.
        server: MCP 세션 (테스트가 대역을 넣는다).

    Returns:
        그 종목을 가리키는 기사만. 0건일 수 있다.

    Raises:
        mcpc.McpError: 429 재시도까지 실패했거나 429가 아닌 실패. 호출자가 생략으로 삼킨다 (F34).
    """
    srv = server or mcpc.get("naver")
    try:
        return _ask(srv, company_name)
    except mcpc.McpCallError as exc:
        if "429" not in str(exc):
            raise
        print(f"[news] {company_name} 429 — {RETRY_WAIT}초 후 재시도")
        _sleep(RETRY_WAIT)
    return _ask(srv, company_name)
