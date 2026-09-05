"""dart_fin — `fnlttMultiAcnt.json`을 REST로 직접 (F30·F30b). MCP에 다중회사 도구가 없다.

계약 테스트는 실제 응답 표본(`tests/fixtures/dart_multiacnt.json`)으로 한다 (N14).

지키는 것:
  · **보고서 하강 탐색** (F30b) — 미제출 분기를 부르면 `013`이 온다(2026-09-05 실측).
    값이 온 것을 쓰고 **어느 보고서였는지 함께 남긴다** — 종목마다 기준 시점이 다르다
  · **아직 못 찾은 회사만 다음 단계로 가져간다** — 배치 전체를 한 보고서로 묶으면
    결산월이 다른 회사가 조용히 빈다
  · **응답이 요청한 회사를 다 담았는지 센다** — 조용한 절단은 그 종목의 재무 갈래를
    「없는 것」으로 만들고, 아무도 모른다
  · 계정 해석은 여기서 하지 않는다 — `financial.py`(F30·F31)의 일이다
"""

from __future__ import annotations

import json
import pathlib
from datetime import date
from typing import Any

import pytest

from verify import dart, dart_fin

FIX = pathlib.Path(__file__).parent / "fixtures"
SAMPLE: dict[str, Any] = json.loads((FIX / "dart_multiacnt.json").read_text(encoding="utf-8"))

GEN = "00104768"  # 일반 회사 (000500)
FIN = "00104856"  # 금융사 (016360 삼성증권)
TODAY = date(2026, 9, 5)


def only(*corps: str) -> dict[str, Any]:
    """표본에서 그 회사들만 남긴 응답."""
    items = [x for x in SAMPLE["list"] if x["corp_code"] in corps]
    return {"status": "000", "message": "정상", "list": items}


NO_DATA = {"status": "013", "message": "조회된 데이타가 없습니다."}


class Recorder:
    """`dart.get_json` 대역. 부른 인자를 적고 준비된 응답을 순서대로 돌려준다."""

    def __init__(self, *outcomes: Any) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, str]] = []

    def __call__(self, path: str, params: dict[str, str]) -> Any:
        self.calls.append({"path": path, **params})
        out = self.outcomes.pop(0) if self.outcomes else NO_DATA
        if isinstance(out, BaseException):
            raise out
        return out

    def corps(self, i: int) -> list[str]:
        return self.calls[i]["corp_code"].split(",")


# ── 보고서 하강 탐색 (F30b) ───────────────────────────────────────


def test_descent_order_is_newest_first() -> None:
    """`11014`(3분기) → `11012`(반기) → `11013`(1분기) → 전년 `11011`(사업보고서)."""
    got = dart_fin.report_descent(TODAY)
    assert got[:4] == [
        ("2026", "11014"),
        ("2026", "11012"),
        ("2026", "11013"),
        ("2025", "11011"),
    ]


def test_descent_covers_january(  ) -> None:
    """1월에는 당해 분기도 전년 사업보고서도 아직 없다 — 전년 3분기가 마지막 방어선이다.

    2027-01-15에 F30b 네 단계만 돌면 **전부 013**이라 재무 갈래가 두 달간 통째로 빈다
    (2026-09-05 확인). 그래서 전년 분기까지 내려간다.
    """
    got = dart_fin.report_descent(date(2027, 1, 15))
    assert ("2026", "11011") in got  # 아직 미제출일 수 있다
    assert ("2026", "11014") in got  # 이것은 제출돼 있다
    assert got.index(("2026", "11011")) < got.index(("2026", "11014"))


def test_a_not_yet_filed_quarter_moves_to_the_next_report() -> None:
    """미제출은 `013`으로 온다 — 오류가 아니다 (2026-09-05 실측)."""
    rec = Recorder(NO_DATA, only(GEN))
    got = dart_fin.fetch_accounts([GEN], TODAY, fetch=rec)
    assert len(rec.calls) == 2
    assert rec.calls[0]["reprt_code"] == "11014"
    assert rec.calls[1]["reprt_code"] == "11012"
    assert got[GEN].report == ("2026", "11012")


def test_the_report_used_is_recorded_per_company() -> None:
    """**종목마다 기준 시점이 다를 수 있다** — 근거에 함께 적어야 한다 (F30b)."""
    rec = Recorder(only(GEN), only(FIN))
    got = dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=rec)
    assert got[GEN].report == ("2026", "11014")
    assert got[FIN].report == ("2026", "11012")


@pytest.mark.parametrize(
    ("report", "label"),
    [
        (("2026", "11014"), "2026년 3분기보고서"),
        (("2026", "11012"), "2026년 반기보고서"),
        (("2026", "11013"), "2026년 1분기보고서"),
        (("2025", "11011"), "2025년 사업보고서"),
    ],
)
def test_report_label_is_readable(report: tuple[str, str], label: str) -> None:
    """근거에 그대로 실린다 — 종목마다 기준 시점이 달라서 사람이 읽고 알아야 한다 (F30b)."""
    assert dart_fin.Accounts(corp_code=GEN, report=report).report_label == label


def test_report_label_survives_an_unknown_code() -> None:
    """모르는 코드를 만나도 빈 말을 하지 않는다 — 코드라도 보여 준다."""
    assert "11099" in dart_fin.Accounts(corp_code=GEN, report=("2026", "11099")).report_label


def test_only_the_missing_companies_go_to_the_next_step() -> None:
    """배치를 통째로 다음 보고서로 넘기면 이미 찾은 회사를 또 부른다 — 그리고 덮어쓴다."""
    rec = Recorder(only(GEN), only(FIN))
    dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=rec)
    assert rec.corps(0) == [GEN, FIN]
    assert rec.corps(1) == [FIN]  # GEN은 이미 찾았다


def test_descent_stops_once_everyone_is_found() -> None:
    rec = Recorder(only(GEN, FIN))
    dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=rec)
    assert len(rec.calls) == 1


def test_a_company_never_found_is_absent_not_empty() -> None:
    """빈 것을 만들어 넣으면 「재무가 0이었다」로 읽힌다 — 빠져야 「생략」으로 표기된다 (F34)."""
    got = dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=Recorder(only(GEN)))
    assert GEN in got
    assert FIN not in got


# ── 15개씩 나눠 보낸다 ────────────────────────────────────────────


def test_requests_are_chunked() -> None:
    corps = [f"{i:08d}" for i in range(1, 45)]  # 44종목
    rec = Recorder(*[NO_DATA] * 20)
    dart_fin.fetch_accounts(corps, TODAY, fetch=rec)
    first_round = [
        c for c in rec.calls if (c["bsns_year"], c["reprt_code"]) == ("2026", "11014")
    ]
    assert len(first_round) == 3  # 44 ÷ 15 → 3회
    assert [len(c["corp_code"].split(",")) for c in first_round] == [15, 15, 14]


def test_chunk_size_is_the_measured_one() -> None:
    assert dart_fin.CHUNK == 15


def test_no_corp_codes_means_no_call() -> None:
    rec = Recorder()
    assert dart_fin.fetch_accounts([], TODAY, fetch=rec) == {}
    assert rec.calls == []


# ── 조용한 절단을 잡는다 ──────────────────────────────────────────


def test_a_company_found_nowhere_is_reported_once() -> None:
    """어느 보고서에서도 못 찾은 회사 — 재무 갈래가 비는 종목이다 (F34가 「생략」으로 적는다)."""
    rec = Recorder(only(GEN))  # GEN만 오고 FIN은 끝까지 안 온다
    missing: list[str] = []
    dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=rec, on_missing=missing.extend)
    assert missing == [FIN]


def test_the_descent_itself_is_not_reported_as_missing() -> None:
    """**정상 실행이 울면 안 된다.** 라운드마다 알리던 첫 판은 44종목 실측에서
    절단 0건인데 44건을 통보했다 — 하강 탐색은 단계마다 대부분이 안 오는 것이 정상이다
    (실측 분포: 3분기 1개 · 반기 42개 · 1분기 1개).
    """
    rec = Recorder(only(GEN), only(FIN))  # 각각 다른 단계에서 찾는다
    missing: list[str] = []
    got = dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=rec, on_missing=missing.extend)
    assert set(got) == {GEN, FIN}
    assert missing == []


def test_nothing_is_reported_when_everyone_arrives() -> None:
    missing: list[str] = []
    rec = Recorder(only(GEN, FIN))
    dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=rec, on_missing=missing.extend)
    assert missing == []


# ── 응답을 회사별로 나눈다 ────────────────────────────────────────


def test_items_are_grouped_by_company() -> None:
    got = dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=Recorder(only(GEN, FIN)))
    assert {x["corp_code"] for x in got[GEN].items} == {GEN}
    assert {x["corp_code"] for x in got[FIN].items} == {FIN}
    assert len(got[GEN].items) + len(got[FIN].items) == len(SAMPLE["list"])


def test_accounts_are_handed_over_unread() -> None:
    """계정 해석은 `financial.py`의 일이다 — 여기서 이름을 고르거나 고치지 않는다."""
    got = dart_fin.fetch_accounts([FIN], TODAY, fetch=Recorder(only(FIN)))
    names = {x["account_nm"] for x in got[FIN].items}
    assert "순이자손익" in names  # 금융사 계정이 그대로 넘어온다
    assert "매출액" not in names  # 금융사에는 없다 — 지어내지 않는다


def test_both_consolidated_and_separate_statements_come_through() -> None:
    """같은 계정이 `CFS`(연결)·`OFS`(개별)로 두 번 온다 — 고르는 것은 도메인의 일이다."""
    got = dart_fin.fetch_accounts([GEN], TODAY, fetch=Recorder(only(GEN)))
    assert {x["fs_div"] for x in got[GEN].items} == {"CFS", "OFS"}


# ── 실패 ──────────────────────────────────────────────────────────


def test_a_rate_limit_stops_the_whole_descent() -> None:
    """`020`이면 다음 보고서를 불러 봐야 같은 답이다 — 4단계 × 3청크를 헛돌지 않는다."""
    rec = Recorder(dart.DartRateLimitError("한도 초과", "020"))
    with pytest.raises(dart.DartRateLimitError):
        dart_fin.fetch_accounts([GEN, FIN], TODAY, fetch=rec)
    assert len(rec.calls) == 1


def test_the_endpoint_and_params_are_what_dart_expects() -> None:
    rec = Recorder(only(GEN))
    dart_fin.fetch_accounts([GEN], TODAY, fetch=rec)
    call = rec.calls[0]
    assert call["path"] == "fnlttMultiAcnt.json"
    assert set(call) == {"path", "corp_code", "bsns_year", "reprt_code"}
