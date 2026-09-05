"""메일 본문 (F50·N9·N1·N3). **순수 함수.**

**간략하게 보낸다.** 판정·점수·근거 발췌 + 대시보드 링크. 전문은 웹으로 유도한다.

## 접지 않는 넷

접기(`<details>`)를 쓰되 **판정·점수·공시·한계 문구는 어느 단계에서도 접지 않는다** (F50).
접힌 것은 읽히지 않고, 그 넷이 안 읽히면 이 메일이 존재할 이유가 없다.

## 예산 (N9)

**102,400 bytes.** 넘으면 Gmail이 잘라내는데, **잘리는 곳이 꼬리라 한계 문구가 먼저 사라진다.**
선행 첫 판이 149,971 bytes로 실제 절단됐다. 그래서 두 가지를 한다:

1. **한계 문구를 앞쪽에 둔다** — 잘려도 남게
2. **우리가 먼저 줄인다** — 넘칠 것 같으면 종목 수를 줄이고 **줄였다고 적는다.**
   조용히 줄이면 「그날은 3종목뿐이었나」로 읽힌다

크기는 **실제 `EmailMessage`로 잰다** (`notify.build_message`). HTML 문자열 길이가 아니다 —
헤더와 인코딩이 더해진다.
"""

from __future__ import annotations

import html as _html
import re
from collections.abc import Sequence
from datetime import date
from typing import Any

MAX_BYTES = 102_400

# 한 통에 실을 종목 수 상한. 넘으면 줄이고 그렇다고 적는다.
MAX_ITEMS = 40

# 인용문(공시·뉴스 제목)은 우리 문장이 아니다 — 금지어 검사에서 뺀다.
_QUOTED = re.compile(r'<span class="q">.*?</span>|「.*?」', re.S)


def strip_quoted(body: str) -> str:
    """인용 부분을 뺀 **우리 문장만**. 금지어 검사는 이것으로 한다 (N1)."""
    return _QUOTED.sub(" ", body)


def subject(d: date, n: int) -> str:
    """메일 제목. **`[검증]`을 붙인다** — 병행 기간에 선행 `[브리핑]`과 섞이면 안 된다 (R11)."""
    day = d.strftime("%m-%d")
    return f"[검증] {day} 검증 없음" if n == 0 else f"[검증] {day} {n}종목"


def _q(text: str) -> str:
    """인용 — 공시·뉴스 제목 원문. 금지어 검사에서 빠진다."""
    return f'<span class="q">{_html.escape(text)}</span>'


def _limit_note(items: Sequence[Any]) -> str:
    """한계 문구. **앞쪽에 둔다** — 잘려도 남게 (N9)."""
    for _, v, _, _ in items:
        return _html.escape(v.limit_note)
    return "이 점수는 신호의 근거가 받쳐지는지를 재며, 앞으로의 주가를 말하지 않는다"


def _one(sig: Any, v: Any, ev: Any, summary: str) -> str:
    """종목 한 칸. **판정·점수·공시는 접기 밖에 둔다.**"""
    parts = " · ".join(f"{p.label} {p.delta:+d}" for p in v.parts)
    lines = [
        f"<h3>{_html.escape(sig.name)} ({sig.ticker})</h3>",
        f"<p><b>{v.stand} {v.score}점</b>{' · ' + _html.escape(parts) if parts else ''}</p>",
    ]
    for d in ev.disclosures or ():
        lines.append(f'<p>{_q(d.report_nm)} · <a href="{d.link}">DART 원문</a></p>')
    lines.append(
        f"<p>{_html.escape(summary)}</p>" if summary else "<p>⚠ 서술 생략</p>"
    )
    return "\n".join(lines)


def html(d: date, items: Sequence[Any], url: str) -> str:
    """메일 본문 (HTML). 예산을 넘칠 것 같으면 **줄이고 줄였다고 적는다.**"""
    shown, cut = list(items)[:MAX_ITEMS], max(0, len(items) - MAX_ITEMS)
    head = [
        f"<h2>{d.isoformat()} 신호 검증</h2>",
        f"<p><i>{_limit_note(items)}</i></p>",  # 앞쪽에 둔다 — 잘려도 남게
        f'<p><a href="{_html.escape(url)}">전문 보기</a></p>',
    ]
    if not shown:
        head.append("<p>그날 검증할 신호가 없었다.</p>")
    if cut:
        head.append(f"<p>{cut}종목은 메일에서 생략했다 — 전문 보기에서 볼 수 있다.</p>")
    return "\n".join(head + [_one(*x) for x in shown])


def text(d: date, items: Sequence[Any], url: str) -> str:
    """메일 본문 (평문). HTML을 못 보는 곳을 위한 것이라 더 짧다."""
    shown = list(items)[:MAX_ITEMS]
    out = [f"{d.isoformat()} 신호 검증", _limit_note(items), url, ""]
    for sig, v, _, summary in shown:
        out.append(f"{sig.name}({sig.ticker}) {v.stand} {v.score}점 — {summary or '서술 생략'}")
    if len(items) > MAX_ITEMS:
        out.append(f"{len(items) - MAX_ITEMS}종목 생략")
    return "\n".join(out)
