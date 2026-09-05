"""갈래를 M2 모듈에 붙인다 (F3~F9). **여기가 붙기 전에는 판정이 전부 `무관 50점`이었다.**

지키는 것:
  · **묶음은 한 번, 종목별은 fan-out에서** — 재무는 15개/회, 수급·시세는 티커 목록으로 받는다.
    종목마다 부르면 44회가 되고 그 설계가 무의미해진다
  · **공유 맥락은 `Send` payload로 나른다** — payload가 상태를 통째로 대신하므로 (2026-09-05 실증)
  · 갈래 하나가 죽어도 나머지가 온다 (F34) — 격리는 `lanes.collect`가 한다
  · **본문(`bodies`)과 공시 이상(`anomaly`)이 산식까지 간다** — 자리가 없으면
    오버행 감산이 영원히 안 걸린다
"""

from __future__ import annotations

from datetime import date
from typing import Any, cast

import pytest

from verify import nodes
from verify import state as st
from verify.models import Disclosure, EventBody, Evidence, SignalRow

D = date(2026, 9, 3)


def sig(ticker: str = "005930", name: str = "삼성전자") -> SignalRow:
    return SignalRow(d=D, strategy="vcp", ticker=ticker, name=name, evidence={})


# ── 묶음 조회는 한 번만 ───────────────────────────────────────────


def test_batched_sources_are_asked_once_for_everyone(monkeypatch: pytest.MonkeyPatch) -> None:
    """재무 15개/회 · 수급·시세는 티커 목록 — **종목마다 부르면 그 설계가 죽는다.**"""
    calls: list[tuple[str, int]] = []

    monkeypatch.setattr(nodes, "_corp_codes", lambda: {"005930": "00126380", "000660": "00164779"})
    def db(tks: Any) -> Any:
        calls.append(("db", len(tks)))
        return {}, {}

    def fin(corps: Any, day: Any) -> Any:
        calls.append(("fin", len(corps)))
        return {}

    monkeypatch.setattr(nodes, "_upstream", db)
    monkeypatch.setattr(nodes, "_financials", fin)
    monkeypatch.setattr(nodes, "_shorting_state", lambda: None)

    ctx = nodes.prefetch([sig("005930"), sig("000660", "SK하이닉스")], D)
    assert calls == [("db", 2), ("fin", 2)]  # 두 종목을 한 번에
    assert ctx["corps"]["005930"] == "00126380"


def test_prefetch_survives_a_dead_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """묶음 하나가 죽어도 나머지 갈래는 살아야 한다 (F34)."""
    def boom(*a: Any) -> Any:
        raise RuntimeError("DART 죽음")

    monkeypatch.setattr(nodes, "_corp_codes", boom)
    monkeypatch.setattr(nodes, "_upstream", lambda tks: ({"005930": "수급"}, {}))
    monkeypatch.setattr(nodes, "_financials", lambda corps, day: {})
    monkeypatch.setattr(nodes, "_shorting_state", lambda: None)

    ctx = nodes.prefetch([sig()], D)
    assert ctx["corps"] == {}  # 공시·재무는 못 하지만
    assert ctx["flows"]["005930"] == "수급"  # 수급은 온다
    assert any("DART 죽음" in e for e in ctx["errors"])


# ── payload가 맥락을 나른다 ───────────────────────────────────────


def test_the_send_payload_carries_that_tickers_slice() -> None:
    """payload가 상태를 통째로 대신한다 — 필요한 것을 다 실어야 한다."""
    ctx: dict[str, Any] = {
        "corps": {"005930": "00126380"},
        "flows": {"005930": "수급"},
        "financials": {"00126380": "재무"},
        "shorting": None,
        "errors": [],
    }
    sends = nodes.fan_out(cast(st.VerifyState, {
        "run_date": D, "signals": [sig()], "context": ctx
    }))
    assert isinstance(sends, list)
    lane = sends[0].arg["lane_ctx"]
    assert lane["corp"] == "00126380"
    assert lane["flows"] == "수급"
    assert lane["financial"] == "재무"


def test_a_ticker_without_a_corp_code_still_goes_out() -> None:
    """DART에 없는 종목(신규 상장 등) — 공시만 못 볼 뿐 뉴스·수급은 본다."""
    ctx: dict[str, Any] = {
        "corps": {}, "flows": {}, "financials": {}, "shorting": None, "errors": []
    }
    sends = nodes.fan_out(cast(st.VerifyState, {
        "run_date": D, "signals": [sig()], "context": ctx
    }))
    assert isinstance(sends, list)
    assert sends[0].arg["lane_ctx"]["corp"] == ""


# ── 종목별 갈래 ───────────────────────────────────────────────────


def test_all_five_lanes_are_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    """다섯 갈래 전부에 함수가 넘어가야 한다 — 안 넘기면 그 갈래가 늘 생략된다."""
    from verify import lanes as lanes_mod

    seen: dict[str, Any] = {}
    real = lanes_mod.collect

    def spy(**kw: Any) -> Any:
        seen.update(kw)
        return real(**kw)

    monkeypatch.setattr(lanes_mod, "collect", spy)
    nodes.collect_lanes(D, sig(), {"corp": "00126380", "flows": None,
                                   "financial": None, "shorting": None})
    for lane in ("disclosures", "news", "flows", "financial", "shorting"):
        assert seen.get(lane) is not None, lane


def test_disclosures_reach_the_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """붙기 전에는 전부 `무관 50점`이었다 — 공시가 오면 점수가 움직여야 한다."""
    cb = Disclosure(D, "전환사채권발행결정", "20260903000001")
    monkeypatch.setattr(nodes, "_disclosures_of", lambda corp, day: ((cb,), ()))
    monkeypatch.setattr(nodes, "_news_of", lambda name: ())
    ev, _, _ = nodes.collect_lanes(D, sig(), {"corp": "00126380", "flows": None,
                                              "financial": None, "shorting": None})
    v = nodes.judge_all([sig()], [ev])["005930"]
    assert v.stand != "무관" or v.score != 50


def test_bodies_and_anomaly_have_a_place_to_live() -> None:
    """**자리가 없으면 오버행 감산이 영원히 안 걸린다** — `Evidence`가 들고 있어야 한다."""
    fields = set(Evidence.__dataclass_fields__)
    assert "bodies" in fields
    assert "anomaly" in fields


def test_overhang_actually_reaches_the_formula() -> None:
    """같은 「전환사채권발행결정」이라도 오버행 18.63%는 다른 사실이다 (F15)."""
    cb = Disclosure(D, "전환사채권발행결정", "20260903000001")
    body = EventBody(rcept_no="20260903000001", overhang_pct=18.63, method="사모")
    without = Evidence(d=D, ticker="005930", disclosures=(cb,))
    withbody = Evidence(d=D, ticker="005930", disclosures=(cb,), bodies=(body,))
    a = nodes.judge_all([sig()], [without])["005930"]
    b = nodes.judge_all([sig()], [withbody])["005930"]
    assert b.score < a.score  # 실측: 42점 → 20점
    assert any("18.63" in p.label for p in b.parts), [p.label for p in b.parts]
    assert any("사모" in p.label for p in b.parts)  # 본문에서만 알 수 있는 사실이다


def test_bodies_are_not_a_sixth_lane() -> None:
    """본문은 공시 갈래의 일부다 — 「생략」 표기가 여섯 개가 되면 안 된다."""
    from verify.models import EVIDENCE_LANES

    assert len(EVIDENCE_LANES) == 5
    assert len(Evidence(d=D, ticker="005930").missing_lanes()) == 5


# ── 실패 격리 ─────────────────────────────────────────────────────


def test_a_dead_news_lane_leaves_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    cb = Disclosure(D, "유상증자결정", "20260903000002")
    monkeypatch.setattr(nodes, "_disclosures_of", lambda corp, day: ((cb,), ()))
    monkeypatch.setattr(nodes, "_news_of", lambda name: (_ for _ in ()).throw(RuntimeError("429")))
    ev, skipped, reasons = nodes.collect_lanes(
        D, sig(), {"corp": "00126380", "flows": "수급", "financial": None, "shorting": None}
    )
    assert ev.disclosures
    assert ev.flows == "수급"
    assert "뉴스" in skipped
    assert "429" in reasons["뉴스"]


def test_a_ticker_with_no_corp_code_skips_only_disclosures(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(nodes, "_news_of", lambda name: ("뉴스",))
    ev, skipped, _ = nodes.collect_lanes(
        D, sig(), {"corp": "", "flows": "수급", "financial": None, "shorting": None}
    )
    assert "공시" in skipped
    assert ev.news == ("뉴스",)


def test_the_window_is_thirty_days() -> None:
    """공시·본문·뉴스가 같은 창을 본다 — 갈래마다 다르면 대조가 안 된다."""
    assert nodes.WINDOW_DAYS == 30


# ── 묶음 조회가 실제로 불리는가 ───────────────────────────────────


def test_fetch_signals_actually_prefetches(monkeypatch: pytest.MonkeyPatch) -> None:
    """⚠ **`prefetch`를 만들어 두고 부르지 않은 적이 있다** (2026-09-05 실행에서 잡혔다).

    맥락이 비면 공시·수급·재무가 전부 「생략」으로 흐르고, 맥락이 필요 없는 뉴스만 붙는다.
    노드가 그것을 부르는지 여기서 본다.
    """
    called: list[Any] = []
    monkeypatch.setattr(nodes, "_fetch_signals", lambda day: [sig()])
    def spy(rows: Any, day: Any) -> Any:
        called.append((len(rows), day))
        return {"corps": {}, "errors": []}

    monkeypatch.setattr(nodes, "prefetch", spy)
    out = nodes.fetch_signals(cast(st.VerifyState, {"run_date": D}))
    assert called == [(1, D)]
    assert "context" in out


def test_prefetch_errors_reach_the_run_record(monkeypatch: pytest.MonkeyPatch) -> None:
    """묶음 조회가 죽으면 **실행 기록에 남아야 한다** — 조용히 빈 갈래로 흐르면 모른다."""
    monkeypatch.setattr(nodes, "_fetch_signals", lambda day: [sig()])
    monkeypatch.setattr(nodes, "prefetch", lambda rows, day: {
        "corps": {}, "errors": ["corps 조회 실패: RuntimeError: DART 죽음"]
    })
    out = nodes.fetch_signals(cast(st.VerifyState, {"run_date": D}))
    assert any("DART 죽음" in e for e in out["errors"])


def test_no_signals_means_no_prefetch(monkeypatch: pytest.MonkeyPatch) -> None:
    """신호가 없는 날 corpCode.xml을 받아 오지 않는다."""
    called: list[Any] = []
    monkeypatch.setattr(nodes, "_fetch_signals", lambda day: [])
    def never(rows: Any, day: Any) -> Any:
        called.append(1)
        return {}

    monkeypatch.setattr(nodes, "prefetch", never)
    out = nodes.fetch_signals(cast(st.VerifyState, {"run_date": D}))
    assert called == []
    assert out["signals"] == []
