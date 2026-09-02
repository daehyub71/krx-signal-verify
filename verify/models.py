"""도메인 모델 — 아무것도 import하지 않는다 (표준 라이브러리만).

읽는 쪽(`ksa_signals`)과 쓰는 쪽(`ksv_*`)이 여기서 만난다.
**`evidence`는 우리가 통제하지 않는 계약이다** (SPEC R12 · 상위 PLAN §4 — 우리는 네 번째 소비자).
상위가 키를 바꾸거나 값 모양을 바꿔도 **그 줄만 비고 나머지는 나가야 한다.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="

STANDS = ("정합", "불일치", "무관")
HORIZONS = (5, 20, 60)
EVIDENCE_LANES = ("공시", "뉴스", "수급", "재무", "공매도")


def dart_link(rcept_no: str) -> str:
    """접수번호 → DART 원문 뷰어 링크. **모든 공시 항목에 필수** (SPEC N3)."""
    return f"{DART_VIEWER}{rcept_no}"


def _as_int(v: Any) -> int:
    """숫자로 읽히면 int, 아니면 0 (R12). `int("8,420")`은 예외를 던진다."""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(v: Any) -> float:
    """숫자로 읽히면 float, 아니면 0.0 (R12). `float("+1.8%")`도 예외다."""
    try:
        return float(v or 0.0)
    except (TypeError, ValueError):
        return 0.0


# ── 읽는 쪽 — ksa_signals ────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SignalRow:
    """`ksa_signals` 한 행 중 검증이 쓰는 것.

    실제로 왔던 모양들: `evidence`가 통째로 `null` · 종가가 `"8,420"`(쉼표 낀 문자열) ·
    `conditions`가 목록이 아닌 문자열 · 조건 항목에 `label`이 없음.

    **`evidence`를 직접 `.get()`으로 파헤치지 말고 아래 프로퍼티를 쓴다** —
    직접 읽으면 그날 판정이 통째로 사라진다.
    """

    d: date
    strategy: str
    ticker: str  # 숫자가 아니다. `0126Z0`이 실재한다
    name: str
    evidence: Any = None

    @property
    def ev(self) -> dict[str, Any]:
        """`evidence`를 딕셔너리로 본다. DB가 `null`을 주는 날이 있다."""
        return self.evidence if isinstance(self.evidence, dict) else {}

    @property
    def conditions(self) -> tuple[tuple[str, bool, str], ...]:
        """(label, ok, actual). 목록이 아니면 빈 튜플, 키가 없으면 **그 자리만** 빈다."""
        raw = self.ev.get("conditions")
        if not isinstance(raw, list):
            return ()
        return tuple(
            (str(c.get("label", "")), bool(c.get("ok", False)), str(c.get("actual", "")))
            for c in raw
            if isinstance(c, dict)
        )

    @property
    def _price(self) -> dict[str, Any]:
        p = self.ev.get("price")
        return p if isinstance(p, dict) else {}

    @property
    def close(self) -> int:
        """종가(원). 숫자로 안 읽히면 0 — 그 줄만 빈다."""
        return _as_int(self._price.get("close"))

    @property
    def change_pct(self) -> float:
        """등락률(%). 숫자로 안 읽히면 0.0."""
        return _as_float(self._price.get("change_pct"))

    @property
    def in_progress(self) -> bool:
        """진행 중인 주봉 기준 판정인가 (상위 F8 표기)."""
        meta = self.ev.get("meta")
        return bool(meta.get("in_progress", False)) if isinstance(meta, dict) else False


# ── 공시 (M1 이식) ───────────────────────────────────────────────

FlagLevel = Literal["red", "amber"]


@dataclass(frozen=True, slots=True)
class Disclosure:
    """공시 하나. OpenDART `list.json` 한 항목."""

    rcept_dt: date
    report_nm: str
    rcept_no: str
    flr_nm: str = ""
    corrected: bool = False  # `[정정]`·`[기재정정]` 접두가 있었는가

    @property
    def link(self) -> str:
        """DART 원문 링크. **모든 공시 항목에 필수** (N3)."""
        return dart_link(self.rcept_no)


@dataclass(frozen=True, slots=True)
class Flag:
    """등급을 올린 공시 하나 — 「몇 점」이 아니라 **「어떤 공시 때문인지」**를 남긴다."""

    rule: str
    level: FlagLevel
    rcept_no: str
    report_nm: str


@dataclass(frozen=True, slots=True)
class Insider:
    """임원·주요주주 매매 군집 (korean-dart-mcp `insider_signal`). 실물 연결은 M2."""

    signal: str  # strong_sell_cluster / sell_cluster / buy_cluster / none …
    buy_events: int = 0
    sell_events: int = 0
    unique_buyers: int = 0
    unique_sellers: int = 0
    net_change_shares: int = 0
    summary: str = ""

    @property
    def sell_cluster(self) -> bool:
        """매도 군집인가. **매수 군집은 플래그가 아니다** — 참고 표시만."""
        return "sell_cluster" in self.signal


@dataclass(frozen=True, slots=True)
class UpstreamRun:
    """상위 `ksa_runs` 한 행 — 게이트가 보는 것 (F1).

    **상위도 스스로 `stale_data`로 끝내는 날이 있다** (2026-08-30·08-31 실측:
    `data_date=2026-08-27`로 사흘 낡은 채 돌았다). 그 판단을 우리가 다시 하지 않고 그대로 받는다.
    """

    run_at: datetime
    data_date: date | None
    status: str
    signals: int


# ── 판정 — 코드가 낸다. LLM은 바꾸지 못한다 (F10) ────────────────


@dataclass(frozen=True, slots=True)
class VerdictPart:
    """점수 한 조각 — 무엇 때문에 얼마가 오르내렸는지."""

    label: str
    delta: int


@dataclass(frozen=True, slots=True)
class Verdict:
    """판정 결과. `stand`·`score`는 코드가 정하고 **LLM이 바꾸지 못한다**.

    Raises:
        ValueError: `stand`가 정합/불일치/무관이 아닐 때. 「호재」 같은 말이 새어
            들어오는 것을 여기서 막는다 (N1).
    """

    stand: str
    score: int
    parts: tuple[VerdictPart, ...] = ()
    blind_spots: tuple[str, ...] = ()
    rules_version: str = ""

    def __post_init__(self) -> None:
        if self.stand not in STANDS:
            raise ValueError(f"stand는 {STANDS} 중 하나여야 한다: {self.stand!r}")
        object.__setattr__(self, "score", max(0, min(100, self.score)))

    @property
    def delta_total(self) -> int:
        """구성 요소의 합. **점수를 여기서 다시 계산하지 않는다** — 대조용이다."""
        return sum(p.delta for p in self.parts)

    @property
    def limit_note(self) -> str:
        """점수와 **항상 함께 나가는** 한 줄.

        점수는 사실보다 그럴듯해 보인다. 「공시 이후의 주가」는 이제 우리가 보므로
        목록에서 빠지고, 그만큼 **나머지를 더 분명히** 적는다 (F10b).
        """
        return "이 점수는 신호의 근거를 재며, " + " · ".join(self.blind_spots) + "을 보지 않는다"


# ── 적중 추적 — 기준선은 소속 시장 지수 하나뿐이다 (V12) ─────────


@dataclass(frozen=True, slots=True)
class Outcome:
    """판정일로부터 5·20·60거래일 뒤의 수익률과 같은 구간 지수 수익률.

    **미도래 구간은 `None`이다.** 0으로 두면 「초과수익 0%」로 읽힌다 (F22).
    지수가 없으면 초과수익도 `None`이다 — **프록시로 대신 재지 않는다** (F23b).
    `baseline` 열은 두지 않는다: 기준선이 하나뿐이라 기록할 것이 없다.
    """

    d: date
    ticker: str
    h5: float | None = None
    h20: float | None = None
    h60: float | None = None
    h5_index: float | None = None
    h20_index: float | None = None
    h60_index: float | None = None

    def is_filled(self, horizon: int) -> bool:
        """그 구간이 도래해 채워졌는가."""
        return getattr(self, f"h{horizon}") is not None

    def excess(self, horizon: int) -> float | None:
        """지수 대비 초과수익. **둘 중 하나라도 없으면 `None`** (F23b)."""
        stock: float | None = getattr(self, f"h{horizon}")
        index: float | None = getattr(self, f"h{horizon}_index")
        if stock is None or index is None:
            return None
        return stock - index


# ── 증거 다섯 갈래 — 없어도 되는 층이다 (F34) ────────────────────


@dataclass(frozen=True, slots=True)
class Evidence:
    """그날 그 종목의 증거. 실패한 갈래는 `None`으로 남고 **그 줄만 비운다**."""

    d: date
    ticker: str
    disclosures: Any = None
    news: Any = None
    flows: Any = None
    financial: Any = None
    shorting: Any = None

    def missing_lanes(self) -> tuple[str, ...]:
        """얻지 못한 갈래의 이름. 화면과 메일에 「생략」으로 표기한다."""
        got = (self.disclosures, self.news, self.flows, self.financial, self.shorting)
        return tuple(name for name, v in zip(EVIDENCE_LANES, got, strict=True) if v is None)


# ── 실행 기록 ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SendResult:
    """발송 결과. **예외를 밖으로 내지 않고 여기에 적는다** — raise하면 `record_run`에 못 간다."""

    ok: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class RunRecord:
    """실행 기록. **기본값이 실패다** — 기록이 없으면 성공으로 위장하지 않는다."""

    run_at: date
    status: str = "failed"
    gate: str = ""
    signals: int = 0
    verdicts: int = 0
    outcomes_filled: int = 0
    detail: dict[str, Any] = field(default_factory=dict)
