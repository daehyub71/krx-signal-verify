"""다중회사 주요계정 — `fnlttMultiAcnt.json`을 **REST로 직접** 부른다 (F30·F30b). I/O 층.

MCP에 다중회사 도구가 없다. 종목마다 한 번씩 부르면 44회인데, 이 끝점은 **여러 회사를
한 번에** 준다 — 15개씩 세 번이면 하루치가 끝난다.

**여기는 계정을 읽지 않는다.** 이름을 고르고 전기와 견주는 일은 `financial.py`(F30·F31)가 한다.
이 모듈은 「어느 보고서를 부를지 정하고, 받아서, 회사별로 나눠 준다」까지다.

## 보고서 하강 탐색 (F30b)

`bsns_year`·`reprt_code`를 요구하는데 **아직 제출되지 않은 분기를 부르면 `013`이 온다**
(2026-09-05 실측 — 오류가 아니라 「조회된 데이타가 없습니다」). 그래서 최신부터 내려가며
처음으로 값이 온 것을 쓰고, **어느 보고서였는지 함께 남긴다** — 결산월이 달라 종목마다
기준 시점이 다를 수 있다.

내려가는 중에는 **아직 못 찾은 회사만** 다음 단계로 가져간다. 배치를 통째로 넘기면
이미 찾은 회사를 다시 부르고 덮어쓴다.

## 못 찾은 회사는 **끝에서 한 번** 알린다

처음에는 라운드마다 「이번에 안 온 회사」를 알렸는데, 44종목 실측에서 **정상 실행이 44건을
통보했다** (2026-09-05). 하강 탐색은 원래 단계마다 대부분이 안 오는 것이 정상이라
— 3분기 1개 · 반기 42개 · 1분기 1개로 나뉘었다 — 그 신호는 매번 울고 아무것도 못 가린다.

그래서 **어느 보고서에서도 못 찾은 회사만** 끝에서 한 번 넘긴다. 그것이 실제로 재무 갈래가
비는 종목이고, F34가 「생략」으로 표기할 대상이다. 조용한 절단도 여기로 나타난다 —
청크를 `CHUNK`보다 키우지 않는 것이 절단에 대한 진짜 방어다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from verify import dart

ENDPOINT = "fnlttMultiAcnt.json"

# 한 회에 넘길 corp_code 수. 15개는 실측으로 확인했다 (2026-09-05: 15개 요청 → 15개 회사).
# 17개도 정상으로 왔지만 문서에 상한이 없어 **검증된 수를 쓴다** — 조용히 잘리면
# 그 종목들의 재무가 통째로 빈다. 44종목이면 3회다.
CHUNK = 15

# DART 보고서 코드.
Q3, HALF, Q1, ANNUAL = "11014", "11012", "11013", "11011"

Fetch = Callable[[str, dict[str, str]], Any]


@dataclass(frozen=True, slots=True)
class Accounts:
    """한 회사의 주요계정 원본 + **어느 보고서에서 왔는지**.

    항목은 손대지 않고 넘긴다 — `CFS`(연결)·`OFS`(개별)가 섞여 있고, 고르는 것은
    도메인의 일이다.
    """

    corp_code: str
    report: tuple[str, str]  # (bsns_year, reprt_code)
    items: tuple[dict[str, Any], ...] = ()

    @property
    def report_label(self) -> str:
        """근거에 적을 말. 「2026년 반기보고서」."""
        names = {Q3: "3분기보고서", HALF: "반기보고서", Q1: "1분기보고서", ANNUAL: "사업보고서"}
        year, code = self.report
        return f"{year}년 {names.get(code, code)}"


def report_descent(today: date) -> list[tuple[str, str]]:
    """최신부터 내려가는 `(bsns_year, reprt_code)` 순서 (F30b).

    당해년도 3분기 → 반기 → 1분기 → **전년 사업보고서**까지가 SPEC F30b다.
    거기에 **전년 분기**를 덧붙인다: 1월에는 당해 분기도 전년 사업보고서(3월 제출)도
    아직 없어 네 단계가 전부 `013`이고, 재무 갈래가 두 달간 통째로 빈다
    (2026-09-05 확인). 이미 제출된 전년 3분기가 마지막 방어선이다.

    Args:
        today: 기준일 (KST).

    Returns:
        위에서부터 시도할 순서. 앞이 최신이다.
    """
    y, prev = str(today.year), str(today.year - 1)
    return [
        (y, Q3), (y, HALF), (y, Q1),
        (prev, ANNUAL),
        (prev, Q3), (prev, HALF), (prev, Q1),
    ]


def _chunks(items: Sequence[str], size: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def fetch_accounts(
    corp_codes: Sequence[str],
    today: date,
    *,
    fetch: Fetch | None = None,
    on_missing: Callable[[list[str]], None] | None = None,
) -> dict[str, Accounts]:
    """회사들의 최근 확정 보고서 주요계정 (F30·F30b).

    Args:
        corp_codes: DART 고유번호 8자리 목록.
        today: 기준일 — 하강 탐색의 출발점.
        fetch: `dart.get_json` 대역 (테스트가 넣는다).
        on_missing: **어느 보고서에서도 못 찾은** 회사를 끝에서 한 번 넘긴다.
            재무 갈래가 비는 종목이고, F34가 「생략」으로 표기한다. 라운드마다 알리면
            정상 실행에서도 매번 운다 (44종목 실측에서 44건).

    Returns:
        `{corp_code: Accounts}`. **어느 보고서에서도 못 찾은 회사는 빠진다** —
        빈 것을 만들어 넣으면 「재무가 0이었다」로 읽힌다 (F34).

    Raises:
        dart.DartRateLimitError: `020`. 다음 보고서를 불러도 같은 답이라 **바로 멈춘다** —
            4단계 × 3청크를 헛돌지 않는다.
        dart.DartError: 그 밖의 오류 상태·네트워크 오류.
    """
    get = fetch or dart.get_json
    out: dict[str, Accounts] = {}
    pending = list(corp_codes)
    for year, code in report_descent(today):
        if not pending:
            break  # 조기 종료일 뿐이다 — 빈 목록이면 청크가 안 생겨 호출도 없다
                   # (변이 검사로 확인: 지워도 관측 차이가 없다, 2026-09-05)
        found = _round(get, pending, year, code)
        out.update(found)
        pending = [c for c in pending if c not in found]
    if on_missing and pending:
        on_missing(pending)
    return out


def _round(get: Fetch, corp_codes: Sequence[str], year: str, code: str) -> dict[str, Accounts]:
    """보고서 하나를 청크로 나눠 부르고, 온 것을 회사별로 묶는다."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for chunk in _chunks(list(corp_codes), CHUNK):
        payload = get(ENDPOINT, {
            "corp_code": ",".join(chunk),
            "bsns_year": year,
            "reprt_code": code,
        })
        for item in payload.get("list") or ():
            if corp := str(item.get("corp_code", "")):
                grouped.setdefault(corp, []).append(item)
    return {
        corp: Accounts(corp_code=corp, report=(year, code), items=tuple(items))
        for corp, items in grouped.items()
    }
