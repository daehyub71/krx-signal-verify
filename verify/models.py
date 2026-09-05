"""도메인 모델 — 아무것도 import하지 않는다 (표준 라이브러리만).

읽는 쪽(`ksa_signals`)과 쓰는 쪽(`ksv_*`)이 여기서 만난다.
**`evidence`는 우리가 통제하지 않는 계약이다** (SPEC R12 · 상위 PLAN §4 — 우리는 네 번째 소비자).
상위가 키를 바꾸거나 값 모양을 바꿔도 **그 줄만 비고 나머지는 나가야 한다.**
"""

from __future__ import annotations

from collections.abc import Iterable
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

    @classmethod
    def from_dart_item(cls, item: dict[str, Any]) -> Disclosure:
        """OpenDART `list.json` 항목 → Disclosure. **REST와 MCP가 같은 매핑을 쓴다.**

        두 경로가 다른 Disclosure를 만들면 폴백이 일어난 날만 판정이 달라진다.

        `corrected`는 채우지 않는다 — 제목 해석은 `flags.classify()` 한 곳에서만 한다.

        Args:
            item: `rcept_dt`(`YYYYMMDD` 또는 `YYYY-MM-DD`) · `report_nm` · `rcept_no` ·
                `flr_nm` 키를 가진 사전. MCP 경로는 날짜에 하이픈을 넣어 준다(실측).
        """
        raw = str(item["rcept_dt"]).replace("-", "")
        return cls(
            rcept_dt=date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])),
            report_nm=str(item.get("report_nm", "")).strip(),
            rcept_no=str(item["rcept_no"]),
            flr_nm=str(item.get("flr_nm", "")).strip(),
        )

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
class NewsItem:
    """네이버 뉴스 한 건. 검색어 `{종목명}` + 관련도순 + 제목 필터를 거친 것만 담는다.

    **앞 글자가 한글이면 다른 회사다** — `아이텍`이 `위세아이텍` 안에서 잡혔다 (선행 실측).
    """

    title: str
    link: str
    published: date | None = None
    summary: str = ""
    source: str = ""


@dataclass(frozen=True, slots=True)
class EventBody:
    """플래그된 공시의 **본문**. `report_nm` 한 줄로는 무슨 일인지 알 수 없다.

    **`overhang_pct`가 이 모델의 핵심이다.** 같은 「전환사채 발행」이라도 잠재 물량이
    5.10%인지 18.63%인지는 전혀 다른 사실이다 (선행 2026-08-26 실측: 씨피시스템 vs 엔투텍).
    값이 없으면 `None` — 사채가 아닌 사건에는 전환가·오버행이 없다.
    """

    rcept_no: str
    event_type: str = ""
    amount: int | None = None
    use_of_funds: tuple[tuple[str, int], ...] = ()  # (용도, 금액) — 비어 있으면 미기재
    kind: str = ""
    method: str = ""  # 사모 / 공모
    coupon_rate: float | None = None
    conv_price: int | None = None
    overhang_pct: float | None = None  # 발행주식총수 대비 잠재 물량(%)
    outstanding: int | None = None
    refix_floor: int | None = None  # 전환가액 하향조정 하한(원)


@dataclass(frozen=True, slots=True)
class Anomaly:
    """공시 이상 점수 — **보조 신호다. 등급을 바꾸지 않는다.**"""

    score: int  # 0~100
    verdict: str  # clean / watch / warning / red_flag
    summary: str = ""
    flags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FlowDay:
    """하루치 투자자별 순매수거래대금(원) — 상위 `ksc_investor_flows` 한 행."""

    d: date
    inst: int | None = None  # 기관합계
    foreign: int | None = None  # 외국인 + 기타외국인 (상위는 따로 담는다)
    indiv: int | None = None


@dataclass(frozen=True, slots=True)
class Quote:
    """종목 하나의 시세·시총 참고 — 상위 `ksc_tickers` + `ksc_bars` (F12).

    **호출 0회, 키 0개.** 상위 `krx-stock-charts`가 매일 채워 둔 값을 SQL로 읽는다.

    없는 값은 `None`이다 — 신규 상장이나 오래 정지된 종목은 시총만 있고 일봉이 없다.
    `0`으로 채우면 「거래대금 0원」이라는 없는 사실이 생긴다.
    """

    ticker: str
    name: str = ""  # 뉴스 검색어이자 제목 필터의 기준 (news_mcp)
    market: str = ""  # KOSPI / KOSDAQ — M4가 소속 시장 지수를 고를 때 쓴다 (F23)
    mktcap: int | None = None
    list_shrs: int | None = None
    last_d: date | None = None  # 마지막 일봉 날짜
    close: int | None = None
    trdval: int | None = None  # 최근 `bar_days` 거래일 거래대금 합(원)
    bar_days: int = 0  # 실제로 센 일봉 수 — 창이 짧으면 여기가 작다


@dataclass(frozen=True, slots=True)
class InvestorFlows:
    """종목 하나의 수급 30일. 날짜 **오름차순**.

    합계는 **`None`을 0으로 세지 않는다** — 그 투자자 표에 종목이 없던 날과
    순매수가 0원이던 날은 다르다.
    """

    days: tuple[FlowDay, ...] = ()

    @staticmethod
    def _sum(values: Iterable[int | None]) -> int | None:
        got = [v for v in values if v is not None]
        return sum(got) if got else None

    @property
    def inst_total(self) -> int | None:
        """기간 누적 기관 순매수(원). 값이 하나도 없으면 `None`."""
        return self._sum(x.inst for x in self.days)

    @property
    def foreign_total(self) -> int | None:
        return self._sum(x.foreign for x in self.days)

    @property
    def indiv_total(self) -> int | None:
        return self._sum(x.indiv for x in self.days)

    def recent(self, n: int) -> InvestorFlows:
        """최근 n일만. 날짜 오름차순이므로 뒤에서 자른다."""
        return InvestorFlows(days=self.days[-n:] if n > 0 else ())

    def on(self, day: date) -> FlowDay | None:
        """그날 행. 없으면 `None`."""
        return next((x for x in self.days if x.d == day), None)


@dataclass(frozen=True, slots=True)
class VerdictInput:
    """`judge()`가 보는 것 **전부**. 산식이 무엇에 기대는지 여기 한눈에 보인다.

    `Evidence`를 그대로 받지 않는 이유: **산식을 증거 저장 형태와 떼어 놓기 위해서다.**
    저장 스키마가 바뀌어도 산식은 그대로여야 하고, 반대도 마찬가지다.
    """

    level: str = "none"  # flags.classify의 등급: red / amber / none / error / unknown
    flags: tuple[Flag, ...] = ()
    disclosures: tuple[Disclosure, ...] = ()
    bodies: tuple[EventBody, ...] = ()
    news: tuple[Any, ...] = ()  # judge는 **있는지 없는지만** 본다
    flows: InvestorFlows | None = None
    anomaly: Anomaly | None = None
    financial: object | None = None  # M2에서 채운다 (F30)
    shorting: object | None = None  # M2에서 채운다 (F32)
    window_days: int = 30


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
        """점수와 **항상 함께 나가는** 한 줄. 어느 표면에서도 접지 않는다.

        선행은 「공시 이후의 주가」를 사각지대로 적었다. 이 프로젝트는 그것을 보므로
        목록에서 뺐는데(F10b), **목록이 짧아진 만큼 읽는 사람은 점수를 더 믿게 된다.**
        그래서 빠진 자리에 **뒷문장을 세운다** — 사각지대를 나열하는 것만으로는
        「그럼 주가를 맞히는 점수인가」라는 오해를 막지 못한다 (R2).
        """
        return (
            "이 점수는 신호의 근거가 받쳐지는지를 재며, "
            + " · ".join(self.blind_spots)
            + "을 보지 않는다. 앞으로의 주가를 말하지 않는다"
        )


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

    # 공시 갈래에 딸린 것들 — **여섯째 갈래가 아니다.** 「생략」 표기는 다섯 개 그대로다.
    # 자리가 없으면 오버행 감산(F15)이 영원히 안 걸린다.
    bodies: Any = None
    anomaly: Any = None

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
