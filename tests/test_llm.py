"""llm — Claude 호출 (F11·M5). **있으면 좋은 층이다.**

지키는 것:
  · **`stop_reason == "refusal"`을 `content`보다 먼저 본다** — 거부를 HTTP 200으로 준다.
    content를 먼저 읽으면 빈 응답을 「LLM이 할 말이 없었다」로 오해한다
  · **죽어도 판정·점수·증거는 나간다** (F34) — 예외를 밖으로 내지 않고 `summary_error`를 남긴다
  · 그래프 어디에서도 **LLM에 도구를 주지 않는다** (N5) — 호출 순서는 코드가 정한다
  · 모델은 `claude-opus-5` — 판을 바꾸면 서술이 달라지므로 고정한다
"""

from __future__ import annotations

from typing import Any

import pytest

from verify import llm


class Block:
    def __init__(self, text: str, type_: str = "text") -> None:
        self.text, self.type = text, type_


class Details:
    def __init__(self, category: str, explanation: str = "") -> None:
        self.category, self.explanation = category, explanation


class Reply:
    def __init__(self, blocks: list[Block], stop_reason: str = "end_turn",
                 stop_details: Details | None = None) -> None:
        self.content, self.stop_reason, self.stop_details = blocks, stop_reason, stop_details


class FakeClient:
    """`anthropic.Anthropic` 대역. 부른 인자를 적어 둔다."""

    def __init__(self, reply: Any) -> None:
        self.reply = reply
        self.calls: list[dict[str, Any]] = []
        self.beta = self
        self.messages = self

    def create(self, **kw: Any) -> Any:
        self.calls.append(kw)
        if isinstance(self.reply, BaseException):
            raise self.reply
        return self.reply


def ok(text: str = '{"items": []}') -> FakeClient:
    return FakeClient(Reply([Block(text)]))


# ── ★ 거부를 content보다 먼저 본다 ────────────────────────────────


def test_a_refusal_is_seen_before_the_content() -> None:
    """**거부를 HTTP 200으로 준다.** content를 먼저 읽으면 빈 응답으로 오해한다."""
    client = FakeClient(Reply([], stop_reason="refusal", stop_details=Details("cyber", "…")))
    got = llm.summarize([{"ticker": "005930"}], client=client)
    assert got.text == ""
    assert "refusal" in got.error
    assert "cyber" in got.error


def test_a_refusal_with_text_still_refuses() -> None:
    """**본문이 있어도 거부는 거부다** — 순서를 뒤집으면 여기가 깨진다."""
    client = FakeClient(Reply([Block("무언가 썼다")], stop_reason="refusal"))
    got = llm.summarize([{"ticker": "005930"}], client=client)
    assert got.text == ""
    assert got.error


def test_missing_stop_details_does_not_crash() -> None:
    """`stop_details`는 `refusal`일 때만 채워진다 — 없을 수도 있다."""
    client = FakeClient(Reply([], stop_reason="refusal", stop_details=None))
    got = llm.summarize([{"ticker": "005930"}], client=client)
    assert got.error and got.text == ""


# ── 있으면 좋은 층 (F34) ──────────────────────────────────────────


def test_an_api_failure_never_escapes() -> None:
    """**죽어도 판정·점수·증거는 나간다** — 예외를 밖으로 내지 않는다."""
    got = llm.summarize([{"ticker": "005930"}], client=FakeClient(RuntimeError("500")))
    assert got.text == ""
    assert "RuntimeError" in got.error


def test_a_missing_key_is_an_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    got = llm.summarize([{"ticker": "005930"}], client=None)
    assert got.text == ""
    assert got.error


def test_nothing_to_say_means_no_call() -> None:
    """종목이 0건이면 부르지 않는다 — 빈 호출도 돈이 든다."""
    client = ok()
    got = llm.summarize([], client=client)
    assert client.calls == []
    assert got.text == "" and got.error == ""


def test_a_good_reply_comes_back_whole() -> None:
    client = ok('{"items": [{"ticker": "005930", "reason": "…"}]}')
    got = llm.summarize([{"ticker": "005930"}], client=client)
    assert '"005930"' in got.text
    assert got.error == ""


def test_only_text_blocks_are_joined() -> None:
    """생각 블록 등이 섞여 와도 본문만 모은다.

    **생각 블록에 글자가 들어 있을 때를 본다** — 빈 블록으로 시험하면 이어 붙여도 티가 안 난다
    (변이 검사로 드러남, 2026-09-05). 섞이면 뒤따르는 JSON 파싱이 통째로 실패한다.
    """
    client = FakeClient(Reply([Block("먼저 생각을 정리하면", "thinking"), Block('{"items": []}')]))
    assert llm.summarize([{"ticker": "005930"}], client=client).text == '{"items": []}'


# ── 요청 모양 ─────────────────────────────────────────────────────


def test_the_model_is_pinned() -> None:
    """판을 바꾸면 서술이 달라진다 — 고정한다."""
    client = ok()
    llm.summarize([{"ticker": "005930"}], client=client)
    assert client.calls[0]["model"] == "claude-opus-5"
    assert llm.MODEL == "claude-opus-5"


def test_no_tools_are_offered() -> None:
    """**LLM에 도구를 주지 않는다** (N5) — 호출 순서·인자는 코드가 정한다."""
    client = ok()
    llm.summarize([{"ticker": "005930"}], client=client)
    assert "tools" not in client.calls[0]


def test_the_system_prompt_is_the_one_from_analysis() -> None:
    """규칙이 두 곳에 있으면 갈라진다 — `analysis.SYSTEM_PROMPT` 하나를 쓴다."""
    from verify import analysis

    client = ok()
    llm.summarize([{"ticker": "005930"}], client=client)
    assert client.calls[0]["system"] == analysis.SYSTEM_PROMPT


def test_the_input_goes_in_as_json() -> None:
    """세라고 시키지 않고 **세어서 준다** — `build_input`이 만든 것을 그대로 넣는다."""
    import json

    client = ok()
    llm.summarize([{"ticker": "005930", "score": 20}], client=client)
    body = client.calls[0]["messages"][0]["content"]
    assert json.loads(body)[0]["score"] == 20


def test_a_refusal_can_be_rescued_by_the_fallback() -> None:
    """정책 거부에 다른 판이 이어받는다 — 서술이 통째로 비는 것보다 낫다."""
    client = ok()
    llm.summarize([{"ticker": "005930"}], client=client)
    call = client.calls[0]
    assert call["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in call["betas"]


def test_the_output_shape_is_enforced_not_requested() -> None:
    """⚠ **프롬프트로 부탁하면 마크다운이 온다.** 2026-09-05 첫 실발송에서 15건 전부
    「응답이 JSON이 아니다」로 버려져 메일이 「⚠ 서술 생략」으로만 나갔다.

    `output_config.format`이 스키마를 **강제**한다 — `analysis.OUTPUT_SCHEMA` 하나를 쓴다.
    """
    from verify import analysis

    client = ok()
    llm.summarize([{"ticker": "005930"}], client=client)
    fmt = client.calls[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] is analysis.OUTPUT_SCHEMA
    assert fmt["schema"]["required"] == ["items"]


def test_output_is_capped_but_not_starved() -> None:
    """잘리면 마지막 종목의 서술이 통째로 사라진다."""
    client = ok()
    llm.summarize([{"ticker": "005930"}], client=client)
    assert client.calls[0]["max_tokens"] >= 8000


# ── explain 노드 — 검증까지 붙인다 ────────────────────────────────


def a_verdict(stand: str = "불일치", score: int = 20) -> Any:
    from verify.models import Verdict

    return Verdict(stand, score, (), ("재무",), "1.0")


def an_evidence(ticker: str = "005930") -> Any:
    """**증거가 있어야 LLM에 들어간다** — 볼 것이 없으면 설명할 것도 없다."""
    from datetime import date

    from verify.models import Disclosure, Evidence

    return Evidence(
        d=date(2026, 9, 3), ticker=ticker,
        disclosures=(Disclosure(date(2026, 9, 2), "전환사채권발행결정", "20260902000001"),),
    )


def a_state(**over: Any) -> Any:
    from datetime import date

    from verify.models import SignalRow

    base: dict[str, Any] = {
        "run_date": date(2026, 9, 3),
        "signals": [SignalRow(d=date(2026, 9, 3), strategy="vcp", ticker="005930",
                              name="삼성전자", evidence={})],
        "evidence": [an_evidence()],
        "verdicts": {"005930": a_verdict()},
    }
    base.update(over)
    return base


def test_explain_keeps_only_what_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    """**걸린 항목만 버린다.** 다듬지 않는다 — 경계를 넓히는 쪽이 더 위험하다 (N13)."""
    from verify import nodes

    reply = '{"items": [{"ticker": "005930", "reason": "공시가 신호와 어긋난다"},'\
            ' {"ticker": "999999", "reason": "지어낸 종목"}]}'
    monkeypatch.setattr(nodes, "_summarize", lambda items: llm.Summary(text=reply))
    out = nodes.explain(a_state())
    assert set(out["summaries"]) == {"005930"}  # 없는 티커는 버린다


def test_a_forbidden_word_drops_that_item(monkeypatch: pytest.MonkeyPatch) -> None:
    """N1 — 매매 판단이 섞이면 그 줄만 버린다."""
    from verify import nodes

    reply = '{"items": [{"ticker": "005930", "reason": "지금 매도 판단이 맞다"}]}'
    monkeypatch.setattr(nodes, "_summarize", lambda items: llm.Summary(text=reply))
    out = nodes.explain(a_state())
    assert out["summaries"] == {}


def test_a_dead_llm_leaves_the_verdicts_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    """**LLM이 죽어도 판정·점수는 그대로 나간다** (F34)."""
    from verify import nodes

    monkeypatch.setattr(nodes, "_summarize", lambda items: llm.Summary(error="500"))
    out = nodes.explain(a_state())
    assert out["summaries"] == {}
    assert "500" in out["summary_error"]
    assert "verdicts" not in out  # 판정을 건드리지 않는다


def test_a_non_json_reply_is_an_error_not_a_crash(monkeypatch: pytest.MonkeyPatch) -> None:
    from verify import nodes

    monkeypatch.setattr(nodes, "_summarize", lambda items: llm.Summary(text="죄송합니다"))
    out = nodes.explain(a_state())
    assert out["summaries"] == {}
    assert out["summary_error"]


def test_explain_never_changes_a_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """**LLM이 판정을 바꾸지 못한다** (F10) — 노드가 그 키를 돌려주지 않는다."""
    import inspect

    from verify import nodes

    src = inspect.getsource(nodes.explain)
    assert '"verdicts"' not in src
    assert '"stand"' not in src and '"score"' not in src


def test_explain_is_no_longer_a_stub() -> None:
    from verify import nodes

    assert "explain" not in nodes.STUB_NODES


def test_it_is_one_call_a_day(monkeypatch: pytest.MonkeyPatch) -> None:
    """**하루 1회 일괄** — 종목마다 부르면 44회가 되고 비용도 그만큼이다."""
    from verify import nodes

    calls: list[Any] = []

    def once(items: Any) -> Any:
        calls.append(len(items))
        return llm.Summary(text='{"items": []}')

    monkeypatch.setattr(nodes, "_summarize", once)
    from datetime import date

    from verify.models import SignalRow

    sigs = [SignalRow(d=date(2026, 9, 3), strategy="vcp", ticker=f"{i:06d}",
                      name=f"종목{i}", evidence={}) for i in range(5)]
    evs = [an_evidence(s.ticker) for s in sigs]
    nodes.explain(a_state(signals=sigs, evidence=evs,
                          verdicts={s.ticker: a_verdict() for s in sigs}))
    assert calls == [5]  # 한 번에 다섯 종목


def test_a_ticker_with_nothing_to_explain_is_not_sent(monkeypatch: pytest.MonkeyPatch) -> None:
    """**볼 것이 없는 종목은 넣지 않는다** — 설명할 것도 없고 토큰만 든다.

    `analysis.build_input`이 공시도 뉴스도 없는 종목을 거른다. 그것까지 보내면
    LLM은 「근거가 없다」를 44번 쓰고 우리는 그만큼 낸다.
    """
    from datetime import date

    from verify import nodes
    from verify.models import Evidence

    calls: list[Any] = []
    def spy(items: Any) -> Any:
        calls.append(len(items))
        return llm.Summary()

    monkeypatch.setattr(nodes, "_summarize", spy)
    nodes.explain(a_state(evidence=[Evidence(d=date(2026, 9, 3), ticker="005930")]))
    assert calls == []  # 아예 부르지 않는다
