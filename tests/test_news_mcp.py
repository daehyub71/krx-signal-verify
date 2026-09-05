"""news_mcp — naver-search-mcp `search_news` → NewsItem.

계약 테스트는 실제 응답 표본(`tests/fixtures/mcp_news.json`)으로 한다 (N14).

지키는 것:
  · 검색어는 **종목명만**, 정렬은 **관련도순** — `{종목명} 주가` + 최신순은 적합도 64%였다
    (자동 생성 시세 기사가 상위를 채운다). 종목명만 + 관련도순이 95%다 (선행 A/B 실측)
  · **앞 글자가 한글이면 다른 회사다** — `아이텍`이 `위세아이텍` 안에서 잡혔다.
    이 파일의 중심이고, 닮은꼴 반례를 여러 갈래로 잠근다
  · 뒷글자는 **막지 않는다** — 조사가 붙는다(`제테마는`·`아이텍급등`). 막으면 멀쩡한 기사를 버린다
  · 필터가 **못 하는 것**도 적어 둔다 — 접두가 아닌 동음이의(`LG` ↔ `LG이노텍`)는 안 걸러진다
  · 0건과 「층이 죽었다」는 다르다 (F34)
"""

from __future__ import annotations

import json
import pathlib
from datetime import date
from typing import Any

import pytest

from verify import mcpc, news_mcp
from verify.models import NewsItem

FIX = pathlib.Path(__file__).parent / "fixtures"
SAMPLE = json.loads((FIX / "mcp_news.json").read_text(encoding="utf-8"))


class FakeServer:
    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = 0
    ) -> Any:
        self.calls.append(dict(args or {}))
        out = self.outcomes.pop(0) if self.outcomes else {"items": []}
        if isinstance(out, BaseException):
            raise out
        return out


@pytest.fixture(autouse=True)
def no_pacing(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """호출 간격·재시도 대기를 재기만 하고 실제로 자지 않는다."""
    slept: list[float] = []
    monkeypatch.setattr(news_mcp, "_sleep", slept.append)
    monkeypatch.setattr(news_mcp, "_last_call", 0.0)
    return slept


def news(title: str) -> NewsItem:
    return NewsItem(title=title, link="https://n.news.naver.com/x")


# ── ★ 닮은꼴 — 앞 글자가 한글이면 다른 회사 ────────────────────────


def test_the_measured_case_a_longer_company_name(   ) -> None:
    """선행 2026-08-30 실호출: `아이텍`으로 검색한 다섯 건이 **전부** 위세아이텍 기사였다."""
    items = [news("위세아이텍 주가 급등"), news("아이텍, 유상증자 결정")]
    assert [n.title for n in news_mcp.about(items, "아이텍")] == ["아이텍, 유상증자 결정"]


@pytest.mark.parametrize(
    ("company", "title", "keep"),
    [
        # 앞에 한글이 붙으면 더 긴 회사 이름이다 — 버린다
        ("아이텍", "위세아이텍 주가 급등", False),
        ("아이텍", "케이아이텍 상장폐지", False),
        ("바이오", "삼성바이오로직스 실적", False),
        # 맨 앞이면 그 회사다
        ("아이텍", "아이텍 CB 발행", True),
        # 앞이 한글이 아니면 그 회사다 — 공백·괄호·따옴표·숫자·영문
        ("아이텍", "[단독] 아이텍, 공장 증설", True),
        ("아이텍", "'아이텍' 급등 배경", True),
        ("아이텍", "코스닥 아이텍 강세", True),
        ("제테마", "2026 제테마 실적 발표", True),
        # 뒤에 조사·서술어가 붙는 것은 막지 않는다 — 막으면 멀쩡한 기사를 버린다
        ("제테마", "제테마는 왜 올랐나", True),
        ("아이텍", "아이텍급등 이유", True),
        ("가비아", "가비아의 공개매수", True),
        # 이름이 두 번 나오고 한 번만 온전하면 살린다
        ("아이텍", "위세아이텍과 아이텍은 다르다", True),
    ],
)
def test_leading_hangul_decides(company: str, title: str, keep: bool) -> None:
    got = news_mcp.about([news(title)], company)
    assert bool(got) is keep, title


def test_spaces_in_the_name_are_ignored() -> None:
    """`한올바이오파마`가 기사에서는 `한올 바이오파마`로 쓰인다."""
    assert news_mcp.about([news("한올 바이오파마, 기술수출")], "한올바이오파마")
    assert news_mcp.about([news("한올바이오파마 급등")], "한올 바이오파마")


def test_finding_and_boundary_use_different_strings() -> None:
    """**이 둘을 같은 문자열에서 하면 서로를 망친다.** 선행이 그래서 조용히 놓치고 있었다.

    · 찾기는 공백을 뺀 것에서 — 그래야 `한올 바이오파마`가 `한올바이오파마`와 맞는다
    · 앞 글자는 원문에서 — 그래야 `코스닥 아이텍`의 앞이 `닥`이 아니라 공백으로 보인다

    한쪽으로 통일하면 아래 둘 중 하나가 반드시 깨진다.
    """
    both = [news("코스닥 아이텍 강세"), news("한올 바이오파마 기술수출")]
    assert len(news_mcp.about(both[:1], "아이텍")) == 1  # 공백을 지워 보면 앞이 `닥`이다
    assert len(news_mcp.about(both[1:], "한올바이오파마")) == 1  # 공백을 안 지우면 안 맞는다


@pytest.mark.parametrize(
    "title",
    ["코스닥 아이텍 강세", "특징주 아이텍 급등", "[특징주] 코스닥 아이텍", "장중 아이텍 상한가"],
)
def test_headlines_that_put_a_word_before_the_name_survive(title: str) -> None:
    """한국 헤드라인은 이름 앞에 말을 붙이는 꼴이 흔하다 — 여기서 새면 조용히 근거가 빈다."""
    assert news_mcp.about([news(title)], "아이텍"), title


def test_what_the_filter_does_not_do() -> None:
    """정직하게 적어 둔다 — **접두가 아닌 동음이의는 못 거른다.**

    `LG`는 야구단 기사(`부산 LG-롯데전`)도 계열사 기사(`LG이노텍`)도 통과시킨다.
    뒷글자를 막으면 조사가 붙은 멀쩡한 기사가 다 죽으므로, 여기서는 막지 않기로 했다.
    이 한계는 프롬프트가 아니라 사람이 읽을 때 걸러진다.
    """
    assert news_mcp.about([news("부산 LG-롯데전 승리")], "LG")
    assert news_mcp.about([news("LG이노텍 주가 상승")], "LG")


def test_a_title_without_the_name_is_dropped() -> None:
    assert news_mcp.about([news("코스닥 지수 상승 마감")], "아이텍") == []


def test_an_empty_company_name_keeps_nothing() -> None:
    """종목명을 못 얻었을 때 전부 통과시키면 남의 회사 기사가 근거로 붙는다."""
    assert news_mcp.about([news("아무 기사")], "") == []
    assert news_mcp.about([news("아무 기사")], "   ") == []


def test_zero_matches_is_not_a_failure() -> None:
    """0건과 「층이 죽었다」는 다르다 (F34)."""
    assert news_mcp.about([news("무관한 기사")], "아이텍") == []


# ── 검색어·정렬 (F11 v2) ──────────────────────────────────────────


def test_query_is_the_company_name_only() -> None:
    """`주가`를 붙이면 자동 생성 시세 기사가 상위를 채운다 — 적합도 64%였다."""
    assert news_mcp.query_for("  가비아 ") == "가비아"
    assert "주가" not in news_mcp.query_for("가비아")


def test_call_uses_relevance_sort() -> None:
    srv = FakeServer(SAMPLE)
    news_mcp.fetch_news("가비아", server=srv)
    args = srv.calls[0]
    assert args["query"] == "가비아"
    assert args["sort"] == "sim"  # 최신순이면 시세 기사가 온다
    assert args["display"] == news_mcp.DISPLAY


# ── 응답 정제 ─────────────────────────────────────────────────────


def test_parse_news_from_the_real_sample() -> None:
    got = news_mcp.parse_news(SAMPLE)
    assert len(got) == 5
    first = got[0]
    assert "<b>" not in first.title  # 검색어 강조 태그
    assert first.title.startswith("맥쿼리 공개매수 중인 가비아")
    assert first.published == date(2026, 8, 28)  # RFC 822
    assert first.link.startswith("https://n.news.naver.com/")
    assert first.source.startswith("https://zdnet.co.kr/")  # 언론사 원문은 따로 남긴다


def test_clean_text_strips_tags_entities_and_extra_space() -> None:
    raw = "<b>가비아</b>가  &quot;성장&quot;  &amp; 도약"
    assert news_mcp.clean_text(raw) == '가비아가 "성장" & 도약'


def test_unparseable_date_keeps_the_article() -> None:
    """날짜를 못 읽는다고 기사를 버리지 않는다."""
    assert news_mcp.parse_pub_date("어제") is None
    assert news_mcp.parse_pub_date("") is None
    got = news_mcp.parse_news({"items": [{"title": "가비아 실적", "link": "u", "pubDate": "어제"}]})
    assert len(got) == 1 and got[0].published is None


def test_items_without_a_title_or_link_are_dropped() -> None:
    payload = {"items": [
        {"title": "", "link": "u"},
        {"title": "가비아", "link": ""},
        {"title": "가비아 실적", "link": "u"},
    ]}
    assert [n.title for n in news_mcp.parse_news(payload)] == ["가비아 실적"]


def test_missing_items_key_is_empty() -> None:
    assert news_mcp.parse_news({}) == []
    assert news_mcp.parse_news({"items": None}) == []


# ── 초당 제한 (429) ───────────────────────────────────────────────


def test_429_retries_once_and_filters_the_retry_too(no_pacing: list[float]) -> None:
    """재시도 경로에도 같은 필터를 건다 — 빠뜨리면 **429가 난 종목만** 안 걸러진다."""
    payload = {"items": [
        {"title": "위세아이텍 급등", "link": "u1"},
        {"title": "아이텍 유상증자", "link": "u2"},
    ]}
    srv = FakeServer(mcpc.McpCallError("[naver] search_news 실패: HTTP 429"), payload)
    got = news_mcp.fetch_news("아이텍", server=srv)
    assert [n.title for n in got] == ["아이텍 유상증자"]
    assert len(srv.calls) == 2
    assert news_mcp.RETRY_WAIT in no_pacing


def test_a_non_429_call_error_is_not_retried(no_pacing: list[float]) -> None:
    """일일 한도나 키 오류는 다시 불러도 같다."""
    srv = FakeServer(mcpc.McpCallError("[naver] 일일 한도 초과"))
    with pytest.raises(mcpc.McpCallError):
        news_mcp.fetch_news("가비아", server=srv)
    assert len(srv.calls) == 1


def test_other_mcp_failures_are_not_retried(no_pacing: list[float]) -> None:
    srv = FakeServer(mcpc.McpProtocolError("세션 파손"))
    with pytest.raises(mcpc.McpProtocolError):
        news_mcp.fetch_news("가비아", server=srv)
    assert len(srv.calls) == 1


def test_calls_are_paced_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    """fan-out 스레드가 몰리면 초당 제한에 걸린다 (선행 실측 HTTP 429)."""
    slept: list[float] = []
    clock = iter([0.0, 0.0, 0.0, 0.05, 0.05])
    monkeypatch.setattr(news_mcp, "_sleep", slept.append)
    monkeypatch.setattr(news_mcp, "_now", lambda: next(clock))
    monkeypatch.setattr(news_mcp, "_last_call", 0.0)
    srv = FakeServer(SAMPLE, SAMPLE)
    news_mcp.fetch_news("가비아", server=srv)
    news_mcp.fetch_news("가비아", server=srv)
    assert any(0 < s <= news_mcp.MIN_INTERVAL for s in slept)


def test_fetch_applies_the_title_filter(no_pacing: list[float]) -> None:
    """수집과 필터가 붙어 있어야 한다 — 부르는 쪽이 `about()`을 잊으면 남의 기사가 근거가 된다."""
    payload = {"items": [{"title": "위세아이텍 급등", "link": "u"}]}
    assert news_mcp.fetch_news("아이텍", server=FakeServer(payload)) == []
