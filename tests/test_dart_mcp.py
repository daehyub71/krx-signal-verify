"""dart_mcp — korean-dart-mcp 도구 호출 → 도메인 모델, 그리고 REST 폴백.

계약 테스트는 **실제 응답 표본**(`tests/fixtures/mcp_*.json`)으로 한다. 서버 버전을 올릴 때
표본을 다시 뽑아 돌린다 (N14).

지키는 것:
  · 공시는 **MCP 우선 · REST 폴백** — 둘 다 죽어야 그 종목이 실패다 (F34)
  · 두 경로가 **같은 매핑**(`Disclosure.from_dart_item`)을 쓴다 —
    폴백한 날만 판정이 달라지면 안 된다
  · 본문 인자는 **`start`/`end`** — `bgn_de`면 HTTP 200 + `status:100`으로
    **조용히 0건**이 온다.
    선행이 2026-08-30에 그렇게 하루를 헛돌았다. 여기서는 `100`을 **소리 나게** 만든다
  · anomaly·insider는 폴백이 없다 — 실패하면 그 갈래만 생략한다
"""

from __future__ import annotations

import json
import pathlib
from datetime import date
from typing import Any

import pytest

from verify import dart, dart_mcp, mcpc
from verify.dart import DartError
from verify.models import Disclosure

FIX = pathlib.Path(__file__).parent / "fixtures"
CORP = "00126380"
BGN, END = date(2026, 7, 27), date(2026, 8, 27)


def fixture(name: str) -> Any:
    return json.loads((FIX / f"mcp_{name}.json").read_text(encoding="utf-8"))


class FakeServer:
    """`mcpc.McpServer` 대역 — 도구별 응답 또는 예외."""

    def __init__(self, **replies: Any) -> None:
        self.replies = replies
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = 0
    ) -> Any:
        self.calls.append((tool, dict(args or {})))
        out = self.replies.get(tool, {})
        if isinstance(out, BaseException):
            raise out
        return out

    def args_of(self, tool: str) -> dict[str, Any]:
        return next(a for t, a in self.calls if t == tool)


# ── 공시 목록 (MCP) ───────────────────────────────────────────────


def test_parse_disclosures_uses_the_shared_mapping() -> None:
    got = dart_mcp.parse_disclosures(fixture("search_disclosures"))
    assert len(got) == 20
    assert got[0] == Disclosure.from_dart_item(fixture("search_disclosures")["items"][0])
    assert got[0].report_nm == "주식등의대량보유상황보고서(일반)"
    assert got[0].rcept_dt == date(2026, 8, 28)


def test_parse_disclosures_survives_a_missing_items_key() -> None:
    assert dart_mcp.parse_disclosures({}) == []
    assert dart_mcp.parse_disclosures({"items": None}) == []


def test_disclosure_args_are_pinned_to_the_combination_that_matches_rest() -> None:
    """`all_pages`만 주면 정정공시가 빠진다 (선행 실측 53 vs 61). 조합을 고정한다."""
    a = dart_mcp.disclosure_args(CORP, BGN, END)
    assert a["corp"] == CORP
    assert a["begin"] == "2026-07-27"
    assert a["end"] == "2026-08-27"
    assert a["all_pages"] is True
    assert a["include_corrections"] is True


# ── REST 폴백 (F34·D15) ───────────────────────────────────────────


def test_mcp_success_does_not_touch_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[Any] = []
    monkeypatch.setattr(dart, "fetch_disclosures", lambda *a: called.append(a))
    srv = FakeServer(search_disclosures=fixture("search_disclosures"))
    items, source = dart_mcp.fetch_disclosures(CORP, BGN, END, server=srv)
    assert source == dart_mcp.SOURCE_MCP
    assert len(items) == 20
    assert called == []


@pytest.mark.parametrize(
    "boom",
    [
        mcpc.McpUnavailableError("안 떴다"),
        mcpc.McpCallError("타임아웃"),
        mcpc.McpProtocolError("세션 파손"),
        mcpc.McpStartError("자격증명 없음"),
    ],
)
def test_any_mcp_failure_falls_back_to_rest(
    monkeypatch: pytest.MonkeyPatch, capsys: Any, boom: Exception
) -> None:
    """네 실패 갈래 전부 폴백해야 한다 — 하나라도 새면 그날 그 종목이 빈다."""
    rest = [Disclosure(date(2026, 8, 26), "전환사채권발행결정", "20260826000286")]
    monkeypatch.setattr(dart, "fetch_disclosures", lambda *a: rest)
    srv = FakeServer(search_disclosures=boom)
    items, source = dart_mcp.fetch_disclosures(CORP, BGN, END, server=srv)
    assert (items, source) == (rest, dart_mcp.SOURCE_REST)
    assert "폴백" in capsys.readouterr().out  # 조용히 갈아타지 않는다


def test_rest_receives_the_same_window(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def rest(*a: Any) -> list[Any]:
        seen.append(a)
        return []

    monkeypatch.setattr(dart, "fetch_disclosures", rest)
    srv = FakeServer(search_disclosures=mcpc.McpCallError("x"))
    dart_mcp.fetch_disclosures(CORP, BGN, END, server=srv)
    assert seen == [(CORP, BGN, END)]


def test_both_paths_failing_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """공시는 **있으면 좋은 층이 아니다** — 둘 다 죽으면 그 종목은 실패다."""

    def boom(*a: Any) -> None:
        raise DartError("list.json status=020 한도 초과")

    monkeypatch.setattr(dart, "fetch_disclosures", boom)
    srv = FakeServer(search_disclosures=mcpc.McpCallError("x"))
    with pytest.raises(DartError):
        dart_mcp.fetch_disclosures(CORP, BGN, END, server=srv)


def test_a_dead_session_does_not_stop_the_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """세션을 못 얻는 것도(기동 실패) 폴백 대상이다 — `mcpc.get`이 던지는 자리다."""
    def no_session(name: str) -> Any:
        raise mcpc.McpStartError("[dart] 환경변수 없음: DART_API_KEY")

    monkeypatch.setattr(mcpc, "get", no_session)
    monkeypatch.setattr(dart, "fetch_disclosures", lambda *a: [])
    items, source = dart_mcp.fetch_disclosures(CORP, BGN, END)
    assert (items, source) == ([], dart_mcp.SOURCE_REST)


# ── 보조 신호 — 폴백 없음 (F4b) ───────────────────────────────────


def test_parse_anomaly_from_the_real_sample() -> None:
    a = dart_mcp.parse_anomaly(fixture("anomaly"))
    assert 0 <= a.score <= 100
    assert a.verdict
    assert all(isinstance(f, str) for f in a.flags)


def test_parse_anomaly_rejects_a_shape_it_does_not_know() -> None:
    """점수가 없는데 0으로 채우면 「이상 없음」으로 읽힌다 — 다르다."""
    with pytest.raises(ValueError, match="score"):
        dart_mcp.parse_anomaly({"summary_text": "…"})


def test_parse_insider_from_the_real_sample() -> None:
    i = dart_mcp.parse_insider(fixture("insider"))
    assert i.signal
    assert i.buy_events >= 0 and i.sell_events >= 0


def test_parse_insider_without_a_summary_is_none_not_a_crash() -> None:
    i = dart_mcp.parse_insider({})
    assert i.signal == "none"
    assert i.sell_cluster is False


def test_insider_uses_start_and_end_not_bgn_de() -> None:
    srv = FakeServer(insider_signal=fixture("insider"))
    dart_mcp.fetch_insider(CORP, BGN, END, server=srv)
    args = srv.args_of("insider_signal")
    assert set(args) == {"corp", "start", "end"}
    assert "bgn_de" not in args


def test_auxiliary_lanes_have_no_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """REST에 대응 끝점이 없다 — 실패는 그대로 올라가고 호출자가 생략한다 (F34)."""
    monkeypatch.setattr(dart, "fetch_disclosures", lambda *a: [Disclosure(BGN, "x", "1")])
    srv = FakeServer(disclosure_anomaly=mcpc.McpCallError("죽음"),
                     insider_signal=mcpc.McpCallError("죽음"))
    with pytest.raises(mcpc.McpError):
        dart_mcp.fetch_anomaly(CORP, server=srv)
    with pytest.raises(mcpc.McpError):
        dart_mcp.fetch_insider(CORP, BGN, END, server=srv)


# ── 본문 — 인자 이름 함정 (SPEC F15) ──────────────────────────────

EVENT = fixture("corporate_event")
CPS = EVENT["cb_issuance"][0]  # 씨피시스템 CB 1건
N2 = EVENT["cb_issuance"][1]  # 엔투텍 CB 2건


def test_event_args_use_start_and_end() -> None:
    """**`bgn_de`면 HTTP 200 + `status:100`으로 조용히 0건이 온다.** 선행이 하루를 헛돌았다."""
    a = dart_mcp.event_args(CORP, "cb_issuance", BGN, END)
    assert a["start"] == "20260727"
    assert a["end"] == "20260827"
    assert "bgn_de" not in a and "end_de" not in a
    assert a["event_type"] == "cb_issuance"


def test_fetch_event_sends_start_and_end() -> None:
    srv = FakeServer(get_corporate_event=CPS)
    dart_mcp.fetch_event(CORP, "cb", BGN, END, server=srv)
    assert set(srv.args_of("get_corporate_event")) == {"corp", "event_type", "start", "end"}


def test_status_100_is_loud_not_an_empty_list() -> None:
    """이게 이 파일의 요점이다 — `100`(필수값 누락)은 **우리 인자가 틀렸다**는 뜻이다.

    조용히 `()`를 돌려주면 「본문 없는 공시」와 구별되지 않아 하루를 헛돈다.
    데이터 상태가 아니라 우리 버그이므로 소리를 낸다.
    """
    srv = FakeServer(get_corporate_event={"status": "100", "message": "필수값 누락", "items": []})
    with pytest.raises(mcpc.McpCallError, match="100"):
        dart_mcp.fetch_event(CORP, "cb", BGN, END, server=srv)


def test_status_013_is_quietly_empty() -> None:
    """본문이 없는 것은 정상이다 — 이건 조용해야 한다."""
    srv = FakeServer(get_corporate_event={"status": "013", "items": []})
    assert dart_mcp.fetch_event(CORP, "cb", BGN, END, server=srv) == ()


def test_parse_events_reads_the_real_body() -> None:
    (body,) = dart_mcp.parse_events(CPS, "cb_issuance")
    assert body.rcept_no == "20260826000286"
    assert body.amount == 10_000_000_000
    assert body.overhang_pct == 5.10
    assert body.conv_price == 5106
    assert body.method == "사모"
    assert ("시설자금", 10_000_000_000) in body.use_of_funds
    assert body.refix_floor is None  # `-` — 0원이 아니다


def test_overhang_separates_two_identical_titles() -> None:
    """같은 「전환사채권발행결정」이라도 5.10%와 18.63%는 전혀 다른 사실이다."""
    (cps,) = dart_mcp.parse_events(CPS, "cb_issuance")
    first, second = dart_mcp.parse_events(N2, "cb_issuance")
    assert (cps.overhang_pct, first.overhang_pct, second.overhang_pct) == (5.10, 18.63, 5.41)
    assert first.refix_floor == 1064  # 이쪽은 하향조정 하한이 있다


def test_absent_markers_become_none_not_zero() -> None:
    """`-`·`미해당`을 0으로 읽으면 「자금 0원」이라는 없는 사실이 생긴다."""
    (body,) = dart_mcp.parse_events(CPS, "cb_issuance")
    assert dict(body.use_of_funds) == {"시설자금": 10_000_000_000}  # 나머지 다섯은 `-`


def test_dash_in_a_text_field_becomes_empty_not_a_dash() -> None:
    """글자 칸에서 `-`를 남기면 화면에 「종류: -」가 그대로 찍힌다."""
    item = {**CPS["items"][0], "bd_knd": "-", "bdis_mthn": "미해당"}
    (body,) = dart_mcp.parse_events({"status": "000", "items": [item]}, "cb_issuance")
    assert body.kind == ""
    assert body.method == ""


def test_zero_survives_where_absent_becomes_none() -> None:
    """0원과 「기재 없음」은 다르다 — 둘 다 None이 되면 구별이 사라진다."""
    item = {**CPS["items"][0], "bd_intr_ex": "0.0", "bd_fta": "-"}
    (body,) = dart_mcp.parse_events({"status": "000", "items": [item]}, "cb_issuance")
    assert body.coupon_rate == 0.0
    assert body.amount is None


def test_unmapped_rule_does_not_call_the_server() -> None:
    """규칙에 event_type이 없으면 부르지 않는다 — 없는 값을 지어내면 서버가 400을 준다."""
    srv = FakeServer(get_corporate_event=CPS)
    assert dart_mcp.fetch_event(CORP, "audit", BGN, END, server=srv) == ()
    assert srv.calls == []


def test_every_mapped_rule_exists_in_the_rule_table() -> None:
    """오타 난 규칙 id는 영원히 본문을 못 읽는다 — 조용히."""
    from verify import flags

    known = {r.id for r in flags.RULES}
    assert set(dart_mcp.EVENT_TYPE_OF) <= known, set(dart_mcp.EVENT_TYPE_OF) - known


def test_parse_events_skips_non_dict_items() -> None:
    assert dart_mcp.parse_events({"status": "000", "items": ["문자열", None]}, "cb_issuance") == ()
