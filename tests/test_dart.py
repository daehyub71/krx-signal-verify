"""dart — OpenDART REST 클라이언트. `urlopen`을 mock한다. 실제 네트워크 없음 (N14).

지키는 것:
  · **`013`은 오류가 아니라 공시 0건** — 예외로 다루면 그날 그 종목이 통째로 빠진다
  · **`020`은 한도 초과** — 1회 재시도 후 전용 예외. 호출자가 남은 종목을 포기할지 정한다
  · `800`(점검) · 5xx · 타임아웃도 1회 재시도. `010`/`011`(키 오류)은 **재시도하지 않는다**
  · **키가 URL 쿼리에 실린다** — 예외 메시지·stdout 어디에도 키가 없다 (N10).
    규율이 아니라 장치로 막는다: `DartError`를 만드는 것만으로 마스킹된다
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import date
from email.message import Message
from typing import Any
from urllib.error import HTTPError, URLError

import pytest

from verify import dart
from verify.dart import DartError, DartMaintenanceError, DartRateLimitError
from verify.models import Disclosure

KEY = "0123456789abcdef0123456789abcdef01234567"  # 40자 가짜 키
CORP = "00126380"
BGN, END = date(2026, 8, 1), date(2026, 9, 2)


class FakeResponse:
    """`urlopen()`이 돌려주는 것 — 컨텍스트 매니저 + read()."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def body(status: str, items: list[dict[str, Any]] | None = None, **extra: Any) -> bytes:
    d: dict[str, Any] = {"status": status, "message": "정상" if status == "000" else "오류"}
    if items is not None:
        d["list"] = items
        d["total_count"] = extra.pop("total_count", len(items))
    d.update(extra)
    return json.dumps(d, ensure_ascii=False).encode("utf-8")


def item(
    rcept_no: str = "20260822000123",
    report_nm: str = "전환사채권발행결정",
    rcept_dt: str = "20260822",
    flr_nm: str = "가비아",
) -> dict[str, str]:
    return {
        "rcept_no": rcept_no,
        "report_nm": report_nm,
        "rcept_dt": rcept_dt,
        "flr_nm": flr_nm,
        "corp_code": CORP,
        "corp_name": flr_nm,
        "stock_code": "079940",
        "rm": "",
    }


class Recorder:
    """urlopen 대역. 부른 URL을 적고 준비된 응답/예외를 순서대로 돌려준다."""

    def __init__(self, *outcomes: bytes | BaseException) -> None:
        self.outcomes = list(outcomes)
        self.urls: list[str] = []

    def __call__(self, req: Any, timeout: float | None = None) -> FakeResponse:
        self.urls.append(getattr(req, "full_url", str(req)))
        out = self.outcomes.pop(0)
        if isinstance(out, BaseException):
            raise out
        return FakeResponse(out)

    def query(self, i: int = 0) -> dict[str, str]:
        return dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(self.urls[i]).query))


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """재시도 대기를 재기만 하고 실제로 자지 않는다."""
    slept: list[float] = []
    monkeypatch.setattr(dart, "sleep", slept.append)
    monkeypatch.setenv("DART_API_KEY", KEY)
    return slept


def use(monkeypatch: pytest.MonkeyPatch, rec: Recorder) -> Recorder:
    monkeypatch.setattr(dart, "urlopen", rec)
    return rec


def http_error(code: int) -> HTTPError:
    return HTTPError(
        "https://opendart.fss.or.kr/api/list.json", code, "Server Error", Message(), None
    )


# ── list.json 정상 ────────────────────────────────────────────────


def test_fetch_disclosures_parses_items(no_sleep: list[float], monkeypatch: Any) -> None:
    use(monkeypatch, Recorder(body("000", [item(), item("20260821000001", "주주총회소집결의")])))
    got = dart.fetch_disclosures(CORP, BGN, END)
    assert [d.report_nm for d in got] == ["전환사채권발행결정", "주주총회소집결의"]
    assert got[0].rcept_dt == date(2026, 8, 22)
    assert got[0].rcept_no == "20260822000123"
    assert got[0].flr_nm == "가비아"
    assert no_sleep == []  # 재시도 없음


def test_request_carries_the_expected_params(no_sleep: list[float], monkeypatch: Any) -> None:
    rec = use(monkeypatch, Recorder(body("000", [])))
    dart.fetch_disclosures(CORP, BGN, END)
    q = rec.query()
    assert q["corp_code"] == CORP
    assert q["bgn_de"] == "20260801"
    assert q["end_de"] == "20260902"
    assert q["crtfc_key"] == KEY


def test_corrected_is_left_to_the_domain(no_sleep: list[float], monkeypatch: Any) -> None:
    """수집층은 제목을 해석하지 않는다 — `[정정]` 판단은 `flags.classify()` 한 곳에서만 한다."""
    use(monkeypatch, Recorder(body("000", [item(report_nm="[기재정정]전환사채권발행결정")])))
    got = dart.fetch_disclosures(CORP, BGN, END)
    assert got[0].corrected is False
    assert got[0].report_nm == "[기재정정]전환사채권발행결정"  # 원문 그대로


# ── 013 — 오류가 아니다 ───────────────────────────────────────────


def test_013_is_zero_disclosures_not_an_error(no_sleep: list[float], monkeypatch: Any) -> None:
    """이걸 예외로 다루면 **공시 없는 종목이 통째로 빠진다** — 흔한 정상 상태다."""
    use(monkeypatch, Recorder(body("013")))
    assert dart.fetch_disclosures(CORP, BGN, END) == []
    assert no_sleep == []  # 재시도하지 않는다 — 다시 물어도 없다


def test_013_without_a_list_key_is_still_empty(no_sleep: list[float], monkeypatch: Any) -> None:
    """`013`은 `list` 키 자체를 안 준다 — KeyError로 터지면 안 된다."""
    raw = '{"status":"013","message":"조회된 데이터가 없습니다."}'.encode()
    use(monkeypatch, Recorder(raw))
    assert dart.fetch_disclosures(CORP, BGN, END) == []


# ── 020 — 한도 초과 ───────────────────────────────────────────────


def test_020_retries_once_then_raises_rate_limit(no_sleep: list[float], monkeypatch: Any) -> None:
    rec = use(monkeypatch, Recorder(body("020"), body("020")))
    with pytest.raises(DartRateLimitError) as e:
        dart.fetch_disclosures(CORP, BGN, END)
    assert e.value.status == "020"
    assert len(rec.urls) == 2
    assert no_sleep == [dart.RETRY_WAIT]


def test_020_that_clears_on_retry_succeeds(no_sleep: list[float], monkeypatch: Any) -> None:
    """일시적 한도라면 두 번째에 답이 온다 — 한 번은 기다려 준다."""
    use(monkeypatch, Recorder(body("020"), body("000", [item()])))
    assert len(dart.fetch_disclosures(CORP, BGN, END)) == 1


def test_rate_limit_is_a_dart_error(no_sleep: list[float], monkeypatch: Any) -> None:
    """호출자가 `DartError` 하나로 잡아도 새지 않는다 (F34)."""
    assert issubclass(DartRateLimitError, DartError)
    assert issubclass(DartMaintenanceError, DartError)


# ── 그 밖의 재시도 ────────────────────────────────────────────────


def test_800_retries_once_then_raises_maintenance(no_sleep: list[float], monkeypatch: Any) -> None:
    """점검은 HTTP 200으로 온다 — 본문을 봐야 안다."""
    rec = use(monkeypatch, Recorder(body("800"), body("800")))
    with pytest.raises(DartMaintenanceError):
        dart.fetch_disclosures(CORP, BGN, END)
    assert len(rec.urls) == 2


def test_5xx_retries_once_then_raises(no_sleep: list[float], monkeypatch: Any) -> None:
    rec = use(monkeypatch, Recorder(http_error(503), http_error(503)))
    with pytest.raises(DartError, match="503"):
        dart.fetch_disclosures(CORP, BGN, END)
    assert len(rec.urls) == 2


def test_timeout_retries_once_then_raises(no_sleep: list[float], monkeypatch: Any) -> None:
    rec = use(monkeypatch, Recorder(TimeoutError("timed out"), TimeoutError("timed out")))
    with pytest.raises(DartError):
        dart.fetch_disclosures(CORP, BGN, END)
    assert len(rec.urls) == 2


def test_connection_error_then_success(no_sleep: list[float], monkeypatch: Any) -> None:
    use(monkeypatch, Recorder(URLError("연결 거부"), body("000", [item()])))
    assert len(dart.fetch_disclosures(CORP, BGN, END)) == 1
    assert no_sleep == [dart.RETRY_WAIT]


def test_key_error_does_not_retry(no_sleep: list[float], monkeypatch: Any) -> None:
    """`010`(키 없음)·`011`(키 만료)은 다시 불러도 같다 — 44종목이면 44번 헛수고다."""
    rec = use(monkeypatch, Recorder(body("010")))
    with pytest.raises(DartError) as e:
        dart.fetch_disclosures(CORP, BGN, END)
    assert e.value.status == "010"
    assert len(rec.urls) == 1
    assert no_sleep == []


def test_retry_is_not_limited_to_list_json(no_sleep: list[float], monkeypatch: Any) -> None:
    """상태 재시도는 **응답 본문으로** 판단한다 — 경로 이름으로 하면 새 끝점이 조용히 빠진다.

    M2의 `dart_fin.py`가 `fnlttMultiAcnt.json`을 부른다.
    """
    rec = use(monkeypatch, Recorder(body("020"), body("000", cnt=1)))
    payload = dart.get_json("fnlttMultiAcnt.json", {"corp_code": CORP})
    assert payload["cnt"] == 1
    assert len(rec.urls) == 2
    assert "fnlttMultiAcnt.json" in rec.urls[0]


# ── 키 마스킹 (N10) — 규율이 아니라 장치 ───────────────────────────


def test_constructing_a_dart_error_masks_the_key(monkeypatch: Any) -> None:
    """이것이 장치다 — 예외를 만드는 것만으로 가려진다. 부르는 쪽이 잊어도 새지 않는다."""
    monkeypatch.setenv("DART_API_KEY", KEY)
    exc = DartError(f"list.json?crtfc_key={KEY}&corp_code={CORP} 실패")
    assert KEY not in str(exc)
    assert "***" in str(exc)


def test_masking_survives_subclasses(monkeypatch: Any) -> None:
    monkeypatch.setenv("DART_API_KEY", KEY)
    for cls in (DartRateLimitError, DartMaintenanceError):
        assert KEY not in str(cls(f"…crtfc_key={KEY}…"))


def test_masking_does_nothing_without_a_key(monkeypatch: Any) -> None:
    """키가 없을 때 `***`로 문장을 망치지 않는다."""
    monkeypatch.delenv("DART_API_KEY", raising=False)
    assert str(DartError("list.json 실패")) == "list.json 실패"


@pytest.mark.parametrize(
    "outcome",
    [
        http_error(500),
        URLError("[SSL] certificate verify failed"),
        TimeoutError("timed out"),
        OSError("broken pipe"),
    ],
)
def test_no_failure_path_leaks_the_key(
    no_sleep: list[float], monkeypatch: Any, capsys: Any, outcome: BaseException
) -> None:
    """네트워크 실패 네 갈래 — 예외 메시지와 stdout 어디에도 키가 없어야 한다."""
    use(monkeypatch, Recorder(outcome, outcome))
    with pytest.raises(DartError) as e:
        dart.fetch_disclosures(CORP, BGN, END)
    assert KEY not in str(e.value)
    assert KEY not in capsys.readouterr().out


def test_status_error_message_never_leaks_the_key(
    no_sleep: list[float], monkeypatch: Any, capsys: Any
) -> None:
    """DART가 오류 메시지에 키를 되비추는 경우 — 실제로 그런 응답이 있다."""
    use(monkeypatch, Recorder(body("011", message=f"인증키가 만료되었습니다: {KEY}")))
    with pytest.raises(DartError) as e:
        dart.fetch_disclosures(CORP, BGN, END)
    assert KEY not in str(e.value)
    assert KEY not in capsys.readouterr().out


def test_retry_log_never_leaks_the_key(
    no_sleep: list[float], monkeypatch: Any, capsys: Any
) -> None:
    use(monkeypatch, Recorder(body("020"), body("000", [])))
    dart.fetch_disclosures(CORP, BGN, END)
    assert KEY not in capsys.readouterr().out


def test_mask_helper() -> None:
    assert dart.mask(f"a{KEY}b", KEY) == "a***b"
    assert dart.mask("변화 없음", "") == "변화 없음"


# ── 100건 절단 ────────────────────────────────────────────────────


def test_warns_when_more_than_one_page_exists(
    no_sleep: list[float], monkeypatch: Any, capsys: Any
) -> None:
    """조용히 자르면 빠진 공시를 아무도 모른다."""
    use(monkeypatch, Recorder(body("000", [item()], total_count=137)))
    dart.fetch_disclosures(CORP, BGN, END)
    out = capsys.readouterr().out
    assert "137" in out and str(dart.PAGE_COUNT) in out


# ── corpCode.xml ──────────────────────────────────────────────────


def test_fetch_corp_codes_returns_raw_bytes(no_sleep: list[float], monkeypatch: Any) -> None:
    """zip을 그대로 넘긴다 — 파싱과 오류 본문 판별은 순수 모듈 `corp.py`가 한다."""
    use(monkeypatch, Recorder(b"PK\x03\x04rest-of-zip"))
    assert dart.fetch_corp_codes() == b"PK\x03\x04rest-of-zip"


def test_fetch_corp_codes_retries_on_network_error(no_sleep: list[float], monkeypatch: Any) -> None:
    rec = use(monkeypatch, Recorder(URLError("끊김"), b"PK\x03\x04"))
    assert dart.fetch_corp_codes() == b"PK\x03\x04"
    assert len(rec.urls) == 2


def test_zip_bytes_do_not_trip_the_status_retry(
    no_sleep: list[float], monkeypatch: Any
) -> None:
    """상태 판단이 JSON 파싱에 기대므로, zip은 조용히 통과해야 한다."""
    rec = use(monkeypatch, Recorder(b"PK\x03\x04\x14\x00status020"))
    dart.fetch_corp_codes()
    assert len(rec.urls) == 1


def test_missing_key_fails_fast(monkeypatch: Any) -> None:
    monkeypatch.delenv("DART_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="DART_API_KEY"):
        dart.fetch_disclosures(CORP, BGN, END)


# ── 매핑은 한 곳 (REST ↔ MCP 공용) ────────────────────────────────


def test_from_dart_item_is_the_shared_mapping() -> None:
    """`dart_mcp.py`가 같은 함수를 쓴다 — 두 경로가 다른 Disclosure를 만들면 판정이 갈린다."""
    d = Disclosure.from_dart_item(item())
    assert (d.rcept_dt, d.rcept_no, d.report_nm) == (
        date(2026, 8, 22), "20260822000123", "전환사채권발행결정"
    )


def test_from_dart_item_accepts_dashed_dates() -> None:
    """MCP 경로는 `2026-08-22`로 준다 (선행 실측)."""
    assert Disclosure.from_dart_item(item(rcept_dt="2026-08-22")).rcept_dt == date(2026, 8, 22)


def test_from_dart_item_trims_whitespace() -> None:
    raw = {**item(), "report_nm": "  전환사채권발행결정 ", "flr_nm": " 가비아 "}
    d = Disclosure.from_dart_item(raw)
    assert d.report_nm == "전환사채권발행결정"
    assert d.flr_nm == "가비아"
