"""신호 검증 판정과 점수 — **도메인 층 · 순수 함수.**

선행 `krx-signal-briefing`에서 **테스트와 함께 이식**했다 (V11).
입력만 `VerdictInput`으로 바꿨다 — 산식을 증거 저장 형태와 떼어 놓기 위해서다.

**LLM에 숫자를 물으면 지어낸다.** 2026-08-30에 실제로 겪었다 — 플래그가 1건인 종목의
요약이 "위험 유형 2건"이라고 적었다. 그래서 판정과 점수는 여기서 규칙으로 낸다.
LLM(F19)은 이 결과를 **설명**할 뿐 바꾸지 못한다.

## 무엇을 재는가

상위가 보낸 차트 신호는 "지금 오르는 모양"이라고 말한다. 세 갈래 증거가 그 말을
받치는지, 거스르는지, 아무 말도 하지 않는지를 잰다.

| 판정 | 뜻 |
|------|-----|
| `정합` | 공시·뉴스·수급이 신호와 같은 방향이다 |
| `불일치` | 증거가 신호를 거스른다 (오버행·외국인 이탈 등) |
| `무관` | 증거가 신호에 대해 말이 없다 |

**점수는 종목의 좋고 나쁨이 아니다.** 신호의 *근거가 얼마나 받쳐지는가*다.
50이 중립이고, 근거가 받치면 오르고 거스르면 내린다.

## 반드시 함께 나가는 것 (R20)

점수는 사실보다 그럴듯해 보인다. 그래서 `Verdict.blind_spots`가 **무엇을 보지 않은
점수인지**를 항상 함께 돌려준다. 렌더는 이것을 접지 않는다 (F7b).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from verify.models import VerdictInput

NEUTRAL = 50
CORROBORATES_AT = 60  # 이상이면 정합
CONTRADICTS_AT = 40  # 이하면 불일치

STAND_CORROBORATES = "정합"
STAND_CONTRADICTS = "불일치"
STAND_SILENT = "무관"
STANDS = (STAND_CORROBORATES, STAND_CONTRADICTS, STAND_SILENT)

# 어떤 점수든 보지 않는 것들. **항상** 함께 적는다 (R20).
ALWAYS_BLIND: tuple[str, ...] = (
    "실적·밸류에이션",  # F30(재무)이 M2에서 일부 채운다. 채워지면 여기서 뺀다
    "업황",
    "시장 전체 흐름",
)
# ⚠ 「공시 이후의 주가」를 뺐다 (F10b) — **이제 우리가 그것을 본다** (F22~F24).
# 선행에는 이 줄이 있었다. 빠진 만큼 나머지를 더 분명히 적는다.

# 층이 빠졌을 때의 표기.
LAYER_BLIND: dict[str, str] = {
    "flows": "수급",
    "bodies": "공시 본문",
    "news": "뉴스",
    "anomaly": "공시 이상 점수",
    # 이 프로젝트에서 늘어난 두 갈래 (F30·F32). 가중치는 M2에서 정한다 —
    # **지금은 점수에 넣지 않고 「보지 않았다」고만 적는다.** 없는 근거를 만들지 않는다.
    "financial": "재무",
    "shorting": "공매도",
}

# 가중치. **여기 숫자를 바꾸면 테스트가 깨진다** — 산식은 테스트로 고정한다.
W_RED_FLAG = -8  # 🔴 하나당
W_AMBER_FLAG = -4  # 🟡 하나당
FLAG_FLOOR = -24  # 플래그 감산 하한 (건수가 많다고 무한히 내려가지 않는다)
W_OVERHANG_CAP = -25  # 오버행 감산 하한
W_REFIX = -5  # 시가하락 리픽싱 조항이 있으면
W_PRIVATE = -3  # 사모 발행이면
W_ANOMALY = {"warning": -6, "watch": -3, "red_flag": -10, "clean": 0}
W_FLOW_DAY = 6  # 플래그된 공시 당일 기관+외국인 순매수 방향
W_FLOW_30D = 8  # 30일 누적 기관+외국인 순매수 방향
W_NO_RISK = 10  # 확인된 위험 유형이 없음
W_NEWS_EXPLAINS = 3  # 위험 공시가 있는데 그것을 설명하는 뉴스가 있음


@dataclass(frozen=True, slots=True)
class Part:
    """점수 한 조각 — 무엇 때문에 얼마가 오르내렸는지."""

    label: str
    delta: int


@dataclass(frozen=True, slots=True)
class Verdict:
    """판정 결과 (F18). `stand`·`score`는 코드가 정하고 LLM이 바꾸지 못한다."""

    stand: str  # 정합 / 불일치 / 무관
    score: int  # 0~100. 50이 중립
    parts: tuple[Part, ...] = ()
    blind_spots: tuple[str, ...] = ()

    @property
    def limit_note(self) -> str:
        """점수와 **항상 함께 나가는** 한 줄 (R20)."""
        return "이 점수는 신호의 근거를 재며, " + " · ".join(self.blind_spots) + "을 보지 않는다"


def _clamp(v: int) -> int:
    return max(0, min(100, v))


def _flag_parts(inp: VerdictInput) -> list[Part]:
    """플래그 감산. 건수가 많아도 하한에서 멈춘다."""
    reds = sum(1 for f in inp.flags if f.level == "red")
    ambers = sum(1 for f in inp.flags if f.level == "amber")
    if not reds and not ambers:
        return []
    raw = reds * W_RED_FLAG + ambers * W_AMBER_FLAG
    return [Part(f"위험 유형 🔴{reds} 🟡{ambers}", max(FLAG_FLOOR, raw))]


def _body_parts(inp: VerdictInput) -> list[Part]:
    """공시 본문에서 오는 감산 — 오버행이 가장 크다.

    같은 "전환사채 발행"이라도 잠재 물량이 5.10%인지 18.63%인지는 전혀 다른 사실이다
    (2026-08-26 실측: 씨피시스템 vs 엔투텍).
    """
    out: list[Part] = []
    overhang = sum(x.overhang_pct or 0.0 for x in inp.bodies)
    if overhang > 0:
        out.append(Part(f"잠재 물량 {overhang:.2f}%", max(W_OVERHANG_CAP, -round(overhang))))
    if any(x.refix_floor is not None for x in inp.bodies):
        out.append(Part("시가하락 시 전환가 조정 조항", W_REFIX))
    if any("사모" in (x.method or "") for x in inp.bodies):
        out.append(Part("사모 발행", W_PRIVATE))
    return out


def _flow_parts(inp: VerdictInput, flag_days: set[date]) -> list[Part]:
    """수급 — 기관과 외국인을 합쳐 방향만 본다. 금액의 크기는 점수에 넣지 않는다."""
    if inp.flows is None or not inp.flows.days:
        return []
    out: list[Part] = []
    inst, foreign = inp.flows.inst_total, inp.flows.foreign_total
    total = sum(v for v in (inst, foreign) if v is not None)
    if inst is not None or foreign is not None:
        sign = 1 if total > 0 else -1 if total < 0 else 0
        if sign:
            word = "순매수" if sign > 0 else "순매도"
            out.append(Part(f"30일 기관·외국인 {word}", sign * W_FLOW_30D))
    for day in sorted(flag_days):
        row = inp.flows.on(day)
        if row is None:
            continue
        day_total = sum(v for v in (row.inst, row.foreign) if v is not None)
        if day_total:
            sign = 1 if day_total > 0 else -1
            word = "순매수" if sign > 0 else "순매도"
            out.append(
                Part(f"{day.month:02d}/{day.day:02d} 공시일 기관·외국인 {word}", sign * W_FLOW_DAY)
            )
    return out


def _blind_spots(inp: VerdictInput) -> tuple[str, ...]:
    """무엇을 못 보고 낸 점수인가 (R20). 빠진 층을 앞에 둔다."""
    missing = []
    # 이 프로젝트에서 늘어난 두 갈래. 가중치는 M2에서 정한다 —
    # **지금은 점수에 넣지 않고 「보지 않았다」고만 적는다.** 없는 근거를 만들지 않는다.
    if inp.financial is None:
        missing.append(LAYER_BLIND["financial"])
    if inp.shorting is None:
        missing.append(LAYER_BLIND["shorting"])
    if inp.flows is None or not inp.flows.days:
        missing.append(LAYER_BLIND["flows"])
    if inp.flags and not inp.bodies:
        missing.append(LAYER_BLIND["bodies"])
    if not inp.news:
        missing.append(LAYER_BLIND["news"])
    if inp.anomaly is None:
        missing.append(LAYER_BLIND["anomaly"])
    return (*missing, *ALWAYS_BLIND)


def judge(inp: VerdictInput) -> Verdict:
    """신호 하나를 판정한다 (F10).

    Args:
        inp: 공시·본문·뉴스·수급이 채워진 입력.

    Returns:
        판정·점수·근거 조각·사각지대. **증거가 하나도 없으면 `무관`에 중립 점수**다 —
        모르는 것을 낮은 점수로 바꾸지 않는다.
    """
    if inp.level in ("error", "unknown"):
        return Verdict(STAND_SILENT, NEUTRAL, (), _blind_spots(inp))

    flagged_nos = {f.rcept_no for f in inp.flags}
    flag_days = {d.rcept_dt for d in inp.disclosures if d.rcept_no in flagged_nos}
    parts: list[Part] = []
    parts.extend(_flag_parts(inp))
    parts.extend(_body_parts(inp))
    parts.extend(_flow_parts(inp, flag_days))
    if inp.anomaly is not None and (w := W_ANOMALY.get(inp.anomaly.verdict, 0)):
        parts.append(Part(f"공시 이상 {inp.anomaly.verdict}", w))
    if not inp.flags and inp.disclosures:
        parts.append(Part(f"최근 {inp.window_days}일 확인된 위험 유형 없음", W_NO_RISK))
    if inp.flags and inp.news:
        parts.append(Part("공시를 설명하는 뉴스 있음", W_NEWS_EXPLAINS))

    score = _clamp(NEUTRAL + sum(p.delta for p in parts))
    if not parts:
        stand = STAND_SILENT
    elif score >= CORROBORATES_AT:
        stand = STAND_CORROBORATES
    elif score <= CONTRADICTS_AT:
        stand = STAND_CONTRADICTS
    else:
        stand = STAND_SILENT
    return Verdict(stand, score, tuple(parts), _blind_spots(inp))
