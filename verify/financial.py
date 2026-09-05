"""주요계정 원본 → 사실 몇 줄 (F30·F31). **순수 함수. I/O 없음.**

`dart_fin.Accounts`를 받아 **표시할 사실만** 낸다: 매출·영업이익·당기순이익의 전기 대비,
부채비율, 이익잉여금 부호. **밸류에이션(PER·PBR)은 계산하지 않는다** — 시총은 있지만
주식 수·지배주주지분 처리가 업종마다 달라 잘못 쓰기 쉽다 (F30).

## 못 찾으면 비운다 — 그리고 그렇다고 적는다 (F31·R7)

보험사·증권사에는 **`매출액`이 아예 없다** (2026-09-05 실측: 신호 44종목 중 5개).
`순이자손익`을 그 자리에 넣는 것이 **억지 매핑**이고 SPEC이 금지한다. 비우고 `absent`에
이름을 남긴 뒤, 표준 밖 계정은 **제 이름 그대로** `extra`에 싣는다.

**업종을 판정하지 않는다.** 「고유 계정이 있으면 금융사」로 봤다가 44종목 실측에서
**아세아제지(종이·목재)가 금융사로 잡혔다** — `차입부채`는 제조업도 쓴다. 계정 이름으로
업종을 추측하는 것이 R7이 막는 일이다. 매출액이 없다는 **사실**만 적는다.

**표기 변형은 억지 매핑이 아니다.** `영업이익`과 `영업이익(손실)`은 같은 계정의 두 표기이고,
일반 회사도 `당기순이익(손실)`로 온다 (실측). 괄호 안 `(손실)`은 음수가 될 수 있다는 표시일 뿐이다.

## 연결과 개별을 섞지 않는다

같은 계정이 `CFS`(연결)·`OFS`(개별)로 **두 번** 온다. 연결을 먼저 쓰고 없으면 개별로 간다.
연결 손익과 개별 재무상태표를 한 표에 섞으면 부채비율이 **실재하지 않는 값**이 된다 —
고른 쪽에 없는 것은 비운다.

## 없는 숫자를 만들지 않는다

- 전기가 0이거나 음수면 증가율을 내지 않는다 — 적자에서 흑자로 간 것을 「-250% 성장」이라 할 수 없다
- **자본총계가 0 이하면 부채비율을 내지 않는다** — 음수 부채비율은 오해를 부른다 (자본잠식)
- `0`은 살리고 빈칸은 `None`이다 — 0원과 「기재 없음」은 다르다
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from verify.dart_fin import Accounts

# 계정 이름 정규화 — 괄호 주석과 공백을 뗀다.
_PAREN = re.compile(r"\([^)]*\)")
_WS = re.compile(r"\s+")

CONSOLIDATED, SEPARATE = "CFS", "OFS"
BASIS_NAME = {CONSOLIDATED: "연결", SEPARATE: "개별"}

REVENUE, OPERATING, NET = "매출액", "영업이익", "당기순이익"
LIABILITIES, EQUITY, RETAINED = "부채총계", "자본총계", "이익잉여금"
DEBT_RATIO = "부채비율"

# 표준 다섯 항목 밖의 계정들 (실측). 있으면 **제 이름 그대로** 싣는다 — 매출액 자리에 넣지 않는다.
#
# ⚠ **이 목록으로 업종을 판정하지 않는다.** 처음에는 「하나라도 있으면 금융사」로 봤는데,
# 44종목 실측에서 **아세아제지(종이·목재)가 금융사로 잡혔다** — `차입부채`는 제조업도 쓴다
# (2026-09-05). 계정 이름으로 업종을 추측하는 것이 바로 R7이 막는 일이다.
# 매출액이 없다는 **사실**만 `absent`에 적고, 왜 없는지는 진단하지 않는다.
EXTRA_ACCOUNTS = ("순이자손익", "순수수료손익", "예수부채", "차입부채")


def normalize(name: str) -> str:
    """계정 이름에서 괄호 주석과 공백을 뗀다. `영업이익(손실)` → `영업이익`."""
    return _WS.sub("", _PAREN.sub("", name))


def amount(raw: Any) -> int | None:
    """쉼표 낀 금액 → int. 빈칸·`-`·읽을 수 없는 값은 `None`. **`0`은 살린다.**"""
    try:
        return int(str(raw).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True, slots=True)
class Change:
    """한 계정의 당기와 전기. **증가율은 낼 수 있을 때만 낸다.**"""

    now: int
    prev: int | None = None
    period: str = ""  # 전기 이름 — `제 78 기반기`. 무엇과 견줬는지 사람이 봐야 한다

    @property
    def pct(self) -> float | None:
        """전기 대비 증가율(%). **전기가 없거나 0 이하면 `None`.**"""
        if self.prev is None or self.prev <= 0:
            return None
        return (self.now - self.prev) / self.prev * 100

    @property
    def turned_positive(self) -> bool:
        """적자에서 흑자로. 증가율 대신 이것이 사실이다."""
        return self.prev is not None and self.prev < 0 <= self.now


def change(now: int | None, prev: int | None, period: str) -> Change | None:
    """당기·전기 → Change. **당기가 없으면 사실이 없다** — `None`."""
    return None if now is None else Change(now=now, prev=prev, period=period)


@dataclass(frozen=True, slots=True)
class Financial:
    """한 회사의 재무 사실 (F30). 없는 것은 `None`이고 이름이 `absent`에 남는다."""

    report: str = ""  # `2026년 반기보고서` — 종목마다 기준 시점이 다르다 (F30b)
    basis: str = ""  # 연결 / 개별
    revenue: Change | None = None
    operating: Change | None = None
    net: Change | None = None
    debt_ratio: float | None = None
    retained: int | None = None
    absent: tuple[str, ...] = ()
    extra: tuple[tuple[str, Change], ...] = ()  # 표준 밖 계정 — 제 이름 그대로
    equity_wiped_out: bool = False  # 자본총계 0 이하 — 부채비율을 내지 않은 이유

    @property
    def has_revenue(self) -> bool:
        """매출액을 찾았는가. **업종을 말하지 않는다** — 못 찾았다는 사실만 말한다 (F31·R7)."""
        return self.revenue is not None

    @property
    def retained_is_deficit(self) -> bool:
        """이익잉여금이 음수인가 — 결손금이다."""
        return self.retained is not None and self.retained < 0

    def lines(self) -> tuple[str, ...]:
        """사람이 읽을 줄. **못 본 것도 적는다** — 줄이 사라지면 안 본 것과 구별되지 않는다."""
        out = [f"{self.report} 기준 ({self.basis})"] if self.report else []
        for label, c in (("매출액", self.revenue), ("영업이익", self.operating),
                         ("당기순이익", self.net), *self.extra):
            if c is None:
                continue
            if c.pct is not None:
                out.append(f"{label} {c.now:,}원 (전기 대비 {c.pct:+.1f}%)")
            elif c.turned_positive:
                out.append(f"{label} {c.now:,}원 (전기 {c.prev:,}원에서 흑자 전환)")
            else:
                out.append(f"{label} {c.now:,}원")
        if self.debt_ratio is not None:
            out.append(f"부채비율 {self.debt_ratio:.1f}%")
        if self.equity_wiped_out:
            out.append("자본총계가 0 이하여서 부채비율을 내지 않았다")
        if self.retained is not None:
            kind = "결손금" if self.retained_is_deficit else "이익잉여금"
            out.append(f"{kind} {abs(self.retained):,}원")
        if self.absent:
            out.append(f"이 보고서에 {' · '.join(self.absent)}이(가) 없다")
        return tuple(out)


def _pick(items: Sequence[dict[str, Any]], basis: str) -> dict[str, dict[str, Any]]:
    """한 기준(연결/개별)의 계정만 골라 `{정규화 이름: 항목}`. **먼저 온 것을 쓴다.**

    같은 계정이 `ord`만 다르게 두 번 오는 경우가 있다 (`당기순이익(손실)`, 실측).
    """
    out: dict[str, dict[str, Any]] = {}
    for item in sorted(items, key=lambda x: _ord(x)):
        if str(item.get("fs_div", "")) != basis:
            continue
        out.setdefault(normalize(str(item.get("account_nm", ""))), item)
    return out


def _ord(item: dict[str, Any]) -> int:
    try:
        return int(str(item.get("ord", "0")))
    except ValueError:
        return 0


def _change_of(rows: dict[str, dict[str, Any]], name: str) -> Change | None:
    item = rows.get(name)
    if item is None:
        return None
    return change(
        amount(item.get("thstrm_amount")),
        amount(item.get("frmtrm_amount")),
        str(item.get("frmtrm_nm", "")).strip(),
    )


def _value_of(rows: dict[str, dict[str, Any]], name: str) -> int | None:
    item = rows.get(name)
    return None if item is None else amount(item.get("thstrm_amount"))


def read(accounts: Accounts) -> Financial:
    """주요계정 원본 → 재무 사실 (F30·F31).

    Args:
        accounts: `dart_fin.fetch_accounts`가 준 한 회사분. 항목은 손대지 않은 원본이다.

    Returns:
        없는 것은 `None`이고 그 이름이 `absent`에 남는다. **0으로 채우지 않는다.**
    """
    rows = _pick(accounts.items, CONSOLIDATED)
    basis = CONSOLIDATED
    if not rows:
        rows, basis = _pick(accounts.items, SEPARATE), SEPARATE

    revenue = _change_of(rows, REVENUE)
    operating = _change_of(rows, OPERATING)
    net = _change_of(rows, NET)
    liabilities, equity = _value_of(rows, LIABILITIES), _value_of(rows, EQUITY)
    retained = _value_of(rows, RETAINED)

    wiped = equity is not None and equity <= 0
    ratio = None if (liabilities is None or equity is None or wiped) else liabilities / equity * 100

    extra = tuple(
        (name, c)
        for name in EXTRA_ACCOUNTS
        if (c := _change_of(rows, name)) is not None
    )

    absent = tuple(
        name
        for name, got in (
            (REVENUE, revenue), (OPERATING, operating), (NET, net),
            (DEBT_RATIO, ratio), (RETAINED, retained),
        )
        if got is None
    )
    return Financial(
        report=accounts.report_label,
        basis=BASIS_NAME.get(basis, basis),
        revenue=revenue,
        operating=operating,
        net=net,
        debt_ratio=ratio,
        retained=retained,
        absent=absent,
        extra=extra,
        equity_wiped_out=wiped,
    )


def read_all(by_corp: dict[str, Accounts]) -> dict[str, Financial]:
    """회사별로 한 번에. 빈 것은 만들지 않는다 — 안 들어온 회사는 애초에 없다 (F34)."""
    return {corp: read(acc) for corp, acc in by_corp.items()}


def absent_names(items: Iterable[Financial]) -> tuple[str, ...]:
    """여러 회사에서 비었던 항목 이름 (로그용). 무엇이 자주 비는지 보려는 것이다."""
    return tuple(sorted({name for f in items for name in f.absent}))
