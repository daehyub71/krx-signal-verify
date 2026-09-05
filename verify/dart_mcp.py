"""korean-dart-mcp 도구 호출 → 도메인 모델, 그리고 **REST 폴백** (F4·F4b·F15, F34).

네 도구를 쓴다. 호출은 `mcpc.get("dart")` 세션으로 한다.

| 갈래 | 도구 | 실패하면 |
|------|------|----------|
| 공시 목록 (F4) | `search_disclosures` | **REST(`dart.py`)로 폴백.** 둘 다 죽어야 실패다 |
| 공시 이상 (F4b) | `disclosure_anomaly` | 폴백 없음 — 그 갈래만 생략 (F34) |
| 임원 매매 (F4b) | `insider_signal` | 폴백 없음 — 그 갈래만 생략 |
| 공시 본문 (F15) | `get_corporate_event` | 폴백 없음 — 제목만 쓴다 |

선행은 폴백을 `enrich.py`에 두었지만, 이 프로젝트의 `enrich.py`는 **상위 DB 전용**이라
폴백이 여기 있다. 그래서 「MCP 우선, 안 되면 REST」를 아는 곳이 한 군데다.

**응답 → 모델 변환은 여기 순수 함수(`parse_*`)에 있다.** 계약 테스트는 실제 응답 표본
(`tests/fixtures/mcp_*.json`)으로 한다. 서버 버전을 올릴 때 표본을 다시 뽑아 돌린다 (N14).

`search_disclosures` 인자는 REST `list.json`과 **같은 목록**을 주는 조합으로 고정한다
(선행 실측: `all_pages`만 주면 정정공시가 빠져 53건, `include_corrections`까지 줘야 61 = 61).
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Protocol

from verify import dart, mcpc
from verify.models import Anomaly, Disclosure, EventBody, Insider

TIMEOUT = 30.0
LIMIT = 200  # 30일 창에서 200건을 넘는 종목은 없다고 본다 (REST는 100 — 실측 최대 61)

SOURCE_MCP = "mcp"
SOURCE_REST = "rest"

# `get_corporate_event`가 돌려주는 상태.
STATUS_OK = "000"
STATUS_NO_DATA = "013"
# **`100`은 데이터 상태가 아니라 우리 버그다** — 필수값 누락. 인자 이름을 `bgn_de`로 주면
# HTTP 200에 이 상태가 실려 오고, 조용히 넘기면 「본문 없는 공시」와 구별되지 않는다.
# 선행이 2026-08-30에 그렇게 하루를 헛돌았다. 여기서는 소리를 낸다.
STATUS_BAD_ARGS = "100"


class _Server(Protocol):
    def call_json(
        self, tool: str, args: dict[str, Any] | None = None, *, timeout: float = ...
    ) -> Any: ...


def _dart() -> _Server:
    return mcpc.get("dart")


# ── 공시 목록 (F4) + REST 폴백 ────────────────────────────────────


def disclosure_args(corp_code: str, bgn: date, end: date) -> dict[str, Any]:
    """`search_disclosures` 인자 — REST와 같은 목록을 주는 조합으로 **고정**."""
    return {
        "corp": corp_code,
        "begin": bgn.isoformat(),
        "end": end.isoformat(),
        "all_pages": True,
        "include_corrections": True,  # 이게 없으면 정정공시가 빠진다 (실측)
        "limit": LIMIT,
    }


def parse_disclosures(payload: dict[str, Any]) -> list[Disclosure]:
    """`search_disclosures` 응답 → Disclosure 목록. 순서는 응답 그대로.

    **매핑은 `Disclosure.from_dart_item` 하나** — REST 경로와 같은 함수다.
    두 매핑을 두면 폴백이 일어난 날만 판정이 달라진다.
    """
    return [Disclosure.from_dart_item(x) for x in payload.get("items") or []]


def fetch_disclosures(
    corp_code: str, bgn: date, end: date, *, server: _Server | None = None
) -> tuple[list[Disclosure], str]:
    """한 회사의 기간 내 공시 목록 — **MCP 우선, 실패하면 REST** (D15).

    공시는 있으면 좋은 층이 아니다. 두 경로가 다 죽어야 그 종목이 실패한다.

    Args:
        corp_code: DART 고유번호 8자리.
        bgn: 조회 시작일.
        end: 조회 종료일.
        server: MCP 세션 (테스트가 대역을 넣는다).

    Returns:
        `(공시 목록, 출처)`. 출처는 `SOURCE_MCP` 또는 `SOURCE_REST` — 저장해 두면
        어떤 날 폴백이 일어났는지 나중에 볼 수 있다.

    Raises:
        DartError: MCP와 REST가 **둘 다** 실패했다.
    """
    try:
        srv = server or _dart()
        payload = srv.call_json("search_disclosures", disclosure_args(corp_code, bgn, end),
                                timeout=TIMEOUT)
        return parse_disclosures(payload), SOURCE_MCP
    except mcpc.McpError as exc:
        # 조용히 갈아타지 않는다 — 폴백이 잦아지면 서버 쪽을 봐야 한다
        print(f"[dart_mcp] {corp_code} MCP 공시 실패 → REST 폴백: {exc}")
    return dart.fetch_disclosures(corp_code, bgn, end), SOURCE_REST


# ── 보조 신호 (F4b) — 폴백 없음 ───────────────────────────────────


def parse_anomaly(payload: dict[str, Any]) -> Anomaly:
    """`disclosure_anomaly` 응답 → Anomaly.

    `score`·`verdict`가 없으면 `ValueError` — **0으로 채우면 「이상 없음」으로 읽힌다.**
    모르는 것과 깨끗한 것은 다르다.
    """
    if "score" not in payload or "verdict" not in payload:
        raise ValueError(f"disclosure_anomaly 응답에 score/verdict가 없다: {list(payload)[:6]}")
    flags = tuple(
        f if isinstance(f, str) else json.dumps(f, ensure_ascii=False)
        for f in payload.get("flags") or []
    )
    return Anomaly(
        score=int(payload["score"]),
        verdict=str(payload["verdict"]),
        summary=str(payload.get("summary_text") or "").strip(),
        flags=flags,
    )


def fetch_anomaly(corp_code: str, *, server: _Server | None = None) -> Anomaly:
    """공시 이상 점수 (3년 창은 서버 기본값). **보조 신호 — 등급을 바꾸지 않는다.**

    Raises:
        mcpc.McpError: 호출 실패. 호출자가 생략으로 삼킨다 (F34).
    """
    srv = server or _dart()
    return parse_anomaly(srv.call_json("disclosure_anomaly", {"corp": corp_code}, timeout=TIMEOUT))


def parse_insider(payload: dict[str, Any]) -> Insider:
    """`insider_signal` 응답 → Insider. `summary`가 없으면 신호 없음."""
    s = payload.get("summary") or {}
    return Insider(
        signal=str(s.get("signal") or "none"),
        buy_events=int(s.get("buy_events") or 0),
        sell_events=int(s.get("sell_events") or 0),
        unique_buyers=int(s.get("unique_buyers") or 0),
        unique_sellers=int(s.get("unique_sellers") or 0),
        net_change_shares=int(s.get("net_change_shares") or 0),
        summary=str(payload.get("summary_text") or "").strip(),
    )


def fetch_insider(
    corp_code: str, bgn: date, end: date, *, server: _Server | None = None
) -> Insider:
    """임원·주요주주 매매 군집 — 같은 30일 창. **인자는 `start`/`end`다.**

    Raises:
        mcpc.McpError: 호출 실패. 호출자가 생략으로 삼킨다 (F34).
    """
    srv = server or _dart()
    args = {"corp": corp_code, "start": bgn.isoformat(), "end": end.isoformat()}
    return parse_insider(srv.call_json("insider_signal", args, timeout=TIMEOUT))


# ── 공시 본문 (F15) ──────────────────────────────────────────────
#
# `report_nm` 한 줄로는 무슨 일인지 알 수 없다. 규칙이 걸린 공시에 한해 본문을 읽는다.
# **정형 공시(F16)의 본문은 부르지 않는다** — 호출이 폭증하고 읽을 것도 없다.

# 규칙 id → `get_corporate_event`의 `event_type`.
# 대응이 없는 규칙은 넣지 않는다 — 없는 값을 지어내면 서버가 400을 준다.
# 테스트가 `flags.RULES`에 실재하는 id인지 확인한다 (오타는 조용히 본문을 못 읽게 만든다).
EVENT_TYPE_OF: dict[str, str] = {
    "cb": "cb_issuance",
    "bw": "bw_issuance",
    "eb": "eb_issuance",
    "rights_issue": "rights_offering",
    "capital_reduction": "capital_reduction",
    "lawsuit": "litigation",
    "rehabilitation": "rehabilitation_filing",
    "treasury_sale": "treasury_disposal",
}

# 자금 용도 칸 — DART 필드명과 사람이 읽는 이름.
USE_OF_FUNDS: tuple[tuple[str, str], ...] = (
    ("fdpp_fclt", "시설자금"),
    ("fdpp_bsninh", "영업양수자금"),
    ("fdpp_op", "운영자금"),
    ("fdpp_dtrp", "채무상환자금"),
    ("fdpp_ocsa", "타법인증권취득자금"),
    ("fdpp_etc", "기타자금"),
)

# DART가 빈 값에 쓰는 표기. **0원과 다르다** — 0으로 읽으면 없는 사실이 생긴다.
# 숫자 칸에서는 따로 거르지 않는다: 이 표기들은 어차피 숫자로 안 읽혀 None이 된다
# (변이 검사로 확인 — 거기서 걸러도 관측 차이가 없는 죽은 가지였다, 2026-09-05).
# 글자 칸(`_text`)에서는 살아 있다. 거기선 `-`가 그대로 남아 화면에 찍힌다.
ABSENT = ("-", "", "해당사항없음", "미해당")


def _int_or_none(raw: Any) -> int | None:
    """쉼표 낀 숫자 → int. `-`나 읽을 수 없는 값이면 None (그 칸만 비운다). **0은 살린다.**"""
    try:
        return int(float(str(raw).strip().replace(",", "")))
    except (TypeError, ValueError):
        return None


def _float_or_none(raw: Any) -> float | None:
    """쉼표 낀 수 → float. 읽을 수 없으면 None."""
    try:
        return float(str(raw).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


def _text(raw: Any) -> str:
    v = str(raw).strip() if raw is not None else ""
    return "" if v in ABSENT else v


def event_args(corp_code: str, event_type: str, bgn: date, end: date) -> dict[str, str]:
    """`get_corporate_event` 인자.

    **이름은 `start`·`end`다.** `bgn_de`/`end_de`로 부르면 HTTP 200 + `status:100`이
    돌아오고, 그것을 빈 결과로 넘기면 하루가 조용히 사라진다.
    """
    return {
        "corp": corp_code,
        "event_type": event_type,
        "start": bgn.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
    }


def parse_events(payload: dict[str, Any], event_type: str) -> tuple[EventBody, ...]:
    """`get_corporate_event` 응답 → `EventBody` 목록. **순수 함수.**

    Args:
        payload: MCP 응답을 JSON으로 읽은 것.
        event_type: 요청했던 `event_type` (응답에 없을 수 있어 받아 둔다).

    Returns:
        본문 목록. 결과가 없으면 빈 튜플 — 본문은 **있으면 좋은 층**이라 없으면 제목만 쓴다.

    Raises:
        mcpc.McpCallError: `status`가 `100`(필수값 누락). 우리 인자가 틀렸다는 뜻이라
            조용히 넘기지 않는다.
    """
    status = str(payload.get("status", STATUS_OK))
    if status == STATUS_BAD_ARGS:
        raise mcpc.McpCallError(
            f"get_corporate_event status=100 필수값 누락 — 인자 이름을 확인하라"
            f" (start/end여야 한다): {payload.get('message', '')}"
        )
    if status not in (STATUS_OK, ""):
        return ()
    out: list[EventBody] = []
    for it in payload.get("items") or ():
        if not isinstance(it, dict):
            continue
        funds = tuple(
            (label, amount)
            for key, label in USE_OF_FUNDS
            if (amount := _int_or_none(it.get(key))) is not None
        )
        out.append(
            EventBody(
                rcept_no=str(it.get("rcept_no", "")),
                event_type=event_type,
                amount=_int_or_none(it.get("bd_fta")),
                use_of_funds=funds,
                kind=_text(it.get("bd_knd")),
                method=_text(it.get("bdis_mthn")),
                coupon_rate=_float_or_none(it.get("bd_intr_ex")),
                conv_price=_int_or_none(it.get("cv_prc")),
                overhang_pct=_float_or_none(it.get("cvisstk_tisstk_vs")),
                outstanding=_int_or_none(it.get("atcsc_rmislmt")),
                refix_floor=_int_or_none(it.get("act_mktprcfl_cvprc_lwtrsprc")),
            )
        )
    return tuple(out)


def fetch_event(
    corp_code: str, rule: str, bgn: date, end: date, *, server: _Server | None = None
) -> tuple[EventBody, ...]:
    """규칙 하나에 해당하는 공시 본문을 읽는다 (F15).

    Args:
        corp_code: DART 고유번호 8자리.
        rule: `flags.RULES`의 id. 매핑이 없으면 **부르지 않는다**.
        bgn: 조회 시작일.
        end: 조회 종료일.
        server: MCP 세션 (테스트가 대역을 넣는다).

    Returns:
        본문 목록. 매핑이 없거나 결과가 없으면 빈 튜플.

    Raises:
        mcpc.McpError: 호출 실패 · `status=100`. 호출자가 생략으로 삼킨다 (F34).
    """
    event_type = EVENT_TYPE_OF.get(rule)
    if event_type is None:
        return ()
    srv = server or _dart()
    payload = srv.call_json(
        "get_corporate_event", event_args(corp_code, event_type, bgn, end), timeout=TIMEOUT
    )
    return parse_events(payload, event_type)
