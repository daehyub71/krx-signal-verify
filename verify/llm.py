"""Claude 호출 — 근거 서술 (F11). **있으면 좋은 층이다.** I/O 층.

판정과 점수는 코드가 이미 냈다 (F10). LLM은 **왜 그런지를 말로 풀 뿐**이고,
`stand`·`score`를 바꾸지 못한다. 그래서 죽어도 배치는 끝까지 간다 —
`summary_error`를 남기고 「⚠ 서술 생략」을 붙인다 (F34).

## 거부를 `content`보다 먼저 본다

Claude는 정책 거부를 **HTTP 200**으로 준다: `stop_reason == "refusal"`에
`stop_details.category`가 실려 온다. `content`를 먼저 읽으면 빈 응답을
「할 말이 없었다」로 오해하고 그날 서술이 조용히 빈다.

**서버 쪽 폴백을 켜 둔다** — 정책 거부가 났을 때 다른 판이 같은 요청을 이어받는다.
`fallbacks="default"`는 거부 사유에 맞춰 알아서 고르므로 모델 목록을 우리가 관리하지 않는다.
그래도 사슬 전체가 거부하면 `stop_reason`이 `refusal`로 남고, 그때는 생략한다.

## 도구를 주지 않는다 (N5)

그래프 어디에서도 LLM이 도구를 굴리지 않는다. 무엇을 어떤 순서로 부를지는 코드가 정하고,
LLM에는 **이미 모아 놓은 사실**만 JSON으로 준다 — 세라고 시키지 않고 세어서 준다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from verify import analysis, config

# 판을 바꾸면 서술이 달라진다 — 고정한다. 바꿀 때는 표본 몇 건을 눈으로 대조한다.
MODEL = "claude-opus-5"

# 잘리면 마지막 종목의 서술이 통째로 사라진다. 하루 44종목 × 몇 줄이면 넉넉하다.
MAX_TOKENS = 16000

# 정책 거부를 다른 판이 이어받게 한다. `"default"`는 사유에 맞춰 알아서 고른다 —
# 모델 목록을 우리가 관리하지 않아도 된다.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass(frozen=True, slots=True)
class Summary:
    """서술 결과. **실패해도 예외가 아니라 이것으로 돌아온다** (F34)."""

    text: str = ""
    error: str = ""


def _client() -> Any:
    """SDK 클라이언트. 키가 없으면 여기서 걸린다."""
    import anthropic

    return anthropic.Anthropic(api_key=config.require("ANTHROPIC_API_KEY"))


def _text_of(reply: Any) -> str:
    """본문 블록만 이어 붙인다. 생각 블록 등이 섞여 와도 본문만 모은다."""
    return "".join(
        b.text for b in (reply.content or []) if getattr(b, "type", "text") == "text"
    ).strip()


def summarize(items: list[dict[str, Any]], *, client: Any = None) -> Summary:
    """근거 서술을 받아 온다 (F11). **하루 1회 일괄.**

    Args:
        items: `analysis.build_input()`이 만든 것. 이미 세어 놓은 사실만 들어 있다.
        client: SDK 클라이언트 (테스트가 대역을 넣는다).

    Returns:
        `Summary`. **실패는 예외가 아니라 `error`로 돌아온다** — 판정·점수는 이미 저장됐고
        메일도 나가야 한다 (F34).
    """
    if not items:
        return Summary()  # 빈 호출도 돈이 든다
    try:
        api = client or _client()
        reply = api.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=analysis.SYSTEM_PROMPT,
            messages=[{"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
            betas=[FALLBACK_BETA],
            fallbacks="default",
            # ⚠ **JSON을 부탁하지 않고 강제한다.** 프롬프트만으로는 마크다운 보고서가 왔다 —
            # 2026-09-05 첫 실발송에서 서술 15건이 전부 「응답이 JSON이 아니다」로 버려졌다.
            output_config={"format": {"type": "json_schema", "schema": analysis.OUTPUT_SCHEMA}},
        )
    except Exception as exc:  # noqa: BLE001 — 있으면 좋은 층이다 (F34)
        return Summary(error=f"{type(exc).__name__}: {exc}")

    # ⚠ **content보다 먼저 본다.** 거부는 HTTP 200으로 오고, 본문이 있을 수도 있다.
    if getattr(reply, "stop_reason", "") == "refusal":
        d = getattr(reply, "stop_details", None)
        why = getattr(d, "category", "") or "사유 없음"
        return Summary(error=f"refusal: {why}")
    return Summary(text=_text_of(reply))
